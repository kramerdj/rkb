"""Backup completo y restauración: la base de Rekordbox (zip con fecha) y la colección musical (copia espejo).

Estructura en la carpeta de destino (idealmente un disco externo):
    Base de Rekordbox/RKB base AAAA-MM-DD HHMM.zip   master.db, playlists, análisis (share) + manifiesto.json
    Colección/musica/...                              copia espejo de la carpeta de la colección
    Colección/otros/...                               temas de Rekordbox que están fuera de esa carpeta
    Colección/indice.json                             de dónde vino cada archivo
    Colección/_quitados/AAAA-MM-DD/...                lo que ya no está en la colección (nunca se borra solo)
"""
import gc
import datetime
import json
import os
import shutil
import sys
import unicodedata
import zipfile
from pathlib import Path

from . import config, plataforma

ARCHIVOS_BASE = ["master.db", "master.db-wal", "master.db-shm", "masterPlaylists6.xml",
                 "networkAnalyze6.db", "datafile.edb", "masterPlaylists3.xml"]
DIR_BASE, DIR_COL = "Base de Rekordbox", "Colección"
OCULTOS = {".DS_Store", "Thumbs.db", "desktop.ini"}
TOLERANCIA = 2.1          # segundos: los discos externos FAT/exFAT guardan la hora de a 2 s


class ErrorRespaldo(Exception):
    pass


# ---------------------------------------------------------------- utilidades
def destino():
    c = config.cargar()
    return Path(c.get("respaldo_destino") or Path(c["backup"]) / "Respaldos RKB")


def _clave(p):
    return unicodedata.normalize("NFC", str(p)).replace("\\", "/").casefold()


def _dentro(hijo, padre):
    h, p = _clave(Path(hijo).resolve()).rstrip("/") + "/", _clave(Path(padre).resolve()).rstrip("/") + "/"
    return h.startswith(p)


def _tam(p):
    total = 0
    for raiz, dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(raiz, f))
            except OSError:
                pass
    return total


def _igual(a_bytes, a_mtime, ruta_b):
    try:
        st = os.stat(ruta_b)
    except OSError:
        return False
    return st.st_size == a_bytes and abs(st.st_mtime - a_mtime) <= TOLERANCIA


