"""Una base de Rekordbox mínima para las pruebas: las mismas tablas, sin cifrar, en una carpeta temporal."""
import datetime
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import entorno
import imageio_ffmpeg
from pyrekordbox.masterdb import models as m
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from kramer import config, rb

CATEGORIAS = ["Genre", "Components", "Situation", ""]


def audio(ruta, segundos=1, formato=None):
    """Un archivo de audio de verdad (un tono), para probar etiquetas y calidad."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    orden = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}"]
    subprocess.run(orden + (formato or []) + [str(ruta)], check=True)
    return ruta


def crear(ids_categorias=("1", "2", "3", "4"), paso_4=True):
    """Crea la base vacía, la deja como la base de la app y devuelve su carpeta.
    paso_4: como si ya se hubiera corrido «Actualizar base de Rekordbox» (las categorías llevan los nombres de la app)."""
    os.environ["KRAMER_RB_TEST"] = "1"
    carpeta = entorno.carpeta()
    motor = create_engine(f"sqlite:///{carpeta / 'master.db'}")
    obligatorias = [c for t in m.Base.metadata.tables.values() for c in t.columns if not c.primary_key and not c.nullable]
    for c in obligatorias:
        c.nullable = True
    try:
        m.Base.metadata.create_all(motor)
    finally:
        for c in obligatorias:
            c.nullable = False
    ahora = datetime.datetime.now()
    filas = [m.DjmdMyTag(ID=cid, Seq=seq, Name=nombre, Attribute=1, ParentID="root", UUID=str(uuid4()),
                         created_at=ahora, updated_at=ahora)
             for seq, (cid, nombre) in enumerate(zip(ids_categorias, CATEGORIAS), 1)]
    filas.append(m.AgentRegistry(registry_id="localUpdateCount", int_1=0, date_1=ahora, date_2=ahora,
                                 created_at=ahora, updated_at=ahora))
    filas.append(m.DjmdMenuItems(ID="1", Class=1, Name="TRACK", UUID=str(uuid4()), created_at=ahora, updated_at=ahora))
    filas.append(m.DjmdDevice(ID="1", MasterDBID="1", Name="prueba", UUID=str(uuid4()), created_at=ahora, updated_at=ahora))
    with Session(motor) as s:
        s.add_all(filas)
        s.commit()
    motor.dispose()
    config.guardar({"rekordbox": str(carpeta), "coleccion": str(carpeta / "coleccion"),
                    "incorporar": str(carpeta / "descargas"), "backup": str(carpeta / "backup")})
    (carpeta / "coleccion").mkdir()
    (carpeta / "descargas").mkdir()
    if paso_4:
        rb.sincronizar_categorias(simular=False, leer_archivos=False)
    return carpeta


def misma_ruta(a, b):
    """Compara dos rutas como lo hace la app, sin importar si vienen con barras de Windows o de Rekordbox."""
    return rb.mismo_path(Path(a).as_posix(), Path(b).as_posix())


def agregar_tema(ruta, titulo, artista="", genero="", anio=None, comentario=None):
    with rb.lock:
        db = rb.abrir()
        try:
            c = db.add_content(str(ruta), Title=titulo, **({"ReleaseYear": anio} if anio else {}),
                               **({"Commnt": comentario} if comentario else {}))
            if artista:
                c.ArtistID = (db.get_artist(Name=artista).first() or db.add_artist(artista)).ID
            if genero:
                c.GenreID = (db.get_genre(Name=genero).first() or db.add_genre(genero)).ID
            db.commit()
            return str(c.ID)
        finally:
            db.close()


def tema(cid):
    """Lo que la base dice de un tema, ya como textos."""
    with rb.lock:
        db = rb.abrir()
        try:
            c = db.get_content(ID=str(cid))
            if c is None:
                return None
            return {"titulo": c.Title, "artista": c.ArtistName, "genero": c.GenreName, "album": c.AlbumName,
                    "anio": c.ReleaseYear, "comentario": c.Commnt, "ruta": c.FolderPath}
        finally:
            db.close()
