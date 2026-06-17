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
WORKSPACE_DIR = SCRIPT_DIR.parents[1]
DEFAULT_OUTPUT_DIR = SCRIPT_DIR
DEFAULT_SQL_PATH = WORKSPACE_DIR / "current-table-01.sql"


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


def value_at(rows: list[list[Any]] | None, row: int = 0, col: int = 0, default: Any = None) -> Any:
    try:
        return rows[row][col]
    except Exception:
        return default


def to_int(value: Any) -> int:
    try:
        return int(str(value))
    except Exception:
        return 0


def scalar_query(runner: DlcRunner, db: str, sql: str) -> int:
    return to_int(value_at(runner.exec_sql(sql, db), 0, 0, 0))


def build_common_cte() -> str:
    return """
    WITH video_spu AS (
        SELECT
            TRIM(CAST(spu AS STRING)) AS spu,
            MAX(CASE WHEN mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> '' THEN TRIM(CAST(mid_cate AS STRING)) END) AS video_mid_cate,
            MAX(CASE WHEN track IS NOT NULL AND TRIM(CAST(track AS STRING)) <> '' THEN TRIM(CAST(track AS STRING)) END) AS video_track,
            MAX(CASE WHEN mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> '' THEN 1 ELSE 0 END) AS video_has_mid,
            MAX(CASE WHEN track IS NOT NULL AND TRIM(CAST(track AS STRING)) <> '' THEN 1 ELSE 0 END) AS video_has_track,
            COUNT(*) AS video_rows
        FROM data_dws.dws_short_video_product_info
        WHERE spu IS NOT NULL AND TRIM(CAST(spu AS STRING)) <> ''
        GROUP BY TRIM(CAST(spu AS STRING))
    ),
    image_src_spu AS (
        SELECT
            TRIM(CAST(spu AS STRING)) AS spu,
            MAX(CASE WHEN mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> '' THEN TRIM(CAST(mid_cate AS STRING)) END) AS image_mid_cate,
            MAX(CASE WHEN sub_track IS NOT NULL AND TRIM(CAST(sub_track AS STRING)) <> '' THEN TRIM(CAST(sub_track AS STRING)) END) AS image_track,
            MAX(CASE WHEN mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> '' THEN 1 ELSE 0 END) AS image_has_mid,
            MAX(CASE WHEN sub_track IS NOT NULL AND TRIM(CAST(sub_track AS STRING)) <> '' THEN 1 ELSE 0 END) AS image_has_track,
            COUNT(*) AS image_rows,
            COUNT(DISTINCT CAST(file_id AS STRING)) AS image_file_ids
        FROM data_dws.dws_platform_file_resource_label_id
        WHERE file_type = '图片'
          AND spu IS NOT NULL AND TRIM(CAST(spu AS STRING)) <> ''
        GROUP BY TRIM(CAST(spu AS STRING))
    ),
    dim_spu AS (
        SELECT
            TRIM(CAST(spu AS STRING)) AS spu,
            MAX(CASE WHEN mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> '' THEN TRIM(CAST(mid_cate AS STRING)) END) AS dim_mid_cate,
            MAX(CASE WHEN track_first_li_ning_bi IS NOT NULL AND TRIM(CAST(track_first_li_ning_bi AS STRING)) <> '' THEN TRIM(CAST(track_first_li_ning_bi AS STRING)) END) AS dim_track,
            MAX(CASE WHEN mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> '' THEN 1 ELSE 0 END) AS dim_has_mid,
            MAX(CASE WHEN track_first_li_ning_bi IS NOT NULL AND TRIM(CAST(track_first_li_ning_bi AS STRING)) <> '' THEN 1 ELSE 0 END) AS dim_has_track,
            COUNT(*) AS dim_rows,
            COUNT(DISTINCT CAST(file_id AS STRING)) AS dim_file_ids
        FROM data_dim.dim_picture_material_data_enriched
        WHERE spu IS NOT NULL AND TRIM(CAST(spu AS STRING)) <> ''
        GROUP BY TRIM(CAST(spu AS STRING))
    )
    """


