#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
for _key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(_key, None)

import requests

_orig_request = requests.Session.request


def _no_proxy(self, method, url, **kwargs):
    kwargs["proxies"] = {"http": "", "https": ""}
    return _orig_request(self, method, url, **kwargs)


requests.Session.request = _no_proxy

from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.dlc.v20210125 import dlc_client, models


REGION = "ap-shanghai"
OUTPUT_DIR = Path("/Users/windwheel/.copaw/workspaces/platform_path_scan_output")


class DlcRunner:
    def __init__(self, secret_id: str | None, secret_key: str | None, max_wait: int = 300):
        if not secret_id or not secret_key:
            raise SystemExit("缺少 DLC_USER / DLC_PASSWORD 环境变量。")
        cred = credential.Credential(secret_id, secret_key)
        http_profile = HttpProfile()
        http_profile.endpoint = "dlc.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        self.client = dlc_client.DlcClient(cred, REGION, client_profile)
        self.max_wait = max_wait

    def exec_sql(self, sql: str, db: str = "data_ods") -> list[list[Any]]:
        task = models.Task()
        task.SparkSQLTask = {"SQL": base64.b64encode(sql.encode("utf-8")).decode("utf-8")}
        req = models.CreateTaskRequest()
        req.DatabaseName = db
        req.DataEngineName = "SparkSQL"
        req.Task = task
        resp = self.client.CreateTask(req)
        payload = json.loads(resp.to_json_string())
        task_id = payload.get("TaskId")
        if not task_id:
            raise RuntimeError(f"CreateTask 未返回 TaskId: {payload}")

        elapsed = 0
        while elapsed < self.max_wait:
            time.sleep(3)
            elapsed += 3
            req2 = models.DescribeTaskResultRequest()
            req2.TaskId = str(task_id)
            result = json.loads(self.client.DescribeTaskResult(req2).to_json_string())
            task_info = result.get("TaskInfo", result)
            state = task_info.get("State", "")
            if state == 2:
                result_set = task_info.get("ResultSet", "[]")
                if isinstance(result_set, str):
                    try:
                        return json.loads(base64.b64decode(result_set).decode("utf-8"))
                    except Exception:
                        return json.loads(result_set)
                return result_set or []
            if state == 3:
                raise RuntimeError(task_info.get("OutputMessage", "SQL failed"))
        raise TimeoutError(f"SQL 执行超时，等待了 {self.max_wait}s")


def enum_sql(topn: int) -> str:
    return f"""
SELECT
    CAST(content_type AS STRING) AS content_type,
    COUNT(*) AS row_cnt
FROM data_ods.ods_pic_for_up_new_backup
WHERE COALESCE(CAST(is_delete AS STRING), 'false') = 'false'
  AND content_type IS NOT NULL
  AND TRIM(CAST(content_type AS STRING)) <> ''
  AND CAST(content_type AS STRING) RLIKE '视频'
GROUP BY CAST(content_type AS STRING)
ORDER BY row_cnt DESC, content_type
LIMIT {topn}
""".strip()


def sample_sql(limit: int) -> str:
    return f"""
SELECT
    CAST(id AS STRING) AS file_id,
    CAST(content_type AS STRING) AS content_type,
    CAST(used_platform AS STRING) AS used_platform,
    CAST(spu AS STRING) AS spu,
    CAST(image_create_time AS STRING) AS image_create_time,
    CAST(image_modify_time AS STRING) AS image_modify_time,
    CAST(image_name AS STRING) AS image_name,
    replace(COALESCE(image_full_path, ''), '\\\\', '/') AS image_full_path
FROM data_ods.ods_pic_for_up_new_backup
WHERE COALESCE(CAST(is_delete AS STRING), 'false') = 'false'
  AND content_type IS NOT NULL
  AND TRIM(CAST(content_type AS STRING)) <> ''
  AND CAST(content_type AS STRING) RLIKE '视频'
ORDER BY image_modify_time DESC
LIMIT {limit}
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="抽查 ods_pic_for_up_new_backup 中 content_type 含视频的枚举和值样本。")
    parser.add_argument("--topn", type=int, default=20, help="枚举 TopN")
    parser.add_argument("--sample-limit", type=int, default=20, help="样本行数")
    parser.add_argument("--max-wait", type=int, default=180, help="DLC 最大等待秒数")
    args = parser.parse_args()

    runner = DlcRunner(os.getenv("DLC_USER"), os.getenv("DLC_PASSWORD"), max_wait=args.max_wait)
    enum_rows = runner.exec_sql(enum_sql(args.topn))
    sample_rows = runner.exec_sql(sample_sql(args.sample_limit))

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "content_type_distribution": [
            {"content_type": row[0], "row_cnt": row[1]} for row in enum_rows
        ],
        "samples": [
            {
                "file_id": row[0],
                "content_type": row[1],
                "used_platform": row[2],
                "spu": row[3],
                "image_create_time": row[4],
                "image_modify_time": row[5],
                "image_name": row[6],
                "image_full_path": row[7],
            }
            for row in sample_rows
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"pic-backup-video-content-type-probe-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Output written to: {out_path}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
