"""Pruebas rápidas que corren solas en cada cambio (no necesitan Rekordbox ni música).

    python -m unittest discover -s tests -v
"""
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

from entorno import TMP

from kramer import categorias, config, lista, nombres, nube, respaldo


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


class MyTagsCategorias(unittest.TestCase):
    """My Tags con bases como las de Windows: categorías con otros ID y tags de fábrica de Rekordbox."""

    def base(self, ids_cat):
        import datetime
        from uuid import uuid4

        from pyrekordbox.masterdb import models as m
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        carpeta = Path(tempfile.mkdtemp(dir=TMP))
        motor = create_engine(f"sqlite:///{carpeta / 'master.db'}")
        # base mínima con las tablas de Rekordbox (sin columnas obligatorias, como una base vacía)
        cols = [c for t in m.Base.metadata.tables.values() for c in t.columns if not c.primary_key and not c.nullable]
        for c in cols:
            c.nullable = True
        try:
            m.Base.metadata.create_all(motor)
        finally:
            for c in cols:
                c.nullable = False
        ahora = datetime.datetime.now()

        def fila(modelo, **kw):
            return modelo(UUID=str(uuid4()), created_at=ahora, updated_at=ahora, **kw)

        filas = [fila(m.DjmdMyTag, ID=cid, Seq=seq, Name=nombre, Attribute=1, ParentID="root")
                 for seq, (cid, nombre) in enumerate(zip(ids_cat, ["Genre", "Components", "Situation", ""]), 1)]
        filas += [fila(m.DjmdMyTag, ID=f"95{seq}", Seq=seq, Name=nombre, Attribute=0, ParentID=ids_cat[0])
                  for seq, nombre in enumerate(["House", "Techno"], 1)]          # tags de fábrica, sin temas
        filas.append(fila(m.DjmdContent, ID="1", Title="Tema", ReleaseYear=1985,
                          Commnt="País: Argentina | Idioma: Español", FolderPath=""))
        filas.append(m.AgentRegistry(registry_id="localUpdateCount", int_1=0, date_1=ahora, date_2=ahora,
                                     created_at=ahora, updated_at=ahora))
        with Session(motor) as s:
            s.add_all(filas)
            s.commit()
        motor.dispose()
        config.guardar({"rekordbox": str(carpeta)})

    def setUp(self):
        os.environ["KRAMER_RB_TEST"] = "1"
        self.cfg_previa = config.cargar().get("rekordbox")

    def tearDown(self):
        os.environ.pop("KRAMER_RB_TEST", None)
        config.guardar({"rekordbox": self.cfg_previa or ""})

    def test_no_muestra_tags_de_fabrica(self):
        from kramer import rb
        self.base(["1", "2", "3", "4"])
        cats = rb.listar_mytags()
        self.assertEqual(cats[0]["nombre"], "Origen/Idioma")
        self.assertEqual(cats[0]["tags"], [])                 # no House/Techno debajo de «Origen/Idioma»

    def test_categorias_con_otros_id(self):
        from pyrekordbox.masterdb import models as m

        from kramer import rb
        self.base(["900", "901", "902", "903"])
        rb.sincronizar_categorias(simular=False, leer_archivos=False)
        db = rb.abrir()
        try:
            hijos = defaultdict(set)
            for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.Attribute == 0):
                hijos[t.ParentID].add(t.Name)
            nombres_cat = {t.ID: t.Name for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == "root")}
        finally:
            db.close()
        self.assertEqual(nombres_cat["900"], "Origen/Idioma")
        self.assertEqual(hijos["900"], {"Argentina", "Latinoamérica", "Español"})
        self.assertEqual(hijos["902"], {"80s"})
        self.assertTrue(set(hijos) <= {"900", "901", "902", "903"})   # nada colgado de categorías que no existen
        cats = {c["id"]: {t["nombre"] for t in c["tags"]} for c in rb.listar_mytags()}
        self.assertEqual(cats["1"], {"Argentina", "Latinoamérica", "Español"})
        self.assertEqual(set(rb.leer_coleccion()["temas"][0]["cats"]["1"]), {"Argentina", "Latinoamérica", "Español"})


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

    def control(self, d):
        """Simula el archivo control/versiones.json de GitHub (None = sin internet)."""
        viejos = nube._control, nube.CONTROL_URL
        nube._control, nube.CONTROL_URL = (lambda forzar: d), "https://ejemplo"
        self.addCleanup(lambda: (setattr(nube, "_control", viejos[0]), setattr(nube, "CONTROL_URL", viejos[1])))

    def test_sin_internet_no_bloquea(self):
        self.control(None)
        self.assertEqual(nube.novedades("0.1"), {"activo": False, "offline": True})

    def test_version_obligatoria(self):
        import datetime
        hoy = datetime.date.today()
        self.control({"ultima": "0.9.2", "minima": "0.9.2", "gracia_dias": 7,
                      "minima_desde": (hoy - datetime.timedelta(days=3)).isoformat()})
        d = nube.novedades("0.9.1")
        self.assertTrue(d["hayNueva"])
        self.assertFalse(d["bloqueo"])
        self.assertEqual(d["diasGracia"], 4)
        self.control({"ultima": "0.9.2", "minima": "0.9.2", "gracia_dias": 7,
                      "minima_desde": (hoy - datetime.timedelta(days=8)).isoformat()})
        self.assertTrue(nube.novedades("0.9.1")["bloqueo"])
        self.assertFalse(nube.novedades("0.9.2")["bloqueo"])
        self.assertFalse(nube.novedades("0.10")["hayNueva"])


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


if __name__ == "__main__":
    unittest.main()
