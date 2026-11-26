"""Paso 1: traer la lista de temas (solo nombres) desde un link de Spotify, YouTube / YouTube Music o Deezer.
No baja audio: lee el nombre y el artista de cada tema de una playlist o álbum público."""
import base64
import json
import re
from urllib.parse import parse_qs, urlparse

import requests

from . import config

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
TIMEOUT = 20


class ErrorLink(Exception):
    pass


def _get(url, **kw):
    h = {"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9,en;q=0.8"}
    h.update(kw.pop("headers", {}))
    r = requests.get(url, headers=h, timeout=TIMEOUT, **kw)
    if r.status_code == 404:
        raise ErrorLink("No encontré esa lista: revisá que el link sea correcto y que la playlist sea pública.")
    r.raise_for_status()
    return r


def extraer(url):
    url = (url or "").strip()
    if not url:
        raise ErrorLink("Pegá un link.")
    host = urlparse(url).netloc.lower()
    if "spotify" in host:
        return spotify(url)
    if "youtube" in host or "youtu.be" in host:
        return youtube(url)
    if "deezer" in host:
        return deezer(url)
    raise ErrorLink("Por ahora entiendo links de Spotify, YouTube / YouTube Music y Deezer.")


# =============================================================================
# SPOTIFY
# =============================================================================
def _spotify_id(url):
    m = re.search(r"(playlist|album|track)/([A-Za-z0-9]{10,})", url)
    if not m:
        m2 = re.match(r"spotify:(playlist|album|track):([A-Za-z0-9]+)", url)
        if not m2:
            raise ErrorLink("Ese link de Spotify no es de una playlist, un álbum o un tema.")
        return m2.group(1), m2.group(2)
    return m.group(1), m.group(2)


