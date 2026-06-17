#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import csv
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

try:
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.dlc.v20210125 import dlc_client, models
except ImportError as exc:
    raise SystemExit(
        "缺少 tencentcloud-sdk-python，请先安装：python -m pip install tencentcloud-sdk-python"
    ) from exc


REGION = "ap-shanghai"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "live-core-dimension-probe-output"
DEFAULT_TOP_N = 30
DEFAULT_SAMPLE_N = 50

FIELD_CANDIDATES: dict[str, list[str]] = {
    "shop": [
        "shop",
        "shop_name",
        "shop_nick",
        "store_name",
        "seller_shop_name",
        "shop_id",
        "erp_shop_id",
        "store_id",
    ],
    "spu": ["spu", "spu_id", "goods_spu", "item_spu"],
    "author_id": ["author_id", "anchor_id", "live_author_id", "主播id", "主播ID", "authorid"],
    "room_id": ["room_id", "live_room_id", "live_room", "session_id", "room_session_id", "场次id", "场次ID"],
    "remark": ["remark", "remarks", "备注", "comment", "memo", "note", "description", "biz_remark", "live_remark"],
    "date_key": ["dt", "ds", "date", "biz_date", "stat_date", "partition_date", "thedate"],
    "datetime_key": [
        "daterange",
        "data_time",
        "stat_time",
        "event_time",
        "create_time",
        "update_time",
        "live_time",
        "start_time",
    ],
}

MAPPING_PAIRS: list[tuple[str, str, str]] = [
    ("shop_to_spu", "shop", "spu"),
    ("shop_to_author_id", "shop", "author_id"),
    ("shop_to_room_id", "shop", "room_id"),
    ("author_id_to_room_id", "author_id", "room_id"),
    ("author_id_to_spu", "author_id", "spu"),
    ("room_id_to_spu", "room_id", "spu"),
]


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class DlcRunner:
    def __init__(self, secret_id: str | None, secret_key: str | None, max_wait: int = 600):
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
        preview = " ".join(sql.strip().split())[:180]
        print(f"[SQL] {db}: {preview}...", flush=True)
        task = models.Task()
        task.SparkSQLTask = {"SQL": base64.b64encode(sql.encode("utf-8")).decode("utf-8")}
        req = models.CreateTaskRequest()
        req.DatabaseName = db
        req.DataEngineName = "SparkSQL"
        req.Task = task
        resp = self.client.CreateTask(req)
        task_id = json.loads(resp.to_json_string()).get("TaskId")
        if not task_id:
            raise RuntimeError("CreateTask 未返回 TaskId")

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

    def describe_table(self, db: str, table: str) -> list[str]:
        req = models.DescribeTableRequest()
        req.DatabaseName = db
        req.TableName = table
        resp = self.client.DescribeTable(req)
        data = json.loads(resp.to_json_string())
        table_info = data.get("Table", data)
        columns = table_info.get("Columns") or []
        names: list[str] = []
        for item in columns:
            if isinstance(item, dict) and item.get("Name"):
                names.append(item["Name"])
        return names


def split_table_ref(table_ref: str) -> tuple[str, str]:
    if "." not in table_ref:
        raise SystemExit("--table-ref 必须是 db.table 形式。")
    db, table = table_ref.split(".", 1)
    if not db or not table:
        raise SystemExit("--table-ref 必须是 db.table 形式。")
    return db, table


def normalize_expr(column_name: str, upper: bool = False) -> str:
    raw = f"TRIM(CAST(`{column_name}` AS STRING))"
    value_expr = f"UPPER({raw})" if upper else raw
    return f"CASE WHEN `{column_name}` IS NULL OR {raw} = '' THEN NULL ELSE {value_expr} END"


def value_label_expr(field_name: str) -> str:
    return f"COALESCE({field_name}, '无')"


def date_prefix_expr(column_name: str) -> str:
    raw = f"TRIM(CAST(`{column_name}` AS STRING))"
    return f"CASE WHEN `{column_name}` IS NULL OR {raw} = '' THEN NULL ELSE SUBSTR({raw}, 1, 10) END"


def resolve_columns(raw_columns: list[str]) -> tuple[dict[str, str | None], list[dict[str, Any]]]:
    column_set = set(raw_columns)
    resolved: dict[str, str | None] = {}
    missing: list[dict[str, Any]] = []
    for logical_name, candidates in FIELD_CANDIDATES.items():
        hit = None
        for candidate in candidates:
            if candidate in column_set:
                hit = candidate
                break
        resolved[logical_name] = hit
        if not hit:
            missing.append({"logical_name": logical_name, "candidates": candidates})
    return resolved, missing


