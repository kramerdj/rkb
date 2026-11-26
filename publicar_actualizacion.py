"""Herramienta del desarrollador: arma y firma un paquete de actualización con kramer/ + web/.

    python publicar_actualizacion.py generar-clave --clave-privada RUTA
    python publicar_actualizacion.py armar --clave-privada RUTA --salida CARPETA

La clave privada va siempre fuera de la carpeta del proyecto. La versión del paquete sale de web/version.txt.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path

from nacl.signing import SigningKey

import kramer_arranque

RAIZ = Path(__file__).resolve().parent


def _fuera_del_proyecto(ruta):
    ruta = Path(ruta).expanduser().resolve()
    if ruta == RAIZ or RAIZ in ruta.parents:
        sys.exit("La clave privada no puede estar dentro de la carpeta del proyecto. Elegí otra ruta.")
    return ruta


def generar_clave(ruta):
    ruta = _fuera_del_proyecto(ruta)
    clave = SigningKey.generate()
    try:
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        sys.exit(f"Ya existe {ruta}. No la piso: si la perdés, las apps instaladas dejan de aceptar actualizaciones.")
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(clave.encode().hex() + "\n")
    print(f"Clave privada guardada en {ruta} (guardala bien y hacé una copia: no se puede recuperar).")
    print(f"Clave pública, para CLAVE_PUBLICA en kramer_arranque.py: {clave.verify_key.encode().hex()}")


def _archivos():
    for carpeta in ("kramer", "web"):
        for f in sorted((RAIZ / carpeta).rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc" and f.name != ".DS_Store":
                yield f.relative_to(RAIZ).as_posix(), f.read_bytes()


def armar_zip():
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        for nombre, datos in _archivos():
            if not kramer_arranque.ruta_valida(nombre):
                sys.exit(f"Nombre de archivo no permitido en un paquete: {nombre}")
            info = zipfile.ZipInfo(nombre, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o644 << 16
            z.writestr(info, datos, zipfile.ZIP_DEFLATED, 9)
    return memoria.getvalue()


def armar(ruta_clave, salida, shell):
    clave = SigningKey(bytes.fromhex(_fuera_del_proyecto(ruta_clave).read_text(encoding="ascii").strip()))
    publica = clave.verify_key.encode().hex()
    if kramer_arranque.CLAVE_PUBLICA and publica != kramer_arranque.CLAVE_PUBLICA:
        sys.exit("Esa clave privada no corresponde a la CLAVE_PUBLICA de kramer_arranque.py: las apps rechazarían el paquete.")
    version = (RAIZ / "web" / "version.txt").read_text(encoding="utf-8").strip()
    datos = armar_zip()
    manifiesto = json.dumps({"version": version, "shell": shell, "sha256": hashlib.sha256(datos).hexdigest(),
                             "tamano": len(datos), "archivo": f"codigo-{version}.zip"}, sort_keys=True)
    firma = clave.sign(manifiesto.encode("utf-8")).signature.hex()
    sobre = json.dumps({"manifiesto": manifiesto, "firma": firma}, indent=1).encode("utf-8")
    try:
        kramer_arranque.comprobar_zip(datos, kramer_arranque.leer_sobre(sobre, publica))
    except kramer_arranque.PaqueteInvalido as e:
        sys.exit(f"El paquete armado no pasa la verificación ({e}). No escribí nada.")
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / f"codigo-{version}.zip").write_bytes(datos)
    (salida / "manifiesto.json").write_bytes(sobre)
    print(f"Paquete {version} (shell {shell}, {len(datos)} bytes) listo en {salida}:")
    print(f" · codigo-{version}.zip  sha256 {hashlib.sha256(datos).hexdigest()}")
    print(" · manifiesto.json")
    print(f"Clave pública que lo firma: {publica}")
    print("Subí primero el zip y después manifiesto.json a la carpeta de KRAMER_ACTUALIZACION_URL.")


def main():
    p = argparse.ArgumentParser(description="Arma y firma paquetes de actualización de RKB Collection Manager.")
    sub = p.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("generar-clave", help="crea un par de claves Ed25519")
    g.add_argument("--clave-privada", required=True, help="archivo nuevo, fuera de la carpeta del proyecto")
    a = sub.add_parser("armar", help="arma el zip, lo firma y deja manifiesto + zip listos para subir")
    a.add_argument("--clave-privada", required=True, help="archivo de la clave privada")
    a.add_argument("--salida", required=True, help="carpeta donde dejar manifiesto.json y el zip")
    args = p.parse_args()
    if args.comando == "generar-clave":
        generar_clave(args.clave_privada)
    else:
        armar(args.clave_privada, args.salida, kramer_arranque.SHELL)


if __name__ == "__main__":
    main()
