"""Acceso a la base de Rekordbox (master.db): lectura de la colección y escritura de cambios."""
import datetime
import os
import threading
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from pyrekordbox import MasterDatabase
from pyrekordbox.masterdb import models as m
from pyrekordbox.utils import get_rekordbox_pid

from . import archivos, categorias, config, mytags, plataforma

CAT_MOMENTO = "4"                       # lugar de la categoría Momento (la 4ª), no su ID en la base
lock = threading.RLock()


def rekordbox_abierto():
    try:
        return bool(get_rekordbox_pid())
    except Exception:
        return False


class SinRekordbox(Exception):
    pass


def abrir():
    c = config.cargar()
    ruta = Path(c["rekordbox"]) / "master.db"
    if not ruta.is_file():
        raise SinRekordbox("No encuentro la base de Rekordbox en esta computadora. ¿Está instalado Rekordbox 6 o 7 "
                           "y lo abriste al menos una vez? Si la base está en otro lugar, elegila en Ajustes → Base de Rekordbox.")
    # Siempre la base de Ajustes: es la misma que se respalda antes de cada cambio y la que devuelve Deshacer.
    db = MasterDatabase(path=str(ruta), unlock=False) if os.environ.get("KRAMER_RB_TEST") else MasterDatabase(path=str(ruta))
    cerrar_sesion = db.close

    def cerrar():
        cerrar_sesion()
        db.engine.dispose()         # suelta master.db: Windows no deja reemplazar un archivo abierto

    db.close = cerrar
    return db


def carpeta_sugerida():
    """La carpeta donde está la mayoría de los temas de Rekordbox (para el primer uso)."""
    from collections import Counter
    try:
        with lock:
            db = abrir()
            try:
                rutas = [c.FolderPath for c in db.get_content() if c.FolderPath]
            finally:
                db.close()
    except Exception:
        return ""
    rutas = [r.replace("\\", "/") for r in rutas if "/samples/" not in r.lower().replace("\\", "/")]
    if not rutas:
        return ""
    cuenta = Counter()
    for r in rutas:
        partes = r.split("/")[:-1]
        for i in range(2, len(partes) + 1):
            cuenta["/".join(partes[:i])] += 1
    minimo = len(rutas) * 0.6
    candidatas = [(len(k), k) for k, n in cuenta.items() if n >= minimo]
    if not candidatas:
        return ""
    elegida = max(candidatas)[1]
    if os.name == "nt":
        elegida = elegida.replace("/", "\\")
    return elegida if Path(elegida).is_dir() else ""


def _decada(anio):
    t = categorias.tag_decada(anio)
    return t[0] if t else ""


def _datos(c, pais=None, idioma=None):
    p0, i0 = archivos.pais_idioma(c.Commnt or "")
    return {"pais": p0 if pais is None else pais, "idioma": i0 if idioma is None else idioma,
            "genero": c.GenreName or "", "anio": c.ReleaseYear or "", "titulo": c.Title or "",
            "bpm": (c.BPM or 0) / 100}


def ids_categorias(db):
    """{lugar: ID en la base} de las 4 categorías de My Tags ("1".."4" = 1ª..4ª columna de Rekordbox).
    En muchas bases las categorías tienen justo los ID 1 a 4, pero no en todas (pasa en Windows):
    ahí se toman en el orden en que las muestra Rekordbox."""
    lugares = [c["id"] for c in categorias.DEFAULT]
    raiz = [str(t.ID) for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == "root").order_by(m.DjmdMyTag.Seq)]
    if not raiz or all(x in raiz for x in lugares):
        return {x: x for x in lugares}
    return {x: (raiz[i] if i < len(raiz) else x) for i, x in enumerate(lugares)}


def tags_automaticos(db, cid, datos, ahora):
    """Pone los tags de las categorías automáticas de un tema (según Ajustes de My Tags).
    Una categoría se toca recién cuando en Rekordbox ya lleva el nombre de la app, o sea, después de
    «Actualizar base de Rekordbox» en el paso 4: antes de eso puede tener tags propios del usuario."""
    ids = ids_categorias(db)
    en_base = {str(t.ID): t.Name for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == "root")}
    for cat in categorias.automaticas():
        if en_base.get(ids[cat["id"]]) == cat["nombre"]:
            _poner_tags(db, str(cid), ids[cat["id"]], categorias.calcular(cat["fuente"], datos), ahora)


# =============================================================================
# LECTURA
# =============================================================================
def listar_playlists():
    with lock:
        db = abrir()
        try:
            return [{"id": str(p.ID), "nombre": p.Name} for p in db.get_playlist()
                    if p.Attribute == 0 and not p.SmartList]
        finally:
            db.close()


# ---------------------------------------------------------------- tonalidad (Camelot)
_CAMELOT = {"C": "8B", "G": "9B", "D": "10B", "A": "11B", "E": "12B", "B": "1B", "F#": "2B", "Gb": "2B",
            "Db": "3B", "C#": "3B", "Ab": "4B", "G#": "4B", "Eb": "5B", "D#": "5B", "Bb": "6B", "A#": "6B", "F": "7B",
            "Am": "8A", "Em": "9A", "Bm": "10A", "F#m": "11A", "Gbm": "11A", "C#m": "12A", "Dbm": "12A",
            "G#m": "1A", "Abm": "1A", "D#m": "2A", "Ebm": "2A", "Bbm": "3A", "A#m": "3A", "Fm": "4A",
            "Cm": "5A", "Gm": "6A", "Dm": "7A"}


