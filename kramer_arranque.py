"""Arranque de la app: decide de dónde se carga el código (kramer/ + web/).

Si en la carpeta de datos hay un paquete de actualización firmado, más nuevo y compatible, se usa ese;
si no, el código que viene con la app. Este archivo queda fuera del paquete `kramer` a propósito:
ninguna actualización lo puede reemplazar.
"""
import hashlib
import importlib
import io
import json
import os
import re
import shutil
import sys
import threading
import traceback
import zipfile
from pathlib import Path

SHELL = 1
URL_BASE = os.environ.get("KRAMER_ACTUALIZACION_URL", "")
CLAVE_PUBLICA = os.environ.get("KRAMER_ACTUALIZACION_CLAVE", "")

INCLUIDO = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
VERSION_INCLUIDA = (INCLUIDO / "web" / "version.txt").read_text(encoding="utf-8").strip()


def _dir_app():
    if sys.platform.startswith("win"):
        defecto = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "KramerDJ"
    else:
        defecto = Path.home() / "Library/Application Support/KramerDJ"
    return Path(os.environ.get("KRAMER_APP_DIR", defecto))


DIR_APP = _dir_app()
DIR = DIR_APP / "actualizacion"
ESTADO = {"activo": bool(URL_BASE and CLAVE_PUBLICA), "origen": "incluido", "version": VERSION_INCLUIDA,
          "carpeta": str(INCLUIDO), "motivo": "", "buscando": False, "lista": ""}
FALLAS = (ImportError, SyntaxError, NameError, AttributeError, TypeError, ValueError, LookupError,
          ArithmeticError, AssertionError, OSError, RuntimeError)

_VERSION = re.compile(r"\d+(\.\d+)*")
_SHA = re.compile(r"[0-9a-f]{64}")
_ARCHIVO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.zip")
_PARTE = re.compile(r"[\w.\- ]+")


class PaqueteInvalido(Exception):
    pass


def estado():
    return dict(ESTADO)


def _num(version):
    if not _VERSION.fullmatch(version):
        raise PaqueteInvalido(f"la versión «{version}» no es un número con puntos")
    return tuple(int(x) for x in version.split("."))


def _json(datos, campos):
    try:
        d = json.loads(datos)
    except ValueError:
        raise PaqueteInvalido("el manifiesto no se puede leer")
    if not isinstance(d, dict) or any(k not in d or type(d[k]) is not t for k, t in campos.items()):
        raise PaqueteInvalido("al manifiesto le faltan datos")
    return d


def leer_sobre(datos, clave_publica):
    """Comprueba la firma Ed25519 del manifiesto y lo devuelve; si algo no cierra, lanza PaqueteInvalido."""
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey
    sobre = _json(datos, {"manifiesto": str, "firma": str})
    try:
        VerifyKey(bytes.fromhex(clave_publica)).verify(sobre["manifiesto"].encode("utf-8"), bytes.fromhex(sobre["firma"]))
    except (BadSignatureError, ValueError):
        raise PaqueteInvalido("la firma del manifiesto no es válida")
    m = _json(sobre["manifiesto"], {"version": str, "shell": int, "sha256": str, "tamano": int, "archivo": str})
    if not (_VERSION.fullmatch(m["version"]) and _SHA.fullmatch(m["sha256"]) and _ARCHIVO.fullmatch(m["archivo"])):
        raise PaqueteInvalido("el manifiesto tiene datos inválidos")
    return m


def comprobar_zip(datos, manifiesto):
    if len(datos) != manifiesto["tamano"] or hashlib.sha256(datos).hexdigest() != manifiesto["sha256"]:
        raise PaqueteInvalido("el paquete no coincide con el manifiesto firmado")


def ruta_valida(nombre):
    partes = nombre.split("/")
    return len(partes) > 1 and partes[0] in ("kramer", "web") and all(_PARTE.fullmatch(p) and p.strip(". ") for p in partes)


def _escribir(ruta, datos):
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_bytes(datos)
    os.replace(tmp, ruta)


def _malas():
    try:
        return _json((DIR / "malas.json").read_bytes(), {})
    except (OSError, PaqueteInvalido):
        return {}


def _marcar_mala(version, motivo):
    malas = _malas()
    malas[version] = motivo
    _escribir(DIR / "malas.json", json.dumps(malas, ensure_ascii=False, indent=1).encode("utf-8"))


def _ajeno_vivo(ruta):
    import psutil
    pid = ruta.stem.rpartition("-")[2]
    return pid.isdigit() and len(pid) < 10 and int(pid) != os.getpid() and psutil.pid_exists(int(pid))


def _limpiar():
    for carpeta in DIR.glob("codigo-*"):
        if not _ajeno_vivo(carpeta):
            shutil.rmtree(carpeta, ignore_errors=True)
    for testigo in DIR.glob("probando-*.txt"):
        if not _ajeno_vivo(testigo):
            version = testigo.read_bytes().decode("ascii", "replace").strip()
            testigo.unlink()
            if _VERSION.fullmatch(version):
                _marcar_mala(version, "la app se cerró mientras cargaba esta versión")


