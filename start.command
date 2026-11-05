#!/bin/bash
# 双击运行本文件即可启动「书稿字数分配工具」
cd "$(dirname "$0")" || exit 1

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "未找到 python3，请先安装 Python 3.9 或更高版本"
  read -r -p "按回车键关闭…" _
  exit 1
fi

echo "启动后终端会打印内网地址，同 Wi-Fi 的手机/电脑可直接访问。"
echo "正在检查依赖…"
$PY - <<'PYCHK' || { echo "缺少依赖，请执行： python3 -m pip install --user fastapi uvicorn pymupdf openpyxl python-multipart"; read -r -p "按回车键关闭…" _; exit 1; }
import importlib, sys
missing = [m for m in ("fitz", "fastapi", "uvicorn", "openpyxl", "multipart") if not __import__("importlib.util").util.find_spec(m)]
if missing:
    sys.exit(1)
PYCHK

$PY app/server.py
