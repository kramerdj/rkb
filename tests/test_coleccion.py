"""Los flujos que tocan la base de Rekordbox y los archivos, de punta a punta, sobre una base y música de prueba."""
import unittest
from pathlib import Path
from unittest import mock

import base_rb
from pyrekordbox.masterdb import models as m

from kramer import archivos, config, historial, ingreso, lista, rb


def callado(_):
    pass


class ConBase(unittest.TestCase):
    def setUp(self):
        self.d = base_rb.crear()
        self.coleccion, self.descargas = self.d / "coleccion", self.d / "descargas"

    def tema(self, nombre, titulo, artista, carpeta=None, **datos):
        ruta = base_rb.audio((carpeta or self.coleccion) / nombre)
        archivos.escribir(ruta, {"titulo": titulo, "artista": artista, **{k: str(v) for k, v in datos.items() if k in archivos.CAMPOS}})
        return ruta, base_rb.agregar_tema(ruta, titulo, artista, datos.get("genero", ""), datos.get("anio"))

    def consulta(self, modelo, **filtros):
        with rb.lock:
            db = rb.abrir()
            try:
                return [{c.name: getattr(f, c.name) for c in modelo.__table__.columns} for f in db.query(modelo).filter_by(**filtros)]
            finally:
                db.close()


class Coleccion(ConBase):
    def test_leer(self):
        ruta, cid = self.tema("soda.mp3", "De Música Ligera", "Soda Stereo", genero="Rock", anio=1990)
        col = rb.leer_coleccion()
        self.assertEqual(len(col["temas"]), 1)
        t = col["temas"][0]
        self.assertEqual((t["id"], t["titulo"], t["artista"], t["genero"], t["anio"], t["decada"]),
                         (cid, "De Música Ligera", "Soda Stereo", "Rock", "1990", "90s"))
        self.assertTrue(base_rb.misma_ruta(t["ruta"], ruta))
        self.assertEqual(col["momentos"], ["Previa", "Warm Up", "Main", "Peak", "Close", "Lentos"])

    def test_coleccion_vacia(self):
        self.assertEqual(rb.leer_coleccion()["temas"], [])
        self.assertEqual(rb.buscar_duplicados(), [])


