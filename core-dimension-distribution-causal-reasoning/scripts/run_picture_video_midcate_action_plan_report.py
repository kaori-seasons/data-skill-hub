#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

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
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle
except ImportError as exc:
    raise SystemExit("缺少 reportlab，请先安装：python -m pip install reportlab") from exc


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR
DEFAULT_INPUT_JSON = SCRIPT_DIR / "picture-video-midcate-rule-gap-report-20260420.json"


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d")


def confidence_rank(value: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(value, 3)


def explicit_merge_mapping() -> dict[str, tuple[str, str, str]]:
    return {
        "短袖": ("T恤类", "high", "字面上是 T 恤家族的简写，优先归并到既有 `T恤类`。"),
        "短袖衫": ("T恤类", "high", "与 `T恤类` 的产品语义接近，属于命名粒度差异。"),
        "长袖衫": ("T恤类", "medium", "更像长袖 T 恤表达，优先考虑归并到 `T恤类`。"),
        "短袖套装": ("套装类", "high", "属于套装的细分命名，应归并到既有 `套装类`。"),
        "长袖套装": ("套装类", "high", "属于套装的细分命名，应归并到既有 `套装类`。"),
        "梭织运动套装": ("套装类", "high", "材质前缀不改变主类，应归并到 `套装类`。"),
        "配件套装": ("套装类", "medium", "仍然是套装表达，建议先并入 `套装类`。"),
        "紧身衣套装": ("套装类", "medium", "优先按套装主类归并。"),
        "套装(上-短袖T恤/下-运动短裤)": ("套装类", "high", "这是套装类的展开描述，应收敛到 `套装类`。"),
        "专业跑步鞋": ("跑步鞋类", "high", "是跑步鞋类的更细颗粒度命名。"),
        "基础跑步鞋": ("跑步鞋类", "high", "是跑步鞋类的更细颗粒度命名。"),
        "老爹鞋": ("运动生活鞋类", "medium", "更像风格/楦型表达，宜先归并到广义生活鞋类。"),
        "运动鞋": ("运动生活鞋类", "medium", "过于泛化，宜先收敛到广义鞋类标准枚举。"),
        "复古慢跑鞋": ("运动生活鞋类", "medium", "属于生活化鞋型命名，先归并到生活鞋类。"),
        "休闲鞋": ("运动生活鞋类", "medium", "属于生活鞋类命名。"),
        "帆布鞋": ("运动生活鞋类", "medium", "与既有生活鞋类更接近。"),
        "学步鞋": ("童鞋类", "medium", "核心是儿童鞋履，优先并到 `童鞋类`。"),
        "工作鞋": ("运动生活鞋类", "low", "缺乏独立视频类目支撑，先作为生活鞋类候选归并。"),
        "棉鞋": ("运动生活鞋类", "low", "更像季节性鞋型，优先并入生活鞋类。"),
        "灯鞋": ("运动生活鞋类", "low", "功能款式命名，先归并到生活鞋类。"),
        "泡泡鞋": ("运动生活鞋类", "low", "款式表达，优先归并到生活鞋类。"),
        "高帮鞋": ("运动生活鞋类", "medium", "鞋帮高度是风格属性，先归并到生活鞋类。"),
        "洞洞鞋": ("运动生活鞋类", "medium", "鞋型表达，先归并到生活鞋类。"),
        "商务休闲鞋": ("运动生活鞋类", "low", "当前视频标准类目未见更细分商务鞋，先并生活鞋类。"),
        "中国李宁鞋类": ("运动生活鞋类", "low", "品牌口径混入中类，优先消解到广义鞋类。"),
        "闪钻鞋": ("运动生活鞋类", "low", "装饰风格词，不宜单列为视频标准中类。"),
        "浅口单鞋": ("运动生活鞋类", "low", "鞋型表达，先并入生活鞋类。"),
        "拖鞋": ("运动生活鞋类", "medium", "当前视频类目没有独立拖鞋标准，先并入广义鞋类。"),
        "露趾凉鞋": ("运动生活鞋类", "low", "是凉鞋的细分鞋型，先并入广义鞋类。"),
        "包头凉鞋": ("运动生活鞋类", "low", "是凉鞋的细分鞋型，先并入广义鞋类。"),
        "玛丽珍": ("运动生活鞋类", "low", "鞋型风格名，优先并入广义鞋类。"),
        "健步鞋": ("健身鞋类", "medium", "更贴近训练/健步场景，可先并 `健身鞋类`。"),
        "综合训练鞋": ("健身鞋类", "high", "训练鞋语义明确，优先并到 `健身鞋类`。"),
        "羽绒外套": ("羽绒服类", "high", "本质仍是羽绒服饰类。"),
        "棉外套": ("棉服类", "high", "本质仍是棉服家族。"),
        "软壳衣": ("冲锋衣类", "medium", "当前视频侧已有户外上装标准，软壳更适合作为其子表达。"),
        "抓绒厚外套": ("抓绒衣类", "high", "抓绒语义明确，应归并到 `抓绒衣类`。"),
        "运动上衣类": ("针织运动上衣", "high", "当前视频已有更接近的标准中类。"),
        "比赛上衣": ("专业比赛服类", "high", "比赛上衣应作为比赛服的细分表达。"),
        "毛织/开衫": ("编织衫类", "high", "针织/开衫与编织衫类高度同义。"),
        "针织衫": ("编织衫类", "high", "与编织衫类高度同义。"),
        "专业锻炼服": ("专业比赛服类", "medium", "专业训练服与比赛服类存在较强口径重合。"),
        "防晒服": ("外套", "medium", "更像功能型外套表达，可先归并到 `外套`。"),
        "长裤": ("运动裤类", "medium", "通用裤装表达，宜先收敛到 `运动裤类`。"),
        "短裤": ("运动裤类", "medium", "通用裤装表达，宜先收敛到 `运动裤类`。"),
        "九分裤": ("运动裤类", "medium", "裤长差异更像子属性。"),
        "梭织长裤": ("运动裤类", "medium", "材质+裤型，不必单立视频中类。"),
        "速干裤类": ("运动裤类", "medium", "功能型裤装表达，宜先并入运动裤类。"),
        "紧身裤": ("紧身衣", "medium", "当前视频标准没有独立紧身裤类，先与紧身类体系归并。"),
        "冲锋裤类": ("软壳裤", "medium", "当前视频侧已有更接近的户外裤装标准。"),
        "抓绒裤类": ("软壳裤", "low", "视频侧缺少独立抓绒裤标准，先临时并入户外裤类。"),
        "双肩背包": ("包类", "high", "明显是包类的细分表达。"),
        "其他包": ("包类", "high", "明显是包类的兜底表达。"),
        "羽绒背心": ("马甲类", "high", "核心仍是背心/马甲形态。"),
        "背心": ("马甲类", "medium", "当前视频侧已有 `马甲类`，优先收敛。"),
        "吊带/背心类": ("马甲类", "low", "与马甲/背心家族有交集，但仍需业务确认是否拆分。"),
    }


def explicit_add_mapping() -> dict[str, tuple[str, str, str]]:
    return {
        "裙类": ("裙类", "high", "视频侧当前没有裙装标准中类，这更像新业务家族，而不是旧类别名。"),
        "半裙": ("半裙", "high", "裙装家族在视频侧缺失，应作为新增候选。"),
        "连衣裙": ("连衣裙", "high", "裙装家族在视频侧缺失，应作为新增候选。"),
        "背带裙": ("背带裙", "high", "裙装家族在视频侧缺失，应作为新增候选。"),
        "游泳衣类": ("游泳衣类", "high", "游泳服饰家族在视频侧整体缺失，应优先新增。"),
        "泳具类": ("泳具类", "high", "游泳器具家族在视频侧整体缺失，应优先新增。"),
        "泳装": ("泳装", "high", "游泳服饰家族在视频侧整体缺失，应优先新增。"),
        "泳帽": ("泳帽", "high", "游泳配件家族在视频侧缺失，应优先新增。"),
        "泳镜": ("泳镜", "high", "游泳配件家族在视频侧缺失，应优先新增。"),
        "内衣": ("内衣", "high", "视频侧当前没有内衣标准中类，应作为新增候选。"),
        "运动内衣": ("运动内衣", "high", "视频侧当前没有运动内衣标准中类，应作为新增候选。"),
        "运动型内衣": ("运动型内衣", "high", "视频侧当前没有运动内衣标准中类，应作为新增候选。"),
        "连体衣": ("连体衣", "high", "视频侧无对应标准家族。"),
        "连身衣": ("连身衣", "high", "视频侧无对应标准家族。"),
        "球类": ("球类", "high", "是图片侧稳定存在的新家族，视频来源层与历史规则都未覆盖。"),
        "拍类": ("拍类", "high", "是图片侧稳定存在的新家族，视频侧没有同名标准。"),
        "匹克球拍": ("匹克球拍", "high", "匹克球器材在视频侧尚无标准中类。"),
        "匹克球": ("匹克球", "high", "匹克球器材在视频侧尚无标准中类。"),
        "网球拍": ("网球拍", "high", "网球器材家族在视频侧尚无标准中类。"),
        "网球线": ("网球线", "high", "网球器材家族在视频侧尚无标准中类。"),
        "网球": ("网球", "high", "网球器材家族在视频侧尚无标准中类。"),
        "壁球拍": ("壁球拍", "high", "壁球器材家族在视频侧尚无标准中类。"),
        "壁球": ("壁球", "high", "壁球器材家族在视频侧尚无标准中类。"),
        "羽毛球柄皮": ("羽毛球柄皮", "high", "虽然同属羽毛球家族，但器材子类差异明显，直接并拍/球/线会损失业务语义。"),
        "球拍配件类": ("球拍配件类", "high", "器材配件家族在视频侧尚无标准中类。"),
        "器械类": ("器械类", "high", "视频侧无对应器械大类。"),
        "小器材": ("小器材", "high", "视频侧无对应器材大类。"),
        "耗材": ("耗材", "high", "耗材不是现有视频中类的自然别名。"),
        "基础护具": ("基础护具", "high", "护具家族在视频侧缺失。"),
        "护具类": ("护具类", "high", "护具家族在视频侧缺失。"),
        "围巾": ("围巾", "medium", "与现有包/帽/袜类差异较大，更像新增配件中类。"),
        "水壶": ("水壶", "high", "视频侧无对应器材配件标准。"),
        "公仔": ("公仔", "high", "不属于现有视频商品中类。"),
        "玩偶": ("玩偶", "high", "不属于现有视频商品中类。"),
        "配饰类": ("配饰类", "medium", "现有视频中类没有可直接承接的配饰总类。"),
        "其它配件": ("其它配件", "medium", "现有视频配件中类缺少统一容器。"),
        "其他配件": ("其他配件", "medium", "现有视频配件中类缺少统一容器。"),
        "运动用品": ("运动用品", "medium", "现有视频标准中类无法自然承接。"),
        "运动装备": ("运动装备", "medium", "现有视频标准中类无法自然承接。"),
        "推广品类": ("推广品类", "medium", "更像业务经营口径，不建议硬并入现有商品中类。"),
        "赠品": ("赠品", "high", "不属于现有视频商品中类。"),
        "乒乓球鞋类": ("乒乓球鞋类", "high", "运动项目清晰，当前视频鞋类标准未覆盖。"),
        "网球鞋类": ("网球鞋类", "high", "运动项目清晰，当前视频鞋类标准未覆盖。"),
        "高尔夫鞋": ("高尔夫鞋", "high", "运动项目清晰，当前视频鞋类标准未覆盖。"),
        "田径鞋类": ("田径鞋类", "high", "运动项目清晰，当前视频鞋类标准未覆盖。"),
        "滑雪服": ("滑雪服", "high", "运动项目清晰，当前视频服装标准未覆盖。"),
        "婴幼儿服装类": ("婴幼儿服装类", "high", "视频侧当前无婴幼儿服装标准中类。"),
        "防撞服": ("防撞服", "high", "专项功能服在视频侧未形成现有标准枚举。"),
        "夹棉裤类": ("夹棉裤类", "medium", "冬季裤装在视频侧无独立标准，更像新增候选。"),
        "羽绒裤类": ("羽绒裤类", "medium", "冬季裤装在视频侧无独立标准，更像新增候选。"),
    }


def classify_row(row: dict[str, Any]) -> dict[str, Any]:
    enum_value = str(row["enum_value"])
    merge_map = explicit_merge_mapping()
    add_map = explicit_add_mapping()

    if row.get("rule_status") == "历史规则目标已定义":
        row["action_bucket"] = "归并候选"
        row["proposed_enum"] = row.get("suggested_target") or enum_value
        row["confidence"] = "high"
        row["reason"] = "历史视频规整规则已经把该值定义为标准目标枚举，应优先视作覆盖/来源问题，而不是新增枚举。"
        return row

    if enum_value in merge_map:
        target, confidence, reason = merge_map[enum_value]
        row["action_bucket"] = "归并候选"
        row["proposed_enum"] = target
        row["confidence"] = confidence
        row["reason"] = reason
        return row

    if enum_value in add_map:
        target, confidence, reason = add_map[enum_value]
        row["action_bucket"] = "新增候选"
        row["proposed_enum"] = target
        row["confidence"] = confidence
        row["reason"] = reason
        return row

    family_bucket = row.get("family_bucket", "")
    if family_bucket == "鞋靴":
        row["action_bucket"] = "归并候选"
        row["proposed_enum"] = "运动生活鞋类"
        row["confidence"] = "low"
        row["reason"] = "落在鞋靴家族，但未命中明确规则；暂按广义鞋类归并，需人工复核。"
    elif family_bucket == "裤装":
        row["action_bucket"] = "归并候选"
        row["proposed_enum"] = "运动裤类"
        row["confidence"] = "low"
        row["reason"] = "落在裤装家族，但未命中明确规则；暂按广义裤装归并，需人工复核。"
    elif family_bucket == "上装":
        row["action_bucket"] = "归并候选"
        row["proposed_enum"] = "外套"
        row["confidence"] = "low"
        row["reason"] = "落在上装家族，但未命中明确规则；暂按广义上装归并，需人工复核。"
    elif family_bucket == "套装":
        row["action_bucket"] = "归并候选"
        row["proposed_enum"] = "套装类"
        row["confidence"] = "medium"
        row["reason"] = "落在套装家族，优先收敛到现有 `套装类`。"
    else:
        row["action_bucket"] = "新增候选"
        row["proposed_enum"] = enum_value
        row["confidence"] = "low"
        row["reason"] = "未命中明确归并规则，也没有现成视频标准枚举能自然承接，先列为新增候选。"
    return row


def build_summary_df(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "total_uncovered_count": int(len(df.index)),
                "add_candidate_count": int((df["action_bucket"] == "新增候选").sum()),
                "merge_candidate_count": int((df["action_bucket"] == "归并候选").sum()),
                "high_confidence_count": int((df["confidence"] == "high").sum()),
                "medium_confidence_count": int((df["confidence"] == "medium").sum()),
                "low_confidence_count": int((df["confidence"] == "low").sum()),
            }
        ]
    )


