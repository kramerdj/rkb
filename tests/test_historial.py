"""Historial: cada operación guarda la base y los archivos antes de tocarlos, y Deshacer los devuelve."""
import datetime
import unittest
from pathlib import Path

import entorno

from kramer import archivos, config, historial


class Historial(unittest.TestCase):
    def setUp(self):
        self.d = entorno.carpeta()
        self.rb = self.d / "rekordbox"
        self.rb.mkdir()
        (self.rb / "master.db").write_bytes(b"base antes")
        (self.rb / "masterPlaylists6.xml").write_bytes(b"playlists antes")
        self.tema = self.d / "tema.mp3"
        self.tema.write_bytes(b"audio original")
        config.guardar({"rekordbox": str(self.rb), "backup": str(self.d / "backup")})
        self.segundo = datetime.datetime(2026, 1, 1, 12, 0, 0)

    def operacion(self, que, **kw):
        """Cada operación de la prueba cae en un segundo distinto, como en el uso real."""
        self.segundo += datetime.timedelta(seconds=1)
        op = historial.Operacion(que, **kw)
        op.ts = self.segundo
        op.carpeta = config.dir_backups() / op.ts.strftime("%Y-%m-%d_%H%M%S")
        return op

    def test_guarda_la_base_antes_de_tocarla(self):
        with self.operacion("Prueba") as op:
            (self.rb / "master.db").write_bytes(b"base despues")
            op.detalle = "1 tema"
        self.assertEqual((op.carpeta / "base" / "master.db").read_bytes(), b"base antes")
        self.assertEqual((op.carpeta / "base" / "masterPlaylists6.xml").read_bytes(), b"playlists antes")
        registro = historial.listar()[0]
        self.assertEqual((registro["que"], registro["detalle"], registro["deshecho"]), ("Prueba", "1 tema", False))

    def test_sin_base_no_empieza(self):
        (self.rb / "master.db").unlink()
        with self.assertRaises(RuntimeError):
            with self.operacion("Prueba"):
                self.fail("no tendría que entrar sin backup de la base")

    def test_deshacer_devuelve_la_base_y_los_archivos(self):
        with self.operacion("Prueba") as op:
            op.respaldar_archivo(self.tema)
            self.tema.write_bytes(b"audio cambiado")
            (self.rb / "master.db").write_bytes(b"base despues")
            (self.rb / "master.db-wal").write_bytes(b"cambios sin pasar a la base")
        historial.deshacer(op.carpeta.name)
        self.assertEqual(self.tema.read_bytes(), b"audio original")
        self.assertEqual((self.rb / "master.db").read_bytes(), b"base antes")
        self.assertFalse((self.rb / "master.db-wal").exists())
        self.assertTrue(historial.listar()[0]["deshecho"])

    def test_el_backup_de_un_archivo_es_el_de_antes_del_primer_cambio(self):
        with self.operacion("Prueba") as op:
            op.respaldar_archivo(self.tema)
            self.tema.write_bytes(b"primer cambio")
            op.respaldar_archivo(self.tema)
            self.tema.write_bytes(b"segundo cambio")
        historial.deshacer(op.carpeta.name)
        self.assertEqual(self.tema.read_bytes(), b"audio original")

    def test_dos_archivos_con_el_mismo_nombre(self):
        otro = self.d / "otra carpeta" / "tema.mp3"
        otro.parent.mkdir()
        otro.write_bytes(b"otro audio")
        with self.operacion("Prueba") as op:
            op.respaldar_archivo(self.tema)
            op.respaldar_archivo(otro)
            self.tema.write_bytes(b"x")
            otro.write_bytes(b"y")
        historial.deshacer(op.carpeta.name)
        self.assertEqual((self.tema.read_bytes(), otro.read_bytes()), (b"audio original", b"otro audio"))

    def test_archivo_sacado_de_la_coleccion_vuelve(self):
        with self.operacion("Borrar duplicados") as op:
            op.mover_archivo(self.tema)
        self.assertFalse(self.tema.exists())
        self.assertEqual(Path(op.archivos[str(self.tema)]).read_bytes(), b"audio original")
        historial.deshacer(op.carpeta.name)
        self.assertEqual(self.tema.read_bytes(), b"audio original")

    def test_operacion_que_falla_queda_registrada_y_se_deshace(self):
        with self.assertRaises(ZeroDivisionError):
            with self.operacion("Prueba") as op:
                op.respaldar_archivo(self.tema)
                self.tema.write_bytes(b"a medio cambiar")
                (self.rb / "master.db").write_bytes(b"base a medio cambiar")
                1 / 0
        registro = historial.listar()[0]
        self.assertIn("con error", registro["que"])
        historial.deshacer(registro["id"])
        self.assertEqual(self.tema.read_bytes(), b"audio original")
        self.assertEqual((self.rb / "master.db").read_bytes(), b"base antes")

    def test_se_deshace_en_orden(self):
        with self.operacion("Primera") as primera:
            (self.rb / "master.db").write_bytes(b"base 1")
        with self.operacion("Segunda") as segunda:
            (self.rb / "master.db").write_bytes(b"base 2")
        self.assertEqual([o["que"] for o in historial.listar()], ["Segunda", "Primera"])
        with self.assertRaises(ValueError):
            historial.deshacer(primera.carpeta.name)
        self.assertEqual((self.rb / "master.db").read_bytes(), b"base 2")
        historial.deshacer(segunda.carpeta.name)
        self.assertEqual((self.rb / "master.db").read_bytes(), b"base 1")
        historial.deshacer(primera.carpeta.name)
        self.assertEqual((self.rb / "master.db").read_bytes(), b"base antes")
        with self.assertRaises(ValueError):
            historial.deshacer(primera.carpeta.name)

    def test_archivo_creado_por_la_operacion_se_saca_y_el_original_vuelve(self):
        descarga = self.d / "descargas" / "nuevo.mp3"
        descarga.parent.mkdir()
        descarga.write_bytes(b"tema nuevo")
        destino = self.d / "coleccion" / "nuevo.mp3"
        destino.parent.mkdir()
        with self.operacion("Incorporar") as op:
            op.respaldar_archivo(descarga)
            descarga.rename(destino)
            op.creados.append(str(destino))
        historial.deshacer(op.carpeta.name)
        self.assertFalse(destino.exists())
        self.assertEqual(descarga.read_bytes(), b"tema nuevo")

    def test_renombrado_vuelve_a_su_nombre(self):
        nuevo = self.tema.with_name("Artista - Tema.mp3")
        with self.operacion("Ordenar nombres") as op:
            self.tema.rename(nuevo)
            op.renombrados[str(nuevo)] = str(self.tema)
        historial.deshacer(op.carpeta.name)
        self.assertFalse(nuevo.exists())
        self.assertEqual(self.tema.read_bytes(), b"audio original")

    def test_operacion_sin_base_ni_archivos_que_falla_no_ensucia_el_historial(self):
        with self.assertRaises(ZeroDivisionError):
            with self.operacion("Prueba", con_base=False):
                1 / 0
        self.assertEqual(historial.listar(), [])

    @unittest.expectedFailure
    def test_dos_operaciones_en_el_mismo_segundo_no_se_pisan(self):
        """Hoy la carpeta del backup se llama por fecha y hora al segundo: dos operaciones seguidas comparten carpeta
        y la segunda pisa el backup de la primera (ver la revisión, «Historial»)."""
        primera = self.operacion("Primera")
        segunda = historial.Operacion("Segunda")
        segunda.ts, segunda.carpeta = primera.ts, primera.carpeta
        with primera:
            (self.rb / "master.db").write_bytes(b"base 1")
        with segunda:
            (self.rb / "master.db").write_bytes(b"base 2")
        self.assertEqual(len(historial.listar()), 2)
        self.assertEqual((primera.carpeta / "base" / "master.db").read_bytes(), b"base antes")


