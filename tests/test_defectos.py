"""Defectos encontrados en la revisión de noviembre de 2026, todavía sin arreglar.

Cada prueba describe lo que TENDRÍA que pasar y está marcada como «falla esperada». Cuando se arregle el defecto,
la prueba empieza a pasar, la corrida avisa «unexpected success» y hay que sacarle la marca: desde ahí cuida el arreglo.
"""
import json
import os
import threading
import time
import unittest
import zipfile
from unittest import mock

import base_rb
import entorno
import requests
from pyrekordbox.masterdb import models as m

from kramer import backups, config, historial, nube, plataforma, rb, respaldo, servidor


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


if __name__ == "__main__":
    unittest.main()
