#!/bin/bash
# start.sh — 启动后端服务
# 自动清理 8000 端口残留进程，再启动 FastAPI

set -e

PORT=8000

# 杀掉占用端口的进程（如果有）
PIDS=$(lsof -ti:$PORT 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  echo "⚠️  端口 $PORT 被占用，正在清理..."
  echo "$PIDS" | xargs kill -9
  sleep 1
  echo "✅ 已清理"
fi

echo "🚀 启动后端服务..."
conda run -n base python main.py
