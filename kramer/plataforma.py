"""Lo que cambia entre Mac y Windows: carpetas por defecto y abrir archivos/carpetas/links."""
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

ES_WIN = sys.platform.startswith("win")
ES_MAC = sys.platform == "darwin"
HOME = Path.home()


def _appdata():
    return Path(os.environ.get("APPDATA") or HOME / "AppData/Roaming")


def dir_app():
    """Configuración de la app (config.json, pendientes)."""
    if ES_WIN:
        return _appdata() / "KramerDJ"
    return HOME / "Library/Application Support/KramerDJ"


def dir_rekordbox():
    """Carpeta donde Rekordbox 6/7 guarda master.db y la carpeta share (análisis, cues, carátulas)."""
    if ES_WIN:
        return _appdata() / "Pioneer/rekordbox"
    return HOME / "Library/Pioneer/rekordbox"


def descargas():
    return HOME / "Downloads"


def abrir(ruta):
    """Abre un archivo o carpeta con la app que corresponda."""
    ruta = str(ruta)
    if ES_WIN:
        os.startfile(ruta)                     # noqa:  (sólo existe en Windows)
    else:
        subprocess.run(["open", ruta])


def mostrar(ruta):
    """Muestra el archivo seleccionado en el Finder / Explorador."""
    ruta = str(ruta)
    if ES_WIN:
        subprocess.run(["explorer", "/select,", os.path.normpath(ruta)])
    else:
        subprocess.run(["open", "-R", ruta])


def abrir_url(url):
    if ES_MAC:
        subprocess.run(["open", url])
    else:
        webbrowser.open(url)


def abrir_privacidad():
    """Sólo Mac: Ajustes → Privacidad → Acceso total al disco."""
    if ES_MAC:
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])


def elegir_carpeta(titulo):
    """Selector de carpeta cuando no hay ventana propia (modo navegador)."""
    if ES_MAC:
        script = "on run argv\nreturn POSIX path of (choose folder with prompt (item 1 of argv))\nend run"
        r = subprocess.run(["osascript", "-e", script, str(titulo)], capture_output=True, text=True)
        return r.stdout.strip().rstrip("/")
    try:
        import tkinter
        from tkinter import filedialog
        raiz = tkinter.Tk()
        raiz.withdraw()
        raiz.attributes("-topmost", True)
        r = filedialog.askdirectory(title=titulo) or ""
        raiz.destroy()
        return r
    except Exception:
        return ""
