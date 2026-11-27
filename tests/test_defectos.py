"""Pruebas que nacieron de la revisión de noviembre de 2026: cada una cuida un defecto que se encontró ahí.

Las que siguen marcadas como «falla esperada» son defectos todavía sin arreglar: describen lo que TENDRÍA que pasar.
Cuando se arregle uno, su prueba avisa «unexpected success» y hay que sacarle la marca.
"""
import datetime
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

    def test_guarda_lo_que_pisa(self):
        with historial.Operacion("Sincronizar") as op:
            (self.rb / "master.db").write_bytes(b"base despues de la operacion")
        (self.rb / "master.db").write_bytes(b"una semana de trabajo en Rekordbox")
        historial.deshacer(op.carpeta.name)
        copias = [p for p in self.d.rglob("*") if p.is_file() and p.read_bytes() == b"una semana de trabajo en Rekordbox"]
        self.assertTrue(copias, "no quedó ninguna copia de la base que se pisó")

    def test_backup_incompleto_no_se_da_por_deshecho(self):
        with historial.Operacion("Sincronizar") as op:
            (self.rb / "master.db").write_bytes(b"base despues de la operacion")
        (op.carpeta / "base" / "master.db").unlink()
        with self.assertRaises(Exception):
            historial.deshacer(op.carpeta.name)


class LimpiezaDeBackups(unittest.TestCase):
    def test_solo_ofrece_borrar_backups_de_operaciones(self):
        raiz = entorno.carpeta() / "backup"
        (raiz / "Respaldos RKB" / "base").mkdir(parents=True)
        (raiz / "Contratos").mkdir()
        (raiz / "Contratos" / "contrato.pdf").write_bytes(b"x")
        config.guardar({"backup": str(raiz), "respaldo_destino": ""})
        self.assertEqual([i["nombre"] for i in backups.listar()["items"]], [])


class BackupCompleto(unittest.TestCase):
    def test_datos_del_manifiesto_llegan_como_numeros(self):
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

    def test_restaurar_la_base_que_la_app_acaba_de_leer(self):
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
    def test_no_se_pierden_cuando_llegan_juntos(self):
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

    def test_cero_de_mas_no_bloquea_a_quien_esta_al_dia(self):
        self.control({"ultima": "0.9.1", "minima": "0.9.1.0", "gracia_dias": 0, "minima_desde": "2026-01-01"})
        self.assertFalse(nube.novedades("0.9.1")["bloqueo"])


class SesionDeMisAnuncios(unittest.TestCase):
    def test_sin_internet_no_cierra_la_sesion(self):
        sesion = {"access": "a", "refresh": "r", "vence": time.time() - 10, "uid": "u1", "email": "dj@ejemplo.com"}
        config.guardar({"nube_sesion": sesion})
        self.addCleanup(config.guardar, {"nube_sesion": None})
        with mock.patch.object(nube, "URL", "https://ejemplo.supabase.co"), mock.patch.object(nube, "CLAVE", "anon"), \
                mock.patch.object(requests, "request", side_effect=requests.ConnectionError("sin internet")):
            with self.assertRaises(nube.ErrorNube):
                nube.token()
        self.assertEqual(config.cargar()["nube_sesion"], sesion)