class Sincronizar(ConBase):
    """Paso 5: los cambios pendientes van al archivo y a Rekordbox, con backup, y se pueden deshacer."""

    def setUp(self):
        super().setUp()
        self.ruta, self.cid = self.tema("soda.mp3", "De Música Ligera", "Soda Stereo", genero="Rock", anio=1990)

    def aplicar(self, **pendientes):
        with historial.Operacion("Sincronizar") as op:
            self.op = op
            return rb.aplicar({"meta": {}, "momento": {}, "tags": {}, **pendientes}, op.respaldar_archivo, callado)

    def test_metadata_va_al_archivo_y_a_la_base(self):
        r = self.aplicar(meta={self.cid: {"titulo": "Persiana Americana", "genero": "Pop", "anio": "1986", "album": "Signos"}})
        self.assertEqual((r["metadata"], r["errores"]), (1, []))
        en_base = base_rb.tema(self.cid)
        self.assertEqual((en_base["titulo"], en_base["genero"], en_base["anio"], en_base["album"]), ("Persiana Americana", "Pop", 1986, "Signos"))
        en_archivo = archivos.leer(self.ruta)
        self.assertEqual((en_archivo["titulo"], en_archivo["genero"], en_archivo["anio"], en_archivo["album"]),
                         ("Persiana Americana", "Pop", "1986", "Signos"))
        self.assertEqual(en_archivo["artista"], "Soda Stereo")

    def test_deshacer_devuelve_archivo_y_base(self):
        self.aplicar(meta={self.cid: {"titulo": "Otro", "artista": "Otro Artista", "genero": "Pop"}})
        historial.deshacer(self.op.carpeta.name)
        en_base = base_rb.tema(self.cid)
        self.assertEqual((en_base["titulo"], en_base["artista"], en_base["genero"]), ("De Música Ligera", "Soda Stereo", "Rock"))
        en_archivo = archivos.leer(self.ruta)
        self.assertEqual((en_archivo["titulo"], en_archivo["artista"], en_archivo["genero"]), ("De Música Ligera", "Soda Stereo", "Rock"))

    def test_pais_e_idioma_van_al_comentario_y_a_los_tags(self):
        self.aplicar(meta={self.cid: {"pais": "Argentina", "idioma": "Español"}})
        self.assertEqual(archivos.leer(self.ruta)["comentario"], "País: Argentina | Idioma: Español")
        self.assertEqual(base_rb.tema(self.cid)["comentario"], "País: Argentina | Idioma: Español")
        t = rb.leer_coleccion()["temas"][0]
        self.assertEqual((t["pais"], t["idioma"]), ("Argentina", "Español"))
        self.assertEqual(set(t["cats"]["1"]), {"Argentina", "Latinoamérica", "Español"})
        self.assertEqual(t["cats"]["3"], ["90s"])

    def test_momento(self):
        self.aplicar(momento={self.cid: "Peak"})
        self.assertEqual(rb.leer_coleccion()["temas"][0]["momento"], "Peak")
        self.aplicar(momento={self.cid: "Close"})
        self.assertEqual(rb.leer_coleccion()["temas"][0]["momento"], "Close")
        self.aplicar(momento={self.cid: ""})
        self.assertEqual(rb.leer_coleccion()["temas"][0]["momento"], "")

    def test_borrar_un_campo(self):
        self.aplicar(meta={self.cid: {"genero": "", "anio": ""}})
        en_base = base_rb.tema(self.cid)
        self.assertEqual((en_base["genero"] or "", en_base["anio"]), ("", None))
        self.assertEqual(archivos.leer(self.ruta)["genero"], "")

    def test_tema_que_ya_no_esta_en_rekordbox(self):
        r = self.aplicar(meta={"999999": {"titulo": "x"}}, momento={"999999": "Peak"})
        self.assertEqual(r["metadata"], 0)
        self.assertEqual(len(r["errores"]), 1)

    def test_archivo_que_ya_no_esta_en_el_disco(self):
        self.ruta.unlink()
        r = self.aplicar(meta={self.cid: {"titulo": "Nuevo"}})
        self.assertEqual(r["metadata"], 1)
        self.assertEqual(base_rb.tema(self.cid)["titulo"], "Nuevo")

    def test_anio_invalido_avisa_y_no_rompe(self):
        r = self.aplicar(meta={self.cid: {"anio": "mil novecientos", "titulo": "Nuevo"}})
        self.assertEqual(len(r["errores"]), 1)
        self.assertEqual((base_rb.tema(self.cid)["anio"], base_rb.tema(self.cid)["titulo"]), (1990, "Nuevo"))

    @unittest.expectedFailure
    def test_comentario_editado_junto_con_el_pais(self):
        """Hoy, si en el mismo guardado cambian el comentario y el país, el comentario nuevo se pierde
        (ver la revisión, «Sincronizar»)."""
        self.aplicar(meta={self.cid: {"comentario": "pedido por la novia", "pais": "Argentina"}})
        self.assertIn("pedido por la novia", archivos.leer(self.ruta)["comentario"])

    @unittest.expectedFailure
    def test_comentario_editado_llega_a_la_base(self):
        """Hoy el comentario se escribe en el archivo pero no en Rekordbox (ver la revisión, «Sincronizar»)."""
        self.aplicar(meta={self.cid: {"comentario": "pedido por la novia"}})
        self.assertEqual(archivos.leer(self.ruta)["comentario"], "pedido por la novia")
        self.assertEqual(base_rb.tema(self.cid)["comentario"], "pedido por la novia")

    @unittest.expectedFailure
    def test_el_resumen_cuenta_los_momentos(self):
        """Hoy el resumen informa 0 momentos aunque se haya guardado uno (ver la revisión, «Sincronizar»)."""
        self.assertEqual(self.aplicar(momento={self.cid: "Peak"})["momento"], 1)


