"""Servidor local de la app: sirve la interfaz (web/) y la API en http://127.0.0.1:PUERTO."""
import json
import re
import mimetypes
import os
import subprocess
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import kramer_arranque

from . import archivos, config, estadisticas, historial, plataforma, rb, trabajos

CONGELADA = getattr(sys, "frozen", False)          # True dentro de "Kramer DJ.app"
RAIZ = Path(kramer_arranque.estado()["carpeta"])
WEB = RAIZ / "web"
PUERTO = int(os.environ.get("KRAMER_PUERTO", "8765"))
RUTAS = {}            # id de tema -> ruta del archivo (para el reproductor)
VERSION = (WEB / "version.txt").read_text(encoding="utf-8").strip()
EN_VENTANA = False        # lo pone kramer_ventana.py
AL_SALIR = None           # callback para cerrar la ventana
ELEGIR_CARPETA = None     # selector nativo de la ventana


class Error(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


# ajustes internos que la página no ve
OCULTAS = ("nube_sesion", "spotify_refresh", "cartelera_vistos", "estadisticas_estado")


def tema_inicial():
    """Modo con el que se abre la página: la primera vez en la 0.9.5, claro (para que se note la novedad);
    después, el que eligió la persona o, si no eligió, el del sistema (vacío)."""
    c = config.cargar()
    if not c.get("tema_estreno"):
        try:
            config.guardar({"tema_estreno": True})
        except Exception:
            pass
        return "claro"
    return c.get("tema") if c.get("tema") in ("claro", "oscuro") else ""


def requiere_cerrado():
    if rb.rekordbox_abierto():
        raise Error("Rekordbox está abierto. Cerralo para guardar en la base; "
                    "tus cambios quedan pendientes mientras tanto.", 409)


# =============================================================================
# ACCIONES
# =============================================================================
_PERMISO = {"ok": None}


def permiso_archivos(forzar=False):
    """¿macOS deja leer la colección? (sin «Acceso total al disco» puede negarlo)."""
    if _PERMISO["ok"] is not None and not forzar:
        return _PERMISO["ok"]
    ok = True
    try:
        col = Path(config.cargar()["coleccion"])
        with os.scandir(col) as it:
            for e in it:
                if e.is_file() and Path(e.name).suffix.lower() in archivos_audio():
                    with open(e.path, "rb") as f:
                        f.read(16)
                    break
    except PermissionError:
        ok = False
    except FileNotFoundError:
        ok = True            # carpeta mal configurada: eso lo muestra otra parte
    except OSError as e:
        ok = getattr(e, "errno", 0) not in (1, 13)
    _PERMISO["ok"] = ok
    return ok


def archivos_audio():
    return {".mp3", ".m4a", ".mp4", ".aac", ".wav", ".aif", ".aiff", ".flac", ".ogg"}


def api_estado(q):
    estadisticas.al_abrir(VERSION)          # en segundo plano y como mucho una vez por día
    p = config.pendientes()
    forzar = bool(q and q.get("revisar"))
    return {"version": VERSION, "ventana": EN_VENTANA, "rekordboxAbierto": rb.rekordbox_abierto(),
            "config": {k: v for k, v in config.cargar().items() if k not in OCULTAS},
            "pendientes": len(p["momento"]) + len(p["meta"]) + len(p["tags"]), "permisoArchivos": permiso_archivos(forzar),
            "coleccionExiste": Path(config.cargar()["coleccion"]).is_dir(),
            "sistema": "windows" if plataforma.ES_WIN else "mac",
            "rekordboxExiste": (Path(config.cargar()["rekordbox"]) / "master.db").is_file()}


def api_informe(b):
    """Arma un zip para soporte: versión, sistema, ajustes (sin claves), registro de errores e historial.
    No incluye música, ni la base de Rekordbox, ni claves o sesiones."""
    import datetime
    import platform
    import zipfile
    secretos = {"lastfm", "discogs", "spotify_id", "spotify_secret", "spotify_refresh", "spotify_usuario",
                "youtube_key", "nube_sesion", "cartelera_vistos", "evento"}
    c = {k: ("(cargada)" if v else "") if k in secretos else v for k, v in config.cargar().items()}
    info = [f"RKB Collection Manager {VERSION}", f"Fecha: {datetime.datetime.now():%Y-%m-%d %H:%M}",
            f"Sistema: {platform.platform()} · {platform.machine()}", f"Python: {platform.python_version()}",
            f"Rekordbox abierto: {rb.rekordbox_abierto()}",
            f"Base de Rekordbox: {'sí' if (Path(c['rekordbox']) / 'master.db').is_file() else 'NO ENCONTRADA'}",
            f"Carpeta de la colección: {'existe' if Path(c['coleccion']).is_dir() else 'NO EXISTE'}",
            f"Permiso de archivos: {permiso_archivos(True)}"]
    try:
        info.append(f"Temas en Rekordbox: {len(RUTAS) or 'sin leer'}")
    except Exception:
        pass
    if b.get("texto"):
        info += ["", "Qué pasó (según el usuario):", str(b["texto"])[:3000]]
    destino = plataforma.descargas() / f"RKB informe {datetime.datetime.now():%Y-%m-%d %H%M}.zip"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("info.txt", "\n".join(info))
        z.writestr("ajustes.json", json.dumps(c, ensure_ascii=False, indent=1))
        z.writestr("historial.json", json.dumps(historial.listar()[:30], ensure_ascii=False, indent=1))
        for n in ("registro.txt", "registro-anterior.txt"):
            f = config.DIR_APP / n
            if f.is_file():
                z.writestr(n, f.read_bytes()[-2_000_000:])
    plataforma.mostrar(destino)
    return {"ruta": str(destino), "mensaje": f"Listo: guardé «{destino.name}» en Descargas. Mandáselo a Guido (KRAMER DJ)."}


def api_carpeta_sugerida(_):
    return {"ruta": rb.carpeta_sugerida()}


def api_abrir_privacidad(_):
    plataforma.abrir_privacidad()
    return {"ok": True}


def api_coleccion(_):
    datos = rb.leer_coleccion()
    RUTAS.clear()
    RUTAS.update({t["id"]: t["ruta"] for t in datos["temas"]})
    datos["pendientes"] = config.pendientes()
    return datos


def api_tema(q):
    tid = q.get("id", [""])[0]
    ruta = RUTAS.get(tid, "")
    if not ruta or not Path(ruta).is_file():
        raise Error("No encuentro el archivo de este tema.", 404)
    t = archivos.leer(ruta)
    t["pais"], t["idioma"] = archivos.pais_idioma(t.get("comentario", ""))
    t["archivo"] = Path(ruta).name
    t["carpeta"] = str(Path(ruta).parent)
    return t


def _anotar_pendiente(p, it):
    tid = str(it["id"])
    if it.get("quitarMomento"):
        p["momento"].pop(tid, None)
    elif "momento" in it:
        p["momento"][tid] = it["momento"] or ""
    if "meta" in it:
        meta = {k: str(v).strip() for k, v in it["meta"].items()}
        if meta:
            p["meta"][tid] = meta
        else:
            p["meta"].pop(tid, None)
    if "tags" in it:
        p["tags"][tid] = {str(k): list(v) for k, v in it["tags"].items()}
    if it.get("descartar"):
        for parte in ("momento", "meta", "tags"):
            p[parte].pop(tid, None)


def api_pendiente(b):
    return {"pendientes": config.cambiar_pendientes(lambda p: _anotar_pendiente(p, {k: v for k, v in b.items() if k != "tags"}))}


def api_pendiente_lote(b):
    """items: [{id, meta?: {...} (reemplaza), momento?: str, quitarMomento?: bool}]"""
    def lote(p):
        for it in b.get("items", []):
            _anotar_pendiente(p, {k: v for k, v in it.items() if k != "descartar"})
    return {"pendientes": config.cambiar_pendientes(lote)}


def api_descartar(_):
    config.guardar_pendientes({"momento": {}, "meta": {}, "tags": {}})
    return {"ok": True}


def api_sincronizar(_):
    requiere_cerrado()
    p = config.pendientes()
    if not p["momento"] and not p["meta"] and not p["tags"]:
        return {"mensaje": "No hay cambios pendientes."}
    partes = []
    if p["meta"]:
        partes.append(f"metadata de {len(p['meta'])} temas")
    if p["momento"]:
        partes.append(f"Momento de {len(p['momento'])} temas")
    if p["tags"]:
        partes.append(f"tags manuales de {len(p['tags'])} temas")
    with historial.Operacion("Sincronizar " + " y ".join(partes)) as op:
        r = rb.aplicar(p, op.respaldar_archivo, lambda s: None)
        op.detalle = "archivos + Rekordbox" if p["meta"] else "solo Rekordbox"
    def quitar_aplicados(actual):       # lo que se anotó mientras corría la sincronización sigue pendiente
        for parte in ("momento", "meta", "tags"):
            for tid, valor in p[parte].items():
                if actual[parte].get(tid) == valor:
                    del actual[parte][tid]
    config.cambiar_pendientes(quitar_aplicados)
    estadisticas.uso("sincronizar")
    return {"mensaje": "Listo: " + " y ".join(partes) + ".", "errores": r["errores"]}


def api_traer_buscar(_):
    return {"diferencias": rb.diferencias_con_archivos()}


def api_traer_aplicar(b):
    ids = set(map(str, b.get("ids", [])))
    difs = [d for d in rb.diferencias_con_archivos() if d["id"] in ids]
    errores = []
    with historial.Operacion("Traer cambios de Rekordbox a los archivos", con_base=False) as op:
        for d in difs:
            try:
                op.respaldar_archivo(d["ruta"])
                archivos.escribir(d["ruta"], d["cambios"])
            except Exception as e:
                errores.append(f"{Path(d['ruta']).name}: {e}")
        op.detalle = f"{len(difs) - len(errores)} archivos actualizados"
    return {"mensaje": f"Actualicé {len(difs) - len(errores)} archivos.", "errores": errores}


def api_duplicados(_):
    return {"grupos": rb.buscar_duplicados()}


def api_duplicados_borrar(b):
    requiere_cerrado()
    grupos = [g for g in b.get("grupos", []) if g.get("conservar") and g.get("borrar")]
    if not grupos:
        return {"mensaje": "No marcaste nada para borrar."}
    n = sum(len(g["borrar"]) for g in grupos)
    with historial.Operacion(f"Borrar {n} duplicados") as op:
        r = rb.borrar_duplicados(grupos, op.mover_archivo, lambda s: None)
        op.detalle = (f"{r['borrados']} temas fuera de la colección, {r['reemplazos']} reemplazos en playlists; "
                      "archivos guardados en el backup")
    extra = (f" En {r['yaEstaba']} playlists ya estaba la versión que queda, así que solo se sacó la repetida."
             if r["yaEstaba"] else "")
    estadisticas.uso("duplicados")
    return {"mensaje": f"Listo: borré {r['borrados']} duplicados e hice {r['reemplazos']} reemplazos en playlists.{extra} "
                       "Los archivos quedaron en el backup (se recuperan con Deshacer).", "errores": r["errores"]}


def api_eliminar_revisar(b):
    return {"temas": rb.revisar_eliminar(b.get("ids", [])), "carpeta": str(config.dir_eliminados())}


def api_eliminar(b):
    requiere_cerrado()
    ids = [str(i) for i in b.get("ids", [])]
    if not ids:
        return {"mensaje": "No elegiste ningún tema."}
    n = len(ids)
    with historial.Operacion(f"Eliminar {n} {'tema' if n == 1 else 'temas'}") as op:
        r = rb.eliminar_temas(ids, op.eliminar_archivo, lambda s: None)
        op.detalle = (f"{r['eliminados']} fuera de Rekordbox, {r['archivos']} archivos en «eliminados»"
                      + (f", sacados de {r['dePlaylists']} playlists" if r["dePlaylists"] else ""))
    # lo que quedaba pendiente de esos temas ya no tiene sentido
    def sin_esos_temas(p):
        for clave in ("momento", "meta", "tags"):
            for cid in ids:
                p[clave].pop(cid, None)
    config.cambiar_pendientes(sin_esos_temas)
    carpeta = config.dir_eliminados()
    return {"mensaje": (f"Listo: eliminé {r['eliminados']} {'tema' if r['eliminados'] == 1 else 'temas'} de Rekordbox. "
                        f"Los archivos quedaron en la carpeta «eliminados» ({carpeta}). Se puede deshacer desde Ajustes e historial."),
            "errores": r["errores"]}


def api_eliminados_abrir(_):
    d = config.dir_eliminados()
    d.mkdir(parents=True, exist_ok=True)
    plataforma.abrir(d)
    return {"ok": True}


# ---------------------------------------------------------------- 1 · LISTA
def api_lista_comparar(b):
    from . import lista
    items = lista.leer(b.get("texto", ""), b.get("nombre", ""))
    if not items:
        raise Error("No encontré temas en la lista. Usá una línea por tema: «Artista - Tema».")
    r = lista.comparar(items)
    estadisticas.uso("comparar lista")
    return {"items": r}


def api_lista_link(b):
    from . import streaming
    try:
        r = streaming.extraer(b.get("url", ""))
    except streaming.ErrorLink as e:
        raise Error(str(e))
    except Exception as e:
        raise Error(f"No pude leer el link ({type(e).__name__}). ¿Hay conexión a internet?")
    lineas = [f"{t['artista']} - {t['titulo']}" if t["artista"] else t["titulo"] for t in r["temas"]]
    return {**r, "texto": "\n".join(lineas)}


def api_spotify_estado(_):
    from . import streaming
    return streaming.spotify_estado()


def api_spotify_conectar(_):
    from . import streaming
    try:
        return {**streaming.spotify_conectar(), "mensaje": "Spotify conectado."}
    except streaming.ErrorLink as e:
        raise Error(str(e))


def api_spotify_desconectar(_):
    config.guardar({"spotify_refresh": "", "spotify_usuario": ""})
    return {"mensaje": "Spotify desconectado."}


def api_spotify_playlist(b):
    from . import streaming
    temas = [t for t in b.get("temas", []) if t.get("titulo")]
    if not temas:
        raise Error("La lista está vacía.")
    nombre = (b.get("nombre") or "Lista").strip()
    try:
        streaming._token_usuario()                   # falla rápido si no está conectado
    except streaming.ErrorLink as e:
        raise Error(str(e))
    t = trabajos.lanzar("spotify", lambda tr: streaming.spotify_crear_playlist(nombre, temas, b.get("publica"), tr),
                        total=len(temas))
    estadisticas.uso("playlist Spotify")
    return {"trabajo": t.id}


def ruta_libre(ruta):
    """Sólo deja escuchar archivos de la carpeta de descargas o de la colección."""
    c = config.cargar()
    try:
        p = Path(ruta).resolve()
        for base in (c["incorporar"], c["coleccion"]):
            if Path(base).resolve() in p.parents:
                return str(p)
    except Exception:
        pass
    return None


def api_incorporar_quitar(b):
    """Saca un tema de la lista de preparados; si 'eliminar', lo mueve a _descartados."""
    from . import ingreso
    ruta = b.get("ruta", "")
    lista = ingreso.leer_preparados()
    ingreso.guardar_preparados([p for p in lista if p["ruta"] != ruta])
    if b.get("eliminar") and ruta_libre(ruta) and Path(ruta).is_file():
        destino = ingreso._unico(Path(config.cargar()["incorporar"]) / ingreso.DESCARTADOS / Path(ruta).name)
        destino.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.move(ruta, destino)
        return {"mensaje": f"«{Path(ruta).name}» movido a {ingreso.DESCARTADOS} (no se borró del todo)."}
    return {"mensaje": f"«{Path(ruta).name}» quedó fuera de la lista (el archivo sigue en su carpeta)."}


def api_fuente(_):
    """Copia el código fuente de la app (requisito de la licencia GPL) a Descargas."""
    import shutil
    origen = kramer_arranque.INCLUIDO / "codigo-fuente.zip"
    if not origen.is_file():
        raise Error("Esta versión no trae el código fuente adentro.")
    destino = plataforma.descargas() / f"RKB Collection Manager {VERSION} - codigo fuente.zip"
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origen, destino)
    plataforma.mostrar(destino)
    return {"mensaje": f"Guardé el código fuente en Descargas ({destino.name})."}