def build_bucket_summary_df(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for bucket in ["新增候选", "归并候选"]:
        part = df[df["action_bucket"] == bucket].copy()
        family_summary = (
            part.groupby("family_bucket", dropna=False)
            .agg(enum_count=("enum_value", "count"), picture_rows=("picture_row_count", "sum"), picture_spus=("picture_spu_count", "sum"))
            .reset_index()
            .sort_values(by=["enum_count", "picture_rows"], ascending=[False, False])
        )
        for row in family_summary.itertuples(index=False):
            rows.append(
                {
                    "action_bucket": bucket,
                    "family_bucket": row.family_bucket,
                    "enum_count": int(row.enum_count),
                    "picture_rows": int(row.picture_rows),
                    "picture_spus": int(row.picture_spus),
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


def build_pdf(pdf_path: Path, summary_df: pd.DataFrame, bucket_df: pd.DataFrame, add_df: pd.DataFrame, merge_df: pd.DataFrame) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], fontName="STSong-Light", fontSize=18, leading=22)
    body_style = ParagraphStyle("body", parent=styles["BodyText"], fontName="STSong-Light", fontSize=9, leading=12)
    small_style = ParagraphStyle("small", parent=styles["BodyText"], fontName="STSong-Light", fontSize=8, leading=10)

    story: list[Any] = []
    story.append(Paragraph("图片独有中类下一步处置拆分报告", title_style))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", body_style))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("口径：基于上一份“图片独有中类 vs 视频规则覆盖报告”，把 108 个“历史规则未覆盖”的中类继续拆成“新增视频标准枚举候选”与“归并到现有视频标准枚举候选”。这里是启发式建议，不是最终业务字典。", body_style))
    story.append(Spacer(1, 4 * mm))

    summary_rows = [["指标", "数值"]]
    for col, value in summary_df.iloc[0].to_dict().items():
        summary_rows.append([col, str(value)])
    summary_table = LongTable(summary_rows, colWidths=[90 * mm, 30 * mm], repeatRows=1)
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B7C9E2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 4 * mm))

    bucket_rows = [["action_bucket", "family_bucket", "enum_count", "picture_rows", "picture_spus"]]
    for row in bucket_df.itertuples(index=False):
        bucket_rows.append([row.action_bucket, row.family_bucket, str(int(row.enum_count)), str(int(row.picture_rows)), str(int(row.picture_spus))])
    bucket_table = LongTable(bucket_rows, colWidths=[35 * mm, 40 * mm, 25 * mm, 30 * mm, 30 * mm], repeatRows=1)
    bucket_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E2F3")),
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B7C9E2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(bucket_table)
    story.append(PageBreak())

    def append_section(title: str, df: pd.DataFrame) -> None:
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 2 * mm))
        rows = [[
            "enum_value",
            "proposed_enum",
            "confidence",
            "picture_rows",
            "picture_spus",
            "family_bucket",
            "reason",
        ]]
        for row in df.itertuples(index=False):
            rows.append(
                [
                    Paragraph(str(row.enum_value), small_style),
                    Paragraph(str(row.proposed_enum), small_style),
                    Paragraph(str(row.confidence), small_style),
                    Paragraph(str(int(row.picture_row_count)), small_style),
                    Paragraph(str(int(row.picture_spu_count)), small_style),
                    Paragraph(str(row.family_bucket), small_style),
                    Paragraph(str(row.reason), small_style),
                ]
            )
        table = LongTable(
            rows,
            colWidths=[28 * mm, 30 * mm, 16 * mm, 18 * mm, 18 * mm, 26 * mm, 110 * mm],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B7C9E2")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(table)
        story.append(PageBreak())

    append_section("新增候选清单", add_df)
    append_section("归并候选清单", merge_df)

    doc.build(story)


def write_markdown(output_path: Path, summary_df: pd.DataFrame, bucket_df: pd.DataFrame, add_df: pd.DataFrame, merge_df: pd.DataFrame) -> None:
    lines: list[str] = []
    lines.append("# 图片独有中类下一步处置拆分报告")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    summary = summary_df.iloc[0].to_dict()
    lines.append(f"- 历史规则未覆盖的中类共 `{summary['total_uncovered_count']}` 个。")
    lines.append(f"- 其中判定为 `新增候选` 的有 `{summary['add_candidate_count']}` 个。")
    lines.append(f"- 其中判定为 `归并候选` 的有 `{summary['merge_candidate_count']}` 个。")
    lines.append(f"- 高置信 `{summary['high_confidence_count']}` 个，中置信 `{summary['medium_confidence_count']}` 个，低置信 `{summary['low_confidence_count']}` 个。")
    lines.append("")
    lines.append("## 自我反思")
    lines.append("")
    lines.append("- 这一步不再依赖实时 DLC，而是基于上一份真实差集报告做业务规则拆分。")
    lines.append("- 规则型判断的优点是可追溯，但缺点是会把一部分边界值推到低置信分组，例如 `中国李宁鞋类`、`工作鞋` 这类混合了品牌/场景的中类。")
    lines.append("- 因此，本报告更适合做治理清单，而不是直接拿去覆盖线上字典。高置信项可优先推进，低置信项建议人工复核。")
    lines.append("")
    lines.append("## 家族分布")
    lines.append("")
    lines.append("| action_bucket | family_bucket | enum_count | picture_rows | picture_spus |")
    lines.append("| --- | --- | ---: | ---: | ---: |")
    for row in bucket_df.itertuples(index=False):
        lines.append(f"| {row.action_bucket} | {row.family_bucket} | {int(row.enum_count)} | {int(row.picture_rows)} | {int(row.picture_spus)} |")
    lines.append("")

    def append_table(title: str, df: pd.DataFrame) -> None:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| enum_value | proposed_enum | confidence | picture_rows | picture_spus | family_bucket | reason |")
        lines.append("| --- | --- | --- | ---: | ---: | --- | --- |")
        for row in df.itertuples(index=False):
            lines.append(
                f"| {row.enum_value} | {row.proposed_enum} | {row.confidence} | {int(row.picture_row_count)} | "
                f"{int(row.picture_spu_count)} | {row.family_bucket} | {row.reason} |"
            )
        lines.append("")

    append_table("新增候选", add_df)
    append_table("归并候选", merge_df)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="把图片独有中类拆成新增候选与归并候选，并导出 PDF")
    parser.add_argument("--input-json", default=str(DEFAULT_INPUT_JSON), help="输入的中类规则覆盖报告 JSON")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    args = parser.parse_args()

    input_json = Path(args.input_json).resolve()
    if not input_json.exists():
        raise SystemExit(f"输入文件不存在：{input_json}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = json.loads(input_json.read_text(encoding="utf-8"))
    detail_df = pd.DataFrame(raw.get("detail", []))
    if detail_df.empty:
        raise SystemExit("输入报告 detail 为空，无法继续拆分。")

    uncovered_df = detail_df[detail_df["rule_status"] == "历史规则未覆盖"].copy()
    if uncovered_df.empty:
        raise SystemExit("没有历史规则未覆盖的中类，无需继续拆分。")

    numeric_cols = ["picture_row_count", "picture_spu_count", "video_source_row_count", "video_final_row_count"]
    for col in numeric_cols:
        if col in uncovered_df.columns:
            uncovered_df[col] = pd.to_numeric(uncovered_df[col], errors="coerce").fillna(0).astype(int)

    classified_rows = [classify_row(row) for row in uncovered_df.to_dict(orient="records")]
    classified_df = pd.DataFrame(classified_rows)
    classified_df["confidence_rank"] = classified_df["confidence"].map(confidence_rank)

    classified_df = classified_df.sort_values(
        by=["action_bucket", "confidence_rank", "picture_row_count", "picture_spu_count", "enum_value"],
        ascending=[True, True, False, False, True],
    ).drop(columns=["confidence_rank"])

    add_df = classified_df[classified_df["action_bucket"] == "新增候选"].copy()
    merge_df = classified_df[classified_df["action_bucket"] == "归并候选"].copy()
    summary_df = build_summary_df(classified_df)
    bucket_df = build_bucket_summary_df(classified_df)

    tag = now_tag()
    prefix = f"picture-video-midcate-action-plan-report-{tag}"
    md_path = output_dir / f"{prefix}.md"
    json_path = output_dir / f"{prefix}.json"
    xlsx_path = output_dir / f"{prefix}.xlsx"
    pdf_path = output_dir / f"{prefix}.pdf"

    write_markdown(md_path, summary_df, bucket_df, add_df, merge_df)
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "input_json": str(input_json),
                "summary": summary_df.to_dict(orient="records"),
                "bucket_summary": bucket_df.to_dict(orient="records"),
                "add_candidates": add_df.to_dict(orient="records"),
                "merge_candidates": merge_df.to_dict(orient="records"),
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
            "add_candidates": add_df,
            "merge_candidates": merge_df,
        },
    )
    build_pdf(pdf_path, summary_df, bucket_df, add_df, merge_df)

    print(f"[DONE] Markdown: {md_path}")
    print(f"[DONE] JSON: {json_path}")
    print(f"[DONE] Excel: {xlsx_path}")
    print(f"[DONE] PDF: {pdf_path}")


if __name__ == "__main__":
    main()