class Incorporar(ConBase):
    """Paso 3: los temas preparados pasan de Descargas a la colección y a Rekordbox."""

    def descarga(self, nombre, titulo, artista, **datos):
        ruta = base_rb.audio(self.descargas / nombre)
        archivos.escribir(ruta, {"titulo": titulo, "artista": artista, **datos})
        return ruta

    def incorporar(self, rutas, playlist=None, **kw):
        with historial.Operacion("Incorporar") as op:
            self.op = op
            return ingreso.incorporar([str(r) for r in rutas], playlist, op, callado, **kw)

    def test_mueve_agrega_y_arma_la_playlist_del_dia(self):
        nuevo = self.descarga("queen.mp3", "Bohemian Rhapsody", "Queen", genero="Rock", anio="1975",
                              comentario="País: Inglaterra | Idioma: Inglés")
        r = self.incorporar([nuevo])
        self.assertEqual((r["incorporados"], r["errores"]), (1, []))
        self.assertTrue(r["playlistFecha"].startswith("Importación "))
        self.assertFalse(nuevo.exists())
        self.assertTrue((self.coleccion / "queen.mp3").is_file())
        t = rb.leer_coleccion()["temas"][0]
        self.assertEqual((t["titulo"], t["artista"], t["genero"], t["anio"]), ("Bohemian Rhapsody", "Queen", "Rock", "1975"))
        self.assertEqual(set(t["cats"]["1"]), {"Inglaterra", "Europa", "Inglés"})
        nombres = {f["ID"]: f["Name"] for f in self.consulta(m.DjmdPlaylist)}
        self.assertEqual([nombres[p] for p in t["playlists"]], [r["playlistFecha"]])

    def test_no_pisa_un_archivo_con_el_mismo_nombre(self):
        viejo, _ = self.tema("queen.mp3", "Otro tema", "Otro")
        original = viejo.read_bytes()
        nuevo = self.descarga("queen.mp3", "Bohemian Rhapsody", "Queen")
        self.incorporar([nuevo])
        self.assertEqual(viejo.read_bytes(), original)
        self.assertTrue((self.coleccion / "queen (2).mp3").is_file())
        self.assertEqual(len(rb.leer_coleccion()["temas"]), 2)

    def test_deshacer_devuelve_el_tema_a_descargas(self):
        nuevo = self.descarga("queen.mp3", "Bohemian Rhapsody", "Queen")
        original = nuevo.read_bytes()
        self.incorporar([nuevo])
        historial.deshacer(self.op.carpeta.name)
        self.assertEqual(nuevo.read_bytes(), original)
        self.assertFalse((self.coleccion / "queen.mp3").exists())
        self.assertEqual(rb.leer_coleccion()["temas"], [])

    def test_archivo_que_ya_no_esta(self):
        r = self.incorporar([self.descargas / "no-existe.mp3"], playlist_fecha=False)
        self.assertEqual((r["incorporados"], len(r["errores"])), (0, 1))

    def test_dos_importaciones_el_mismo_dia(self):
        a = self.incorporar([self.descarga("a.mp3", "A", "X")])["playlistFecha"]
        b = self.incorporar([self.descarga("b.mp3", "B", "X")])["playlistFecha"]
        self.assertNotEqual(a, b)
        self.assertEqual(b, f"{a} (2)")

    def test_si_la_base_no_se_puede_guardar_los_archivos_vuelven(self):
        nuevo = self.descarga("queen.mp3", "Bohemian Rhapsody", "Queen")
        original = nuevo.read_bytes()
        with mock.patch.object(rb, "tags_automaticos", side_effect=RuntimeError("la base falló")):
            with self.assertRaises(RuntimeError):
                self.incorporar([nuevo])
        self.assertEqual(nuevo.read_bytes(), original)
        self.assertFalse((self.coleccion / "queen.mp3").exists())
        self.assertEqual(rb.leer_coleccion()["temas"], [])


