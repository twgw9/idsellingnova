#!/usr/bin/env bash
# Premium ID Store Bot — start script
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "⚠️  .env nahi mila — .env.example copy kar raha hoon."
    cp .env.example .env
fi

[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

exec python main.py