def api_abrir_url(b):
    url = b.get("url", "")
    if re.match(r"^https://(open\.spotify\.com|developer\.spotify\.com|console\.cloud\.google\.com)/", url):
        plataforma.abrir_url(url)
    return {"ok": True}


def api_lista_txt(b):
    from . import lista
    ruta = lista.guardar_txt(b.get("nombre") or "lista", b.get("filas", []), b.get("links", True))
    return {"ruta": ruta, "mensaje": f"Guardé la lista depurada en {ruta}"}


def api_lista_evento(b):
    from . import lista
    requiere_cerrado()
    nombre = (b.get("nombre") or "").strip()
    if not nombre:
        raise Error("Poné un nombre para el evento.")
    with historial.Operacion(f"Crear evento «{nombre}»") as op:
        r = lista.crear_evento(nombre, b.get("ids", []))
        op.detalle = f"playlist con {r['agregados']} temas que ya tenías"
    config.guardar({"evento": {"id": r["id"], "nombre": nombre}})
    return {"evento": r, "mensaje": f"Playlist «{nombre}» creada en Rekordbox con {r['agregados']} temas."}


def api_abrir(b):
    """Muestra en la carpeta un archivo de las carpetas de trabajo de la app, o abre un .txt de ahí (la lista depurada)."""
    c = config.cargar()
    p = Path(str(b.get("ruta") or "")).resolve()
    if not p.is_file() or not any(Path(c[k]).resolve() in p.parents for k in ("incorporar", "coleccion", "backup")):
        raise Error("Ese archivo no está en las carpetas de la app.")
    if b.get("mostrar"):
        plataforma.mostrar(str(p))
    elif p.suffix.lower() == ".txt":
        plataforma.abrir(str(p))
    else:
        raise Error("Desde acá sólo se abren las listas en .txt.")
    return {"ok": True}


