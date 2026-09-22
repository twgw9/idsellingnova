#!/usr/bin/env bash
# Premium ID Store Bot — start script
#   bash run.sh            → foreground (screen / alwaysdata Service ke liye)
#   bash run.sh --daemon   → background + pidfile (keepalive.sh ke saath)
set -e
cd "$(dirname "$0")"

[ -f bot.stopped ] && rm -f bot.stopped          # /shutdown ka nishan hatao

if [ ! -f .env ]; then
    echo "⚠️  .env nahi mila — .env.example copy kar raha hoon (apni values daalo!)."
    cp .env.example .env
fi

[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ "$1" = "--daemon" ]; then
    nohup python main.py >> bot.log 2>&1 &
    echo $! > bot.pid
    echo "✅ Bot background me chal raha hai (pid $(cat bot.pid)) — log: bot.log"
else
    exec python main.py
fi