def _spotify_token(cid, secret):
    r = requests.post("https://accounts.spotify.com/api/token", data={"grant_type": "client_credentials"},
                      headers={"Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()},
                      timeout=TIMEOUT)
    if r.status_code != 200:
        raise ErrorLink("Spotify rechazó las claves de Ajustes (Client ID / Client Secret).")
    return r.json()["access_token"]


def spotify(url):
    tipo, sid = _spotify_id(url)
    c = config.cargar()
    if c.get("spotify_id") and c.get("spotify_secret"):
        try:
            return _spotify_api(tipo, sid, _spotify_token(c["spotify_id"], c["spotify_secret"]))
        except ErrorLink:
            raise
        except Exception:
            pass                     # si la API falla, se intenta con la página pública
    return _spotify_embed(tipo, sid)


def _spotify_api(tipo, sid, token):
    h = {"Authorization": f"Bearer {token}"}
    base = "https://api.spotify.com/v1"
    if tipo == "track":
        t = _get(f"{base}/tracks/{sid}", headers=h).json()
        return {"nombre": t["name"], "temas": [_sp_tema(t)], "completa": True, "fuente": "Spotify"}
    info = _get(f"{base}/{tipo}s/{sid}", headers=h, params={"fields": "name"} if tipo == "playlist" else None).json()
    temas = []
    # playlists: /items (desde 2026 Spotify sólo muestra el contenido de playlists tuyas por API;
    # si no es tuya, se cae al lector de la página pública)
    sig = f"{base}/playlists/{sid}/items?limit=100" if tipo == "playlist" else f"{base}/albums/{sid}/tracks?limit=50"
    while sig:
        d = _get(sig, headers=h).json()
        for it in d.get("items", []):
            t = (it.get("item") or it.get("track")) if tipo == "playlist" else it
            if t and t.get("name"):
                temas.append(_sp_tema(t))
        sig = d.get("next")
    if not temas:
        raise RuntimeError("sin contenido por API")
    return {"nombre": info.get("name", ""), "temas": temas, "completa": True, "fuente": "Spotify"}


def _sp_tema(t):
    return {"artista": ", ".join(a["name"] for a in t.get("artists", []) if a.get("name")), "titulo": t["name"]}


def _spotify_embed(tipo, sid):
    html = _get(f"https://open.spotify.com/embed/{tipo}/{sid}").text
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ErrorLink("No pude leer la lista desde Spotify. Probá cargando las claves de Spotify en Ajustes.")
    datos = json.loads(m.group(1))
    ent = _buscar(datos, lambda d: isinstance(d, dict) and "trackList" in d) or {}
    temas = [{"artista": (t.get("subtitle") or "").replace(" ", " "), "titulo": t.get("title", "")}
             for t in ent.get("trackList", []) if t.get("title")]
    if not temas and tipo == "track":
        temas = [{"artista": ent.get("subtitle", ""), "titulo": ent.get("title") or ent.get("name", "")}]
    if not temas:
        raise ErrorLink("La lista de Spotify vino vacía. ¿Es pública?")
    return {"nombre": ent.get("name") or ent.get("title", ""), "temas": temas,
            "completa": len(temas) < 100, "fuente": "Spotify"}


# =============================================================================
# YOUTUBE / YOUTUBE MUSIC
# =============================================================================
_CANAL = re.compile(r"\s*(-\s*Topic|VEVO|Official|Oficial|Music|TV)\s*$", re.I)


def _yt_tema(titulo, canal):
    titulo = (titulo or "").strip()
    for sep in (" - ", " – ", " — ", " | "):
        if sep in titulo:
            a, t = titulo.split(sep, 1)
            return {"artista": a.strip(), "titulo": t.strip()}
    artista = _CANAL.sub("", (canal or "").strip())
    artista = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", artista) if " " not in artista else artista   # "BadBunny" -> "Bad Bunny"
    return {"artista": artista, "titulo": titulo}


def youtube(url):
    q = parse_qs(urlparse(url).query)
    lista = (q.get("list") or [""])[0]
    if not lista:
        raise ErrorLink("Ese link de YouTube no es de una playlist (le falta «list=…»).")
    if lista.startswith("RD"):
        raise ErrorLink("Ese link es un «mix» automático de YouTube: no se puede leer. Usá una playlist guardada.")
    clave = config.cargar().get("youtube_key")
    if clave:
        try:
            return _youtube_api(lista, clave)
        except ErrorLink:
            raise
        except Exception:
            pass
    return _youtube_pagina(lista)


def _youtube_api(lista, clave):
    base = "https://www.googleapis.com/youtube/v3"
    info = _get(f"{base}/playlists", params={"part": "snippet", "id": lista, "key": clave}).json()
    if not info.get("items"):
        raise ErrorLink("No encontré esa playlist en YouTube. ¿Es pública o no listada?")
    temas, token = [], None
    while True:
        p = {"part": "snippet", "playlistId": lista, "maxResults": 50, "key": clave}
        if token:
            p["pageToken"] = token
        d = _get(f"{base}/playlistItems", params=p).json()
        for it in d.get("items", []):
            s = it["snippet"]
            if s.get("title") in ("Deleted video", "Private video"):
                continue
            temas.append(_yt_tema(s.get("title"), s.get("videoOwnerChannelTitle")))
        token = d.get("nextPageToken")
        if not token:
            break
    return {"nombre": info["items"][0]["snippet"]["title"], "temas": temas, "completa": True, "fuente": "YouTube"}


def _youtube_pagina(lista):
    r = _get("https://www.youtube.com/playlist", params={"list": lista, "hl": "es"},
             cookies={"CONSENT": "YES+cb", "SOCS": "CAI"})
    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", r.text, re.S)
    if not m:
        raise ErrorLink("No pude leer la playlist de YouTube. Probá cargando una clave de YouTube en Ajustes.")
    datos = json.loads(m.group(1))
    temas = []
    for v in _todos(datos, "playlistVideoRenderer"):
        titulo = "".join(x.get("text", "") for x in v.get("title", {}).get("runs", [])) or \
            v.get("title", {}).get("simpleText", "")
        canal = "".join(x.get("text", "") for x in v.get("shortBylineText", {}).get("runs", []))
        if titulo and titulo not in ("[Video eliminado]", "[Video privado]", "[Deleted video]", "[Private video]"):
            temas.append(_yt_tema(titulo, canal))
    nombre = ""
    meta = _buscar(datos, lambda d: isinstance(d, dict) and "playlistMetadataRenderer" in d)
    if meta:
        nombre = meta["playlistMetadataRenderer"].get("title", "")
    if not nombre:
        t = re.search(r"<title>(.*?)</title>", r.text)
        nombre = re.sub(r"\s*-\s*YouTube\s*$", "", t.group(1)) if t else ""
    if not temas:
        raise ErrorLink("La playlist de YouTube vino vacía. ¿Es pública o no listada?")
    hay_mas = bool(_buscar(datos, lambda d: isinstance(d, dict) and "continuationItemRenderer" in d))
    return {"nombre": nombre, "temas": temas, "completa": not hay_mas, "fuente": "YouTube"}


# =============================================================================
# DEEZER (API pública, sin claves)
# =============================================================================
def deezer(url):
    u = url
    if "deezer.page.link" in url or "link.deezer.com" in url:
        u = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True).url
    m = re.search(r"(playlist|album|track)/(\d+)", u)
    if not m:
        raise ErrorLink("Ese link de Deezer no es de una playlist, un álbum o un tema.")
    tipo, did = m.groups()
    base = "https://api.deezer.com"
    info = _get(f"{base}/{tipo}/{did}").json()
    if info.get("error"):
        raise ErrorLink("No encontré esa lista en Deezer. ¿Es pública?")
    if tipo == "track":
        return {"nombre": info["title"], "temas": [{"artista": info["artist"]["name"], "titulo": info["title"]}],
                "completa": True, "fuente": "Deezer"}
    temas, sig = [], f"{base}/{tipo}/{did}/tracks?limit=100"
    while sig:
        d = _get(sig).json()
        for t in d.get("data", []):
            temas.append({"artista": t.get("artist", {}).get("name", ""), "titulo": t.get("title", "")})
        sig = d.get("next")
    return {"nombre": info.get("title", ""), "temas": temas, "completa": True, "fuente": "Deezer"}