def query_summary(runner: DlcRunner) -> dict[str, int]:
    sql = f"""
    {build_common_cte()}
    SELECT
        COUNT(*) AS video_spu_total,
        SUM(CASE WHEN video_has_mid = 1 THEN 1 ELSE 0 END) AS video_spu_with_mid,
        SUM(CASE WHEN video_has_track = 1 THEN 1 ELSE 0 END) AS video_spu_with_track,
        SUM(CASE WHEN COALESCE(image_rows, 0) > 0 THEN 1 ELSE 0 END) AS video_spu_hit_image_source,
        SUM(CASE WHEN COALESCE(dim_rows, 0) > 0 THEN 1 ELSE 0 END) AS video_spu_hit_dim,
        SUM(CASE WHEN video_has_mid = 1 AND COALESCE(image_has_mid, 0) = 0 THEN 1 ELSE 0 END) AS missing_mid_in_source_spu,
        SUM(CASE WHEN video_has_track = 1 AND COALESCE(image_has_track, 0) = 0 THEN 1 ELSE 0 END) AS missing_track_in_source_spu,
        SUM(CASE WHEN video_has_mid = 1 AND COALESCE(dim_has_mid, 0) = 0 THEN 1 ELSE 0 END) AS missing_mid_in_dim_spu,
        SUM(CASE WHEN video_has_track = 1 AND COALESCE(dim_has_track, 0) = 0 THEN 1 ELSE 0 END) AS missing_track_in_dim_spu,
        SUM(CASE WHEN video_has_mid = 1 AND video_has_track = 1 AND (COALESCE(image_has_mid, 0) = 0 OR COALESCE(image_has_track, 0) = 0) THEN 1 ELSE 0 END) AS any_gap_in_source_spu,
        SUM(CASE WHEN video_has_mid = 1 AND video_has_track = 1 AND (COALESCE(dim_has_mid, 0) = 0 OR COALESCE(dim_has_track, 0) = 0) THEN 1 ELSE 0 END) AS any_gap_in_dim_spu
    FROM video_spu v
    LEFT JOIN image_src_spu s ON v.spu = s.spu
    LEFT JOIN dim_spu d ON v.spu = d.spu
    """
    rows = runner.exec_sql(sql, "data_dws")
    cols = [
        "video_spu_total",
        "video_spu_with_mid",
        "video_spu_with_track",
        "video_spu_hit_image_source",
        "video_spu_hit_dim",
        "missing_mid_in_source_spu",
        "missing_track_in_source_spu",
        "missing_mid_in_dim_spu",
        "missing_track_in_dim_spu",
        "any_gap_in_source_spu",
        "any_gap_in_dim_spu",
    ]
    return {col: to_int(value_at(rows, 0, idx, 0)) for idx, col in enumerate(cols)}


def query_missing_spu_details(runner: DlcRunner) -> pd.DataFrame:
    sql = f"""
    {build_common_cte()}
    SELECT
        v.spu,
        v.video_mid_cate,
        v.video_track,
        COALESCE(s.image_mid_cate, '') AS source_mid_cate,
        COALESCE(s.image_track, '') AS source_track,
        COALESCE(d.dim_mid_cate, '') AS dim_mid_cate,
        COALESCE(d.dim_track, '') AS dim_track,
        COALESCE(s.image_rows, 0) AS image_rows,
        COALESCE(d.dim_rows, 0) AS dim_rows,
        CASE WHEN v.video_has_mid = 1 AND COALESCE(s.image_has_mid, 0) = 0 THEN 1 ELSE 0 END AS missing_mid_in_source,
        CASE WHEN v.video_has_track = 1 AND COALESCE(s.image_has_track, 0) = 0 THEN 1 ELSE 0 END AS missing_track_in_source,
        CASE WHEN v.video_has_mid = 1 AND COALESCE(d.dim_has_mid, 0) = 0 THEN 1 ELSE 0 END AS missing_mid_in_dim,
        CASE WHEN v.video_has_track = 1 AND COALESCE(d.dim_has_track, 0) = 0 THEN 1 ELSE 0 END AS missing_track_in_dim
    FROM video_spu v
    LEFT JOIN image_src_spu s ON v.spu = s.spu
    LEFT JOIN dim_spu d ON v.spu = d.spu
    WHERE (v.video_has_mid = 1 AND COALESCE(s.image_has_mid, 0) = 0)
       OR (v.video_has_track = 1 AND COALESCE(s.image_has_track, 0) = 0)
       OR (v.video_has_mid = 1 AND COALESCE(d.dim_has_mid, 0) = 0)
       OR (v.video_has_track = 1 AND COALESCE(d.dim_has_track, 0) = 0)
    ORDER BY
        missing_mid_in_source DESC,
        missing_track_in_source DESC,
        missing_mid_in_dim DESC,
        missing_track_in_dim DESC,
        image_rows ASC,
        dim_rows ASC,
        v.spu ASC
    """
    rows = runner.exec_sql(sql, "data_dws")
    return pd.DataFrame(
        rows,
        columns=[
            "spu",
            "video_mid_cate",
            "video_track",
            "source_mid_cate",
            "source_track",
            "dim_mid_cate",
            "dim_track",
            "image_rows",
            "dim_rows",
            "missing_mid_in_source",
            "missing_track_in_source",
            "missing_mid_in_dim",
            "missing_track_in_dim",
        ],
    )


