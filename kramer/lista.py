"""Paso 1: lista del cliente vs colección -> lista depurada (txt) y evento opcional."""
import csv
import datetime
import difflib
import io
import re
from pathlib import Path
from urllib.parse import quote_plus

from . import config, rb

TIENDAS = [("Beatsource", "https://www.beatsource.com/search?q={q}"),
           ("Beatport", "https://www.beatport.com/search?q={q}"),
           ("iTunes", "https://music.apple.com/search?term={q}"),
           ("Bandcamp", "https://bandcamp.com/search?q={q}")]

_VERSION = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")


# ------------------------------------------------------------------ lectura
def _partir(linea):
    linea = re.sub(r"^\s*(\d+[\.\)\-]\s+|[-•*]\s+)", "", linea).strip()   # numeración / viñetas
    for sep in (" - ", " – ", " — ", " -- ", " | ", "\t"):
        if sep in linea:
            a, t = linea.split(sep, 1)
            return a.strip(), t.strip()
    return "", linea.strip()


def leer(texto, nombre=""):
    """Acepta: texto pegado ('Artista - Tema' por línea), CSV (Spotify/Exportify, etc.) y M3U."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    filas = []
    ext = Path(nombre).suffix.lower()
    if ext in (".m3u", ".m3u8") or texto.startswith("#EXTM3U"):
        con_info = False
        for l in texto.split("\n"):
            l = l.strip()
            if l.startswith("#EXTINF"):
                filas.append(_partir(l.split(",", 1)[-1]))
                con_info = True
            elif l and not l.startswith("#"):
                if not con_info:
                    filas.append(_partir(Path(l).stem))
                con_info = False
    elif ext in (".csv", ".tsv") or (texto.count(",") > texto.count("\n") and "\n" in texto
                                      and re.search(r"(?i)(track|title|t[ií]tulo|tema|song)", texto.split("\n")[0])):
        dialecto = csv.Sniffer().sniff(texto[:4000], delimiters=",;\t") if texto.strip() else csv.excel
        r = csv.DictReader(io.StringIO(texto), dialect=dialecto)
        cols = {c.lower().strip(): c for c in (r.fieldnames or [])}
        ct = next((cols[c] for c in cols if re.search(r"track name|^title$|^name$|t[ií]tulo|^tema$|^song", c)), None)
        ca = next((cols[c] for c in cols if re.search(r"artist|artista|int[ée]rprete", c)), None)
        for row in r:
            t = (row.get(ct) or "").strip() if ct else ""
            a = (row.get(ca) or "").strip() if ca else ""
            a = re.split(r"\s*[,;]\s*", a)[0] if ";" in a else a
            if t:
                filas.append((a, t))
    else:
        for l in texto.split("\n"):
            if l.strip() and not l.strip().startswith("#"):
                filas.append(_partir(l))
    return [{"n": i + 1, "artista": a, "titulo": t} for i, (a, t) in enumerate(filas) if t]


# ------------------------------------------------------------------ comparación
def _base_titulo(t):
    return rb._clave_titulo(_VERSION.sub(" ", t or ""))


def _indice():
    with rb.lock:
        db = rb.abrir()
        try:
            temas = [{"id": str(c.ID), "artista": c.ArtistName or "", "titulo": c.Title or "",
                      "genero": c.GenreName or "", "anio": c.ReleaseYear or "", "ruta": c.FolderPath or ""}
                     for c in db.get_content()]
        finally:
            db.close()
    for t in temas:
        t["ka"], t["kt"], t["kb"] = rb._clave_artista(t["artista"]), rb._clave_titulo(t["titulo"]), _base_titulo(t["titulo"])
        t["archivo"] = Path(t["ruta"]).name
    return temas


def _art_coincide(a, b):
    if not a or not b:
        return not a          # si la lista no trae artista, alcanza con el título
    pa, pb = set(a.split(" + ")), set(b.split(" + "))
    return bool(pa & pb) or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def comparar(items):
    temas = _indice()
    por_titulo = {}
    for t in temas:
        por_titulo.setdefault(t["kt"], []).append(t)
        por_titulo.setdefault(t["kb"], []).append(t)
    vistos, out = {}, []
    for it in items:
        ka, kt, kb = rb._clave_artista(it["artista"]), rb._clave_titulo(it["titulo"]), _base_titulo(it["titulo"])
        clave = (ka, kt)
        r = {**it, "estado": "falta", "detalle": "No está en la colección", "match": None}
        if clave in vistos:
            r.update(estado="repetido", detalle=f"Repite la línea {vistos[clave]} de la lista")
            out.append(r)
            continue
        vistos[clave] = it["n"]
        exactos = [t for t in por_titulo.get(kt, []) if t["kt"] == kt and _art_coincide(ka, t["ka"])]
        if exactos:
            t = exactos[0]
            r.update(estado="tengo", match=t["id"],
                     detalle=f"{t['archivo']} · {t['anio'] or ''} · {t['genero']}".replace(" ·  · ", " · ").strip(" ·"))
        else:
            # mismo tema en otra versión (remix, en vivo…) o título parecido
            cands = [t for t in por_titulo.get(kb, []) if _art_coincide(ka, t["ka"])]
            if not cands:
                mejores = []
                for t in temas:
                    if not _art_coincide(ka, t["ka"]):
                        continue
                    s = difflib.SequenceMatcher(None, kb, t["kb"]).ratio()
                    if s >= 0.84:
                        mejores.append((s, t))
                cands = [t for _, t in sorted(mejores, key=lambda x: -x[0])[:1]]
            if cands:
                t = cands[0]
                r.update(estado="posible", match=t["id"],
                         detalle=f"Tenés «{t['artista']} - {t['titulo']}». ¿Es el mismo o hay que bajar otra versión?")
        out.append(r)
    return out


# ------------------------------------------------------------------ salida
def guardar_txt(nombre, filas, con_links=True):
    """filas: [{artista, titulo}] que quedan para bajar."""
    seguro = re.sub(r"[^\w\- ]+", "", nombre).strip().replace(" ", "_") or "lista"
    destino = Path(config.cargar()["incorporar"]) / f"{seguro}_depurada.txt"
    lineas = [f"{nombre} — temas para bajar ({len(filas)}) · {datetime.datetime.now():%d/%m/%Y %H:%M}", ""]
    for f in filas:
        q = f"{f['artista']} {f['titulo']}".strip()
        lineas.append(f"{f['artista']} - {f['titulo']}" if f["artista"] else f["titulo"])
        if con_links:
            lineas.append("    " + "  ·  ".join(f"{n}: {u.format(q=quote_plus(q))}" for n, u in TIENDAS))
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return str(destino)


def crear_evento(nombre, ids):
    """Crea (o completa) una playlist con los temas que ya están en la colección."""
    from pyrekordbox.masterdb import models as m
    with rb.lock:
        db = rb.abrir()
        try:
            pl = db.query(m.DjmdPlaylist).filter(m.DjmdPlaylist.Name == nombre,
                                                 m.DjmdPlaylist.Attribute == 0).first()
            if pl is None:
                pl = db.create_playlist(nombre)
            ya = {str(s.ContentID) for s in db.query(m.DjmdSongPlaylist).filter(m.DjmdSongPlaylist.PlaylistID == pl.ID)}
            n = 0
            for cid in ids:
                if str(cid) not in ya and db.get_content(ID=str(cid)) is not None:
                    db.add_to_playlist(pl, str(cid))
                    n += 1
            db.commit()
            return {"id": str(pl.ID), "nombre": nombre, "agregados": n}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
