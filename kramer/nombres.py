"""Nombres prolijos y unificados a partir de la metadata.

Formato: «Artista - Título (feat. Invitado) (Versión).ext»
  · varios artistas: «A, B & C» (los dúos como «Zion & Lennox» quedan como están)
  · «ft.», «Ft», «featuring» -> «(feat. …)» al final del título
  · se sacan: (Official Video), (Audio), [HD], 4K, (320), [103-111 BPM], «CD 1 TRACK 10», «01 », «_», «- Topic»
  · versiones al final y entre paréntesis: «- Reggaeton Mix» -> «(Reggaeton Mix)»
  · títulos en MAYÚSCULAS o minúsculas -> «Tipo Título» (los artistas se respetan: ABBA, KAROL G, WOS)
"""
import re
import unicodedata

RUIDO = re.compile(
    r"\s*[\(\[\{][^\)\]\}]*\b(official|oficial|video|v[ií]deo|audio|lyrics?|letra|visuali[sz]er|"
    r"hd|hq|4k|1080p|720p|320|kbps|bpm|videoclip|clip|premiere|estreno)\b[^\)\]\}]*[\)\]\}]",
    re.I)
RUIDO_SUELTO = re.compile(r"\s*\b(official (music )?video|video oficial|official audio|audio oficial|lyric video|"
                          r"videoclip oficial|hd|4k)\s*$", re.I)
PISTA_CD = re.compile(r"\s*\bCD\s*\d+\s*TRACK\s*\d+\b.*$", re.I)
NUM_INICIAL = re.compile(r"^\s*(?:\d{1,2}\s*[\.\-)]|0\d)\s+(?=\D)")     # «01 Tema», «3. Tema»; no «7 rings» ni «99 Problems»
ENTEROS = {"tyler, the creator", "earth, wind & fire", "crosby, stills & nash", "crosby, stills, nash & young",
           "emerson, lake & palmer", "blood, sweat & tears", "peter, paul and mary"}
COPIA_FINAL = re.compile(r"(\s*\(\d\)|\s*-\d|\s+copia)$", re.I)
FEAT = re.compile(r"\s*[\(\[]?\s*\b(?:feat\.?|ft\.?|featuring)\s+([^\)\]]+?)\s*[\)\]]?(?=\s*[\(\[]|$)", re.I)
VERSION = re.compile(r"\b(remix|mix|edit|version|versi[oó]n|extended|radio|live|en vivo|ac[uú]stic[oa]|"
                     r"acoustic|remaster(ed)?|rmx|bootleg|mashup|intro|outro|clean|dub|vip|rework|cover)\b", re.I)
CHICAS = {"a", "al", "and", "as", "at", "by", "con", "de", "del", "e", "el", "en", "for", "in", "la", "las", "lo",
          "los", "mi", "o", "of", "on", "or", "para", "por", "que", "se", "su", "te", "the", "to", "tu", "u", "un",
          "una", "y", "x", "vs"}