class BaseDeRekordbox(unittest.TestCase):
    def test_abre_siempre_la_base_configurada(self):
        d = entorno.carpeta()
        (d / "master.db").write_bytes(b"x")
        config.guardar({"rekordbox": str(d)})
        with mock.patch.dict(os.environ), mock.patch.object(plataforma, "dir_rekordbox", return_value=d), \
                mock.patch.object(rb, "MasterDatabase") as abrir:
            os.environ.pop("KRAMER_RB_TEST", None)
            rb.abrir()
        self.assertEqual(abrir.call_args.kwargs.get("path"), str(d / "master.db"))

    def test_rutas_de_windows_con_cualquier_barra(self):
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

    def test_no_deja_dos_tags_con_el_mismo_nombre(self):
        base_rb.crear()
        rb.editar_mytags([{"cat": "4", "accion": "agregar", "nombre": "Peak"}, {"cat": "4", "accion": "agregar", "nombre": "Main"}])
        tags = {t["nombre"]: t["id"] for t in rb.listar_mytags()[3]["tags"]}
        with self.assertRaises(ValueError):
            rb.editar_mytags([{"cat": "4", "accion": "renombrar", "id": tags["Main"], "nombre": "Peak"}])
        self.assertEqual(set(t["nombre"] for t in rb.listar_mytags()[3]["tags"]), {"Peak", "Main"})

    def test_tags_repetidos_que_ya_estaban_no_rompen_el_guardado(self):
        d = base_rb.crear()
        cid = base_rb.agregar_tema(base_rb.audio(d / "coleccion" / "tema.mp3"), "Tema", "Artista")
        rb.editar_mytags([{"cat": "4", "accion": "agregar", "nombre": "Peak"}, {"cat": "4", "accion": "agregar", "nombre": "Main"}])
        with rb.lock:
            db = rb.abrir()
            try:
                db.query(m.DjmdMyTag).filter(m.DjmdMyTag.Name == "Main").one().Name = "Peak"
                db.commit()
            finally:
                db.close()
        with historial.Operacion("Sincronizar") as op:
            rb.aplicar({"meta": {}, "momento": {cid: "Peak"}, "tags": {}}, op.respaldar_archivo, lambda s: None)
        self.assertEqual(rb.leer_coleccion()["temas"][0]["momento"], "Peak")


class NombresProlijos(unittest.TestCase):
    def test_titulos_que_empiezan_con_un_numero(self):
        self.assertEqual(nombres.prolijo("Ariana Grande", "7 rings")[1], "7 Rings")
        self.assertEqual(nombres.prolijo("Jay-Z", "99 Problems")[1], "99 Problems")

    def test_el_titulo_nunca_queda_vacio(self):
        self.assertEqual(nombres.prolijo("El Alfa", "4K")[1], "4K")
        self.assertNotEqual(nombres.nombre_archivo("", "HD", ".mp3"), ".mp3")

    def test_clean_y_explicit_son_versiones_distintas(self):
        self.assertNotEqual(nombres.prolijo("Cardi B", "WAP (Clean)"), nombres.prolijo("Cardi B", "WAP (Explicit)"))

    def test_artistas_con_x_o_con_coma_en_el_nombre(self):
        self.assertEqual(nombres.prolijo("Lil Nas X & Jack Harlow", "Industry Baby")[0], "Lil Nas X & Jack Harlow")
        self.assertEqual(nombres.prolijo("Tyler, The Creator", "Earfquake")[0], "Tyler, The Creator")


