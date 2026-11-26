"""Cambia control/versiones.json (lo usan los botones de GitHub Actions).

    python control/control.py publicada 0.9.2 [--obligatoria --dias 7] [--mensaje "..."]
    python control/control.py obligar 0.9.2 --dias 7 [--mensaje "..."]
    python control/control.py liberar
"""
import argparse
import datetime
import json
import re
from pathlib import Path

ARCHIVO = Path(__file__).resolve().parent / "versiones.json"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("accion", choices=["publicada", "obligar", "liberar"])
    p.add_argument("version", nargs="?")
    p.add_argument("--obligatoria", action="store_true")
    p.add_argument("--dias", type=int, default=7)
    p.add_argument("--mensaje", default=None)
    a = p.parse_args()
    if a.accion != "liberar" and not re.fullmatch(r"\d+(\.\d+)*", a.version or ""):
        raise SystemExit(f"La versión «{a.version}» no es un número con puntos (por ejemplo 0.9.2).")
    if a.dias < 0:
        raise SystemExit("Los días de gracia no pueden ser negativos.")
    d = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    if a.accion == "publicada":
        d["ultima"] = a.version
    if a.accion == "obligar" or a.obligatoria:
        d.update(minima=a.version, minima_desde=datetime.date.today().isoformat(), gracia_dias=a.dias)
    if a.accion == "liberar":
        d.update(minima=None, minima_desde=None)
    if a.mensaje is not None:
        d["mensaje"] = a.mensaje.strip()
    ARCHIVO.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(d, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