def _elegir():
    sobre = DIR / "manifiesto.json"
    if not sobre.is_file():
        return None
    manifiesto = leer_sobre(sobre.read_bytes(), CLAVE_PUBLICA)
    try:
        datos = (DIR / manifiesto["archivo"]).read_bytes()
    except FileNotFoundError:
        raise PaqueteInvalido(f"falta el archivo {manifiesto['archivo']}")
    comprobar_zip(datos, manifiesto)
    version = manifiesto["version"]
    if manifiesto["shell"] > SHELL:
        raise PaqueteInvalido(f"el paquete {version} necesita una app más nueva (shell {manifiesto['shell']}, esta es {SHELL})")
    if _num(version) <= _num(VERSION_INCLUIDA):
        raise PaqueteInvalido(f"el paquete {version} no es más nuevo que el código de la app ({VERSION_INCLUIDA})")
    if version in _malas():
        raise PaqueteInvalido(f"el paquete {version} ya falló antes en esta computadora")
    return manifiesto, datos


def _extraer(datos, carpeta):
    if carpeta.exists():
        shutil.rmtree(carpeta)
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            for info in z.infolist():
                if not ruta_valida(info.filename):
                    raise PaqueteInvalido(f"el paquete trae un archivo que no corresponde: {info.filename}")
                destino = carpeta.joinpath(*info.filename.split("/"))
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(z.read(info))
    except zipfile.BadZipFile:
        raise PaqueteInvalido("el paquete no es un zip válido")


def _volver_al_incluido(carpeta):
    sys.path.remove(str(carpeta))
    for nombre in [n for n in sys.modules if n == "kramer" or n.startswith("kramer.")]:
        del sys.modules[nombre]
    importlib.invalidate_caches()
    ESTADO.update(origen="incluido", version=VERSION_INCLUIDA, carpeta=str(INCLUIDO))


def _cargar_paquete():
    _limpiar()
    elegido = _elegir()
    if elegido is None:
        return
    manifiesto, datos = elegido
    version = manifiesto["version"]
    carpeta = DIR / f"codigo-{os.getpid()}"
    testigo = DIR / f"probando-{os.getpid()}.txt"
    _extraer(datos, carpeta)
    _escribir(testigo, version.encode("ascii"))
    sys.path.insert(0, str(carpeta))
    ESTADO.update(origen="paquete", version=version, carpeta=str(carpeta))
    try:
        servidor = importlib.import_module("kramer.servidor")
        if Path(servidor.__file__).resolve().parent.parent != carpeta.resolve():
            raise ImportError("el código no se cargó desde el paquete")
    except FALLAS:
        _volver_al_incluido(carpeta)
        _marcar_mala(version, traceback.format_exc()[-3000:])
        testigo.unlink()
        raise PaqueteInvalido(f"el paquete {version} falló al cargar; queda descartado")
    testigo.unlink()


def preparar():
    """Elige el código de esta sesión y deja sys.path listo. Hay que llamarla antes de importar `kramer`."""
    if not ESTADO["activo"]:
        return
    try:
        _cargar_paquete()
    except (PaqueteInvalido, OSError, ImportError) as e:
        ESTADO["motivo"] = str(e)
        print(f"Actualización: sigo con el código de la app ({VERSION_INCLUIDA}): {e}", flush=True)


def buscar():
    """Busca en segundo plano un paquete más nuevo. Lo que baja recién se usa la próxima vez que se abre la app."""
    if ESTADO["activo"]:
        ESTADO["buscando"] = True
        threading.Thread(target=_buscar, daemon=True).start()


def _buscar():
    import requests
    base = URL_BASE.rstrip("/")
    try:
        r = requests.get(f"{base}/manifiesto.json", timeout=5)
        r.raise_for_status()
        sobre = r.content
        manifiesto = leer_sobre(sobre, CLAVE_PUBLICA)
        version = manifiesto["version"]
        if manifiesto["shell"] > SHELL or _num(version) <= _num(ESTADO["version"]) or version in _malas():
            return
        r = requests.get(f"{base}/{manifiesto['archivo']}", timeout=(5, 30), stream=True)
        r.raise_for_status()
        datos = b""
        for trozo in r.iter_content(65536):
            datos += trozo
            if len(datos) > manifiesto["tamano"]:
                break
        comprobar_zip(datos, manifiesto)
        DIR.mkdir(parents=True, exist_ok=True)
        _escribir(DIR / manifiesto["archivo"], datos)
        _escribir(DIR / "manifiesto.json", sobre)
        for viejo in DIR.glob("*.zip"):
            if viejo.name != manifiesto["archivo"]:
                viejo.unlink()
        ESTADO["lista"] = version
        print(f"Actualización: el paquete {version} quedó listo; se aplica la próxima vez que se abra la app.", flush=True)
    except requests.RequestException:
        pass
    except (PaqueteInvalido, OSError, ImportError) as e:
        print(f"Actualización: no pude bajar el paquete nuevo: {e}", flush=True)
    finally:
        ESTADO["buscando"] = False
