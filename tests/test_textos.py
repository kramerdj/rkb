"""Reglas de texto que no necesitan base ni archivos: nombres prolijos, listas, claves de comparación y My Tags."""
import unittest

import entorno  # noqa: F401

from kramer import archivos, categorias, lista, nombres, rb


class NombresProlijos(unittest.TestCase):
    def test_invitados_al_final_del_titulo(self):
        self.assertEqual(nombres.prolijo("Don Omar ft. Lucenzo", "Danza Kuduro (Official Video)"),
                         ("Don Omar", "Danza Kuduro (feat. Lucenzo)"))
        self.assertEqual(nombres.prolijo("A x B", "Tema (feat. C) (Remix)"), ("A & B", "Tema (feat. C) (Remix)"))

    def test_version_entre_parentesis(self):
        self.assertEqual(nombres.prolijo("Queen", "Don't Stop Me Now - Remastered 2011")[1], "Don't Stop Me Now (Remastered 2011)")
        self.assertEqual(nombres.prolijo("Artista", "Tema - Parte Dos")[1], "Tema - Parte Dos")

    def test_saca_el_ruido(self):
        self.assertEqual(nombres.prolijo("Artista", "01 Tema_con_guiones [HD]")[1], "Tema con guiones")
        self.assertEqual(nombres.prolijo("Artista", "Tema (Audio Oficial) (320 kbps)")[1], "Tema")
        self.assertEqual(nombres.prolijo("Artista - Topic", "Tema")[0], "Artista")

    def test_mayusculas(self):
        self.assertEqual(nombres.prolijo("KAROL G", "PROVENZA"), ("KAROL G", "Provenza"))
        self.assertEqual(nombres.prolijo("soda stereo", "de música ligera"), ("Soda Stereo", "De Música Ligera"))

    def test_duos_y_varios_artistas(self):
        self.assertEqual(nombres.separar_artistas("Zion & Lennox"), ["Zion & Lennox"])
        self.assertEqual(nombres.separar_artistas("AC/DC"), ["AC/DC"])
        self.assertEqual(nombres.separar_artistas("A; B / C"), ["A", "B", "C"])
        self.assertEqual(nombres.unir_artistas(["A", "B", "C"]), "A, B & C")
        self.assertEqual(nombres.unir_artistas(["Zion & Lennox", "Farruko"]), "Zion & Lennox, Farruko")

    def test_artistas_pegados_que_ya_conoce(self):
        conocidos = {"don omar", "daddy yankee"}
        self.assertEqual(nombres.separar_artistas("Don Omar Daddy Yankee", conocidos), ["Don Omar", "Daddy Yankee"])
        self.assertEqual(nombres.separar_artistas("Don Omar Desconocido", conocidos), ["Don Omar Desconocido"])

    def test_nombre_de_archivo_valido_en_windows_y_mac(self):
        n = nombres.nombre_archivo("AC/DC", 'T.N.T: "Live"?', ".FLAC")
        self.assertEqual(n, "AC-DC - T.N.T - Live.flac")
        for malo in '/\\:*?"<>|':
            self.assertNotIn(malo, nombres.nombre_archivo(f"Ar{malo}tista", f"Te{malo}ma", ".mp3"))

    def test_sin_artista_o_sin_titulo(self):
        self.assertEqual(nombres.nombre_archivo("", "Solo Título", ".mp3"), "Solo Título.mp3")
        self.assertEqual(nombres.nombre_archivo("Solo Artista", "", ".mp3"), "Solo Artista.mp3")

    def test_nombre_largo_se_corta_en_una_palabra(self):
        n = nombres.nombre_archivo("Artista", " ".join(["palabra"] * 40), ".mp3")
        self.assertLessEqual(len(n), 144)
        self.assertTrue(n.startswith("Artista - Palabra Palabra"), n)
        self.assertTrue(n.endswith(" Palabra.mp3"), n)