# =============================================================================
def _buscar(obj, cond):
    if cond(obj):
        return obj
    hijos = obj.values() if isinstance(obj, dict) else obj if isinstance(obj, list) else []
    for h in hijos:
        r = _buscar(h, cond)
        if r is not None:
            return r
    return None


def _todos(obj, clave):
    if isinstance(obj, dict):
        if clave in obj:
            yield obj[clave]
        for v in obj.values():
            yield from _todos(v, clave)
    elif isinstance(obj, list):
        for v in obj:
            yield from _todos(v, clave)


# =============================================================================
# CREAR PLAYLIST EN SPOTIFY (con tu cuenta: autorización una sola vez)
# =============================================================================
import hashlib
import os
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode

PUERTO_SPOTIFY = 8898
REDIRECT = f"http://127.0.0.1:{PUERTO_SPOTIFY}/callback"
PERMISOS = "playlist-modify-private playlist-modify-public"


def spotify_estado():
    c = config.cargar()
    return {"clientId": bool(c.get("spotify_id")), "conectado": bool(c.get("spotify_refresh")),
            "usuario": c.get("spotify_usuario", ""), "redirect": REDIRECT}


def spotify_conectar(espera=180):
    """Abre el navegador para que autorices la app (PKCE: no hace falta el Secret)."""
    cid = config.cargar().get("spotify_id", "").strip()
    if not cid:
        raise ErrorLink("Primero cargá el Client ID de Spotify en Ajustes.")
    verificador = secrets.token_urlsafe(64)[:96]
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).decode().rstrip("=")
    estado = secrets.token_urlsafe(16)
    resultado = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            ok = q.get("state", [""])[0] == estado and "code" in q
            resultado.update(code=q.get("code", [""])[0] if ok else "", error=q.get("error", [""])[0])
            msg = ("Listo: RKB Collection Manager quedó conectado a tu Spotify. Ya podés cerrar esta pestaña."
                   if ok else "No se pudo conectar con Spotify. Volvé a la app y probá de nuevo.")
            cuerpo = f"<html><body style='font-family:-apple-system;background:#121316;color:#E8E9EC;padding:40px'>{msg}</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(cuerpo.encode())

    try:
        srv = HTTPServer(("127.0.0.1", PUERTO_SPOTIFY), H)
    except OSError:
        raise ErrorLink(f"El puerto {PUERTO_SPOTIFY} está ocupado. Cerrá otras ventanas de conexión y probá de nuevo.")
    srv.timeout = 1
    url = "https://accounts.spotify.com/authorize?" + urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": REDIRECT, "scope": PERMISOS,
        "state": estado, "code_challenge_method": "S256", "code_challenge": desafio})
    from . import plataforma
    plataforma.abrir_url(url)
    fin = time.time() + espera
    while not resultado and time.time() < fin:
        srv.handle_request()
    srv.server_close()
    if not resultado.get("code"):
        raise ErrorLink("Spotify no confirmó la autorización" +
                        (f" ({resultado['error']})." if resultado.get("error") else " a tiempo."))
    r = requests.post("https://accounts.spotify.com/api/token", timeout=TIMEOUT, data={
        "grant_type": "authorization_code", "code": resultado["code"], "redirect_uri": REDIRECT,
        "client_id": cid, "code_verifier": verificador})
    if r.status_code != 200:
        raise ErrorLink("Spotify rechazó la autorización: revisá que el Redirect URI de tu app sea " + REDIRECT)
    tok = r.json()
    yo = requests.get("https://api.spotify.com/v1/me", timeout=TIMEOUT,
                      headers={"Authorization": f"Bearer {tok['access_token']}"}).json()
    config.guardar({"spotify_refresh": tok["refresh_token"], "spotify_usuario": yo.get("display_name") or yo.get("id", "")})
    return spotify_estado()


