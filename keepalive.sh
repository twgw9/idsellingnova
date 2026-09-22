#!/usr/bin/env bash
# =============================================================================
#  alwaysdata (free plan) — background process allowed nahi, isliye ye script
#  ko "Scheduled Tasks" me har 5 minute chalao:
#      Command: /home/<user>/idsellingnova/keepalive.sh
#  Bot gir gaya / server restart hua to ye khud dobara start kar deta hai.
#  /shutdown kar diya ho to bot.stopped file bana deta hai — tab start NAHI karega.
# =============================================================================
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
PIDFILE="$DIR/bot.pid"
LOG="$DIR/bot.log"
PY="$DIR/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"

if [ -f "$DIR/bot.stopped" ]; then
    echo "[$(date '+%F %T')] bot.stopped maujood hai — start nahi kar raha."
    exit 0
fi

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0                       # chal raha hai, kuch mat karo
fi

# purane log ko ghuma do (free plan me disk chhoti hoti hai)
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 2000000 ]; then
    mv "$LOG" "$LOG.old"
fi

nohup "$PY" main.py >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
echo "[$(date '+%F %T')] bot started (pid $(cat "$PIDFILE"))"
