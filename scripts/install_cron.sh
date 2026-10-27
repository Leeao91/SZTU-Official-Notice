#!/usr/bin/env bash
# 在 Linux / macOS 上用 cron 每天 18:00 跑一次
# 用法：bash scripts/install_cron.sh [时间，如 08:30]
set -euo pipefail

HHMM="${1:-18:00}"
HOUR="${HHMM%%:*}"
MIN="${HHMM##*:}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3 || command -v python)"

TAG="# nbwdigest daily digest"
LINE="$MIN $HOUR * * * cd $ROOT && $PY -m nbwdigest >> $ROOT/logs/cron.log 2>&1 $TAG"

mkdir -p "$ROOT/logs"
( crontab -l 2>/dev/null | grep -v "$TAG" || true; echo "$LINE" ) | crontab -

echo "已安装 cron 任务（每天 $HHMM）："
crontab -l | grep "$TAG"
echo
echo "取消： crontab -e 后删掉那一行；或 crontab -l | grep -v nbwdigest | crontab -"
