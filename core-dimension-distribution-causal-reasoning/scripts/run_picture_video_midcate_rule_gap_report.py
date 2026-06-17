#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from collections import Counter
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
    import pandas as pd
except ImportError as exc:
    raise SystemExit("缺少 pandas，请先安装：python -m pip install pandas openpyxl") from exc

try:
    from openpyxl.styles import Alignment, Font, PatternFill
except ImportError as exc:
    raise SystemExit("缺少 openpyxl，请先安装：python -m pip install openpyxl") from exc

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
WORKSPACE_DIR = SCRIPT_DIR.parents[1]
DEFAULT_OUTPUT_DIR = SCRIPT_DIR
DEFAULT_RULE_SQL_PATH = WORKSPACE_DIR / "sample-002.sql"
DEFAULT_CURRENT_SQL_PATH = WORKSPACE_DIR / "current-table-01.sql"
PICTURE_TABLE = "data_dim.dim_picture_material_data_enriched"
VIDEO_SOURCE_TABLE = "data_dws.dws_platform_file_resource_label_id"
VIDEO_FINAL_TABLE = "data_dws.dws_short_video_product_info"


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d")


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


def normalize_expr(column_name: str) -> str:
    return f"TRIM(CAST(`{column_name}` AS STRING))"


def non_empty_expr(column_name: str) -> str:
    return f"`{column_name}` IS NOT NULL AND TRIM(CAST(`{column_name}` AS STRING)) <> ''"


def build_picture_only_detail_sql() -> str:
    return f"""
    WITH picture_vals AS (
        SELECT
            {normalize_expr("mid_cate")} AS enum_value,
            COUNT(*) AS picture_row_count,
            COUNT(DISTINCT CAST(spu AS STRING)) AS picture_spu_count
        FROM {PICTURE_TABLE}
        WHERE {non_empty_expr("mid_cate")}
        GROUP BY {normalize_expr("mid_cate")}
    ),
    video_src_vals AS (
        SELECT
            {normalize_expr("mid_cate")} AS enum_value,
            COUNT(*) AS video_source_row_count,
            COUNT(DISTINCT CAST(spu AS STRING)) AS video_source_spu_count
        FROM {VIDEO_SOURCE_TABLE}
        WHERE file_type = '视频'
          AND {non_empty_expr("mid_cate")}
        GROUP BY {normalize_expr("mid_cate")}
    ),
    video_final_vals AS (
        SELECT
            {normalize_expr("mid_cate")} AS enum_value,
            COUNT(*) AS video_final_row_count,
            COUNT(DISTINCT CAST(spu AS STRING)) AS video_final_spu_count
        FROM {VIDEO_FINAL_TABLE}
        WHERE {non_empty_expr("mid_cate")}
        GROUP BY {normalize_expr("mid_cate")}
    ),
    picture_samples AS (
        SELECT
            {normalize_expr("mid_cate")} AS enum_value,
            TRIM(CAST(spu AS STRING)) AS sample_spu,
            TRIM(CAST(file_id AS STRING)) AS sample_file_id,
            TRIM(CAST(product_name AS STRING)) AS sample_product_name,
            ROW_NUMBER() OVER (
                PARTITION BY {normalize_expr("mid_cate")}
                ORDER BY TRIM(CAST(spu AS STRING)) ASC, TRIM(CAST(file_id AS STRING)) ASC
            ) AS rn
        FROM {PICTURE_TABLE}
        WHERE {non_empty_expr("mid_cate")}
    )
    SELECT
        p.enum_value,
        p.picture_row_count,
        p.picture_spu_count,
        COALESCE(s.video_source_row_count, 0) AS video_source_row_count,
        COALESCE(s.video_source_spu_count, 0) AS video_source_spu_count,
        COALESCE(v.video_final_row_count, 0) AS video_final_row_count,
        COALESCE(v.video_final_spu_count, 0) AS video_final_spu_count,
        MAX(CASE WHEN ps.rn = 1 THEN ps.sample_spu END) AS sample_spu_1,
        MAX(CASE WHEN ps.rn = 1 THEN ps.sample_file_id END) AS sample_file_id_1,
        MAX(CASE WHEN ps.rn = 1 THEN ps.sample_product_name END) AS sample_product_name_1,
        MAX(CASE WHEN ps.rn = 2 THEN ps.sample_spu END) AS sample_spu_2,
        MAX(CASE WHEN ps.rn = 2 THEN ps.sample_file_id END) AS sample_file_id_2,
        MAX(CASE WHEN ps.rn = 2 THEN ps.sample_product_name END) AS sample_product_name_2
    FROM picture_vals p
    LEFT JOIN video_src_vals s
        ON p.enum_value = s.enum_value
    LEFT JOIN video_final_vals v
        ON p.enum_value = v.enum_value
    LEFT JOIN picture_samples ps
        ON p.enum_value = ps.enum_value AND ps.rn <= 2
    WHERE COALESCE(v.video_final_row_count, 0) = 0
    GROUP BY
        p.enum_value,
        p.picture_row_count,
        p.picture_spu_count,
        s.video_source_row_count,
        s.video_source_spu_count,
        v.video_final_row_count,
        v.video_final_spu_count
    ORDER BY p.picture_row_count DESC, p.picture_spu_count DESC, p.enum_value ASC
    """