def query_missing_value_sets(runner: DlcRunner) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    specs = [
        (
            "missing_mid_values",
            """
            WITH video_vals AS (
                SELECT DISTINCT TRIM(CAST(mid_cate AS STRING)) AS val
                FROM data_dws.dws_short_video_product_info
                WHERE mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> ''
            ),
            source_vals AS (
                SELECT DISTINCT TRIM(CAST(mid_cate AS STRING)) AS val
                FROM data_dws.dws_platform_file_resource_label_id
                WHERE file_type = '图片' AND mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> ''
            ),
            dim_vals AS (
                SELECT DISTINCT TRIM(CAST(mid_cate AS STRING)) AS val
                FROM data_dim.dim_picture_material_data_enriched
                WHERE mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> ''
            )
            SELECT
                v.val AS mid_cate,
                CASE WHEN s.val IS NULL THEN 1 ELSE 0 END AS missing_in_source,
                CASE WHEN d.val IS NULL THEN 1 ELSE 0 END AS missing_in_dim
            FROM video_vals v
            LEFT JOIN source_vals s ON v.val = s.val
            LEFT JOIN dim_vals d ON v.val = d.val
            WHERE s.val IS NULL OR d.val IS NULL
            ORDER BY v.val
            """,
            ["mid_cate", "missing_in_source", "missing_in_dim"],
        ),
        (
            "missing_track_values",
            """
            WITH video_vals AS (
                SELECT DISTINCT TRIM(CAST(track AS STRING)) AS val
                FROM data_dws.dws_short_video_product_info
                WHERE track IS NOT NULL AND TRIM(CAST(track AS STRING)) <> ''
            ),
            source_vals AS (
                SELECT DISTINCT TRIM(CAST(sub_track AS STRING)) AS val
                FROM data_dws.dws_platform_file_resource_label_id
                WHERE file_type = '图片' AND sub_track IS NOT NULL AND TRIM(CAST(sub_track AS STRING)) <> ''
            ),
            dim_vals AS (
                SELECT DISTINCT TRIM(CAST(track_first_li_ning_bi AS STRING)) AS val
                FROM data_dim.dim_picture_material_data_enriched
                WHERE track_first_li_ning_bi IS NOT NULL AND TRIM(CAST(track_first_li_ning_bi AS STRING)) <> ''
            )
            SELECT
                v.val AS track,
                CASE WHEN s.val IS NULL THEN 1 ELSE 0 END AS missing_in_source,
                CASE WHEN d.val IS NULL THEN 1 ELSE 0 END AS missing_in_dim
            FROM video_vals v
            LEFT JOIN source_vals s ON v.val = s.val
            LEFT JOIN dim_vals d ON v.val = d.val
            WHERE s.val IS NULL OR d.val IS NULL
            ORDER BY v.val
            """,
            ["track", "missing_in_source", "missing_in_dim"],
        ),
    ]
    for key, sql, cols in specs:
        rows = runner.exec_sql(sql, "data_dws")
        result[key] = pd.DataFrame(rows, columns=cols)
    return result


