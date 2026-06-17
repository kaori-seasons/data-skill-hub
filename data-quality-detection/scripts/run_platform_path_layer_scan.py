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
OUTPUT_DIR = Path("/Users/windwheel/.copaw/workspaces/platform_path_scan_output")

PLATFORM_PATTERNS = {
    "天猫": [r"天猫(?:主图|店铺|旗舰店|商城)?"],
    "淘宝": [r"淘宝(?:主图|店铺)?"],
    "唯品会": [r"唯品会(?:主图)?", r"唯品"],
    "快手": [r"快手(?:版|店铺|小店)?"],
    "拼多多": [r"拼多多(?:店铺|温馨提示)?", r"\bPDD\b"],
    "抖音": [r"抖音(?:店铺|小店)?", r"Douyin"],
    "京东": [r"京东(?:主图|店铺)?", r"JD"],
    "小红书": [r"小红书"],
    "视频号": [r"视频号"],
    "得物": [r"得物"],
    "唯品仓": [r"唯品仓"],
}

NON_PLATFORM_LABELS = [
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
    "小图",
]

PATH_FIELDS = {
    "ods_t_image_file_information": ["folder_path", "business_path", "full_path", "file_name"],
    "ods_pic_for_up_new_backup": ["image_full_path", "image_name"],
}


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


def canonicalize_platform(text: Any) -> str | None:
    raw = normalize_text(text)
    if not raw:
        return None
    for label in NON_PLATFORM_LABELS:
        if raw == label:
            return None
    for canonical, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, raw, flags=re.IGNORECASE):
                return canonical
    return None


def split_segments(path_text: str) -> list[str]:
    if not path_text:
        return []
    return [seg.strip() for seg in path_text.split("/") if seg and seg.strip()]


def analyze_segments(row: dict[str, Any], path_field: str) -> list[dict[str, Any]]:
    path_text = normalize_path(row.get(path_field))
    segments = split_segments(path_text)
    hits: list[dict[str, Any]] = []
    for idx, segment in enumerate(segments):
        canonical = canonicalize_platform(segment)
        if not canonical:
            continue
        hits.append(
            {
                "field": path_field,
                "canonical_platform": canonical,
                "segment": segment,
                "depth_from_root": idx + 1,
                "depth_from_leaf": len(segments) - idx,
                "is_filename": idx == len(segments) - 1,
                "path": path_text,
            }
        )
    return hits


