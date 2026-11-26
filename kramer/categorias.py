"""Las 4 categorías de My Tags: cada una es automática (sale de la metadata) o manual."""
import re

from . import config

FUENTES = {
    "origen_idioma": "Automático: origen e idioma",
    "genero": "Automático: género",
    "decada": "Automático: década",
    "version": "Automático: versión (original, remix…)",
    "bpm": "Automático: rango de BPM",
    "manual": "Manual",
}
DEFAULT = [
    {"id": "1", "nombre": "Origen/Idioma", "fuente": "origen_idioma"},
    {"id": "2", "nombre": "Género", "fuente": "genero"},
    {"id": "3", "nombre": "Década", "fuente": "decada"},
    {"id": "4", "nombre": "Momento", "fuente": "manual"},
]

# ------------------------------------------------------------------ origen e idioma
PAISES = ["Argentina", "Brasil", "Colombia", "Estados Unidos", "Inglaterra"]
REGIONES = ["Latinoamérica", "Norteamérica", "Europa", "Asia", "África", "Oceanía"]
IDIOMAS = ["Español", "Inglés", "Portugués"]
ORDEN_ORIGEN = PAISES + ["Otro país"] + REGIONES + IDIOMAS + ["Otro idioma"]

INGLATERRA = {"Inglaterra", "Reino Unido", "Escocia", "Gales", "Irlanda del Norte"}
LATAM = {"Argentina", "Brasil", "Colombia", "Uruguay", "Chile", "Paraguay", "Bolivia", "Perú", "Venezuela",
         "Ecuador", "México", "Puerto Rico", "República Dominicana", "Cuba", "Panamá", "Costa Rica", "Guatemala",
         "Honduras", "El Salvador", "Nicaragua", "Jamaica", "Bahamas", "Trinidad y Tobago", "Haití", "Barbados"}
NORTE = {"Estados Unidos", "Canadá"}
EUROPA = {"España", "Irlanda", "Portugal", "Francia", "Italia", "Alemania", "Países Bajos", "Bélgica", "Suiza",
          "Austria", "Suecia", "Noruega", "Dinamarca", "Finlandia", "Islandia", "Polonia", "Rusia", "Ucrania",
          "Grecia", "Rumania", "República Checa", "Hungría", "Lituania", "Letonia", "Estonia", "Croacia",
          "Serbia", "Eslovenia", "Eslovaquia", "Bulgaria", "Luxemburgo", "Malta", "Chipre", "Bielorrusia",
          "Bosnia y Herzegovina", "Albania", "Macedonia del Norte", "Montenegro", "Mónaco"} | INGLATERRA
ASIA = {"Japón", "Corea del Sur", "China", "India", "Israel", "Turquía", "Filipinas", "Tailandia", "Indonesia",
        "Líbano", "Emiratos Árabes Unidos", "Irán", "Vietnam", "Malasia", "Singapur", "Taiwán", "Kazajistán"}
AFRICA = {"Sudáfrica", "Nigeria", "Ghana", "Senegal", "Marruecos", "Egipto", "Argelia", "Kenia", "Mali",
          "Costa de Marfil", "Camerún", "Angola", "Cabo Verde", "Congo", "Etiopía", "Túnez"}
OCEANIA = {"Australia", "Nueva Zelanda"}
INGLES_A_ES = {"Lithuania": "Lituania", "Latvia": "Letonia", "Croatia": "Croacia", "Slovenia": "Eslovenia",
               "Slovakia": "Eslovaquia", "Belarus": "Bielorrusia", "Czech Republic": "República Checa",
               "Czechia": "República Checa", "Netherlands": "Países Bajos", "Germany": "Alemania",
               "France": "Francia", "Italy": "Italia", "Spain": "España", "Sweden": "Suecia", "Norway": "Noruega",
               "Denmark": "Dinamarca", "Finland": "Finlandia", "Belgium": "Bélgica", "Switzerland": "Suiza",
               "Poland": "Polonia", "Greece": "Grecia", "Turkey": "Turquía", "Brazil": "Brasil",
               "Mexico": "México", "Peru": "Perú", "Dominican Republic": "República Dominicana",
               "United States": "Estados Unidos", "USA": "Estados Unidos", "EEUU": "Estados Unidos",
               "United Kingdom": "Reino Unido", "UK": "Reino Unido", "England": "Inglaterra",
               "Canada": "Canadá", "Japan": "Japón", "South Korea": "Corea del Sur", "South Africa": "Sudáfrica",
               "New Zealand": "Nueva Zelanda", "Panama": "Panamá", "Ireland": "Irlanda", "Austria": "Austria",
               "Australia": "Australia", "Jamaica": "Jamaica", "Colombia": "Colombia", "Argentina": "Argentina"}


