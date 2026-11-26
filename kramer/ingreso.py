"""Pasos 2 y 3: analizar las descargas (metadata + calidad + duplicados) e incorporarlas."""
import datetime
import json
import os
import re
import shutil
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import archivos, config, mytags, oc, rb

EXT = oc.EXT_AUDIO
DESCARTADOS = "_descartados"
PREPARADOS = config.DIR_APP / "preparados.json"      # temas listos para el paso 3
FUENTES = {"mb": "MusicBrainz", "wd": "Wikidata", "itunes": "iTunes", "lastfm": "Last.fm",
           "discogs": "Discogs", "img": "Carátulas"}
CAMPOS = {"genero": "Género", "grouping": "Subgénero (Grouping)", "anio": "Año", "album": "Álbum",
          "caratula": "Carátula", "pais": "País", "idioma": "Idioma", "renombrar": 'Nombre prolijo "Artista - Tema (feat.) (Versión)"',
          "pisar": "Pisar datos que ya tienen"}
DEFAULT_CAMPOS = {k: k != "pisar" for k in CAMPOS}
DEFAULT_FUENTES = {k: True for k in FUENTES}


def preparar_ffmpeg():
    """La app trae su propio ffmpeg (para analizar la calidad, también de los .m4a)."""
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        dir_bin = config.DIR_APP / "bin"
        dir_bin.mkdir(parents=True, exist_ok=True)
        enlace = dir_bin / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if not enlace.exists():
            try:
                enlace.symlink_to(exe)
            except OSError:              # Windows no deja crear enlaces sin permisos de administrador
                shutil.copy2(exe, enlace)
        os.environ["PATH"] = f"{dir_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    except Exception:
        pass


class FuentesElegidas(oc.Fuentes):
    def __init__(self, lastfm, discogs, apagadas):
        super().__init__(lastfm, discogs, offline=False)
        self.apagadas = set(apagadas)

    def get(self, fuente, url, params=None):
        if fuente in self.apagadas:
            return None
        return super().get(fuente, url, params)

    def descargar_imagen(self, url, destino):
        if "img" in self.apagadas:
            return False
        return super().descargar_imagen(url, destino)


def _clave_path(p):
    return unicodedata.normalize("NFC", str(p)).casefold()


def listar(carpeta=None):
    carpeta = Path(carpeta or config.cargar()["incorporar"])
    coleccion = _clave_path(Path(config.cargar()["coleccion"]))
    out = []
    if not carpeta.is_dir():
        return out
    for root, dirs, files in os.walk(carpeta):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != DESCARTADOS
                   and not _clave_path(Path(root) / d).startswith(coleccion)]
        for f in files:
            if not f.startswith(".") and Path(f).suffix.lower() in EXT:
                out.append(str(Path(root) / f))
    return sorted(out, key=lambda x: x.lower())


def _indice_coleccion():
    with rb.lock:
        db = rb.abrir()
        try:
            idx = {}
            for c in db.get_content():
                k = (rb._clave_artista(c.ArtistName), rb._clave_titulo(c.Title))
                idx.setdefault(k, []).append({"id": str(c.ID), "archivo": Path(c.FolderPath or "").name,
                                              "duracion": c.Length or 0})
            return idx
        finally:
            db.close()


def _nombre_limpio(artista, titulo, ext, conocidos=None):
    from . import nombres
    return nombres.nombre_archivo(artista, titulo, ext, conocidos=conocidos)


