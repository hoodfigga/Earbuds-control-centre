#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

# Append logs, truncate if over 1MB
if [ -f "$DIR/app.log" ] && [ $(stat -c%s "$DIR/app.log" 2>/dev/null || echo 0) -gt 1048576 ]; then
    > "$DIR/app.log"
fi

./venv/bin/python main.py >> "$DIR/app.log" 2>&1