# ---------------------------------------------------------------- 2 · DESCARGAS
def api_descargas(_):
    from . import ingreso
    c = config.cargar()
    rutas = ingreso.listar()
    return {"carpeta": c["incorporar"],
            "archivos": [{"ruta": r, "archivo": Path(r).name,
                          "carpeta": str(Path(r).parent.relative_to(c["incorporar"])) if r.startswith(c["incorporar"]) else "",
                          "mb": round(os.path.getsize(r) / 1e6, 1)} for r in rutas],
            "campos": {**ingreso.DEFAULT_CAMPOS, **(c.get("ingreso_campos") or {})},
            "fuentes": {**ingreso.DEFAULT_FUENTES, **(c.get("ingreso_fuentes") or {})},
            "nombresCampos": ingreso.CAMPOS, "nombresFuentes": ingreso.FUENTES,
            "claves": {"lastfm": bool(c.get("lastfm")), "discogs": bool(c.get("discogs"))}}


def api_coleccion_metadata_opciones(_):
    from . import ingreso
    c = config.cargar()
    return {"campos": {**ingreso.DEFAULT_CAMPOS_COLECCION, **(c.get("coleccion_campos") or {})},
            "fuentes": {**ingreso.DEFAULT_FUENTES, **(c.get("ingreso_fuentes") or {})},
            "nombresCampos": ingreso.CAMPOS_COLECCION,
            "nombresFuentes": {k: v for k, v in ingreso.FUENTES.items() if k != "img"},
            "claves": {"lastfm": bool(c.get("lastfm")), "discogs": bool(c.get("discogs"))}}


