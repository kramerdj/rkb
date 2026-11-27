#!/bin/bash
# Instalador de Kramer DJ (Etapa 1). Se puede volver a correr para actualizar: no toca tus datos.
set -e
cd "$(dirname "$0")"
DIR="$HOME/Library/Application Support/KramerDJ"
echo "=== Instalando Kramer DJ ==="

PY=""
for v in 3.15 3.14 3.13 3.12 3.11; do
  if command -v "python$v" >/dev/null 2>&1; then PY="$(command -v python$v)"; break; fi
done
if [ -z "$PY" ]; then
  echo "No encontré Python 3.11 o más nuevo. Instalalo desde python.org y volvé a correr esto."
  exit 1
fi
echo "Python: $PY"

mkdir -p "$DIR"
rm -rf "$DIR/app"
mkdir -p "$DIR/app"
cp -R kramer web kramer_app.py kramer_arranque.py "$DIR/app/"

if [ ! -x "$DIR/venv/bin/python" ]; then
  echo "Preparando el entorno (una sola vez)…"
  "$PY" -m venv --system-site-packages "$DIR/venv"
fi
"$DIR/venv/bin/python" -m pip install -q --disable-pip-version-check pyrekordbox mutagen
"$DIR/venv/bin/python" -c "import pyrekordbox, mutagen; print('Librerías OK')"

# ---- la app (.app) ----
DEST="/Applications"
[ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
APPB="$DEST/Kramer DJ.app"
rm -rf "$APPB"
mkdir -p "$APPB/Contents/MacOS" "$APPB/Contents/Resources"
cp lanzador.sh "$APPB/Contents/MacOS/KramerDJ"
chmod +x "$APPB/Contents/MacOS/KramerDJ"
if [ -f icono.png ]; then
  T="$(mktemp -d)/Kramer.iconset"; mkdir -p "$T"
  for s in 16 32 128 256 512; do
    sips -z $s $s icono.png --out "$T/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) icono.png --out "$T/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$T" -o "$APPB/Contents/Resources/Kramer.icns" || true
fi
cat > "$APPB/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Kramer DJ</string>
<key>CFBundleDisplayName</key><string>Kramer DJ</string>
<key>CFBundleIdentifier</key><string>ar.kramerdj.coleccion</string>
<key>CFBundleVersion</key><string>0.1</string>
<key>CFBundleShortVersionString</key><string>0.1</string>
<key>CFBundleExecutable</key><string>KramerDJ</string>
<key>CFBundleIconFile</key><string>Kramer</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSMinimumSystemVersion</key><string>12.0</string>
<key>LSArchitecturePriority</key><array><string>arm64</string><string>x86_64</string></array>
</dict></plist>
PL

# si el motor viejo está corriendo, se reinicia con la versión nueva
curl -s -m 1 -X POST -H "Content-Type: application/json" -d "{}" http://127.0.0.1:8765/api/salir >/dev/null 2>&1 || true
sleep 1
echo ""
echo "Listo: la app quedó en $APPB"
open "$APPB"