class ListaDelCliente(ConBase):
    """Paso 1: la lista del cliente contra la colección."""

    def setUp(self):
        super().setUp()
        _, self.soda = self.tema("soda.mp3", "De Música Ligera", "Soda Stereo")
        _, self.queen = self.tema("queen.mp3", "Don't Stop Me Now (Remastered 2011)", "Queen")

    def comparar(self, texto):
        return {(r["artista"], r["titulo"]): r for r in lista.comparar(lista.leer(texto))}

    def test_estados(self):
        r = self.comparar("soda stereo - de musica ligera\nQueen - Don't Stop Me Now (Live)\nBad Bunny - Tití Me Preguntó\n"
                          "Soda Stereo - De Música Ligera\n")
        self.assertEqual(r[("soda stereo", "de musica ligera")]["estado"], "tengo")
        self.assertEqual(r[("soda stereo", "de musica ligera")]["match"], self.soda)
        self.assertEqual(r[("Queen", "Don't Stop Me Now (Live)")]["estado"], "posible")
        self.assertEqual(r[("Bad Bunny", "Tití Me Preguntó")]["estado"], "falta")
        self.assertEqual(r[("Soda Stereo", "De Música Ligera")]["estado"], "repetido")

    def test_mismo_titulo_de_otro_artista_no_es_el_mismo_tema(self):
        r = self.comparar("Los Enanitos Verdes - De Música Ligera\n")
        self.assertNotEqual(r[("Los Enanitos Verdes", "De Música Ligera")]["estado"], "tengo")

    def test_sin_artista_alcanza_el_titulo(self):
        self.assertEqual(self.comparar("De Música Ligera\n")[("", "De Música Ligera")]["estado"], "tengo")

    def test_crear_el_evento_como_playlist(self):
        r = lista.crear_evento("Casamiento Sofi y Tomi", [self.soda, self.queen, "999999"])
        self.assertEqual(r["agregados"], 2)
        self.assertEqual(lista.crear_evento("Casamiento Sofi y Tomi", [self.soda])["agregados"], 0)
        self.assertEqual(len(self.consulta(m.DjmdSongPlaylist, PlaylistID=r["id"])), 2)

    def test_lista_depurada_en_descargas(self):
        destino = Path(lista.guardar_txt("Casamiento: Sofi/Tomi", [{"artista": "Bad Bunny", "titulo": "Tití Me Preguntó"}]))
        self.assertEqual(destino.parent, self.descargas)
        texto = destino.read_text(encoding="utf-8")
        self.assertIn("Bad Bunny - Tití Me Preguntó", texto)
        self.assertIn("https://www.beatport.com/search?q=Bad+Bunny", texto)