def api_coleccion_metadata(b):
    """Busca metadata para temas de la colección (no escribe nada: los cambios aceptados quedan pendientes)."""
    from . import ingreso
    temas = rb.temas_para_metadata([str(i) for i in b.get("ids", [])])
    if not temas:
        raise Error("Elegí al menos un tema.")
    campos = {k: bool(v) for k, v in (b.get("campos") or {}).items() if k in ingreso.CAMPOS_COLECCION}
    if not any(v for k, v in campos.items() if k != "pisar"):
        raise Error("Marcá al menos un dato para actualizar.")
    fuentes = {k: bool(v) for k, v in (b.get("fuentes") or {}).items() if k in ingreso.FUENTES}
    config.guardar({"coleccion_campos": campos})
    t = trabajos.lanzar("metadata_coleccion", lambda tr: ingreso.analizar_coleccion(tr, temas, campos, fuentes),
                        total=len(temas))
    return {"trabajo": t.id}


def api_descargas_analizar(b):
    from . import ingreso
    rutas = [r for r in b.get("rutas", []) if Path(r).is_file()]
    if not rutas:
        raise Error("Elegí al menos un tema.")
    campos, fuentes = b.get("campos", {}), b.get("fuentes", {})
    config.guardar({"ingreso_campos": campos, "ingreso_fuentes": fuentes})
    t = trabajos.lanzar("analizar", lambda tr: ingreso.analizar(tr, rutas, campos, fuentes), total=len(rutas))
    estadisticas.uso("analizar descargas")
    return {"trabajo": t.id}


def api_trabajo(q):
    t = trabajos.obtener(q.get("id", [""])[0])
    if not t:
        raise Error("No encuentro ese trabajo.", 404)
    return t.dict(int(q.get("desde", ["0"])[0]))


def api_trabajo_cancelar(b):
    t = trabajos.obtener(b.get("id", ""))
    if t:
        t.cancelar = True
    return {"ok": True}


def api_descargas_aplicar(b):
    from . import ingreso
    items = b.get("items", [])
    if not items:
        raise Error("No hay temas para guardar.")
    with historial.Operacion(f"Preparar {len(items)} descargas", con_base=False) as op:
        r = ingreso.aplicar_metadata(items, op, lambda s: None)
        op.detalle = f"{r['preparados']} listos para incorporar, {r['descartados']} a _descartados"
    return {**r, "mensaje": f"Listo: {r['preparados']} temas preparados para incorporar"
                            + (f" y {r['descartados']} movidos a _descartados" if r["descartados"] else "") + "."}


# ---------------------------------------------------------------- 3 · INCORPORAR
def api_incorporar_estado(_):
    from . import ingreso
    c = config.cargar()
    ev = c.get("evento")
    chequeo = ingreso.chequeo_playlist(ev["id"]) if ev else None
    return {"preparados": ingreso.leer_preparados(), "coleccion": c["coleccion"], "evento": ev,
            "playlists": rb.listar_playlists(), "chequeo": chequeo}