def analizar(trabajo, rutas, campos, fuentes_on):
    """Para cada archivo: duplicado, calidad y metadata propuesta. No escribe nada."""
    preparar_ffmpeg()
    c = config.cargar()
    apagadas = [k for k, v in fuentes_on.items() if not v]
    F = FuentesElegidas(c.get("lastfm", ""), c.get("discogs", ""), apagadas)
    idx = _indice_coleccion()
    from . import nombres
    with rb.lock:
        conocidos = rb.artistas_conocidos()
    hacer_calidad = bool(shutil.which("ffmpeg") or shutil.which("afconvert"))
    tmp = Path(tempfile.mkdtemp(prefix="rkb_car_"))

    def uno(i_ruta):
        i, ruta = i_ruta
        if trabajo.cancelar:
            return
        p = Path(ruta)
        item = {"ruta": ruta, "archivo": p.name, "estado": "ok", "notas": []}
        try:
            tags = oc.leer_tags(p)
            item["duracion"] = round(tags["duration"] or 0)
            item["bitrate"] = (tags["bitrate"] or 0) // 1000
            # calidad
            if hacer_calidad:
                q = oc.analizar_calidad(p, tags)
                item["calidad"], item["corte"] = q["estado"], q["corte"]
            else:
                item["calidad"], item["corte"] = "SIN ANALIZAR", None
            # metadata
            r = oc.analizar_tema(p, F, tags)
            artista, titulo = r["artista"], r["titulo"]
            if campos.get("renombrar"):          # nombre y metadata prolijos, con el mismo formato
                artista, titulo = nombres.prolijo(artista, titulo, conocidos)
            pisar = campos.get("pisar")

            def elegir(nuevo, actual):
                return nuevo if (nuevo and (pisar or not actual)) else (actual or nuevo or "")

            pais0, idioma0 = archivos.pais_idioma(tags["comment"])
            meta = {"artista": artista, "titulo": titulo}
            if campos.get("genero"):
                meta["genero"] = elegir(r.get("genero"), tags["genre"])
            if campos.get("grouping"):
                meta["grouping"] = elegir(oc.elegir_grouping(r, tags["grouping"]), tags["grouping"])
            if campos.get("anio"):
                meta["anio"] = elegir(str(r["anio"]) if r.get("anio") else "", tags["year"][:4])
            if campos.get("album"):
                meta["album"] = elegir(r.get("album"), tags["album"])
            if campos.get("pais"):
                meta["pais"] = elegir(r.get("pais"), pais0)
            if campos.get("idioma"):
                meta["idioma"] = elegir(r.get("idioma"), idioma0)
            item["meta"] = meta
            item["confianza"] = r.get("confianza", "")
            if r.get("confianza") == "BAJA":
                item["notas"].append("No figura en las fuentes: revisá los datos")
            elif r.get("notas"):
                item["notas"].append(r["notas"])
            if campos.get("caratula"):
                car = oc.preparar_caratula(F, r, tags, tmp, i)
                if car:
                    destino = tmp / f"{i:05d}.img"
                    destino.write_bytes(car)
                    item["caratulaNueva"] = str(destino)
            item["nuevoNombre"] = _nombre_limpio(artista, titulo, p.suffix, conocidos) if campos.get("renombrar") else p.name
            # duplicado contra la colección
            k = (rb._clave_artista(artista), rb._clave_titulo(titulo))
            dups = idx.get(k, [])
            if dups:
                d = dups[0]
                misma = abs((d["duracion"] or 0) - item["duracion"]) <= 4
                item["duplicado"] = {"archivo": d["archivo"], "id": d["id"], "mismaDuracion": misma}
                item["accion"] = "eliminar" if misma else "conservar"
                item["notas"].insert(0, f"Ya lo tenés: {d['archivo']}" + ("" if misma else " (otra duración: ¿otra versión?)"))
            else:
                item["accion"] = "eliminar" if item["calidad"] == "MALO" else "conservar"
        except Exception as e:
            item.update(estado="error", accion="conservar", notas=[f"Error: {e}"])
        trabajo.avanzar(item, f"{p.name}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(uno, enumerate(rutas)))
    F.guardar()
    return {"total": len(rutas)}


def aplicar_metadata(items, op, log):
    """Escribe la metadata elegida, renombra y separa los descartados. Devuelve los preparados."""
    c = config.cargar()
    base_inc = Path(c["incorporar"])
    preparados, descartados, errores = [], [], []
    for it in items:
        ruta = Path(it["ruta"])
        if not ruta.is_file():
            errores.append(f"{ruta.name}: ya no está")
            continue
        if it.get("accion") == "eliminar":
            dest = base_inc / DESCARTADOS / ruta.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest = _unico(dest)
            shutil.move(str(ruta), dest)
            descartados.append(str(dest))
            continue
        try:
            op.respaldar_archivo(ruta)
            m = it.get("meta", {})
            cambios = {k: m[k] for k in ("titulo", "artista", "album", "anio", "genero", "grouping") if k in m}
            if "pais" in m or "idioma" in m:
                previo = archivos.leer(ruta).get("comentario", "")
                cambios["comentario"] = archivos.armar_comentario(previo, m.get("pais", ""), m.get("idioma", ""))
            archivos.escribir(ruta, cambios)
            if it.get("caratulaNueva") and Path(it["caratulaNueva"]).is_file():
                oc.escribir_tags(ruta, {}, Path(it["caratulaNueva"]).read_bytes())
            nuevo = ruta.with_name(it.get("nuevoNombre") or ruta.name)
            if nuevo != ruta:
                nuevo = _unico(nuevo)
                ruta.rename(nuevo)
                ruta = nuevo
            preparados.append({"ruta": str(ruta), "meta": m, "calidad": it.get("calidad"),
                               "corte": it.get("corte"), "duracion": it.get("duracion"), "bitrate": it.get("bitrate")})
            log(f"Listo: {ruta.name}")
        except Exception as e:
            errores.append(f"{ruta.name}: {e}")
    previos = [p for p in leer_preparados() if p["ruta"] not in {x["ruta"] for x in preparados}]
    guardar_preparados(previos + preparados)
    return {"preparados": len(preparados), "descartados": len(descartados), "errores": errores}


def _unico(p):
    p = Path(p)
    if not p.exists():
        return p
    for n in range(2, 999):
        q = p.with_name(f"{p.stem} ({n}){p.suffix}")
        if not q.exists():
            return q
    return p


def leer_preparados():
    try:
        datos = json.loads(PREPARADOS.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [d for d in datos if Path(d["ruta"]).is_file()]


def guardar_preparados(lista):
    PREPARADOS.parent.mkdir(parents=True, exist_ok=True)
    tmp = PREPARADOS.with_suffix(".tmp")
    tmp.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PREPARADOS)


# =============================================================================
# PASO 3: INCORPORAR
# =============================================================================
CARPETA_IMPORTACIONES = "Importaciones"


def _playlist_importacion(db, ahora):
    """Crea «Importación AAAA-MM-DD» (o «… (2)» si ya hubo otra ese día) dentro de la carpeta Importaciones."""
    from pyrekordbox.masterdb import models as m
    carpeta = (db.query(m.DjmdPlaylist).filter(m.DjmdPlaylist.Name == CARPETA_IMPORTACIONES,
                                              m.DjmdPlaylist.Attribute == 1).first()
               or db.create_playlist_folder(CARPETA_IMPORTACIONES))
    base = f"Importación {ahora:%Y-%m-%d}"
    existentes = {p.Name for p in db.query(m.DjmdPlaylist).filter(m.DjmdPlaylist.ParentID == carpeta.ID)}
    nombre, n = base, 2
    while nombre in existentes:
        nombre, n = f"{base} ({n})", n + 1
    return db.create_playlist(nombre, parent=carpeta)


def incorporar(rutas, playlist_id, op, log, playlist_fecha=True):
    from pyrekordbox.masterdb import models as m
    c = config.cargar()
    coleccion = Path(c["coleccion"])
    prep = {p["ruta"]: p for p in leer_preparados()}
    hechos, errores, en_playlist = [], [], 0
    ahora = datetime.datetime.now()
    movidos = []
    with rb.lock:
        db = rb.abrir()
        try:
            pl = db.get_playlist(ID=str(playlist_id)) if playlist_id else None
            pl_fecha = _playlist_importacion(db, ahora) if playlist_fecha and rutas else None
            for ruta in rutas:
                src = Path(ruta)
                if not src.is_file():
                    errores.append(f"{src.name}: ya no está")
                    continue
                dest = _unico(coleccion / src.name)
                op.respaldar_archivo(src)
                shutil.move(str(src), dest)
                movidos.append((src, dest))
                op.creados.append(str(dest))
                t = archivos.leer(dest)
                info = prep.get(ruta, {})
                pais, idioma = archivos.pais_idioma(t.get("comentario", ""))
                kw = {"Title": t["titulo"] or dest.stem, "Commnt": t.get("comentario") or None,
                      "Length": int(info.get("duracion") or 0) or None,
                      "BitRate": int(info.get("bitrate") or 0) or None}
                try:
                    kw["ReleaseYear"] = int(t["anio"][:4]) if t.get("anio") else None
                except ValueError:
                    pass
                cont = db.add_content(str(dest), **{k: v for k, v in kw.items() if v is not None})
                if t.get("artista"):
                    a = db.get_artist(Name=t["artista"]).first() or db.add_artist(t["artista"])
                    cont.ArtistID = a.ID
                if t.get("album"):
                    a = db.get_album(Name=t["album"]).first() or db.add_album(t["album"])
                    cont.AlbumID = a.ID
                if t.get("genero"):
                    g = db.get_genre(Name=t["genero"]).first() or db.add_genre(t["genero"])
                    cont.GenreID = g.ID
                cid = str(cont.ID)
                db.flush()
                rb.tags_automaticos(db, cid, rb._datos(cont, pais, idioma), ahora)
                if pl is not None:
                    db.add_to_playlist(pl, cont)
                    en_playlist += 1
                if pl_fecha is not None:
                    db.add_to_playlist(pl_fecha, cont)
                hechos.append(dest.name)
                log(f"Incorporado: {dest.name}")
            pl_fecha_nombre = pl_fecha.Name if pl_fecha is not None else None
            db.commit()
        except Exception:
            db.rollback()
            for src, dest in reversed(movidos):     # la base no se guardó: los archivos vuelven
                try:
                    shutil.move(str(dest), src)
                except Exception:
                    pass
            raise
        finally:
            db.close()
    restantes = [p for p in leer_preparados() if p["ruta"] not in set(rutas)]
    guardar_preparados(restantes)
    return {"incorporados": len(hechos), "enPlaylist": en_playlist, "errores": errores,
            "playlistFecha": pl_fecha_nombre}


def chequeo_playlist(playlist_id):
    """Para el evento: archivos perdidos, temas sin analizar en Rekordbox y calidad (si se analizó)."""
    from pyrekordbox.masterdb import models as m
    with rb.lock:
        db = rb.abrir()
        try:
            pl = db.get_playlist(ID=str(playlist_id))
            if pl is None:
                return None
            filas = []
            canciones = sorted(db.query(m.DjmdSongPlaylist).filter(m.DjmdSongPlaylist.PlaylistID == pl.ID),
                               key=lambda s: s.TrackNo or 0)
            for s in canciones:
                c = db.get_content(ID=str(s.ContentID))
                if c is None:
                    continue
                filas.append({"id": str(c.ID), "tema": f"{c.ArtistName or ''} - {c.Title or ''}".strip(" -"),
                              "existe": bool(c.FolderPath) and Path(c.FolderPath).is_file(),
                              "analizado": bool(c.Analysed), "ruta": c.FolderPath or ""})
            return {"nombre": pl.Name, "temas": filas,
                    "perdidos": sum(not f["existe"] for f in filas),
                    "sinAnalizar": sum(not f["analizado"] for f in filas)}
        finally:
            db.close()


def calidad_de(rutas, trabajo):
    preparar_ffmpeg()
    for r in rutas:
        if trabajo.cancelar:
            break
        p = Path(r)
        if p.is_file():
            q = oc.analizar_calidad(p, oc.leer_tags(p))
            trabajo.avanzar({"ruta": r, "calidad": q["estado"], "corte": q["corte"]}, p.name)
        else:
            trabajo.avanzar({"ruta": r, "calidad": "NO ESTÁ", "corte": None}, p.name)