class Duplicados(ConBase):
    def setUp(self):
        super().setUp()
        self.a_ruta, self.a = self.tema("soda.mp3", "De Música Ligera", "Soda Stereo")
        self.b_ruta, self.b = self.tema("soda copia.mp3", "De Musica Ligera (Official Video)", "SODA STEREO")
        _, self.otro = self.tema("queen.mp3", "Bohemian Rhapsody", "Queen")
        self.evento = lista.crear_evento("Evento", [self.b, self.otro])["id"]

    def borrar(self, conservar, borrar):
        with historial.Operacion("Borrar duplicados") as op:
            self.op = op
            return rb.borrar_duplicados([{"conservar": conservar, "borrar": [borrar]}], op.mover_archivo, callado)

    def test_encuentra_el_mismo_tema_con_otro_nombre(self):
        grupos = rb.buscar_duplicados()
        self.assertEqual(len(grupos), 1)
        self.assertEqual({c["id"] for c in grupos[0]["copias"]}, {self.a, self.b})

    def test_borrar_saca_de_rekordbox_y_aparta_el_archivo(self):
        original = self.b_ruta.read_bytes()
        r = self.borrar(self.a, self.b)
        self.assertEqual((r["borrados"], r["reemplazos"], r["errores"]), (1, 1, []))
        self.assertIsNone(base_rb.tema(self.b))
        self.assertFalse(self.b_ruta.exists())
        self.assertTrue(self.a_ruta.is_file())
        apartado = next(copia for ruta, copia in self.op.archivos.items() if base_rb.misma_ruta(ruta, self.b_ruta))
        self.assertEqual(Path(apartado).read_bytes(), original)
        en_evento = {f["ContentID"] for f in self.consulta(m.DjmdSongPlaylist, PlaylistID=self.evento)}
        self.assertEqual(en_evento, {self.a, self.otro})

    def test_deshacer_devuelve_el_duplicado(self):
        original = self.b_ruta.read_bytes()
        self.borrar(self.a, self.b)
        historial.deshacer(self.op.carpeta.name)
        self.assertEqual(self.b_ruta.read_bytes(), original)
        self.assertIsNotNone(base_rb.tema(self.b))
        self.assertEqual({f["ContentID"] for f in self.consulta(m.DjmdSongPlaylist, PlaylistID=self.evento)}, {self.b, self.otro})

    def test_no_borra_el_que_se_conserva(self):
        r = self.borrar(self.a, self.a)
        self.assertEqual(r["borrados"], 0)
        self.assertTrue(self.a_ruta.is_file())
        self.assertIsNotNone(base_rb.tema(self.a))


class EliminarTemas(ConBase):
    def setUp(self):
        super().setUp()
        self.a_ruta, self.a = self.tema("soda.mp3", "De Música Ligera", "Soda Stereo")
        self.b_ruta, self.b = self.tema("queen.mp3", "Bohemian Rhapsody", "Queen")
        self.evento = lista.crear_evento("Casamiento", [self.a, self.b])["id"]

    def eliminar(self, *ids):
        with historial.Operacion("Eliminar temas") as op:
            self.op = op
            return rb.eliminar_temas(list(ids), op.eliminar_archivo, callado)

    def test_avisa_en_que_playlists_esta(self):
        _, solo = self.tema("suelto.mp3", "Suelto", "Nadie")
        r = {t["id"]: t["playlists"] for t in rb.revisar_eliminar([self.a, solo, "999999"])}
        self.assertEqual(r, {self.a: ["Casamiento"], solo: []})

    def test_saca_de_rekordbox_y_de_la_playlist_y_aparta_el_archivo(self):
        original = self.a_ruta.read_bytes()
        r = self.eliminar(self.a)
        self.assertEqual((r["eliminados"], r["dePlaylists"], r["archivos"], r["errores"]), (1, 1, 1, []))
        self.assertIsNone(base_rb.tema(self.a))
        self.assertFalse(self.a_ruta.exists())
        apartado = Path(next(iter(self.op.eliminados.values())))
        self.assertEqual(apartado.parent, config.dir_eliminados())
        self.assertEqual(apartado.name, "soda.mp3")
        self.assertEqual(apartado.read_bytes(), original)
        self.assertEqual({f["ContentID"] for f in self.consulta(m.DjmdSongPlaylist, PlaylistID=self.evento)}, {self.b})
        self.assertEqual(self.consulta(m.DjmdSongMyTag, ContentID=self.a), [])
        self.assertIsNotNone(base_rb.tema(self.b))

    def test_varios_y_nombres_repetidos_en_eliminados(self):
        config.dir_eliminados().mkdir(parents=True, exist_ok=True)
        (config.dir_eliminados() / "soda.mp3").write_bytes(b"otro")
        r = self.eliminar(self.a, self.b)
        self.assertEqual(r["eliminados"], 2)
        nombres = sorted(Path(x).name for x in self.op.eliminados.values())
        self.assertEqual(nombres, ["queen.mp3", "soda (2).mp3"])
        self.assertEqual((config.dir_eliminados() / "soda.mp3").read_bytes(), b"otro")

    def test_no_mueve_un_archivo_que_usa_otro_tema(self):
        _, otro = self.tema("copia.mp3", "Copia", "Soda Stereo")
        with rb.lock:                              # dos temas de Rekordbox apuntando al mismo archivo
            db = rb.abrir()
            try:
                db.get_content(ID=otro).FolderPath = db.get_content(ID=self.a).FolderPath
                db.commit()
            finally:
                db.close()
        r = self.eliminar(self.a)
        self.assertEqual((r["eliminados"], r["archivos"]), (1, 0))
        self.assertTrue(self.a_ruta.is_file())
        self.assertIsNotNone(base_rb.tema(otro))

    def test_deshacer_devuelve_todo(self):
        original = self.a_ruta.read_bytes()
        self.eliminar(self.a)
        apartado = Path(next(iter(self.op.eliminados.values())))
        historial.deshacer(self.op.carpeta.name)
        self.assertEqual(self.a_ruta.read_bytes(), original)
        self.assertFalse(apartado.exists())
        self.assertIsNotNone(base_rb.tema(self.a))
        self.assertEqual({f["ContentID"] for f in self.consulta(m.DjmdSongPlaylist, PlaylistID=self.evento)}, {self.a, self.b})