def api_incorporar(b):
    from . import ingreso
    requiere_cerrado()
    rutas = b.get("rutas", [])
    if not rutas:
        raise Error("No hay temas para incorporar.")
    if not Path(config.cargar()["coleccion"]).is_dir():
        raise Error("La carpeta de la colección no existe. Elegila en Ajustes → Carpetas antes de incorporar temas.")
    preparados = {rb._clave_path(p["ruta"]) for p in ingreso.leer_preparados()}
    if any(rb._clave_path(r) not in preparados for r in rutas):
        raise Error("Alguno de esos temas no está en la lista de preparados. Volvé a abrir el paso 3 y probá de nuevo.")
    with historial.Operacion(f"Incorporar {len(rutas)} temas") as op:
        r = ingreso.incorporar(rutas, b.get("playlist"), op, lambda s: None, b.get("playlistFecha", True))
        op.detalle = f"movidos a la colección y agregados a Rekordbox" + (
            f", {r['enPlaylist']} en la playlist" if r["enPlaylist"] else "")
    estadisticas.uso("incorporar")
    return {**r, "mensaje": f"Listo: {r['incorporados']} temas en la colección y en Rekordbox"
                            + (f" ({r['enPlaylist']} en la playlist del evento)" if r["enPlaylist"] else "")
                            + (f", también en la playlist «{r['playlistFecha']}» (carpeta Importaciones)" if r.get("playlistFecha") else "")
                            + ". Abrí Rekordbox y analizalos (BPM, forma de onda)."}


def api_chequeo(q):
    from . import ingreso
    pid = q.get("playlist", [""])[0]
    return {"chequeo": ingreso.chequeo_playlist(pid) if pid else None}


def api_calidad(b):
    from . import ingreso
    rutas = b.get("rutas", [])
    t = trabajos.lanzar("calidad", lambda tr: ingreso.calidad_de(rutas, tr), total=len(rutas))
    return {"trabajo": t.id}


def api_mytags_listar(_):
    from . import categorias
    return {"categorias": rb.listar_mytags(), "fuentes": categorias.FUENTES}


def api_mytags_editar(b):
    requiere_cerrado()
    cambios = b.get("cambios", [])
    if not cambios:
        return {"mensaje": "Sin cambios."}
    with historial.Operacion("Editar tags manuales") as op:
        rb.editar_mytags(cambios)
        op.detalle = ", ".join(sorted({c["accion"] for c in cambios}))
    # los renombres se reflejan en teclas y cambios pendientes
    es4 = lambda c: str(c.get("cat") or "4") == "4"
    renombres = {c["viejo"]: c["nombre"] for c in cambios if c.get("accion") == "renombrar" and c.get("viejo") and es4(c)}
    borrados = {c.get("viejo") for c in cambios if c.get("accion") == "borrar" and es4(c)}
    if renombres or borrados:
        cfg = config.cargar()
        teclas = [renombres.get(t, t) if t not in borrados else "" for t in cfg["teclas"]]
        config.guardar({"teclas": teclas})
        p = config.pendientes()
        p["momento"] = {k: renombres.get(v, v) for k, v in p["momento"].items() if v not in borrados}
        config.guardar_pendientes(p)
    return {"mensaje": "Tags guardados en Rekordbox.", "categorias": rb.listar_mytags()}


def api_nombres(_):
    return {"cambios": rb.propuesta_nombres()}


def api_nombres_aplicar(b):
    requiere_cerrado()
    cambios = b.get("cambios", [])
    if not cambios:
        return {"mensaje": "No marcaste ningún archivo."}
    with historial.Operacion(f"Ordenar nombres de {len(cambios)} archivos") as op:
        r = rb.renombrar(cambios, op, lambda s: None)
        op.detalle = f"{r['renombrados']} archivos renombrados (archivo + Rekordbox)"
    return {**r, "mensaje": f"Listo: {r['renombrados']} archivos con nombre nuevo, también en Rekordbox."}


def api_backups(_):
    from . import backups
    return backups.listar()


def api_backups_borrar(b):
    from . import backups
    r = backups.borrar(b.get("rutas", []))
    gb = r["liberado"] / 1e9
    return {**r, "mensaje": f"Listo: liberé {gb:.2f} GB." if gb >= 0.1 else f"Listo: liberé {r['liberado'] / 1e6:.0f} MB."}


# ---------------------------------------------------------------- BACKUP Y RESTAURACIÓN
def api_respaldo(_):
    from . import respaldo
    return respaldo.estado()


def api_respaldo_share(_):
    from . import respaldo
    return {"bytes": respaldo.tam_share()}


def _tarea_respaldo(tipo, fn):
    from . import respaldo

    def correr(t):
        try:
            return fn(t)
        except respaldo.ErrorRespaldo as e:
            raise RuntimeError(str(e)) from None
    return {"trabajo": trabajos.lanzar(tipo, correr).id}


def api_respaldo_hacer(b):
    from . import respaldo
    base, col = bool(b.get("base", True)), bool(b.get("coleccion", True))
    if not (base or col):
        raise Error("Marcá qué querés respaldar.")
    if base:
        requiere_cerrado()
    cambios = {k: b[k] for k in ("respaldo_share", "respaldo_otros") if k in b}
    if cambios:
        config.guardar(cambios)
    try:
        respaldo._validar_destino(respaldo.destino())
    except respaldo.ErrorRespaldo as e:
        raise Error(str(e))
    estadisticas.uso("backup")
    return _tarea_respaldo("respaldo", lambda t: respaldo.backup_completo(
        t, base=base, coleccion=col, con_share=bool(b.get("respaldo_share", True)), con_otros=bool(b.get("respaldo_otros", True))))


def api_respaldo_restaurar_base(b):
    from . import respaldo
    requiere_cerrado()
    try:
        respaldo._zip_valido(b.get("ruta", ""))
    except respaldo.ErrorRespaldo as e:
        raise Error(str(e))
    return _tarea_respaldo("restaurar_base", lambda t: respaldo.restaurar_base(t, b["ruta"], bool(b.get("share", True))))