def camelot(nombre):
    n = (nombre or "").strip()
    if not n:
        return ""
    if n[:-1].isdigit() and n[-1].upper() in "AB":
        return n[:-1] + n[-1].upper()
    n = n.replace("min", "m").replace("maj", "").replace("♯", "#").replace("♭", "b")
    return _CAMELOT.get(n, "")


def leer_coleccion():
    with lock:
        db = abrir()
        try:
            ids = ids_categorias(db)
            lugar_de = {v: k for k, v in ids.items()}
            cats = {}
            for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.Attribute == 0):
                if t.ParentID in lugar_de:
                    cats[t.ID] = (lugar_de[t.ParentID], t.Name)
            tags_tema = defaultdict(lambda: defaultdict(list))
            for a in db.query(m.DjmdSongMyTag):
                if a.MyTagID in cats:
                    cat, nombre = cats[a.MyTagID]
                    tags_tema[str(a.ContentID)][cat].append(nombre)
            playlists = {}
            for p in db.get_playlist():
                if p.Attribute == 0 and not p.SmartList:
                    playlists[str(p.ID)] = p.Name
            en_pl = defaultdict(list)
            for s in db.get_playlist_songs():
                if str(s.PlaylistID) in playlists:
                    en_pl[str(s.ContentID)].append(str(s.PlaylistID))
            primer_cue, n_cues = {}, defaultdict(int)
            for q in db.get_cue():
                k = str(q.ContentID)
                n_cues[k] += 1
                if q.InMsec is not None and q.InMsec >= 0:
                    primer_cue[k] = min(primer_cue.get(k, q.InMsec), q.InMsec)
            claves = {k.ID: camelot(k.ScaleName) for k in db.query(m.DjmdKey)}
            # historial de reproducción (sesiones HISTORY de Rekordbox)
            fecha_hist = {h.ID: (h.DateCreated or "")[:10] for h in db.query(m.DjmdHistory) if h.Attribute == 0}
            tocado, ultima = defaultdict(int), {}
            for sh in db.query(m.DjmdSongHistory):
                k = str(sh.ContentID)
                tocado[k] += 1
                f = fecha_hist.get(sh.HistoryID, "")
                if f > ultima.get(k, ""):
                    ultima[k] = f
            temas = []
            for c in db.get_content():
                cid = str(c.ID)
                tt = tags_tema.get(cid, {})
                pais, idioma = archivos.pais_idioma(c.Commnt or "")
                cat_origen = next((k["id"] for k in categorias.cargar() if k["fuente"] == "origen_idioma"), None)
                origen = tt.get(cat_origen, []) if cat_origen else []
                temas.append({
                    "id": cid,
                    "titulo": c.Title or "",
                    "artista": c.ArtistName or "",
                    "album": c.AlbumName or "",
                    "genero": c.GenreName or "",
                    "anio": str(c.ReleaseYear) if c.ReleaseYear else "",
                    "bpm": round((c.BPM or 0) / 100, 1),
                    "duracion": c.Length or 0,
                    "ruta": c.FolderPath or "",
                    "pais": pais, "idioma": idioma,
                    "origen": origen,
                    "cats": {k: v for k, v in tt.items()},
                    "decada": _decada(c.ReleaseYear),
                    "momento": (tt.get(CAT_MOMENTO) or [""])[0],
                    "playlists": en_pl.get(cid, []),
                    "cue": primer_cue.get(cid),
                    "cues": n_cues.get(cid, 0),
                    "analizado": bool(c.Analysed),
                    "tono": claves.get(c.KeyID, ""),
                    "tocado": max(tocado.get(cid, 0), c.DJPlayCount or 0),
                    "ultimaVez": ultima.get(cid, ""),
                    "existe": bool(c.FolderPath) and Path(c.FolderPath).is_file(),
                })
            momentos = [t.Name for t in db.query(m.DjmdMyTag)
                        .filter(m.DjmdMyTag.ParentID == ids[CAT_MOMENTO]).order_by(m.DjmdMyTag.Seq)]
            cats_cfg = categorias.cargar()
            for k in cats_cfg:
                k["tags"] = [t.Name for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == ids[k["id"]])
                             .order_by(m.DjmdMyTag.Seq)]
            return {"temas": temas, "playlists": playlists, "momentos": momentos or config.MOMENTOS,
                    "categorias": cats_cfg}
        finally:
            db.close()


# =============================================================================
# ESCRITURA
# =============================================================================
def _por_nombre(db, modelo, getter, alta, nombre):
    if not nombre:
        return None
    obj = getter(Name=nombre).first()
    return obj if obj is not None else alta(nombre)