def query_missing_pairs(runner: DlcRunner) -> pd.DataFrame:
    sql = """
    WITH video_pairs AS (
        SELECT
            TRIM(CAST(mid_cate AS STRING)) AS mid_cate,
            TRIM(CAST(track AS STRING)) AS track,
            COUNT(*) AS video_rows,
            COUNT(DISTINCT TRIM(CAST(spu AS STRING))) AS video_spu_count
        FROM data_dws.dws_short_video_product_info
        WHERE spu IS NOT NULL AND TRIM(CAST(spu AS STRING)) <> ''
          AND mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> ''
          AND track IS NOT NULL AND TRIM(CAST(track AS STRING)) <> ''
        GROUP BY TRIM(CAST(mid_cate AS STRING)), TRIM(CAST(track AS STRING))
    ),
    source_pairs AS (
        SELECT DISTINCT
            TRIM(CAST(mid_cate AS STRING)) AS mid_cate,
            TRIM(CAST(sub_track AS STRING)) AS track
        FROM data_dws.dws_platform_file_resource_label_id
        WHERE file_type = '图片'
          AND mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> ''
          AND sub_track IS NOT NULL AND TRIM(CAST(sub_track AS STRING)) <> ''
    ),
    dim_pairs AS (
        SELECT DISTINCT
            TRIM(CAST(mid_cate AS STRING)) AS mid_cate,
            TRIM(CAST(track_first_li_ning_bi AS STRING)) AS track
        FROM data_dim.dim_picture_material_data_enriched
        WHERE mid_cate IS NOT NULL AND TRIM(CAST(mid_cate AS STRING)) <> ''
          AND track_first_li_ning_bi IS NOT NULL AND TRIM(CAST(track_first_li_ning_bi AS STRING)) <> ''
    )
    SELECT
        v.mid_cate,
        v.track,
        v.video_rows,
        v.video_spu_count,
        CASE WHEN s.mid_cate IS NULL THEN 1 ELSE 0 END AS missing_in_source,
        CASE WHEN d.mid_cate IS NULL THEN 1 ELSE 0 END AS missing_in_dim
    FROM video_pairs v
    LEFT JOIN source_pairs s
        ON v.mid_cate = s.mid_cate AND v.track = s.track
    LEFT JOIN dim_pairs d
        ON v.mid_cate = d.mid_cate AND v.track = d.track
    WHERE s.mid_cate IS NULL OR d.mid_cate IS NULL
    ORDER BY v.video_spu_count DESC, v.video_rows DESC, v.mid_cate ASC, v.track ASC
    """
    rows = runner.exec_sql(sql, "data_dws")
    return pd.DataFrame(rows, columns=["mid_cate", "track", "video_rows", "video_spu_count", "missing_in_source", "missing_in_dim"])


def inspect_sql_mapping(sql_path: Path) -> list[dict[str, Any]]:
    patterns = [
        ("source_mid_track_read", "dws.mid_cate,", 1),
        ("source_track_read", "dws.sub_track,", 1),
        ("dim_mid_write", "        mid_cate,", 200),
        ("dim_track_write", "sub_track AS track_first_li_ning_bi,", 200),
        ("dim_reference_mid", "mid_cate AS reference_mid_cate,", 200),
        ("dim_reference_track", "sub_track AS reference_track,", 200),
    ]
    lines = sql_path.read_text(encoding="utf-8").splitlines()
    findings: list[dict[str, Any]] = []
    for key, pattern, start_line in patterns:
        for idx, line in enumerate(lines, start=1):
            if idx < start_line:
                continue
            if pattern in line:
                findings.append({"pattern_key": key, "line_no": idx, "line_text": line.strip()})
                break
    return findings


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


def truncate_text(text: Any, limit: int = 70) -> str:
    raw = str(text) if text is not None else ""
    return raw if len(raw) <= limit else raw[: limit - 3] + "..."