def choose_best_hit(hits: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not hits:
        return None
    non_filename = [hit for hit in hits if not hit["is_filename"]]
    candidates = non_filename or hits
    candidates.sort(key=lambda x: (x["depth_from_leaf"], x["depth_from_root"]))
    return candidates[0]


def build_queries(limit: int) -> dict[str, str]:
    keyword_or = "|".join(
        sorted(
            {
                canonical
                for canonical in PLATFORM_PATTERNS
            }
            | set(NON_PLATFORM_LABELS)
        )
    )
    return {
        "ods_t_image_file_information": f"""
SELECT
    CAST(file_id AS STRING) AS resource_id,
    CAST(platform AS STRING) AS explicit_platform,
    replace(COALESCE(folder_path, ''), '\\\\', '/') AS folder_path,
    replace(COALESCE(business_path, ''), '\\\\', '/') AS business_path,
    replace(COALESCE(full_path, ''), '\\\\', '/') AS full_path,
    CAST(file_name AS STRING) AS file_name,
    CAST(data_update_time AS STRING) AS order_time
FROM data_ods.ods_t_image_file_information
WHERE file_id IS NOT NULL
  AND TRIM(CAST(file_id AS STRING)) <> ''
  AND (
        (platform IS NOT NULL AND TRIM(CAST(platform AS STRING)) <> '')
        OR replace(COALESCE(folder_path, business_path, full_path, file_name, ''), '\\\\', '/') RLIKE '{keyword_or}'
      )
ORDER BY data_update_time DESC
LIMIT {limit}
""".strip(),
        "ods_pic_for_up_new_backup": f"""
SELECT
    CAST(id AS STRING) AS resource_id,
    CAST(used_platform AS STRING) AS explicit_platform,
    replace(COALESCE(image_full_path, ''), '\\\\', '/') AS image_full_path,
    CAST(image_name AS STRING) AS image_name,
    CAST(content_type AS STRING) AS content_type,
    CAST(image_modify_time AS STRING) AS order_time
FROM data_ods.ods_pic_for_up_new_backup
WHERE id IS NOT NULL
  AND TRIM(CAST(id AS STRING)) <> ''
  AND (
        (used_platform IS NOT NULL AND TRIM(CAST(used_platform AS STRING)) <> '')
        OR replace(COALESCE(image_full_path, image_name, content_type, ''), '\\\\', '/') RLIKE '{keyword_or}'
      )
ORDER BY image_modify_time DESC
LIMIT {limit}
""".strip(),
    }


def rows_to_dicts(table: str, rows: list[list[Any]]) -> list[dict[str, Any]]:
    dicts: list[dict[str, Any]] = []
    if table == "ods_t_image_file_information":
        for row in rows:
            dicts.append(
                {
                    "resource_id": row[0],
                    "explicit_platform": row[1],
                    "folder_path": row[2],
                    "business_path": row[3],
                    "full_path": row[4],
                    "file_name": row[5],
                    "order_time": row[6],
                }
            )
    elif table == "ods_pic_for_up_new_backup":
        for row in rows:
            dicts.append(
                {
                    "resource_id": row[0],
                    "explicit_platform": row[1],
                    "image_full_path": row[2],
                    "image_name": row[3],
                    "content_type": row[4],
                    "order_time": row[5],
                }
            )
    return dicts


def analyze_table(table: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    explicit_counter = Counter()
    suspicious_explicit_counter = Counter()
    path_field_hits = Counter()
    field_platform_hits: dict[str, Counter] = defaultdict(Counter)
    root_depth_hits: dict[str, Counter] = defaultdict(Counter)
    leaf_depth_hits: dict[str, Counter] = defaultdict(Counter)
    segment_examples: dict[str, Counter] = defaultdict(Counter)
    consistency_counter = Counter()
    best_hit_samples: list[dict[str, Any]] = []

    for row in rows:
        explicit_raw = normalize_text(row.get("explicit_platform"))
        explicit_canonical = canonicalize_platform(explicit_raw)
        if explicit_raw:
            explicit_counter[explicit_raw] += 1
            if explicit_canonical is None:
                suspicious_explicit_counter[explicit_raw] += 1

        hits: list[dict[str, Any]] = []
        for field in PATH_FIELDS[table]:
            hits.extend(analyze_segments(row, field))

        best_hit = choose_best_hit(hits)
        if best_hit:
            path_field_hits[best_hit["field"]] += 1
            field_platform_hits[best_hit["field"]][best_hit["canonical_platform"]] += 1
            root_depth_hits[best_hit["canonical_platform"]][best_hit["depth_from_root"]] += 1
            leaf_depth_hits[best_hit["canonical_platform"]][best_hit["depth_from_leaf"]] += 1
            segment_examples[best_hit["canonical_platform"]][best_hit["segment"]] += 1
            if len(best_hit_samples) < 30:
                best_hit_samples.append(
                    {
                        "resource_id": row["resource_id"],
                        "explicit_platform": explicit_raw,
                        "path_field": best_hit["field"],
                        "canonical_platform": best_hit["canonical_platform"],
                        "segment": best_hit["segment"],
                        "depth_from_root": best_hit["depth_from_root"],
                        "depth_from_leaf": best_hit["depth_from_leaf"],
                        "path": best_hit["path"],
                    }
                )

        if explicit_raw and best_hit:
            if explicit_canonical == best_hit["canonical_platform"]:
                consistency_counter["explicit_match_path"] += 1
            elif explicit_canonical is None:
                consistency_counter["explicit_dirty_path_has_platform"] += 1
            else:
                consistency_counter["explicit_conflict_path"] += 1
        elif explicit_raw and not best_hit:
            if explicit_canonical is None:
                consistency_counter["explicit_dirty_no_path_hit"] += 1
            else:
                consistency_counter["explicit_only"] += 1
        elif not explicit_raw and best_hit:
            consistency_counter["path_only"] += 1
        else:
            consistency_counter["neither"] += 1

    recommendation = {
        "preferred_path_field": path_field_hits.most_common(1)[0][0] if path_field_hits else None,
        "preferred_root_depth_by_platform": {
            platform: depth_counter.most_common(1)[0][0]
            for platform, depth_counter in root_depth_hits.items()
            if depth_counter
        },
        "preferred_leaf_depth_by_platform": {
            platform: depth_counter.most_common(1)[0][0]
            for platform, depth_counter in leaf_depth_hits.items()
            if depth_counter
        },
    }

    return {
        "row_count": len(rows),
        "top_explicit_platform_values": explicit_counter.most_common(20),
        "top_suspicious_explicit_platform_values": suspicious_explicit_counter.most_common(20),
        "path_field_hit_distribution": path_field_hits.most_common(),
        "path_field_platform_distribution": {
            field: counter.most_common()
            for field, counter in field_platform_hits.items()
        },
        "root_depth_distribution": {
            platform: counter.most_common()
            for platform, counter in root_depth_hits.items()
        },
        "leaf_depth_distribution": {
            platform: counter.most_common()
            for platform, counter in leaf_depth_hits.items()
        },
        "segment_examples": {
            platform: counter.most_common(10)
            for platform, counter in segment_examples.items()
        },
        "consistency": dict(consistency_counter),
        "recommendation": recommendation,
        "sample_hits": best_hit_samples,
    }


def write_outputs(result: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    json_path = OUTPUT_DIR / f"platform-path-layer-scan-{timestamp}.json"
    md_path = OUTPUT_DIR / f"platform-path-layer-scan-{timestamp}.md"
    pattern_path = OUTPUT_DIR / "platform_path_patterns.json"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    pattern_payload = {
        "generated_at": result["generated_at"],
        "positive_patterns": PLATFORM_PATTERNS,
        "negative_labels": NON_PLATFORM_LABELS,
        "recommendations": {
            table: result["tables"][table]["recommendation"] for table in result["tables"]
        },
    }
    pattern_path.write_text(json.dumps(pattern_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Platform Path Layer Scan",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- sample_limit_per_table: {result['sample_limit_per_table']}",
        "",
    ]
    for table, summary in result["tables"].items():
        lines.extend(
            [
                f"## {table}",
                "",
                f"- row_count: {summary['row_count']}",
                f"- preferred_path_field: {summary['recommendation']['preferred_path_field']}",
                f"- consistency: {json.dumps(summary['consistency'], ensure_ascii=False)}",
                "",
                f"### Top Suspicious Explicit Platform Values",
                "",
            ]
        )
        if summary["top_suspicious_explicit_platform_values"]:
            for value, cnt in summary["top_suspicious_explicit_platform_values"][:10]:
                lines.append(f"- {value}: {cnt}")
        else:
            lines.append("- none")
        lines.extend(["", "### Path Field Hit Distribution", ""])
        for field, cnt in summary["path_field_hit_distribution"]:
            lines.append(f"- {field}: {cnt}")
        lines.extend(["", "### Preferred Leaf Depth By Platform", ""])
        for platform, depth in summary["recommendation"]["preferred_leaf_depth_by_platform"].items():
            lines.append(f"- {platform}: {depth}")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    print(f"Pattern file: {pattern_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="扫描 ODS 路径层级中的平台关键词，定位平台信息所在层。")
    parser.add_argument("--limit", type=int, default=20000, help="每张表抽样行数上限")
    parser.add_argument("--max-wait", type=int, default=300, help="DLC 最大等待秒数")
    args = parser.parse_args()

    runner = DlcRunner(os.getenv("DLC_USER"), os.getenv("DLC_PASSWORD"), max_wait=args.max_wait)
    queries = build_queries(args.limit)

    result: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_limit_per_table": args.limit,
        "tables": {},
    }
    for table, sql in queries.items():
        rows = runner.exec_sql(sql, "data_ods")
        dict_rows = rows_to_dicts(table, rows)
        result["tables"][table] = analyze_table(table, dict_rows)

    write_outputs(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