def build_base_cte(
    table_fqn: str,
    resolved: dict[str, str | None],
    where_clause: str | None,
    start_date: str | None,
    end_date: str | None,
) -> str:
    date_source = resolved.get("date_key") or resolved.get("datetime_key")
    select_items = {
        "shop": normalize_expr(resolved["shop"]) if resolved.get("shop") else "CAST(NULL AS STRING)",
        "spu": normalize_expr(resolved["spu"], upper=True) if resolved.get("spu") else "CAST(NULL AS STRING)",
        "author_id": normalize_expr(resolved["author_id"]) if resolved.get("author_id") else "CAST(NULL AS STRING)",
        "room_id": normalize_expr(resolved["room_id"]) if resolved.get("room_id") else "CAST(NULL AS STRING)",
        "remark": normalize_expr(resolved["remark"]) if resolved.get("remark") else "CAST(NULL AS STRING)",
        "date_key": date_prefix_expr(date_source) if date_source else "CAST(NULL AS STRING)",
    }

    where_lines = ["    WHERE 1 = 1"]
    if where_clause:
        where_lines.append(f"      AND ({where_clause})")
    if start_date:
        if not date_source:
            raise SystemExit("传了 --start-date，但表中未命中日期/时间字段候选列，请改用 --where。")
        where_lines.append(f"      AND {date_prefix_expr(date_source)} >= '{start_date}'")
    if end_date:
        if not date_source:
            raise SystemExit("传了 --end-date，但表中未命中日期/时间字段候选列，请改用 --where。")
        where_lines.append(f"      AND {date_prefix_expr(date_source)} <= '{end_date}'")

    lines = ["WITH base AS (", "    SELECT"]
    aliases = list(select_items.keys())
    for index, alias in enumerate(aliases):
        suffix = "," if index < len(aliases) - 1 else ""
        lines.append(f"        {select_items[alias]} AS {alias}{suffix}")
    lines.append(f"    FROM {table_fqn}")
    lines.extend(where_lines)
    lines.append(")")
    return "\n".join(lines)


def build_field_profile_sql(base_cte: str, resolved: dict[str, str | None]) -> str:
    fields = [
        ("shop", resolved.get("shop")),
        ("spu", resolved.get("spu")),
        ("author_id", resolved.get("author_id")),
        ("room_id", resolved.get("room_id")),
        ("remark", resolved.get("remark")),
        ("date_key", resolved.get("date_key") or resolved.get("datetime_key")),
    ]
    unions: list[str] = []
    for logical_name, physical_column in fields:
        physical = physical_column or "未命中"
        unions.append(
            f"""
            SELECT
                '{logical_name}' AS logical_field,
                '{physical}' AS physical_column,
                COUNT(*) AS total_rows,
                SUM(CASE WHEN {logical_name} IS NULL THEN 1 ELSE 0 END) AS null_rows,
                ROUND(SUM(CASE WHEN {logical_name} IS NULL THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 6) AS null_ratio,
                COUNT(DISTINCT {logical_name}) AS distinct_values
            FROM base
            """
        )
    return "\n".join([base_cte, "\nUNION ALL\n".join(unions), "ORDER BY logical_field"])


def build_top_distribution_sql(base_cte: str, field_name: str, limit_n: int) -> str:
    label_expr = value_label_expr(field_name)
    return f"""
    {base_cte},
    agg AS (
        SELECT
            {label_expr} AS field_value,
            COUNT(*) AS row_count
        FROM base
        GROUP BY {label_expr}
    )
    SELECT
        field_value,
        row_count,
        ROUND(row_count * 1.0 / SUM(row_count) OVER (), 6) AS ratio,
        ROUND(SUM(row_count) OVER (ORDER BY row_count DESC, field_value ASC) * 1.0 / SUM(row_count) OVER (), 6) AS cumulative_ratio
    FROM agg
    ORDER BY row_count DESC, field_value ASC
    LIMIT {limit_n}
    """


