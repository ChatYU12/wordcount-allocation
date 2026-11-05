# -*- coding: utf-8 -*-
"""把分配结果导出成 Excel（openpyxl）。

五个工作表：
  1. 分配总表   —— 一段一行，含课时量
  2. 按人汇总   —— 一人一行，合作段按目标比例切分
  3. 章节明细   —— 一个单元一行，标注整页图
  4. 编写任务书 —— 可直接发给作者的分工通知
  5. 计算说明   —— 口径、规则与国标依据
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEAD_FILL = PatternFill("solid", fgColor="FFD966")
HEAD_FONT = Font(bold=True, size=11)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
COOP_FILL = PatternFill("solid", fgColor="E2EFDA")   # 合作段浅绿
WARN_FILL = PatternFill("solid", fgColor="FCE4D6")   # 超差浅橙
TITLE_FONT = Font(bold=True, size=14)

DEFAULT_QUALITY = (
    "1) 按本表章节范围与字数区间交稿，超支或不足请提前沟通；"
    "2) 图表、案例须原创或已获授权并注明出处；"
    "3) 交稿为可编辑文档，体例与全书统一；"
    "4) 编校差错率控制在万分之一以内。"
)
DEFAULT_EXIT = (
    "编写人如因故退出，其负责章节由主编另行指派，已交稿部分按实际字数认定；"
    "字数超出计划部分不计入认定字数，需调剂须经主编确认。"
)


def _style_header(ws, row: int, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _autosize(ws, widths: List[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _hours(words: int, hours_per_1000: float) -> float:
    if hours_per_1000 <= 0:
        return 0.0
    return round(words / 1000.0 * hours_per_1000, 1)


def build_workbook(
    res: Dict,
    people: List[Dict],
    units: List[Dict],
    per_page_words: int,
    options: Optional[Dict] = None,
) -> io.BytesIO:
    opts = options or {}
    hours_per_1000 = float(opts.get("hours_per_1000") or 0)
    deadline = (opts.get("deadline") or "").strip()
    quality = (opts.get("quality_note") or DEFAULT_QUALITY).strip()
    exit_note = (opts.get("exit_note") or DEFAULT_EXIT).strip()
    book_title = (opts.get("book_title") or "书稿").strip()

    def hours_cell(ws, row: int, col: int, words: int) -> None:
        cell = ws.cell(row=row, column=col)
        if hours_per_1000 > 0:
            cell.value = _hours(words, hours_per_1000)
            cell.number_format = "0.0"
        else:
            cell.value = "—"
            cell.alignment = Alignment(horizontal="center")

    wb = Workbook()

    # ---------- Sheet 1：分配总表 ----------
    ws = wb.active
    ws.title = "分配总表"
    headers = [
        "序号", "角色", "姓名", "负责内容（章节）", "起始页", "结束页",
        "页数", "分配字数", "目标字数", "差额", "偏差", "折合课时", "备注",
    ]
    ws.append(headers)
    _style_header(ws, 1, len(headers))

    for seg in res["segments"]:
        role = " + ".join(p["role"] for p in seg["members"])
        name = " + ".join(p["name"] for p in seg["members"])
        labels = seg.get("chapter_text") or "；".join(seg["labels"])
        note = []
        if seg["cooperative"]:
            note.append("合作编写")
        if seg["cross_project"]:
            note.append("跨项目")
        if not seg["within_tolerance"]:
            note.append("超出容差")
        if seg.get("figure_pages"):
            note.append(f"含整页图 {seg['figure_pages']} 页")
        row = [
            seg["order"], role, name, labels, seg["start"], seg["end"],
            seg["pages"], seg["words"], seg["target"], seg["delta"],
            round(seg["delta_ratio"] * 100, 1), None, "、".join(note),
        ]
        ws.append(row)
        r = ws.max_row
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=(c == 4))
            if c == 11:
                cell.number_format = "+0.0%;-0.0%"
            if c in (8, 9, 10):
                cell.number_format = "#,##0"
        hours_cell(ws, r, 12, seg["words"])
        if seg["cooperative"]:
            for c in range(1, len(headers) + 1):
                ws.cell(row=r, column=c).fill = COOP_FILL
        if not seg["within_tolerance"]:
            ws.cell(row=r, column=11).fill = WARN_FILL

    total_row = ws.max_row + 1
    ws.cell(row=total_row, column=1, value="合计").font = Font(bold=True)
    ws.cell(row=total_row, column=4, value=f"共 {len(res['segments'])} 段")
    ws.cell(row=total_row, column=7, value=sum(s["pages"] for s in res["segments"])).number_format = "#,##0"
    ws.cell(row=total_row, column=8, value=sum(s["words"] for s in res["segments"])).number_format = "#,##0"
    ws.cell(row=total_row, column=9, value=sum(s["target"] for s in res["segments"])).number_format = "#,##0"
    hours_cell(ws, total_row, 12, sum(s["words"] for s in res["segments"]))
    for c in range(1, len(headers) + 1):
        ws.cell(row=total_row, column=c).border = BORDER
        ws.cell(row=total_row, column=c).font = Font(bold=True)

    _autosize(ws, [6, 18, 16, 46, 8, 8, 7, 11, 11, 10, 9, 10, 24])
    ws.freeze_panes = "A2"

    # ---------- Sheet 2：按人汇总 ----------
    ws2 = wb.create_sheet("按人汇总")
    h2 = [
        "姓名", "角色", "负责段数", "起始页", "结束页", "页数",
        "分配字数", "目标字数", "差额", "偏差", "折合课时", "备注",
    ]
    ws2.append(h2)
    _style_header(ws2, 1, len(h2))
    by_person: Dict[str, Dict] = {}
    for seg in res["segments"]:
        shares = seg.get("shares") or [
            {"name": m["name"], "role": m["role"], "words": seg["words"] // max(1, len(seg["members"])),
             "target": m["target_words"]}
            for m in seg["members"]
        ]
        for sh in shares:
            key = sh["name"]
            if key not in by_person:
                by_person[key] = {
                    "name": sh["name"], "role": sh["role"], "units": 0,
                    "start": seg["start"], "end": seg["end"], "pages": 0,
                    "words": 0, "target": sh.get("target", 0), "notes": [],
                }
            d = by_person[key]
            d["units"] += 1
            d["start"] = min(d["start"], seg["start"])
            d["end"] = max(d["end"], seg["end"])
            d["pages"] += seg["pages"]
            d["words"] += sh["words"]
            if seg["cooperative"]:
                partners = "、".join(m["name"] for m in seg["members"] if m["name"] != sh["name"])
                d["notes"].append(
                    f"与{partners}合作编写第{seg['start']}-{seg['end']}页"
                    f"（该段 {seg['words']:,} 字，按目标比例分得 {sh['words']:,} 字）"
                )
    for d in by_person.values():
        ratio = (d["words"] - d["target"]) / d["target"] if d["target"] else 0
        ws2.append([
            d["name"], d["role"], d["units"], d["start"], d["end"], d["pages"],
            d["words"], d["target"], d["words"] - d["target"], round(ratio * 100, 1),
            None, "；".join(d["notes"]),
        ])
        r = ws2.max_row
        for c in range(1, len(h2) + 1):
            ws2.cell(row=r, column=c).border = BORDER
        ws2.cell(row=r, column=7).number_format = "#,##0"
        ws2.cell(row=r, column=8).number_format = "#,##0"
        ws2.cell(row=r, column=9).number_format = "#,##0"
        ws2.cell(row=r, column=10).number_format = "+0.0%;-0.0%"
        hours_cell(ws2, r, 11, d["words"])
    _autosize(ws2, [10, 10, 11, 8, 8, 7, 11, 11, 10, 9, 10, 52])
    ws2.freeze_panes = "A2"

    # ---------- Sheet 3：章节明细 ----------
    ws3 = wb.create_sheet("章节明细")
    h3 = ["序号", "单元名称", "类型", "起始页", "结束页", "页数", "整页图", "字数", "归属", "合作"]
    ws3.append(h3)
    _style_header(ws3, 1, len(h3))
    owner_of = {}
    for seg in res["segments"]:
        for ui in seg["unit_idx"]:
            owner_of[ui] = {
                "names": " + ".join(p["name"] for p in seg["members"]),
                "coop": "是" if seg["cooperative"] else "",
            }
    kind_cn = {
        "project-head": "项目标题", "task": "任务",
        "project-tail": "项目检测/岗位实践/能力拓展", "ref": "参考文献",
    }
    for u in units:
        info = owner_of.get(u["index"], {"names": "—", "coop": ""})
        ws3.append([
            u["index"] + 1, u["label"], kind_cn.get(u["kind"], u["kind"]),
            u["start"], u["end"], u["pages"], u.get("figure_pages", 0),
            u["words"], info["names"], info["coop"],
        ])
        r = ws3.max_row
        for c in range(1, len(h3) + 1):
            ws3.cell(row=r, column=c).border = BORDER
        ws3.cell(row=r, column=8).number_format = "#,##0"
    _autosize(ws3, [6, 44, 26, 8, 8, 7, 8, 10, 18, 8])
    ws3.freeze_panes = "A2"

    # ---------- Sheet 4：编写任务书 ----------
    ws4 = wb.create_sheet("编写任务书")
    ws4.cell(row=1, column=1, value=f"《{book_title}》编写任务书").font = TITLE_FONT
    ws4.merge_cells(start_row=1, start_column=1, end_row=1, end_column=8)
    ws4.cell(row=2, column=1, value=f"生成时间：{datetime.now().strftime('%Y-%m-%d')}")
    if deadline:
        ws4.cell(row=2, column=4, value=f"交稿截止：{deadline}")

    h4 = ["序号", "编写人", "角色", "负责章节", "页码范围", "字数要求", "折合课时", "交稿时间"]
    ws4.append([])
    ws4.append(h4)
    head_row = ws4.max_row
    _style_header(ws4, head_row, len(h4))
    tol = res.get("tolerance", 0.05)
    for seg in res["segments"]:
        lo = int(round(seg["words"] * (1 - tol)))
        hi = int(round(seg["words"] * (1 + tol)))
        ws4.append([
            seg["order"],
            " + ".join(p["name"] for p in seg["members"]),
            " + ".join(p["role"] for p in seg["members"]),
            seg.get("chapter_text") or "；".join(seg["labels"]),
            f"第 {seg['start']}–{seg['end']} 页",
            f"{lo:,} – {hi:,} 字（基准 {seg['words']:,}）",
            _hours(seg["words"], hours_per_1000) if hours_per_1000 > 0 else "—",
            deadline or "",
        ])
        r = ws4.max_row
        for c in range(1, len(h4) + 1):
            cell = ws4.cell(row=r, column=c)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=(c == 4))
        if seg["cooperative"]:
            for c in range(1, len(h4) + 1):
                ws4.cell(row=r, column=c).fill = COOP_FILL

    r = ws4.max_row + 2
    ws4.cell(row=r, column=1, value="质量要求").font = Font(bold=True)
    ws4.cell(row=r, column=2, value=quality)
    ws4.merge_cells(start_row=r, start_column=2, end_row=r, end_column=8)
    ws4.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    ws4.row_dimensions[r].height = 58

    r += 1
    ws4.cell(row=r, column=1, value="变更与退出").font = Font(bold=True)
    ws4.cell(row=r, column=2, value=exit_note)
    ws4.merge_cells(start_row=r, start_column=2, end_row=r, end_column=8)
    ws4.cell(row=r, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    ws4.row_dimensions[r].height = 46

    r += 2
    ws4.cell(row=r, column=1, value="编写人签字：____________　　主编确认：____________　　日期：____________")
    ws4.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)

    _autosize(ws4, [6, 20, 16, 44, 16, 26, 10, 16])
    ws4.freeze_panes = f"A{head_row + 1}"

    # ---------- Sheet 5：计算说明 ----------
    ws5 = wb.create_sheet("计算说明")
    lines = [
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("字数口径", "版面字数 = 有效页数 × 每页字数；整页图按国标折减（见下）"),
        ("每页字数", per_page_words),
        ("全书可分配页数", sum(u["pages"] for u in units)),
        ("其中整页图", f"{sum(u.get('figure_pages', 0) for u in units)} 页（按满版 20% 折算）"),
        ("全书可分配字数", res["total_words"]),
        ("名单需求合计", res["total_target"]),
        ("差额（可分配 - 需求）", res["gap"]),
        ("理论最小偏差", f"±{res.get('best_bound', 0) * 100:.2f}%"),
        ("设定容差", f"±{res['tolerance'] * 100:.1f}%"),
        ("课时折算", f"每 1000 字折合 {hours_per_1000} 课时" if hours_per_1000 > 0 else "未启用"),
        (
            "分配规则",
            "任务为最小单元不拆分；项目检测/岗位实践/能力拓展跟随所属项目；"
            "每人领一段连续区间；主编可与副主编合作共担一段（两人目标字数相加比对）。",
        ),
        (
            "国标依据",
            "《图书质量管理规定》（新闻出版总署令第26号，2005-03-01 施行）附件第二条："
            "图书总字数一律以版面字数为准，总字数 = 每行字数 × 每面行数 × 总面数；"
            "正文中的插图占一面的，按正文满版字数的 20% 计算字数。",
        ),
    ]
    for k, v in lines:
        ws5.append([k, v])
        ws5.cell(row=ws5.max_row, column=1).font = Font(bold=True)
        ws5.cell(row=ws5.max_row, column=1).border = BORDER
        ws5.cell(row=ws5.max_row, column=2).border = BORDER
        ws5.cell(row=ws5.max_row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    _autosize(ws5, [24, 92])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
