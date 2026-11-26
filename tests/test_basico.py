"""Pruebas rápidas que corren solas en cada cambio (no necesitan Rekordbox ni música).

    python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
TMP = Path(tempfile.mkdtemp(prefix="rkb-test-"))
os.environ["KRAMER_APP_DIR"] = str(TMP / "app")           # nunca toca la configuración real
os.environ.pop("KRAMER_NUBE_URL", None)

from kramer import categorias, config, lista, nombres, nube, respaldo  # noqa: E402


class Nombres(unittest.TestCase):
    def test_formato_prolijo(self):
        self.assertEqual(nombres.nombre_archivo("Daddy Yankee", "Gasolina (Official Video) [HD]", ".mp3"), "Daddy Yankee - Gasolina.mp3")
        self.assertEqual(nombres.nombre_archivo("SODA STEREO", "de música ligera", ".mp3"), "SODA STEREO - De Música Ligera.mp3")

    def test_puntos_y_barras(self):
        self.assertEqual(nombres.nombre_archivo("Boney M.", "rasputin", ".mp3"), "Boney M. - Rasputin.mp3")
        self.assertEqual(nombres.nombre_archivo("AC/DC", "Back In Black", ".mp3"), "AC-DC - Back In Black.mp3")


class Categorias(unittest.TestCase):
    def test_origen_idioma(self):
        self.assertEqual(categorias.tags_origen_idioma("Argentina", "Español"), ["Argentina", "Latinoamérica", "Español"])
        self.assertEqual(categorias.tags_origen_idioma("Jamaica", "Inglés"), ["Otro país", "Latinoamérica", "Inglés"])

    def test_decada_y_bpm(self):
        self.assertEqual(categorias.tag_decada(1985), ["80s"])
        self.assertEqual(categorias.tag_bpm(128), ["120 a 128"])


class Lista(unittest.TestCase):
    def test_leer_txt(self):
        r = lista.leer("Soda Stereo - De Música Ligera\nDaddy Yankee – Gasolina\n\n1. Queen - Bohemian Rhapsody\n")
        self.assertEqual([(x["artista"], x["titulo"]) for x in r],
                         [("Soda Stereo", "De Música Ligera"), ("Daddy Yankee", "Gasolina"), ("Queen", "Bohemian Rhapsody")])


class Cartelera(unittest.TestCase):
    def test_filtro_por_zona(self):
        caba = {"pais": "AR", "region": "Ciudad de Buenos Aires"}
        miami = {"pais": "US", "region": "Florida"}
        a = lambda alc, pais, reg: {"alcance": alc, "pais": pais, "region": reg}
        self.assertTrue(nube.le_corresponde(a("region", "AR", "Ciudad de Buenos Aires"), caba))
        self.assertTrue(nube.le_corresponde(a("region", "AR", "Buenos Aires (provincia)"), caba))   # misma zona
        self.assertFalse(nube.le_corresponde(a("region", "AR", "Córdoba"), caba))
        self.assertTrue(nube.le_corresponde(a("pais", "AR", "Córdoba"), caba))
        self.assertFalse(nube.le_corresponde(a("region", "NZ", "Auckland"), miami))
        self.assertTrue(nube.le_corresponde(a("mundo", "ES", "Cataluña"), miami))

    def test_apagada_sin_servidor(self):
        self.assertFalse(nube.configurado())
        self.assertEqual(nube.novedades("0.8"), {"activo": False})


class Respaldo(unittest.TestCase):
    """Backup y restauración completos sobre carpetas de prueba."""

    class T:
        total = hechos = 0
        mensaje = ""
        cancelar = False

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(dir=TMP))
        (self.d / "rb/share/PIONEER").mkdir(parents=True)
        (self.d / "rb/master.db").write_bytes(b"base original")
        (self.d / "rb/share/PIONEER/ANLZ.DAT").write_bytes(b"analisis")
        (self.d / "col/Cumbia").mkdir(parents=True)
        (self.d / "col/Cumbia/a.mp3").write_bytes(b"a" * 1000)
        (self.d / "col/b.mp3").write_bytes(b"b" * 500)
        config.guardar({"rekordbox": str(self.d / "rb"), "coleccion": str(self.d / "col"),
                        "respaldo_destino": str(self.d / "bk"), "backup": str(self.d / "hist")})

    def test_ciclo_completo(self):
        r = respaldo.backup_completo(self.T(), con_otros=False)
        self.assertTrue(Path(r["base"]["zip"]).is_file())
        self.assertEqual(r["coleccion"]["copiados"], 2)
        # incremental: la segunda vez no copia nada
        self.assertEqual(respaldo.backup_coleccion(self.T(), con_otros=False)["copiados"], 0)
        # se borra un tema: el backup lo aparta en _quitados (no lo borra)
        (self.d / "col/b.mp3").unlink()
        self.assertEqual(respaldo.backup_coleccion(self.T(), con_otros=False)["apartados"], 1)
        # restaurar los que faltan
        (self.d / "col/Cumbia/a.mp3").unlink()
        self.assertEqual(respaldo.restaurar_coleccion(self.T(), "faltantes")["restaurados"], 1)
        self.assertTrue((self.d / "col/Cumbia/a.mp3").is_file())
        # restaurar la base: antes guarda la actual
        (self.d / "rb/master.db").write_bytes(b"base rota")
        zips = respaldo.estado()["bases"]
        r = respaldo.restaurar_base(self.T(), zips[0]["ruta"])
        self.assertEqual((self.d / "rb/master.db").read_bytes(), b"base original")
        self.assertTrue(r["previo"] and Path(r["previo"]).is_file())

    def test_no_dentro_de_la_coleccion(self):
        config.guardar({"respaldo_destino": str(self.d / "col/backups")})
        with self.assertRaises(respaldo.ErrorRespaldo):
            respaldo.backup_completo(self.T())

    def test_zip_malicioso(self):
        z = self.d / "malo.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("master.db", b"x")
            zf.writestr("../../afuera.txt", b"x")
        with self.assertRaises(respaldo.ErrorRespaldo):
            respaldo._zip_valido(z)


class Servidor(unittest.TestCase):
    """La app arranca y responde, aunque no haya Rekordbox instalado."""

    @classmethod
    def setUpClass(cls):
        from kramer import servidor
        config.guardar({"rekordbox": str(TMP / "no-existe"), "acepto_riesgo": True})
        cls.srv = servidor.crear(0)
        cls.puerto = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, ruta):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.puerto}{ruta}", timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_pagina(self):
        st, cuerpo = self.get("/")
        self.assertEqual(st, 200)
        self.assertIn(b"RKB", cuerpo)

    def test_estado(self):
        st, cuerpo = self.get("/api/estado")
        self.assertEqual(st, 200)
        d = json.loads(cuerpo)
        self.assertFalse(d["rekordboxExiste"])
        self.assertNotIn("nube_sesion", d["config"])         # nunca mandar sesiones a la interfaz

    def test_sin_rekordbox_mensaje_claro(self):
        st, cuerpo = self.get("/api/coleccion")
        self.assertEqual(st, 404)
        self.assertIn("No encuentro la base de Rekordbox", json.loads(cuerpo)["error"])


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
