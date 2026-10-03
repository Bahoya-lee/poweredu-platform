#!/usr/bin/env bash
# 电真万确 - AI 赋能电力教学仿真平台 一键启动（Linux / macOS）
# 仅本机模式：只监听 127.0.0.1，不开放端口、不需要改防火墙
set -e
cd "$(dirname "$0")"

PORT="${1:-8000}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[错误] 未检测到 python3，请先安装 Python 3.11 及以上版本。" >&2
  exit 1
fi

echo "运行方式：仅本机（http://127.0.0.1:${PORT}/），其他机器无法访问。"

export PYTHONIOENCODING=utf-8
exec python3 -m server.app --port "$PORT" --open
