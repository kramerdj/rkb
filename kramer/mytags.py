#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rekordbox_mytags.py  —  KRAMER DJ
Arma los My Tags de Rekordbox y los asigna automáticamente a cada tema.

Categorías (Rekordbox permite 4):
  1. Origen   -> región (Argentina, Latinoamérica, España, EEUU, UK, Europa, Otros)
                 + país exacto cuando la región tiene varios países
  2. Idioma   -> Español, Inglés, Portugués, Otro, Instrumental
  3. Década   -> 60s, 70s, 80s, 90s, 2000s, 2010s, 2020s...
  4. Momento  -> Previa, Warm Up, Main, Peak, Close, Lentos   (se crean vacíos, van a mano)

De dónde saca los datos: directamente de cada archivo
  - País e Idioma: del comentario "País: X | Idioma: Y" (lo escribe ordenar_coleccion.py)
  - Década: del año

Se puede volver a correr cuando quieras: agrega lo que falta y corrige lo que cambió
en Origen, Idioma y Década. NUNCA toca lo que cargaste a mano en Momento.

SEGURIDAD
  - Rekordbox tiene que estar CERRADO.
  - Antes de modificar, copia la base a: Documents/rekordbox/Backups base Rekordbox/FECHA
  - Para volver atrás: python3.15 rekordbox_mytags.py --restaurar

USO
  python3.15 -m pip install pyrekordbox mutagen
  python3.15 rekordbox_mytags.py --simular     # muestra qué haría, no modifica nada
  python3.15 rekordbox_mytags.py               # aplica