def _espacios(s):
    s = unicodedata.normalize("NFC", s or "")
    s = s.replace("_", " ").replace("–", "-").replace("—", "-").replace(" ", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip(" -")


def _tipo_titulo(s):
    palabras = s.split(" ")
    out = []
    for i, p in enumerate(palabras):
        base = p.lower()
        letras = re.sub(r"[^\w]", "", base)
        if i and letras in CHICAS and not out[-1].endswith(("(", "-")):
            out.append(base)
        elif re.fullmatch(r"[ivx]+", letras) and len(letras) <= 4:      # números romanos
            out.append(p.upper())
        else:
            out.append(re.sub(r"^([^\w]*)(\w)", lambda m: m.group(1) + m.group(2).upper(), base, count=1))
    return " ".join(out)


def _capitalizar_titulo(t):
    letras = re.sub(r"[^A-Za-zÁÉÍÓÚÑÜáéíóúñü]", "", t)
    if len(letras) >= 3 and (letras.isupper() or letras.islower()):
        return _tipo_titulo(t)
    # palabras sueltas en MAYÚSCULAS largas dentro de un título normal: «Tema GIGANTE» -> «Tema Gigante»
    return re.sub(r"\b([A-ZÁÉÍÓÚÑÜ]{5,})\b", lambda m: m.group(1).capitalize(), t)


def _pegados(a, conocidos):
    """«Don Omar Daddy Yankee» -> ['Don Omar', 'Daddy Yankee'] usando los artistas que ya tenés."""
    if not conocidos or a.lower() in conocidos:
        return [a]
    w = a.split(" ")
    for i in range(len(w) - 1, 0, -1):
        izq, der = " ".join(w[:i]), " ".join(w[i:])
        if izq.lower() in conocidos:
            resto = _pegados(der, conocidos)
            if any(r.lower() in conocidos for r in resto):
                return [izq] + resto
    return [a]


def separar_artistas(a, conocidos=None):
    """'A, B & C' / 'A x B' / 'A; B' / 'A / B' / 'A- B'  -> ['A', 'B', 'C'].
    Los dúos con '&' o 'y' no se tocan; 'AC/DC' tampoco."""
    a = _espacios(a)
    a = re.sub(r"\s*-\s*Topic\b", "", a, flags=re.I)
    if a.lower() in ENTEROS or (conocidos and a.lower() in conocidos):
        return [a]
    partes = re.split(r"\s*(?:,|;|\s/\s?|/\s|\s[xX]\s(?![&,;/])|\svs\.?\s|-\s)\s*", a)
    partes = [q for p in partes for q in _pegados(p.strip(" -"), conocidos)]
    vistos, out = set(), []
    for p in partes:
        p = p.strip(" -")
        if p and p.lower() not in vistos and p.lower() not in ("various artists", "varios artistas", "topic"):
            vistos.add(p.lower())
            out.append(p)
    return out


def unir_artistas(lista, maximo=3):
    lista = lista[:maximo]
    if len(lista) <= 1:
        return "".join(lista)
    if any(" & " in x for x in lista):          # ya hay dúos: «Zion & Lennox, Farruko»
        return ", ".join(lista)
    return ", ".join(lista[:-1]) + " & " + lista[-1]


def prolijo(artista, titulo, conocidos=None):
    """Devuelve (artista, titulo) prolijos."""
    t = _espacios(titulo)
    t = PISTA_CD.sub("", t)
    t = NUM_INICIAL.sub("", t)
    t = RUIDO.sub("", t)
    t = RUIDO_SUELTO.sub("", t)
    t = COPIA_FINAL.sub("", t)
    t = re.sub(r"\[([^\]]*)\]", r"(\1)", t)
    a = _espacios(artista)
    invitados = []
    # «feat.» en el artista
    m = re.search(r"\s+\b(?:feat\.?|ft\.?|featuring)\s+(.+)$", a, re.I)
    if m:
        invitados += separar_artistas(m.group(1).replace(" & ", ", "), conocidos)
        a = a[:m.start()]
    # «feat.» en el título
    for m in list(FEAT.finditer(t)):
        invitados += separar_artistas(m.group(1).replace(" & ", ", "), conocidos)
    t = FEAT.sub("", t)
    # «Tema - Reggaeton Mix» -> «Tema (Reggaeton Mix)»
    if " - " in t:
        base, resto = t.rsplit(" - ", 1)
        if VERSION.search(resto) and base:
            t = f"{base} ({resto})"
    # paréntesis vacíos o sin cerrar, espacios
    t = re.sub(r"\(\s*\)", "", t)
    if t.count("(") > t.count(")"):
        t += ")"
    t = _espacios(t) or _espacios(titulo)       # un título que es todo «ruido» («4K», «HD») se deja como vino
    principales = separar_artistas(a, conocidos)
    claves = {x.lower() for x in principales}
    invitados = [x for x in dict.fromkeys(invitados) if x.lower() not in claves]
    # si el artista vino todo pegado en minúsculas
    a = unir_artistas(principales)
    if a and a.islower():
        a = _tipo_titulo(a)
    t = _capitalizar_titulo(t)
    if invitados:
        version = re.search(r"\s*(\([^()]*\))\s*$", t)
        feat = f"(feat. {unir_artistas(invitados)})"
        if version and VERSION.search(version.group(1)):
            t = t[:version.start()] + f" {feat} " + version.group(1)
        else:
            t = f"{t} {feat}"
    return a, _espacios(t)


def nombre_archivo(artista, titulo, ext, largo=140, conocidos=None):
    a, t = prolijo(artista, titulo, conocidos)
    n = f"{a} - {t}" if a and t else (t or a)
    n = n.replace("/", "-").replace("\\", "-").replace(":", " -")
    n = re.sub(r'[*?"<>|]', "", n) if not n.startswith("*") else "*" + re.sub(r'[*?"<>|]', "", n[1:])
    n = re.sub(r"\s+", " ", n).strip(" .")
    n = re.sub(r"\.(\s*-)", r".\1", n) or "Sin nombre"
    if len(n) > largo:                                   # cortar en una palabra, nunca a la mitad
        n = n[:largo].rsplit(" ", 1)[0].rstrip(" -(,&")
    return n + ext.lower()