def api_respaldo_restaurar_coleccion(b):
    from . import respaldo
    modo = "todos" if b.get("modo") == "todos" else "faltantes"
    return _tarea_respaldo("restaurar_coleccion", lambda t: respaldo.restaurar_coleccion(t, modo, b.get("carpeta")))


def api_respaldo_borrar(b):
    from . import respaldo
    try:
        respaldo.borrar_base(b.get("ruta", ""))
    except respaldo.ErrorRespaldo as e:
        raise Error(str(e))
    return {"mensaje": "Backup borrado."}


def api_respaldo_destino(b):
    from . import respaldo
    ruta = (b.get("ruta") or "").strip()
    if ruta:
        try:
            respaldo._validar_destino(Path(ruta))
        except respaldo.ErrorRespaldo as e:
            raise Error(str(e))
    config.guardar({"respaldo_destino": ruta})
    return respaldo.estado()


def api_respaldo_abrir(_):
    from . import respaldo
    d = respaldo.destino()
    d.mkdir(parents=True, exist_ok=True)
    plataforma.abrir(d)
    return {"ok": True}


# ---------------------------------------------------------------- CARTELERA, MIS ANUNCIOS Y VERSIÓN
def _nube(fn):
    def envuelta(arg):
        from . import nube
        try:
            return fn(nube, arg)
        except nube.ErrorNube as e:
            raise Error(str(e))
    return envuelta


@_nube
def api_novedades(nube, q):
    forzar = bool(q.get("forzar"))
    d = nube.novedades(VERSION, forzar)
    act = kramer_arranque.estado()
    if d.get("hayNueva") and act["activo"]:
        # la app armada baja sola el código nuevo: si ya está bajado, alcanza con cerrarla y abrirla
        d["auto"] = "lista" if act["lista"] == d["ultima"] else "buscando" if act["buscando"] else ""
    if d.get("activo"):
        c = nube.cartelera(forzar)
        vistos = set(config.cargar().get("cartelera_vistos") or [])
        d["nuevos"] = sum(1 for a in c["anuncios"] if a["id"] not in vistos)
        d["mostrarAlInicio"] = config.cargar().get("cartelera_inicio", True)
        d["ubicacion"] = nube.ubicacion()
    return d


@_nube
def api_cartelera(nube, q):
    return nube.cartelera(bool(q.get("forzar")))


@_nube
def api_cartelera_vistos(nube, b):
    vistos = list(dict.fromkeys((config.cargar().get("cartelera_vistos") or []) + [str(x) for x in b.get("ids", [])]))[-500:]
    config.guardar({"cartelera_vistos": vistos})
    return {"ok": True}


@_nube
def api_ubicacion(nube, b):
    pais = str(b.get("pais") or "").upper()[:2]
    if not re.fullmatch(r"[A-Z]{2}", pais):
        raise Error("Elegí un país.")
    config.guardar({"ubicacion": {"pais": pais, "region": str(b.get("region") or "").strip()[:60]}})
    return nube.cartelera(True)


@_nube
def api_abrir_anuncio(nube, b):
    url = str(b.get("url") or "")
    if nube.link_publicado(url):
        plataforma.abrir_url(url)
    return {"ok": True}


@_nube
def api_abrir_descarga(nube, _):
    d = nube.novedades(VERSION)
    if str(d.get("link") or "").startswith("https://"):
        plataforma.abrir_url(d["link"])
    return {"ok": True}


@_nube
def api_nube_quien(nube, _):
    return nube.quien()


@_nube
def api_nube_codigo(nube, b):
    return {"email": nube.pedir_codigo(b.get("email")), "mensaje": "Te mandamos un código por email."}


@_nube
def api_nube_verificar(nube, b):
    nube.verificar_codigo(b.get("email", ""), b.get("codigo", ""))
    return nube.quien()


@_nube
def api_nube_salir(nube, _):
    nube.salir()
    return {"ok": True}


@_nube
def api_nube_nombre(nube, b):
    return {"nombre": nube.guardar_nombre(b.get("nombre")), "mensaje": "Nombre guardado."}


@_nube
def api_nube_mis(nube, _):
    return {"anuncios": nube.mis_anuncios()}


@_nube
def api_nube_guardar(nube, b):
    a = nube.guardar_anuncio(b)
    return {"anuncio": a, "mensaje": "Anuncio enviado: queda en revisión hasta que se apruebe."}


@_nube
def api_nube_borrar(nube, b):
    nube.borrar_anuncio(b.get("id"))
    return {"mensaje": "Anuncio borrado."}


@_nube
def api_nube_pendientes(nube, _):
    return {"anuncios": nube.pendientes()}


@_nube
def api_nube_moderar(nube, b):
    nube.moderar(b.get("id"), b.get("estado"), b.get("motivo", ""), b.get("destacado"))
    return {"mensaje": "Publicado." if b.get("estado") == "publicado" else "Rechazado."}


CARPETAS_DE_AJUSTES = ("coleccion", "incorporar", "backup", "rekordbox", "respaldo_destino")


def _validar_ajustes(b):
    """Cada ajuste tiene que ser del mismo tipo que su valor de fábrica; las carpetas, rutas completas."""
    for k, v in b.items():
        if k not in config.DEFAULT:
            continue
        fabrica = config.DEFAULT[k]
        if k in CARPETAS_DE_AJUSTES:
            bien = isinstance(v, str) and (Path(v).is_absolute() or (v == "" and k == "respaldo_destino"))
        elif isinstance(fabrica, bool):
            bien = isinstance(v, bool)
        elif isinstance(fabrica, int):
            bien = isinstance(v, (int, float)) and not isinstance(v, bool)
        elif isinstance(fabrica, (str, list)):
            bien = isinstance(v, type(fabrica))
        else:
            bien = v is None or isinstance(v, (dict, list))
        if not bien:
            raise Error(f"El ajuste «{k}» no tiene un valor válido.")