def _tag_en_categoria(db, cat, nombre, ahora):
    t = (db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == cat, m.DjmdMyTag.Name == nombre)
         .order_by(m.DjmdMyTag.Seq).first())
    if t is not None:
        return t
    seq = db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == cat).count() + 1
    t = m.DjmdMyTag.create(
        ID=str(db.generate_unused_id(m.DjmdMyTag, is_28_bit=False)), Seq=seq, Name="New Tag",
        Attribute=0, ParentID=cat, UUID=str(uuid4()), created_at=ahora, updated_at=ahora)
    db.add(t)
    t.Name = nombre
    return t


def _poner_tags(db, content_id, cat, nombres, ahora):
    """Deja exactamente 'nombres' como tags del tema en la categoría 'cat'."""
    ids_cat = {t.ID for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == cat)}
    deseados = {_tag_en_categoria(db, cat, n, ahora).ID for n in nombres if n}
    actuales = {}
    for a in db.query(m.DjmdSongMyTag).filter(m.DjmdSongMyTag.ContentID == content_id):
        if a.MyTagID in ids_cat or a.MyTagID in deseados:
            actuales[a.MyTagID] = a
    for tid, fila in actuales.items():
        if tid not in deseados:
            db.delete(fila)
    for tid in deseados - set(actuales):
        db.add(m.DjmdSongMyTag.create(
            ID=str(uuid4()), MyTagID=tid, ContentID=content_id, TrackNo=None,
            UUID=str(uuid4()), created_at=ahora, updated_at=ahora))


def aplicar(pend, respaldar_archivo, log):
    """Aplica Momento y metadata pendientes. respaldar_archivo(ruta) copia el original antes
    de tocarlo. Devuelve un resumen."""
    resumen = {"momento": 0, "metadata": 0, "errores": []}
    ahora = datetime.datetime.now()
    with lock:
        db = abrir()
        try:
            for cid, cambios in pend.get("meta", {}).items():
                c = db.get_content(ID=cid)
                if c is None:
                    resumen["errores"].append(f"Tema {cid}: no está en Rekordbox")
                    continue
                ruta = c.FolderPath or ""
                actual = archivos.leer(ruta) if Path(ruta).is_file() else {}
                pais0, idioma0 = archivos.pais_idioma(actual.get("comentario") or c.Commnt or "")
                pais = cambios.get("pais", pais0)
                idioma = cambios.get("idioma", idioma0)
                texto = cambios["comentario"] if "comentario" in cambios else (actual.get("comentario") or c.Commnt or "")
                comentario = archivos.armar_comentario(texto, pais, idioma)
                con_comentario = any(k in cambios for k in ("comentario", "pais", "idioma"))
                al_archivo = {k: v for k, v in cambios.items() if k in archivos.CAMPOS}
                if con_comentario:
                    al_archivo["comentario"] = comentario
                if Path(ruta).is_file() and al_archivo:
                    try:
                        respaldar_archivo(ruta)
                        archivos.escribir(ruta, al_archivo)
                    except Exception as e:
                        resumen["errores"].append(f"{Path(ruta).name}: no se pudo escribir ({e})")
                # ----- base -----
                if "titulo" in cambios:
                    c.Title = cambios["titulo"]
                if "artista" in cambios:
                    a = _por_nombre(db, m.DjmdArtist, db.get_artist, db.add_artist, cambios["artista"])
                    c.ArtistID = a.ID if a else None
                if "album" in cambios:
                    a = _por_nombre(db, m.DjmdAlbum, db.get_album, db.add_album, cambios["album"])
                    c.AlbumID = a.ID if a else None
                if "genero" in cambios:
                    g = _por_nombre(db, m.DjmdGenre, db.get_genre, db.add_genre, cambios["genero"])
                    c.GenreID = g.ID if g else None
                if "anio" in cambios:
                    try:
                        c.ReleaseYear = int(str(cambios["anio"])[:4]) if cambios["anio"] else None
                    except ValueError:
                        resumen["errores"].append(f"{c.Title}: año inválido '{cambios['anio']}'")
                if con_comentario:
                    c.Commnt = comentario
                c.updated_at = ahora
                # My Tags automáticos del tema
                db.flush()
                tags_automaticos(db, cid, _datos(c, pais, idioma), ahora)
                resumen["metadata"] += 1
                log(f"Metadata: {c.ArtistName} - {c.Title}")
            ids = ids_categorias(db)
            for cid, mom in pend.get("momento", {}).items():
                if db.get_content(ID=cid) is None:
                    continue
                _poner_tags(db, cid, ids[CAT_MOMENTO], [mom] if mom else [], ahora)
                resumen["momento"] += 1
            manuales = {k["id"] for k in categorias.cargar() if k["fuente"] == "manual"}
            for cid, por_cat in pend.get("tags", {}).items():
                if db.get_content(ID=cid) is None:
                    continue
                for cat, nombres in por_cat.items():
                    if cat in manuales:
                        _poner_tags(db, cid, ids[cat], nombres, ahora)
                resumen["momento"] += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    return resumen