def _token_usuario():
    c = config.cargar()
    if not c.get("spotify_refresh"):
        raise ErrorLink("Conectá tu cuenta de Spotify (Ajustes → Conectar con Spotify).")
    r = requests.post("https://accounts.spotify.com/api/token", timeout=TIMEOUT, data={
        "grant_type": "refresh_token", "refresh_token": c["spotify_refresh"], "client_id": c["spotify_id"]})
    if r.status_code != 200:
        config.guardar({"spotify_refresh": ""})
        raise ErrorLink("La conexión con Spotify venció. Volvé a conectar tu cuenta en Ajustes.")
    tok = r.json()
    if tok.get("refresh_token"):
        config.guardar({"spotify_refresh": tok["refresh_token"]})
    return tok["access_token"]


def _sp(metodo, url, token, **kw):
    for intento in range(4):
        r = requests.request(metodo, url, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT, **kw)
        if r.status_code == 429:                       # demasiadas consultas: esperar lo que pide
            time.sleep(min(int(r.headers.get("Retry-After", "2")) + 1, 30))
            continue
        return r
    return r


def _limpio(s):
    return re.sub(r"\s*[\(\[][^\)\]]*(official|oficial|video|audio|lyric|letra|bpm|remaster)[^\)\]]*[\)\]]", "", s or "", flags=re.I).strip()


def spotify_crear_playlist(nombre, temas, publica, trabajo):
    token = _token_usuario()
    uris, no = [], []
    for t in temas:
        if trabajo.cancelar:
            break
        art, tit = _limpio(t.get("artista")), _limpio(t.get("titulo"))
        uri = None
        for q in ([f'track:"{tit}" artist:"{art.split(",")[0]}"'] if art else []) + [f"{art} {tit}".strip()]:
            r = _sp("GET", "https://api.spotify.com/v1/search", token, params={"q": q, "type": "track", "limit": 1})
            if r.status_code == 200:
                items = r.json().get("tracks", {}).get("items", [])
                if items:
                    uri = items[0]["uri"]
                    break
        if uri and uri not in uris:
            uris.append(uri)
        elif not uri:
            no.append(f"{art} - {tit}" if art else tit)
        trabajo.avanzar({"ok": bool(uri)}, tit)
    r = _sp("POST", "https://api.spotify.com/v1/me/playlists", token,
            json={"name": nombre, "public": bool(publica), "description": "Creada con RKB Collection Manager"})
    if r.status_code not in (200, 201):
        raise ErrorLink(f"Spotify no dejó crear la playlist ({r.status_code}).")
    pl = r.json()
    # Desde febrero de 2026 Spotify cambió /tracks por /items
    for i in range(0, len(uris), 100):
        lote = uris[i:i + 100]
        r = _sp("POST", f"https://api.spotify.com/v1/playlists/{pl['id']}/items", token, json={"uris": lote})
        if r.status_code in (404, 405, 410):
            r = _sp("POST", f"https://api.spotify.com/v1/playlists/{pl['id']}/tracks", token, json={"uris": lote})
        if r.status_code not in (200, 201):
            detalle = ""
            try:
                detalle = r.json().get("error", {}).get("message", "")
            except Exception:
                pass
            raise ErrorLink(f"Spotify creó la playlist pero no dejó agregar los temas ({r.status_code} {detalle}).")
    return {"url": pl.get("external_urls", {}).get("spotify", ""), "agregados": len(uris), "noEncontrados": no}
