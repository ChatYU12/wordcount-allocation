# -*- coding: utf-8 -*-
"""从 Excel / CSV 名单导入编写人员。

真实名单的列名五花八门（姓名/编写人/作者、角色/职务/署名、需要字数/目标字数/字数…），
数字还常写成「6万」「6.5w」。这里做的是尽力识别 + 明确回报识别到了什么，
识别不准的地方宁可报错也不要静默猜错。
"""
from __future__ import annotations

import csv
import io
import os
import re
from typing import Dict, List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROLE_CHIEF_EDITOR = "总主编"
ROLE_CHIEF = "主编"
ROLE_VICE = "副主编"
ROLE_MEMBER = "参编"

NAME_KEYS = ("姓名", "名字", "编写人", "作者", "人员", "编委", "教师", "署名")
ROLE_KEYS = ("角色", "职务", "身份", "岗位", "分工", "担任")
WORD_KEYS = ("需要字数", "目标字数", "分配字数", "编写字数", "任务字数", "字数", "工作量", "字")
PAIR_KEYS = ("可合作", "参与合作", "合作")

SKIP_ROW_KEYS = ("合计", "总计", "小计", "共计", "平均", "备注")

# 角色识别顺序敏感：先判「总主编」「副主编」，再判「主编」，最后才是参编
ROLE_PATTERNS = [
    (ROLE_CHIEF_EDITOR, ("总主编", "总编")),
    (ROLE_VICE, ("副主编", "副编", "副主任")),
    (ROLE_CHIEF, ("主编", "主任", "负责人", "主持")),
    (ROLE_MEMBER, ("参编", "编委", "编写", "编者", "委员", "教师", "老师")),
]


def normalize_role(raw: object) -> str:
    """把各种写法归一到四个角色。认不出来按参编处理。"""
    text = str(raw or "").strip()
    if not text:
        return ROLE_MEMBER
    for role, keys in ROLE_PATTERNS:
        for k in keys:
            if k in text:
                return role
    return ROLE_MEMBER