# =============================================================================
# REKORDBOX -> ARCHIVOS
# =============================================================================
def diferencias_con_archivos():
    """Temas cuyos datos en Rekordbox difieren del archivo. Lista de {id, ruta, cambios}."""
    out = []
    with lock:
        db = abrir()
        try:
            for c in db.get_content():
                ruta = c.FolderPath or ""
                if not Path(ruta).is_file():
                    continue
                f = archivos.leer(ruta)
                base = {"titulo": c.Title or "", "artista": c.ArtistName or "",
                        "album": c.AlbumName or "", "genero": c.GenreName or "",
                        "anio": str(c.ReleaseYear) if c.ReleaseYear else "",
                        "comentario": c.Commnt or ""}
                cambios = {k: v for k, v in base.items() if v and v.strip() != (f.get(k) or "").strip()}
                if cambios:
                    out.append({"id": str(c.ID), "ruta": ruta, "tema": f"{base['artista']} - {base['titulo']}",
                                "cambios": cambios, "antes": {k: f.get(k, "") for k in cambios}})
        finally:
            db.close()
    return out


# =============================================================================
# DUPLICADOS
# =============================================================================
import re
import unicodedata

_RUIDO = re.compile(r"[\(\[][^\)\]]*(official|oficial|video|audio|lyric|letra|visualizer|hq|hd|4k|320|"
                    r"remaster|remasterizad|explicit|clean|radio edit|bpm|\d+ ?- ?\d+)[^\)\]]*[\)\]]", re.I)
_FEAT = re.compile(r"\s*[\(\[]?\b(feat\.?|ft\.?|featuring|con)\b.*?([\)\]]|$)", re.I)


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _clave_titulo(titulo):
    t = _RUIDO.sub(" ", titulo or "")
    t = _FEAT.sub(" ", t)
    return _norm(t)


def _clave_artista(artista):
    a = _FEAT.sub(" ", artista or "")
    partes = re.split(r"\s*(?:,|/|&|\by\b|\band\b|\bx\b|;)\s*", _norm_keep(a))
    partes = sorted({re.sub(r"^the ", "", _norm(p)) for p in partes
                     if _norm(p) and _norm(p) not in ("various artists", "varios")})
    return " + ".join(partes)


def _norm_keep(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def mismo_path(a, b):
    """macOS no distingue acentos compuestos/descompuestos ni mayúsculas: compara así."""
    return _clave_path(a) == _clave_path(b)


def _clave_path(x):
    """Rekordbox guarda las rutas con «/» también en Windows, donde el sistema las arma con «\\»."""
    return unicodedata.normalize("NFC", str(x or "")).casefold().replace("\\", "/")


def _cues_por_tema(db):
    hot, mem = defaultdict(int), defaultdict(int)
    for q in db.get_cue():
        (hot if (q.Kind or 0) > 0 else mem)[str(q.ContentID)] += 1
    return hot, mem


def _sugerencia(copias):
    """Elige qué copia conservar: 1) la que tiene cues, 2) la que está en playlists,
    3) más bitrate, 4) archivo existente, 5) la más vieja."""
    def puntaje(c):
        return (c["existe"], c["hot"] + c["mem"] > 0, len(c["playlists"]) > 0, c["hot"] + c["mem"],
                len(c["playlists"]), c["bitrate"], -c["agregadoTs"])
    orden = sorted(copias, key=puntaje, reverse=True)
    mejor = orden[0]
    otra = orden[1]
    if mejor["hot"] + mejor["mem"] > 0 and otra["hot"] + otra["mem"] == 0:
        motivo = "Se conserva la que tiene cue points."
    elif mejor["playlists"] and not otra["playlists"]:
        motivo = "Se conserva la que está en playlists."
    elif mejor["hot"] + mejor["mem"] > 0 and otra["hot"] + otra["mem"] > 0:
        motivo = "Las dos tienen cue points: se conserva la que tiene más cues y playlists."
    elif mejor["bitrate"] > otra["bitrate"]:
        motivo = "Se conserva la de mejor calidad."
    else:
        motivo = "Se conserva la más antigua en la colección."
    return mejor["id"], motivo


def buscar_duplicados():
    with lock:
        db = abrir()
        try:
            hot, mem = _cues_por_tema(db)
            playlists = {str(p.ID): p.Name for p in db.get_playlist() if p.Attribute == 0 and not p.SmartList}
            en_pl = defaultdict(list)
            for s in db.get_playlist_songs():
                if str(s.PlaylistID) in playlists:
                    en_pl[str(s.ContentID)].append(playlists[str(s.PlaylistID)])
            mom_ids = {t.ID: t.Name for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == ids_categorias(db)[CAT_MOMENTO])}
            momento = {}
            for a in db.query(m.DjmdSongMyTag):
                if a.MyTagID in mom_ids:
                    momento[str(a.ContentID)] = mom_ids[a.MyTagID]
            temas = {}
            por_clave, por_archivo = defaultdict(list), defaultdict(list)
            for c in db.get_content():
                cid = str(c.ID)
                fecha = c.created_at or datetime.datetime(2000, 1, 1)
                temas[cid] = {
                    "id": cid, "titulo": c.Title or "", "artista": c.ArtistName or "",
                    "ruta": c.FolderPath or "", "archivo": Path(c.FolderPath or "").name,
                    "existe": bool(c.FolderPath) and Path(c.FolderPath).is_file(),
                    "duracion": c.Length or 0, "bitrate": c.BitRate or 0, "tamano": c.FileSize or 0,
                    "hot": hot.get(cid, 0), "mem": mem.get(cid, 0), "playlists": en_pl.get(cid, []),
                    "momento": momento.get(cid, ""), "agregado": fecha.strftime("%d/%m/%Y"),
                    "agregadoTs": fecha.timestamp(),
                }
                kt, ka = _clave_titulo(c.Title), _clave_artista(c.ArtistName)
                if kt and ka:
                    por_clave[(ka, kt)].append(cid)
                if c.FileSize and c.Length:
                    por_archivo[(c.FileSize, c.Length)].append(cid)
        finally:
            db.close()

    # componentes: une por clave (artista + título) y por archivo idéntico (tamaño + duración)
    padre = {}

    def raiz(x):
        while padre.setdefault(x, x) != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for ids in list(por_clave.values()) + list(por_archivo.values()):
        for i in ids[1:]:
            padre[raiz(i)] = raiz(ids[0])
    comp = defaultdict(list)
    for cid in padre:
        comp[raiz(cid)].append(cid)
    clave_de = {cid: k for k, ids in por_clave.items() for cid in ids}

    grupos = []
    for ids in comp.values():
        if len(ids) < 2:
            continue
        copias = sorted((temas[i] for i in ids), key=lambda c: c["archivo"].lower())
        durs = [c["duracion"] for c in copias]
        misma_clave = len({clave_de.get(c["id"]) for c in copias}) == 1 and clave_de.get(copias[0]["id"])
        mismo_archivo = len({(c["tamano"], c["duracion"]) for c in copias}) == 1
        if not misma_clave:
            tipo, conservar, motivo = "Posible", None, \
                "Mismo tamaño y duración pero distinto nombre: puede ser el mismo audio mal etiquetado. Escuchalos antes de borrar."
        elif max(durs) - min(durs) > 8:
            tipo, conservar, motivo = "Posible", None, \
                "Las duraciones no coinciden: puede ser otra versión. Escuchalos antes de borrar."
        else:
            tipo = "Archivo idéntico" if mismo_archivo else "Mismo tema"
            conservar, motivo = _sugerencia(copias)
        grupos.append({"id": "-".join(sorted(ids)), "titulo": f"{copias[0]['artista']} – {copias[0]['titulo']}",
                       "tipo": tipo, "conservar": conservar, "motivo": motivo,
                       "mismoArchivo": len({_clave_path(c["ruta"]) for c in copias}) < len(copias), "copias": copias})
    grupos.sort(key=lambda g: (g["conservar"] is None, g["titulo"].lower()))
    return grupos


