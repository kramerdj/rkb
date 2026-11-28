"""Guía de bienvenida y «Actualizar metadata» de Colección: lo que se puede probar sin pantalla."""
import re
import unittest

import entorno

from kramer import config, servidor

WEB = entorno.RAIZ / "web"


class Guia(unittest.TestCase):
    def test_se_muestra_una_sola_vez(self):
        self.assertIs(config.DEFAULT["guia_vista"], False)
        servidor.api_config({"guia_vista": True})
        self.addCleanup(config.guardar, {"guia_vista": False})
        self.assertTrue(config.cargar()["guia_vista"])

    def test_estan_todas_las_capturas(self):
        js = (WEB / "guia.js").read_text(encoding="utf-8")
        pasos = re.findall(r"\{ id: '(\w+)', vista: '(\w+)'", js)
        self.assertEqual([p for p, _ in pasos], ["backup", "coleccion", "mytags", "lista", "descargas", "incorporar"])
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for paso, vista in pasos:
            self.assertIn(f'data-vista="{vista}"', html)
            for tema in ("claro", "oscuro"):
                self.assertTrue((WEB / "guia" / f"{paso}-{tema}.jpg").is_file(), f"{paso}-{tema}.jpg")


class MetadataColeccion(unittest.TestCase):
    def test_pide_temas_y_datos(self):
        with self.assertRaises(servidor.Error):
            servidor.api_coleccion_metadata({"ids": [], "campos": {"genero": True}})

    def test_opciones(self):
        d = servidor.api_coleccion_metadata_opciones({})
        self.assertNotIn("caratula", d["campos"])            # en la colección la carátula no se toca
        self.assertNotIn("renombrar", d["campos"])           # los nombres van por «Ordenar nombres»
        self.assertFalse(d["campos"]["pisar"])
        self.assertFalse(d["campos"]["artista_titulo"])


if __name__ == "__main__":
    unittest.main()
