# -*- coding: utf-8 -*-
"""字数分配工具 —— 本地 Web 服务。

启动：python3 app/server.py  然后打开 http://127.0.0.1:8765
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import time
from urllib.parse import quote
from typing import Dict, List, Optional

import hashlib
import hmac

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from allocator import (  # noqa: E402
    allocate_best, allocate_under_bound, best_under_bound, distribute_words,
    infer_per_page_words, optimize_order, optimize_under_bound, rescale_units,
    solve_allow_over,
)
from excel_export import build_workbook  # noqa: E402
from pdf_parser import parse_book  # noqa: E402
from people_import import build_people_template, parse_people_csv, parse_people_xlsx  # noqa: E402
from cover_parser import IMAGE_EXTS, parse_cover  # noqa: E402
from policy import build_initial_people, suggest_members  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="书稿字数分配工具")


@app.get("/login", response_class=HTMLResponse)
def login_page(error: str = "") -> HTMLResponse:
    err = '<div class="err">口令不对，请重试</div>' if error else ""
    return HTMLResponse(LOGIN_PAGE.replace("{ERROR}", err))


@app.post("/login")
def do_login(code: str = Form("")):
    ok = bool(ACCESS_CODE) and hmac.compare_digest(code.strip(), ACCESS_CODE)
    if not ok:
        return RedirectResponse("/login?error=1", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("wca_auth", _AUTH_TOKEN, httponly=True, samesite="lax", max_age=7 * 86400)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("wca_auth")
    return resp


@app.middleware("http")
async def access_gate(request: Request, call_next):
    """设了 ACCESS_CODE 才启用；本地运行完全不受影响。"""
    if not ACCESS_CODE:
        return await call_next(request)
    path = request.url.path
    if path.startswith("/login") or path.startswith("/logout"):
        return await call_next(request)
    if hmac.compare_digest(request.cookies.get("wca_auth", ""), _AUTH_TOKEN):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "需要访问口令"}, status_code=401)
    return RedirectResponse("/login", status_code=303)

# 最近一次解析结果（单用户本地工具，够用）
_CACHE: Dict[str, Dict] = {}

# ---- 访问口令（仅公网穿透时启用；本地不设环境变量即无口令） ----
ACCESS_CODE = os.environ.get("ACCESS_CODE", "").strip()
_AUTH_TOKEN = hashlib.sha256(f"wca:{ACCESS_CODE}".encode()).hexdigest() if ACCESS_CODE else ""

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>需要访问口令 · 书稿字数分配工具</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:#f5f6f8;font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:#1f2933}
  .box{background:#fff;padding:38px 34px;border-radius:14px;box-shadow:0 8px 32px rgba(31,41,51,.10);width:min(92vw,380px)}
  h1{margin:0 0 6px;font-size:19px}
  p.sub{margin:0 0 22px;color:#6b7684;font-size:13px}
  input{width:100%;padding:11px 13px;border:1px solid #d5dae1;border-radius:9px;font-size:15px;outline:none}
  input:focus{border-color:#1f3a5f;box-shadow:0 0 0 3px rgba(31,58,95,.08)}
  button{margin-top:14px;width:100%;padding:11px;border:0;border-radius:9px;background:#1f3a5f;color:#fff;
    font-size:15px;font-weight:600;cursor:pointer}
  button:hover{background:#2b4d7a}
  .err{margin-top:12px;color:#c0392b;font-size:13px}
</style></head><body>
<form class="box" method="post" action="/login">
  <h1>书稿字数分配工具</h1>
  <p class="sub">此工具已开启访问保护，请输入访问口令</p>
  <input type="password" name="code" placeholder="访问口令" autofocus autocomplete="current-password">
  <button type="submit">进入</button>
  {ERROR}
</form></body></html>"""


DEFAULT_PEOPLE = [
    {"name": "夏群", "role": "主编", "target_words": 60000},
    {"name": "邓竹君", "role": "主编", "target_words": 50000},
    {"name": "景丽", "role": "主编", "target_words": 40000},
    {"name": "汪涛", "role": "副主编", "target_words": 40000},
    {"name": "卢振芝", "role": "副主编", "target_words": 40000},
    {"name": "欧唐燕", "role": "副主编", "target_words": 30000},
    {"name": "黄嘉嘉", "role": "副主编", "target_words": 30000},
    {"name": "刘洁俐", "role": "副主编", "target_words": 30000},
    {"name": "梁锦", "role": "参编", "target_words": 20000},
    {"name": "夏紫晴", "role": "参编", "target_words": 20000},
]