def _escribir_json(p, datos):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{datetime.datetime.now():%H%M%S%f}.tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _leer_json(p, defecto=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _libre(p):
    p = Path(p)
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


def _libre_seguro(p):
    try:
        return _libre(p)
    except OSError:
        return None


def _gb(b):
    return f"{b / 1e9:.1f} GB" if b >= 1e9 else f"{b / 1e6:.0f} MB"


def _validar_destino(dest):
    col = Path(config.cargar()["coleccion"])
    if col.is_dir() and _dentro(dest, col):
        raise ErrorRespaldo("La carpeta de backups no puede estar adentro de la carpeta de la colección. Elegí otra (idealmente un disco externo).")
    if _dentro(dest, config.cargar()["rekordbox"]):
        raise ErrorRespaldo("La carpeta de backups no puede estar adentro de la carpeta de Rekordbox.")


# ---------------------------------------------------------------- estado
def _entero(v):
    """Un dato del manifiesto de un zip (que puede venir de otra computadora) sólo vale si es un número."""
    return v if type(v) is int else None


def estado():
    dest = destino()
    c = config.cargar()
    rb_dir = Path(c["rekordbox"])
    bases = []
    for z in sorted((dest / DIR_BASE).glob("*.zip"), reverse=True) if (dest / DIR_BASE).is_dir() else []:
        man = {}
        try:
            with zipfile.ZipFile(z) as zf:
                man = json.loads(zf.read("manifiesto.json"))
        except Exception:
            man = {"error": "no se pudo leer"}
        bases.append({"ruta": str(z), "nombre": z.name, "bytes": z.stat().st_size,
                      "fecha": man.get("fecha") or datetime.datetime.fromtimestamp(z.stat().st_mtime).isoformat(timespec="minutes"),
                      "share": bool(man.get("share")), "temas": _entero(man.get("temas")), "playlists": _entero(man.get("playlists")),
                      "sistema": man.get("sistema", ""), "motivo": man.get("motivo", ""), "valido": "error" not in man})
    ind = _leer_json(dest / DIR_COL / "indice.json")
    col = None
    if ind:
        arch = ind.get("archivos", {})
        col = {"actualizado": ind.get("actualizado"), "archivos": len(arch),
               "bytes": sum(a.get("bytes", 0) for a in arch.values()),
               "otros": sum(1 for k in arch if k.startswith("otros/")), "sistema": ind.get("sistema", "")}
    quitados = []
    q = dest / DIR_COL / "_quitados"
    if q.is_dir():
        for d in sorted(q.iterdir(), reverse=True):
            if d.is_dir():
                quitados.append({"nombre": d.name, "ruta": str(d)})
    share = rb_dir / "share"
    return {"destino": str(dest), "destinoExiste": dest.is_dir(), "libre": _libre_seguro(dest),
            "bases": bases, "coleccion": col, "quitados": quitados,
            "rekordbox": str(rb_dir), "hayShare": share.is_dir(), "carpetaColeccion": c["coleccion"],
            "opciones": {"share": c.get("respaldo_share", True), "otros": c.get("respaldo_otros", True)}}


def tam_share():
    return _tam(Path(config.cargar()["rekordbox"]) / "share")


# ---------------------------------------------------------------- backup de la base
def _contar_base():
    try:
        from . import rb
        with rb.lock:
            db = rb.abrir()
            try:
                from pyrekordbox.masterdb import models as m
                temas = db.get_content().count()
                pls = db.query(m.DjmdPlaylist).filter(m.DjmdPlaylist.Attribute == 0).count()
                return temas, pls
            finally:
                db.close()
    except Exception:
        return None, None


def backup_base(t=None, con_share=True, motivo="manual", dest=None):
    """Zip con la base de Rekordbox (y opcionalmente la carpeta share). Devuelve la ruta del zip."""
    c = config.cargar()
    rb_dir = Path(c["rekordbox"])
    if not (rb_dir / "master.db").is_file():
        raise ErrorRespaldo(f"No encontré la base de Rekordbox (master.db) en {rb_dir}.")
    dest = Path(dest or destino()) / DIR_BASE
    dest.mkdir(parents=True, exist_ok=True)
    temas, pls = _contar_base()
    ahora = datetime.datetime.now()
    extra = " (antes de restaurar)" if motivo == "antes de restaurar" else ""
    zpath = dest / f"RKB base {ahora:%Y-%m-%d %H%M%S}{extra}.zip"
    archivos = [(rb_dir / n, n) for n in ARCHIVOS_BASE if (rb_dir / n).is_file()]
    share = rb_dir / "share"
    if con_share and share.is_dir():
        for raiz, dirs, files in os.walk(share):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f in OCULTOS or f.startswith("._"):
                    continue
                p = Path(raiz) / f
                archivos.append((p, p.relative_to(rb_dir).as_posix()))
    total = sum(p.stat().st_size for p, _ in archivos)
    if _libre(dest) < total * 1.05 + 50e6:
        raise ErrorRespaldo(f"No hay lugar suficiente en {dest} (hacen falta ~{_gb(total)}).")
    if t:
        t.total += len(archivos)
    tmp = zpath.with_suffix(".parcial")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as zf:
            zf.writestr("manifiesto.json", json.dumps({
                "app": "RKB Collection Manager", "tipo": "base", "fecha": ahora.isoformat(timespec="seconds"),
                "sistema": "windows" if plataforma.ES_WIN else "mac", "rekordbox": str(rb_dir),
                "share": bool(con_share and share.is_dir()), "temas": temas, "playlists": pls,
                "motivo": motivo, "archivos": len(archivos), "bytes": total}, ensure_ascii=False, indent=1))
            for i, (p, nombre) in enumerate(archivos):
                if t and t.cancelar:
                    raise ErrorRespaldo("Cancelado.")
                comp = zipfile.ZIP_STORED if p.suffix.lower() in (".jpg", ".jpeg", ".png") else zipfile.ZIP_DEFLATED
                zf.write(p, nombre, compress_type=comp)
                if t and (i % 25 == 0 or i == len(archivos) - 1):
                    t.mensaje = f"Base de Rekordbox: {i + 1} de {len(archivos)} archivos"
                if t:
                    t.hechos += 1
        os.replace(tmp, zpath)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return {"zip": str(zpath), "bytes": zpath.stat().st_size, "temas": temas, "playlists": pls}


# ---------------------------------------------------------------- backup de la colección
def _relativo_otros(ruta):
    p = Path(ruta)
    partes = list(p.parts)
    ancla = partes.pop(0) if p.anchor else ""
    letra = ancla.replace(":", "").strip("\\/")             # "C:\\" -> "C", "/" -> ""
    return "/".join(["otros"] + ([letra] if letra else []) + partes)


def _fuera_de_la_carpeta(col):
    """Temas de Rekordbox cuyo archivo existe pero está fuera de la carpeta de la colección."""
    try:
        from . import rb
        with rb.lock:
            db = rb.abrir()
            try:
                rutas = [c.FolderPath for c in db.get_content() if c.FolderPath]
            finally:
                db.close()
    except Exception:
        return []
    fuera, vistos = [], set()
    for r in rutas:
        k = _clave(r)
        if k in vistos or "/samples/" in k or "/sampler/" in k:
            continue
        vistos.add(k)
        if not _dentro(r, col) and os.path.isfile(r):
            fuera.append(r)
    return fuera


def backup_coleccion(t=None, con_otros=True, dest=None):
    """Copia espejo incremental: copia sólo lo nuevo o cambiado; lo que ya no está va a _quitados."""
    c = config.cargar()
    col = Path(c["coleccion"])
    if not col.is_dir():
        raise ErrorRespaldo(f"No encuentro la carpeta de la colección: {col}")
    raiz = Path(dest or destino()) / DIR_COL
    _validar_destino(raiz)
    if t:
        t.mensaje = "Revisando la colección…"
    # 1) qué hay que tener en el backup
    quiero = {}                                    # ruta en backup -> ruta original
    for base, dirs, files in os.walk(col):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f in OCULTOS or f.startswith("._") or f.startswith("."):
                continue
            p = Path(base) / f
            quiero["musica/" + p.relative_to(col).as_posix()] = str(p)
    if con_otros:
        for r in _fuera_de_la_carpeta(col):
            quiero.setdefault(_relativo_otros(r), r)
    ind_viejo = _leer_json(raiz / "indice.json", {}) or {}
    viejos = ind_viejo.get("archivos", {})
    # 2) qué falta copiar
    copiar, total_bytes, info = [], 0, {}
    for rel, origen in quiero.items():
        try:
            st = os.stat(origen)
        except OSError:
            continue
        info[rel] = {"origen": origen, "bytes": st.st_size, "mtime": st.st_mtime}
        if not _igual(st.st_size, st.st_mtime, raiz / rel):
            copiar.append(rel)
            total_bytes += st.st_size
    if total_bytes and _libre(raiz) < total_bytes * 1.02 + 100e6:
        raise ErrorRespaldo(f"No hay lugar suficiente en el destino: hay que copiar {_gb(total_bytes)} "
                            f"y quedan {_gb(_libre(raiz))} libres.")
    quitar = [rel for rel in viejos if rel not in info]
    if t:
        t.total += len(copiar) + len(quitar)
    # 3) copiar
    copiados, hechos_b = 0, 0
    for rel in copiar:
        if t and t.cancelar:
            break
        d = raiz / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        tmp = d.with_name(d.name + ".parcial")
        shutil.copy2(info[rel]["origen"], tmp)
        os.replace(tmp, d)
        copiados += 1
        hechos_b += info[rel]["bytes"]
        if t:
            t.hechos += 1
            t.mensaje = f"Colección: {copiados} de {len(copiar)} archivos nuevos o cambiados · {_gb(hechos_b)} de {_gb(total_bytes)}"
    # 4) lo que ya no está en la colección: se aparta (no se borra)
    apartados = 0
    if not (t and t.cancelar):
        hoy = raiz / "_quitados" / datetime.date.today().isoformat()
        for rel in quitar:
            src = raiz / rel
            if src.is_file():
                dst = hoy / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                apartados += 1
            if t:
                t.hechos += 1
        _limpiar_vacias(raiz / "musica")
        _limpiar_vacias(raiz / "otros")
    # 5) índice (si se canceló, guardo lo que quedó copiado igual)
    final = {}
    for rel, i in info.items():
        if _igual(i["bytes"], i["mtime"], raiz / rel):
            final[rel] = i
        elif rel in viejos and (raiz / rel).is_file():
            final[rel] = viejos[rel]
    _escribir_json(raiz / "indice.json", {
        "app": "RKB Collection Manager", "actualizado": datetime.datetime.now().isoformat(timespec="seconds"),
        "coleccion": str(col), "sistema": "windows" if plataforma.ES_WIN else "mac", "archivos": final})
    return {"copiados": copiados, "bytes": hechos_b, "apartados": apartados, "total": len(final),
            "otros": sum(1 for k in final if k.startswith("otros/")), "cancelado": bool(t and t.cancelar)}


def _limpiar_vacias(d):
    if not Path(d).is_dir():
        return
    for base, dirs, files in os.walk(d, topdown=False):
        for x in dirs:
            p = Path(base) / x
            try:
                restos = [f for f in p.iterdir() if f.name not in OCULTOS]
                if not restos:
                    for f in p.iterdir():
                        f.unlink()
                    p.rmdir()
            except OSError:
                pass


def backup_completo(t, base=True, coleccion=True, con_share=True, con_otros=True):
    dest = destino()
    _validar_destino(dest)
    dest.mkdir(parents=True, exist_ok=True)
    r = {}
    if base:
        r["base"] = backup_base(t, con_share=con_share)
    if coleccion and not t.cancelar:
        r["coleccion"] = backup_coleccion(t, con_otros=con_otros)
    return r


# ---------------------------------------------------------------- restaurar la base
def _zip_valido(ruta):
    ruta = Path(ruta)
    if ruta.suffix.lower() != ".zip" or not ruta.is_file():
        raise ErrorRespaldo("No encuentro ese backup.")
    with zipfile.ZipFile(ruta) as zf:
        nombres = zf.namelist()
        if "master.db" not in nombres:
            raise ErrorRespaldo("Ese zip no es un backup de la base de Rekordbox (no tiene master.db).")
        for n in nombres:                       # nada que se escape de la carpeta de Rekordbox
            if n.startswith(("/", "\\")) or ".." in Path(n).parts or ":" in n:
                raise ErrorRespaldo(f"El backup tiene una ruta inválida: {n}")
        man = json.loads(zf.read("manifiesto.json")) if "manifiesto.json" in nombres else {}
    return nombres, man


def restaurar_base(t, ruta, con_share=True):
    nombres, man = _zip_valido(ruta)
    rb_dir = Path(config.cargar()["rekordbox"])
    incluye_share = con_share and any(n.startswith("share/") for n in nombres)
    # 1) red de seguridad: backup de la base actual antes de pisarla
    t.mensaje = "Guardando la base actual por las dudas…"
    previo = None
    if (rb_dir / "master.db").is_file():
        previo = backup_base(t, con_share=incluye_share, motivo="antes de restaurar")
    if t.cancelar:
        raise ErrorRespaldo("Cancelado antes de tocar nada.")
    # 2) restaurar
    a_extraer = [n for n in nombres if n != "manifiesto.json" and not n.endswith("/")
                 and (n in ARCHIVOS_BASE or (incluye_share and n.startswith("share/")))]
    t.total += len(a_extraer)
    with zipfile.ZipFile(ruta) as zf:
        for i, n in enumerate(a_extraer):
            destino_f = rb_dir / n
            destino_f.parent.mkdir(parents=True, exist_ok=True)
            tmp = destino_f.with_name(destino_f.name + ".restaurando")
            with zf.open(n) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            try:
                os.replace(tmp, destino_f)
            except PermissionError:
                gc.collect()            # Windows: una conexión a la base que quedó sin cerrar la mantiene tomada
                os.replace(tmp, destino_f)
            t.hechos += 1
            if i % 25 == 0 or i == len(a_extraer) - 1:
                t.mensaje = f"Restaurando la base: {i + 1} de {len(a_extraer)} archivos"
    for n in ("master.db-wal", "master.db-shm"):       # con la base ya restaurada: si el backup no los trae,
        if n not in nombres and (rb_dir / n).exists():  # los que quedaron son de la base anterior y no sirven
            (rb_dir / n).unlink()
    return {"restaurados": len(a_extraer), "previo": previo["zip"] if previo else None,
            "fecha": man.get("fecha"), "share": incluye_share,
            "otroSistema": bool(man.get("sistema")) and man.get("sistema") != ("windows" if plataforma.ES_WIN else "mac")}


# ---------------------------------------------------------------- restaurar la colección
def restaurar_coleccion(t, modo="faltantes", carpeta=None):
    """modo: 'faltantes' (sólo lo que no está) o 'todos' (también pisa lo que cambió).
    carpeta: restaurar desde una carpeta de _quitados en vez de la copia espejo."""
    dest = destino()
    raiz = dest / DIR_COL
    ind = _leer_json(raiz / "indice.json")
    if not ind:
        raise ErrorRespaldo("Todavía no hay un backup de la colección en la carpeta de backups.")
    col = Path(config.cargar()["coleccion"])
    origen_base = raiz
    entradas = ind.get("archivos", {})
    if carpeta:
        origen_base = Path(carpeta)
        if not _dentro(origen_base, raiz / "_quitados"):
            raise ErrorRespaldo("Esa carpeta no está dentro de los backups de la colección.")
        entradas = {}
        for base, dirs, files in os.walk(origen_base):
            for f in files:
                if f in OCULTOS:
                    continue
                rel = (Path(base) / f).relative_to(origen_base).as_posix()
                entradas[rel] = {}
    plan = []
    for rel, i in entradas.items():
        src = origen_base / rel
        if not src.is_file():
            continue
        if rel.startswith("musica/"):
            dst = col / rel[len("musica/"):]
        elif rel.startswith("otros/"):
            dst = Path(i.get("origen") or "")
            if not i.get("origen"):          # de _quitados: buscar el origen en el índice viejo
                continue
        else:
            continue
        if dst.exists():
            if modo != "todos":
                continue
            st = src.stat()
            if _igual(st.st_size, st.st_mtime, dst):
                continue
        plan.append((src, dst))
    total = sum(s.stat().st_size for s, _ in plan)
    if plan and _libre(col if col.exists() else col.parent) < total + 100e6:
        raise ErrorRespaldo(f"No hay lugar suficiente para restaurar {_gb(total)}.")
    t.total += len(plan)
    hechos, hb, errores = 0, 0, []
    for src, dst in plan:
        if t.cancelar:
            break
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".restaurando")
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
            hechos += 1
            hb += src.stat().st_size
        except OSError as e:
            errores.append(f"{dst.name}: {e}")
        t.hechos += 1
        t.mensaje = f"Restaurando: {hechos} de {len(plan)} archivos · {_gb(hb)}"
    return {"restaurados": hechos, "bytes": hb, "errores": errores[:20], "nErrores": len(errores),
            "cancelado": t.cancelar}


def borrar_base(ruta):
    p = Path(ruta).resolve()
    if not _dentro(p, destino() / DIR_BASE) or p.suffix.lower() != ".zip":
        raise ErrorRespaldo("Sólo se pueden borrar backups de la carpeta de backups.")
    p.unlink()
