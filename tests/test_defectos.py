"""Defectos encontrados en la revisión de noviembre de 2026, todavía sin arreglar.

Cada prueba describe lo que TENDRÍA que pasar y está marcada como «falla esperada». Cuando se arregle el defecto,
la prueba empieza a pasar, la corrida avisa «unexpected success» y hay que sacarle la marca: desde ahí cuida el arreglo.
"""
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

import base_rb
import entorno
import requests
from pyrekordbox.masterdb import models as m

from kramer import archivos, backups, config, historial, ingreso, nombres, nube, plataforma, rb, respaldo, servidor


class Deshacer(unittest.TestCase):
    def setUp(self):
        self.d = entorno.carpeta()
        self.rb = self.d / "rekordbox"
        self.rb.mkdir()
        (self.rb / "master.db").write_bytes(b"base antes de la operacion")
        config.guardar({"rekordbox": str(self.rb), "backup": str(self.d / "backup")})

    @unittest.expectedFailure
    def test_guarda_lo_que_pisa(self):
        """Deshacer copia la base vieja arriba de la actual sin guardar la actual: lo que se hizo en Rekordbox
        después de la operación (cues, playlists, temas nuevos) se pierde sin vuelta."""
        with historial.Operacion("Sincronizar") as op:
            (self.rb / "master.db").write_bytes(b"base despues de la operacion")
        (self.rb / "master.db").write_bytes(b"una semana de trabajo en Rekordbox")
        historial.deshacer(op.carpeta.name)
        copias = [p for p in self.d.rglob("*") if p.is_file() and p.read_bytes() == b"una semana de trabajo en Rekordbox"]
        self.assertTrue(copias, "no quedó ninguna copia de la base que se pisó")

    @unittest.expectedFailure
    def test_backup_incompleto_no_se_da_por_deshecho(self):
        """Si al backup de la operación le falta master.db, Deshacer no devuelve nada pero igual dice «Deshecho»."""
        with historial.Operacion("Sincronizar") as op:
            (self.rb / "master.db").write_bytes(b"base despues de la operacion")
        (op.carpeta / "base" / "master.db").unlink()
        with self.assertRaises(Exception):
            historial.deshacer(op.carpeta.name)


class LimpiezaDeBackups(unittest.TestCase):
    @unittest.expectedFailure
    def test_solo_ofrece_borrar_backups_de_operaciones(self):
        """La pantalla para liberar espacio lista (y deja borrar para siempre) todo lo que haya en la carpeta de backups:
        también el backup completo «Respaldos RKB» y cualquier otra carpeta que el usuario tenga ahí."""
        raiz = entorno.carpeta() / "backup"
        (raiz / "Respaldos RKB" / "base").mkdir(parents=True)
        (raiz / "Contratos").mkdir()
        (raiz / "Contratos" / "contrato.pdf").write_bytes(b"x")
        config.guardar({"backup": str(raiz), "respaldo_destino": ""})
        self.assertEqual([i["nombre"] for i in backups.listar()["items"]], [])


class BackupCompleto(unittest.TestCase):
    @unittest.expectedFailure
    def test_datos_del_manifiesto_llegan_como_numeros(self):
        """La pantalla de backups muestra «temas» y «playlists» tal como vienen dentro del zip, sin revisarlos:
        un zip armado a propósito puede meter código en la página. Tienen que llegar como números o vacíos."""
        d = entorno.carpeta()
        config.guardar({"respaldo_destino": str(d), "coleccion": str(d / "coleccion")})
        carpeta = respaldo.destino() / respaldo.DIR_BASE
        carpeta.mkdir(parents=True)
        with zipfile.ZipFile(carpeta / "RKB base 2026-01-01 000000.zip", "w") as z:
            z.writestr("master.db", b"x")
            z.writestr("manifiesto.json", json.dumps({"temas": "<img src=x onerror=alert(1)>", "playlists": "<b>3</b>"}))
        base = respaldo.estado()["bases"][0]
        self.assertIsInstance(base["temas"], (int, type(None)))
        self.assertIsInstance(base["playlists"], (int, type(None)))

    @unittest.skipUnless(os.name == "nt", "sólo pasa en Windows")
    @unittest.expectedFailure
    def test_restaurar_la_base_en_windows(self):
        """En Windows, restaurar la base falla con «Acceso denegado»: la app deja master.db abierto después de leerlo
        y Windows no permite reemplazar un archivo abierto. Antes de fallar ya borró master.db-wal."""
        d = entorno.carpeta()
        (d / "rb").mkdir()
        (d / "rb" / "master.db").write_bytes(b"base original")
        config.guardar({"rekordbox": str(d / "rb"), "coleccion": str(d / "col"), "respaldo_destino": str(d / "bk")})

        class Trabajo:
            total = hechos = 0
            mensaje = ""
            cancelar = False

        zip_base = respaldo.backup_base(Trabajo(), con_share=False)["zip"]
        (d / "rb" / "master.db").write_bytes(b"base rota")
        respaldo.restaurar_base(Trabajo(), zip_base)
        self.assertEqual((d / "rb" / "master.db").read_bytes(), b"base original")


