#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from collections import Counter, defaultdict
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
TARGET_SQL = Path("/Users/windwheel/.copaw/workspaces/sample-table01.sql")
OUTPUT_DIR = Path("/Users/windwheel/.copaw/workspaces/platform_path_scan_output")

KNOWN_PLATFORM_PATTERNS = {
    "天猫": [r"天猫"],
    "淘宝": [r"淘宝"],
    "唯品会": [r"唯品会", r"唯品"],
    "快手": [r"快手"],
    "拼多多": [r"拼多多", r"\bPDD\b"],
    "抖音": [r"抖音"],
    "京东": [r"京东", r"\bJD\b"],
    "小红书": [r"小红书"],
    "视频号": [r"视频号"],
    "得物": [r"得物"],
}

NON_PLATFORM_TERMS = [
    "商品内页",
    "详情图",
    "详情页",
    "主图",
    "白底图",
    "灰底图",
    "素材图",
    "配色图",
    "尺码图",
    "面料图",
    "内页图",
    "温馨提示",
    "选购图",
    "海报图",
    "场景图",
    "平铺图",
    "挂拍图",
    "细节图",
    "穿搭图",
    "官网主图",
]


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

    def exec_sql(self, sql: str, db: str) -> list[list[Any]]:
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


def get_cte_sql(sql_path: Path) -> str:
    raw_sql = sql_path.read_text(encoding="utf-8")
    marker = "insert overwrite table data_dwd.dwd_t_file_resource_id_test_001"
    pos = raw_sql.lower().find(marker)
    if pos < 0:
        raise SystemExit(f"未找到目标 insert 语句: {marker}")
    cte_sql = raw_sql[:pos].rstrip()
    return re.sub(r";\s*$", "", cte_sql, flags=re.S)


def build_ranked_probe_cte(sql_path: Path) -> str:
    cte_sql = get_cte_sql(sql_path)
    return f"""{cte_sql},
ranked_probe as (
    select
        file_type,
        file_id,
        platform,
        brand,
        create_time,
        full_path,
        concatenated_path,
        spu,
        picture_type,
        file_name,
        source_priority,
        order_time,
        row_number() over (
            partition by file_id
            order by source_priority asc, order_time desc, create_time desc, full_path desc
        ) as rn
    from resource_union
    where file_id is not null
      and trim(cast(file_id as string)) <> ''
)
""".strip()


def build_summary_sql(sql_path: Path) -> str:
    probe_cte = build_ranked_probe_cte(sql_path)
    return f"""{probe_cte}
select
    cast(source_priority as string) as source_priority,
    file_type,
    count(*) as total_rows,
    sum(case when platform is null or trim(cast(platform as string)) = '' then 1 else 0 end) as null_rows,
    round(
        100.0 * sum(case when platform is null or trim(cast(platform as string)) = '' then 1 else 0 end) / count(*),
        4
    ) as null_rate_pct
from ranked_probe
where rn = 1
group by cast(source_priority as string), file_type
order by source_priority, file_type
""".strip()


def build_null_sample_sql(sql_path: Path, limit: int) -> str:
    probe_cte = build_ranked_probe_cte(sql_path)
    return f"""{probe_cte}
select
    cast(source_priority as string) as source_priority,
    file_type,
    cast(file_id as string) as file_id,
    cast(platform as string) as platform,
    cast(brand as string) as brand,
    cast(spu as string) as spu,
    cast(picture_type as string) as picture_type,
    cast(file_name as string) as file_name,
    cast(create_time as string) as create_time,
    cast(full_path as string) as full_path,
    cast(concatenated_path as string) as concatenated_path
from ranked_probe
where rn = 1
  and (platform is null or trim(cast(platform as string)) = '')
order by source_priority asc, create_time desc, file_id desc
limit {limit}
""".strip()


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_path(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    text = text.replace("\\", "/")
    text = re.sub(r"/+", "/", text)
    return text.strip("/")


def split_segments(path_text: str) -> list[str]:
    return [seg.strip() for seg in path_text.split("/") if seg and seg.strip()]


def detect_known_platform(segment: str) -> str | None:
    for platform, patterns in KNOWN_PLATFORM_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, segment, flags=re.IGNORECASE):
                return platform
    return None


