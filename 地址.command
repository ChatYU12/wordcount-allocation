#!/bin/bash
# 双击运行：打印本工具当前的访问地址，并把内网地址复制到剪贴板
cd "$(dirname "$0")" || exit 1

BASE_PORT=${PORT:-8770}

find_port() {
  for p in $(seq "$BASE_PORT" $((BASE_PORT + 60))); do
    if lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | grep -q Python; then
      echo "$p"; return 0
    fi
  done
  return 1
}

echo "──────────────────────────────────────────"
echo "  书稿字数分配工具 · 当前访问地址"
echo "──────────────────────────────────────────"

PORT_NOW=$(find_port)
if [ -z "$PORT_NOW" ]; then
  echo "  服务没有在运行。"
  echo "  请先双击 start.command 启动，再回来看地址。"
  echo "──────────────────────────────────────────"
  read -r -p "按回车键关闭…" _
  exit 0
fi

IPS=$(ifconfig 2>/dev/null | awk '/inet /{print $2}' | grep -v '^127\.')
if [ -z "$IPS" ]; then
  echo "  未检测到局域网地址（可能没连 Wi-Fi 或网线）。"
  echo "  本机访问：http://127.0.0.1:$PORT_NOW"
else
  for ip in $IPS; do
    echo "  内网访问：http://$ip:$PORT_NOW"
  done
  MAIN=$(echo "$IPS" | head -1)
  printf "http://%s:%s" "$MAIN" "$PORT_NOW" | pbcopy
  echo ""
  echo "  （已复制到剪贴板，可直接粘贴发给同事）"
fi
echo "  本机访问：http://127.0.0.1:$PORT_NOW"
echo "  主机名  ：http://$(hostname -s).local:$PORT_NOW"
echo "──────────────────────────────────────────"
read -r -p "按回车键关闭…" _