def _reemplazar_en_playlists(db, viejo, nuevo):
    n = total = 0
    for s in list(db.query(m.DjmdSongPlaylist).filter(m.DjmdSongPlaylist.ContentID == viejo)):
        total += 1
        pl = db.get_playlist(ID=s.PlaylistID)
        tn = s.TrackNo
        ya = db.query(m.DjmdSongPlaylist).filter(m.DjmdSongPlaylist.PlaylistID == s.PlaylistID,
                                                 m.DjmdSongPlaylist.ContentID == nuevo).count()
        db.remove_from_playlist(pl, s)
        if not ya and pl is not None and pl.Attribute == 0:
            largo = db.query(m.DjmdSongPlaylist).filter(m.DjmdSongPlaylist.PlaylistID == s.PlaylistID).count()
            db.add_to_playlist(pl, nuevo, track_no=tn if tn and tn <= largo else None)
            n += 1
    return n, total


TABLAS_TEMA = ["DjmdCue", "ContentCue", "ContentFile", "ContentActiveCensor", "DjmdActiveCensor",
               "DjmdMixerParam", "DjmdSongHotCueBanklist", "DjmdSongMyTag", "DjmdSongRelatedTracks",
               "DjmdSongTagList"]


def revisar_eliminar(ids):
    """Antes de eliminar: cada tema con las playlists donde está."""
    with lock:
        db = abrir()
        try:
            nombres = {str(p.ID): p.Name for p in db.get_playlist() if p.Attribute == 0}
            out = []
            for cid in dict.fromkeys(str(i) for i in ids):
                c = db.get_content(ID=cid)
                if c is None:
                    continue
                pls = sorted({nombres[str(s.PlaylistID)] for s in db.query(m.DjmdSongPlaylist)
                              .filter(m.DjmdSongPlaylist.ContentID == cid) if str(s.PlaylistID) in nombres}, key=str.lower)
                out.append({"id": cid, "titulo": c.Title or Path(c.FolderPath or "").stem,
                            "artista": c.ArtistName or "", "playlists": pls})
            return out
        finally:
            db.close()


