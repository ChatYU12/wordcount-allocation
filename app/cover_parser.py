# -*- coding: utf-8 -*-
"""扉页编写名单识别。

支持三种输入：
  - 图片（png / jpg / jpeg / heic / tif…）—— 用 macOS Vision 框架做中文 OCR
  - PDF —— 先试文字层，没有文字层就把页面渲染成图再做 OCR
  - 纯文本 —— 直接按行解析

版式还原靠 OCR 的坐标：按 y 聚类成行、行内按 x 排序，才能把
「主　编　王春桃　龚建光　任兰梅」这种一角色多姓名的排布正确拆开。

OCR 的两个已知误差各有对策：
  - 字形误识（主审 → 主車）—— 对「主X」做兜底匹配
  - 漏字（副主编 → 主编）—— 角色必须严格降级，重复出现即降一级
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
OCR_SWIFT = os.path.join(BIN_DIR, "ocr.swift")
OCR_BIN = os.path.join(BIN_DIR, "ocr")

# 角色从高到低。rank 越大越靠后，用来做「必须严格降级」的判断。
ROLES = ["主审", "总主编", "主编", "副主编", "参编"]
RANK = {r: i for i, r in enumerate(ROLES)}

ROLE_SYNONYMS = [
    ("总主编", ("总主编", "总主編", "总编")),
    ("副主编", ("副主编", "副主編", "副编")),
    ("主编", ("主编", "主編")),
    ("参编", ("参编", "参編", "编委", "编者")),
]

# 「主审」的「审」常被误识成形近字，且少有其它以「主」开头的角色词
AUDIT_RE = re.compile(r"^主[\u4e00-\u9fa5]$")
NOT_AUDIT = {"主编", "主編", "主任", "主管", "主持", "主导"}

NAME_RE = re.compile(r"^[\u4e00-\u9fa5·]{2,4}$")
NOISE_WORDS = {
    "出版社", "编委会", "编写组", "组织编写", "编写人员", "前言", "目录", "序言",
    "内容提要", "责任编辑", "封面设计", "版式设计", "责任校对", "出版发行",
    "模块一", "模块二", "模块三", "项目检测", "岗位实践", "能力拓展",
    "参考文献", "附录", "后记", "定价", "书号", "版权所有",
}


# ---------------- OCR ----------------

def ocr_available() -> bool:
    """当前环境能不能做图片 OCR（只有 macOS 的 Vision 可用）。"""
    import platform
    return platform.system() == "Darwin" and os.path.exists(OCR_SWIFT)


def _ensure_ocr_binary() -> Optional[str]:
    """把 swift 脚本编译成二进制，避免每次调用都现场编译。"""
    if os.path.exists(OCR_BIN) and os.path.getmtime(OCR_BIN) >= os.path.getmtime(OCR_SWIFT):
        return OCR_BIN
    if not os.path.exists(OCR_SWIFT):
        return None
    try:
        proc = subprocess.run(
            ["swiftc", "-o", OCR_BIN, OCR_SWIFT],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode == 0 and os.path.exists(OCR_BIN):
            os.chmod(OCR_BIN, 0o755)
            return OCR_BIN
    except Exception:  # noqa: BLE001
        pass
    return None


def ocr_image(path: str) -> List[Tuple[float, float, str]]:
    """OCR 一张图片，返回 [(中心x, 中心y, 文字)]，坐标为归一化值。"""
    binary = _ensure_ocr_binary()
    if binary:
        cmd = [binary, path]
    else:
        cmd = ["swift", OCR_SWIFT, path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:  # noqa: BLE001
        return []
    items: List[Tuple[float, float, str]] = []
    for line in proc.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        text = parts[2].strip()
        if text:
            items.append((x, y, text))
    return items


def render_pdf_page_to_png(pdf_path: str, page_index: int, zoom: float = 3.0) -> Optional[str]:
    """把 PDF 某一页渲染成临时 PNG，供 OCR 使用。"""
    try:
        import fitz  # noqa: PLC0415
    except ImportError:
        return None
    doc = fitz.open(pdf_path)
    try:
        if page_index >= doc.page_count:
            return None
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        out = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        out.write(pix.tobytes("png"))
        out.close()
        return out.name
    finally:
        doc.close()


# ---------------- 版式还原 ----------------

def cluster_rows(items: List[Tuple[float, float, str]], tol: float = 0.02) -> List[List[str]]:
    """按 y 坐标把 OCR 结果聚成行，行内按 x 从左到右。"""
    if not items:
        return []
    ordered = sorted(items, key=lambda t: -t[1])
    rows: List[List[Tuple[float, str]]] = []
    current: List[Tuple[float, str]] = []
    last_y: Optional[float] = None
    for x, y, text in ordered:
        if last_y is None or abs(y - last_y) <= tol:
            current.append((x, text))
        else:
            rows.append(current)
            current = [(x, text)]
        last_y = y
    if current:
        rows.append(current)
    out = []
    for row in rows:
        row.sort(key=lambda t: t[0])
        out.append([t for _, t in row])
    return out


def text_to_rows(text: str) -> List[List[str]]:
    """纯文本按行切分，行内按全角/半角空白拆词。"""
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        cells = [c for c in re.split(r"[\s\u3000\u00a0]+", line) if c]
        if cells:
            rows.append(cells)
    return rows


# ---------------- 角色与姓名 ----------------

def match_role(cell: str) -> Optional[str]:
    """识别一个单元格是不是角色词。"""
    compact = re.sub(r"[\s\u3000\u00a0]+", "", cell)
    if not compact:
        return None
    for role, keys in ROLE_SYNONYMS:
        for k in keys:
            if compact == k:
                return role
    if compact in NOT_AUDIT:
        return None
    if AUDIT_RE.match(compact):
        return "主审"
    return None


def expand_row(row: List[str]) -> List[str]:
    """OCR 常把整行吐成一个单元格，这里按空白重新拆开。

    但「杨 丽」这种姓名内部的空格不能拆，判据是去掉空白后
    如果正好是一个 2–4 字的姓名，就合并回去。
    """
    out: List[str] = []
    for cell in row:
        parts = [p for p in re.split(r"[\s\u3000\u00a0]+", cell) if p]
        if len(parts) <= 1:
            out.append(parts[0] if parts else cell)
            continue
        compact = "".join(parts)
        if len(compact) <= 4 and NAME_RE.match(compact):
            out.append(compact)      # 姓名内部空格：「杨 丽」→「杨丽」
        else:
            out.extend(parts)        # 多个姓名或「角色 姓名」：「周五湖 吴六桥」→ 两个
    return out


def merge_role_tokens(cells: List[str]) -> List[str]:
    """把被 OCR 拆成单字的角色词合回去，如 ['参','编','郑七弦'] → ['参编','郑七弦']。

    只在相邻片段能组成合法角色词时才合并，不会把姓名的两个字误并。
    """
    out: List[str] = []
    i = 0
    n = len(cells)
    while i < n:
        merged = False
        for take in (3, 2):
            if i + take <= n:
                cand = "".join(cells[i:i + take])
                if match_role(cand):
                    out.append(cand)
                    i += take
                    merged = True
                    break
        if not merged:
            out.append(cells[i])
            i += 1
    return out


def split_role_cell(cell: str) -> Tuple[Optional[str], Optional[str]]:
    """把「主编孙三峰」这种黏在一起的单元格拆成 (角色, 姓名)。

    只在单元格以角色词开头、且后面还有内容时才拆，
    避免把姓「主」的少数情况误判（这类姓氏几乎不存在）。
    """
    compact = re.sub(r"[\s\u3000\u00a0]+", "", cell)
    if not compact:
        return None, None
    for role, keys in ROLE_SYNONYMS:
        for k in keys:
            if compact.startswith(k) and len(compact) > len(k):
                return role, compact[len(k):]
    if len(compact) > 2 and AUDIT_RE.match(compact[:2]):
        return "主审", compact[2:]
    return None, None


def clean_name(cell: str) -> Optional[str]:
    compact = re.sub(r"[\s\u3000\u00a0]+", "", cell)
    if not compact or compact in NOISE_WORDS:
        return None
    if match_role(compact):
        return None
    if NAME_RE.match(compact):
        return compact
    return None


def parse_rows(rows: List[List[str]]) -> Dict:
    """把「已经还原成行」的扉页解析成编写名单。

    返回 {title, authors, warnings}。
    authors 里每人带 role；不按字数，字数由制度另行计算。
    """
    title = ""
    authors: List[Dict] = []
    warnings: List[str] = []
    current_role: Optional[str] = None
    last_rank = -1
    seen: Dict[str, str] = {}

    for row in rows:
        if not row:
            continue
        cells = merge_role_tokens(expand_row(row))
        if not cells:
            continue
        first = cells[0]
        role = match_role(first)
        names_in_row: List[str] = []
        if role is None:
            prefix_role, rest = split_role_cell(first)
            if prefix_role:
                role = prefix_role
                names_in_row = ([rest] if rest else []) + cells[1:]

        if role:
            rank = RANK[role]
            # 角色必须严格降级；同一角色重复出现 → OCR 漏字，降到下一级
            if rank <= last_rank and last_rank + 1 < len(ROLES):
                fixed = ROLES[last_rank + 1]
                warnings.append(
                    f"「{role}」重复出现，已按下一级「{fixed}」处理（扉页可能漏字，请核对）"
                )
                role = fixed
                rank = RANK[role]
            last_rank = rank
            current_role = role
            if not names_in_row:
                names_in_row = cells[1:]
        elif role is not None and names_in_row:
            pass
        elif current_role:
            # 续行：沿用上一个角色词（角色名可能跨多行排列）
            role = current_role
            names_in_row = cells
        else:
            # 角色词之前的内容：多半是书名
            if not title:
                joined = "".join(row)
                if 2 <= len(joined) <= 30:
                    title = joined
            continue

        for cell in names_in_row:
            name = clean_name(cell)
            if not name:
                # 一行里出现非姓名内容，说明这个角色块结束了
                current_role = None
                break
            if name in seen:
                continue
            seen[name] = role
            authors.append({"name": name, "role": role})

    return {"title": title, "authors": authors, "warnings": warnings}


# ---------------- 对外入口 ----------------

def _rows_from_image(path: str) -> List[List[str]]:
    return cluster_rows(ocr_image(path))


def _rows_from_pdf(path: str, max_pages: int = 20) -> Tuple[List[List[str]], int]:
    """PDF：优先用文字层，没有就渲染成图 OCR。返回 (行, 用到的页码 1-based)。"""
    try:
        import fitz  # noqa: PLC0415
    except ImportError:
        return [], 0

    doc = fitz.open(path)
    try:
        for i in range(min(max_pages, doc.page_count)):
            try:
                text = doc[i].get_text()
            except Exception:  # noqa: BLE001
                text = ""
            if text and any(k in text for k in ("主审", "总主编", "主编", "副主编", "参编")):
                rows = text_to_rows(text)
                parsed = parse_rows(rows)
                if parsed["authors"]:
                    return rows, i + 1
    finally:
        doc.close()

    # 文字层里没有：逐页渲染做 OCR
    for i in range(min(max_pages, doc.page_count)):
        png = render_pdf_page_to_png(path, i)
        if not png:
            continue
        try:
            rows = _rows_from_image(png)
            parsed = parse_rows(rows)
            if len(parsed["authors"]) >= 2:
                return rows, i + 1
        finally:
            try:
                os.unlink(png)
            except OSError:
                pass
    return [], 0


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".webp")


def parse_cover(path: str, filename: str = "") -> Dict:
    """解析扉页文件，返回 {ok, title, authors, rows, page, warnings, error}。"""
    name = (filename or path).lower()
    if name.endswith(".pdf"):
        rows, page = _rows_from_pdf(path)
        source = "pdf"
    elif name.endswith(IMAGE_EXTS):
        rows = _rows_from_image(path)
        page = 1
        source = "image"
    else:
        rows = text_to_rows(open(path, encoding="utf-8", errors="ignore").read())
        page = 1
        source = "text"

    parsed = parse_rows(rows)
    if not parsed["authors"]:
        if source == "image" and not ocr_available():
            msg = (
                "当前系统不支持图片文字识别（仅 macOS 可用）。"
                "请改为上传含扉页的 PDF，或直接在名单表里手动录入。"
            )
        else:
            msg = (
                "没能从这张图/文件里识别出编写名单。请确认扉页上有「主审 / 总主编 / 主 编 / "
                "副主编 / 参 编」这样的角色字样，且图片清晰、文字横向排列。"
            )
        return {"ok": False, "source": source, "rows": rows, "error": msg}
    parsed.update({"ok": True, "source": source, "page": page, "rows": rows})
    return parsed
