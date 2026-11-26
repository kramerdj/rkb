#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ordenar_coleccion.py  —  KRAMER DJ
Ordena y corrige directamente la metadata de toda la colección de Rekordbox.

Para cada tema busca y escribe:
  - Género amplio (Género) y subgénero (Grouping)
  - Año real: el original (no el del compilado); si es remix, el del remix
  - Álbum original y su carátula (si falta, es chica o cambió el álbum)
  - País del artista e idioma (en Comentarios: "País: Argentina | Idioma: Español")
Fuentes: MusicBrainz, Wikipedia/Wikidata, Cover Art Archive, iTunes, Last.fm
(API key) y Discogs (token, opcional).

Además analiza la calidad real del audio (como Spek, automatizado) y deja
"calidad_no_ok.txt" en la carpeta de la colección.

BACKUP: antes de modificar un archivo, copia el original a
   Documents/backup/_BACKUP originales/   (misma estructura de carpetas)

USO
   python3 ordenar_coleccion.py                 # corre sobre toda la colección
   python3 ordenar_coleccion.py --limite 20     # prueba con 20 temas
   python3 ordenar_coleccion.py --simular       # muestra qué cambiaría, sin tocar nada
   python3 ordenar_coleccion.py --deshacer      # vuelve a poner los originales del backup
   Otras: --sin-calidad, --solo-calidad, --espectros, --carpeta RUTA

IMPORTANTE
   - No renombra ni mueve temas: Rekordbox no pierde cues, grids ni playlists.
   - Los temas que no encuentra en ninguna fuente NO se tocan (quedan listados
     en el registro de cambios).
   - Después: en Rekordbox seleccioná todos los temas -> clic derecho ->
     "Volver a cargar etiqueta".

Requisitos:
   python3 -m pip install --user mutagen requests numpy pillow
