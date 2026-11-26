"""Limpieza de backups: tamaños y borrado de los que ya no hacen falta."""
import datetime
import os
import shutil
from pathlib import Path

from . import config, historial


def _tam(p):
    p = Path(p)
    if p.is_file():
        return p.stat().st_size
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def listar():
    raiz = Path(config.cargar()["backup"])
    ops = {h["id"]: h for h in historial.listar()}
    app = config.dir_backups()
    items = []
    if app.is_dir():
        for d in app.iterdir():
            if d.is_dir():
                h = ops.get(d.name)
                fecha = datetime.datetime.fromtimestamp(d.stat().st_mtime)
                items.append({"ruta": str(d), "nombre": h["que"] if h else d.name, "tipo": "operacion",
                              "fecha": (h["cuando"][:10] if h else fecha.strftime("%Y-%m-%d")),
                              "deshecho": bool(h and h.get("deshecho")), "bytes": _tam(d)})
    if raiz.is_dir():
        for d in raiz.iterdir():
            if d.name.startswith(".") or d == app:
                continue
            fecha = datetime.datetime.fromtimestamp(d.stat().st_mtime)
            items.append({"ruta": str(d), "nombre": d.name, "tipo": "otro", "fecha": fecha.strftime("%Y-%m-%d"),
                          "deshecho": False, "bytes": _tam(d)})
    items.sort(key=lambda x: (x["tipo"] != "operacion", x["fecha"]), reverse=False)
    return {"carpeta": str(raiz), "items": items, "total": sum(i["bytes"] for i in items)}


def borrar(rutas):
    raiz = Path(config.cargar()["backup"]).resolve()
    liberado, errores = 0, []
    for r in rutas:
        p = Path(r).resolve()
        if raiz not in p.parents:                 # nunca fuera de la carpeta de backups
            errores.append(f"{p.name}: está fuera de la carpeta de backups")
            continue
        try:
            t = _tam(p)
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            liberado += t
        except Exception as e:
            errores.append(f"{p.name}: {e}")
    return {"liberado": liberado, "errores": errores}