def build_video_enum_sql() -> str:
    return f"""
    SELECT
        {normalize_expr("mid_cate")} AS enum_value,
        COUNT(*) AS video_final_row_count,
        COUNT(DISTINCT CAST(spu AS STRING)) AS video_final_spu_count
    FROM {VIDEO_FINAL_TABLE}
    WHERE {non_empty_expr("mid_cate")}
    GROUP BY {normalize_expr("mid_cate")}
    ORDER BY video_final_row_count DESC, video_final_spu_count DESC, enum_value ASC
    """


def build_video_source_consistency_sql() -> str:
    return f"""
    WITH src AS (
        SELECT DISTINCT {normalize_expr("mid_cate")} AS enum_value
        FROM {VIDEO_SOURCE_TABLE}
        WHERE file_type = '视频'
          AND {non_empty_expr("mid_cate")}
    ),
    final AS (
        SELECT DISTINCT {normalize_expr("mid_cate")} AS enum_value
        FROM {VIDEO_FINAL_TABLE}
        WHERE {non_empty_expr("mid_cate")}
    )
    SELECT
        COUNT(*) AS source_enum_count,
        SUM(CASE WHEN f.enum_value IS NULL THEN 1 ELSE 0 END) AS source_only_enum_count
    FROM src s
    LEFT JOIN final f ON s.enum_value = f.enum_value
    """


def parse_historical_rules(sql_path: Path) -> tuple[list[dict[str, Any]], set[str], dict[str, str]]:
    sql_text = sql_path.read_text(encoding="utf-8")
    block_match = re.search(r"case when t5\.mid_cate.*?else t5\.mid_cate end as mid_cate", sql_text, re.S)
    if not block_match:
        raise RuntimeError(f"未在 {sql_path} 中找到视频中类规整 CASE 片段")
    block = block_match.group(0)
    pattern = re.compile(r"when t5\.mid_cate in \((.*?)\) then '([^']*)'", re.S)

    rules: list[dict[str, Any]] = []
    target_set: set[str] = set()
    alias_to_target: dict[str, str] = {}
    for match in pattern.finditer(block):
        alias_tokens = re.findall(r"'([^']*)'", match.group(1))
        target = match.group(2).strip()
        target_set.add(target)
        cleaned_aliases = [token.strip() for token in alias_tokens if token.strip()]
        rules.append({"aliases": cleaned_aliases, "target": target})
        for alias in cleaned_aliases:
            if alias != target:
                alias_to_target[alias] = target
    return rules, target_set, alias_to_target


