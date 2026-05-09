#!/bin/bash
# stop.sh — 关闭后端服务
# 清理 8000 端口上的所有进程

PORT=8000

PIDS=$(lsof -ti:$PORT 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  echo "$PIDS" | xargs kill -9
  echo "✅ 后端已关闭（端口 $PORT 已释放）"
else
  echo "ℹ️  端口 $PORT 没有运行中的进程"
fi