class UnitModel(BaseModel):
    index: int
    label: str
    kind: str
    start: int
    end: int
    pages: int
    words: int
    project_no: Optional[int] = None
    figure_pages: int = 0


class PersonModel(BaseModel):
    name: str
    role: str
    target_words: int
    allow_pair: bool = True


class AllocateRequest(BaseModel):
    units: List[UnitModel]
    people: List[PersonModel]
    per_page_words: int = 1200
    tolerance: float = 0.1
    over_weight: float = 3.0
    under_weight: float = 1.0
    allowed_pairs: Optional[List[List[str]]] = None
    calibrate: bool = False
    total_words: Optional[int] = None
    boundary_penalty: float = 0.02
    # 国标口径：整页图按满版 20% 折算
    use_figure_discount: bool = True
    # 工作量折算：每 1000 字折合多少课时（0 表示不折算）
    hours_per_1000: float = 1.0
    # 允许超额：只约束欠额，超额不限（业务上「多写没关系，少写不行」）
    allow_over: bool = False
    # 任务书
    book_title: str = ""
    deadline: str = ""
    quality_note: str = ""
    exit_note: str = ""


def _prepare_units(units: List[Dict], use_figure_discount: bool) -> List[Dict]:
    """按是否启用整页图折减，给每个单元算出字数权重。"""
    out = []
    for u in units:
        v = dict(u)
        pages = float(v.get("pages") or 0)
        figs = float(v.get("figure_pages") or 0)
        v["weight"] = max(0.0, pages - figs * 0.8) if (use_figure_discount and figs) else pages
        out.append(v)
    return out


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/default-people")
def default_people() -> JSONResponse:
    return JSONResponse({"people": DEFAULT_PEOPLE})


@app.get("/api/people-template")
def people_template() -> StreamingResponse:
    """下载名单填写模板。"""
    buf = build_people_template()
    fname = "编写名单模板.xlsx"
    quoted = quote(fname)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f"attachment; filename=people_template.xlsx; filename*=UTF-8''{quoted}"
            )
        },
    )


@app.post("/api/parse-cover")
async def parse_cover_file(file: UploadFile = File(...)) -> JSONResponse:
    """识别扉页上的编写名单，并按公司制度给出初版字数。"""
    name = (file.filename or "").lower()
    if not name.endswith((".pdf",) + IMAGE_EXTS):
        raise HTTPException(400, "请上传扉页图片（png/jpg/heic）或包含扉页的 PDF")
    data = await file.read()
    if len(data) > 60 * 1024 * 1024:
        raise HTTPException(400, "文件过大（>60MB）")

    suffix = os.path.splitext(name)[1] or ".png"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(data)
        tmp.close()
        result = parse_cover(tmp.name, filename=file.filename or "")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"扉页识别失败：{exc}") from exc
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    result["filename"] = file.filename
    if not result.get("ok"):
        return JSONResponse(result)

    built = build_initial_people(result["authors"])
    result["people"] = built["people"]
    result["skipped"] = built["skipped"]
    result["policy"] = {
        "total": built["policy_total"],
        "member_pool": built["member_pool"],
        "member_words_each": built["member_words_each"],
        "chief_tiers": [60000, 50000, 30000],
        "vice_words": 20000,
    }
    return JSONResponse(result)


@app.post("/api/member-suggest")
def member_suggest(req: Dict) -> JSONResponse:
    """已知全书字数时，算出能给多少参编各分 1 万。"""
    people = req.get("people") or []
    total = req.get("total_words")
    return JSONResponse(suggest_members(people, total))


@app.post("/api/import-people")
async def import_people(file: UploadFile = File(...)) -> JSONResponse:
    """从 Excel / CSV 导入编写名单。"""
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "请上传 .xlsx 或 .csv 文件")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件过大（>20MB）")
    if name.endswith(".csv"):
        result = parse_people_csv(data)
    else:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        try:
            tmp.write(data)
            tmp.close()
            result = parse_people_xlsx(tmp.name)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    result["filename"] = file.filename
    return JSONResponse(result)