def eliminar_temas(ids, eliminar_archivo, log):
    """Saca los temas de Rekordbox (y de sus playlists) y lleva sus archivos a la carpeta «eliminados».
    eliminar_archivo(ruta) mueve el archivo (historial.Operacion.eliminar_archivo)."""
    res = {"eliminados": 0, "dePlaylists": 0, "archivos": 0, "errores": []}
    with lock:
        db = abrir()
        try:
            rutas = []
            for cid in dict.fromkeys(str(i) for i in ids):
                c = db.get_content(ID=cid)
                if c is None:
                    continue
                for s in list(db.query(m.DjmdSongPlaylist).filter(m.DjmdSongPlaylist.ContentID == cid)):
                    db.remove_from_playlist(db.get_playlist(ID=s.PlaylistID), s)
                    res["dePlaylists"] += 1
                for nombre in TABLAS_TEMA + ["DjmdSongHistory", "DjmdSongSampler"]:
                    modelo = getattr(m, nombre)
                    for r in list(db.query(modelo).filter(modelo.ContentID == cid)):
                        db.delete(r)
                if c.FolderPath:
                    rutas.append(c.FolderPath)
                db.delete(c)
                res["eliminados"] += 1
                log(f"Eliminado: {c.ArtistName} - {c.Title}")
            db.commit()
            # sólo se mueven los archivos que ya no usa ningún otro tema de Rekordbox
            en_uso = {_clave_path(c.FolderPath) for c in db.get_content()}
            vistos = set()
            for ruta in rutas:
                k = _clave_path(ruta)
                if k in en_uso or k in vistos or not Path(ruta).is_file():
                    continue
                vistos.add(k)
                try:
                    eliminar_archivo(ruta)
                    res["archivos"] += 1
                except PermissionError:
                    motivo = ("Windows no dejó moverlo (¿está abierto en otro programa?)" if plataforma.ES_WIN
                              else "macOS no dejó moverlo (falta «Acceso total al disco»)")
                    res["errores"].append(f"{Path(ruta).name}: {motivo}. Quedó fuera de Rekordbox pero sigue en la carpeta.")
                except Exception as e:
                    res["errores"].append(f"{Path(ruta).name}: no se pudo mover ({e})")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    return res


def borrar_duplicados(grupos, mover_archivo, log):
    """grupos: [{conservar: id, borrar: [ids]}]. Reemplaza en playlists, pasa el Momento
    y el historial de reproducción, borra de Rekordbox y mueve el archivo al backup."""
    res = {"borrados": 0, "reemplazos": 0, "yaEstaba": 0, "errores": []}
    ahora = datetime.datetime.now()
    with lock:
        db = abrir()
        try:
            a_mover = []
            mom_ids = {t.ID for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == ids_categorias(db)[CAT_MOMENTO])}
            for g in grupos:
                keep = db.get_content(ID=str(g["conservar"]))
                if keep is None:
                    res["errores"].append(f"No encontré el tema a conservar ({g['conservar']})")
                    continue
                for bid in g["borrar"]:
                    bid = str(bid)
                    if bid == str(keep.ID):
                        continue
                    c = db.get_content(ID=bid)
                    if c is None:
                        continue
                    ruta = c.FolderPath or ""
                    reemp, total = _reemplazar_en_playlists(db, bid, str(keep.ID))
                    res["reemplazos"] += reemp
                    res["yaEstaba"] += total - reemp
                    # Momento: si el que queda no tiene, hereda el del borrado
                    tiene = db.query(m.DjmdSongMyTag).filter(m.DjmdSongMyTag.ContentID == str(keep.ID),
                                                             m.DjmdSongMyTag.MyTagID.in_(mom_ids)).count()
                    if not tiene:
                        for a in db.query(m.DjmdSongMyTag).filter(m.DjmdSongMyTag.ContentID == bid,
                                                                  m.DjmdSongMyTag.MyTagID.in_(mom_ids)):
                            db.add(m.DjmdSongMyTag.create(
                                ID=str(uuid4()), MyTagID=a.MyTagID, ContentID=str(keep.ID), TrackNo=None,
                                UUID=str(uuid4()), created_at=ahora, updated_at=ahora))
                    # historial de reproducción y sampler pasan al que queda
                    for modelo in (m.DjmdSongHistory, m.DjmdSongSampler):
                        for r in db.query(modelo).filter(modelo.ContentID == bid):
                            r.ContentID = str(keep.ID)
                    for nombre in TABLAS_TEMA:
                        modelo = getattr(m, nombre)
                        for r in list(db.query(modelo).filter(modelo.ContentID == bid)):
                            db.delete(r)
                    db.delete(c)
                    if ruta:
                        a_mover.append(ruta)
                    res["borrados"] += 1
                    log(f"Borrado: {c.ArtistName} - {c.Title} ({Path(ruta).name})")
            db.commit()
            # sólo se mueven archivos que ya no usa ningún tema de Rekordbox (comparando como macOS)
            en_uso = {_clave_path(c.FolderPath) for c in db.get_content()}
            vistos = set()
            a_mover = [r for r in a_mover if _clave_path(r) not in en_uso and Path(r).is_file()
                       and not (_clave_path(r) in vistos or vistos.add(_clave_path(r)))]
            for ruta in a_mover:          # recién con la base guardada se sacan los archivos
                try:
                    mover_archivo(ruta)
                except PermissionError:
                    motivo = ("Windows no dejó moverlo (¿está abierto en otro programa?)" if plataforma.ES_WIN
                              else "macOS no dejó moverlo (falta «Acceso total al disco»)")
                    res["errores"].append(f"{Path(ruta).name}: {motivo}. Quedó fuera de Rekordbox pero sigue en la carpeta.")
                except Exception as e:
                    res["errores"].append(f"{Path(ruta).name}: no se pudo mover ({e})")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    return res


