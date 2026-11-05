# -*- coding: utf-8 -*-
"""PDF 目录解析：从书籍 PDF 中提取「模块 / 项目 / 任务 / 项目检测 / 岗位实践 / 能力拓展」结构。

设计原则：
1. 只依赖 PyMuPDF，不依赖任何在线服务。
2. 解析失败不崩，返回可编辑的中间结果，交给用户在前端手工修正。
3. 所有页码统一使用「书上印刷页码」，并单独给出与 PDF 物理页的偏移量。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import fitz

# ---------- 常量 ----------

FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 目录节点类型
KIND_MODULE = "module"
KIND_PROJECT = "project"
KIND_TASK = "task"
KIND_TAIL = "tail"          # 项目检测 / 岗位实践 / 能力拓展
KIND_REF = "ref"            # 参考文献
KIND_OTHER = "other"

TAIL_TITLES = ("项目检测", "岗位实践", "能力拓展", "项目小结", "复习思考题", "实训")

# 目录行匹配（容忍全角空格、多余空格、«»书名号）
RE_MODULE = re.compile(r"^模块\s*[一二三四五六七八九十百]+")
RE_PROJECT = re.compile(r"^项目\s*[一二三四五六七八九十百]+")
RE_TASK = re.compile(r"^任务\s*[一二三四五六七八九十百]+")
RE_REF = re.compile(r"^参考文献")
# 兼容其他书稿结构：章 / 节 / 单元 / 课题
RE_CHAPTER = re.compile(r"^(第\s*[一二三四五六七八九十百0-9]+\s*章|单元\s*[一二三四五六七八九十])")
RE_SECTION = re.compile(r"^(第\s*[一二三四五六七八九十百0-9]+\s*节|课题\s*[一二三四五六七八九十])")
RE_TAIL = re.compile(r"^(" + "|".join(TAIL_TITLES) + r")")
RE_PAGE_NO = re.compile(r"^[0-9]{1,4}$")


def _norm(s: str) -> str:
    """规范化一行文本：去首尾空白、全角转半角数字、压缩空白。"""
    s = s.replace("\u3000", " ").replace("\xa0", " ")
    s = s.translate(FULLWIDTH)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _cjk_count(text: str) -> int:
    return len(CJK_RE.findall(text))


def classify(title: str) -> str:
    t = _norm(title)
    if RE_MODULE.match(t):
        return KIND_MODULE
    if RE_PROJECT.match(t) or RE_CHAPTER.match(t):
        return KIND_PROJECT
    if RE_TASK.match(t) or RE_SECTION.match(t):
        return KIND_TASK
    if RE_REF.match(t):
        return KIND_REF
    if RE_TAIL.match(t):
        return KIND_TAIL
    return KIND_OTHER


# ---------- 定位目录页 ----------

def find_toc_pages(
    doc: "fitz.Document", scan_limit: int = 40, texts: Optional[List[str]] = None
) -> List[int]:
    """在前 scan_limit 页里找出「目录页」。

    判定：该页出现 >= 3 个可识别节点标题 且 出现 >= 3 个纯数字行，或整页含大量引导点。
    """
    hits: List[int] = []
    for i in range(min(scan_limit, doc.page_count)):
        text = texts[i] if texts is not None else doc[i].get_text()
        lines = [_norm(x) for x in text.split("\n") if _norm(x)]
        node_cnt = sum(
            1
            for ln in lines
            if classify(ln) in (KIND_MODULE, KIND_PROJECT, KIND_TASK, KIND_TAIL, KIND_REF)
        )
        num_cnt = sum(1 for ln in lines if RE_PAGE_NO.match(ln))
        dots = text.count("\u2488") + text.count("…") + text.count("􀆺")
        if node_cnt >= 3 and num_cnt >= 3:
            hits.append(i)
        elif dots > 20 and node_cnt >= 2:
            hits.append(i)
    return hits


# ---------- 解析目录 ----------

def parse_toc_text(lines: List[str]) -> List[Dict]:
    """把目录页的文本行解析成节点列表。

    返回 [{title, kind, book_page, level, project_no, task_no}]
    """
    nodes: List[Dict] = []
    lines = [_norm(x) for x in lines]
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        kind = classify(line)
        if kind in (KIND_MODULE, KIND_PROJECT, KIND_TASK, KIND_TAIL, KIND_REF):
            # 页码可能在同一行末尾（如「项目一 职业认知 3」），也可能在下一行
            page: Optional[int] = None
            inline = re.search(r"([0-9]{1,4})\s*$", line)
            if inline and classify(line[: inline.start()]) in (
                KIND_MODULE, KIND_PROJECT, KIND_TASK, KIND_TAIL, KIND_REF
            ):
                page = int(inline.group(1))
                line = line[: inline.start()].strip()
            elif i + 1 < n:
                nxt = lines[i + 1]
                if RE_PAGE_NO.match(nxt):
                    page = int(nxt)
                    i += 1
            if page is not None:
                nodes.append(
                    {
                        "title": line,
                        "kind": kind,
                        "book_page": page,
                        "level": _level_of(kind),
                        "project_no": None,
                        "task_no": None,
                    }
                )
        i += 1
    return _attach_numbers(nodes)


def _level_of(kind: str) -> int:
    return {"module": 1, "project": 2, "task": 3, "tail": 3, "ref": 2}.get(kind, 3)


NUM_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_to_int(s: str) -> int:
    """把「一二…十九」转成整数（够用到 99）。"""
    s = s.strip()
    if not s:
        return 0
    if s == "十":
        return 10
    if "十" in s:
        a, _, b = s.partition("十")
        tens = NUM_CN.get(a, 1) if a else 1
        ones = NUM_CN.get(b, 0) if b else 0
        return tens * 10 + ones
    return NUM_CN.get(s, 0)


def _attach_numbers(nodes: List[Dict]) -> List[Dict]:
    """标注每个节点所属的项目序号、任务序号。"""
    cur_proj = None
    cur_task = 0
    for nd in nodes:
        t = nd["title"]
        if nd["kind"] == KIND_PROJECT:
            m = re.match(r"^(项目|单元)\s*([一二三四五六七八九十百]+)", t) or re.match(
                r"^第\s*([一二三四五六七八九十百0-9]+)\s*章", t
            )
            if m:
                token = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
                cur_proj = int(token) if token.isdigit() else _cn_to_int(token)
            else:
                cur_proj = None
            cur_task = 0
            nd["project_no"] = cur_proj
        elif nd["kind"] == KIND_TASK:
            cur_task += 1
            nd["project_no"] = cur_proj
            nd["task_no"] = cur_task
        else:
            nd["project_no"] = cur_proj
    return nodes


# ---------- 估计书页 → PDF 物理页偏移 ----------

def _title_key(title: str) -> str:
    t = re.sub(r"^(模块|项目|任务|单元|课题)\s*[一二三四五六七八九十百]+\s*", "", _norm(title))
    t = re.sub(r"^第\s*[一二三四五六七八九十百0-9]+\s*[章节]\s*", "", t)
    t = t.replace(" ", "")
    return t[:6]


def estimate_offset(
    doc: "fitz.Document",
    nodes: List[Dict],
    search: range = range(0, 21),
    texts: Optional[List[str]] = None,
) -> int:
    """印刷页码 p 对应 PDF 索引 p+offset，用标题在正文页的命中率估计 offset。"""
    if texts is None:
        texts = [doc[i].get_text() for i in range(doc.page_count)]
    text_pages = [t.replace("\n", "").replace(" ", "") for t in texts]
    best_off, best_score = 0, -1.0
    for off in search:
        hit = tot = 0
        for nd in nodes:
            key = _title_key(nd["title"])
            if len(key) < 2:
                continue
            idx = nd["book_page"] + off
            if 0 <= idx < len(text_pages):
                tot += 1
                if key in text_pages[idx]:
                    hit += 1
        if tot == 0:
            continue
        score = hit / tot
        if score > best_score:
            best_off, best_score = off, score
    return best_off


# ---------- 构建可分配单元 ----------

def detect_figure_pages(
    doc: "fitz.Document",
    offset: int,
    start: int,
    end: int,
    min_text: int = 120,
    min_ratio: float = 0.55,
    texts: Optional[List[str]] = None,
) -> int:
    """统计书页区间内「整页图」的页数。

    《图书质量管理规定》附件第二条：正文中的插图占一面的，按正文满版字数的 20% 计算字数。
    判定标准：文字极少（<min_text 字）且图像/矢量图覆盖版面一半以上。
    """
    count = 0
    for book_p in range(start, end + 1):
        pi = book_p + offset
        if not (0 <= pi < doc.page_count):
            continue
        page = doc[pi]
        try:
            text = (texts[pi] if texts is not None else page.get_text()).strip()
        except Exception:  # noqa: BLE001
            text = ""
        if len(text) >= min_text:
            continue
        try:
            imgs = page.get_images(full=True)
        except Exception:  # noqa: BLE001
            imgs = []
        if not imgs:
            # 纯矢量图版面（流程图、表格截图）没有位图对象，用绘图对象兜底
            try:
                if len(page.get_drawings()) < 12:
                    continue
            except Exception:  # noqa: BLE001
                continue
            # 矢量图无法算面积，退化为「几乎无文字」即视为整页图
            count += 1
            continue
        try:
            page_area = abs(page.rect)
        except Exception:  # noqa: BLE001
            page_area = 0
        if not page_area:
            continue
        covered = 0.0
        for img in imgs[:6]:
            try:
                rects = page.get_image_rects(img[0])
            except Exception:  # noqa: BLE001
                rects = []
            for r in rects:
                covered = max(covered, abs(r))
        if covered / page_area >= min_ratio:
            count += 1
    return count


def build_units(
    nodes: List[Dict],
    offset: int,
    doc: "fitz.Document",
    per_page_words: int = 1200,
    last_book_page: Optional[int] = None,
    include_ref: bool = False,
    figure_discount: float = 0.2,
    texts: Optional[List[str]] = None,
) -> List[Dict]:
    """把节点合并成「不可再拆」的分配单元。

    单元划分规则（与业务约定一致）：
      * 项目标题单独成块（project-head）——通常 1~2 页
      * 每个任务是一个原子单元（task）
      * 项目检测 / 岗位实践 / 能力拓展 合成一个尾部块（project-tail），跟随所属项目
      * 参考文献单独成块（可选是否参与分配）
    页数为 0 的块（与前一块同页）自动并入前一块，避免出现半页碎块。
    """
    if not nodes:
        return []

    end_default = last_book_page
    if end_default is None:
        # 默认到 PDF 末页对应的书页
        end_default = max(doc.page_count - 1 - offset, 1)

    # 1) 计算每个节点的起止书页
    for i, nd in enumerate(nodes):
        start = nd["book_page"]
        if i + 1 < len(nodes):
            end = nodes[i + 1]["book_page"] - 1
        else:
            end = end_default
        nd["_start"] = start
        nd["_end"] = max(end, start)

    # 2) 归并成单元
    units: List[Dict] = []
    for nd in nodes:
        kind = nd["kind"]
        if kind == KIND_MODULE:
            continue  # 模块扉页并入紧随其后的项目头
        if kind == KIND_REF:
            if not include_ref:
                continue
            units.append(_mk_unit(nd, "ref", nd["_start"], nd["_end"]))
            continue
        if kind == KIND_PROJECT:
            units.append(_mk_unit(nd, "project-head", nd["_start"], nd["_end"]))
            continue
        if kind == KIND_TASK:
            units.append(_mk_unit(nd, "task", nd["_start"], nd["_end"]))
            continue
        if kind == KIND_TAIL:
            if units and units[-1]["kind"] == "project-tail":
                units[-1]["_end"] = nd["_end"]
                units[-1]["nodes"].append(nd["title"])
            else:
                units.append(_mk_unit(nd, "project-tail", nd["_start"], nd["_end"]))
            continue

    # 3) 页数为 0 的单元并入前一单元（同页共享）
    merged: List[Dict] = []
    for u in units:
        if u["pages"] <= 0 and merged:
            merged[-1]["_end"] = max(merged[-1]["_end"], u["_end"])
            merged[-1]["nodes"].extend(u["nodes"])
            continue
        merged.append(u)

    # 4) 补齐页数/字数，生成展示用名称
    for idx, u in enumerate(merged):
        u["start"], u["end"] = u["_start"], u["_end"]
        u["pages"] = max(0, u["_end"] - u["_start"] + 1)
        # 整页图按国标折算：一页图只算满版字数的一小部分
        u["figure_pages"] = (
            detect_figure_pages(doc, offset, u["start"], u["end"], texts=texts)
            if figure_discount > 0
            else 0
        )
        u["weight"] = max(0.0, u["pages"] - u["figure_pages"] * (1 - figure_discount))
        u["words"] = int(round(u["weight"] * per_page_words))
        u["index"] = idx
        u["label"] = _unit_label(u)
    return merged


def _mk_unit(nd: Dict, kind: str, start: int, end: int) -> Dict:
    return {
        "kind": kind,
        "title": nd["title"],
        "project_no": nd.get("project_no"),
        "task_no": nd.get("task_no"),
        "nodes": [nd["title"]],
        "_start": start,
        "_end": end,
        "start": start,
        "end": end,
        "pages": max(0, end - start + 1),
        "words": 0,
    }


def _unit_label(u: Dict) -> str:
    if u["kind"] == "project-head":
        return u["title"]
    if u["kind"] == "project-tail":
        return "、".join(u["nodes"]) if len(u["nodes"]) > 1 else u["title"]
    return u["title"]


# ---------- 统计真实字符数（仅用于报表参考） ----------

def measure_real_chars(
    doc: "fitz.Document", units: List[Dict], offset: int, texts: Optional[List[str]] = None
) -> None:
    """给每个单元回填实际汉字数（版面字数口径之外的参考值）。"""
    cache: Dict[int, int] = {}
    for u in units:
        total = 0
        for p in range(u["start"] + offset, u["end"] + offset + 1):
            if 0 <= p < doc.page_count:
                if p not in cache:
                    raw = texts[p] if texts is not None else doc[p].get_text()
                    cache[p] = _cjk_count(raw)
                total += cache[p]
        u["real_chars"] = total


# ---------- 对外主入口 ----------

def parse_book(
    pdf_path: str,
    per_page_words: int = 1200,
    include_ref: bool = False,
    toc_pages: Optional[List[int]] = None,
    offset: Optional[int] = None,
    figure_discount: float = 0.2,
) -> Dict:
    """解析整本书，返回结构化结果（可直接交给前端编辑）。"""
    doc = fitz.open(pdf_path)
    pages_total = doc.page_count
    # 只提取一次全文文本，后续所有统计复用（避免 300+ 页重复解析）
    texts: List[str] = [doc[i].get_text() for i in range(pages_total)]

    tpages = toc_pages if toc_pages is not None else find_toc_pages(doc, texts=texts)
    if not tpages:
        # 兜底：用前 10 页里节点最多的一页
        tpages = list(range(0, min(10, doc.page_count)))

    raw_lines: List[str] = []
    for p in tpages:
        for ln in texts[p].split("\n"):
            ln = _norm(ln)
            if ln and not ln.startswith("5 ") and "߈" not in ln:  # 过滤页眉乱码
                raw_lines.append(ln)

    nodes = parse_toc_text(raw_lines)
    if not nodes:
        return {
            "ok": False,
            "error": "未能从 PDF 中识别出目录。请确认前 40 页存在目录页，或手动粘贴目录。",
            "pages_total": pages_total,
        }

    off = offset if offset is not None else estimate_offset(doc, nodes, texts=texts)
    units = build_units(
        nodes, off, doc, per_page_words=per_page_words,
        include_ref=include_ref, figure_discount=figure_discount, texts=texts,
    )
    measure_real_chars(doc, units, off, texts=texts)

    doc.close()
    return {
        "ok": True,
        "pages_total": pages_total,
        "toc_pages": [p + 1 for p in tpages],
        "offset": off,
        "figure_pages_total": sum(u.get("figure_pages", 0) for u in units),
        "nodes": nodes,
        "units": units,
    }


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "work/book.pdf"
    res = parse_book(path)
    print(json.dumps({k: v for k, v in res.items() if k != "nodes"}, ensure_ascii=False, indent=1)[:3000])
