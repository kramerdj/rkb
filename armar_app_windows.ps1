# Arma "RKB Collection Manager.exe" para Windows: un solo archivo, con ventana propia, sin instalar nada.
# Se corre con doble clic en armar_app_windows.bat (que llama a este script).
$ErrorActionPreference = "Stop"
$SRC = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $SRC
$DESC = if ($env:KRAMER_SALIDA) { $env:KRAMER_SALIDA } else { Join-Path $env:USERPROFILE "Downloads" }
New-Item -ItemType Directory -Force -Path $DESC | Out-Null
$FALLO = $false
$LOG = Join-Path $DESC "kramer_build_windows.txt"
Start-Transcript -Path $LOG -Force | Out-Null
Write-Host "=== Armando RKB Collection Manager.exe ($(Get-Date)) ==="

try {
  # 1) uv: trae su propio Python 3.13 sin tocar nada de la computadora
  $UV = (Get-Command uv -ErrorAction SilentlyContinue).Source
  if (-not $UV) { $UV = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
  if (-not (Test-Path $UV)) {
    Write-Host "Bajando uv..."
    powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
  }
  if (-not (Test-Path $UV)) { throw "No se pudo instalar uv. Revisá la conexión a internet." }

  $B = Join-Path $env:LOCALAPPDATA "KramerDJ-build"
  New-Item -ItemType Directory -Force -Path $B | Out-Null
  $PY = Join-Path $B "venv\Scripts\python.exe"
  if (-not (Test-Path $PY)) { & $UV venv --python 3.13 (Join-Path $B "venv") }
  Write-Host "Instalando librerías..."
  & $UV pip install --python $PY -q pyinstaller pywebview pyrekordbox mutagen requests numpy pillow imageio-ffmpeg pynacl psutil
  if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de librerías." }
  & $PY -c "import webview, pyrekordbox, mutagen, PyInstaller, requests, PIL, imageio_ffmpeg, clr, nacl, psutil; print('Librerías OK', pyrekordbox.__version__)"
  if ($LASTEXITCODE -ne 0) { throw "Falta alguna librería (mirá el mensaje de arriba)." }

  # 2) ícono .ico y código fuente adentro (la licencia GPL pide compartirlo junto con la app)
  $ICO = Join-Path $B "Kramer.ico"
  $ZIP = Join-Path $B "codigo-fuente.zip"
  & $PY -c @"
import sys, zipfile, os
from PIL import Image
src, ico, z = sys.argv[1], sys.argv[2], sys.argv[3]
Image.open(os.path.join(src, 'icono.png')).save(ico, sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as zf:
    for raiz in ('kramer', 'web', 'distribucion'):
        for base, dirs, files in os.walk(os.path.join(src, raiz)):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in files:
                if not f.endswith('.pyc'):
                    p = os.path.join(base, f); zf.write(p, os.path.relpath(p, src))
    for f in ('kramer_ventana.py', 'kramer_app.py', 'kramer_arranque.py', 'publicar_actualizacion.py', 'armar_app.command', 'armar_app_windows.bat', 'armar_app_windows.ps1', 'supabase.sql', 'icono.png'):
        if os.path.exists(os.path.join(src, f)): zf.write(os.path.join(src, f), f)
"@ $SRC $ICO $ZIP
  if ($LASTEXITCODE -ne 0) { throw "No se pudo preparar el ícono o el código fuente." }

  # 3) armado: un solo .exe
  $DIST = Join-Path $B "dist"; $WORK = Join-Path $B "work"
  Remove-Item -Recurse -Force $DIST, $WORK -ErrorAction SilentlyContinue
  $PYI = Join-Path $B "venv\Scripts\pyinstaller.exe"
  & $PYI --noconfirm --log-level WARN --onefile --windowed --name "RKB Collection Manager" `
    --icon $ICO --add-data "$SRC\web;web" --add-data "$ZIP;." --paths $SRC `
    --collect-all pyrekordbox --collect-all sqlcipher3 --collect-all imageio_ffmpeg --collect-all webview `
    --collect-submodules kramer --hidden-import clr --hidden-import _cffi_backend `
    --distpath $DIST --workpath $WORK --specpath $B `
    (Join-Path $SRC "kramer_ventana.py")
  if ($LASTEXITCODE -ne 0) { throw "Falló PyInstaller (mirá los mensajes de arriba)." }
  $EXE = Join-Path $DIST "RKB Collection Manager.exe"
  if (-not (Test-Path $EXE)) { throw "No se generó el .exe" }

  # 4) prueba rápida del motor (sin abrir ventana)
  $p = Start-Process -FilePath $EXE -ArgumentList "--mytags","--help" -PassThru -WindowStyle Hidden
  if ($p.WaitForExit(60000) -and $p.ExitCode -eq 0) { Write-Host "Prueba interna OK" } else { Write-Host "Aviso: la prueba interna no respondió (sigo igual)" }
  $version = (& $EXE --version | Out-String).Trim()
  if ($version) { Write-Host $version } else { Write-Host "Aviso: la app no informó su versión (sigo igual)" }

  # 5) dejar el .exe y un zip para compartir en Descargas
  $FINAL = Join-Path $DESC "RKB Collection Manager.exe"
  Copy-Item $EXE $FINAL -Force
  $ZIPW = Join-Path $DESC "RKB Collection Manager (Windows).zip"
  Remove-Item $ZIPW -ErrorAction SilentlyContinue
  $LEEME = Join-Path $B "LEEME - Instalación.txt"
  Copy-Item (Join-Path $SRC "distribucion\LEEME Windows.txt") $LEEME -Force
  Compress-Archive -Path $FINAL, $LEEME -DestinationPath $ZIPW
  $MB = [math]::Round((Get-Item $FINAL).Length / 1MB)
  Write-Host ""
  Write-Host "Listo:"
  Write-Host " · App: $FINAL ($MB MB)"
  Write-Host " · Para compartir: $ZIPW"
  if (-not $env:KRAMER_SALIDA) { Start-Process explorer.exe "/select,`"$FINAL`"" }
}
catch {
  Write-Host ""
  Write-Host "ERROR: $_" -ForegroundColor Red
  Write-Host "El detalle quedó en $LOG"
  $FALLO = $true
}
finally {
  Stop-Transcript | Out-Null
}
if ($FALLO) { exit 1 }