# =============================================================================
# MY TAGS: listar y editar (las categorías automáticas se generan solas)
# =============================================================================
def listar_mytags():
    with lock:
        db = abrir()
        try:
            cuenta = defaultdict(int)
            for a in db.query(m.DjmdSongMyTag):
                cuenta[a.MyTagID] += 1
            ids = ids_categorias(db)
            out = []
            for cfg in categorias.cargar():
                tags = [{"id": t.ID, "nombre": t.Name, "temas": cuenta.get(t.ID, 0)} for t in
                        db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == ids[cfg["id"]]).order_by(m.DjmdMyTag.Seq)]
                if cfg["fuente"] != "manual":
                    # los tags que trae Rekordbox de fábrica (sin temas) no son de esta categoría:
                    # se borran solos al actualizar la base
                    tags = [t for t in tags if t["temas"]]
                out.append({**cfg, "tags": tags, "manual": cfg["fuente"] == "manual"})
            return out
        finally:
            db.close()


def _renumerar(db, cat, ahora):
    for seq, t in enumerate(db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == cat).order_by(m.DjmdMyTag.Seq), 1):
        if t.Seq != seq:
            t.Seq, t.updated_at = seq, ahora


def editar_mytags(cambios):
    """cambios: [{cat, accion: agregar|renombrar|borrar|ordenar, ...}] sólo sobre categorías manuales."""
    ahora = datetime.datetime.now()
    manuales = {k["id"] for k in categorias.cargar() if k["fuente"] == "manual"}
    with lock:
        db = abrir()
        try:
            for c in cambios:
                cat = str(c.get("cat") or CAT_MOMENTO)
                if cat not in manuales:
                    continue
                cat = ids_categorias(db)[cat]
                acc = c.get("accion")
                if acc == "agregar":
                    nombre = (c.get("nombre") or "").strip()
                    if nombre:
                        _tag_en_categoria(db, cat, nombre, ahora)
                elif acc in ("renombrar", "borrar"):
                    t = db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ID == str(c["id"]),
                                                     m.DjmdMyTag.ParentID == cat).one_or_none()
                    if t is None:
                        continue
                    if acc == "renombrar" and (c.get("nombre") or "").strip():
                        nuevo = c["nombre"].strip()
                        if db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == cat, m.DjmdMyTag.Name == nuevo,
                                                        m.DjmdMyTag.ID != t.ID).count():
                            raise ValueError(f"Ya hay un tag que se llama «{nuevo}» en esa categoría.")
                        t.Name, t.updated_at = nuevo, ahora
                    elif acc == "borrar":
                        for a in list(db.query(m.DjmdSongMyTag).filter(m.DjmdSongMyTag.MyTagID == t.ID)):
                            db.delete(a)
                        db.delete(t)
                elif acc == "ordenar":
                    for seq, tid in enumerate(c.get("ids", []), 1):
                        t = db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ID == str(tid)).one_or_none()
                        if t is not None and t.ParentID == cat:
                            t.Seq, t.updated_at = seq, ahora
                db.flush()
                _renumerar(db, cat, ahora)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


# =============================================================================
# NOMBRES DE ARCHIVO PROLIJOS
# =============================================================================
def artistas_conocidos(db=None):
    from . import nombres
    propio = db is None
    db = db or abrir()
    try:
        nombres_a = {a.Name for a in db.get_artist() if a.Name}
    finally:
        if propio:
            db.close()
    con = {a.lower() for a in nombres_a}
    for a in nombres_a:
        con |= {p.lower() for p in nombres.separar_artistas(a)}
    return con


def propuesta_nombres():
    from . import nombres
    with lock:
        db = abrir()
        try:
            con = artistas_conocidos(db)
            usados = {unicodedata.normalize("NFC", c.FolderPath or "").casefold() for c in db.get_content()}
            out = []
            for c in db.get_content():
                ruta = c.FolderPath or ""
                p = Path(ruta)
                if not ruta or "/samples/" in ruta.lower().replace("\\", "/") or not p.is_file():
                    continue
                nuevo = nombres.nombre_archivo(c.ArtistName or "", c.Title or p.stem, p.suffix, conocidos=con)
                if nuevo == p.name:
                    continue
                destino = p.with_name(nuevo)
                if _clave_path(destino) in usados and _clave_path(destino) != _clave_path(p):
                    continue                     # ya hay otro tema con ese nombre: se deja como está
                out.append({"id": str(c.ID), "viejo": p.name, "nuevo": nuevo, "carpeta": str(p.parent)})
            return out
        finally:
            db.close()


