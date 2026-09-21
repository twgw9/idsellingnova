#!/usr/bin/env bash
# run.sh ka shortcut — `bash start.sh` se bhi chal jaye
cd "$(dirname "$0")" || exit 1
exec bash run.sh
