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
PLATFORM_REGEX = "(唯品会|天猫|淘宝|快手|拼多多|抖音|京东|小红书|视频号|得物)"


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


def summary_queries() -> dict[str, str]:
    return {
        "video_source_summary": f"""
SELECT
    COUNT(*) AS total_rows,
    SUM(CASE WHEN platform IS NULL OR TRIM(CAST(platform AS STRING)) = '' THEN 1 ELSE 0 END) AS explicit_platform_null_rows,
    SUM(CASE
            WHEN (platform IS NULL OR TRIM(CAST(platform AS STRING)) = '')
             AND replace(COALESCE(folder_path, full_path, file_name, ''), '\\\\', '/') RLIKE '{PLATFORM_REGEX}'
            THEN 1 ELSE 0
        END) AS path_contains_platform_keyword_rows
FROM data_ods.ods_t_file_information
WHERE COALESCE(CAST(is_delete AS STRING), 'false') <> 'true'
  AND file_id IS NOT NULL
  AND TRIM(CAST(file_id AS STRING)) <> ''
""".strip(),
        "image_info_source_summary": f"""
SELECT
    COUNT(*) AS total_rows,
    SUM(
        CASE
            WHEN
                CASE
                    WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*抖音[^/]*(/|$)' THEN '抖音'
                    WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*天猫[^/]*(/|$)' THEN '天猫'
                    WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*唯品会[^/]*(/|$)' THEN '唯品会'
                    WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*快手[^/]*(/|$)' THEN '快手'
                    WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*拼多多[^/]*(/|$)' THEN '拼多多'
                    WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*淘宝[^/]*(/|$)' THEN '淘宝'
                    WHEN replace(COALESCE(business_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*淘宝[^/]*(/|$)' THEN '淘宝'
                    WHEN replace(COALESCE(full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*抖音[^/]*(/|$)' THEN '抖音'
                    WHEN platform RLIKE '抖音' THEN '抖音'
                    WHEN platform RLIKE '天猫' THEN '天猫'
                    WHEN platform RLIKE '淘宝' THEN '淘宝'
                    WHEN platform RLIKE '唯品会' THEN '唯品会'
                    WHEN platform RLIKE '快手' THEN '快手'
                    WHEN platform RLIKE '拼多多' THEN '拼多多'
                    ELSE NULL
                END IS NULL
            THEN 1 ELSE 0
        END
    ) AS resolved_platform_null_rows
FROM data_ods.ods_t_image_file_information
WHERE COALESCE(CAST(is_delete AS STRING), 'false') <> 'true'
  AND file_id IS NOT NULL
  AND TRIM(CAST(file_id AS STRING)) <> ''
""".strip(),
        "pic_backup_source_summary": f"""
SELECT
    COUNT(*) AS total_rows,
    SUM(
        CASE
            WHEN
                CASE
                    WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*唯品会[^/]*(/|$)' THEN '唯品会'
                    WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*天猫[^/]*(/|$)' THEN '天猫'
                    WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*淘宝[^/]*(/|$)' THEN '淘宝'
                    WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*快手[^/]*(/|$)' THEN '快手'
                    WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*拼多多[^/]*(/|$)' THEN '拼多多'
                    WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*抖音[^/]*(/|$)' THEN '抖音'
                    WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*京东[^/]*(/|$)' THEN '京东'
                    WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*小红书[^/]*(/|$)' THEN '小红书'
                    WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*视频号[^/]*(/|$)' THEN '视频号'
                    WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*得物[^/]*(/|$)' THEN '得物'
                    WHEN used_platform RLIKE '唯品会' THEN '唯品会'
                    WHEN used_platform RLIKE '天猫' THEN '天猫'
                    WHEN used_platform RLIKE '淘宝' THEN '淘宝'
                    WHEN used_platform RLIKE '快手' THEN '快手'
                    WHEN used_platform RLIKE '拼多多' THEN '拼多多'
                    WHEN used_platform RLIKE '抖音' THEN '抖音'
                    WHEN used_platform RLIKE '京东' THEN '京东'
                    WHEN used_platform RLIKE '小红书' THEN '小红书'
                    WHEN used_platform RLIKE '视频号' THEN '视频号'
                    WHEN used_platform RLIKE '得物' THEN '得物'
                    ELSE NULL
                END IS NULL
            THEN 1 ELSE 0
        END
    ) AS resolved_platform_null_rows
FROM data_ods.ods_pic_for_up_new_backup
WHERE COALESCE(CAST(is_delete AS STRING), 'false') = 'false'
  AND id IS NOT NULL
  AND TRIM(CAST(id AS STRING)) <> ''
""".strip(),
    }