class CambiosPendientes(unittest.TestCase):
    @unittest.expectedFailure
    def test_no_se_pierden_cuando_llegan_juntos(self):
        """Cada Momento que se marca se guarda leyendo y reescribiendo pendientes.json sin turno: si llegan varios
        a la vez (tecla apretada, dos pedidos seguidos) algunos se pisan y se pierden sin aviso."""
        config.guardar_pendientes({"momento": {}, "meta": {}, "tags": {}})
        hilos = [threading.Thread(target=servidor.api_pendiente, args=({"id": str(n), "momento": "Peak"},)) for n in range(150)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(len(config.pendientes()["momento"]), 150)


class VersionObligatoria(unittest.TestCase):
    def control(self, d):
        viejos = nube._control, nube.CONTROL_URL
        nube._control, nube.CONTROL_URL = (lambda forzar: d), "https://ejemplo"
        self.addCleanup(lambda: (setattr(nube, "_control", viejos[0]), setattr(nube, "CONTROL_URL", viejos[1])))

    @unittest.expectedFailure
    def test_cero_de_mas_no_bloquea_a_quien_esta_al_dia(self):
        """«0.9.1.0» se toma como más nueva que «0.9.1»: si alguien escribe la mínima con un cero de más,
        quedan bloqueados los que ya tienen la última versión."""
        self.control({"ultima": "0.9.1", "minima": "0.9.1.0", "gracia_dias": 0, "minima_desde": "2026-01-01"})
        self.assertFalse(nube.novedades("0.9.1")["bloqueo"])


class SesionDeMisAnuncios(unittest.TestCase):
    @unittest.expectedFailure
    def test_sin_internet_no_cierra_la_sesion(self):
        """Si falla la renovación de la sesión por cualquier motivo (también sin internet o con el servidor caído),
        la app borra la sesión y obliga a pedir otro código por email."""
        sesion = {"access": "a", "refresh": "r", "vence": time.time() - 10, "uid": "u1", "email": "dj@ejemplo.com"}
        config.guardar({"nube_sesion": sesion})
        self.addCleanup(config.guardar, {"nube_sesion": None})
        with mock.patch.object(nube, "URL", "https://ejemplo.supabase.co"), mock.patch.object(nube, "CLAVE", "anon"), \
                mock.patch.object(requests, "request", side_effect=requests.ConnectionError("sin internet")):
            with self.assertRaises(nube.ErrorNube):
                nube.token()
        self.assertEqual(config.cargar()["nube_sesion"], sesion)


class BaseDeRekordbox(unittest.TestCase):
    @unittest.expectedFailure
    def test_abre_siempre_la_base_configurada(self):
        """Cuando la base está en la carpeta de siempre, la app deja que pyrekordbox elija cuál abrir. Si en Rekordbox
        se mudó la biblioteca a otro disco, se escribe en una base y el backup y el Deshacer trabajan sobre otra."""
        d = entorno.carpeta()
        (d / "master.db").write_bytes(b"x")
        config.guardar({"rekordbox": str(d)})
        with mock.patch.dict(os.environ), mock.patch.object(plataforma, "dir_rekordbox", return_value=d), \
                mock.patch.object(rb, "MasterDatabase") as abrir:
            os.environ.pop("KRAMER_RB_TEST", None)
            rb.abrir()
        self.assertEqual(abrir.call_args.kwargs.get("path"), str(d / "master.db"))

    @unittest.expectedFailure
    def test_rutas_de_windows_con_cualquier_barra(self):
        """Rekordbox guarda las rutas con «/» y Windows las arma con «\\»: la app las compara como si fueran distintas,
        así que en Windows no reconoce que dos temas usan el mismo archivo."""
        self.assertEqual(rb._clave_path("C:/Musica/Tema.mp3"), rb._clave_path("C:\\Musica\\Tema.mp3"))

    @unittest.expectedFailure
    def test_menos_de_cuatro_categorias_de_my_tags(self):
        """Si la base tiene menos de 4 categorías de My Tags, la app usa un ID inventado para las que faltan
        y cuelga los tags de una categoría que no existe."""
        base_rb.crear(ids_categorias=("900", "901", "902"))
        with rb.lock:
            db = rb.abrir()
            try:
                existentes = {str(t.ID) for t in db.query(m.DjmdMyTag).filter(m.DjmdMyTag.ParentID == "root")}
                self.assertLessEqual(set(rb.ids_categorias(db).values()), existentes)
            finally:
                db.close()

    @unittest.expectedFailure
    def test_dos_tags_con_el_mismo_nombre_no_rompen_el_guardado(self):
        """Si en una categoría hay dos tags con el mismo nombre (se puede llegar renombrando uno), guardar un Momento
        con ese nombre falla con un error interno y los cambios quedan trabados."""
        d = base_rb.crear()
        cid = base_rb.agregar_tema(base_rb.audio(d / "coleccion" / "tema.mp3"), "Tema", "Artista")
        rb.editar_mytags([{"cat": "4", "accion": "agregar", "nombre": "Peak"}, {"cat": "4", "accion": "agregar", "nombre": "Main"}])
        tags = {t["nombre"]: t["id"] for t in rb.listar_mytags()[3]["tags"]}
        rb.editar_mytags([{"cat": "4", "accion": "renombrar", "id": tags["Main"], "nombre": "Peak"}])
        with historial.Operacion("Sincronizar") as op:
            rb.aplicar({"meta": {}, "momento": {cid: "Peak"}, "tags": {}}, op.respaldar_archivo, lambda s: None)


class NombresProlijos(unittest.TestCase):
    @unittest.expectedFailure
    def test_titulos_que_empiezan_con_un_numero(self):
        """Al limpiar el título se saca el «número de pista» del principio aunque sea parte del nombre:
        «7 rings» queda «Rings» y «99 Problems» queda «Problems», en la etiqueta y en el nombre del archivo."""
        self.assertEqual(nombres.prolijo("Ariana Grande", "7 rings")[1], "7 Rings")
        self.assertEqual(nombres.prolijo("Jay-Z", "99 Problems")[1], "99 Problems")

    @unittest.expectedFailure
    def test_el_titulo_nunca_queda_vacio(self):
        """Un tema que se llama «4K» o «HD» queda sin título (se toma por ruido), y sin artista el archivo
        pasa a llamarse «.mp3», que en Mac es un archivo oculto."""
        self.assertEqual(nombres.prolijo("El Alfa", "4K")[1], "4K")
        self.assertNotEqual(nombres.nombre_archivo("", "HD", ".mp3"), ".mp3")

    @unittest.expectedFailure
    def test_clean_y_explicit_son_versiones_distintas(self):
        """«(Clean)» y «(Explicit)» se sacan como ruido: las dos versiones quedan con el mismo título
        y el paso 2 marca la segunda como duplicado para eliminar."""
        self.assertNotEqual(nombres.prolijo("Cardi B", "WAP (Clean)"), nombres.prolijo("Cardi B", "WAP (Explicit)"))

    @unittest.expectedFailure
    def test_artistas_con_x_o_con_coma_en_el_nombre(self):
        """«Lil Nas X & Jack Harlow» queda «Lil Nas & & Jack Harlow» y «Tyler, The Creator» queda «Tyler & The Creator»."""
        self.assertEqual(nombres.prolijo("Lil Nas X & Jack Harlow", "Industry Baby")[0], "Lil Nas X & Jack Harlow")
        self.assertEqual(nombres.prolijo("Tyler, The Creator", "Earfquake")[0], "Tyler, The Creator")


class Descargas(unittest.TestCase):
    def setUp(self):
        self.d = base_rb.crear()

    @unittest.expectedFailure
    def test_cambiar_el_pais_no_borra_el_idioma(self):
        """En el paso 2, si se guarda sólo el país, el idioma que ya tenía el comentario se borra
        (y con él los My Tags automáticos de idioma)."""
        ruta = base_rb.audio(self.d / "descargas" / "tema.mp3")
        archivos.escribir(ruta, {"titulo": "Tema", "artista": "Artista", "comentario": "País: Argentina | Idioma: Español"})
        with historial.Operacion("Preparar descargas", con_base=False) as op:
            ingreso.aplicar_metadata([{"ruta": str(ruta), "meta": {"pais": "Uruguay"}}], op, lambda s: None)
        comentarios = [archivos.leer(p)["comentario"] for p in (self.d / "descargas").glob("*.mp3")]
        self.assertEqual(comentarios, ["País: Uruguay | Idioma: Español"])

    @unittest.expectedFailure
    def test_ve_las_subcarpetas_aunque_el_nombre_empiece_igual_que_la_coleccion(self):
        """Si la carpeta de descargas se llama como la colección más algo («Musica» y «Musica nueva»),
        la app saltea todas sus subcarpetas sin avisar."""
        descargas = self.d / "coleccion nueva"
        base_rb.audio(descargas / "pack" / "adentro.mp3")
        config.guardar({"incorporar": str(descargas)})
        self.assertEqual([Path(x["ruta"]).name for x in ingreso.listar()], ["adentro.mp3"])

    @unittest.expectedFailure
    def test_incorporar_solo_acepta_archivos_de_descargas(self):
        """El paso 3 mueve a la colección cualquier archivo cuya ruta le llegue, esté donde esté en el disco."""
        ajeno = base_rb.audio(self.d / "otra carpeta" / "ajeno.mp3")
        with mock.patch.object(rb, "rekordbox_abierto", return_value=False):
            with self.assertRaises(servidor.Error):
                servidor.api_incorporar({"rutas": [str(ajeno)], "playlistFecha": False})
        self.assertTrue(ajeno.is_file())


class ServidorLocal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = servidor.crear(0)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)

    @unittest.expectedFailure
    def test_no_acepta_pedidos_de_otra_pagina(self):
        """El servidor de la app no mira de dónde viene cada pedido: una página cualquiera abierta en el navegador
        de la misma computadora puede mandarle órdenes. Un pedido que declara otro origen tiene que ser rechazado."""
        pedido = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_address[1]}/api/pendiente",
                                        data=json.dumps({"id": "1", "momento": "Peak"}).encode(),
                                        headers={"Origin": "https://ejemplo.com", "Content-Type": "text/plain"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(pedido, timeout=10).close()
        self.assertEqual(error.exception.code, 403)

    @unittest.expectedFailure
    def test_ajustes_no_acepta_cualquier_valor(self):
        """Ajustes guarda lo que le llegue, del tipo que sea: un valor mal formado deja la app sin poder abrir
        hasta editar config.json a mano, y las carpetas no se revisan."""
        self.addCleanup(config.guardar, {"respaldo_destino": ""})
        with self.assertRaises(servidor.Error):
            servidor.api_config({"respaldo_destino": 5})

    @unittest.expectedFailure
    def test_la_interfaz_no_recibe_las_claves_guardadas(self):
        """La pantalla recibe las claves de Last.fm, Discogs, Spotify y YouTube tal cual están guardadas;
        alcanza con decirle si están cargadas o no."""
        config.guardar({"lastfm": "clave-secreta-de-prueba"})
        self.addCleanup(config.guardar, {"lastfm": ""})
        self.assertNotIn("clave-secreta-de-prueba", json.dumps(servidor.api_estado({})))


if __name__ == "__main__":
    unittest.main()