def build_pdf_table(rows: list[list[Any]], col_widths: list[float], style) -> LongTable:
    table = LongTable(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(style)
    return table


def write_pdf(
    output_path: Path,
    summary: dict[str, int],
    sql_findings: list[dict[str, Any]],
    missing_values: dict[str, pd.DataFrame],
    missing_pairs: pd.DataFrame,
    missing_spu: pd.DataFrame,
) -> None:
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
    story.append(Paragraph("图片中类-赛道缺口检测报告", title_style))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", body_style))
    story.append(Paragraph("基准口径：以 data_dws.dws_short_video_product_info 的中类-赛道为参照，检查图片来源链路在 data_dws.dws_platform_file_resource_label_id 与 data_dim.dim_picture_material_data_enriched 两层的缺口。", body_style))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("一、链路溯源", heading_style))
    mapping_rows = [["pattern_key", "line_no", "line_text"]]
    for item in sql_findings:
        mapping_rows.append([item["pattern_key"], item["line_no"], truncate_text(item["line_text"], 78)])
    story.append(build_pdf_table(mapping_rows, [35 * mm, 18 * mm, 120 * mm], table_style))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("结论：current-table-01.sql 直接从 data_dws.dws_platform_file_resource_label_id 读取 dws.mid_cate / dws.sub_track，并直接写入 dim_picture_material_data_enriched 的 mid_cate / track_first_li_ning_bi / reference_track，因此来源层缺失会直接传递到图片 DIM。", body_style))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("二、SPU 缺口概览", heading_style))
    summary_rows = [["metric", "value"]]
    for key, value in summary.items():
        summary_rows.append([key, value])
    story.append(build_pdf_table(summary_rows, [90 * mm, 45 * mm], table_style))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("三、缺失的中类 / 赛道取值", heading_style))
    for name, df in missing_values.items():
        rows = [list(df.columns)]
        for row in df.itertuples(index=False):
            rows.append(list(row))
        story.append(Paragraph(name, body_style))
        story.append(build_pdf_table(rows, [70 * mm, 30 * mm, 30 * mm], table_style))
        story.append(Spacer(1, 3 * mm))

    story.append(Paragraph("四、视频侧存在但图片链路缺失的中类-赛道组合", heading_style))
    pair_rows = [list(missing_pairs.columns)]
    for row in missing_pairs.head(80).itertuples(index=False):
        pair_rows.append([row.mid_cate, row.track, int(row.video_rows), int(row.video_spu_count), int(row.missing_in_source), int(row.missing_in_dim)])
    story.append(build_pdf_table(pair_rows, [42 * mm, 40 * mm, 18 * mm, 20 * mm, 18 * mm, 18 * mm], table_style))
    story.append(PageBreak())

    story.append(Paragraph("五、SPU 缺口样本", heading_style))
    sample_rows = [list(missing_spu.columns)]
    for row in missing_spu.head(120).itertuples(index=False):
        sample_rows.append(
            [
                truncate_text(row.spu, 18),
                truncate_text(row.video_mid_cate, 18),
                truncate_text(row.video_track, 18),
                truncate_text(row.source_mid_cate, 18),
                truncate_text(row.source_track, 18),
                int(row.missing_mid_in_source),
                int(row.missing_track_in_source),
                int(row.missing_mid_in_dim),
                int(row.missing_track_in_dim),
            ]
        )
    story.append(build_pdf_table(sample_rows, [22 * mm, 26 * mm, 26 * mm, 26 * mm, 26 * mm, 16 * mm, 16 * mm, 16 * mm, 16 * mm], table_style))

    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
    doc.build(story)


