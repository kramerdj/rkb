"""Modo claro y oscuro: con qué modo se abre la página y qué se puede guardar."""
import unittest

import entorno  # noqa: F401

from kramer import config, servidor


class Tema(unittest.TestCase):
    def setUp(self):
        self.addCleanup(config.guardar, {"tema": "", "tema_estreno": False})

    def test_la_primera_vez_arranca_en_claro_y_despues_sigue_al_sistema(self):
        config.guardar({"tema": "", "tema_estreno": False})
        self.assertEqual(servidor.tema_inicial(), "claro")
        self.assertEqual(servidor.tema_inicial(), "")          # vacío: la página usa el del sistema

    def test_respeta_lo_que_eligio_la_persona(self):
        config.guardar({"tema_estreno": True, "tema": "oscuro"})
        self.assertEqual(servidor.tema_inicial(), "oscuro")
        servidor.api_config({"tema": "claro"})
        self.assertEqual(servidor.tema_inicial(), "claro")

    def test_la_primera_vez_gana_el_claro_aunque_haya_elegido_antes(self):
        config.guardar({"tema_estreno": False, "tema": "oscuro"})
        self.assertEqual(servidor.tema_inicial(), "claro")
        self.assertEqual(servidor.tema_inicial(), "oscuro")

    def test_solo_acepta_modos_validos(self):
        with self.assertRaises(servidor.Error):
            servidor.api_config({"tema": "violeta"})
        servidor.api_config({"tema": ""})
        self.assertEqual(config.cargar()["tema"], "")

    def test_la_pagina_trae_el_modo_y_lo_aplica_antes_de_dibujar(self):
        html = (servidor.WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="es">', html)               # el servidor lo reemplaza con data-tema-guardado
        self.assertLess(html.index("data-tema-guardado"), html.index('href="app.css"'))


if __name__ == "__main__":
    unittest.main()