def parse_words(raw: object) -> Optional[int]:
    """解析字数，支持 60000 / 6万 / 6.5w / "6万" / "60000字" 等写法。"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(round(float(raw)))
    text = str(raw).strip().replace(",", "").replace("，", "").replace(" ", "")
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    val = float(m.group(1))
    unit = text[m.end():].lower()
    if unit.startswith("万") or unit.startswith("w"):
        val *= 10000
    elif unit.startswith("千") or unit.startswith("k"):
        val *= 1000
    return int(round(val))


def _match_column(header_cell: object, keys: Tuple[str, ...]) -> Optional[int]:
    """返回关键词在表头文字里的位置权重（越靠前越优先）。"""
    text = str(header_cell or "").strip()
    if not text:
        return None
    for i, k in enumerate(keys):
        if k in text:
            return i
    return None


def _find_header(rows: List[Tuple]) -> Tuple[Optional[int], Dict[str, int]]:
    """在前 12 行里找表头，返回 (表头行号, {字段: 列号})。"""
    best: Tuple[Optional[int], Dict[str, int]] = (None, {})
    for ri, row in enumerate(rows[:12]):
        cols: Dict[str, int] = {}
        scores: Dict[str, int] = {}
        for ci, cell in enumerate(row):
            for field, keys in (
                ("name", NAME_KEYS),
                ("role", ROLE_KEYS),
                ("words", WORD_KEYS),
                ("pair", PAIR_KEYS),
            ):
                if field in cols:
                    continue
                score = _match_column(cell, keys)
                if score is not None and (field not in scores or score < scores[field]):
                    cols[field], scores[field] = ci, score
        if "name" in cols and len(cols) >= 2:
            return ri, cols
        if "name" in cols and best[0] is None:
            best = (ri, cols)
    return best


def _rows_to_people(rows: List[Tuple], cols: Dict[str, int]) -> List[Dict]:
    people: List[Dict] = []
    seen = set()
    for row in rows:
        if not row:
            continue
        def cell(field: str):
            idx = cols.get(field)
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        name = str(cell("name") or "").strip()
        if not name or any(k in name for k in SKIP_ROW_KEYS):
            continue
        if name in seen:  # 同名去重，避免重复行把人算两遍
            continue
        words = parse_words(cell("words"))
        if words is None or words <= 0:
            continue
        pair_raw = str(cell("pair") or "").strip().lower()
        allow_pair = pair_raw not in ("否", "no", "n", "false", "0", "×", "x")
        seen.add(name)
        people.append({
            "name": name,
            "role": normalize_role(cell("role")),
            "target_words": words,
            "allow_pair": allow_pair,
        })
    return people


def parse_people_xlsx(path: str) -> Dict:
    """解析 xlsx 名单，返回 {ok, people, sheet, columns, warnings}。"""
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"无法打开 Excel 文件：{exc}"}

    tried: List[str] = []
    for ws in wb.worksheets:
        rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
        if not rows:
            continue
        tried.append(ws.title)
        header_idx, cols = _find_header(rows)
        if header_idx is None:
            continue
        people = _rows_to_people(rows[header_idx + 1:], cols)
        if people:
            warnings: List[str] = []
            if "role" not in cols:
                warnings.append("未识别到「角色」列，全部按参编处理，可在页面上逐行调整。")
            if "words" not in cols:
                warnings.append("未识别到「字数」列，请检查表头。")
            return {
                "ok": True,
                "people": people,
                "sheet": ws.title,
                "header_row": header_idx + 1,
                "columns": {k: v for k, v in cols.items()},
                "warnings": warnings,
            }

    if not tried:
        return {"ok": False, "error": "Excel 里没有内容。"}
    return {
        "ok": False,
        "error": (
            "没能识别出名单表头。请确认表格里至少有一列叫「姓名」，"
            "以及与它同行的「角色」「需要字数」列（列名可以写在表头上方的标题行之下）。"
        ),
        "sheets": tried,
    }


def parse_people_csv(data: bytes) -> Dict:
    """解析 CSV（UTF-8 / GBK 都试一遍，照顾 Excel 导出的中文 CSV）。"""
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return {"ok": False, "error": "无法识别 CSV 编码，请另存为 UTF-8 后重试。"}

    rows = [tuple(r) for r in csv.reader(io.StringIO(text))]
    if not rows:
        return {"ok": False, "error": "CSV 是空的。"}
    header_idx, cols = _find_header(rows)
    if header_idx is None:
        return {"ok": False, "error": "CSV 里没找到「姓名」列。"}
    people = _rows_to_people(rows[header_idx + 1:], cols)
    if not people:
        return {"ok": False, "error": "CSV 里没有有效的人员行（姓名 + 字数）。"}
    return {"ok": True, "people": people, "sheet": "CSV", "header_row": header_idx + 1,
            "columns": cols, "warnings": []}


# ---------- 模板 ----------

def build_people_template() -> io.BytesIO:
    """生成一份填写模板，减少「表头写错导致识别失败」。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "编写名单"
    head_fill = PatternFill("solid", fgColor="FFD966")
    headers = ["序号", "姓名", "角色", "需要字数", "可合作", "备注"]
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = head_fill
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    sample = [
        (1, "张三", "主编", 60000, "是", ""),
        (2, "李四", "主编", 50000, "是", ""),
        (3, "王五", "副主编", 40000, "是", "可填 6万 这样的写法"),
        (4, "赵六", "参编", 20000, "否", ""),
    ]
    for r in sample:
        ws.append(list(r))
    for i, w in enumerate([6, 12, 12, 14, 10, 24], start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    note_row = ws.max_row + 2
    ws.cell(row=note_row, column=1, value="填写说明")
    notes = [
        "1. 「序号」可留空，人员顺序按表格从上到下的顺序（也是书稿顺序）排列。",
        "2. 角色填：总主编 / 主编 / 副主编 / 参编，其他写法会按关键词归类，认不出来按参编。",
        "3. 字数可写 60000，也可写 6万 或 6.5w。",
        "4. 「可合作」填 否 表示该人不参与合作编写，留空视为可合作。",
        "5. 表头必须在，列顺序可以不同；有多余的列（部门、职称）不影响导入。",
    ]
    for i, n in enumerate(notes, start=1):
        ws.cell(row=note_row + i, column=1, value=n).alignment = Alignment(wrap_text=False)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
