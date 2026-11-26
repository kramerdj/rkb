#!/bin/bash
# Arma "RKB Collection Manager.app": una sola app con ventana propia, sin instalar nada aparte.
set -e
cd "$(dirname "$0")"
SRC="$(pwd)"
LOG="$HOME/Downloads/kramer_build.txt"
exec > >(tee "$LOG") 2>&1
echo "=== Armando RKB Collection Manager.app ($(date)) ==="

# 1) uv: trae su propio Python 3.13 sin tocar el de la Mac
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  echo "Bajando uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"

B="$HOME/Library/Caches/KramerDJ-build"
mkdir -p "$B"
if [ ! -x "$B/venv/bin/python" ]; then
  "$UV" venv --python 3.13 "$B/venv"
fi
echo "Instalando librerías…"
"$UV" pip install --python "$B/venv/bin/python" -q pyinstaller pywebview pyrekordbox mutagen requests numpy pillow imageio-ffmpeg
"$B/venv/bin/python" -c "import webview, pyrekordbox, mutagen, PyInstaller, requests, PIL, imageio_ffmpeg; print('Librerías OK', pyrekordbox.__version__)"

# 2) ícono
T="$B/Kramer.iconset"; rm -rf "$T"; mkdir -p "$T"
for s in 16 32 128 256 512; do
  sips -z $s $s icono.png --out "$T/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) icono.png --out "$T/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$T" -o "$B/Kramer.icns"

# 2b) código fuente adentro de la app (la licencia GPL pide compartirlo junto con la app)
rm -f "$B/codigo-fuente.zip"
(cd "$SRC" && zip -qr "$B/codigo-fuente.zip" kramer web kramer_ventana.py kramer_app.py armar_app.command armar_app_windows.bat armar_app_windows.ps1 supabase.sql distribucion icono.png -x '*__pycache__*' '*.pyc')

# 3) armado
rm -rf "$B/dist" "$B/work"
"$B/venv/bin/pyinstaller" --noconfirm --log-level WARN --windowed --name "RKB Collection Manager" \
  --icon "$B/Kramer.icns" --osx-bundle-identifier ar.kramerdj.rkbcollectionmanager \
  --add-data "$SRC/web:web" --add-data "$B/codigo-fuente.zip:." --paths "$SRC" \
  --collect-all pyrekordbox --collect-all sqlcipher3 --collect-all imageio_ffmpeg --collect-submodules kramer \
  --distpath "$B/dist" --workpath "$B/work" --specpath "$B" \
  "$SRC/kramer_ventana.py"

APP="$B/dist/RKB Collection Manager.app"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString 0.8" "$APP/Contents/Info.plist" || true
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 12.0" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :NSHumanReadableCopyright string '© 2026 Guido · KRAMER DJ. Software libre (GPL-3.0). Hecha con la asistencia de Claude (Anthropic).'" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :NSAppleEventsUsageDescription string 'Para abrir carpetas en el Finder.'" "$APP/Contents/Info.plist" 2>/dev/null || true

# Firma: después de tocar el Info.plist hay que volver a firmar. Con un requisito fijo
# (el identificador de la app), macOS reconoce las versiones nuevas como la misma app y
# conserva los permisos (Acceso total al disco) entre una versión y otra.
ID="ar.kramerdj.rkbcollectionmanager"
codesign --force --deep --sign - "$APP" 2>/dev/null || true
codesign --force --sign - --identifier "$ID" -r="designated => identifier \"$ID\"" "$APP"
codesign --verify --deep --strict "$APP" && echo "Firma OK" || echo "Aviso: revisá la firma (sigo igual)"

# 4) prueba rápida: que arranque el motor (sin abrir ventana)
"$APP/Contents/MacOS/RKB Collection Manager" --mytags --help >/dev/null 2>&1 && echo "Prueba interna OK" || echo "Aviso: la prueba interna no respondió (sigo igual)"

# 5) reemplazar la versión anterior y dejar un zip para compartir
curl -s -m 1 -X POST http://127.0.0.1:8765/api/salir >/dev/null 2>&1 || true
rm -rf "/Applications/Kramer DJ.app" "$HOME/Applications/Kramer DJ.app"   # versión vieja
rm -rf "/Applications/RKB Collection Manager.app"
ditto "$APP" "/Applications/RKB Collection Manager.app"
rm -f "$HOME/Downloads/RKB Collection Manager (Mac).zip"
# el zip para compartir lleva la app y las instrucciones de instalación
P="$B/paquete/RKB Collection Manager"; rm -rf "$B/paquete"; mkdir -p "$P"
ditto "$APP" "$P/RKB Collection Manager.app"
cp "$SRC/distribucion/LEEME Mac.txt" "$P/LEEME - Instalación.txt"
ditto -c -k --keepParent "$P" "$HOME/Downloads/RKB Collection Manager (Mac).zip"
echo ""
echo "Listo:"
echo " · App: /Applications/RKB Collection Manager.app ($(du -sh "/Applications/RKB Collection Manager.app" | cut -f1))"
echo " · Para compartir: ~/Downloads/RKB Collection Manager (Mac).zip"
open "/Applications/RKB Collection Manager.app"
