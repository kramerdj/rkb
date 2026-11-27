"""Historial de operaciones con backup propio y opción de deshacer (en orden inverso)."""
import datetime
import json
import os
import shutil
import threading
from pathlib import Path

from . import config

ARCHIVOS_BASE = ["master.db", "master.db-wal", "master.db-shm", "masterPlaylists6.xml",
                 "networkAnalyze6.db", "datafile.edb"]
_lock = threading.Lock()


def _indice_viejo():
    return config.dir_backups() / "historial.json"


def _leer_json(p, defecto=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _escribir_nuevo(p, datos):
    """Siempre crea un archivo nuevo (nunca reescribe uno existente): macOS puede impedir
    que la app modifique archivos creados por otra app o por otra versión."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{datetime.datetime.now():%H%M%S%f}.tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        tmp.replace(p)
    except OSError:
        if not p.exists():
            raise


def listar():
    """Cada operación vive en su carpeta (operacion.json); 'deshecho.json' marca las deshechas.
    También muestra las del índice viejo (historial.json) si su carpeta no tiene operacion.json."""
    raiz = config.dir_backups()
    items, vistos = [], set()
    if raiz.exists():
        for d in raiz.iterdir():
            op = _leer_json(d / "operacion.json") if d.is_dir() else None
            if op:
                op["deshecho"] = (d / "deshecho.json").exists()
                items.append(op)
                vistos.add(op["id"])
    for op in _leer_json(_indice_viejo(), []) or []:
        if op.get("id") not in vistos:
            op["deshecho"] = op.get("deshecho") or (Path(op["carpeta"]) / "deshecho.json").exists()
            items.append(op)
    items.sort(key=lambda x: x["cuando"], reverse=True)
    return items


class Operacion:
    """Uso:
        with Operacion("Sincronizar metadata") as op:
            op.respaldar_archivo(ruta)   # antes de modificar cada archivo
            ...
            op.detalle = "3 temas"
    Al entrar copia la base de Rekordbox. Si algo falla, no queda registrada.
    """

    def __init__(self, que, con_base=True):
        self.que, self.con_base = que, con_base
        self.detalle = ""
        self.ts = datetime.datetime.now()
        self.carpeta = config.dir_backups() / self.ts.strftime("%Y-%m-%d_%H%M%S")
        self.archivos = {}
        self.creados = []          # archivos que la operación puso en la colección (Deshacer los saca)
        self.renombrados = {}      # nuevo -> viejo (Deshacer los vuelve a su nombre)
        self.eliminados = {}       # original -> lugar en la carpeta «eliminados» (Deshacer los devuelve)

    def __enter__(self):
        self.carpeta.mkdir(parents=True, exist_ok=True)
        if self.con_base:
            origen = Path(config.cargar()["rekordbox"])
            destino = self.carpeta / "base"
            destino.mkdir(exist_ok=True)
            for n in ARCHIVOS_BASE:
                if (origen / n).exists():
                    shutil.copy2(origen / n, destino / n)
            if not (destino / "master.db").exists():
                raise RuntimeError(f"No encontré master.db en {origen}")
        return self

    def respaldar_archivo(self, ruta):
        ruta = str(ruta)
        if ruta in self.archivos:
            return
        destino = self.carpeta / "archivos" / f"{len(self.archivos):05d}_{Path(ruta).name}"
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ruta, destino)
        self.archivos[ruta] = str(destino)

    def mover_archivo(self, ruta):
        """Saca el archivo de la colección y lo guarda en el backup (se recupera con Deshacer)."""
        ruta = str(ruta)
        destino = self.carpeta / "archivos" / f"{len(self.archivos):05d}_{Path(ruta).name}"
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(ruta, destino)
        self.archivos[ruta] = str(destino)

    def eliminar_archivo(self, ruta):
        """Saca el archivo de la colección y lo deja en la carpeta «eliminados» (no se borra)."""
        ruta = Path(ruta)
        carpeta = config.dir_eliminados()
        carpeta.mkdir(parents=True, exist_ok=True)
        destino, n = carpeta / ruta.name, 2
        while destino.exists():
            destino = carpeta / f"{ruta.stem} ({n}){ruta.suffix}"
            n += 1
        shutil.move(str(ruta), destino)
        self.eliminados[str(ruta)] = str(destino)
        return destino

    def __exit__(self, tipo, valor, tb):
        # Se registra aunque haya fallado a mitad de camino: así siempre se puede deshacer.
        if tipo is not None and not self.archivos and not self.con_base:
            return False
        _escribir_nuevo(self.carpeta / "archivos.json", self.archivos)
        if self.creados:
            _escribir_nuevo(self.carpeta / "creados.json", self.creados)
        if self.renombrados:
            _escribir_nuevo(self.carpeta / "renombrados.json", self.renombrados)
        if self.eliminados:
            _escribir_nuevo(self.carpeta / "eliminados.json", self.eliminados)
        que = self.que + (" (con error: revisala)" if tipo is not None else "")
        detalle = self.detalle if tipo is None else f"{self.detalle} · error: {valor}".strip(" ·")
        with _lock:
            _escribir_nuevo(self.carpeta / "operacion.json", {
                "id": self.carpeta.name, "cuando": self.ts.isoformat(timespec="seconds"),
                "que": que, "detalle": detalle, "carpeta": str(self.carpeta),
                "con_base": self.con_base, "archivos": len(self.archivos)})
        return False


def deshacer(op_id):
    """Sólo se puede deshacer la última operación vigente (las posteriores ya deshechas)."""
    with _lock:
        items = listar()
        vigentes = [i for i in items if not i["deshecho"]]
        if not vigentes or vigentes[0]["id"] != op_id:
            raise ValueError("Primero deshacé las operaciones más nuevas (se deshacen en orden).")
        op = vigentes[0]
        carpeta = Path(op["carpeta"])
        if op.get("con_base"):
            destino = Path(config.cargar()["rekordbox"])
            for n in ARCHIVOS_BASE:
                src, dst = carpeta / "base" / n, destino / n
                if src.exists():
                    shutil.copy2(src, dst)
                elif n.endswith(("-wal", "-shm")) and dst.exists():
                    dst.unlink()
        try:
            mapa = json.loads((carpeta / "archivos.json").read_text(encoding="utf-8"))
        except Exception:
            mapa = {}
        for nuevo, viejo in (_leer_json(carpeta / "renombrados.json", {}) or {}).items():
            if Path(nuevo).exists() and not Path(viejo).exists():
                os.rename(nuevo, viejo)
        for original, apartado in (_leer_json(carpeta / "eliminados.json", {}) or {}).items():
            if Path(apartado).exists() and not Path(original).exists():
                Path(original).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(apartado, original)
        for creado in _leer_json(carpeta / "creados.json", []) or []:
            if Path(creado).exists() and creado not in mapa:
                Path(creado).unlink()
        for original, copia in mapa.items():
            if Path(copia).exists():
                Path(original).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(copia, original)
        _escribir_nuevo(carpeta / "deshecho.json", {"cuando": datetime.datetime.now().isoformat(timespec="seconds")})
        op["deshecho"] = True
        return op