"""
import argparse
import datetime
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

if sys.version_info < (3, 11):
    print("Hace falta Python 3.11 o más nuevo. Corrélo con:  python3.15 rekordbox_mytags.py")
    sys.exit(1)
try:
    from mutagen import File as MFile
    from mutagen.id3 import ID3
    from mutagen.mp4 import MP4
    from pyrekordbox import MasterDatabase
    from pyrekordbox.masterdb import models as m
    from pyrekordbox.utils import get_rekordbox_pid
except ImportError as e:
    print(f"Falta una librería ({e}). Instalalas con:\n  python3.15 -m pip install pyrekordbox mutagen")
    sys.exit(1)

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
try:
    from kramer import plataforma
except ImportError:
    import plataforma
DIR_BASE = Path(os.environ.get("KRAMER_RB_DIR", plataforma.dir_rekordbox()))
DIR_BACKUPS = Path(os.environ.get("KRAMER_RB_BACKUPS",
                                  Path.home() / "Documents/rekordbox/Backups base Rekordbox"))

CATEGORIAS = {"1": "Origen", "2": "Idioma", "3": "Década", "4": "Momento"}
AUTOMATICAS = ("1", "2", "3")            # Momento ("4") nunca se toca en las asignaciones

IDIOMAS = ["Español", "Inglés", "Portugués", "Otro", "Instrumental"]
MOMENTOS = ["Previa", "Warm Up", "Main", "Peak", "Close", "Lentos"]
REGIONES = ["Argentina", "Latinoamérica", "España", "EEUU", "UK", "Europa", "Otros"]

LATAM = {"Uruguay", "Chile", "Brasil", "Paraguay", "Bolivia", "Perú", "Colombia", "Venezuela",
         "Ecuador", "México", "Puerto Rico", "República Dominicana", "Cuba", "Panamá",
         "Costa Rica", "Guatemala", "Honduras", "El Salvador", "Nicaragua"}
EUROPA = {"Irlanda", "Portugal", "Francia", "Italia", "Alemania", "Países Bajos", "Bélgica",
          "Suiza", "Austria", "Suecia", "Noruega", "Dinamarca", "Finlandia", "Islandia",
          "Polonia", "Rusia", "Ucrania", "Grecia", "Rumania", "República Checa", "Hungría",
          "Escocia", "Gales", "Inglaterra", "Lituania", "Letonia", "Estonia", "Croacia",
          "Serbia", "Eslovenia", "Eslovaquia", "Bulgaria", "Luxemburgo", "Malta", "Chipre",
          "Bielorrusia", "Bosnia y Herzegovina", "Albania", "Macedonia del Norte", "Montenegro"}
# Países que alguna fuente devolvió en inglés -> nombre en español
TRADUCIR = {"Lithuania": "Lituania", "Latvia": "Letonia", "Estonia": "Estonia",
            "Croatia": "Croacia", "Slovenia": "Eslovenia", "Slovakia": "Eslovaquia",
            "Belarus": "Bielorrusia", "Czech Republic": "República Checa", "Czechia": "República Checa",
            "Netherlands": "Países Bajos", "Germany": "Alemania", "France": "Francia",
            "Italy": "Italia", "Spain": "España", "Sweden": "Suecia", "Norway": "Noruega",
            "Denmark": "Dinamarca", "Finland": "Finlandia", "Belgium": "Bélgica",
            "Switzerland": "Suiza", "Poland": "Polonia", "Greece": "Grecia", "Turkey": "Turquía",
            "Brazil": "Brasil", "Mexico": "México", "Peru": "Perú", "Dominican Republic":
            "República Dominicana", "United States": "Estados Unidos", "United Kingdom":
            "Reino Unido", "Canada": "Canadá", "Japan": "Japón", "South Korea": "Corea del Sur",
            "South Africa": "Sudáfrica", "New Zealand": "Nueva Zelanda", "Panama": "Panamá"}
REGION_UNICA = {"Argentina": "Argentina", "España": "España", "Estados Unidos": "EEUU",
                "Reino Unido": "UK", "Inglaterra": "UK", "Escocia": "UK", "Gales": "UK"}


def region_de(pais):
    if pais in REGION_UNICA:
        return REGION_UNICA[pais]
    if pais in LATAM:
        return "Latinoamérica"
    if pais in EUROPA:
        return "Europa"
    return "Otros"


def tags_origen(pais):
    """Región + país exacto (sólo si la región agrupa varios países)."""
    if not pais:
        return []
    reg = region_de(pais)
    return [reg] if pais in REGION_UNICA else [reg, pais]


def tag_idioma(idioma):
    if not idioma:
        return []
    return [idioma] if idioma in IDIOMAS else ["Otro"]


def tag_decada(anio):
    try:
        y = int(str(anio)[:4])
    except (TypeError, ValueError):
        return []
    if not 1900 <= y <= datetime.date.today().year:
        return []
    d = y // 10 * 10
    return [f"{d % 100:02d}s" if d < 2000 else f"{d}s"]


def orden_decada(nombre):
    n = int(nombre.rstrip("s"))
    return n + 1900 if n < 100 else n

# =============================================================================
# LECTURA DE ARCHIVOS
# =============================================================================
def leer_archivo(ruta):
    """-> (comentario, año) leídos del tag del archivo."""
    try:
        a = MFile(str(ruta))
    except Exception:
        return "", ""
    if a is None or a.tags is None:
        return "", ""
    t = a.tags
    com, anio = "", ""
    try:
        if isinstance(t, ID3):
            for c in t.getall("COMM"):
                if c.desc == "" and c.text:
                    com = str(c.text[0])
                    break
            if "TDRC" in t and t["TDRC"].text:
                anio = str(t["TDRC"].text[0])
        elif isinstance(a, MP4):
            com = str(t["\xa9cmt"][0]) if t.get("\xa9cmt") else ""
            anio = str(t["\xa9day"][0]) if t.get("\xa9day") else ""
        else:
            com = str((t.get("comment") or [""])[0])
            anio = str((t.get("date") or [""])[0])
    except Exception:
        pass
    return com, anio


def datos_de_comentario(com):
    p = re.search(r"Pa[ií]s:\s*([^|]+)", com or "")
    i = re.search(r"Idioma:\s*([^|]+)", com or "")
    pais = p.group(1).strip() if p else ""
    return TRADUCIR.get(pais, pais), (i.group(1).strip() if i else "")

# =============================================================================
# BACKUP
# =============================================================================
ARCHIVOS_BASE = ["master.db", "master.db-wal", "master.db-shm", "masterPlaylists6.xml",
                 "networkAnalyze6.db", "datafile.edb"]


def hacer_backup():
    destino = DIR_BACKUPS / datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    destino.mkdir(parents=True, exist_ok=True)
    copiados = 0
    for nombre in ARCHIVOS_BASE:
        src = DIR_BASE / nombre
        if src.exists():
            shutil.copy2(src, destino / nombre)
            copiados += 1
    if not (destino / "master.db").exists():
        raise RuntimeError(f"No se pudo copiar master.db desde {DIR_BASE}")
    return destino, copiados


def restaurar():
    if get_rekordbox_pid():
        print("Cerrá Rekordbox antes de restaurar.")
        sys.exit(1)
    backups = sorted(p for p in DIR_BACKUPS.glob("*") if (p / "master.db").exists())
    if not backups:
        print(f"No hay backups en {DIR_BACKUPS}")
        sys.exit(1)
    ultimo = backups[-1]
    print(f"Restaurando la base desde {ultimo} ...")
    for nombre in ARCHIVOS_BASE:
        dst = DIR_BASE / nombre
        src = ultimo / nombre
        if src.exists():
            shutil.copy2(src, dst)
        elif nombre.endswith(("-wal", "-shm")) and dst.exists():
            dst.unlink()                  # no estaban en el backup: se quitan
    print("Listo. Abrí Rekordbox y verificá.")

# =============================================================================
# MY TAGS
# =============================================================================
class Gestor:
    def __init__(self, db, simular):
        self.db, self.simular = db, simular
        self.now = datetime.datetime.now()
        self.stats = Counter()

    def tags_de(self, cat_id):
        return (self.db.query(m.DjmdMyTag)
                .filter(m.DjmdMyTag.ParentID == cat_id).order_by(m.DjmdMyTag.Seq).all())

    def preparar_categorias(self):
        for cid, nombre in CATEGORIAS.items():
            cat = self.db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ID == cid).one_or_none()
            if cat is None:
                raise RuntimeError(f"No existe la categoría de My Tag con ID {cid}")
            if cat.Name != nombre:
                print(f"   Categoría '{cat.Name}' -> '{nombre}'")
                cat.Name = nombre
                cat.updated_at = self.now
                self.stats["categorías renombradas"] += 1

    def sincronizar_lista(self, cid, deseados, borrar_con_temas):
        """Deja en la categoría exactamente los tags 'deseados', en ese orden."""
        existentes = self.tags_de(cid)
        por_nombre = {}
        for t in existentes:
            if t.Name in deseados and t.Name not in por_nombre:
                por_nombre[t.Name] = t
                continue
            asign = self.db.query(m.DjmdSongMyTag).filter(m.DjmdSongMyTag.MyTagID == t.ID).all()
            if asign and not borrar_con_temas:
                por_nombre.setdefault(t.Name, t)      # tiene temas cargados a mano: se conserva
                continue
            for a in asign:
                self.db.delete(a)
                self.stats["asignaciones borradas"] += 1
            self.db.delete(t)
            self.stats["tags borrados"] += 1
        for nombre in deseados:
            if nombre not in por_nombre:
                nuevo = m.DjmdMyTag.create(
                    ID=str(self.db.generate_unused_id(m.DjmdMyTag, is_28_bit=False)),
                    Seq=len(por_nombre) + 1, Name="New Tag", Attribute=0, ParentID=cid,
                    UUID=str(uuid4()), created_at=self.now, updated_at=self.now)
                self.db.add(nuevo)
                nuevo.Name = nombre
                por_nombre[nombre] = nuevo
                self.stats["tags creados"] += 1
        orden = list(deseados) + [n for n in por_nombre if n not in deseados]
        for seq, nombre in enumerate(orden, 1):
            t = por_nombre[nombre]
            if t.Seq != seq:
                t.Seq = seq
                t.updated_at = self.now
        return {n: por_nombre[n].ID for n in orden}

    def asignar(self, ids_por_cat, deseado_por_tema):
        """deseado_por_tema: {content_id: set(tag_id)} sólo para categorías automáticas."""
        ids_auto = set()
        for cid in AUTOMATICAS:
            ids_auto |= set(ids_por_cat[cid].values())
        actuales = defaultdict(dict)
        for a in self.db.query(m.DjmdSongMyTag).all():
            if a.MyTagID in ids_auto:
                actuales[str(a.ContentID)][a.MyTagID] = a
        for content_id, deseados in deseado_por_tema.items():
            tiene = actuales.get(content_id, {})
            for tag_id, fila in tiene.items():
                if tag_id not in deseados:
                    self.db.delete(fila)
                    self.stats["asignaciones corregidas (quitadas)"] += 1
            for tag_id in deseados - set(tiene):
                fila = m.DjmdSongMyTag.create(
                    ID=str(uuid4()), MyTagID=tag_id, ContentID=content_id, TrackNo=None,
                    UUID=str(uuid4()), created_at=self.now, updated_at=self.now)
                self.db.add(fila)
                self.stats["asignaciones nuevas"] += 1


class Tee:
    """Muestra en pantalla y además guarda todo en Descargas/rekordbox_mytags_log.txt"""
    def __init__(self, ruta):
        self.f = open(ruta, "w", encoding="utf-8")
        self.o = sys.stdout

    def write(self, x):
        self.o.write(x)
        self.f.write(x)
        self.f.flush()

    def flush(self):
        self.o.flush()


def main():
    try:
        sys.stdout = Tee(Path.home() / "Downloads" / "rekordbox_mytags_log.txt")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="My Tags automáticos — KRAMER DJ")
    ap.add_argument("--simular", action="store_true", help="no modifica nada")
    ap.add_argument("--restaurar", action="store_true", help="vuelve al último backup de la base")
    args = ap.parse_args()
    if args.restaurar:
        restaurar()
        return

    print("=" * 72)
    print("MY TAGS — KRAMER DJ" + ("   [SIMULACIÓN: no se modifica nada]" if args.simular else ""))
    print("=" * 72)
    if get_rekordbox_pid():
        print("Rekordbox está abierto. Cerralo y volvé a correr el script.")
        sys.exit(1)

    if not args.simular:
        destino, n = hacer_backup()
        print(f"Backup de la base ({n} archivos): {destino}")

    if os.environ.get("KRAMER_RB_TEST"):
        db = MasterDatabase(path=str(DIR_BASE / "master.db"), unlock=False)
    elif DIR_BASE == plataforma.dir_rekordbox():
        db = MasterDatabase()
    else:
        db = MasterDatabase(path=str(DIR_BASE / "master.db"))
    g = Gestor(db, args.simular)

    # ---------- leer todos los temas ----------
    contenidos = db.get_content().all()
    print(f"Temas en Rekordbox: {len(contenidos)}  ·  leyendo sus archivos...")
    datos, sin_archivo = {}, 0
    paises = set()
    for c in contenidos:
        ruta = Path(str(c.FolderPath or ""))
        if not ruta.is_file():
            sin_archivo += 1
            continue
        com, anio = leer_archivo(ruta)
        pais, idioma = datos_de_comentario(com)
        if not anio and c.ReleaseYear:
            anio = str(c.ReleaseYear)
        datos[str(c.ID)] = (tags_origen(pais), tag_idioma(idioma), tag_decada(anio))
        if pais and region_de(pais) in ("Latinoamérica", "Europa", "Otros"):
            paises.add(pais)

    decadas = sorted({d for (_, _, dd) in datos.values() for d in dd}, key=orden_decada)
    origen = REGIONES + sorted(paises)

    # ---------- categorías y listas de tags ----------
    print("\nPreparando categorías y tags...")
    g.preparar_categorias()
    ids = {
        "1": g.sincronizar_lista("1", origen, borrar_con_temas=True),
        "2": g.sincronizar_lista("2", IDIOMAS, borrar_con_temas=True),
        "3": g.sincronizar_lista("3", decadas, borrar_con_temas=True),
        "4": ({t.Name: t.ID for t in g.tags_de("4")}             # Momento es tuyo: no se toca
              or g.sincronizar_lista("4", MOMENTOS, borrar_con_temas=False)),
    }

    # ---------- asignaciones ----------
    deseado = {}
    conteo = Counter()
    for cid_tema, (o, i, d) in datos.items():
        tag_ids = set()
        for cat, nombres in (("1", o), ("2", i), ("3", d)):
            for nombre in nombres:
                tag_ids.add(ids[cat][nombre])
                conteo[(CATEGORIAS[cat], nombre)] += 1
        deseado[cid_tema] = tag_ids
    g.asignar(ids, deseado)

    sin_origen = sum(1 for (o, _, _) in datos.values() if not o)
    sin_decada = sum(1 for (_, _, d) in datos.values() if not d)

    # ---------- resumen ----------
    print("\nResumen por tag:")
    for cat in ("Origen", "Idioma", "Década"):
        partes = [f"{n} {conteo[(cat, n)]}" for n in
                  (origen if cat == "Origen" else IDIOMAS if cat == "Idioma" else decadas)
                  if conteo[(cat, n)]]
        print(f"   {cat}: " + " · ".join(partes))
    print(f"   Momento: {', '.join(ids['4'])}  (manual: no se modifica)")
    print(f"\nTemas sin país en el comentario: {sin_origen}  ·  sin año: {sin_decada}"
          f"  ·  archivo no encontrado: {sin_archivo}")
    for k, v in g.stats.items():
        print(f"   {k}: {v}")

    if args.simular:
        db.session.rollback()
        db.close()
        print("\nSimulación: no se modificó nada.")
        return
    db.commit()
    db.close()
    print("=" * 72)
    print("Listo. Abrí Rekordbox: los My Tags ya están cargados.")
    print("Si algo no te gusta:  python3.15 rekordbox_mytags.py --restaurar")
    print("=" * 72)


if __name__ == "__main__":
    main()