class Listas(unittest.TestCase):
    def test_texto_pegado(self):
        r = lista.leer("1) A - B\n- C - D\n# nota\n\nSolo título\nE – F\n")
        self.assertEqual([(x["artista"], x["titulo"]) for x in r], [("A", "B"), ("C", "D"), ("", "Solo título"), ("E", "F")])
        self.assertEqual([x["n"] for x in r], [1, 2, 3, 4])

    def test_csv_de_spotify(self):
        texto = 'Track Name,Artist Name(s),Album\nDe Música Ligera,Soda Stereo,Canción Animal\n"Tití Me Preguntó","Bad Bunny;Otro",X\n,Sin título,Y\n'
        r = lista.leer(texto, "exportify.csv")
        self.assertEqual([(x["artista"], x["titulo"]) for x in r], [("Soda Stereo", "De Música Ligera"), ("Bad Bunny", "Tití Me Preguntó")])

    def test_csv_con_punto_y_coma_y_bom(self):
        r = lista.leer("﻿Título;Artista\nMatador;Los Fabulosos Cadillacs\n", "lista.csv")
        self.assertEqual([(x["artista"], x["titulo"]) for x in r], [("Los Fabulosos Cadillacs", "Matador")])

    def test_m3u(self):
        texto = "#EXTM3U\r\n#EXTINF:210,Queen - Bohemian Rhapsody\r\n/m/q.mp3\r\n/m/Soda Stereo - Persiana Americana.mp3\r\n"
        r = lista.leer(texto, "lista.m3u8")
        self.assertEqual([(x["artista"], x["titulo"]) for x in r], [("Queen", "Bohemian Rhapsody"), ("Soda Stereo", "Persiana Americana")])

    def test_lista_vacia(self):
        self.assertEqual(lista.leer(""), [])
        self.assertEqual(lista.leer("\n\n# sólo comentarios\n"), [])
        self.assertEqual(lista.leer("", "vacia.csv"), [])


class ClavesDeComparacion(unittest.TestCase):
    def test_titulo_sin_ruido_ni_acentos(self):
        self.assertEqual(rb._clave_titulo("De Música Ligera (Official Video) [feat. X]"), "de musica ligera")
        self.assertEqual(rb._clave_titulo("DE MUSICA LIGERA"), rb._clave_titulo("de música ligera"))
        self.assertNotEqual(rb._clave_titulo("Tema (Remix)"), rb._clave_titulo("Tema"))

    def test_artista_sin_orden_ni_articulo(self):
        self.assertEqual(rb._clave_artista("The Beatles & Queen"), rb._clave_artista("Queen, Beatles"))
        self.assertEqual(rb._clave_artista("Wisin y Yandel"), rb._clave_artista("Yandel & Wisin"))
        self.assertEqual(rb._clave_artista("Don Omar feat. Lucenzo"), rb._clave_artista("Don Omar"))

    def test_rutas_como_las_compara_macos(self):
        compuesta, descompuesta = "/Música/Canción.mp3", "/Música/Canción.mp3"
        self.assertNotEqual(compuesta, descompuesta)
        self.assertTrue(rb.mismo_path(compuesta, descompuesta))
        self.assertTrue(rb.mismo_path("/Musica/TEMA.MP3", "/musica/tema.mp3"))
        self.assertFalse(rb.mismo_path("/Musica/a.mp3", "/Musica/b.mp3"))
        self.assertEqual(rb._clave_path(compuesta), rb._clave_path(descompuesta))

    def test_tono_a_camelot(self):
        for tono, camelot in (("Am", "8A"), ("C", "8B"), ("F#m", "11A"), ("Gbm", "11A"), ("Bbmin", "3A"), ("Dmaj", "10B"),
                              ("8a", "8A"), ("12B", "12B"), ("", ""), ("H", ""), (None, "")):
            self.assertEqual(rb.camelot(tono), camelot, tono)


