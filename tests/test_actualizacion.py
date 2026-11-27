"""Actualización automática: qué paquetes acepta el arranque, cuáles rechaza y cómo vuelve al código de la app."""
import functools
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import unittest
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import entorno
from nacl.signing import SigningKey

import kramer_arranque as arranque
import publicar_actualizacion as publicar

CLAVE = SigningKey.generate()
OTRA_CLAVE = SigningKey.generate()
PUBLICA = CLAVE.verify_key.encode().hex()
INCLUIDA = arranque.VERSION_INCLUIDA
NUEVA = ".".join(str(n) for n in (*arranque._num(INCLUIDA)[:-1], arranque._num(INCLUIDA)[-1] + 1))
SIN_SERVIDOR = "http://127.0.0.1:9"


def armar_zip(version, agregado=""):
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, datos in publicar._archivos():
            if nombre == "web/version.txt":
                datos = version.encode()
            if nombre == "kramer/servidor.py":
                datos = agregado.encode() + datos
            z.writestr(nombre, datos)
    return memoria.getvalue()


def firmar(campos, clave=CLAVE):
    manifiesto = json.dumps(campos, sort_keys=True)
    return json.dumps({"manifiesto": manifiesto, "firma": clave.sign(manifiesto.encode()).signature.hex()}).encode()


def paquete(version, shell=arranque.SHELL, clave=CLAVE, agregado=""):
    datos = armar_zip(version, agregado)
    sobre = firmar({"version": version, "shell": shell, "sha256": hashlib.sha256(datos).hexdigest(),
                    "tamano": len(datos), "archivo": f"codigo-{version}.zip"}, clave)
    return sobre, datos


def guardar(carpeta, sobre, datos, version):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"codigo-{version}.zip").write_bytes(datos)
    (carpeta / "manifiesto.json").write_bytes(sobre)