"""

import argparse
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import wave
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

_faltan = []
for _mod, _pip in (("requests", "requests"), ("mutagen", "mutagen"), ("numpy", "numpy"),
                   ("PIL", "pillow")):
    try:
        __import__(_mod)
    except ImportError:
        _faltan.append(_pip)
if _faltan:
    raise ImportError("Faltan librerías: " + " ".join(_faltan))

import numpy as np
import requests
from mutagen import File as MFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC, COMM, TALB, TCON, TDRC, TIT1, TLAN
from mutagen.mp4 import MP4, MP4Cover
from mutagen.mp3 import MP3
from mutagen.wave import WAVE
from mutagen.aiff import AIFF
from PIL import Image

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
COLECCION = os.path.expanduser("~/Music")
CARPETA_BACKUP = "_BACKUP originales"     # nombre de la carpeta de backups (el script nunca la analiza)
BACKUP_RAIZ = os.path.expanduser("~/Documents/backup/_BACKUP originales")   # fuera de la colección


def carpeta_backup(coleccion):
    """Backups fuera de la colección. Para otra carpeta, en una subcarpeta con su nombre."""
    raiz = Path(BACKUP_RAIZ)
    try:
        if coleccion.resolve() == Path(COLECCION).expanduser().resolve():
            return raiz
    except Exception:
        pass
    return raiz / coleccion.name

LASTFM_API_KEY = ""     # pegá tu API key de Last.fm entre las comillas
DISCOGS_TOKEN = ""      # opcional: discogs.com/settings/developers -> "Generate new token"

# Calidad: frecuencia de corte real del audio
CALIDAD_OK_KHZ = 19.0      # >= 19 kHz: OK (192 kbps reales o más)
CALIDAD_MALO_KHZ = 17.5    # <  17,5 kHz: MALO (128 kbps o peor). En el medio: DUDOSO

# Artistas con el mismo nombre que otro de otro país: se fuerza el país correcto.
# Clave: nombre del artista en minúscula, sin acentos. Valor: código de país.
ARTISTAS_PAIS = {
    "airbag": "AR",
}

HILOS = 10                 # temas que se procesan en paralelo (siempre hay 10 en curso)
TAM_CARATULA = 600         # px
CARATULA_MINIMA = 300      # carátulas actuales más chicas que esto se reemplazan

CACHE = Path.home() / ".kramer_ordenar_cache.json"
USER_AGENT = "KramerDJ-Ordenador/2.0 ( kramerdj-organizador@example.com )"
EXT_AUDIO = {".mp3", ".flac", ".m4a", ".aac", ".mp4", ".wav", ".aif", ".aiff", ".ogg"}

# =============================================================================
# GÉNEROS: género amplio -> subgénero (va a Grouping) -> etiquetas que lo indican
# Subgénero "" = sólo género amplio. Editá a gusto (claves en minúscula).
# =============================================================================
GENEROS = {
    "House": {
        "": ["house", "chicago house", "vocal house", "piano house", "garage house",
             "soulful house", "jackin house", "acid house", "latin house", "tribal house",
             "french house", "hard house", "lo fi house", "uk garage", "speed garage"],
        "Tech House": ["tech house"],
        "Deep House": ["deep house"],
        "Afro House": ["afro house", "afrohouse", "amapiano"],
        "Melodic House": ["melodic house", "organic house", "melodic house and techno"],
        "Progressive House": ["progressive house"],
        "Bass House": ["bass house"],
        "Disco House": ["disco house", "funky house"],
        "Future House": ["future house", "slap house", "brazilian bass"],
    },
    "Techno": {
        "": ["techno", "detroit techno", "dub techno", "industrial techno", "acid techno",
             "raw techno", "hypnotic techno"],
        "Melodic Techno": ["melodic techno"],
        "Peak Time": ["peak time techno", "peak time driving techno", "big room techno"],
        "Hard Techno": ["hard techno", "hardgroove"],
        "Minimal": ["minimal", "minimal techno", "microhouse"],
    },
    "Electrónica": {
        "": ["electronic", "electronica", "electronic dance music", "dance", "electro",
             "idm", "leftfield", "electroclash"],
        "EDM": ["edm", "big room", "electro house", "complextro", "festival progressive"],
        "Nu Disco": ["nu disco", "indie dance"],
        "Trance": ["trance", "progressive trance", "uplifting trance", "vocal trance",
                   "psytrance", "psy trance", "goa trance", "hard trance"],
        "Drum & Bass": ["drum and bass", "drum n bass", "dnb", "jungle", "liquid funk",
                        "neurofunk"],
        "Dubstep": ["dubstep", "riddim", "brostep"],
        "Downtempo": ["downtempo", "chillout", "chill out", "ambient", "trip hop", "lounge",
                      "chillwave"],
        "Eurodance": ["eurodance", "euro house", "hands up", "italo dance", "eurobeat"],
        "Guaracha": ["guaracha", "aleteo", "zapateo"],
        "Moombahton": ["moombahton"],
        "Breaks": ["breakbeat", "breaks", "big beat"],
        "Synthwave": ["synthwave", "retrowave"],
    },
    "Pop": {
        "": ["pop", "teen pop", "europop", "bubblegum pop", "art pop", "indie pop",
             "power pop", "adult contemporary", "singer songwriter", "cantautor"],
        "Dance Pop": ["dance pop", "electropop", "synth pop", "synthpop"],
        "Pop Latino": ["latin pop", "pop latino", "pop en espanol", "pop en español"],
        "New Wave": ["new wave", "new romantic"],
        "Pop Rock": ["pop rock"],
        "K-Pop": ["k pop", "kpop"],
    },
    "Rock": {
        "": ["rock", "classic rock", "soft rock", "glam rock", "blues rock", "southern rock",
             "arena rock", "psychedelic rock", "progressive rock", "rock and roll", "blues"],
        "Alternativo": ["alternative rock", "alternative", "indie rock", "indie", "britpop",
                        "grunge", "post punk", "garage rock"],
        "Punk": ["punk", "punk rock", "pop punk", "hardcore punk"],
        "Hard Rock": ["hard rock", "heavy metal", "metal", "nu metal"],
        "Ska": ["ska", "ska punk"],
        "Rock en Español": ["rock en espanol", "rock en español", "latin rock", "rock latino"],
    },
    "Rock Nacional": {
        "": ["rock nacional", "rock argentino", "argentine rock", "rock chabon",
             "rock barrial"],
    },
    "Reggaetón": {
        "": ["reggaeton", "reggaetón", "perreo", "neoperreo", "latin urban"],
        "Old School": ["old school reggaeton", "reggaeton old school"],
    },
    "Dembow": {
        "": ["dembow", "dominican dembow", "dembow dominicano"],
    },
    "Urbano": {
        "": ["urbano", "urbano latino", "musica urbana", "latin hip hop"],
        "Hip Hop": ["hip hop", "rap", "boom bap", "gangsta rap", "conscious hip hop",
                    "hip hop rap"],
        "Trap": ["trap", "latin trap", "trap latino", "trap argentino"],
        "Drill": ["drill", "uk drill"],
    },
    "Cumbia": {
        "": ["cumbia", "cumbia argentina", "tropical", "musica tropical", "cumbia colombiana"],
        "Cumbia Villera": ["cumbia villera"],
        "Cumbia Pop": ["cumbia pop", "cumbia cheta"],
        "Santafesina": ["cumbia santafesina"],
        "RKT": ["rkt", "rkt argentino"],
        "Cachengue": ["cachengue"],
        "Cumbia 420": ["cumbia 420"],
        "Sonidera": ["cumbia sonidera", "cumbia mexicana"],
    },
    "Cuarteto": {
        "": ["cuarteto", "cuarteto cordobes"],
    },
    "Latino": {
        "": ["latin", "latin music", "musica latina", "salsa y tropical"],
        "Salsa": ["salsa", "salsa romantica", "timba"],
        "Merengue": ["merengue"],
        "Bachata": ["bachata"],
        "Vallenato": ["vallenato"],
        "Champeta": ["champeta"],
    },
    "Disco / Funk": {
        "": ["disco funk"],
        "Disco": ["disco", "post disco", "hi nrg", "italo disco"],
        "Funk": ["funk", "p funk", "jazz funk", "boogie"],
    },
    "R&B / Soul": {
        "": ["funk soul", "funk and soul"],
        "R&B": ["r and b", "rnb", "contemporary r and b", "rhythm and blues", "new jack swing",
                "r and b soul"],
        "Soul": ["soul", "neo soul", "motown", "northern soul"],
    },
    "Reggae": {
        "": ["reggae", "roots reggae", "lovers rock", "reggae en espanol"],
        "Dancehall": ["dancehall", "ragga"],
        "Dub": ["dub"],
    },
    "Folclore": {
        "": ["folklore", "folclore", "folklore argentino", "argentine folk", "chacarera",
             "zamba", "chamame", "cueca", "folk world and country"],
    },
    "Tango": {
        "": ["tango", "tango nuevo"],
        "Electrotango": ["electrotango", "electronic tango"],
    },
    "Baladas": {
        "": ["ballad", "balada", "latin ballad", "balada romantica", "cancion melodica",
             "romantico"],
        "Bolero": ["bolero"],
    },
    "Jazz": {
        "": ["jazz", "smooth jazz", "swing", "acid jazz", "nu jazz", "latin jazz"],
        "Bossa Nova": ["bossa nova"],
    },
}
LISTA_GENEROS = list(GENEROS.keys())

PAISES = {
    "AR": "Argentina", "UY": "Uruguay", "CL": "Chile", "BR": "Brasil", "PY": "Paraguay",
    "BO": "Bolivia", "PE": "Perú", "CO": "Colombia", "VE": "Venezuela", "EC": "Ecuador",
    "MX": "México", "PR": "Puerto Rico", "DO": "República Dominicana", "CU": "Cuba",
    "PA": "Panamá", "CR": "Costa Rica", "GT": "Guatemala", "US": "Estados Unidos",
    "CA": "Canadá", "GB": "Reino Unido", "XE": "Reino Unido", "IE": "Irlanda",
    "ES": "España", "PT": "Portugal", "FR": "Francia", "IT": "Italia",
    "DE": "Alemania", "NL": "Países Bajos", "BE": "Bélgica", "CH": "Suiza",
    "AT": "Austria", "SE": "Suecia", "NO": "Noruega", "DK": "Dinamarca",
    "FI": "Finlandia", "IS": "Islandia", "PL": "Polonia", "RU": "Rusia",
    "UA": "Ucrania", "GR": "Grecia", "TR": "Turquía", "IL": "Israel",
    "ZA": "Sudáfrica", "NG": "Nigeria", "AU": "Australia", "NZ": "Nueva Zelanda",
    "JP": "Japón", "KR": "Corea del Sur", "CN": "China", "IN": "India",
    "JM": "Jamaica", "RO": "Rumania", "CZ": "República Checa", "HU": "Hungría",
}
HISPANOS = {"Argentina", "Uruguay", "Chile", "Paraguay", "Bolivia", "Perú", "Colombia",
            "Venezuela", "Ecuador", "México", "Puerto Rico", "República Dominicana", "Cuba",
            "Panamá", "Costa Rica", "Guatemala", "España"}
ANGLO = {"Estados Unidos", "Reino Unido", "Irlanda", "Canadá", "Australia",
         "Nueva Zelanda", "Jamaica", "Sudáfrica"}

IDIOMAS_ISO = {"spa": "Español", "eng": "Inglés", "por": "Portugués", "ita": "Italiano",
               "fra": "Francés", "deu": "Alemán", "zxx": "Instrumental",
               "mul": "Multilingüe", "jpn": "Japonés", "kor": "Coreano", "cat": "Catalán",
               "nld": "Neerlandés", "swe": "Sueco", "rus": "Ruso", "heb": "Hebreo"}
IDIOMA_A_ISO = {v: k for k, v in IDIOMAS_ISO.items()}

# =============================================================================
# TEXTO
# =============================================================================
BASURA = re.compile(
    r"(official\s*(music\s*)?video|official\s*audio|official\s*visuali[sz]er|"
    r"lyric(s)?\s*video|video\s*oficial|audio\s*oficial|videoclip|\bhq\b|\bhd\b|\b4k\b|"
    r"\d{3}\s*kbps|free\s*download|\bletra\b|visuali[sz]er|www\.|youtube)", re.I)
RE_COMPILADO = re.compile(r"greatest|hits|best of|grandes [eé]xitos|lo mejor|collection|"
                          r"colecci[oó]n|antolog|essentials|esenciales|now that|"
                          r"\bmix\b|ministry|cafe del mar|compilation", re.I)


def sin_acentos(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def norm_texto(s):
    s = sin_acentos(s).lower().replace("&", " and ").replace("$", "s")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def similitud(a, b):
    return difflib.SequenceMatcher(None, norm_texto(a), norm_texto(b)).ratio()


def anio_de(s):
    m = re.search(r"(1[89]\d{2}|20\d{2})", str(s or ""))
    if m and 1900 <= int(m.group(1)) <= datetime.now().year:
        return int(m.group(1))
    return None


def limpiar_titulo(t):
    if not t:
        return ""
    t = re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]",
               lambda m: "" if BASURA.search(m.group(0)) else m.group(0), t)
    t = re.sub(r"^\s*\d{1,3}\s*[\.\-_\)]\s*", "", t)
    t = t.replace("_", " ")
    return re.sub(r"\s+", " ", t).strip(" -–_.")


RE_EDICION = re.compile(
    r"\s*[\(\[](?:[^\)\]]*\b(?:bonus track|deluxe|remaster(?:ed)?|expanded|edition|edici[oó]n|"
    r"anniversary|aniversario|version|versi[oó]n|reissue|special|super|collector|legacy)\b"
    r"[^\)\]]*)[\)\]]", re.I)


def limpiar_album(a):
    if not a:
        return ""
    limpio = RE_EDICION.sub("", a)
    limpio = re.sub(r"\s+-\s+(remaster(ed)?|deluxe|expanded).*$", "", limpio, flags=re.I)
    return re.sub(r"\s+", " ", limpio).strip() or a


def partir_nombre_archivo(stem):
    s = limpiar_titulo(stem)
    partes = re.split(r"\s+[\-–—]\s+", s, maxsplit=1)
    return (partes[0].strip(), partes[1].strip()) if len(partes) == 2 else ("", s)


SEP_ARTISTAS = re.compile(r"\s*(?:,|&|\+|/|;|\bx\b|\band\b|\by\b|\bfeat\.?|\bft\.?|"
                          r"\bfeaturing\b|\bvs\.?|\bwith\b|\bcon\b)\s*", re.I)


def partes_artista(a):
    return [p.strip() for p in SEP_ARTISTAS.split(a or "") if p and p.strip()]


def artistas_coinciden(nuestros, de_fuente):
    ns = {norm_texto(x) for x in nuestros if norm_texto(x)}
    fs = {norm_texto(x) for x in de_fuente if norm_texto(x)}
    if not ns or not fs:
        return False
    if ns & fs:
        return True
    return any(difflib.SequenceMatcher(None, a, b).ratio() >= 0.88 for a in ns for b in fs)


PAL_REMIX = re.compile(r"\b(remix|rmx|dub mix|bootleg|rework|re ?edit|edit|vip|mashup|flip|remake|"
                       r"version|versi[oó]n|refix|cover)\b", re.I)
PAL_VIVO = re.compile(r"\b(live|en vivo|vivo|acoustic|ac[uú]stico|unplugged|session)\b", re.I)
PAL_IGUAL = re.compile(r"^\s*(original|extended|radio|club|album|single|main|clean|explicit|"
                       r"dirty|short|full|intro|instrumental|remaster(ed)?|\d{4}\s*remaster"
                       r"(ed)?|remastered\s*\d{4}|mono|stereo)\b.*$", re.I)
GENERICAS_VERSION = {"remix", "rmx", "edit", "mix", "extended", "radio", "original", "version",
                     "bootleg", "rework", "vip", "club", "dub", "re", "the", "feat", "ft",
                     "mashup", "flip", "remake", "refix", "reedit", "cover", "version", "and",
                     "x", "de", "del", "la", "el", "short", "long"}


def separar_version(titulo):
    """-> (titulo_base, texto_version, tipo)  tipo: original | remix | vivo"""
    t = titulo or ""
    grupos = re.findall(r"[\(\[]([^\)\]]*)[\)\]]", t)
    m = re.search(r"\s[\-–]\s+([^\-–]+)$", t)
    sufijo = m.group(1) if m else ""
    tipo, version, quitar = "original", "", []
    for g in grupos + ([sufijo] if sufijo else []):
        gl = sin_acentos(g).lower()
        if re.match(r"^\s*(feat|ft|featuring|with|con)\b", gl):
            quitar.append(g)
        elif PAL_IGUAL.match(gl) and not re.search(r"remix|rmx|bootleg|rework|vip|mashup", gl):
            quitar.append(g)
        elif PAL_REMIX.search(gl) and "radio edit" not in gl:
            quitar.append(g)
            tipo, version = "remix", g
        elif PAL_VIVO.search(gl):
            quitar.append(g)
            if tipo == "original":
                tipo, version = "vivo", g
        elif BASURA.search(g):
            quitar.append(g)
    base = t
    for g in quitar:
        base = base.replace(f"({g})", " ").replace(f"[{g}]", " ")
        if g == sufijo:
            base = re.sub(r"\s[\-–]\s+" + re.escape(g) + r"$", " ", base)
    base = re.sub(r"\s(feat|ft|featuring)\.?\s.*$", " ", base, flags=re.I)
    base = re.sub(r"\s+", " ", base).strip(" -–")
    return base or t, version, tipo


def palabras_version(version):
    return [w for w in norm_texto(version).split() if w not in GENERICAS_VERSION and len(w) > 1]

# =============================================================================
# GÉNERO: mapeo de etiquetas
# =============================================================================
def norm_tag(t):
    t = sin_acentos(t).lower().replace("&", " and ")
    t = re.sub(r"[-_/,.!]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


MAPA = {}
for _g, _subs in GENEROS.items():
    for _s, _tags in _subs.items():
        for _t in _tags:
            MAPA.setdefault(norm_tag(_t), (_g, _s))
_CLAVES_LARGAS = sorted(MAPA, key=len, reverse=True)


def mapear(tag):
    """-> (género, subgénero, factor) o None"""
    t = norm_tag(tag)
    if not t:
        return None
    if t in MAPA:
        return MAPA[t] + (1.0,)
    for k in _CLAVES_LARGAS:
        if len(k) >= 4 and re.search(r"\b" + re.escape(k) + r"\b", t):
            return MAPA[k] + (0.7,)
    return None


class Votos:
    def __init__(self):
        self.c = Counter()
        self.fuentes = defaultdict(set)

    def sumar(self, tag, peso, fuente):
        m = mapear(tag)
        if not m or peso <= 0:
            return
        g, s, f = m
        self.c[(g, s)] += peso * f * (1.0 if s else 0.6)
        self.fuentes[g].add(fuente)

    def resultado(self):
        if not self.c:
            return "", "", 0.0, ""
        por_g = Counter()
        for (g, _s), p in self.c.items():
            por_g[g] += p
        g, pg = por_g.most_common(1)[0]
        subs = Counter({s: p for (gg, s), p in self.c.items() if gg == g and s})
        sub = ""
        if subs:
            s, ps = subs.most_common(1)[0]
            if ps >= 0.25 * pg:
                sub = s
        return g, sub, pg / sum(por_g.values()), ", ".join(sorted(self.fuentes[g]))

# =============================================================================
# TAGS
# =============================================================================
def leer_tags(path):
    r = {"artist": "", "title": "", "album": "", "year": "", "genre": "", "grouping": "",
         "comment": "", "language": "", "cover": None, "duration": 0.0, "bitrate": 0,
         "sample_rate": 44100}
    try:
        a = MFile(str(path))
    except Exception:
        return r
    if a is None:
        return r
    info = getattr(a, "info", None)
    if info:
        r["duration"] = float(getattr(info, "length", 0) or 0)
        r["bitrate"] = int(getattr(info, "bitrate", 0) or 0)
        r["sample_rate"] = int(getattr(info, "sample_rate", 44100) or 44100)
    t = a.tags
    try:
        if isinstance(a, FLAC):
            if a.pictures:
                r["cover"] = a.pictures[0].data
        if t is None:
            return r
        if isinstance(t, ID3):
            for k, f in (("artist", "TPE1"), ("title", "TIT2"), ("album", "TALB"),
                         ("year", "TDRC"), ("genre", "TCON"), ("grouping", "TIT1"),
                         ("language", "TLAN")):
                if f in t and t[f].text:
                    r[k] = str(t[f].text[0])
            for c in t.getall("COMM"):
                if c.desc == "" and c.text:
                    r["comment"] = str(c.text[0])
                    break
            pics = t.getall("APIC")
            if pics:
                front = [p for p in pics if p.type == 3] or pics
                r["cover"] = front[0].data
        elif isinstance(a, MP4):
            for k, f in (("artist", "\xa9ART"), ("title", "\xa9nam"), ("album", "\xa9alb"),
                         ("year", "\xa9day"), ("genre", "\xa9gen"), ("grouping", "\xa9grp"),
                         ("comment", "\xa9cmt")):
                if t.get(f):
                    r[k] = str(t[f][0])
            if t.get("covr"):
                r["cover"] = bytes(t["covr"][0])
        else:
            for k, f in (("artist", "artist"), ("title", "title"), ("album", "album"),
                         ("year", "date"), ("genre", "genre"), ("grouping", "grouping"),
                         ("comment", "comment"), ("language", "language")):
                v = t.get(f)
                if v:
                    r[k] = str(v[0])
    except Exception:
        pass
    return r


def tam_imagen(data):
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


def escribir_tags(path, cambios, caratula=None):
    """cambios: genre, grouping, year, album, comment, language (ISO-639-2)"""
    a = MFile(str(path))
    if a is None:
        raise ValueError("formato no soportado")
    if isinstance(a, MP4):
        t = a.tags if a.tags is not None else (a.add_tags() or a.tags)
        mp = {"genre": "\xa9gen", "grouping": "\xa9grp", "year": "\xa9day",
              "album": "\xa9alb", "comment": "\xa9cmt"}
        for k, v in cambios.items():
            if k in mp:
                if v:
                    t[mp[k]] = [str(v)]
                elif mp[k] in t:
                    del t[mp[k]]
        if caratula:
            t["covr"] = [MP4Cover(caratula, imageformat=MP4Cover.FORMAT_JPEG)]
        a.save()
        return
    if not isinstance(a, (MP3, WAVE, AIFF)):                 # flac / ogg
        if a.tags is None:
            a.add_tags()
        mp = {"genre": "genre", "grouping": "grouping", "year": "date", "album": "album",
              "comment": "comment", "language": "language"}
        for k, v in cambios.items():
            if v:
                a.tags[mp[k]] = [str(v)]
            elif mp[k] in a.tags:
                del a.tags[mp[k]]
        if caratula and isinstance(a, FLAC):
            a.clear_pictures()
            p = Picture()
            p.type, p.mime, p.data = 3, "image/jpeg", caratula
            a.add_picture(p)
        a.save()
        return
    # ID3: mp3, wav, aiff
    if a.tags is None:
        a.add_tags()
    t = a.tags
    clases = {"genre": ("TCON", TCON), "grouping": ("TIT1", TIT1), "year": ("TDRC", TDRC),
              "album": ("TALB", TALB), "language": ("TLAN", TLAN)}
    for k, v in cambios.items():
        if k == "comment":
            for c in list(t.getall("COMM")):
                if c.desc == "":
                    t.delall(c.HashKey)
            if v:
                t.add(COMM(encoding=3, lang="eng", desc="", text=[str(v)]))
            continue
        f, cls = clases[k]
        t.delall(f)
        if v:
            t.add(cls(encoding=3, text=[str(v)]))
    if caratula:
        t.delall("APIC")
        t.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=caratula))
    if Path(path).suffix.lower() == ".mp3":
        a.save(v2_version=3)
    else:
        a.save()


def armar_comentario(previo, pais, idioma):
    """Conserva el texto previo; si no hay país/idioma nuevo, mantiene el que ya tenía."""
    viejo_pais = re.search(r"Pa[ií]s:\s*([^|]+)", previo or "")
    viejo_idioma = re.search(r"Idioma:\s*([^|]+)", previo or "")
    pais = pais or (viejo_pais.group(1).strip() if viejo_pais else "")
    idioma = idioma or (viejo_idioma.group(1).strip() if viejo_idioma else "")
    resto = re.sub(r"\s*\|?\s*(Pa[ií]s|Idioma):\s*[^|]*", "", previo or "").strip(" |")
    partes = [p for p in (resto,
                          f"País: {pais}" if pais else "",
                          f"Idioma: {idioma}" if idioma else "") if p]
    return " | ".join(partes)

# =============================================================================
# CALIDAD DE AUDIO (frecuencia de corte, como Spek)
# =============================================================================
def decodificar(path, sr_info, duracion, segundos=90):
    inicio = max(0.0, duracion / 2 - segundos / 2) if duracion else 0.0
    if shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{inicio:.1f}", "-t", str(segundos),
               "-i", str(path), "-ac", "1", "-f", "s16le", "-acodec", "pcm_s16le", "-"]
        raw = subprocess.run(cmd, capture_output=True, timeout=300).stdout
        return np.frombuffer(raw, np.int16).astype(np.float32) / 32768, sr_info
    if shutil.which("afconvert"):                         # viene con macOS
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "a.wav")
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", str(path), out],
                           capture_output=True, timeout=600)
            with wave.open(out) as w:
                sr, ch = w.getframerate(), w.getnchannels()
                w.setpos(min(int(inicio * sr), max(0, w.getnframes() - 1)))
                raw = w.readframes(int(segundos * sr))
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
        if ch > 1:
            x = x[: len(x) // ch * ch].reshape(-1, ch).mean(1)
        return x, sr
    raise RuntimeError("no hay decodificador (ffmpeg / afconvert)")


def espectro(x, sr, n=4096):
    nfr = len(x) // n
    if nfr < 8:
        return None, None
    fr = x[: nfr * n].reshape(nfr, n)
    rms = np.sqrt((fr ** 2).mean(1))
    sel = fr[rms >= np.percentile(rms, 50)]
    p = (np.abs(np.fft.rfft(sel * np.hanning(n), axis=1)) ** 2).mean(0)
    return np.fft.rfftfreq(n, 1 / sr), 10 * np.log10(p + 1e-20)


def frecuencia_corte(f, d):
    """Busca el 'acantilado' típico de la compresión: caída brusca de >18 dB en ~300 Hz."""
    bw = f[1]
    a, b = max(1, int(60 / bw)), int(400 / bw)
    for i in range(len(f) - b - 1, int(10000 / bw), -1):
        abajo = d[i - b:i - a].mean()
        cerca = d[i + a:i + b].mean()
        arriba = d[i + a:].mean()
        if abajo - cerca > 18 and abajo - arriba > 18:
            return f[i] / 1000
    return f[-1] / 1000


def analizar_calidad(path, tags, carpeta_espectros=None):
    try:
        x, sr = decodificar(path, tags["sample_rate"], tags["duration"])
        f, d = espectro(x, sr)
        if f is None:
            return {"estado": "ERROR", "corte": None, "nota": "audio muy corto"}
        c = frecuencia_corte(f, d)
        estado = "OK" if c >= CALIDAD_OK_KHZ else ("DUDOSO" if c >= CALIDAD_MALO_KHZ else "MALO")
        res = {"estado": estado, "corte": round(c, 1), "nota": ""}
        if estado != "OK" and carpeta_espectros:
            guardar_espectro(x, sr, c, path, carpeta_espectros)
        return res
    except Exception as e:
        return {"estado": "ERROR", "corte": None, "nota": str(e)[:80]}


def guardar_espectro(x, sr, corte, path, carpeta):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    carpeta.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.specgram(x, NFFT=2048, Fs=sr, noverlap=1024, cmap="magma", vmin=-120)
    ax.axhline(corte * 1000, color="cyan", lw=1, ls="--")
    ax.set_title(f"{Path(path).name}  —  corte {corte:.1f} kHz", fontsize=9)
    ax.set_ylabel("Hz")
    fig.tight_layout()
    fig.savefig(carpeta / (Path(path).stem[:120] + ".png"), dpi=80)
    plt.close(fig)

# =============================================================================
# FUENTES ONLINE
# =============================================================================
MB = "https://musicbrainz.org/ws/2/"
WD = "https://www.wikidata.org/w/api.php"
PAUSAS = {"mb": 1.1, "discogs": 1.1, "lastfm": 0.25, "wd": 0.2, "itunes": 3.2, "img": 0.3}


class Fuentes:
    def __init__(self, lastfm_key, discogs_token, offline=False):
        self.lastfm_key, self.discogs_token, self.offline = lastfm_key, discogs_token, offline
        self._local = threading.local()
        self.ultimo = defaultdict(float)
        self.locks = defaultdict(threading.Lock)
        self.lock_cache = threading.Lock()
        self.caidas = Counter()            # fuentes que no responden se dejan de consultar
        try:
            self.cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
        except Exception:
            self.cache = {}

    @property
    def s(self):
        if not hasattr(self._local, "s"):
            self._local.s = requests.Session()
            self._local.s.headers["User-Agent"] = USER_AGENT
        return self._local.s

    def guardar(self):
        try:
            with self.lock_cache:
                texto = json.dumps(self.cache)
            CACHE.write_text(texto)
        except Exception:
            pass

    def _esperar(self, fuente):
        """Respeta el límite de consultas por segundo de cada fuente (entre todos los hilos)."""
        with self.locks[fuente]:
            espera = PAUSAS.get(fuente, 0.5) - (time.time() - self.ultimo[fuente])
            if espera > 0:
                time.sleep(espera)
            self.ultimo[fuente] = time.time()

    def get(self, fuente, url, params=None):
        if self.offline:
            return None
        params = params or {}
        limpio = {k: v for k, v in params.items() if k not in ("token", "api_key")}
        ck = f"{fuente}|{url}|{json.dumps(limpio, sort_keys=True)}"
        if ck in self.cache:
            return self.cache[ck]
        if self.caidas[fuente] >= 8:       # la fuente está saturada: esperar y reintentar
            with self.locks["pausa_" + fuente]:
                if self.caidas[fuente] >= 8:
                    print(f"   (aviso: {fuente} está saturada, espero 45 s y sigo)")
                    time.sleep(45)
                    self.caidas[fuente] = 4
        data, ok = None, False
        for intento in range(2):
            self._esperar(fuente)
            try:
                r = self.s.get(url, params=params, timeout=(5, 12))
                if r.status_code in (429, 503):
                    time.sleep(3 * (intento + 1))
                    continue
                if r.status_code == 404:
                    data, ok = {}, True
                elif r.ok:
                    data, ok = r.json(), True
                break
            except Exception:
                pass
        if ok:
            self.caidas[fuente] = 0
            with self.lock_cache:
                self.cache[ck] = data
        else:
            self.caidas[fuente] += 1
        return data

    def descargar_imagen(self, url, destino):
        if self.offline or not url:
            return False
        if destino.exists():
            return True
        self._esperar("img")
        try:
            r = self.s.get(url, timeout=(5, 15), allow_redirects=True)
            if not r.ok or len(r.content) < 2000:
                return False
            with Image.open(io.BytesIO(r.content)) as im:
                im = im.convert("RGB")
                im.thumbnail((TAM_CARATULA, TAM_CARATULA))
                destino.parent.mkdir(parents=True, exist_ok=True)
                im.save(destino, "JPEG", quality=90, progressive=False)
            return True
        except Exception:
            return False

    # ---------------- MusicBrainz ----------------
    def mb_grabaciones(self, artista, titulo):
        esc = lambda s: (s or "").replace('"', "").replace("\\", "")
        q = f'recording:"{esc(titulo)}"' + (f' AND artist:"{esc(artista)}"' if artista else "")
        d = self.get("mb", MB + "recording/", {"query": q, "fmt": "json", "limit": 25})
        return (d or {}).get("recordings", []) or []

    def mb_artista(self, mbid):
        if not mbid:
            return {}
        return self.get("mb", MB + f"artist/{mbid}",
                        {"fmt": "json", "inc": "url-rels+genres+tags"}) or {}

    def mb_buscar_artista(self, nombre):
        d = self.get("mb", MB + "artist/",
                     {"query": f'artist:"{nombre.replace(chr(34), "")}"', "fmt": "json",
                      "limit": 5})
        for a in (d or {}).get("artists", []) or []:
            if int(a.get("score", 0)) >= 90 and similitud(a.get("name", ""), nombre) >= 0.9:
                return a.get("id", "")
        return ""

    def mb_release_group(self, rgid):
        if not rgid:
            return {}
        return self.get("mb", MB + f"release-group/{rgid}",
                        {"fmt": "json", "inc": "genres+tags"}) or {}

    def mb_release(self, relid):
        if not relid:
            return {}
        return self.get("mb", MB + f"release/{relid}", {"fmt": "json"}) or {}

    # ---------------- Wikidata ----------------
    def wd_entidades(self, ids, props="claims"):
        out = {}
        ids = sorted({i for i in ids if i})
        for k in range(0, len(ids), 50):
            d = self.get("wd", WD, {"action": "wbgetentities", "ids": "|".join(ids[k:k + 50]),
                                    "props": props, "languages": "es|en", "format": "json"})
            out.update((d or {}).get("entities", {}) or {})
        return out

    def wd_etiquetas(self, ids):
        ents = self.wd_entidades(ids, "labels")
        res = {}
        for q, e in ents.items():
            lab = e.get("labels", {}) or {}
            res[q] = ((lab.get("en") or {}).get("value", ""), (lab.get("es") or {}).get("value", ""))
        return res

    def wd_cancion(self, titulo, artista_qid):
        if not artista_qid or not titulo:
            return {}
        d = self.get("wd", WD, {"action": "wbsearchentities", "search": titulo,
                                "language": "en", "type": "item", "limit": 10,
                                "format": "json"})
        ids = [x.get("id") for x in (d or {}).get("search", []) or []]
        ents = self.wd_entidades(ids)
        for q in ids:
            e = ents.get(q, {})
            if artista_qid in wd_items(e, "P175"):
                return e
        return {}

    # ---------------- otros ----------------
    def discogs_masters(self, artista, titulo):
        if not self.discogs_token:
            return []
        d = self.get("discogs", "https://api.discogs.com/database/search",
                     {"type": "master", "artist": artista, "track": titulo, "per_page": 20,
                      "token": self.discogs_token})
        return (d or {}).get("results", []) or []

    def lastfm_tags(self, artista, titulo=None):
        if not self.lastfm_key or not artista:
            return []
        p = {"api_key": self.lastfm_key, "format": "json", "autocorrect": 1, "artist": artista}
        if titulo:
            p.update(method="track.gettoptags", track=titulo)
        else:
            p.update(method="artist.gettoptags")
        d = self.get("lastfm", "https://ws.audioscrobbler.com/2.0/", p)
        lista = ((d or {}).get("toptags") or {}).get("tag") or []
        if isinstance(lista, dict):
            lista = [lista]
        out = []
        for tg in lista[:8]:
            try:
                out.append((tg["name"], int(tg.get("count", 0)) / 100.0))
            except Exception:
                pass
        return out

    def itunes(self, artista, titulo):
        res = []
        for pais in ("US", "AR"):
            d = self.get("itunes", "https://itunes.apple.com/search",
                         {"term": f"{artista} {titulo}", "entity": "song", "limit": 15,
                          "country": pais})
            res = (d or {}).get("results", []) or []
            if any(artistas_coinciden(partes_artista(artista), partes_artista(r.get("artistName", "")))
                   for r in res):
                break
        return res


def wd_items(ent, prop):
    out = []
    for c in (ent or {}).get("claims", {}).get(prop, []) or []:
        try:
            out.append(c["mainsnak"]["datavalue"]["value"]["id"])
        except Exception:
            pass
    return out


def wd_anios(ent, prop="P577"):
    out = []
    for c in (ent or {}).get("claims", {}).get(prop, []) or []:
        try:
            y = anio_de(c["mainsnak"]["datavalue"]["value"]["time"][1:5])
            if y:
                out.append(y)
        except Exception:
            pass
    return out

# =============================================================================
# ANÁLISIS DE UN TEMA
# =============================================================================
SEC_MALAS = {"Compilation", "Live", "Soundtrack", "DJ-mix", "Mixtape/Street", "Demo",
             "Interview", "Spokenword", "Audiobook"}

STOP = {
    "Español": {"el", "la", "los", "las", "de", "que", "y", "mi", "tu", "te", "me", "no", "en",
                "un", "una", "por", "para", "con", "amor", "corazon", "quiero", "noche", "vida"},
    "Inglés": {"the", "you", "me", "my", "your", "love", "i", "it", "is", "on", "in", "of",
               "to", "and", "be", "night", "baby", "don't", "dont", "we", "all"},
    "Portugués": {"o", "os", "voce", "não", "nao", "meu", "minha", "eu", "pra", "coração",
                  "saudade", "do", "da"},
    "Italiano": {"il", "di", "che", "non", "sei", "per", "amore", "ti", "una", "mio"},
}


def idioma_por_titulo(titulo):
    palabras = set(norm_texto(titulo).split())
    puntos = {k: len(palabras & {norm_texto(w) for w in v}) for k, v in STOP.items()}
    mejor = max(puntos, key=puntos.get)
    orden = sorted(puntos.values(), reverse=True)
    return mejor if orden[0] >= 2 and orden[0] > orden[1] else ""


def id_artista(rec):
    for c in rec.get("artist-credit", []) or []:
        if isinstance(c, dict) and (c.get("artist") or {}).get("id"):
            return c["artist"]["id"]
    return ""


def elegir_artista(F, match, principal, comentario):
    """Si hay varios artistas con el mismo nombre, elige el correcto y descarta los otros.
    Prioridad: ARTISTAS_PAIS > país que ya figuraba en Comentarios > Argentina > el más frecuente."""
    ids = Counter(id_artista(r) for r in match if id_artista(r))
    if not ids:
        return match, ""
    forzado = ARTISTAS_PAIS.get(norm_texto(principal), "")
    m = re.search(r"Pa[ií]s:\s*([^|]+)", comentario or "")
    previo = ""
    if m:
        nombre = m.group(1).strip()
        previo = next((c for c, n in PAISES.items() if n == nombre), "")
    if len(ids) == 1 and not forzado:
        return match, next(iter(ids))
    pais_de = {i: (F.mb_artista(i).get("country") or "") for i in ids}
    elegido = ""
    for pref in (forzado, previo, "AR"):
        if pref:
            cands = [i for i in ids if pais_de[i] == pref]
            if cands:
                elegido = max(cands, key=lambda i: ids[i])
                break
            if pref == forzado:          # país forzado y no está: no usar a los homónimos
                return [], ""
    if not elegido:
        elegido = ids.most_common(1)[0][0]
    return [r for r in match if id_artista(r) == elegido], elegido


def analizar_tema(path, F, tags):
    notas, fuentes_usadas = [], set()
    fa, ft = partir_nombre_archivo(path.stem)
    artista = (tags["artist"] or fa).strip()
    titulo = limpiar_titulo(tags["title"] or ft)
    base, version, tipo = separar_version(titulo)
    artistas = partes_artista(artista)
    principal = artistas[0] if artistas else artista
    vpal = palabras_version(version)
    votos = Votos()
    if tags["genre"]:
        for p in re.split(r"\s*[/,;]\s*", tags["genre"]):
            votos.sumar(p, 1.0, "tag actual")
    if tags["grouping"]:
        votos.sumar(tags["grouping"], 1.0, "tag actual")

    res = {"artista": artista, "titulo": titulo, "tipo": tipo, "version": version,
           "anio": None, "album": "", "rgid": "", "pais": "", "idioma": "",
           "url_caratula": [], "fuentes": "", "notas": ""}
    if F.offline:
        g, s, conf, _ = votos.resultado()
        res.update(genero=g, sub=s, conf_genero=conf, confianza="BAJA")
        return res

    # ---------- MusicBrainz: grabaciones ----------
    busqueda = base if tipo == "original" else f"{base}"
    recs = F.mb_grabaciones(principal, busqueda)
    match = []
    for rec in recs:
        if int(rec.get("score", 0)) < 70:
            continue
        rb, rv, rt = separar_version(rec.get("title", ""))
        if similitud(rb, base) < 0.85:
            continue
        cred = []
        for c in rec.get("artist-credit", []) or []:
            if isinstance(c, dict):
                cred += partes_artista(c.get("name", ""))
        if artistas and not artistas_coinciden(artistas, cred):
            continue
        dis = rec.get("disambiguation", "") or ""
        if tipo == "original":
            if rt != "original" or re.search(r"\blive\b|en vivo|remix|demo|karaoke", dis, re.I):
                continue
        else:
            if rt == "original":
                continue
            if vpal and not all(w in norm_texto(rv) for w in vpal):
                continue
        match.append(rec)
    match, art_id = elegir_artista(F, match, principal, tags["comment"])
    if match:
        fuentes_usadas.add("MusicBrainz")

    anios = []
    for rec in match:
        y = anio_de(rec.get("first-release-date"))
        if y:
            anios.append(y)
        for tg in rec.get("tags", []) or []:
            votos.sumar(tg.get("name", ""), min(int(tg.get("count", 1) or 1), 3), "MusicBrainz")

    # ---------- lanzamientos: álbum original ----------
    cands = []
    for rec in match:
        for rel in rec.get("releases", []) or []:
            rg = rel.get("release-group") or {}
            if (rel.get("status") or "Official") != "Official":
                continue
            sec = set(rg.get("secondary-types") or [])
            malas = SEC_MALAS | ({"Remix"} if tipo == "original" else set())
            if rg.get("primary-type") not in ("Album", "Single", "EP") or sec & malas:
                continue
            fecha = rel.get("date") or ""
            if not anio_de(fecha):
                continue
            if rg.get("primary-type") in ("Single", "EP"):
                tit_rg, _, _ = separar_version(rg.get("title") or rel.get("title", ""))
                if similitud(tit_rg, base) < 0.75 and norm_texto(base) not in norm_texto(tit_rg):
                    continue                  # p.ej. el tema fue lado B de otro single
            cands.append({"fecha": fecha, "titulo": rg.get("title") or rel.get("title", ""),
                          "rgid": rg.get("id", ""), "relid": rel.get("id", ""),
                          "tipo": rg.get("primary-type")})
    cands.sort(key=lambda c: c["fecha"])
    elegido = None
    if cands:
        primero = cands[0]
        anios.append(anio_de(primero["fecha"]))
        elegido = dict(primero)
        if primero["tipo"] == "Single":
            y0 = anio_de(primero["fecha"])
            albumes = [c for c in cands if c["tipo"] == "Album" and anio_de(c["fecha"]) <= y0 + 1]
            if albumes:
                elegido = dict(albumes[0])
            else:
                elegido["titulo"] = f"{primero['titulo']} - Single"
        res["album"], res["rgid"] = limpiar_album(elegido["titulo"]), elegido["rgid"]
        rgd = F.mb_release_group(elegido["rgid"]) if sum(votos.c.values()) < 4 else {}
        for gname in rgd.get("genres", []) or []:
            votos.sumar(gname.get("name", ""), 2.0, "MusicBrainz")
        for tg in rgd.get("tags", []) or []:
            votos.sumar(tg.get("name", ""), 0.75, "MusicBrainz")
        res["url_caratula"].append(
            f"https://coverartarchive.org/release-group/{elegido['rgid']}/front-500")

    # ---------- artista: país, géneros, Wikidata ----------
    if not art_id and principal and not match:
        art_id = F.mb_buscar_artista(principal)
    art = F.mb_artista(art_id)
    cod = art.get("country") or ""
    area = art.get("area") or {}
    if cod in PAISES:
        res["pais"] = PAISES[cod]
    elif (area.get("iso-3166-1-codes") or [""])[0] in PAISES:
        res["pais"] = PAISES[area["iso-3166-1-codes"][0]]
    for gname in art.get("genres", []) or []:
        votos.sumar(gname.get("name", ""), 1.5, "MusicBrainz")
    qid = ""
    for rel in art.get("relations", []) or []:
        url = (rel.get("url") or {}).get("resource", "")
        m = re.search(r"wikidata\.org/wiki/(Q\d+)", url)
        if m:
            qid = m.group(1)
            break
    if qid:
        ent_art = F.wd_entidades([qid]).get(qid, {})
        cancion = F.wd_cancion(base, qid)
        gen_ids = wd_items(ent_art, "P136")
        gen_song = wd_items(cancion, "P136")
        lang_ids = wd_items(cancion, "P407")
        pais_ids = [] if res["pais"] else (wd_items(ent_art, "P495") or wd_items(ent_art, "P27"))
        etiquetas = F.wd_etiquetas(gen_ids + gen_song + lang_ids + pais_ids[:1])
        for g in gen_ids:
            for lab in etiquetas.get(g, ("", "")):
                if mapear(lab):
                    votos.sumar(lab, 1.5, "Wikipedia")
                    break
        for g in gen_song:
            for lab in etiquetas.get(g, ("", "")):
                if mapear(lab):
                    votos.sumar(lab, 3.0, "Wikipedia")
                    break
        if cancion:
            fuentes_usadas.add("Wikipedia")
            if tipo == "original":
                anios += wd_anios(cancion)
        if lang_ids and not res["idioma"]:
            en, es = etiquetas.get(lang_ids[0], ("", ""))
            res["idioma"] = (es or en).capitalize()
        if pais_ids and not res["pais"]:
            res["pais"] = etiquetas.get(pais_ids[0], ("", ""))[1] or ""

    # ---------- Discogs ----------
    if F.discogs_token:
        for it in F.discogs_masters(principal, base):
            tit = it.get("title", "")
            if " - " in tit and not artistas_coinciden(artistas, partes_artista(tit.split(" - ")[0])):
                continue
            fuentes_usadas.add("Discogs")
            if tipo == "original":
                y = anio_de(it.get("year"))
                if y:
                    anios.append(y)
            for s in it.get("style", []) or []:
                votos.sumar(s, 2.0, "Discogs")
            for g in it.get("genre", []) or []:
                votos.sumar(g, 0.5, "Discogs")

    # ---------- Last.fm ----------
    for name, peso in F.lastfm_tags(principal, base if tipo == "original" else titulo):
        votos.sumar(name, 2.0 * peso, "Last.fm")
    for name, peso in F.lastfm_tags(principal):
        votos.sumar(name, 1.0 * peso, "Last.fm")

    # ---------- iTunes (respaldo: álbum, año, carátula, género) ----------
    if not res["album"] or not anios or not res["rgid"]:
        for it in F.itunes(principal, base if tipo == "original" else titulo):
            tb, tv, tt = separar_version(it.get("trackName", ""))
            if similitud(tb, base) < 0.85 or not artistas_coinciden(artistas, partes_artista(it.get("artistName", ""))):
                continue
            if (tt == "original") != (tipo == "original"):
                continue
            col = it.get("collectionName", "")
            if RE_COMPILADO.search(col) or "various" in (it.get("collectionArtistName", "") or "").lower():
                continue
            fuentes_usadas.add("iTunes")
            votos.sumar(it.get("primaryGenreName", ""), 1.5, "iTunes")
            if not anios:
                y = anio_de(it.get("releaseDate"))
                if y:
                    anios.append(y)
                    notas.append("año sólo de iTunes")
            if not res["album"] and col:
                res["album"] = limpiar_album(col)
            if it.get("artworkUrl100"):
                res["url_caratula"].append(it["artworkUrl100"].replace("100x100bb", "600x600bb"))
            break

    # ---------- resultados ----------
    anios = [a for a in anios if a]
    if anios:
        res["anio"] = min(anios)
    elif tipo != "original":
        notas.append("no se encontró el remix")
    g, s, conf, fg = votos.resultado()
    if g == "Rock" and res["pais"] == "Argentina":
        g, s = "Rock Nacional", ("" if s == "Rock en Español" else s)
    if g == "Rock Nacional" and res["pais"] and res["pais"] != "Argentina":
        g = "Rock"
    res.update(genero=g, sub=s, conf_genero=conf)

    if not res["idioma"] and elegido and res["pais"] not in HISPANOS | ANGLO | {"Brasil"}:
        lang = (F.mb_release(elegido["relid"]).get("text-representation") or {}).get("language")
        if lang in IDIOMAS_ISO:
            res["idioma"] = IDIOMAS_ISO[lang]
    if not res["idioma"]:
        idi = idioma_por_titulo(base)
        if idi:
            res["idioma"] = idi
            notas.append("idioma estimado por título")
        elif res["pais"] in HISPANOS:
            res["idioma"] = "Español"
            notas.append("idioma estimado por país")
        elif res["pais"] in ANGLO:
            res["idioma"] = "Inglés"
            notas.append("idioma estimado por país")
        elif res["pais"] == "Brasil":
            res["idioma"] = "Portugués"
            notas.append("idioma estimado por país")

    n_fuentes = len(fuentes_usadas)
    if match and (len(set(anios)) >= 1 and n_fuentes >= 2 or conf >= 0.5):
        res["confianza"] = "ALTA"
    elif n_fuentes:
        res["confianza"] = "MEDIA"
    else:
        res["confianza"] = "BAJA"
        notas.append("no se encontró en ninguna fuente")
    res["fuentes"] = ", ".join(sorted(fuentes_usadas))
    res["notas"] = "; ".join(notas)
    return res

# =============================================================================
# EJECUCIÓN
# =============================================================================
def listar_audio(carpeta, excluir):
    out = []
    for root, dirs, files in os.walk(carpeta):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != excluir]
        for f in files:
            if not f.startswith(".") and Path(f).suffix.lower() in EXT_AUDIO:
                out.append(Path(root) / f)
    return sorted(out)


def fmt_tiempo(s):
    s = int(s)
    return f"{s // 3600}h{(s % 3600) // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def elegir_grouping(r, actual):
    """Subgénero encontrado; si no hay, se conserva el actual salvo que sea de otro género."""
    if r["sub"] or not r["genero"]:
        return r["sub"] or actual
    m = mapear(actual) if actual else None
    return actual if (not m or m[0] == r["genero"]) else ""


def preparar_caratula(F, r, tags, dir_tmp, i):
    """Devuelve los bytes de la carátula nueva o None."""
    cov = tags["cover"]
    tam = tam_imagen(cov) if cov else None
    album_cambia = bool(r["album"]) and norm_texto(r["album"]) != norm_texto(tags["album"])
    chica = bool(tam) and min(tam) < CARATULA_MINIMA
    if cov and not album_cambia and not chica:
        return None
    destino = dir_tmp / f"{i:05d}.jpg"
    for url in r["url_caratula"]:
        if F.descargar_imagen(url, destino):
            data = destino.read_bytes()
            destino.unlink()
            return data
    return None


def hacer_backup(ruta, coleccion, dir_bk):
    try:
        rel = ruta.relative_to(coleccion)
    except ValueError:
        rel = Path(ruta.name)
    destino = dir_bk / rel
    if not destino.exists():                 # se guarda sólo el ORIGINAL (la primera vez)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ruta, destino)


def ejecutar(args):
    coleccion = Path(args.carpeta).expanduser()
    if not coleccion.is_dir():
        print(f"No existe la carpeta: {coleccion}")
        sys.exit(1)
    dir_bk = carpeta_backup(coleccion)
    archivos = listar_audio(coleccion, CARPETA_BACKUP)
    if args.limite:
        archivos = archivos[: args.limite]
    lastfm = args.lastfm_key or LASTFM_API_KEY or os.environ.get("LASTFM_API_KEY", "")
    discogs = args.discogs_token or DISCOGS_TOKEN or os.environ.get("DISCOGS_TOKEN", "")
    online = not (args.sin_internet or args.solo_calidad)
    print("=" * 72)
    print("ORDENAR COLECCIÓN — KRAMER DJ" + ("   [SIMULACIÓN: no se modifica nada]" if args.simular else ""))
    print(f"Colección: {coleccion}  ({len(archivos)} temas)")
    if not args.simular and not args.solo_calidad:
        print(f"Backup   : {dir_bk}")
    if online:
        print("Fuentes  : MusicBrainz + Wikipedia + iTunes"
              + (" + Last.fm" if lastfm else "  (sin Last.fm: falta API key)")
              + (" + Discogs" if discogs else ""))
    print("=" * 72)

    F = Fuentes(lastfm, discogs, offline=not online)
    hacer_calidad = not args.sin_calidad
    if hacer_calidad and not (shutil.which("ffmpeg") or shutil.which("afconvert")):
        print("Aviso: no hay ffmpeg ni afconvert, se saltea el análisis de calidad.")
        hacer_calidad = False
    carpeta_esp = coleccion.parent / "Espectros calidad" if args.espectros else None
    dir_tmp = Path(tempfile.mkdtemp(prefix="kramer_car_"))

    registro, sin_datos, filas_cal = [], [], []
    cont = Counter()
    lock = threading.Lock()
    t0 = time.time()
    total = len(archivos)

    def procesar(i, f):
        """Un tema completo: calidad -> búsqueda -> backup -> escritura."""
        t_ini = time.time()
        tags = leer_tags(f)
        if hacer_calidad:
            q = analizar_calidad(f, tags, carpeta_esp)
            with lock:
                cont["cal_" + q["estado"]] += 1
                filas_cal.append({"Archivo": f.name, "Ruta": str(f), "Calidad": q["estado"],
                                  "Corte kHz": q["corte"],
                                  "Bitrate": tags["bitrate"] // 1000 if tags["bitrate"] else ""})
        if args.solo_calidad:
            with lock:
                cont["hechos"] += 1
                n = cont["hechos"]
            if n % 25 == 0 or n == total:
                print(f"   calidad: {n}/{total}")
            return
        try:
            r = analizar_tema(f, F, tags)
        except Exception as e:
            with lock:
                cont["errores"] += 1
                cont["hechos"] += 1
                registro.append(f"✗ {f.name}: error al buscar ({e})")
            return
        lineas_log, linea = None, ""
        if r["confianza"] == "BAJA":
            with lock:
                sin_datos.append(f)
            linea = f"{r['artista']} - {r['titulo']}  ->  no encontrado, no se toca"
        else:
            pais, idioma = r["pais"], r["idioma"]
            nuevos = {
                "genre": r["genero"] or tags["genre"],
                "grouping": elegir_grouping(r, tags["grouping"]),
                "year": str(r["anio"]) if r["anio"] else tags["year"],
                "album": r["album"] or tags["album"],
                "comment": armar_comentario(tags["comment"], pais, idioma),
                "language": IDIOMA_A_ISO.get(idioma, ""),
            }
            cambios = {}
            for k, v in nuevos.items():
                actual = tags[k][:4] if k == "year" else tags[k]
                if k == "language" and not v:
                    continue
                if (v or "") != (actual or ""):
                    cambios[k] = v
            caratula = preparar_caratula(F, r, tags, dir_tmp, i)
            linea = (f"{r['artista']} - {r['titulo']}  |  {nuevos['genre'] or '?'}"
                     f"{' / ' + nuevos['grouping'] if nuevos['grouping'] else ''}  |  "
                     f"{nuevos['year'][:4] if nuevos['year'] else '?'}  |  {pais or '?'}  |  "
                     f"{idioma or '?'}")
            if cambios or caratula:
                detalle = []
                for k, nombre in (("genre", "Género"), ("grouping", "Grouping"), ("year", "Año"),
                                  ("album", "Álbum"), ("comment", "Comentario")):
                    if k in cambios:
                        antes = tags[k][:4] if k == "year" else tags[k]
                        detalle.append(f"{nombre}: '{antes}' -> '{cambios[k]}'")
                if caratula:
                    detalle.append("Carátula nueva")
                rel = f.relative_to(coleccion) if coleccion in f.parents else f.name
                lineas_log = f"✓ {rel}\n    " + "\n    ".join(detalle)
                if not args.simular:
                    try:
                        hacer_backup(f, coleccion, dir_bk)
                        escribir_tags(f, cambios, caratula)
                    except Exception as e:
                        lineas_log = f"✗ {f.name}: no se pudo escribir ({e})"
                        with lock:
                            cont["errores"] += 1
                if lineas_log.startswith("✓"):
                    with lock:
                        cont["modificados"] += 1
            else:
                linea += "  (ya estaba bien)"
        with lock:
            if lineas_log:
                registro.append(lineas_log)
            cont["hechos"] += 1
            n = cont["hechos"]
            resto = (time.time() - t0) / n * (total - n)
            print(f"[{n}/{total}] {linea}   ({time.time() - t_ini:.0f}s · falta ~{fmt_tiempo(resto)})")
            if n % 20 == 0:
                F.guardar()

    pool = ThreadPoolExecutor(max_workers=max(1, args.hilos))
    futs = [pool.submit(procesar, i, f) for i, f in enumerate(archivos, 1)]
    try:
        for fut in futs:
            try:
                fut.result()
            except Exception as e:
                print(f"   error inesperado: {e}")
    except KeyboardInterrupt:
        print("\nCortado. Terminando los temas en curso (unos segundos)...")
        pool.shutdown(wait=True, cancel_futures=True)
        F.guardar()
        print("Lo consultado quedó guardado: la próxima corrida retoma rápido.")
        sys.exit(1)
    pool.shutdown()
    F.guardar()
    shutil.rmtree(dir_tmp, ignore_errors=True)
    modificados, errores = cont["modificados"], cont["errores"]
    cal = Counter({k[4:]: v for k, v in cont.items() if k.startswith("cal_")})
    if filas_cal:
        escribir_txt_calidad(filas_cal, coleccion / "calidad_no_ok.txt")

    if not args.solo_calidad:
        sello = datetime.now().strftime("%Y%m%d_%H%M")
        dir_log = dir_bk if not args.simular else coleccion
        dir_log.mkdir(parents=True, exist_ok=True)
        log = dir_log / f"cambios_{sello}{'_SIMULACION' if args.simular else ''}.txt"
        cuerpo = [f"Cambios de metadata — {datetime.now():%d/%m/%Y %H:%M}", ""] + registro
        if sin_datos:
            cuerpo += ["", f"=== NO ENCONTRADOS (no se tocaron): {len(sin_datos)}"]
            cuerpo += [f"  {f}" for f in sin_datos]
        log.write_text("\n".join(cuerpo), encoding="utf-8")

    print("=" * 72)
    if not args.solo_calidad:
        print(f"{'A modificar' if args.simular else 'Modificados'}: {modificados}  ·  "
              f"no encontrados: {len(sin_datos)}" + (f"  ·  errores: {errores}" if errores else ""))
        print(f"Detalle de cambios: {log}")
    if cal:
        print(f"Calidad: OK {cal['OK']}  ·  DUDOSO {cal['DUDOSO']}  ·  MALO {cal['MALO']}"
              f"  ->  {coleccion / 'calidad_no_ok.txt'}")
    if not args.simular and modificados:
        print("Ahora en Rekordbox: seleccioná todos los temas -> clic derecho -> "
              "'Volver a cargar etiqueta'.")
    print("=" * 72)


def escribir_txt_calidad(filas, destino):
    lineas = [f"Temas con calidad NO OK — {datetime.now():%d/%m/%Y %H:%M}",
              f"Criterio: OK >= {CALIDAD_OK_KHZ} kHz · DUDOSO {CALIDAD_MALO_KHZ}–{CALIDAD_OK_KHZ}"
              f" kHz · MALO < {CALIDAD_MALO_KHZ} kHz (frecuencia de corte real del audio)", ""]
    for estado, titulo in (("MALO", "MALOS (muy comprimidos, se nota al escucharlos)"),
                           ("DUDOSO", "DUDOSOS (compresión media, revisar)"),
                           ("ERROR", "NO SE PUDIERON ANALIZAR")):
        grupo = sorted((f for f in filas if f.get("Calidad") == estado),
                       key=lambda f: f.get("Corte kHz") or 0)
        if not grupo:
            continue
        lineas += [f"=== {titulo}: {len(grupo)}", ""]
        for f in grupo:
            br = f" · declara {f['Bitrate']} kbps" if f.get("Bitrate") else ""
            corte = f"corte {f['Corte kHz']} kHz" if f.get("Corte kHz") else "sin dato"
            lineas.append(f"{f['Archivo']}  ({corte}{br})")
            lineas.append(f"    Ruta: {f['Ruta']}")
        lineas.append("")
    if len(lineas) == 3:
        lineas.append("Todos los temas están OK.")
    destino.write_text("\n".join(lineas), encoding="utf-8")


def deshacer(args):
    coleccion = Path(args.carpeta).expanduser()
    dir_bk = carpeta_backup(coleccion)
    origs = listar_audio(dir_bk, "") if dir_bk.is_dir() else []
    if not origs:
        print("No hay originales en el backup.")
        sys.exit(1)
    print(f"Restaurando {len(origs)} archivos originales desde {dir_bk} ...")
    ok = 0
    for b in origs:
        destino = coleccion / b.relative_to(dir_bk)
        try:
            shutil.copy2(b, destino)
            ok += 1
        except Exception as e:
            print(f"  ✗ {b.name}: {e}")
    print(f"Listo: {ok} restaurados. En Rekordbox: 'Volver a cargar etiqueta'.")
    print(f"(Los originales siguen en {dir_bk}; si ya no los necesitás, podés borrar esa carpeta.)")


def main():
    ap = argparse.ArgumentParser(description="Ordenar metadata de la colección — KRAMER DJ")
    ap.add_argument("--carpeta", default=COLECCION)
    ap.add_argument("--limite", type=int, default=0, help="procesar sólo los primeros N temas")
    ap.add_argument("--simular", action="store_true", help="mostrar cambios sin escribir")
    ap.add_argument("--deshacer", action="store_true", help="restaurar los originales")
    ap.add_argument("--hilos", type=int, default=HILOS, help="temas en paralelo")
    ap.add_argument("--sin-calidad", action="store_true")
    ap.add_argument("--solo-calidad", action="store_true")
    ap.add_argument("--espectros", action="store_true")
    ap.add_argument("--sin-internet", action="store_true")
    ap.add_argument("--lastfm-key", default="")
    ap.add_argument("--discogs-token", default="")
    args = ap.parse_args()
    deshacer(args) if args.deshacer else ejecutar(args)


if __name__ == "__main__":
    main()
