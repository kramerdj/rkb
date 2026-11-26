#!/bin/bash
# Kramer DJ — abre la app (arranca el motor si no está corriendo)
DIR="$HOME/Library/Application Support/KramerDJ"
PORT=8765
URL="http://127.0.0.1:$PORT/"
if ! curl -s -m 1 "${URL}api/ping" >/dev/null 2>&1; then
  cd "$DIR/app" || exit 1
  # En Macs con chip Apple, forzar arm64 (si no, macOS lo puede abrir como Intel y falla)
  if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
    nohup arch -arm64 "$DIR/venv/bin/python" kramer_app.py >> "$DIR/app.log" 2>&1 &
  else
    nohup "$DIR/venv/bin/python" kramer_app.py >> "$DIR/app.log" 2>&1 &
  fi
  for i in $(seq 1 80); do
    curl -s -m 1 "${URL}api/ping" >/dev/null 2>&1 && break
    sleep 0.25
  done
fi
if [ -d "/Applications/Google Chrome.app" ]; then
  open -na "Google Chrome" --args --app="$URL" --user-data-dir="$DIR/ventana" --window-size=1440,900 --no-first-run --no-default-browser-check
else
  open "$URL"
fi