def api_config(b):
    b = {k: v for k, v in b.items() if k not in ("nube_sesion", "spotify_refresh", "estadisticas_estado")}
    if "tema" in b and b["tema"] not in ("", "claro", "oscuro"):
        raise Error("El modo tiene que ser claro, oscuro o el del sistema.")
    _validar_ajustes(b)
    c = config.guardar(b)
    if b.get("acepto_riesgo") or b.get("estadisticas_avisado"):
        estadisticas.al_abrir(VERSION, de_nuevo=True)   # recién vio la explicación: cuenta como apertura
    return {"config": {k: v for k, v in c.items() if k not in OCULTAS}}


def api_historial(_):
    return {"historial": historial.listar()}


def api_deshacer(b):
    requiere_cerrado()
    op = historial.deshacer(b["id"])
    return {"mensaje": f"Deshecho: {op['que']}"}


def api_mytags(b):
    """Recalcula las categorías automáticas (simular = sólo mostrar qué cambiaría)."""
    simular = bool(b.get("simular", True))
    if simular:
        return {"resumen": rb.sincronizar_categorias(simular=True)}
    requiere_cerrado()
    with historial.Operacion("Actualizar My Tags automáticos") as op:
        r = rb.sincronizar_categorias(simular=False)
        op.detalle = ", ".join(f"{c['nombre']}: {c['cambios']} temas" for c in r if c["fuente"] != "manual")
    estadisticas.uso("My Tags")
    return {"resumen": r, "mensaje": "My Tags actualizados en Rekordbox."}


def api_mytags_config(b):
    from . import categorias
    cats = b.get("categorias", [])
    validas = []
    for d in categorias.DEFAULT:
        c = next((x for x in cats if str(x.get("id")) == d["id"]), d)
        fuente = c.get("fuente") if c.get("fuente") in categorias.FUENTES else d["fuente"]
        if d["id"] == "4":
            fuente = "manual"              # la 4 es la de etiquetado rápido (teclas 1-4)
        validas.append({"id": d["id"], "nombre": (c.get("nombre") or d["nombre"]).strip()[:40], "fuente": fuente})
    config.guardar({"categorias": validas})
    return {"categorias": rb.listar_mytags(), "mensaje": "Guardado. Tocá «Actualizar base de Rekordbox» para aplicarlo."}


def api_elegir_carpeta(b):
    titulo = b.get("titulo", "Elegí una carpeta")
    if ELEGIR_CARPETA:
        r = ELEGIR_CARPETA(titulo) or ""
        return {"ruta": r if len(r) <= 3 else r.rstrip("/\\")}
    return {"ruta": plataforma.elegir_carpeta(titulo)}


def api_mostrar(b):
    ruta = RUTAS.get(str(b.get("id")), "")
    if ruta:
        plataforma.mostrar(ruta)
    return {"ok": True}


GET = {"/api/estado": api_estado, "/api/coleccion": api_coleccion, "/api/tema": api_tema,
       "/api/traer": api_traer_buscar, "/api/historial": api_historial,
       "/api/duplicados": api_duplicados, "/api/coleccion/metadata/opciones": api_coleccion_metadata_opciones, "/api/descargas": api_descargas, "/api/trabajo": api_trabajo,
       "/api/incorporar": api_incorporar_estado, "/api/chequeo": api_chequeo, "/api/mytags": api_mytags_listar,
       "/api/nombres": api_nombres, "/api/spotify": api_spotify_estado, "/api/backups": api_backups,
       "/api/novedades": api_novedades, "/api/carpeta_sugerida": api_carpeta_sugerida, "/api/cartelera": api_cartelera, "/api/nube/quien": api_nube_quien,
       "/api/nube/mis": api_nube_mis, "/api/nube/pendientes": api_nube_pendientes,
       "/api/respaldo": api_respaldo, "/api/respaldo/share": api_respaldo_share,
       "/api/actualizacion": lambda q: kramer_arranque.estado(),
       "/api/ping": lambda q: {"ok": True}}
POST = {"/api/pendiente": api_pendiente, "/api/pendiente_lote": api_pendiente_lote, "/api/descartar": api_descartar,
        "/api/sincronizar": api_sincronizar, "/api/traer": api_traer_aplicar,
        "/api/config": api_config, "/api/duplicados": api_duplicados_borrar,
        "/api/coleccion/metadata": api_coleccion_metadata,
        "/api/eliminar/revisar": api_eliminar_revisar, "/api/eliminar": api_eliminar, "/api/eliminados/abrir": api_eliminados_abrir,
        "/api/lista/comparar": api_lista_comparar, "/api/lista/link": api_lista_link,
        "/api/spotify/conectar": api_spotify_conectar, "/api/spotify/desconectar": api_spotify_desconectar,
        "/api/spotify/playlist": api_spotify_playlist, "/api/abrir_url": api_abrir_url,
        "/api/incorporar/quitar": api_incorporar_quitar, "/api/fuente": api_fuente, "/api/nombres": api_nombres_aplicar, "/api/lista/txt": api_lista_txt,
        "/api/lista/evento": api_lista_evento, "/api/abrir": api_abrir,
        "/api/descargas/analizar": api_descargas_analizar, "/api/trabajo/cancelar": api_trabajo_cancelar,
        "/api/descargas/aplicar": api_descargas_aplicar, "/api/incorporar": api_incorporar,
        "/api/calidad": api_calidad, "/api/abrir_privacidad": api_abrir_privacidad,
        "/api/backups/borrar": api_backups_borrar, "/api/mytags/editar": api_mytags_editar, "/api/mytags/config": api_mytags_config, "/api/deshacer": api_deshacer, "/api/mytags": api_mytags,
        "/api/cartelera/vistos": api_cartelera_vistos, "/api/ubicacion": api_ubicacion, "/api/abrir_anuncio": api_abrir_anuncio, "/api/abrir_descarga": api_abrir_descarga,
        "/api/nube/codigo": api_nube_codigo, "/api/nube/verificar": api_nube_verificar, "/api/nube/salir": api_nube_salir,
        "/api/nube/nombre": api_nube_nombre, "/api/nube/guardar": api_nube_guardar, "/api/nube/borrar": api_nube_borrar,
        "/api/nube/moderar": api_nube_moderar,
        "/api/informe": api_informe, "/api/respaldo/hacer": api_respaldo_hacer, "/api/respaldo/restaurar_base": api_respaldo_restaurar_base,
        "/api/respaldo/restaurar_coleccion": api_respaldo_restaurar_coleccion, "/api/respaldo/borrar": api_respaldo_borrar,
        "/api/respaldo/destino": api_respaldo_destino, "/api/respaldo/abrir": api_respaldo_abrir,
        "/api/elegir_carpeta": api_elegir_carpeta, "/api/mostrar": api_mostrar}