@app.post("/api/parse")
async def parse_pdf(
    file: UploadFile = File(...),
    per_page_words: int = Form(1200),
    include_ref: bool = Form(False),
    split_sections: bool = Form(False),
    min_section_pages: int = Form(1),
) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "请上传 PDF 文件")
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(400, "文件过大（>200MB）")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    try:
        tmp.write(data)
        tmp.close()
        t0 = time.time()
        result = parse_book(
            tmp.name, per_page_words=per_page_words, include_ref=include_ref,
            split_sections=split_sections, min_section_pages=min_section_pages,
        )
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        result["filename"] = file.filename
        # 若书稿自带扉页，一并按公司制度给出初版名单
        authors = result.get("authors") or []
        if authors:
            built = build_initial_people(authors)
            result["cover_people"] = built["people"]
            result["cover_skipped"] = built["skipped"]
            result["cover_policy"] = {
                "total": built["policy_total"],
                "member_pool": built["member_pool"],
                "member_words_each": built["member_words_each"],
            }
        return JSONResponse(result)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"解析失败：{exc}") from exc
    finally:
        # 解析完立刻删掉临时文件，不在磁盘留书稿副本
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@app.post("/api/allocate")
def allocate(req: AllocateRequest) -> JSONResponse:
    # 指定全书总字数时走「平均法」：字数 ÷ 正文页数 × 各单元页数，
    # 此时不做事图折减，保证每一页的字数完全相同。
    by_average = bool(req.total_words and req.total_words > 0) or req.calibrate
    units = _prepare_units([u.model_dump() for u in req.units], req.use_figure_discount and not by_average)
    people = [p.model_dump() for p in req.people]
    if not units or not people:
        raise HTTPException(400, "缺少单元或人员数据")

    notes: List[str] = []
    ppw = req.per_page_words
    _need_total = sum(p["target_words"] for p in people)
    total_pages = sum(u["pages"] for u in units) or 1
    if req.total_words and req.total_words > 0:
        # 用户手动指定全书总字数：按页数比例精确分摊
        scaled = distribute_words(units, req.total_words)
        ppw = round(req.total_words / total_pages)
        notes.append(f"全书总字数按手动输入 {req.total_words:,} 字，按页数比例分摊到各单元（约 {ppw} 字/页）")
    elif req.calibrate:
        target_total = sum(p["target_words"] for p in people)
        scaled = distribute_words(units, target_total)
        ppw = round(target_total / total_pages)
        notes.append(f"全书总字数按名单需求合计 {target_total:,} 字分摊（约 {ppw} 字/页）")
    else:
        scaled = rescale_units(units, ppw)
    try:
        if req.allow_over:
            res = solve_allow_over(scaled, people)
            res["by_average"] = by_average
            res["avg_words_per_page"] = round(
                (req.total_words or sum(p["target_words"] for p in people)) / total_pages, 1
            ) if total_pages else 0
        else:
            res = allocate_best(
                scaled,
                people,
                tolerance=req.tolerance,
                over_weight=req.over_weight,
                under_weight=req.under_weight,
                allowed_pairs=req.allowed_pairs,
                boundary_penalty=req.boundary_penalty,
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc

    res["per_page_words"] = ppw
    # 正文页数不含参考文献等非正文部分
    body_pages = sum(u["pages"] for u in units if u.get("kind") != "ref") or total_pages
    res["body_pages"] = body_pages
    res["total_pages_all"] = total_pages
    res["by_average"] = by_average
    if by_average:
        base = req.total_words if (req.total_words and req.total_words > 0) else sum(
            p["target_words"] for p in people
        )
        res["avg_words_per_page"] = round(base / body_pages, 1) if body_pages else 0
        notes.append(
            f"按平均法：全书 {base:,} 字 ÷ 正文 {body_pages} 页 = "
            f"平均 {res['avg_words_per_page']} 字/页（不含目录、扉页、参考文献），"
            f"各章节字数 = 页数 × 平均每页字数。"
        )
    res["hours_per_1000"] = req.hours_per_1000

    # 全书字数不足制度需求时，必然有人欠额——这是口径问题，必须点明
    if _need_total and res["total_words"] < _need_total * 0.995:
        gap = _need_total - res["total_words"]
        suggest_ppw = round(_need_total / total_pages) if total_pages else 0
        notes.append(
            f"⚠ 全书可分配字数 {res['total_words']:,} 字，少于名单制度需求 {_need_total:,} 字，"
            f"缺口 {gap:,} 字——无论怎么分配都会有人写不够。"
            f"建议：勾选「用名单需求合计作为全书总字数」（相当于 {suggest_ppw} 字/页），"
            f"或把每页字数改成 {suggest_ppw}。"
        )

    # 目标为 0 的人（多为余量不足的参编）不参与分配，明确告知
    zero_people = [p["name"] for p in people if (p.get("target_words") or 0) <= 0]
    if zero_people:
        notes.append(
            f"{'、'.join(zero_people)} 的目标字数为 0，不承担编写，未参与本次分配。"
        )
    # 大单元导致的粒度限制
    if scaled:
        biggest = max(scaled, key=lambda u: u["pages"])
        if biggest["pages"] >= sum(u["pages"] for u in scaled) * 0.15:
            notes.append(
                f"「{biggest['label']}」单个任务就有 {biggest['pages']} 页，"
                f"任务不可拆时它就是不可分割的一整块，会限制整体精度。"
            )
    for seg in res["segments"]:
        seg["hours"] = round(seg["words"] / 1000.0 * req.hours_per_1000, 1) if req.hours_per_1000 > 0 else 0
    res["notes"] = notes
    res["warnings"] = notes + res.get("warnings", [])
    # 回填每个单元
    res["units"] = scaled
    return JSONResponse(res)


def _diagnose_granularity(units: List[Dict], res: Dict) -> List[str]:
    """解释偏差为什么降不下去：找出最稀疏的切点和最大的不可拆单元。"""
    out: List[str] = []
    pages = sorted({u["start"] for u in units} | {u["end"] + 1 for u in units})
    if len(pages) >= 2:
        gaps = [(pages[i + 1] - pages[i], pages[i], pages[i + 1]) for i in range(len(pages) - 1)]
        gaps.sort(reverse=True)
        widest = gaps[0]
        if widest[0] >= 15:
            out.append(
                f"第 {widest[1]}–{widest[2]} 页之间没有任何可切点（跨度 {widest[0]} 页），"
                f"这一段只能整块给一个人，是偏差的主要来源。"
            )
    biggest = max(units, key=lambda u: u["pages"])
    total_pages = sum(u["pages"] for u in units) or 1
    if biggest["pages"] / total_pages >= 0.15:
        out.append(
            f"最大的单个单元「{biggest['label']}」有 {biggest['pages']} 页"
            f"（占全书 {biggest['pages'] / total_pages * 100:.0f}%），任务不拆时它就是不可分割的一整块。"
        )
    bad = [s for s in res.get("segments", []) if abs(s.get("delta_ratio", 0)) > 0.10]
    if bad:
        names = "、".join(
            "+".join(m["name"] for m in s["members"]) for s in bad
        )
        out.append(
            f"仍有 {len(bad)} 段超出 ±10%：{names}。"
            f"在「任务不可拆」的前提下，这已经是本稿能达到的最好结果。"
        )
    return out


@app.post("/api/optimize-order")
def optimize(req: AllocateRequest) -> JSONResponse:
    """自动搜索偏差最小的名单顺序（同角色同目标的人互换不影响结果）。"""
    by_average = bool(req.total_words and req.total_words > 0) or req.calibrate
    units = _prepare_units([u.model_dump() for u in req.units], req.use_figure_discount and not by_average)
    people = [p.model_dump() for p in req.people]
    if not units or not people:
        raise HTTPException(400, "缺少单元或人员数据")

    total_pages = sum(u["pages"] for u in units) or 1
    if req.total_words and req.total_words > 0:
        units = distribute_words(units, req.total_words)
    elif req.calibrate:
        units = distribute_words(units, sum(p["target_words"] for p in people))
    else:
        units = rescale_units(units, req.per_page_words)

    try:
        if req.allow_over:
            res = optimize_under_bound(units, people, over_cap=2.0)
        else:
            res = optimize_order(units, people, tolerance=req.tolerance)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc

    res["per_page_words"] = req.per_page_words
    res["body_pages"] = total_pages
    res["units"] = units
    need_total = sum(p["target_words"] for p in people)
    if need_total and res["total_words"] < need_total * 0.995:
        gap = need_total - res["total_words"]
        suggest_ppw = round(need_total / total_pages) if total_pages else 0
        res.setdefault("warnings", []).insert(0,
            f"⚠ 全书 {res['total_words']:,} 字 < 制度需求 {need_total:,} 字，缺口 {gap:,} 字——"
            f"必然有人欠额。建议勾选「用名单需求合计作为全书总字数」（≈{suggest_ppw} 字/页）。"
        )
    res["diagnosis"] = _diagnose_granularity(units, res)
    return JSONResponse(res)


@app.post("/api/export")
def export(req: AllocateRequest) -> StreamingResponse:
    by_average = bool(req.total_words and req.total_words > 0) or req.calibrate
    units = _prepare_units([u.model_dump() for u in req.units], req.use_figure_discount and not by_average)
    people = [p.model_dump() for p in req.people]
    ppw = req.per_page_words
    total_pages = sum(u["pages"] for u in units) or 1
    if req.total_words and req.total_words > 0:
        scaled = distribute_words(units, req.total_words)
        ppw = round(req.total_words / total_pages)
    elif req.calibrate:
        target_total = sum(p["target_words"] for p in people)
        scaled = distribute_words(units, target_total)
        ppw = round(target_total / total_pages)
    else:
        scaled = rescale_units(units, ppw)
    if req.allow_over:
        res = solve_allow_over(scaled, people)
    else:
        res = allocate_best(
            scaled,
            people,
            tolerance=req.tolerance,
            over_weight=req.over_weight,
            under_weight=req.under_weight,
            allowed_pairs=req.allowed_pairs,
            boundary_penalty=req.boundary_penalty,
        )
    buf: io.BytesIO = build_workbook(
        res, people, units=scaled, per_page_words=ppw,
        options={
            "hours_per_1000": req.hours_per_1000,
            "deadline": req.deadline,
            "quality_note": req.quality_note,
            "exit_note": req.exit_note,
            "book_title": req.book_title or "书稿",
        },
    )
    fname = "字数分配表.xlsx"
    quoted = quote(fname)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=allocation.xlsx; filename*=UTF-8''{quoted}"
        },
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _free_port(start: int = 8770, host: str = "0.0.0.0") -> int:
    import socket

    for p in range(start, start + 60):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, p))
                return p
            except OSError:
                continue
    return start


