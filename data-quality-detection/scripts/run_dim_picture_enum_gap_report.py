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

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit("缺少 pandas，请先安装：python -m pip install pandas openpyxl") from exc

try:
    from openpyxl.styles import Alignment, Font, PatternFill
except ImportError as exc:
    raise SystemExit("缺少 openpyxl，请先安装：python -m pip install openpyxl") from exc

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle
except ImportError as exc:
    raise SystemExit("缺少 reportlab，请先安装：python -m pip install reportlab") from exc

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
DEFAULT_OUTPUT_DIR = SCRIPT_DIR
TABLE_FQN = "data_dim.dim_picture_material_data_enriched"


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
        preview = " ".join(sql.strip().split())[:160]
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


def compare_pair(runner: DlcRunner, target_col: str, ref_col: str, sample_limit: int) -> dict[str, Any]:
    base_cte = f"""
    WITH target_vals AS (
        SELECT DISTINCT {normalize_expr(target_col)} AS enum_value
        FROM {TABLE_FQN}
        WHERE {non_empty_expr(target_col)}
    ),
    ref_vals AS (
        SELECT DISTINCT {normalize_expr(ref_col)} AS enum_value
        FROM {TABLE_FQN}
        WHERE {non_empty_expr(ref_col)}
    )
    """
    summary_sql = f"""
    {base_cte}
    SELECT
        (SELECT COUNT(*) FROM target_vals) AS target_enum_count,
        (SELECT COUNT(*) FROM ref_vals) AS ref_enum_count,
        (SELECT COUNT(*) FROM ref_vals r LEFT JOIN target_vals t ON r.enum_value = t.enum_value WHERE t.enum_value IS NULL) AS missing_in_target_count,
        (SELECT COUNT(*) FROM target_vals t LEFT JOIN ref_vals r ON t.enum_value = r.enum_value WHERE r.enum_value IS NULL) AS extra_in_target_count
    """
    summary_rows = runner.exec_sql(summary_sql, "data_dim")
    summary = {
        "target_col": target_col,
        "reference_col": ref_col,
        "target_enum_count": int(summary_rows[0][0]) if summary_rows else 0,
        "ref_enum_count": int(summary_rows[0][1]) if summary_rows else 0,
        "missing_in_target_count": int(summary_rows[0][2]) if summary_rows else 0,
        "extra_in_target_count": int(summary_rows[0][3]) if summary_rows else 0,
    }

    missing_sql = f"""
    {base_cte}
    SELECT
        r.enum_value,
        stats.row_count,
        stats.spu_count
    FROM ref_vals r
    LEFT JOIN target_vals t ON r.enum_value = t.enum_value
    LEFT JOIN (
        SELECT
            {normalize_expr(ref_col)} AS enum_value,
            COUNT(*) AS row_count,
            COUNT(DISTINCT CAST(spu AS STRING)) AS spu_count
        FROM {TABLE_FQN}
        WHERE {non_empty_expr(ref_col)}
        GROUP BY {normalize_expr(ref_col)}
    ) stats ON r.enum_value = stats.enum_value
    WHERE t.enum_value IS NULL
    ORDER BY stats.row_count DESC, stats.spu_count DESC, r.enum_value ASC
    """
    missing_df = pd.DataFrame(runner.exec_sql(missing_sql, "data_dim"), columns=["enum_value", "row_count", "spu_count"])

    extra_sql = f"""
    {base_cte}
    SELECT
        t.enum_value,
        stats.row_count,
        stats.spu_count
    FROM target_vals t
    LEFT JOIN ref_vals r ON t.enum_value = r.enum_value
    LEFT JOIN (
        SELECT
            {normalize_expr(target_col)} AS enum_value,
            COUNT(*) AS row_count,
            COUNT(DISTINCT CAST(spu AS STRING)) AS spu_count
        FROM {TABLE_FQN}
        WHERE {non_empty_expr(target_col)}
        GROUP BY {normalize_expr(target_col)}
    ) stats ON t.enum_value = stats.enum_value
    WHERE r.enum_value IS NULL
    ORDER BY stats.row_count DESC, stats.spu_count DESC, t.enum_value ASC
    """
    extra_df = pd.DataFrame(runner.exec_sql(extra_sql, "data_dim"), columns=["enum_value", "row_count", "spu_count"])

    missing_sample_sql = f"""
    {base_cte}
    SELECT
        file_id,
        platform,
        spu,
        {normalize_expr(ref_col)} AS reference_value,
        {normalize_expr(target_col)} AS target_value,
        full_path
    FROM {TABLE_FQN}
    WHERE {non_empty_expr(ref_col)}
      AND {normalize_expr(ref_col)} IN (
          SELECT r.enum_value
          FROM ref_vals r
          LEFT JOIN target_vals t ON r.enum_value = t.enum_value
          WHERE t.enum_value IS NULL
      )
    LIMIT {sample_limit}
    """
    missing_sample_df = pd.DataFrame(
        runner.exec_sql(missing_sample_sql, "data_dim"),
        columns=["file_id", "platform", "spu", "reference_value", "target_value", "full_path"],
    )

    extra_sample_sql = f"""
    {base_cte}
    SELECT
        file_id,
        platform,
        spu,
        {normalize_expr(target_col)} AS target_value,
        {normalize_expr(ref_col)} AS reference_value,
        full_path
    FROM {TABLE_FQN}
    WHERE {non_empty_expr(target_col)}
      AND {normalize_expr(target_col)} IN (
          SELECT t.enum_value
          FROM target_vals t
          LEFT JOIN ref_vals r ON t.enum_value = r.enum_value
          WHERE r.enum_value IS NULL
      )
    LIMIT {sample_limit}
    """
    extra_sample_df = pd.DataFrame(
        runner.exec_sql(extra_sample_sql, "data_dim"),
        columns=["file_id", "platform", "spu", "target_value", "reference_value", "full_path"],
    )

    return {
        "summary": summary,
        "missing_df": missing_df,
        "extra_df": extra_df,
        "missing_sample_df": missing_sample_df,
        "extra_sample_df": extra_sample_df,
    }


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
                values = [str(cell.value) if cell.value is not None else "" for cell in column_cells[:120]]
                width = min(max(len(value) for value in values) + 2, 90)
                sheet.column_dimensions[column_cells[0].column_letter].width = width