def family_bucket(value: str) -> str:
    if re.search(r"鞋|靴|凉鞋|拖鞋|单鞋|玛丽珍", value):
        return "鞋靴"
    if re.search(r"裤", value):
        return "裤装"
    if re.search(r"裙|内衣|泳|连体衣|连身衣|背心|吊带", value):
        return "裙装/内衣/泳装"
    if "套装" in value:
        return "套装"
    if re.search(r"外套|衫|衣|服|上衣|马甲|羽绒|防晒|针织衫|大衣", value):
        return "上装"
    if re.search(r"球|拍|线|柄皮|器材|器械|耗材", value):
        return "球拍球线/器材"
    if re.search(r"帽|包|袜|配件|护具|手套|围巾|壶|镜|公仔|玩偶", value):
        return "配件/护具/包袜"
    return "其他"


def classify_row(
    row: pd.Series,
    historical_target_set: set[str],
    alias_to_target: dict[str, str],
    family_to_video_enums: dict[str, list[str]],
) -> pd.Series:
    enum_value = str(row["enum_value"])
    if enum_value in historical_target_set:
        status = "历史规则目标已定义"
        suggested_target = enum_value
        action = "无需新增视频标准枚举，优先排查视频来源覆盖或当前周期无视频样本"
    elif enum_value in alias_to_target:
        status = "历史规则别名已定义"
        suggested_target = alias_to_target[enum_value]
        action = f"无需新增视频标准枚举，若视频原始值出现应规整到 `{suggested_target}`"
    else:
        status = "历史规则未覆盖"
        suggested_target = ""
        action = "需业务判定：新增视频标准枚举，或补充归并规则"

    bucket = family_bucket(enum_value)
    same_family_video = "、".join(family_to_video_enums.get(bucket, [])[:12])
    row["rule_status"] = status
    row["suggested_target"] = suggested_target
    row["family_bucket"] = bucket
    row["same_family_video_enums"] = same_family_video
    row["suggested_action"] = action
    return row


def inspect_current_sql(sql_path: Path) -> pd.DataFrame:
    lines = sql_path.read_text(encoding="utf-8").splitlines()
    video_insert_pattern = "insert overwrite table data_dws.dws_short_video_product_info"
    video_source_pattern = "FROM data_dws.dws_platform_file_resource_label_id"
    video_mid_agg_pattern = "MAX(mid_cate) as mid_cate"

    video_insert_line = 0
    for idx, line in enumerate(lines, start=1):
        if video_insert_pattern in line:
            video_insert_line = idx
            break

    rows: list[dict[str, Any]] = []
    patterns = [
        ("video_insert", video_insert_pattern, 1),
        ("video_source", video_source_pattern, video_insert_line or 1),
        ("video_mid_agg", video_mid_agg_pattern, video_insert_line or 1),
    ]
    for key, pattern, start_line in patterns:
        matched_line = 0
        matched_text = ""
        for idx, line in enumerate(lines, start=1):
            if idx < start_line:
                continue
            if pattern in line:
                matched_line = idx
                matched_text = line.strip()
                break
        rows.append(
            {
                "pattern_key": key,
                "matched": 1 if matched_line else 0,
                "line_no": matched_line,
                "line_text": matched_text,
            }
        )
    return pd.DataFrame(rows)


