"""Estadísticas anónimas (Aptabase): qué se envía, cuándo, y que nunca se note si falla.
Los eventos van a un servidor de prueba local, nunca a Aptabase."""
import datetime
import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import entorno

from kramer import config, estadisticas, servidor

HOY = datetime.date.today()
CAMPOS_EVENTO = {"timestamp", "sessionId", "eventName", "systemProps", "props"}
CAMPOS_SISTEMA = {"isDebug", "appVersion", "osName", "sdkVersion"}


class Receptor(BaseHTTPRequestHandler):
    recibidos = []

    def do_POST(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Receptor.recibidos.append({"app_key": self.headers.get("App-Key"), "eventos": cuerpo})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


class Estadisticas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Receptor)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/api/v0/events"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Receptor.recibidos = []
        os.environ["KRAMER_ESTADISTICAS"] = "1"
        self.addCleanup(os.environ.pop, "KRAMER_ESTADISTICAS", None)
        for k, v in {"URL": self.url, "_chequeado": None}.items():
            self.addCleanup(setattr, estadisticas, k, getattr(estadisticas, k))
            setattr(estadisticas, k, v)
        config.guardar({"acepto_riesgo": True, "estadisticas": True, "estadisticas_avisado": True, "estadisticas_estado": None,
                        "coleccion": "/Users/dj/Música/Mi Colección"})
        self.addCleanup(config.guardar, {"acepto_riesgo": False, "estadisticas": True, "estadisticas_avisado": False,
                                         "estadisticas_estado": None})

    def abrir(self, dia=HOY):
        estadisticas._chequeado = None          # como si se volviera a abrir la app
        with mock.patch.object(estadisticas, "_hoy", return_value=dia.isoformat()):
            for h in estadisticas.al_abrir("0.9.4"):
                h.join(5)

    def usar(self, accion, dia=HOY):
        with mock.patch.object(estadisticas, "_hoy", return_value=dia.isoformat()):
            h = estadisticas.uso(accion)
            if h:
                h.join(5)

    def eventos(self):
        return [e for r in Receptor.recibidos for e in r["eventos"]]

    def nombres(self):
        return sorted(e["eventName"] for e in self.eventos())

    def test_primera_vez_instalada_y_abierta(self):
        self.abrir()
        self.assertEqual(self.nombres(), ["abierta", "instalada"])
        self.assertTrue(all(r["app_key"] == "A-US-3833382263" for r in Receptor.recibidos))
        ev = {e["eventName"]: e for e in self.eventos()}
        self.assertEqual(ev["instalada"]["props"], {})
        self.assertEqual(ev["abierta"]["props"], {"version": "0.9.4", "sistema": estadisticas._sistema(),
                                                  "dias_de_uso": "1", "semanas_instalada": 0})

    def test_solo_lo_permitido(self):
        self.abrir()
        self.usar("incorporar")
        for e in self.eventos():
            self.assertEqual(set(e), CAMPOS_EVENTO)
            self.assertEqual(set(e["systemProps"]), CAMPOS_SISTEMA)
            self.assertEqual(e["systemProps"]["appVersion"], "0.9.4")
            self.assertIn(e["systemProps"]["osName"], ("macOS", "Windows"))
            self.assertTrue(e["sessionId"].isdigit())
            self.assertTrue(e["timestamp"].endswith("Z"))
        crudo = json.dumps(Receptor.recibidos, ensure_ascii=False)
        for privado in ("Música", "Colección", "/Users", "dj"):
            self.assertNotIn(privado, crudo)

    def test_abierta_una_vez_por_dia_e_instalada_una_sola_vez(self):
        self.abrir()
        self.abrir()
        self.assertEqual(self.nombres(), ["abierta", "instalada"])
        Receptor.recibidos = []
        self.abrir(HOY + datetime.timedelta(days=1))
        self.assertEqual(self.nombres(), ["abierta"])
        self.assertEqual(self.eventos()[0]["props"]["dias_de_uso"], "2-3")

    def test_dias_de_uso_y_semanas(self):
        for i in range(9):
            self.abrir(HOY + datetime.timedelta(days=i * 3))
        ultimo = [e for e in self.eventos() if e["eventName"] == "abierta"][-1]["props"]
        self.assertEqual((ultimo["dias_de_uso"], ultimo["semanas_instalada"]), ("8-15", 3))

    def test_rangos(self):
        self.assertEqual([estadisticas.rango_dias(n) for n in (1, 2, 3, 4, 7, 8, 15, 16, 200)],
                         ["1", "2-3", "2-3", "4-7", "4-7", "8-15", "8-15", "16+", "16+"])

    def test_uso_una_vez_por_dia_por_accion(self):
        self.usar("sincronizar")
        self.usar("sincronizar")
        self.usar("backup")
        self.usar("borrar todo")                  # no es una de las acciones: no se envía
        self.assertEqual([(e["eventName"], e["props"]) for e in self.eventos()],
                         [("uso", {"accion": "sincronizar"}), ("uso", {"accion": "backup"})])
        self.usar("sincronizar", HOY + datetime.timedelta(days=1))
        self.assertEqual(len(self.eventos()), 3)

    def test_apagadas_no_envian_nada(self):
        config.guardar({"estadisticas": False})
        self.abrir()
        self.usar("incorporar")
        self.assertEqual(Receptor.recibidos, [])

    def test_sin_aceptar_el_aviso_no_envian_nada(self):
        config.guardar({"acepto_riesgo": False})
        self.abrir()
        self.usar("incorporar")
        self.assertEqual(Receptor.recibidos, [])

    def test_quien_ya_usaba_la_app_no_envia_hasta_ver_la_explicacion(self):
        config.guardar({"estadisticas_avisado": False})
        self.abrir()
        self.usar("incorporar")
        self.assertEqual(Receptor.recibidos, [])
        servidor.api_config({"estadisticas_avisado": True, "estadisticas": True})   # «Dejar prendidas»
        for _ in range(50):
            if len(self.eventos()) == 2:
                break
            time.sleep(0.1)
        self.assertEqual(self.nombres(), ["abierta", "instalada"])

    def test_desde_el_codigo_fuente_no_envian(self):
        os.environ.pop("KRAMER_ESTADISTICAS")
        self.abrir()
        self.assertEqual(Receptor.recibidos, [])

    def test_sin_internet_no_se_nota_y_se_reintenta(self):
        estadisticas.URL = "http://127.0.0.1:9/api/v0/events"     # nadie escucha ahí
        antes = time.monotonic()
        estadisticas._chequeado = None
        hilos = estadisticas.al_abrir("0.9.4")
        self.assertLess(time.monotonic() - antes, 0.5)            # la app no espera
        for h in hilos:
            h.join(10)
        self.assertNotIn("instalada", config.cargar()["estadisticas_estado"])
        estadisticas.URL = self.url
        self.abrir()
        self.assertEqual(self.nombres(), ["abierta", "instalada"])

    def test_si_aptabase_contesta_error_no_se_nota(self):
        with mock.patch.object(estadisticas, "_post", side_effect=RuntimeError("caído")):
            self.abrir()
            self.usar("backup")
        self.assertEqual(config.cargar()["estadisticas_estado"].get("uso"), None)


class Ajustes(unittest.TestCase):
    def test_la_pagina_no_ve_ni_cambia_el_estado_interno(self):
        config.guardar({"estadisticas_estado": {"instalada": "2026-01-01"}})
        self.addCleanup(config.guardar, {"estadisticas_estado": None})
        self.assertNotIn("estadisticas_estado", servidor.api_estado({})["config"])
        servidor.api_config({"estadisticas_estado": {"instalada": None}, "estadisticas": False})
        c = config.cargar()
        self.assertEqual((c["estadisticas_estado"], c["estadisticas"]), ({"instalada": "2026-01-01"}, False))
        config.guardar({"estadisticas": True})

    def test_prendidas_de_fabrica(self):
        self.assertIs(config.DEFAULT["estadisticas"], True)


if __name__ == "__main__":
    unittest.main()