class Etiquetas(unittest.TestCase):
    """Leer y escribir etiquetas en archivos de audio de verdad, en cada formato que acepta la app."""

    FORMATOS = {"mp3": None, "flac": None, "m4a": None, "wav": None, "aiff": None}
    DATOS = {"titulo": "De Música Ligera", "artista": "Soda Stereo", "album": "Canción Animal", "anio": "1990",
             "genero": "Rock nacional", "grouping": "Clásicos", "comentario": "País: Argentina | Idioma: Español"}

    @classmethod
    def setUpClass(cls):
        import base_rb
        cls.d = entorno.carpeta()
        cls.archivos = {ext: base_rb.audio(cls.d / f"tono.{ext}") for ext in cls.FORMATOS}

    def test_lo_que_se_escribe_se_lee_igual(self):
        for ext, ruta in self.archivos.items():
            with self.subTest(formato=ext):
                archivos.escribir(ruta, self.DATOS)
                self.assertEqual(archivos.leer(ruta), self.DATOS)

    def test_valor_vacio_borra_el_campo_y_no_toca_los_demas(self):
        for ext, ruta in self.archivos.items():
            with self.subTest(formato=ext):
                archivos.escribir(ruta, self.DATOS)
                archivos.escribir(ruta, {"genero": "", "comentario": ""})
                leido = archivos.leer(ruta)
                self.assertEqual((leido["genero"], leido["comentario"]), ("", ""))
                self.assertEqual((leido["titulo"], leido["artista"], leido["anio"]), ("De Música Ligera", "Soda Stereo", "1990"))

    def test_escribir_etiquetas_no_cambia_el_audio(self):
        import mutagen
        for ext, ruta in self.archivos.items():
            with self.subTest(formato=ext):
                antes = mutagen.File(str(ruta)).info.length
                archivos.escribir(ruta, self.DATOS)
                self.assertAlmostEqual(mutagen.File(str(ruta)).info.length, antes, places=2)

    def test_archivo_que_no_es_audio(self):
        texto = self.d / "nota.mp3"
        texto.write_text("esto no es un mp3")
        self.assertEqual(set(archivos.leer(texto).values()), {""})
        self.assertEqual(set(archivos.leer(self.d / "no-existe.mp3").values()), {""})
        with self.assertRaises(Exception):
            archivos.escribir(self.d / "nota.txt", {"titulo": "x"})

    def test_anio_con_fecha_completa(self):
        ruta = self.archivos["flac"]
        archivos.escribir(ruta, {"anio": "1990-08-07"})
        self.assertEqual(archivos.leer(ruta)["anio"], "1990")


if __name__ == "__main__":
    unittest.main()