def build_mapping_summary_sql(base_cte: str, source_field: str, target_field: str) -> str:
    return f"""
    {base_cte},
    pair_stats AS (
        SELECT
            {source_field} AS source_value,
            COUNT(*) AS row_count,
            COUNT(DISTINCT {target_field}) AS target_distinct_cnt
        FROM base
        WHERE {source_field} IS NOT NULL
          AND {target_field} IS NOT NULL
        GROUP BY {source_field}
    )
    SELECT
        COUNT(*) AS source_key_count,
        SUM(row_count) AS covered_rows,
        ROUND(AVG(target_distinct_cnt), 4) AS avg_target_per_source,
        percentile_approx(target_distinct_cnt, 0.5) AS p50_target_per_source,
        percentile_approx(target_distinct_cnt, 0.9) AS p90_target_per_source,
        MAX(target_distinct_cnt) AS max_target_per_source,
        SUM(CASE WHEN target_distinct_cnt > 1 THEN 1 ELSE 0 END) AS multi_mapping_source_keys,
        ROUND(SUM(CASE WHEN target_distinct_cnt > 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 6) AS multi_mapping_ratio
    FROM pair_stats
    """


def build_mapping_sample_sql(base_cte: str, source_field: str, target_field: str, limit_n: int) -> str:
    return f"""
    {base_cte}
    SELECT
        {source_field} AS source_value,
        {target_field} AS target_value,
        COUNT(*) AS row_count
    FROM base
    WHERE {source_field} IS NOT NULL
      AND {target_field} IS NOT NULL
    GROUP BY {source_field}, {target_field}
    ORDER BY row_count DESC, source_value ASC, target_value ASC
    LIMIT {limit_n}
    """


def build_remark_top_sql(base_cte: str, limit_n: int) -> str:
    return f"""
    {base_cte}
    SELECT
        remark,
        COUNT(*) AS row_count,
        COUNT(DISTINCT shop) AS shop_cnt,
        COUNT(DISTINCT spu) AS spu_cnt,
        COUNT(DISTINCT author_id) AS author_cnt,
        COUNT(DISTINCT room_id) AS room_cnt
    FROM base
    WHERE remark IS NOT NULL
    GROUP BY remark
    ORDER BY row_count DESC, remark ASC
    LIMIT {limit_n}
    """


def build_remark_sample_sql(base_cte: str, limit_n: int) -> str:
    return f"""
    {base_cte}
    SELECT
        shop,
        spu,
        author_id,
        room_id,
        remark
    FROM base
    WHERE remark IS NOT NULL
    ORDER BY LENGTH(remark) DESC, remark ASC
    LIMIT {limit_n}
    """


def fetch_single_row(runner: DlcRunner, sql: str, db: str) -> list[Any]:
    rows = runner.exec_sql(sql, db)
    if not rows:
        return []
    return rows[0]