def sample_queries(limit: int) -> dict[str, str]:
    return {
        "video_null_samples": f"""
SELECT
    CAST(file_id AS STRING) AS file_id,
    CAST(platform AS STRING) AS platform,
    CAST(store AS STRING) AS store,
    CAST(spu AS STRING) AS spu,
    CAST(create_time AS STRING) AS create_time,
    replace(COALESCE(folder_path, ''), '\\\\', '/') AS folder_path,
    replace(COALESCE(full_path, ''), '\\\\', '/') AS full_path
FROM data_ods.ods_t_file_information
WHERE COALESCE(CAST(is_delete AS STRING), 'false') <> 'true'
  AND file_id IS NOT NULL
  AND TRIM(CAST(file_id AS STRING)) <> ''
  AND (platform IS NULL OR TRIM(CAST(platform AS STRING)) = '')
ORDER BY create_time DESC
LIMIT {limit}
""".strip(),
        "image_info_null_samples": f"""
SELECT
    CAST(file_id AS STRING) AS file_id,
    CAST(platform AS STRING) AS platform,
    CAST(store AS STRING) AS store,
    CAST(spu AS STRING) AS spu,
    CAST(create_time AS STRING) AS create_time,
    replace(COALESCE(folder_path, ''), '\\\\', '/') AS folder_path,
    replace(COALESCE(business_path, ''), '\\\\', '/') AS business_path,
    replace(COALESCE(full_path, ''), '\\\\', '/') AS full_path,
    CAST(file_name AS STRING) AS file_name
FROM data_ods.ods_t_image_file_information
WHERE COALESCE(CAST(is_delete AS STRING), 'false') <> 'true'
  AND file_id IS NOT NULL
  AND TRIM(CAST(file_id AS STRING)) <> ''
  AND
    CASE
        WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*抖音[^/]*(/|$)' THEN '抖音'
        WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*天猫[^/]*(/|$)' THEN '天猫'
        WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*唯品会[^/]*(/|$)' THEN '唯品会'
        WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*快手[^/]*(/|$)' THEN '快手'
        WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*拼多多[^/]*(/|$)' THEN '拼多多'
        WHEN replace(COALESCE(folder_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*淘宝[^/]*(/|$)' THEN '淘宝'
        WHEN replace(COALESCE(business_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*淘宝[^/]*(/|$)' THEN '淘宝'
        WHEN replace(COALESCE(full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*抖音[^/]*(/|$)' THEN '抖音'
        WHEN platform RLIKE '抖音' THEN '抖音'
        WHEN platform RLIKE '天猫' THEN '天猫'
        WHEN platform RLIKE '淘宝' THEN '淘宝'
        WHEN platform RLIKE '唯品会' THEN '唯品会'
        WHEN platform RLIKE '快手' THEN '快手'
        WHEN platform RLIKE '拼多多' THEN '拼多多'
        ELSE NULL
    END IS NULL
ORDER BY create_time DESC
LIMIT {limit}
""".strip(),
        "pic_backup_null_samples": f"""
SELECT
    CAST(id AS STRING) AS file_id,
    CAST(used_platform AS STRING) AS used_platform,
    CAST(brand AS STRING) AS brand,
    CAST(spu AS STRING) AS spu,
    CAST(image_create_time AS STRING) AS create_time,
    CAST(content_type AS STRING) AS content_type,
    CAST(image_name AS STRING) AS image_name,
    replace(COALESCE(image_full_path, ''), '\\\\', '/') AS image_full_path
FROM data_ods.ods_pic_for_up_new_backup
WHERE COALESCE(CAST(is_delete AS STRING), 'false') = 'false'
  AND id IS NOT NULL
  AND TRIM(CAST(id AS STRING)) <> ''
  AND
    CASE
        WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*唯品会[^/]*(/|$)' THEN '唯品会'
        WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*天猫[^/]*(/|$)' THEN '天猫'
        WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*淘宝[^/]*(/|$)' THEN '淘宝'
        WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*快手[^/]*(/|$)' THEN '快手'
        WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*拼多多[^/]*(/|$)' THEN '拼多多'
        WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*抖音[^/]*(/|$)' THEN '抖音'
        WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*京东[^/]*(/|$)' THEN '京东'
        WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*小红书[^/]*(/|$)' THEN '小红书'
        WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*视频号[^/]*(/|$)' THEN '视频号'
        WHEN replace(COALESCE(image_full_path, ''), '\\\\', '/') RLIKE '(^|/)[^/]*得物[^/]*(/|$)' THEN '得物'
        WHEN used_platform RLIKE '唯品会' THEN '唯品会'
        WHEN used_platform RLIKE '天猫' THEN '天猫'
        WHEN used_platform RLIKE '淘宝' THEN '淘宝'
        WHEN used_platform RLIKE '快手' THEN '快手'
        WHEN used_platform RLIKE '拼多多' THEN '拼多多'
        WHEN used_platform RLIKE '抖音' THEN '抖音'
        WHEN used_platform RLIKE '京东' THEN '京东'
        WHEN used_platform RLIKE '小红书' THEN '小红书'
        WHEN used_platform RLIKE '视频号' THEN '视频号'
        WHEN used_platform RLIKE '得物' THEN '得物'
        ELSE NULL
    END IS NULL
ORDER BY image_create_time DESC
LIMIT {limit}
""".strip(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="按 ODS 基表拆解 platform 空值根因，并抽样代表 file_id。")
    parser.add_argument("--sample-limit", type=int, default=10, help="每类样本条数")
    parser.add_argument("--max-wait", type=int, default=180, help="DLC 最大等待秒数")
    parser.add_argument(
        "--mode",
        choices=["all", "summary", "samples"],
        default="all",
        help="all=汇总+样本；summary=只跑汇总；samples=只拉样本",
    )
    parser.add_argument(
        "--sample-query",
        choices=["all", "video_null_samples", "image_info_null_samples", "pic_backup_null_samples"],
        default="all",
        help="当 mode=samples 时，可指定只跑某一类样本",
    )
    args = parser.parse_args()

    runner = DlcRunner(os.getenv("DLC_USER"), os.getenv("DLC_PASSWORD"), max_wait=args.max_wait)

    payload: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_limit": args.sample_limit,
        "summaries": {},
        "samples": {},
    }

    if args.mode in ("all", "summary"):
        for name, sql in summary_queries().items():
            rows = runner.exec_sql(sql)
            payload["summaries"][name] = rows[0] if rows else []

    if args.mode in ("all", "samples"):
        queries = sample_queries(args.sample_limit)
        if args.sample_query != "all":
            queries = {args.sample_query: queries[args.sample_query]}
        for name, sql in queries.items():
            payload["samples"][name] = runner.exec_sql(sql)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"platform-null-root-cause-probe-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Output written to: {out_path}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
