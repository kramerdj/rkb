"""Versión obligatoria: el archivo control/versiones.json, la herramienta que lo cambia y cómo lo lee la app."""
import datetime
import importlib.util
import json
import unittest
from unittest import mock

import entorno

from kramer import nube

_spec = importlib.util.spec_from_file_location("control", entorno.RAIZ / "control" / "control.py")
control = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(control)

HOY = datetime.date.today()


def hace(dias):
    return (HOY - datetime.timedelta(days=dias)).isoformat()


class Herramienta(unittest.TestCase):
    """control/control.py, lo que corren los botones de GitHub."""

    def setUp(self):
        self.archivo = entorno.carpeta() / "versiones.json"
        self.archivo.write_text(json.dumps({"ultima": "0.9.1", "minima": None, "minima_desde": None, "gracia_dias": 7, "mensaje": ""}))

    def correr(self, *args):
        with mock.patch.object(control, "ARCHIVO", self.archivo), mock.patch("sys.argv", ["control.py", *args]), \
                mock.patch("builtins.print"):
            control.main()
        return json.loads(self.archivo.read_text(encoding="utf-8"))

    def test_el_archivo_del_repositorio_es_valido(self):
        d = json.loads((entorno.RAIZ / "control" / "versiones.json").read_text(encoding="utf-8"))
        self.assertEqual(set(d), {"ultima", "minima", "minima_desde", "gracia_dias", "mensaje"})
        self.assertRegex(d["ultima"], r"^\d+(\.\d+)*$")
        if d["minima"]:
            self.assertLessEqual(nube._num(d["minima"]), nube._num(d["ultima"]))
            datetime.date.fromisoformat(d["minima_desde"])

    def test_publicada_no_obliga(self):
        d = self.correr("publicada", "0.9.2", "--mensaje", " Arregla My Tags ")
        self.assertEqual((d["ultima"], d["minima"], d["minima_desde"], d["mensaje"]), ("0.9.2", None, None, "Arregla My Tags"))

    def test_publicada_obligatoria(self):
        d = self.correr("publicada", "0.9.2", "--obligatoria", "--dias", "3")
        self.assertEqual((d["ultima"], d["minima"], d["minima_desde"], d["gracia_dias"]), ("0.9.2", "0.9.2", HOY.isoformat(), 3))

    def test_obligar_y_liberar(self):
        d = self.correr("obligar", "0.9.1", "--dias", "10")
        self.assertEqual((d["ultima"], d["minima"], d["gracia_dias"]), ("0.9.1", "0.9.1", 10))
        d = self.correr("liberar")
        self.assertEqual((d["ultima"], d["minima"], d["minima_desde"]), ("0.9.1", None, None))

    def test_sin_mensaje_conserva_el_anterior(self):
        self.correr("publicada", "0.9.2", "--mensaje", "Novedad")
        self.assertEqual(self.correr("obligar", "0.9.2")["mensaje"], "Novedad")

    def test_rechaza_versiones_y_dias_invalidos(self):
        antes = self.archivo.read_text()
        for args in (("publicada", "0.9.2-beta"), ("obligar", ""), ("obligar",), ("publicada", "v0.9.2"), ("obligar", "0.9.1", "--dias", "-1")):
            with self.assertRaises(SystemExit, msg=args):
                self.correr(*args)
            self.assertEqual(self.archivo.read_text(), antes, args)

    @unittest.expectedFailure
    def test_no_deja_obligar_una_version_que_no_esta_publicada(self):
        """Hoy acepta cualquier número: un error de tipeo (0.91 por 0.9.1) bloquearía todas las apps instaladas
        al terminar la gracia, sin ninguna versión que las destrabe (ver la revisión, «Versión obligatoria»)."""
        with self.assertRaises(SystemExit):
            self.correr("obligar", "0.91")


class Aviso(unittest.TestCase):
    """nube.novedades: qué le dice la app al usuario según el archivo de control."""

    def control(self, d):
        viejos = nube._control, nube.CONTROL_URL
        nube._control, nube.CONTROL_URL = (lambda forzar: d), "https://ejemplo"
        self.addCleanup(lambda: (setattr(nube, "_control", viejos[0]), setattr(nube, "CONTROL_URL", viejos[1])))

    def test_al_dia(self):
        self.control({"ultima": "0.9.1", "minima": None, "minima_desde": None, "gracia_dias": 7, "mensaje": ""})
        d = nube.novedades("0.9.1")
        self.assertEqual((d["hayNueva"], d["bloqueo"], d["offline"]), (False, False, False))

    def test_hay_una_nueva_sin_obligar(self):
        self.control({"ultima": "0.10", "minima": None, "mensaje": "Novedades"})
        d = nube.novedades("0.9.1")
        self.assertEqual((d["hayNueva"], d["bloqueo"], d["ultima"], d["mensaje"]), (True, False, "0.10", "Novedades"))
        self.assertIn("releases/latest/download/RKB-Collection-Manager-", d["link"])

    def test_gracia_y_bloqueo(self):
        base = {"ultima": "0.9.2", "minima": "0.9.2", "gracia_dias": 7}
        self.control({**base, "minima_desde": hace(0)})
        self.assertEqual((nube.novedades("0.9.1")["bloqueo"], nube.novedades("0.9.1")["diasGracia"]), (False, 7))
        self.control({**base, "minima_desde": hace(7)})
        self.assertEqual((nube.novedades("0.9.1")["bloqueo"], nube.novedades("0.9.1")["diasGracia"]), (False, 0))
        self.control({**base, "minima_desde": hace(8)})
        self.assertTrue(nube.novedades("0.9.1")["bloqueo"])
        self.assertFalse(nube.novedades("0.9.2")["bloqueo"])
        self.assertFalse(nube.novedades("0.9.10")["bloqueo"])

    def test_archivo_roto_nunca_bloquea(self):
        for roto in ({}, {"ultima": None, "minima": None}, {"ultima": "no es una versión", "minima": "tampoco", "minima_desde": hace(30)},
                     {"ultima": "0.9.2", "minima": "", "minima_desde": hace(30)}, {"ultima": ["0.9.2"], "minima": {"x": 1}, "gracia_dias": "siete"},
                     {"ultima": "0.9.2", "minima": 0, "gracia_dias": None, "minima_desde": 12345}):
            with self.subTest(control=roto):
                self.control(roto)
                self.assertFalse(nube.novedades("0.9.1").get("bloqueo", False))

    def test_sin_internet_nunca_bloquea(self):
        self.control(None)
        self.assertEqual(nube.novedades("0.1"), {"activo": False, "offline": True})

    def test_fecha_ilegible_no_rompe(self):
        self.control({"ultima": "0.9.2", "minima": "0.9.2", "gracia_dias": 7, "minima_desde": "mañana"})
        self.assertIn("bloqueo", nube.novedades("0.9.1"))

    @unittest.expectedFailure
    def test_una_minima_que_nadie_puede_instalar_no_bloquea(self):
        """Hoy una versión mínima mayor que la última publicada bloquea igual, y no hay descarga que lo arregle
        (ver la revisión, «Versión obligatoria»)."""
        self.control({"ultima": "0.9.1", "minima": "0.91", "gracia_dias": 0, "minima_desde": hace(30)})
        self.assertFalse(nube.novedades("0.9.1")["bloqueo"])


if __name__ == "__main__":
    unittest.main()