# =============================================================================
# HTTP
# =============================================================================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, datos, code=200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _api(self, fn, arg):
        try:
            self._json(fn(arg))
        except Error as e:
            self._json({"error": str(e)}, e.code)
        except rb.SinRekordbox as e:
            self._json({"error": str(e), "sinRekordbox": True}, 404)
        except PermissionError as e:
            traceback.print_exc()
            if plataforma.ES_WIN:
                msg = ("Windows no dejó a la app modificar un archivo "
                       f"({getattr(e, 'filename', '') or e}).\n\nRevisá que no esté abierto en otro programa "
                       "(Rekordbox, un reproductor) y que la carpeta no sea de sólo lectura.")
            else:
                msg = ("macOS no dejó a la app modificar un archivo "
                       f"({getattr(e, 'filename', '') or e}).\n\nSolución: Ajustes del Sistema → Privacidad y "
                       "seguridad → Acceso total al disco → activá «RKB Collection Manager» y volvé a abrir la app.")
            self._json({"error": msg}, 403)
        except ValueError as e:
            traceback.print_exc()
            self._json({"error": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _de_la_app(self):
        """Sólo se atiende a la página de la app. Cualquier otra página abierta en un navegador de esta computadora
        puede mandar pedidos a 127.0.0.1, pero no puede cambiar su «Origin» ni hacerse pasar por este «Host»."""
        puerto = self.server.server_address[1]
        propios = {f"127.0.0.1:{puerto}", f"localhost:{puerto}"}
        origen = self.headers.get("Origin")
        return self.headers.get("Host") in propios and (origen is None or origen in {f"http://{h}" for h in propios})

    def do_GET(self):
        if not self._de_la_app():
            self.send_error(403)
            return
        u = urlparse(self.path)
        if u.path in GET:
            return self._api(GET[u.path], parse_qs(u.query))
        if u.path == "/audio":
            q = parse_qs(u.query)
            if q.get("ruta"):
                return self._audio(None, ruta_libre(q["ruta"][0]))
            return self._audio(q.get("id", [""])[0])
        if u.path == "/caratula":
            return self._caratula(parse_qs(u.query).get("id", [""])[0])
        nombre = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        f = (WEB / nombre).resolve()
        if WEB.resolve() not in f.parents or not f.is_file():
            self.send_error(404)
            return
        datos = f.read_bytes()
        if nombre == "index.html":
            datos = datos.replace(b'<html lang="es">', f'<html lang="es" data-tema-guardado="{tema_inicial()}">'.encode(), 1)
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(f.name)[0] or "text/plain") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def do_POST(self):
        if not self._de_la_app() or not self.headers.get("Content-Type", "").startswith("application/json"):
            self.send_error(403)
            return
        u = urlparse(self.path)
        largo = int(self.headers.get("Content-Length") or 0)
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except Exception:
            cuerpo = {}
        if u.path == "/api/salir":
            self._json({"ok": True})
            if AL_SALIR:
                threading.Thread(target=AL_SALIR, daemon=True).start()
            else:
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if u.path in POST:
            return self._api(POST[u.path], cuerpo)
        self.send_error(404)

    def _caratula(self, tid):
        ruta = RUTAS.get(tid)
        datos, mime = archivos.caratula(ruta) if ruta and Path(ruta).is_file() else (None, None)
        if not datos:
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def _audio(self, tid, ruta=None):
        ruta = ruta or RUTAS.get(tid)
        if not ruta or not Path(ruta).is_file():
            self.send_error(404)
            return
        tam = os.path.getsize(ruta)
        ini, fin = 0, tam - 1
        rango = self.headers.get("Range")
        if rango and rango.startswith("bytes="):
            a, _, b = rango[6:].partition("-")
            ini = int(a) if a else 0
            fin = int(b) if b else tam - 1
            fin = min(fin, tam - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {ini}-{fin}/{tam}")
        else:
            self.send_response(200)
        tipo = {".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aif": "audio/aiff", ".aiff": "audio/aiff"}.get(
            Path(ruta).suffix.lower()) or mimetypes.guess_type(ruta)[0] or "audio/mpeg"
        self.send_header("Content-Type", tipo)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fin - ini + 1))
        self.end_headers()
        try:
            with open(ruta, "rb") as f:
                f.seek(ini)
                resta = fin - ini + 1
                while resta > 0:
                    trozo = f.read(min(256 * 1024, resta))
                    if not trozo:
                        break
                    self.wfile.write(trozo)
                    resta -= len(trozo)
        except (BrokenPipeError, ConnectionResetError):
            pass


def crear(puerto=None):
    return ThreadingHTTPServer(("127.0.0.1", PUERTO if puerto is None else puerto), Handler)


def main():
    srv = crear()
    print(f"Kramer DJ {VERSION} en http://127.0.0.1:{PUERTO}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