def renombrar(cambios, op, log):
    """cambios: [{id, nuevo}]. Renombra el archivo y actualiza Rekordbox (y sus archivos de análisis)."""
    hechos, errores, renombrados = 0, [], {}
    with lock:
        db = abrir()
        try:
            for ch in cambios:
                c = db.get_content(ID=str(ch["id"]))
                if c is None or not c.FolderPath or not Path(c.FolderPath).is_file():
                    continue
                viejo = Path(c.FolderPath)
                nuevo = viejo.with_name(ch["nuevo"])
                if _clave_path(nuevo) != _clave_path(viejo) and nuevo.exists():
                    errores.append(f"{viejo.name}: ya existe «{nuevo.name}»")
                    continue
                try:
                    for anlz in (db.get_anlz_paths(c) or {}).values():
                        if anlz and Path(anlz).is_file():
                            op.respaldar_archivo(anlz)
                except Exception:
                    pass
                os.rename(viejo, nuevo)
                renombrados[str(nuevo)] = str(viejo)
                try:
                    db.update_content_path(c, nuevo.as_posix(), save=True, check_path=True, commit=False)
                except Exception:
                    c.FolderPath = nuevo.as_posix()    # si el análisis no se puede leer, al menos la base
                    c.FileNameL = nuevo.name
                hechos += 1
                log(f"{viejo.name} -> {nuevo.name}")
            db.commit()
        except Exception:
            db.rollback()
            for n, v in renombrados.items():            # la base no se guardó: los nombres vuelven
                try:
                    os.rename(n, v)
                except Exception:
                    pass
            raise
        finally:
            db.close()
    op.renombrados.update(renombrados)
    return {"renombrados": hechos, "errores": errores}


# =============================================================================
# SINCRONIZAR CATEGORÍAS AUTOMÁTICAS (reemplaza al script viejo de My Tags)
# =============================================================================
def sincronizar_categorias(simular=True, leer_archivos=True):
    """Recalcula las categorías automáticas para toda la colección.
    Si un tema no tiene país/idioma en Rekordbox, lo busca en el comentario del archivo."""
    ahora = datetime.datetime.now()
    cats = categorias.cargar()
    resumen = []
    with lock:
        db = abrir()
        try:
            temas = db.get_content().all()
            datos = {}
            for c in temas:
                d = _datos(c)
                if leer_archivos and not (d["pais"] and d["idioma"]) and c.FolderPath and Path(c.FolderPath).is_file():
                    p, i = archivos.pais_idioma(archivos.leer(c.FolderPath).get("comentario", ""))
                    d["pais"], d["idioma"] = d["pais"] or p, d["idioma"] or i
                datos[str(c.ID)] = d
            actuales = defaultdict(lambda: defaultdict(set))
            nombre_tag = {t.ID: (t.ParentID, t.Name) for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.Attribute == 0)}
            for a in db.query(m.DjmdSongMyTag):
                if a.MyTagID in nombre_tag:
                    cat, n = nombre_tag[a.MyTagID]
                    actuales[cat][str(a.ContentID)].add(n)
            ids = ids_categorias(db)
            for cfg in cats:
                cat = ids[cfg["id"]]
                fila = db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ID == cat).one_or_none()
                if fila is not None and fila.Name != cfg["nombre"] and not simular:
                    fila.Name, fila.updated_at = cfg["nombre"], ahora
                if cfg["fuente"] == "manual":
                    resumen.append({**cfg, "cambios": 0, "tags": {}})
                    continue
                deseado = {cid: set(categorias.calcular(cfg["fuente"], d)) for cid, d in datos.items()}
                cuenta = defaultdict(int)
                for s in deseado.values():
                    for n in s:
                        cuenta[n] += 1
                cambios = sum(1 for cid in datos if deseado[cid] != actuales[cat].get(cid, set()))
                propios = [tags - set(cuenta) for tags in actuales[cat].values() if tags - set(cuenta)]
                resumen.append({**cfg, "cambios": cambios,
                                "tags": {n: cuenta[n] for n in categorias.orden(cfg["fuente"], cuenta)},
                                "seQuitan": {"temas": len(propios), "tags": sorted(set().union(*propios))}})
                if simular:
                    continue
                for cid in datos:
                    if deseado[cid] != actuales[cat].get(cid, set()):
                        _poner_tags(db, cid, cat, sorted(deseado[cid]), ahora)
                db.flush()
                # se borran los tags que ya no usa nadie y se ordenan
                orden = categorias.orden(cfg["fuente"], cuenta)
                for t in list(db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == cat)):
                    if t.Name not in cuenta:
                        for a in list(db.query(m.DjmdSongMyTag).filter(m.DjmdSongMyTag.MyTagID == t.ID)):
                            db.delete(a)
                        db.delete(t)
                db.flush()
                pos = {n: i for i, n in enumerate(orden, 1)}
                for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == cat):
                    if t.Name in pos and t.Seq != pos[t.Name]:
                        t.Seq, t.updated_at = pos[t.Name], ahora
            if not simular:
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    return resumen