def abrir_app(app, url=SIN_SERVIDOR, clave=PUBLICA, buscar=False):
    """Abre la app en otro proceso, como un arranque de verdad, y devuelve lo que quedó cargado."""
    programa = ("import json, time, kramer_arranque as a\n"
                "a.preparar()\n"
                "import kramer.servidor as s\n"
                + ("a.buscar()\nwhile a.estado()['buscando']: time.sleep(0.05)\n" if buscar else "")
                + "print(json.dumps({**a.estado(), 'servida': s.VERSION, 'web': str(s.WEB)}))\n")
    env = {**os.environ, "KRAMER_APP_DIR": str(app), "KRAMER_ACTUALIZACION_URL": url, "KRAMER_ACTUALIZACION_CLAVE": clave}
    r = subprocess.run([sys.executable, "-c", programa], cwd=entorno.RAIZ, env=env, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return {"codigo": r.returncode, "salida": r.stdout + r.stderr}
    return {"codigo": 0, **json.loads(r.stdout.strip().splitlines()[-1])}


class Verificacion(unittest.TestCase):
    """Las comprobaciones sueltas: firma, tamaño, hash y nombres de archivo."""

    def test_sobre_bien_firmado(self):
        sobre, datos = paquete(NUEVA)
        manifiesto = arranque.leer_sobre(sobre, PUBLICA)
        self.assertEqual(manifiesto["version"], NUEVA)
        arranque.comprobar_zip(datos, manifiesto)

    def test_firma_de_otra_clave(self):
        sobre, _ = paquete(NUEVA, clave=OTRA_CLAVE)
        with self.assertRaises(arranque.PaqueteInvalido):
            arranque.leer_sobre(sobre, PUBLICA)

    def test_manifiesto_cambiado_despues_de_firmar(self):
        sobre, _ = paquete(NUEVA)
        d = json.loads(sobre)
        d["manifiesto"] = d["manifiesto"].replace(NUEVA, "99.0")
        with self.assertRaises(arranque.PaqueteInvalido):
            arranque.leer_sobre(json.dumps(d).encode(), PUBLICA)

    def test_sobre_que_no_es_un_sobre(self):
        for basura in (b"", b"no es json", b"[]", b'{"manifiesto": 1, "firma": "aa"}', b'{"manifiesto": "{}", "firma": "zz"}',
                       b'{"manifiesto": "{}"}'):
            with self.assertRaises(arranque.PaqueteInvalido, msg=basura):
                arranque.leer_sobre(basura, PUBLICA)

    def test_campos_del_manifiesto(self):
        bueno = {"version": NUEVA, "shell": 1, "sha256": "a" * 64, "tamano": 10, "archivo": "codigo.zip"}
        arranque.leer_sobre(firmar(bueno), PUBLICA)
        for campo, valor in (("version", "1.0-beta"), ("version", ""), ("sha256", "abc"), ("archivo", "../codigo.zip"),
                             ("archivo", "codigo.exe"), ("archivo", "sub/codigo.zip"), ("shell", "1"), ("tamano", "10")):
            with self.assertRaises(arranque.PaqueteInvalido, msg=f"{campo}={valor!r}"):
                arranque.leer_sobre(firmar({**bueno, campo: valor}), PUBLICA)
        sin_tamano = {k: v for k, v in bueno.items() if k != "tamano"}
        with self.assertRaises(arranque.PaqueteInvalido):
            arranque.leer_sobre(firmar(sin_tamano), PUBLICA)

    def test_zip_que_no_coincide(self):
        sobre, datos = paquete(NUEVA)
        manifiesto = arranque.leer_sobre(sobre, PUBLICA)
        cambiado = bytearray(datos)
        cambiado[len(cambiado) // 2] ^= 1
        with self.assertRaises(arranque.PaqueteInvalido):
            arranque.comprobar_zip(bytes(cambiado), manifiesto)
        with self.assertRaises(arranque.PaqueteInvalido):
            arranque.comprobar_zip(datos + b"0", manifiesto)

    def test_orden_de_versiones(self):
        self.assertGreater(arranque._num("0.10"), arranque._num("0.9"))
        self.assertGreater(arranque._num("0.9.1"), arranque._num("0.9"))
        self.assertGreater(arranque._num("1.0"), arranque._num("0.99.9"))
        with self.assertRaises(arranque.PaqueteInvalido):
            arranque._num("0.9b")

    def test_archivos_permitidos_en_un_paquete(self):
        for nombre in ("kramer/rb.py", "web/app.js", "web/sub/a b.css", "kramer/__init__.py"):
            self.assertTrue(arranque.ruta_valida(nombre), nombre)
        for nombre in ("../x.py", "kramer/../x.py", "/etc/x", "kramer/", "kramer", "otra/x.py", "kramer/..", "kramer\\x.py",
                       "kramer_arranque.py", "kramer_ventana.py", "web/../../x", "kramer//x.py", "kramer/ ", ""):
            self.assertFalse(arranque.ruta_valida(nombre), nombre)

    def test_zip_con_archivo_de_afuera_no_se_extrae(self):
        memoria = io.BytesIO()
        with zipfile.ZipFile(memoria, "w") as z:
            z.writestr("kramer/servidor.py", b"")
            z.writestr("kramer_arranque.py", b"reemplazo del arranque")
        destino = entorno.carpeta() / "codigo"
        with self.assertRaises(arranque.PaqueteInvalido):
            arranque._extraer(memoria.getvalue(), destino)
        self.assertFalse((destino / "kramer_arranque.py").exists())
        self.assertFalse((destino.parent / "kramer_arranque.py").exists())

    def test_apagada_corriendo_desde_el_codigo(self):
        self.assertFalse(arranque.estado()["activo"])
        self.assertEqual(arranque.estado()["origen"], "incluido")


class Publicacion(unittest.TestCase):
    """La herramienta que arma y firma el paquete."""

    def setUp(self):
        self.d = entorno.carpeta()
        self.clave = self.d / "prueba.clave"
        self.clave.write_text(CLAVE.encode().hex() + "\n", encoding="ascii")

    def armar(self, salida):
        with mock.patch.object(arranque, "CLAVE_DEFECTO", PUBLICA), mock.patch("builtins.print"):
            publicar.armar(self.clave, salida, arranque.SHELL)
        return (salida / "manifiesto.json").read_bytes(), (salida / f"codigo-{INCLUIDA}.zip").read_bytes()

    def test_el_paquete_armado_pasa_la_verificacion(self):
        sobre, datos = self.armar(self.d / "a")
        manifiesto = arranque.leer_sobre(sobre, PUBLICA)
        arranque.comprobar_zip(datos, manifiesto)
        self.assertEqual(manifiesto["version"], INCLUIDA)
        self.assertEqual(manifiesto["shell"], arranque.SHELL)
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            nombres = z.namelist()
        self.assertIn("kramer/servidor.py", nombres)
        self.assertIn("web/version.txt", nombres)
        self.assertTrue(all(arranque.ruta_valida(n) for n in nombres))
        self.assertFalse([n for n in nombres if "__pycache__" in n or n.endswith(".pyc")])

    def test_dos_armados_dan_el_mismo_paquete(self):
        self.assertEqual(self.armar(self.d / "a"), self.armar(self.d / "b"))

    def test_clave_que_no_es_la_de_las_apps(self):
        with mock.patch("builtins.print"), self.assertRaises(SystemExit):
            publicar.armar(self.clave, self.d / "c", arranque.SHELL)
        self.assertFalse((self.d / "c").exists())

    def test_clave_privada_dentro_del_proyecto(self):
        with self.assertRaises(SystemExit):
            publicar.generar_clave(entorno.RAIZ / "tests" / "no-crear.clave")
        self.assertFalse((entorno.RAIZ / "tests" / "no-crear.clave").exists())

    def test_no_pisa_una_clave_que_ya_existe(self):
        antes = self.clave.read_text()
        with self.assertRaises(SystemExit):
            publicar.generar_clave(self.clave)
        self.assertEqual(self.clave.read_text(), antes)


class Arranque(unittest.TestCase):
    """Arranques completos, cada uno en un proceso aparte con su propia carpeta de datos."""

    def setUp(self):
        self.app = entorno.carpeta()
        self.act = self.app / "actualizacion"

    def test_paquete_valido_se_usa(self):
        guardar(self.act, *paquete(NUEVA), NUEVA)
        r = abrir_app(self.app)
        self.assertEqual((r["origen"], r["version"], r["servida"]), ("paquete", NUEVA, NUEVA))
        self.assertTrue(Path(r["web"]).resolve().is_relative_to(self.act.resolve()), r["web"])

    def test_sin_paquete_usa_el_codigo_de_la_app(self):
        r = abrir_app(self.app)
        self.assertEqual((r["origen"], r["servida"], r["motivo"]), ("incluido", INCLUIDA, ""))

    def test_sin_clave_no_mira_el_paquete(self):
        guardar(self.act, *paquete(NUEVA), NUEVA)
        for url, clave in (("", ""), (SIN_SERVIDOR, ""), ("", PUBLICA)):
            r = abrir_app(self.app, url, clave)
            self.assertEqual((r["activo"], r["origen"], r["servida"]), (False, "incluido", INCLUIDA))

    def rechazado(self, sobre, datos, version, motivo):
        guardar(self.act, sobre, datos, version)
        r = abrir_app(self.app)
        self.assertEqual((r["origen"], r["servida"]), ("incluido", INCLUIDA))
        self.assertIn(motivo, r["motivo"])

    def test_zip_alterado(self):
        sobre, datos = paquete(NUEVA)
        cambiado = bytearray(datos)
        cambiado[len(cambiado) // 2] ^= 1
        self.rechazado(sobre, bytes(cambiado), NUEVA, "no coincide con el manifiesto firmado")

    def test_firmado_con_otra_clave(self):
        self.rechazado(*paquete(NUEVA, clave=OTRA_CLAVE), NUEVA, "la firma del manifiesto no es válida")

    def test_paquete_para_una_app_mas_nueva(self):
        self.rechazado(*paquete(NUEVA, shell=arranque.SHELL + 1), NUEVA, "necesita una app más nueva")

    def test_paquete_viejo_o_igual(self):
        self.rechazado(*paquete(INCLUIDA), INCLUIDA, "no es más nuevo")
        self.rechazado(*paquete("0.1"), "0.1", "no es más nuevo")

    def test_falta_el_zip(self):
        sobre, _ = paquete(NUEVA)
        self.act.mkdir(parents=True)
        (self.act / "manifiesto.json").write_bytes(sobre)
        r = abrir_app(self.app)
        self.assertEqual((r["origen"], r["servida"]), ("incluido", INCLUIDA))
        self.assertIn("falta el archivo", r["motivo"])

    def test_paquete_que_falla_al_cargar_queda_descartado(self):
        guardar(self.act, *paquete(NUEVA, agregado='raise RuntimeError("paquete roto")\n'), NUEVA)
        r = abrir_app(self.app)
        self.assertEqual((r["origen"], r["servida"]), ("incluido", INCLUIDA))
        self.assertIn("falló al cargar", r["motivo"])
        self.assertIn("paquete roto", json.loads((self.act / "malas.json").read_text(encoding="utf-8"))[NUEVA])
        r = abrir_app(self.app)
        self.assertEqual((r["origen"], r["servida"]), ("incluido", INCLUIDA))
        self.assertIn("ya falló antes", r["motivo"])

    def test_paquete_que_cierra_la_app_se_descarta_al_abrir_de_nuevo(self):
        guardar(self.act, *paquete(NUEVA, agregado="import os\nos._exit(7)\n"), NUEVA)
        self.assertEqual(abrir_app(self.app)["codigo"], 7)
        r = abrir_app(self.app)
        self.assertEqual((r["codigo"], r["origen"], r["servida"]), (0, "incluido", INCLUIDA))
        self.assertIn("ya falló antes", r["motivo"])

    def test_no_quedan_carpetas_de_arranques_anteriores(self):
        guardar(self.act, *paquete(NUEVA), NUEVA)
        abrir_app(self.app)
        abrir_app(self.app)
        self.assertEqual(len(list(self.act.glob("codigo-*/"))), 1)


class Callado(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Descarga(unittest.TestCase):
    """La búsqueda en segundo plano contra un servidor de prueba."""

    def setUp(self):
        self.app = entorno.carpeta()
        self.act = self.app / "actualizacion"
        self.publicado = entorno.carpeta()
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Callado, directory=str(self.publicado)))
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)
        self.url = f"http://127.0.0.1:{self.servidor.server_address[1]}"

    def test_baja_el_paquete_y_lo_usa_la_proxima_vez(self):
        guardar(self.publicado, *paquete(NUEVA), NUEVA)
        r = abrir_app(self.app, self.url, buscar=True)
        self.assertEqual((r["origen"], r["servida"], r["lista"]), ("incluido", INCLUIDA, NUEVA))
        self.assertTrue((self.act / f"codigo-{NUEVA}.zip").is_file())
        r = abrir_app(self.app, self.url, buscar=True)
        self.assertEqual((r["origen"], r["servida"], r["lista"]), ("paquete", NUEVA, ""))

    def no_guarda(self, sobre, datos, version):
        guardar(self.publicado, sobre, datos, version)
        r = abrir_app(self.app, self.url, buscar=True)
        self.assertEqual((r["origen"], r["lista"]), ("incluido", ""))
        self.assertFalse(list(self.act.glob("*.zip")))
        self.assertFalse((self.act / "manifiesto.json").exists())

    def test_descarga_alterada_no_se_guarda(self):
        sobre, datos = paquete(NUEVA)
        self.no_guarda(sobre, datos[:-1] + bytes([datos[-1] ^ 1]), NUEVA)

    def test_descarga_mas_grande_que_lo_firmado_no_se_guarda(self):
        sobre, datos = paquete(NUEVA)
        self.no_guarda(sobre, datos + b"0" * 200_000, NUEVA)

    def test_firma_ajena_no_se_baja(self):
        self.no_guarda(*paquete(NUEVA, clave=OTRA_CLAVE), NUEVA)

    def test_version_vieja_no_se_baja(self):
        self.no_guarda(*paquete(INCLUIDA), INCLUIDA)

    def test_sin_servidor_no_pasa_nada(self):
        r = abrir_app(self.app, SIN_SERVIDOR, buscar=True)
        self.assertEqual((r["codigo"], r["origen"], r["lista"]), (0, "incluido", ""))


if __name__ == "__main__":
    unittest.main()