def truncate_text(text: Any, limit: int = 72) -> str:
    raw = str(text) if text is not None else ""
    return raw if len(raw) <= limit else raw[: limit - 3] + "..."


def build_pdf_table(rows: list[list[Any]], col_widths: list[float], style) -> LongTable:
    table = LongTable(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(style)
    return table


def write_pdf(output_path: Path, pair_results: list[dict[str, Any]]) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleCN", parent=styles["Title"], fontName="STSong-Light", fontSize=18, leading=24)
    body_style = ParagraphStyle("BodyCN", parent=styles["BodyText"], fontName="STSong-Light", fontSize=10, leading=14)
    heading_style = ParagraphStyle("HeadingCN", parent=styles["Heading2"], fontName="STSong-Light", fontSize=13, leading=18)
    table_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("LEADING", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9AA5B1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#F4F7FB")]),
        ]
    )

    story: list[Any] = []
    story.append(Paragraph("DIM 图片枚举值缺口报告", title_style))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", body_style))
    story.append(Paragraph("检测口径：对比同表 data_dim.dim_picture_material_data_enriched 中目标字段与 reference 字段的枚举值集合差异。", body_style))
    story.append(Spacer(1, 4 * mm))

    for idx, pair in enumerate(pair_results, start=1):
        summary = pair["summary"]
        story.append(Paragraph(f"{idx}. `{summary['target_col']}` 对比 `{summary['reference_col']}`", heading_style))
        summary_rows = [["metric", "value"]]
        for key, value in summary.items():
            summary_rows.append([key, value])
        story.append(build_pdf_table(summary_rows, [80 * mm, 40 * mm], table_style))
        story.append(Spacer(1, 3 * mm))

        missing_rows = [["enum_value", "row_count", "spu_count"]]
        for row in pair["missing_df"].head(80).itertuples(index=False):
            missing_rows.append([truncate_text(row.enum_value, 50), int(row.row_count), int(row.spu_count)])
        story.append(Paragraph("reference 有、target 缺失的枚举值", body_style))
        story.append(build_pdf_table(missing_rows, [90 * mm, 25 * mm, 25 * mm], table_style))
        story.append(Spacer(1, 3 * mm))

        extra_rows = [["enum_value", "row_count", "spu_count"]]
        for row in pair["extra_df"].head(80).itertuples(index=False):
            extra_rows.append([truncate_text(row.enum_value, 50), int(row.row_count), int(row.spu_count)])
        story.append(Paragraph("target 有、reference 缺失的枚举值", body_style))
        story.append(build_pdf_table(extra_rows, [90 * mm, 25 * mm, 25 * mm], table_style))
        story.append(Spacer(1, 3 * mm))

        sample_rows = [["file_id", "platform", "spu", "reference_value", "target_value", "full_path"]]
        for row in pair["missing_sample_df"].head(40).itertuples(index=False):
            sample_rows.append([
                truncate_text(row.file_id, 18),
                truncate_text(row.platform, 12),
                truncate_text(row.spu, 16),
                truncate_text(row.reference_value, 18),
                truncate_text(row.target_value, 18),
                truncate_text(row.full_path, 45),
            ])
        story.append(Paragraph("缺失枚举值样本", body_style))
        story.append(build_pdf_table(sample_rows, [28 * mm, 18 * mm, 18 * mm, 28 * mm, 28 * mm, 55 * mm], table_style))
        if idx < len(pair_results):
            story.append(PageBreak())

    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
    doc.build(story)