def classify_sample(row: dict[str, str]) -> tuple[str, str | None]:
    path = normalize_path(row.get("full_path") or row.get("concatenated_path"))
    if not path:
        return "NO_PATH", None

    segments = split_segments(path)
    if row.get("file_type") == "视频":
        if not segments:
            return "VIDEO_NO_PLATFORM_SEGMENT", None
        for seg in segments:
            if detect_known_platform(seg):
                return "VIDEO_PATH_HAS_PLATFORM_BUT_SQL_NOT_MINING", seg
        return "VIDEO_PATH_NO_PLATFORM_SEGMENT", segments[-1] if segments else None

    has_non_platform = False
    for seg in segments:
        if detect_known_platform(seg):
            return "IMAGE_PATH_HAS_PLATFORM_BUT_SQL_MISSED", seg
        if any(term in seg for term in NON_PLATFORM_TERMS):
            has_non_platform = True

    if has_non_platform:
        return "IMAGE_ONLY_CONTENT_SEGMENTS", None
    return "IMAGE_NO_PLATFORM_SEGMENT", segments[-1] if segments else None


def analyze_samples(rows: list[dict[str, str]]) -> dict[str, Any]:
    reason_counter = Counter()
    source_reason_counter: dict[str, Counter] = defaultdict(Counter)
    segment_counter = Counter()
    representative: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        reason, segment = classify_sample(row)
        reason_counter[reason] += 1
        source_reason_counter[row["source_priority"]][reason] += 1
        if segment:
            segment_counter[segment] += 1
        if len(representative[reason]) < 5:
            representative[reason].append(
                {
                    "file_id": row["file_id"],
                    "source_priority": row["source_priority"],
                    "file_type": row["file_type"],
                    "brand": row["brand"],
                    "spu": row["spu"],
                    "picture_type": row["picture_type"],
                    "file_name": row["file_name"],
                    "create_time": row["create_time"],
                    "full_path": row["full_path"],
                    "concatenated_path": row["concatenated_path"],
                }
            )

    return {
        "reason_distribution": reason_counter.most_common(),
        "reason_distribution_by_source_priority": {
            source: counter.most_common() for source, counter in source_reason_counter.items()
        },
        "top_suspicious_terminal_segments": segment_counter.most_common(20),
        "representative_samples": representative,
    }


def rows_to_dicts(rows: list[list[Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        result.append(
            {
                "source_priority": normalize_text(row[0]),
                "file_type": normalize_text(row[1]),
                "file_id": normalize_text(row[2]),
                "platform": normalize_text(row[3]),
                "brand": normalize_text(row[4]),
                "spu": normalize_text(row[5]),
                "picture_type": normalize_text(row[6]),
                "file_name": normalize_text(row[7]),
                "create_time": normalize_text(row[8]),
                "full_path": normalize_text(row[9]),
                "concatenated_path": normalize_text(row[10]),
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="诊断 sample-table01.sql 当前 platform 空值的来源与样本。")
    parser.add_argument("--db", default="data_dwd", help="DLC 执行库")
    parser.add_argument("--sample-limit", type=int, default=2000, help="抽样空值样本数")
    parser.add_argument("--max-wait", type=int, default=300, help="DLC 最大等待秒数")
    args = parser.parse_args()

    runner = DlcRunner(os.getenv("DLC_USER"), os.getenv("DLC_PASSWORD"), max_wait=args.max_wait)
    summary_rows = runner.exec_sql(build_summary_sql(TARGET_SQL), args.db)
    sample_rows = runner.exec_sql(build_null_sample_sql(TARGET_SQL, args.sample_limit), args.db)
    sample_dicts = rows_to_dicts(sample_rows)

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sql_file": str(TARGET_SQL),
        "summary_by_source": [
            {
                "source_priority": row[0],
                "file_type": row[1],
                "total_rows": row[2],
                "null_rows": row[3],
                "null_rate_pct": row[4],
            }
            for row in summary_rows
        ],
        "sample_limit": args.sample_limit,
        "sample_analysis": analyze_samples(sample_dicts),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"sample-table01-platform-null-diagnosis-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Output written to: {out_path}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