def _lan_ips() -> List[str]:
    """列出本机的内网 IPv4 地址，供启动提示和手动访问使用。"""
    import socket

    ips = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))  # 不真正发包，只用来确定出口网卡
        ips.add(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def _mdns_name() -> str:
    import socket

    try:
        return socket.gethostname().split(".")[0] + ".local"
    except OSError:
        return ""


if __name__ == "__main__":
    import threading
    import webbrowser

    import uvicorn

    # 默认监听所有网卡，同一局域网内的电脑/手机可直接访问；
    # 想只允许本机访问时用： HOST=127.0.0.1 python3 app/server.py
    host = os.environ.get("HOST", "0.0.0.0")
    lan_mode = host in ("0.0.0.0", "::", "")
    bind_host = "0.0.0.0" if lan_mode else host
    port = int(os.environ.get("PORT", "0")) or _free_port(8770, bind_host)
    local_url = f"http://127.0.0.1:{port}"

    def announce() -> None:
        """等端口真正可连接后再报地址，避免「看到地址却打不开」。"""
        import socket as _socket
        import time as _time

        deadline = _time.time() + 60
        while _time.time() < deadline:
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as probe:
                probe.settimeout(0.3)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            _time.sleep(0.1)
        print("=" * 60, flush=True)
        print("  书稿字数分配工具已启动", flush=True)
        print(f"  本机访问：{local_url}", flush=True)
        if lan_mode:
            ips = _lan_ips()
            for ip in ips:
                print(f"  内网访问：http://{ip}:{port}", flush=True)
            mdns = _mdns_name()
            if mdns:
                print(f"  同网段也可用：http://{mdns}:{port}", flush=True)
            if not ips:
                print("  内网访问：未检测到局域网地址（可能未连 Wi-Fi / 网线）", flush=True)
            print("  ─ 同一 Wi-Fi 或局域网的电脑、手机、平板在浏览器输入上面地址即可使用", flush=True)
            print("  ─ 只想本机使用时：HOST=127.0.0.1 python3 app/server.py", flush=True)
        print("  按 Ctrl+C 结束", flush=True)
        print("=" * 60, flush=True)
        if os.environ.get("NO_BROWSER") != "1":
            webbrowser.open(local_url)

    threading.Thread(target=announce, daemon=True).start()
    print(f"正在启动（端口 {port}），稍候会打印访问地址…", flush=True)
    uvicorn.run(app, host=bind_host, port=port, log_level="warning")