class TagsAutomaticos(unittest.TestCase):
    def test_decada(self):
        for anio, tag in ((1959, ["50s"]), (1960, ["60s"]), (1999, ["90s"]), (2000, ["2000s"]), (2019, ["2010s"]),
                          ("2026-05-01", ["2020s"]), (None, []), (0, []), ("s/d", []), (1800, [])):
            self.assertEqual(categorias.tag_decada(anio), tag, anio)

    def test_rango_de_bpm(self):
        for bpm, tag in ((0, []), (None, []), ("x", []), (60, ["Menos de 100"]), (99.9, ["Menos de 100"]), (100, ["100 a 119"]),
                         (120, ["120 a 128"]), (128, ["120 a 128"]), (129, ["Más de 128"])):
            self.assertEqual(categorias.tag_bpm(bpm), tag, bpm)

    def test_version(self):
        for titulo, tag in (("Tema", ["Original"]), ("Tema (Original Mix)", ["Original"]), ("Tema (Fulano Remix)", ["Remix"]),
                            ("Tema (Extended Mix)", ["Extended"]), ("Tema (Radio Edit)", ["Edit"]), ("Tema (En Vivo)", ["En vivo"]),
                            ("Tema - Live", ["En vivo"]), ("A vs B (Mashup)", ["Mashup"]), ("", [])):
            self.assertEqual(categorias.tag_version(titulo), tag, titulo)

    def test_origen_e_idioma(self):
        self.assertEqual(categorias.tags_origen_idioma("Estados Unidos", "Inglés"), ["Estados Unidos", "Norteamérica", "Inglés"])
        self.assertEqual(categorias.tags_origen_idioma("Escocia", "Inglés"), ["Inglaterra", "Europa", "Inglés"])
        self.assertEqual(categorias.tags_origen_idioma("Japón", "Japonés"), ["Otro país", "Asia", "Otro idioma"])
        self.assertEqual(categorias.tags_origen_idioma("", ""), [])

    def test_orden_de_los_tags(self):
        self.assertEqual(categorias.orden("decada", {"2000s": 1, "90s": 5, "80s": 2, "2010s": 9}), ["80s", "90s", "2000s", "2010s"])
        self.assertEqual(categorias.orden("bpm", {"Más de 128": 1, "Menos de 100": 1}), ["Menos de 100", "Más de 128"])
        self.assertEqual(categorias.orden("genero", {"Rock": 2, "Cumbia": 9, "Pop": 2}), ["Cumbia", "Pop", "Rock"])

    def test_categorias_guardadas_con_fuente_desconocida(self):
        from kramer import config
        config.guardar({"categorias": [{"id": "2", "nombre": "Mi género", "fuente": "inventada"}, "basura", {"sin": "id"}]})
        self.addCleanup(config.guardar, {"categorias": None})
        cats = categorias.cargar()
        self.assertEqual([c["id"] for c in cats], ["1", "2", "3", "4"])
        self.assertEqual((cats[1]["nombre"], cats[1]["fuente"]), ("Mi género", "genero"))


class PaisEIdiomaEnElComentario(unittest.TestCase):
    def test_leer(self):
        self.assertEqual(archivos.pais_idioma("País: Argentina | Idioma: Español"), ("Argentina", "Español"))
        self.assertEqual(archivos.pais_idioma("nota mía | Pais: Brasil"), ("Brasil", ""))
        self.assertEqual(archivos.pais_idioma(None), ("", ""))

    def test_armar_conserva_el_resto_del_comentario(self):
        self.assertEqual(archivos.armar_comentario("nota mía | País: Brasil | Idioma: Portugués", "Argentina", "Español"),
                         "nota mía | País: Argentina | Idioma: Español")
        self.assertEqual(archivos.armar_comentario("País: Brasil", "", ""), "")
        self.assertEqual(archivos.armar_comentario("", "Argentina", ""), "País: Argentina")


if __name__ == "__main__":
    unittest.main()