class OrdenarNombres(ConBase):
    def setUp(self):
        super().setUp()
        self.ruta, self.cid = self.tema("01 soda_stereo - DE MUSICA LIGERA [HD].mp3", "DE MUSICA LIGERA [HD]", "Soda Stereo")

    def renombrar(self, cambios):
        with historial.Operacion("Ordenar nombres") as op:
            self.op = op
            return rb.renombrar(cambios, op, callado)

    def test_propone_el_nombre_prolijo(self):
        self.assertEqual([(p["id"], p["nuevo"]) for p in rb.propuesta_nombres()], [(self.cid, "Soda Stereo - De Musica Ligera.mp3")])

    def test_renombra_el_archivo_y_la_base(self):
        r = self.renombrar([{"id": self.cid, "nuevo": "Soda Stereo - De Musica Ligera.mp3"}])
        self.assertEqual((r["renombrados"], r["errores"]), (1, []))
        nuevo = self.coleccion / "Soda Stereo - De Musica Ligera.mp3"
        self.assertTrue(nuevo.is_file())
        self.assertFalse(self.ruta.exists())
        self.assertTrue(base_rb.misma_ruta(base_rb.tema(self.cid)["ruta"], nuevo))
        self.assertEqual(rb.propuesta_nombres(), [])

    def test_deshacer_devuelve_el_nombre(self):
        self.renombrar([{"id": self.cid, "nuevo": "Soda Stereo - De Musica Ligera.mp3"}])
        historial.deshacer(self.op.carpeta.name)
        self.assertTrue(self.ruta.is_file())
        self.assertTrue(base_rb.misma_ruta(base_rb.tema(self.cid)["ruta"], self.ruta))

    def test_no_pisa_otro_archivo(self):
        otro = self.coleccion / "Soda Stereo - De Musica Ligera.mp3"
        otro.write_bytes(b"otro tema")
        r = self.renombrar([{"id": self.cid, "nuevo": otro.name}])
        self.assertEqual((r["renombrados"], len(r["errores"])), (0, 1))
        self.assertEqual(otro.read_bytes(), b"otro tema")
        self.assertTrue(self.ruta.is_file())

    def test_el_nombre_nuevo_no_puede_salir_de_la_carpeta(self):
        afuera = self.d / "afuera.mp3"
        with self.assertRaises(ValueError):
            self.renombrar([{"id": self.cid, "nuevo": "../afuera.mp3"}])
        self.assertFalse(afuera.exists())
        self.assertTrue(self.ruta.is_file())


if __name__ == "__main__":
    unittest.main()
