"""Lectura y escritura de etiquetas en los archivos de audio (mp3, m4a, flac, wav, aiff)."""
import re
from pathlib import Path

from mutagen import File as MFile
from mutagen.aiff import AIFF
from mutagen.id3 import ID3, COMM, TALB, TCON, TDRC, TIT1, TIT2, TPE1
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.wave import WAVE

CAMPOS = ("titulo", "artista", "album", "anio", "genero", "grouping", "comentario")

ID3_MAP = {"titulo": ("TIT2", TIT2), "artista": ("TPE1", TPE1), "album": ("TALB", TALB),
           "anio": ("TDRC", TDRC), "genero": ("TCON", TCON), "grouping": ("TIT1", TIT1)}
MP4_MAP = {"titulo": "\xa9nam", "artista": "\xa9ART", "album": "\xa9alb", "anio": "\xa9day",
           "genero": "\xa9gen", "grouping": "\xa9grp", "comentario": "\xa9cmt"}
VORBIS_MAP = {"titulo": "title", "artista": "artist", "album": "album", "anio": "date",
              "genero": "genre", "grouping": "grouping", "comentario": "comment"}


def leer(ruta):
    r = {k: "" for k in CAMPOS}
    try:
        a = MFile(str(ruta))
    except Exception:
        return r
    if a is None or a.tags is None:
        return r
    t = a.tags
    try:
        if isinstance(t, ID3):
            for k, (f, _) in ID3_MAP.items():
                if f in t and t[f].text:
                    r[k] = str(t[f].text[0])
            for c in t.getall("COMM"):
                if c.desc == "" and c.text:
                    r["comentario"] = str(c.text[0])
                    break
        elif isinstance(a, MP4):
            for k, f in MP4_MAP.items():
                if t.get(f):
                    r[k] = str(t[f][0])
        else:
            for k, f in VORBIS_MAP.items():
                v = t.get(f)
                if v:
                    r[k] = str(v[0])
    except Exception:
        pass
    r["anio"] = (re.match(r"\d{4}", r["anio"] or "") or [""])[0] if r["anio"] else ""
    return r


def escribir(ruta, cambios):
    """cambios: {campo: valor}; valor vacío borra el campo."""
    a = MFile(str(ruta))
    if a is None:
        raise ValueError("formato no soportado")
    if isinstance(a, MP4):
        if a.tags is None:
            a.add_tags()
        for k, v in cambios.items():
            f = MP4_MAP.get(k)
            if not f:
                continue
            if v:
                a.tags[f] = [str(v)]
            elif f in a.tags:
                del a.tags[f]
        a.save()
        return
    if not isinstance(a, (MP3, WAVE, AIFF)):          # flac / ogg
        if a.tags is None:
            a.add_tags()
        for k, v in cambios.items():
            f = VORBIS_MAP.get(k)
            if not f:
                continue
            if v:
                a.tags[f] = [str(v)]
            elif f in a.tags:
                del a.tags[f]
        a.save()
        return
    if a.tags is None:
        a.add_tags()
    t = a.tags
    for k, v in cambios.items():
        if k == "comentario":
            for c in list(t.getall("COMM")):
                if c.desc == "":
                    t.delall(c.HashKey)
            if v:
                t.add(COMM(encoding=3, lang="eng", desc="", text=[str(v)]))
            continue
        if k not in ID3_MAP:
            continue
        f, cls = ID3_MAP[k]
        t.delall(f)
        if v:
            t.add(cls(encoding=3, text=[str(v)]))
    if Path(ruta).suffix.lower() == ".mp3":
        a.save(v2_version=3)
    else:
        a.save()


# ---------------- país e idioma dentro del comentario ----------------
def pais_idioma(comentario):
    p = re.search(r"Pa[ií]s:\s*([^|]+)", comentario or "")
    i = re.search(r"Idioma:\s*([^|]+)", comentario or "")
    return (p.group(1).strip() if p else ""), (i.group(1).strip() if i else "")


def armar_comentario(previo, pais, idioma):
    """Reemplaza país e idioma y conserva cualquier otro texto del comentario."""
    resto = re.sub(r"\s*\|?\s*(Pa[ií]s|Idioma):\s*[^|]*", "", previo or "").strip(" |")
    partes = [p for p in (resto, f"País: {pais}" if pais else "",
                          f"Idioma: {idioma}" if idioma else "") if p]
    return " | ".join(partes)


def caratula(ruta):
    """-> (bytes, mime) de la carátula incrustada, o (None, None)."""
    try:
        a = MFile(str(ruta))
    except Exception:
        return None, None
    if a is None:
        return None, None
    try:
        pics = getattr(a, "pictures", None)
        if pics:
            return pics[0].data, pics[0].mime or "image/jpeg"
        t = a.tags
        if t is None:
            return None, None
        if isinstance(t, ID3):
            ap = t.getall("APIC")
            if ap:
                p = ([x for x in ap if x.type == 3] or ap)[0]
                return p.data, p.mime or "image/jpeg"
        elif isinstance(a, MP4) and t.get("covr"):
            c = t["covr"][0]
            return bytes(c), "image/png" if getattr(c, "imageformat", 13) == 14 else "image/jpeg"
    except Exception:
        pass
    return None, None