def region(pais):
    for nombre, grupo in (("Latinoamérica", LATAM), ("Norteamérica", NORTE), ("Europa", EUROPA),
                          ("Asia", ASIA), ("África", AFRICA), ("Oceanía", OCEANIA)):
        if pais in grupo:
            return nombre
    return ""


def tags_origen_idioma(pais, idioma):
    out = []
    pais = INGLES_A_ES.get((pais or "").strip(), (pais or "").strip())
    if pais:
        p = "Inglaterra" if pais in INGLATERRA else pais
        out.append(p if p in PAISES else "Otro país")
        r = region(pais)
        if r:
            out.append(r)
    i = (idioma or "").strip().lower()
    if i and i != "instrumental":
        if i.startswith("español") or i.startswith("castellano"):
            out.append("Español")
        elif i.startswith("inglés") or i.startswith("ingles") or i.startswith("english"):
            out.append("Inglés")
        elif i.startswith("portugu"):
            out.append("Portugués")
        else:
            out.append("Otro idioma")
    return out


# ------------------------------------------------------------------ otras fuentes
def tag_decada(anio):
    try:
        y = int(str(anio)[:4])
    except (TypeError, ValueError):
        return []
    if y < 1900 or y > 2100:
        return []
    d = y // 10 * 10
    return [f"{d}s" if d >= 2000 else f"{str(d)[2:]}s"]


_VERSIONES = [("Mashup", r"mash ?up"), ("En vivo", r"\b(en vivo|live|ac[uú]stico|unplugged)\b"),
              ("Extended", r"\bextended|extend\b|club mix|12\"|\bvip\b"), ("Edit", r"\b(edit|radio|short)\b"),
              ("Remix", r"\b(remix|rmx|mix|rework|bootleg|flip|version|versi[oó]n|dub)\b")]
ORDEN_VERSION = ["Original", "Remix", "Extended", "Edit", "En vivo", "Mashup"]


def tag_version(titulo):
    t = titulo or ""
    extra = " ".join(re.findall(r"[\(\[]([^\)\]]*)[\)\]]", t)) + " " + (t.rsplit(" - ", 1)[1] if " - " in t else "")
    for nombre, rx in _VERSIONES:
        if re.search(rx, extra, re.I):
            if nombre == "Remix" and re.search(r"original mix", extra, re.I):
                return ["Original"]
            return [nombre]
    return ["Original"] if t else []


ORDEN_BPM = ["Menos de 100", "100 a 119", "120 a 128", "Más de 128"]


def tag_bpm(bpm):
    try:
        b = float(bpm or 0)
    except (TypeError, ValueError):
        return []
    if not b:
        return []
    return [ORDEN_BPM[0] if b < 100 else ORDEN_BPM[1] if b < 120 else ORDEN_BPM[2] if b <= 128.5 else ORDEN_BPM[3]]


def calcular(fuente, d):
    """d: {pais, idioma, genero, anio, titulo, bpm} -> lista de tags."""
    if fuente == "origen_idioma":
        return tags_origen_idioma(d.get("pais"), d.get("idioma"))
    if fuente == "genero":
        g = (d.get("genero") or "").strip()
        return [g] if g else []
    if fuente == "decada":
        return tag_decada(d.get("anio"))
    if fuente == "version":
        return tag_version(d.get("titulo"))
    if fuente == "bpm":
        return tag_bpm(d.get("bpm"))
    return []


def orden(fuente, nombres_con_cuenta):
    """Orden en que se muestran los tags de la categoría (en Rekordbox y en la consola)."""
    fijo = {"origen_idioma": ORDEN_ORIGEN, "version": ORDEN_VERSION, "bpm": ORDEN_BPM}.get(fuente)
    if fijo:
        return [n for n in fijo if n in nombres_con_cuenta] + sorted(n for n in nombres_con_cuenta if n not in fijo)
    if fuente == "decada":
        clave = lambda n: (int(n[:-1]) + (1900 if len(n) == 3 else 0)) if n[:-1].isdigit() else 9999
        return sorted(nombres_con_cuenta, key=clave)
    return sorted(nombres_con_cuenta, key=lambda n: (-nombres_con_cuenta[n], n.lower()))


def cargar():
    guardadas = config.cargar().get("categorias") or []
    por_id = {c["id"]: c for c in guardadas if isinstance(c, dict) and c.get("id")}
    out = []
    for d in DEFAULT:
        c = {**d, **por_id.get(d["id"], {})}
        if c["fuente"] not in FUENTES:
            c["fuente"] = d["fuente"]
        out.append(c)
    return out


def automaticas():
    return [c for c in cargar() if c["fuente"] != "manual"]
