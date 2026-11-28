"""Configuración de la app (por usuario) y carpetas de trabajo."""
import json
import os
import threading
from pathlib import Path

from . import plataforma

HOME = Path.home()
DIR_APP = Path(os.environ.get("KRAMER_APP_DIR", plataforma.dir_app()))
ARCHIVO = DIR_APP / "config.json"
PENDIENTES = DIR_APP / "pendientes.json"

MOMENTOS = ["Previa", "Warm Up", "Main", "Peak", "Close", "Lentos"]

DEFAULT = {
    "coleccion": str(HOME / "Music"),
    "incorporar": str(HOME / "Downloads"),
    "backup": str(HOME / "Documents/backup"),
    "rekordbox": str(plataforma.dir_rekordbox()),
    "teclas": ["Warm Up", "Main", "Peak", "Close"],
    "inicio": "30",            # "inicio" | "seg" | "30" (30 %) | "cue"
    "inicio_seg": 30,          # segundos desde el principio, cuando inicio = "seg"
    "lastfm": "",
    "discogs": "",
    "spotify_id": "",           # opcional: para leer playlists de Spotify de más de 100 temas
    "spotify_secret": "",
    "youtube_key": "",
    "spotify_refresh": "",      # autorización de tu cuenta (para crear playlists)
    "spotify_usuario": "",          # opcional: para leer playlists de YouTube de más de 100 videos
    "ingreso_campos": None,     # qué datos actualiza el paso 2
    "ingreso_fuentes": None,    # qué fuentes consulta
    "coleccion_campos": None,   # qué datos actualiza «Actualizar metadata» en Colección
    "evento": None,             # {"id": playlist, "nombre": ...} del último evento creado
    "categorias": None,         # las 4 categorías de My Tags (nombre y de dónde salen)
    "acepto_riesgo": False,     # aviso de uso bajo propio riesgo
    "tema": "",                 # "" = el del sistema, "claro" u "oscuro" (lo eligió la persona)
    "tema_estreno": False,      # la 0.9.5 arranca una vez en claro para que se note el cambio
    "guia_vista": False,        # la guía de bienvenida ya se mostró (se vuelve a ver desde «Acerca de»)
    "estadisticas": True,       # enviar estadísticas anónimas de uso (kramer/estadisticas.py)
    "estadisticas_avisado": False,  # ya vio la explicación (en el aviso del primer arranque o, si ya usaba la app, en uno propio)
    "estadisticas_estado": None,  # qué ya se envió y en cuántos días se usó (sólo local, nunca se envía tal cual)
    "respaldo_destino": "",     # dónde guardar los backups completos (mejor un disco externo)
    "respaldo_share": True,     # incluir análisis, cues y carátulas de Rekordbox (carpeta share)
    "respaldo_otros": True,
    "ubicacion": None,          # {"pais": "AR", "region": "Buenos Aires"}: qué anuncios ve en la cartelera
    "cartelera_inicio": True,   # mostrar las novedades de la cartelera al abrir la app
    "cartelera_vistos": [],     # anuncios ya vistos (para avisar sólo de los nuevos)
    "nube_sesion": None,        # sesión de "Mis anuncios"     # incluir temas de Rekordbox que están fuera de la carpeta de la colección
}

_lock = threading.Lock()


def _leer(ruta, defecto):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _escribir(ruta, datos):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ruta)


def cargar():
    with _lock:
        c = dict(DEFAULT)
        c.update(_leer(ARCHIVO, {}))
        return c


def guardar(cambios):
    with _lock:
        c = dict(DEFAULT)
        c.update(_leer(ARCHIVO, {}))
        for k, v in cambios.items():
            if k in DEFAULT:
                c[k] = v
        _escribir(ARCHIVO, c)
        return c


def dir_eliminados():
    """Adonde van los temas que se eliminan de la colección (nunca se borran del disco)."""
    return Path(cargar()["backup"]) / "eliminados"


def dir_backups():
    return Path(cargar()["backup"]) / "Kramer DJ app"


# ---------------- cambios pendientes (Momento y metadata) ----------------
def pendientes():
    with _lock:
        p = _leer(PENDIENTES, {})
        p.setdefault("momento", {})
        p.setdefault("meta", {})
        p.setdefault("tags", {})       # tags manuales de otras categorías: {tema: {categoría: [tags]}}
        return p


def guardar_pendientes(p):
    with _lock:
        _escribir(PENDIENTES, p)


def cambiar_pendientes(cambio):
    """Lee, cambia y guarda de una sola vez: dos pedidos a la vez no se pisan. cambio(p) modifica p."""
    with _lock:
        p = _leer(PENDIENTES, {})
        for k in ("momento", "meta", "tags"):
            p.setdefault(k, {})
        cambio(p)
        _escribir(PENDIENTES, p)
        return p