def write_markdown(output_path: Path, pair_results: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("# DIM 图片枚举值缺口报告")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("说明：`middle_cate` 在表中实际字段名为 `mid_cate`。")
    lines.append("")
    for pair in pair_results:
        summary = pair["summary"]
        lines.append(f"## `{summary['target_col']}` 对比 `{summary['reference_col']}`")
        lines.append("")
        lines.append("| metric | value |")
        lines.append("|---|---:|")
        for key, value in summary.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")
        lines.append("### reference 有、target 缺失的枚举值")
        lines.append("")
        lines.append("| enum_value | row_count | spu_count |")
        lines.append("|---|---:|---:|")
        for row in pair["missing_df"].itertuples(index=False):
            lines.append(f"| {row.enum_value} | {int(row.row_count)} | {int(row.spu_count)} |")
        lines.append("")
        lines.append("### target 有、reference 缺失的枚举值")
        lines.append("")
        lines.append("| enum_value | row_count | spu_count |")
        lines.append("|---|---:|---:|")
        for row in pair["extra_df"].itertuples(index=False):
            lines.append(f"| {row.enum_value} | {int(row.row_count)} | {int(row.spu_count)} |")
        lines.append("")
        lines.append("### 缺失枚举值样本")
        lines.append("")
        lines.append("| file_id | platform | spu | reference_value | target_value | full_path |")
        lines.append("|---|---|---|---|---|---|")
        for row in pair["missing_sample_df"].head(40).itertuples(index=False):
            lines.append(f"| {row.file_id} | {row.platform} | {row.spu} | {row.reference_value} | {row.target_value} | {row.full_path} |")
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DIM 图片枚举值缺口检测")
    parser.add_argument("--sample-limit", type=int, default=50, help="每个字段对比的抽样数量")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--max-wait", type=int, default=300, help="单条 SQL 最长等待秒数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runner = DlcRunner(os.environ.get("DLC_USER"), os.environ.get("DLC_PASSWORD"), args.max_wait)

    print("[1/2] 对比 mid_cate 与 reference_mid_cate...", flush=True)
    mid_pair = compare_pair(runner, "mid_cate", "reference_mid_cate", args.sample_limit)
    print("[2/2] 对比 track_first_li_ning_bi 与 reference_track...", flush=True)
    track_pair = compare_pair(runner, "track_first_li_ning_bi", "reference_track", args.sample_limit)
    pair_results = [mid_pair, track_pair]

    date_tag = now_tag()
    md_path = output_dir / f"dim-picture-enum-gap-report-{date_tag}.md"
    json_path = output_dir / f"dim-picture-enum-gap-report-{date_tag}.json"
    xlsx_path = output_dir / f"dim-picture-enum-gap-report-{date_tag}.xlsx"
    pdf_path = output_dir / f"dim-picture-enum-gap-report-{date_tag}.pdf"

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pairs": [
            {
                "summary": pair["summary"],
                "missing_values": pair["missing_df"].to_dict(orient="records"),
                "extra_values": pair["extra_df"].to_dict(orient="records"),
                "missing_samples": pair["missing_sample_df"].to_dict(orient="records"),
                "extra_samples": pair["extra_sample_df"].to_dict(orient="records"),
            }
            for pair in pair_results
        ],
    }
    write_markdown(md_path, pair_results)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_excel(
        xlsx_path,
        {
            "mid_summary": pd.DataFrame([mid_pair["summary"]]),
            "mid_missing": mid_pair["missing_df"],
            "mid_extra": mid_pair["extra_df"],
            "mid_missing_sample": mid_pair["missing_sample_df"],
            "track_summary": pd.DataFrame([track_pair["summary"]]),
            "track_missing": track_pair["missing_df"],
            "track_extra": track_pair["extra_df"],
            "track_missing_sample": track_pair["missing_sample_df"],
        },
    )
    write_pdf(pdf_path, pair_results)

    print("[OK] MD:", md_path)
    print("[OK] JSON:", json_path)
    print("[OK] XLSX:", xlsx_path)
    print("[OK] PDF:", pdf_path)


if __name__ == "__main__":
    main()