def write_markdown(
    output_path: Path,
    summary: dict[str, int],
    sql_findings: list[dict[str, Any]],
    missing_values: dict[str, pd.DataFrame],
    missing_pairs: pd.DataFrame,
    missing_spu: pd.DataFrame,
) -> None:
    lines: list[str] = []
    lines.append("# 图片中类-赛道缺口检测报告")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## 一、链路溯源")
    lines.append("")
    for item in sql_findings:
        lines.append(f"- `{item['pattern_key']}`: 第 {item['line_no']} 行，`{item['line_text']}`")
    lines.append("")
    lines.append("结论：`current-table-01.sql` 从 `data_dws.dws_platform_file_resource_label_id` 读取 `mid_cate` 与 `sub_track`，直接写入 `dim_picture_material_data_enriched.mid_cate` 与 `track_first_li_ning_bi/reference_track`。来源层缺失不会在当前链路内被补齐。")
    lines.append("")
    lines.append("## 二、SPU 缺口概览")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---:|")
    for key, value in summary.items():
        lines.append(f"| {key} | {value} |")
    lines.append("")
    lines.append("## 三、缺失的中类 / 赛道取值")
    lines.append("")
    for name, df in missing_values.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| value | missing_in_source | missing_in_dim |")
        lines.append("|---|---:|---:|")
        for row in df.itertuples(index=False):
            lines.append(f"| {row[0]} | {int(row[1])} | {int(row[2])} |")
        lines.append("")
    lines.append("## 四、视频侧存在但图片链路缺失的中类-赛道组合")
    lines.append("")
    lines.append("| mid_cate | track | video_rows | video_spu_count | missing_in_source | missing_in_dim |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for row in missing_pairs.itertuples(index=False):
        lines.append(f"| {row.mid_cate} | {row.track} | {int(row.video_rows)} | {int(row.video_spu_count)} | {int(row.missing_in_source)} | {int(row.missing_in_dim)} |")
    lines.append("")
    lines.append("## 五、SPU 缺口样本")
    lines.append("")
    lines.append("| spu | video_mid_cate | video_track | source_mid_cate | source_track | dim_mid_cate | dim_track | missing_mid_in_source | missing_track_in_source | missing_mid_in_dim | missing_track_in_dim |")
    lines.append("|---|---|---|---|---|---|---|---:|---:|---:|---:|")
    for row in missing_spu.head(120).itertuples(index=False):
        lines.append(
            f"| {row.spu} | {row.video_mid_cate} | {row.video_track} | {row.source_mid_cate} | {row.source_track} | {row.dim_mid_cate} | {row.dim_track} | {int(row.missing_mid_in_source)} | {int(row.missing_track_in_source)} | {int(row.missing_mid_in_dim)} | {int(row.missing_track_in_dim)} |"
        )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检测图片链路中类-赛道缺口")
    parser.add_argument("--sql-path", default=str(DEFAULT_SQL_PATH), help="current-table-01.sql 路径")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--max-wait", type=int, default=300, help="单条 SQL 最长等待秒数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    sql_path = Path(args.sql_path).resolve()

    runner = DlcRunner(os.environ.get("DLC_USER"), os.environ.get("DLC_PASSWORD"), args.max_wait)
    print("[1/5] 读取 current-table-01.sql 链路映射...", flush=True)
    sql_findings = inspect_sql_mapping(sql_path)
    print("[2/5] 统计 SPU 缺口概览...", flush=True)
    summary = query_summary(runner)
    print("[3/5] 统计中类/赛道缺失取值...", flush=True)
    missing_values = query_missing_value_sets(runner)
    print("[4/5] 统计中类-赛道组合缺口...", flush=True)
    missing_pairs = query_missing_pairs(runner)
    print("[5/5] 抽取 SPU 缺口明细...", flush=True)
    missing_spu = query_missing_spu_details(runner)

    date_tag = now_tag()
    md_path = output_dir / f"picture-mid-track-gap-report-{date_tag}.md"
    json_path = output_dir / f"picture-mid-track-gap-report-{date_tag}.json"
    xlsx_path = output_dir / f"picture-mid-track-gap-report-{date_tag}.xlsx"
    pdf_path = output_dir / f"picture-mid-track-gap-report-{date_tag}.pdf"

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sql_path": str(sql_path),
        "sql_findings": sql_findings,
        "summary": summary,
        "missing_values": {key: df.to_dict(orient="records") for key, df in missing_values.items()},
        "missing_pairs": missing_pairs.to_dict(orient="records"),
        "missing_spu_details": missing_spu.to_dict(orient="records"),
    }
    write_markdown(md_path, summary, sql_findings, missing_values, missing_pairs, missing_spu)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_excel(
        xlsx_path,
        {
            "summary": pd.DataFrame([{"metric": key, "value": value} for key, value in summary.items()]),
            "sql_mapping": pd.DataFrame(sql_findings),
            "missing_mid_values": missing_values["missing_mid_values"],
            "missing_track_values": missing_values["missing_track_values"],
            "missing_pairs": missing_pairs,
            "missing_spu": missing_spu,
        },
    )
    write_pdf(pdf_path, summary, sql_findings, missing_values, missing_pairs, missing_spu)

    print("[OK] MD:", md_path)
    print("[OK] JSON:", json_path)
    print("[OK] XLSX:", xlsx_path)
    print("[OK] PDF:", pdf_path)


if __name__ == "__main__":
    main()
