"""Entorno común de las pruebas. Cada archivo de pruebas lo importa antes que cualquier módulo de la app:
la configuración va a una carpeta temporal (nunca la real) y no se consulta nada en internet."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="rkb-test-"))

os.environ["KRAMER_APP_DIR"] = str(TMP / "app")
os.environ["KRAMER_CONTROL_URL"] = ""
for variable in ("KRAMER_NUBE_URL", "KRAMER_NUBE_CLAVE", "KRAMER_ACTUALIZACION_URL", "KRAMER_ACTUALIZACION_CLAVE",
                 "KRAMER_RB_TEST", "KRAMER_RB_DIR", "KRAMER_RB_BACKUPS"):
    os.environ.pop(variable, None)

sys.path.insert(0, str(RAIZ))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)


def carpeta():
    return Path(tempfile.mkdtemp(dir=TMP))