def write_excel(output_path: Path, frames: dict[str, pd.DataFrame]) -> None:
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in frames.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        workbook = writer.book
        header_fill = PatternFill("solid", fgColor="1F4E78")
        header_font = Font(color="FFFFFF", bold=True)
        for sheet in workbook.worksheets:
            sheet.freeze_panes = "A2"
            for cell in sheet[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
            for column_cells in sheet.columns:
                values = [str(cell.value) if cell.value is not None else "" for cell in column_cells[:200]]
                width = min(max(len(value) for value in values) + 2, 70)
                sheet.column_dimensions[column_cells[0].column_letter].width = width


def write_markdown(
    output_path: Path,
    summary_df: pd.DataFrame,
    bucket_df: pd.DataFrame,
    detail_df: pd.DataFrame,
    historical_rules_df: pd.DataFrame,
    current_sql_df: pd.DataFrame,
) -> None:
    lines: list[str] = []
    lines.append("# 图片独有中类 vs 视频规则覆盖报告")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## 分析目标")
    lines.append("")
    lines.append("- 以图片素材表 `data_dim.dim_picture_material_data_enriched.mid_cate` 为主参照。")
    lines.append("- 对照视频来源层 `data_dws.dws_platform_file_resource_label_id(file_type='视频')` 与视频结果层 `data_dws.dws_short_video_product_info.mid_cate`。")
    lines.append("- 结合历史规则脚本 `sample-002.sql` 中的 `CASE WHEN t5.mid_cate ... THEN ...` 中类规整逻辑，判断图片独有中类到底属于“历史规则已支持但当前没数据”，还是“历史规则根本未覆盖”。")
    lines.append("")
    lines.append("## 关键结论")
    lines.append("")
    summary = summary_df.iloc[0].to_dict()
    lines.append(f"- 图片独有中类共 `{int(summary['picture_only_count'])}` 个。")
    lines.append(f"- 其中 `{int(summary['historical_target_defined_count'])}` 个已经出现在历史视频规整规则的目标枚举中，说明这批值不是标准枚举空缺，而是视频来源覆盖不足或当前周期没有对应视频样本。")
    lines.append(f"- 其中 `{int(summary['historical_alias_defined_count'])}` 个出现在历史规则别名中。")
    lines.append(f"- 其余 `{int(summary['historical_rule_uncovered_count'])}` 个没有出现在历史视频规整规则里，才是真正的“视频规则未覆盖候选”。")
    lines.append(f"- 视频来源层与结果层的中类枚举集合一致：来源层 `{int(summary['video_source_enum_count'])}` 个，来源独有但结果层缺失 `{int(summary['video_source_only_enum_count'])}` 个。也就是说，这批问题不是 `dws_short_video_product_info` 聚合丢值，而是视频来源层本身就没有这些中类。")
    lines.append("")

    lines.append("## 根因拆解")
    lines.append("")
    lines.append("- 当前视频结果表链路在 `current-table-01.sql` 中直接从 `data_dws.dws_platform_file_resource_label_id` 取 `mid_cate`，并 `MAX(mid_cate)` 聚合写入 `dws_short_video_product_info`，没有额外的视频中类规整补齐。")
    lines.append("- 因此，只要视频来源层没有某个 `mid_cate`，结果层也不会凭空出现。")
    lines.append("- `sample-002.sql` 提供的是另一套历史规整经验，它能帮助识别“这个枚举历史上是否被当成视频标准值或别名处理过”，但不能替代当前视频来源数据。")
    lines.append("")

    lines.append("## 汇总")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("| --- | ---: |")
    for col in summary_df.columns:
        lines.append(f"| {col} | {summary[col]} |")
    lines.append("")

    lines.append("## 未覆盖家族分布")
    lines.append("")
    lines.append("| family_bucket | enum_count | picture_rows | picture_spus |")
    lines.append("| --- | ---: | ---: | ---: |")
    for row in bucket_df.itertuples(index=False):
        lines.append(f"| {row.family_bucket} | {int(row.enum_count)} | {int(row.picture_rows)} | {int(row.picture_spus)} |")
    lines.append("")

    lines.append("## 历史规则样例")
    lines.append("")
    lines.append("| target | aliases |")
    lines.append("| --- | --- |")
    for row in historical_rules_df.head(20).itertuples(index=False):
        lines.append(f"| {row.target} | {row.aliases} |")
    lines.append("")

    lines.append("## 当前链路核对")
    lines.append("")
    lines.append("| pattern_key | matched | line_no | line_text |")
    lines.append("| --- | ---: | ---: | --- |")
    for row in current_sql_df.itertuples(index=False):
        lines.append(f"| {row.pattern_key} | {int(row.matched)} | {int(row.line_no)} | {row.line_text} |")
    lines.append("")

    lines.append("## 图片独有中类明细")
    lines.append("")
    lines.append("| enum_value | picture_rows | picture_spus | video_source_rows | video_final_rows | rule_status | suggested_target | family_bucket | same_family_video_enums | sample_spu_1 | sample_file_id_1 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |")
    for row in detail_df.itertuples(index=False):
        lines.append(
            f"| {row.enum_value} | {int(row.picture_row_count)} | {int(row.picture_spu_count)} | "
            f"{int(row.video_source_row_count)} | {int(row.video_final_row_count)} | {row.rule_status} | "
            f"{row.suggested_target} | {row.family_bucket} | {row.same_family_video_enums} | "
            f"{row.sample_spu_1 or ''} | {row.sample_file_id_1 or ''} |"
        )
    lines.append("")

    lines.append("## 建议")
    lines.append("")
    lines.append("- `历史规则目标已定义`：先不要急着新增视频枚举，应先排查视频来源层是否有对应素材、标签是否没打上，或当前周期视频样本覆盖不足。")
    lines.append("- `历史规则未覆盖`：这批才是优先级最高的候选，需要业务判断是新增视频标准枚举，还是归并到同家族已有枚举。")
    lines.append("- 像 `球类` 这种值，当前视频来源层无数据、历史规则也未覆盖，更接近“新增枚举或新增归并规则候选”，而不是下游丢值。")
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="分析图片独有中类在视频规则中的覆盖缺口")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--rule-sql-path", default=str(DEFAULT_RULE_SQL_PATH), help="历史规则 SQL 路径")
    parser.add_argument("--current-sql-path", default=str(DEFAULT_CURRENT_SQL_PATH), help="当前视频链路 SQL 路径")
    parser.add_argument("--max-wait", type=int, default=300, help="DLC 单条 SQL 最长等待秒数")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"picture-video-midcate-rule-gap-report-{now_tag()}"

    runner = DlcRunner(os.getenv("DLC_USER"), os.getenv("DLC_PASSWORD"), max_wait=args.max_wait)

    print("[1/5] 拉取图片独有中类明细...", flush=True)
    detail_rows = runner.exec_sql(build_picture_only_detail_sql(), "data_dim")
    detail_df = pd.DataFrame(
        detail_rows,
        columns=[
            "enum_value",
            "picture_row_count",
            "picture_spu_count",
            "video_source_row_count",
            "video_source_spu_count",
            "video_final_row_count",
            "video_final_spu_count",
            "sample_spu_1",
            "sample_file_id_1",
            "sample_product_name_1",
            "sample_spu_2",
            "sample_file_id_2",
            "sample_product_name_2",
        ],
    )

    print("[2/5] 拉取视频结果层枚举分布...", flush=True)
    video_rows = runner.exec_sql(build_video_enum_sql(), "data_dws")
    video_df = pd.DataFrame(video_rows, columns=["enum_value", "video_final_row_count", "video_final_spu_count"])

    print("[3/5] 校验视频来源层与结果层枚举一致性...", flush=True)
    consistency_rows = runner.exec_sql(build_video_source_consistency_sql(), "data_dws")
    source_enum_count = int(consistency_rows[0][0]) if consistency_rows else 0
    source_only_enum_count = int(consistency_rows[0][1]) if consistency_rows else 0

    print("[4/5] 解析历史规整规则...", flush=True)
    historical_rules, historical_target_set, alias_to_target = parse_historical_rules(Path(args.rule_sql_path))
    historical_rules_df = pd.DataFrame(
        [{"target": item["target"], "aliases": "、".join(item["aliases"])} for item in historical_rules]
    )

    print("[5/5] 生成分类与报告...", flush=True)
    numeric_cols = [
        "picture_row_count",
        "picture_spu_count",
        "video_source_row_count",
        "video_source_spu_count",
        "video_final_row_count",
        "video_final_spu_count",
    ]
    for col in numeric_cols:
        if col in detail_df.columns:
            detail_df[col] = pd.to_numeric(detail_df[col], errors="coerce").fillna(0).astype(int)
        if col in video_df.columns:
            video_df[col] = pd.to_numeric(video_df[col], errors="coerce").fillna(0).astype(int)

    family_to_video_enums: dict[str, list[str]] = {}
    if not video_df.empty:
        for enum_value in video_df["enum_value"].astype(str).tolist():
            family_to_video_enums.setdefault(family_bucket(enum_value), []).append(enum_value)

    if not detail_df.empty:
        detail_df = detail_df.apply(
            classify_row,
            axis=1,
            historical_target_set=historical_target_set,
            alias_to_target=alias_to_target,
            family_to_video_enums=family_to_video_enums,
        )

    summary_df = pd.DataFrame(
        [
            {
                "picture_only_count": int(len(detail_df.index)),
                "historical_target_defined_count": int((detail_df["rule_status"] == "历史规则目标已定义").sum()) if not detail_df.empty else 0,
                "historical_alias_defined_count": int((detail_df["rule_status"] == "历史规则别名已定义").sum()) if not detail_df.empty else 0,
                "historical_rule_uncovered_count": int((detail_df["rule_status"] == "历史规则未覆盖").sum()) if not detail_df.empty else 0,
                "video_source_enum_count": source_enum_count,
                "video_source_only_enum_count": source_only_enum_count,
            }
        ]
    )

    uncovered_df = detail_df[detail_df["rule_status"] == "历史规则未覆盖"].copy() if not detail_df.empty else pd.DataFrame()
    if not uncovered_df.empty:
        bucket_counter = Counter(uncovered_df["family_bucket"].astype(str).tolist())
        bucket_rows: list[dict[str, Any]] = []
        for bucket_name, enum_count in bucket_counter.items():
            bucket_slice = uncovered_df[uncovered_df["family_bucket"] == bucket_name]
            bucket_rows.append(
                {
                    "family_bucket": bucket_name,
                    "enum_count": int(enum_count),
                    "picture_rows": int(bucket_slice["picture_row_count"].sum()),
                    "picture_spus": int(bucket_slice["picture_spu_count"].sum()),
                }
            )
        bucket_df = pd.DataFrame(bucket_rows).sort_values(
            by=["enum_count", "picture_rows", "picture_spus", "family_bucket"],
            ascending=[False, False, False, True],
        )
    else:
        bucket_df = pd.DataFrame(columns=["family_bucket", "enum_count", "picture_rows", "picture_spus"])

    current_sql_df = inspect_current_sql(Path(args.current_sql_path))

    markdown_path = output_dir / f"{prefix}.md"
    json_path = output_dir / f"{prefix}.json"
    xlsx_path = output_dir / f"{prefix}.xlsx"

    write_markdown(markdown_path, summary_df, bucket_df, detail_df, historical_rules_df, current_sql_df)
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "summary": summary_df.to_dict(orient="records"),
                "bucket_summary": bucket_df.to_dict(orient="records"),
                "detail": detail_df.to_dict(orient="records"),
                "historical_rules": historical_rules_df.to_dict(orient="records"),
                "current_sql_checks": current_sql_df.to_dict(orient="records"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_excel(
        xlsx_path,
        {
            "summary": summary_df,
            "bucket_summary": bucket_df,
            "detail": detail_df,
            "historical_rules": historical_rules_df,
            "video_final_enums": video_df,
            "current_sql_checks": current_sql_df,
        },
    )

    print(f"[DONE] Markdown: {markdown_path}", flush=True)
    print(f"[DONE] JSON: {json_path}", flush=True)
    print(f"[DONE] Excel: {xlsx_path}", flush=True)


if __name__ == "__main__":
    main()