def write_csv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_markdown_summary(
    table_ref: str,
    resolved: dict[str, str | None],
    missing: list[dict[str, Any]],
    field_profile_rows: list[list[Any]],
    mapping_summaries: list[dict[str, Any]],
    output_dir: Path,
) -> str:
    lines = [
        f"# 直播核心维度探针报告",
        "",
        f"- 目标表: `{table_ref}`",
        f"- 输出目录: `{output_dir}`",
        "",
        "## 命中字段",
    ]
    for logical_name in ["shop", "spu", "author_id", "room_id", "remark", "date_key", "datetime_key"]:
        lines.append(f"- `{logical_name}` -> `{resolved.get(logical_name) or '未命中'}`")

    if missing:
        lines.append("")
        lines.append("## 未命中候选")
        for item in missing:
            lines.append(f"- `{item['logical_name']}`: {', '.join(item['candidates'])}")

    lines.append("")
    lines.append("## 字段概况")
    lines.append("| logical_field | physical_column | total_rows | null_rows | null_ratio | distinct_values |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
    for row in field_profile_rows:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} |")

    if mapping_summaries:
        lines.append("")
        lines.append("## 映射摘要")
        lines.append("| mapping_name | source_key_count | covered_rows | avg_target_per_source | p50 | p90 | max | multi_mapping_ratio |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for item in mapping_summaries:
            lines.append(
                f"| {item['mapping_name']} | {item['source_key_count']} | {item['covered_rows']} | "
                f"{item['avg_target_per_source']} | {item['p50_target_per_source']} | {item['p90_target_per_source']} | "
                f"{item['max_target_per_source']} | {item['multi_mapping_ratio']} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="采样直播表中的备注与核心维度分布。")
    parser.add_argument("--table-ref", required=True, help="目标表，格式 db.table")
    parser.add_argument("--where", default=None, help="附加过滤条件，例如 shop = '李宁官方网店'")
    parser.add_argument("--start-date", default=None, help="开始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="结束日期，格式 YYYY-MM-DD")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="分布 Top N")
    parser.add_argument("--sample-n", type=int, default=DEFAULT_SAMPLE_N, help="备注/映射样例条数")
    parser.add_argument("--max-wait", type=int, default=600, help="单条 SQL 最长等待秒数")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    args = parser.parse_args()

    db, table = split_table_ref(args.table_ref)
    table_fqn = f"{db}.{table}"
    output_dir = Path(args.output_dir).resolve() / f"{table.replace('.', '_')}_{now_tag()}"
    output_dir.mkdir(parents=True, exist_ok=True)

    runner = DlcRunner(os.getenv("DLC_USER"), os.getenv("DLC_PASSWORD"), max_wait=args.max_wait)
    raw_columns = runner.describe_table(db, table)
    resolved, missing = resolve_columns(raw_columns)
    base_cte = build_base_cte(table_fqn, resolved, args.where, args.start_date, args.end_date)

    field_profile_rows = runner.exec_sql(build_field_profile_sql(base_cte, resolved), db)
    write_csv(
        output_dir / "field_profile.csv",
        ["logical_field", "physical_column", "total_rows", "null_rows", "null_ratio", "distinct_values"],
        field_profile_rows,
    )

    top_distribution_summary: dict[str, list[list[Any]]] = {}
    for field_name in ["shop", "spu", "author_id", "room_id"]:
        rows = runner.exec_sql(build_top_distribution_sql(base_cte, field_name, args.top_n), db)
        top_distribution_summary[field_name] = rows
        write_csv(
            output_dir / f"top_distribution_{field_name}.csv",
            ["field_value", "row_count", "ratio", "cumulative_ratio"],
            rows,
        )

    mapping_summaries: list[dict[str, Any]] = []
    mapping_samples: dict[str, list[list[Any]]] = {}
    for mapping_name, source_field, target_field in MAPPING_PAIRS:
        if not resolved.get(source_field) or not resolved.get(target_field):
            continue
        summary_row = fetch_single_row(runner, build_mapping_summary_sql(base_cte, source_field, target_field), db)
        if summary_row:
            mapping_summaries.append(
                {
                    "mapping_name": mapping_name,
                    "source_field": source_field,
                    "target_field": target_field,
                    "source_key_count": summary_row[0],
                    "covered_rows": summary_row[1],
                    "avg_target_per_source": summary_row[2],
                    "p50_target_per_source": summary_row[3],
                    "p90_target_per_source": summary_row[4],
                    "max_target_per_source": summary_row[5],
                    "multi_mapping_source_keys": summary_row[6],
                    "multi_mapping_ratio": summary_row[7],
                }
            )
        sample_rows = runner.exec_sql(build_mapping_sample_sql(base_cte, source_field, target_field, args.sample_n), db)
        mapping_samples[mapping_name] = sample_rows
        write_csv(
            output_dir / f"mapping_sample_{mapping_name}.csv",
            ["source_value", "target_value", "row_count"],
            sample_rows,
        )

    remark_top_rows: list[list[Any]] = []
    remark_sample_rows: list[list[Any]] = []
    if resolved.get("remark"):
        remark_top_rows = runner.exec_sql(build_remark_top_sql(base_cte, args.top_n), db)
        remark_sample_rows = runner.exec_sql(build_remark_sample_sql(base_cte, args.sample_n), db)
        write_csv(
            output_dir / "remark_top_distribution.csv",
            ["remark", "row_count", "shop_cnt", "spu_cnt", "author_cnt", "room_cnt"],
            remark_top_rows,
        )
        write_csv(
            output_dir / "remark_samples.csv",
            ["shop", "spu", "author_id", "room_id", "remark"],
            remark_sample_rows,
        )

    summary = {
        "table_ref": args.table_ref,
        "where": args.where,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "resolved_columns": resolved,
        "missing_candidates": missing,
        "raw_columns": raw_columns,
        "field_profile": field_profile_rows,
        "top_distributions": top_distribution_summary,
        "mapping_summaries": mapping_summaries,
        "remark_top_distribution": remark_top_rows,
        "remark_samples": remark_sample_rows,
        "output_dir": str(output_dir),
    }
    write_json(output_dir / "summary.json", summary)

    markdown = build_markdown_summary(args.table_ref, resolved, missing, field_profile_rows, mapping_summaries, output_dir)
    (output_dir / "summary.md").write_text(markdown, encoding="utf-8")

    print(f"输出目录: {output_dir}")
    print("已生成: field_profile.csv, top_distribution_*.csv, mapping_sample_*.csv, summary.json, summary.md")
    if resolved.get("remark"):
        print("已生成: remark_top_distribution.csv, remark_samples.csv")
    else:
        print("备注字段未命中，跳过备注采样。")


if __name__ == "__main__":
    main()
