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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from allocator import allocate_best, distribute_words, infer_per_page_words, rescale_units  # noqa: E402
from excel_export import build_workbook  # noqa: E402
from pdf_parser import parse_book  # noqa: E402
from people_import import build_people_template, parse_people_csv, parse_people_xlsx  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="书稿字数分配工具")

# 最近一次解析结果（单用户本地工具，够用）
_CACHE: Dict[str, Dict] = {}

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
        result = parse_book(tmp.name, per_page_words=per_page_words, include_ref=include_ref)
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        result["filename"] = file.filename
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
    units = _prepare_units([u.model_dump() for u in req.units], req.use_figure_discount)
    people = [p.model_dump() for p in req.people]
    if not units or not people:
        raise HTTPException(400, "缺少单元或人员数据")

    notes: List[str] = []
    ppw = req.per_page_words
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
    res["hours_per_1000"] = req.hours_per_1000
    for seg in res["segments"]:
        seg["hours"] = round(seg["words"] / 1000.0 * req.hours_per_1000, 1) if req.hours_per_1000 > 0 else 0
    res["notes"] = notes
    res["warnings"] = notes + res.get("warnings", [])
    # 回填每个单元
    res["units"] = scaled
    return JSONResponse(res)


@app.post("/api/export")
def export(req: AllocateRequest) -> StreamingResponse:
    units = _prepare_units([u.model_dump() for u in req.units], req.use_figure_discount)
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