class Descargas(unittest.TestCase):
    def setUp(self):
        self.d = base_rb.crear()

    def test_cambiar_el_pais_no_borra_el_idioma(self):
        ruta = base_rb.audio(self.d / "descargas" / "tema.mp3")
        archivos.escribir(ruta, {"titulo": "Tema", "artista": "Artista", "comentario": "País: Argentina | Idioma: Español"})
        with historial.Operacion("Preparar descargas", con_base=False) as op:
            ingreso.aplicar_metadata([{"ruta": str(ruta), "meta": {"pais": "Uruguay"}}], op, lambda s: None)
        comentarios = [archivos.leer(p)["comentario"] for p in (self.d / "descargas").glob("*.mp3")]
        self.assertEqual(comentarios, ["País: Uruguay | Idioma: Español"])

    def test_ve_las_subcarpetas_aunque_el_nombre_empiece_igual_que_la_coleccion(self):
        descargas = self.d / "coleccion nueva"
        base_rb.audio(descargas / "pack" / "adentro.mp3")
        config.guardar({"incorporar": str(descargas)})
        self.assertEqual([Path(x).name for x in ingreso.listar()], ["adentro.mp3"])

    def test_incorporar_solo_acepta_archivos_de_descargas(self):
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

    def test_no_acepta_pedidos_de_otra_pagina(self):
        pedido = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_address[1]}/api/pendiente",
                                        data=json.dumps({"id": "1", "momento": "Peak"}).encode(),
                                        headers={"Origin": "https://ejemplo.com", "Content-Type": "text/plain"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(pedido, timeout=10).close()
        self.assertEqual(error.exception.code, 403)

    def test_ajustes_no_acepta_cualquier_valor(self):
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

    def pedir(self, cuerpo, **cabeceras):
        puerto = self.srv.server_address[1]
        pedido = urllib.request.Request(f"http://127.0.0.1:{puerto}/api/pendiente", data=json.dumps(cuerpo).encode(),
                                        headers={"Content-Type": "application/json", **cabeceras})
        try:
            with urllib.request.urlopen(pedido, timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_acepta_los_pedidos_de_su_propia_pagina(self):
        puerto = self.srv.server_address[1]
        self.assertEqual(self.pedir({"id": "1", "momento": "Peak"}), 200)
        self.assertEqual(self.pedir({"id": "1", "momento": "Peak"}, Origin=f"http://127.0.0.1:{puerto}"), 200)
        self.assertEqual(self.pedir({"id": "1", "momento": "Peak"}, Origin=f"http://localhost:{puerto}", Host=f"localhost:{puerto}"), 200)

    def test_rechaza_otro_host_y_otro_tipo_de_contenido(self):
        self.assertEqual(self.pedir({"id": "1"}, Host="sitio-ajeno.example:80"), 403)
        self.assertEqual(self.pedir({"id": "1"}, **{"Content-Type": "text/plain"}), 403)
        self.assertEqual(self.pedir({"id": "1"}, Origin="null"), 403)
        pagina = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_address[1]}/api/estado", headers={"Host": "sitio-ajeno.example"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(pagina, timeout=10).close()
        self.assertEqual(error.exception.code, 403)

    def test_ajustes_validos_se_guardan(self):
        d = entorno.carpeta()
        antes = config.cargar()
        self.addCleanup(config.guardar, {k: antes[k] for k in ("incorporar", "teclas", "inicio_seg", "cartelera_inicio", "ubicacion")})
        c = servidor.api_config({"incorporar": str(d), "teclas": ["Main"], "inicio_seg": 45, "cartelera_inicio": False,
                                 "ubicacion": {"pais": "AR", "region": "Córdoba"}, "respaldo_destino": ""})["config"]
        self.assertEqual((c["incorporar"], c["teclas"], c["inicio_seg"], c["cartelera_inicio"]), (str(d), ["Main"], 45, False))
        for malo in ({"coleccion": "carpeta/relativa"}, {"teclas": "Main"}, {"cartelera_inicio": "si"}, {"inicio_seg": "45"}, {"lastfm": 5}):
            with self.assertRaises(servidor.Error, msg=malo):
                servidor.api_config(malo)

    def test_abrir_solo_dentro_de_las_carpetas_de_la_app(self):
        d = entorno.carpeta()
        antes = config.cargar()["incorporar"]
        self.addCleanup(config.guardar, {"incorporar": antes})
        config.guardar({"incorporar": str(d / "descargas")})
        (d / "descargas").mkdir()
        (d / "descargas" / "lista_depurada.txt").write_text("x")
        (d / "descargas" / "programa.command").write_text("x")
        (d / "afuera.txt").write_text("x")
        with mock.patch.object(plataforma, "abrir") as abrir, mock.patch.object(plataforma, "mostrar") as mostrar:
            servidor.api_abrir({"ruta": str(d / "descargas" / "lista_depurada.txt")})
            servidor.api_abrir({"ruta": str(d / "descargas" / "programa.command"), "mostrar": True})
            for ajeno in (str(d / "afuera.txt"), str(d / "descargas" / "programa.command"), str(d / "descargas" / ".." / "afuera.txt"), ""):
                with self.assertRaises(servidor.Error, msg=ajeno):
                    servidor.api_abrir({"ruta": ajeno})
        self.assertEqual((abrir.call_count, mostrar.call_count), (1, 1))

    def test_el_titulo_del_selector_de_carpetas_no_se_mezcla_con_el_script(self):
        titulo = 'Elegí" & (do shell script "x") & "'
        with mock.patch.object(plataforma, "ES_MAC", True), mock.patch.object(plataforma.subprocess, "run") as correr:
            correr.return_value.stdout = "/Users/dj/Music/\n"
            self.assertEqual(plataforma.elegir_carpeta(titulo), "/Users/dj/Music")
        orden = correr.call_args.args[0]
        self.assertEqual((orden[0], orden[-1]), ("osascript", titulo))
        self.assertNotIn("do shell script", orden[2])


class MyTagsQueYaTenia(unittest.TestCase):
    """Un DJ que ya usaba My Tags en Rekordbox no los pierde por guardar un cambio: recién se reemplazan en el paso 4."""

    def setUp(self):
        self.d = base_rb.crear(paso_4=False)
        self.cid = base_rb.agregar_tema(base_rb.audio(self.d / "coleccion" / "tema.mp3"), "Tema", "Artista", anio=1995)
        ahora = datetime.datetime.now()
        with rb.lock:
            db = rb.abrir()
            try:
                db.add(m.DjmdMyTag(ID="50", Seq=1, Name="House", Attribute=0, ParentID="1", UUID="u-50", created_at=ahora, updated_at=ahora))
                db.add(m.DjmdSongMyTag(ID="60", MyTagID="50", ContentID=self.cid, UUID="u-60", created_at=ahora, updated_at=ahora))
                db.commit()
            finally:
                db.close()

    def tags(self):
        with rb.lock:
            db = rb.abrir()
            try:
                nombres = {t.ID: t.Name for t in db.query(m.DjmdMyTag)}
                return sorted(nombres[a.MyTagID] for a in db.query(m.DjmdSongMyTag).filter(m.DjmdSongMyTag.ContentID == self.cid))
            finally:
                db.close()

    def test_guardar_un_cambio_no_toca_sus_tags(self):
        with historial.Operacion("Sincronizar") as op:
            rb.aplicar({"meta": {self.cid: {"titulo": "Otro", "pais": "Argentina"}}, "momento": {}, "tags": {}}, op.respaldar_archivo, lambda s: None)
        self.assertEqual(self.tags(), ["House"])

    def test_la_simulacion_avisa_que_se_van_a_reemplazar(self):
        resumen = {c["id"]: c for c in rb.sincronizar_categorias(simular=True, leer_archivos=False)}
        self.assertEqual(resumen["1"]["seQuitan"], {"temas": 1, "tags": ["House"]})
        self.assertEqual(resumen["3"]["seQuitan"], {"temas": 0, "tags": []})
        self.assertEqual(self.tags(), ["House"])

    def test_despues_del_paso_4_los_arma_la_app(self):
        rb.sincronizar_categorias(simular=False, leer_archivos=False)
        self.assertEqual(self.tags(), ["90s"])
        with historial.Operacion("Sincronizar") as op:
            rb.aplicar({"meta": {self.cid: {"anio": "2001"}}, "momento": {}, "tags": {}}, op.respaldar_archivo, lambda s: None)
        self.assertEqual(self.tags(), ["2000s"])


class LimpiezaDeBackupsBorrar(unittest.TestCase):
    def test_borra_backups_de_operaciones_y_nada_mas(self):
        d = entorno.carpeta()
        (d / "rb").mkdir()
        (d / "rb" / "master.db").write_bytes(b"x")
        config.guardar({"rekordbox": str(d / "rb"), "backup": str(d / "backup"), "respaldo_destino": ""})
        with historial.Operacion("Sincronizar") as op:
            pass
        completo = d / "backup" / "Respaldos RKB"
        completo.mkdir()
        viejo = d / "backup" / "_BACKUP originales"
        viejo.mkdir()
        self.assertEqual({Path(i["ruta"]).name for i in backups.listar()["items"]}, {op.carpeta.name, "_BACKUP originales"})
        r = backups.borrar([str(completo), str(d / "rb"), str(op.carpeta)])
        self.assertEqual(len(r["errores"]), 2)
        self.assertTrue(completo.is_dir() and (d / "rb" / "master.db").is_file())
        self.assertFalse(op.carpeta.exists())


class NombresEnRekordbox(unittest.TestCase):
    def test_renombrar_guarda_la_ruta_con_las_barras_de_rekordbox(self):
        d = base_rb.crear()
        cid = base_rb.agregar_tema(base_rb.audio(d / "coleccion" / "viejo.mp3"), "Tema", "Artista")
        with historial.Operacion("Ordenar nombres") as op:
            rb.renombrar([{"id": cid, "nuevo": "Artista - Tema.mp3"}], op, lambda s: None)
        self.assertNotIn("\\", base_rb.tema(cid)["ruta"])


if __name__ == "__main__":
    unittest.main()
