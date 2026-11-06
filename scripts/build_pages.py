#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把工具打包成 GitHub Pages 可用的静态演示版，输出到 docs/。

完整版依赖 Python 后端（PDF 解析、分配算法、Excel 生成），Pages 托管不了。
这里做的是「快照演示」：界面和示例数据是真的，分配结果由真实算法预先生成，
/api/* 请求由一个 fetch 垫片用预置数据应答，上传/重新分配给明确提示。

用法：
    python3 scripts/build_pages.py            # 用已有 demo-bundle.json
    python3 scripts/build_pages.py --refresh  # 先起后端重算一遍再打包
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "app", "static")
OUT = os.path.join(ROOT, "docs")
BUNDLE = os.path.join(ROOT, "scripts", ".demo-bundle.json")

BANNER = """<div class="demo-banner">
  <span class="dot"></span>
  <span><b>在线演示版</b> —— 数据为示例书《老年人能力评估实务》，分配结果由真实算法预先生成。
  上传 PDF、重新分配、导入名单需<a href="https://github.com/ChatYU12/wordcount-allocation" target="_blank" rel="noopener">下载源码本地运行</a>。</span>
</div>
<style>
.demo-banner{display:flex;gap:10px;align-items:flex-start;margin:0 0 18px;padding:13px 16px;
  background:#fff8e6;border:1px solid #f0d9a8;border-radius:10px;font-size:13px;line-height:1.6;color:#6b4e12}
.demo-banner .dot{width:8px;height:8px;border-radius:50%;background:#e0a800;margin-top:6px;flex:none}
.demo-banner a{color:#8a5a00;text-decoration:underline;font-weight:600}
</style>
"""


def _build_bundle():
    """跑一遍真实后端，把分配结果存成快照。"""
    demo = json.load(open(os.path.join(STATIC, "demo.json"), encoding="utf-8"))
    keys = ("index", "label", "kind", "start", "end", "pages", "words", "project_no", "figure_pages")
    units = [{k: u.get(k) for k in keys} for u in demo["units"]]

    # 后端没起就先起一个
    started = False
    try:
        people = json.load(urllib.request.urlopen("http://127.0.0.1:8770/api/default-people"))["people"]
    except Exception:  # noqa: BLE001
        env = dict(os.environ, PORT="8770", NO_BROWSER="1")
        subprocess.Popen([sys.executable, "-u", "app/server.py"], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started = True
        for _ in range(40):
            time.sleep(0.5)
            try:
                people = json.load(urllib.request.urlopen("http://127.0.0.1:8770/api/default-people"))["people"]
                break
            except Exception:  # noqa: BLE001
                continue
        else:
            raise SystemExit("后端启动失败，无法生成快照")

    payload = {
        "units": units, "people": people, "per_page_words": 1224, "tolerance": 0.10,
        "calibrate": False, "total_words": None, "use_figure_discount": True,
        "hours_per_1000": 1.0, "deadline": "", "book_title": "老年人能力评估实务",
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8770/api/allocate",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
    )
    res = json.load(urllib.request.urlopen(req))
    bundle = {"result": res, "units": demo["units"], "people": people, "demo": demo}
    with open(BUNDLE, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False)
    print(f"快照生成：{len(res['segments'])} 段 / {res['total_words']:,} 字")
    if started:
        subprocess.run(["pkill", "-f", "app/server.py"], check=False)


SHIM = r"""/* 静态演示版的 API 垫片：把 /api/* 请求接到预置快照上 */
(function () {
  'use strict';
  window.__STATIC_DEMO__ = true;

  var bundlePromise = null;
  function loadBundle() {
    if (!bundlePromise) {
      bundlePromise = fetch('./demo-bundle.json').then(function (r) { return r.json(); });
    }
    return bundlePromise;
  }
  function json(obj) {
    return new Response(JSON.stringify(obj), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    });
  }
  var origFetch = window.fetch.bind(window);

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.indexOf('/api/default-people') >= 0) {
      return loadBundle().then(function (b) { return json({ people: b.people }); });
    }
    if (url.indexOf('/api/allocate') >= 0) {
      return loadBundle().then(function (b) { return json(b.result); });
    }
    if (url.indexOf('/api/parse') >= 0) {
      return Promise.resolve(json({ detail: '在线演示版不支持上传 PDF，请下载源码在本地运行完整版。' }));
    }
    if (url.indexOf('/api/import-people') >= 0) {
      return Promise.resolve(json({ ok: false, error: '在线演示版不支持导入名单，请下载源码在本地运行完整版。' }));
    }
    if (url.indexOf('/api/people-template') >= 0) {
      window.location.href = './编写名单模板.xlsx';
      return Promise.resolve(new Response('', { status: 204 }));
    }
    if (url.indexOf('/api/export') >= 0) {
      // 演示版：直接给一份预先生成的示例表格
      return origFetch('./字数分配表-示例.xlsx').then(function (r) {
        if (r.ok) { setTimeout(function () { /* 前端会自己下载 */ }, 0); }
        return r;
      });
    }
    return origFetch(input, init);
  };

  // 打开页面即载入示例，省得用户面对空白表单
  window.addEventListener('load', function () {
    setTimeout(function () {
      if (typeof loadDemo === 'function') loadDemo();
    }, 30);
  });
})();
"""


def build(refresh: bool = False) -> None:
    os.makedirs(OUT, exist_ok=True)
    if refresh or not os.path.exists(BUNDLE):
        _build_bundle()

    # 1) index.html：相对路径 + 提示条 + 垫片
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    html = html.replace('href="/static/style.css"', 'href="./style.css"')
    html = html.replace('src="/static/app.js"', 'src="./app.js"')
    html = html.replace("<body>\n", "<body>\n" + BANNER, 1)
    html = html.replace("</body>", '<script src="./static-demo.js"></script>\n</body>')
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(html)

    # 2) 样式原样复制
    shutil.copy(os.path.join(STATIC, "style.css"), os.path.join(OUT, "style.css"))

    # 3) app.js：把绝对路径的 demo.json 改成相对
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    js = js.replace("fetch('/static/demo.json')", "fetch('./demo.json')")
    open(os.path.join(OUT, "app.js"), "w", encoding="utf-8").write(js)

    # 4) 垫片与快照
    open(os.path.join(OUT, "static-demo.js"), "w", encoding="utf-8").write(SHIM)
    shutil.copy(BUNDLE, os.path.join(OUT, "demo-bundle.json"))
    # 前端「用示例书试用」直接读 demo.json
    shutil.copy(os.path.join(STATIC, "demo.json"), os.path.join(OUT, "demo.json"))

    # 5) 样例文件（供下载按钮使用）
    for name, src in (
        ("字数分配表-示例.xlsx", os.path.join(ROOT, "data", "字数分配表-示例.xlsx")),
        ("编写名单模板.xlsx", None),
    ):
        dst = os.path.join(OUT, name)
        if src and os.path.exists(src):
            shutil.copy(src, dst)
        elif name == "编写名单模板.xlsx":
            sys.path.insert(0, os.path.join(ROOT, "app"))
            from people_import import build_people_template  # noqa: PLC0415
            with open(dst, "wb") as f:
                f.write(build_people_template().getvalue())

    # 6) 关掉 Jekyll，避免大文件触发构建超时
    open(os.path.join(OUT, ".nojekyll"), "w").close()

    files = sorted(f for f in os.listdir(OUT) if not f.startswith("."))
    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in files if os.path.isfile(os.path.join(OUT, f)))
    print(f"已生成 docs/：{len(files)} 个文件，{total // 1024} KB")
    for f in files:
        p = os.path.join(OUT, f)
        if os.path.isfile(p):
            print(f"  {f}  {os.path.getsize(p) // 1024 or os.path.getsize(p)}"
                  f"{'KB' if os.path.getsize(p) >= 1024 else 'B'}")


if __name__ == "__main__":
    build(refresh="--refresh" in sys.argv)
