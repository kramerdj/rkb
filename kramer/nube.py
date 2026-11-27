"""Conexión con el servidor de la app (Supabase): cartelera de eventos y "Mis anuncios".
La versión mínima se lee de GitHub (control/versiones.json).

Mientras URL/CLAVE estén vacías, todo esto queda apagado y la app funciona igual que antes.
La CLAVE es la "anon public key" de Supabase: es pública a propósito (va dentro de la app).
Lo que protege los datos son los permisos del lado del servidor (ver supabase.sql):
cualquiera puede leer los anuncios publicados y proponer uno nuevo; sólo el administrador publica.
"""
import base64
import datetime
import io
import os
import re
import threading
import time
import uuid

import requests

from . import config

URL = os.environ.get("KRAMER_NUBE_URL", "")          # ej. https://xxxx.supabase.co
CLAVE = os.environ.get("KRAMER_NUBE_CLAVE", "")      # anon public key
BUCKET = "flyers"
TIPOS = ["Evento", "Curso o taller", "Equipos", "Busco DJ", "Otro"]
_cache = {"novedades": None, "cuando": 0, "cartelera": None, "cart_cuando": 0}
_lock = threading.Lock()


class ErrorNube(Exception):
    codigo = None           # código HTTP con que respondió el servidor; None si no hubo respuesta


def configurado():
    return bool(URL and CLAVE)


def _h(token=None, extra=None):
    h = {"apikey": CLAVE, "Authorization": f"Bearer {token or CLAVE}"}
    h.update(extra or {})
    return h


def _pedir(metodo, ruta, token=None, timeout=8, **kw):
    if not configurado():
        raise ErrorNube("La cartelera todavía no está activa.")
    try:
        r = requests.request(metodo, URL.rstrip("/") + ruta, headers=_h(token, kw.pop("headers", None)), timeout=timeout, **kw)
    except requests.RequestException:
        raise ErrorNube("No hay conexión con el servidor. Revisá internet y probá de nuevo.")
    if r.status_code >= 400:
        try:
            d = r.json()
            msg = d.get("msg") or d.get("message") or d.get("error_description") or d.get("error") or r.text
        except ValueError:
            msg = r.text
        error = ErrorNube(_traducir(str(msg), r.status_code))
        error.codigo = r.status_code
        raise error
    if r.status_code == 204 or not r.content:
        return None
    try:
        return r.json()
    except ValueError:
        return r.text


def _traducir(msg, code):
    m = msg.lower()
    if "token has expired" in m or "otp" in m and "invalid" in m or "invalid" in m and "token" in m:
        return "El código no es válido o ya venció. Pedí uno nuevo."
    if "rate limit" in m or code == 429:
        return "Demasiados intentos seguidos. Esperá unos minutos y probá de nuevo."
    if "jwt expired" in m:
        return "Tu sesión venció. Volvé a entrar con tu email."
    if "row-level security" in m or code in (401, 403):
        return "No tenés permiso para hacer eso."
    return f"Error del servidor: {msg}"


# =============================================================================
# VERSIÓN Y NOVEDADES
# =============================================================================
def _num(v):
    try:
        n = [int(x) for x in str(v).strip().split(".")]
    except ValueError:
        return (0,)
    while len(n) > 1 and n[-1] == 0:        # «0.9.1.0» es la misma versión que «0.9.1»
        n.pop()
    return tuple(n)


CONTROL_URL = os.environ.get("KRAMER_CONTROL_URL",
                             "https://raw.githubusercontent.com/kramerdj/rkb/main/control/versiones.json")
DESCARGA = "https://github.com/kramerdj/rkb/releases/latest/download/RKB-Collection-Manager-{}.zip"


def _control(forzar):
    """El archivo control/versiones.json de GitHub (None si no hay internet o no se puede leer)."""
    with _lock:
        if not forzar and _cache["novedades"] is not None and time.time() - _cache["cuando"] < 600:
            return _cache["novedades"]
    try:
        r = requests.get(CONTROL_URL, timeout=5)
        r.raise_for_status()
        d = r.json()
        if not isinstance(d, dict):
            return None
    except (requests.RequestException, ValueError):
        return None
    with _lock:
        _cache.update(novedades=d, cuando=time.time())
    return d


def novedades(version_actual, forzar=False):
    """Última versión y versión mínima obligatoria, según control/versiones.json en GitHub.
    activo = si está la Cartelera (Supabase). Sin internet nunca bloquea: offline = True."""
    res = {"activo": configurado()}
    if not CONTROL_URL:
        return res
    d = _control(forzar)
    if d is None:
        return {**res, "offline": True}
    actual = _num(version_actual)
    ultima = str(d.get("ultima") or version_actual)
    res.update(offline=False, actual=version_actual, ultima=ultima, mensaje=str(d.get("mensaje") or ""),
               hayNueva=_num(ultima) > actual, bloqueo=False, diasGracia=None)
    link = d.get("link_win") if os.name == "nt" else d.get("link_mac")
    res["link"] = str(link or DESCARGA.format("Windows" if os.name == "nt" else "Mac"))
    minima = d.get("minima")
    # Una mínima más nueva que la última publicada no se puede cumplir (error de tipeo): no obliga a nadie.
    if minima and _num(ultima) >= _num(minima) > actual:
        desde = d.get("minima_desde") or datetime.date.today().isoformat()
        try:
            limite = datetime.date.fromisoformat(str(desde)[:10]) + datetime.timedelta(days=int(d.get("gracia_dias") or 0))
        except (ValueError, TypeError, OverflowError):
            limite = datetime.date.today()
        faltan = (limite - datetime.date.today()).days
        res["minima"] = str(minima)
        res["bloqueo"] = faltan < 0
        res["diasGracia"] = max(faltan, 0)
    return res


# =============================================================================
# CARTELERA (pública)
# =============================================================================
CAMPOS = "id,tipo,titulo,fecha,hora,lugar,ciudad,pais,region,alcance,texto,link,imagen,autor_nombre,destacado"
ALCANCES = ("region", "pais", "mundo")


def _norm(t):
    import unicodedata
    t = unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().casefold()
    return " ".join(t.replace(".", " ").split())


def ubicacion():
    u = config.cargar().get("ubicacion") or {}
    return {"pais": (u.get("pais") or "").upper()[:2], "region": (u.get("region") or "").strip()[:60]}


# zonas que en la práctica son la misma (se ven los anuncios entre sí)
VECINAS = [("AR", {"ciudad de buenos aires", "buenos aires (provincia)", "buenos aires", "caba"})]


def _misma_zona(pais, r1, r2):
    r1, r2 = _norm(r1), _norm(r2)
    if r1 == r2:
        return True
    return any(pais == p and r1 in grupo and r2 in grupo for p, grupo in VECINAS)


def le_corresponde(a, u):
    """¿Este anuncio es para alguien de esta ubicación?"""
    alc = a.get("alcance") or "region"
    if alc == "mundo":
        return True
    if not u["pais"] or (a.get("pais") or "").upper() != u["pais"]:
        return False
    return alc == "pais" or _misma_zona(u["pais"], a.get("region"), u["region"])


def cartelera(forzar=False):
    """Anuncios publicados y vigentes para la ubicación del usuario (al servidor sólo se le dice el país)."""
    if not configurado():
        return {"activo": False, "anuncios": []}
    u = ubicacion()
    with _lock:
        fresco = _cache["cartelera"] is not None and time.time() - _cache["cart_cuando"] < 300 and _cache.get("cart_pais") == u["pais"]
    if forzar or not fresco:
        hoy = datetime.date.today().isoformat()
        filtro = f"or=(alcance.eq.mundo,pais.eq.{u['pais']})" if u["pais"] else "alcance=eq.mundo"
        try:
            filas = _pedir("GET", f"/rest/v1/anuncios?select={CAMPOS}&estado=eq.publicado&fecha=gte.{hoy}&{filtro}"
                                  "&order=destacado.desc,fecha.asc,hora.asc&limit=300", timeout=6)
        except ErrorNube as e:
            return {"activo": True, "anuncios": [a for a in (_cache["cartelera"] or []) if le_corresponde(a, u)],
                    "ubicacion": u, "error": str(e)}
        with _lock:
            _cache.update(cartelera=filas, cart_cuando=time.time(), cart_pais=u["pais"])
    return {"activo": True, "ubicacion": u, "anuncios": [a for a in _cache["cartelera"] if le_corresponde(a, u)]}


def link_publicado(url):
    """Sólo se abren links que sean de anuncios publicados (no cualquier cosa que llegue a la API)."""
    return any(a.get("link") == url for a in (_cache["cartelera"] or [])) and url.startswith(("https://", "http://"))


# =============================================================================
# SESIÓN (email + código)
# =============================================================================
def _sesion():
    return config.cargar().get("nube_sesion") or {}


def _guardar_sesion(d):
    config.guardar({"nube_sesion": d})


def pedir_codigo(email):
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ErrorNube("Revisá el email.")
    _pedir("POST", "/auth/v1/otp", json={"email": email, "create_user": True})
    return email


def verificar_codigo(email, codigo):
    d = _pedir("POST", "/auth/v1/verify", json={"type": "email", "email": email.strip().lower(), "token": str(codigo).strip()})
    return _tomar_token(d)


def _tomar_token(d):
    if not d or "access_token" not in d:
        raise ErrorNube("No se pudo iniciar sesión.")
    s = {"access": d["access_token"], "refresh": d["refresh_token"],
         "vence": time.time() + int(d.get("expires_in") or 3600) - 60,
         "uid": d["user"]["id"], "email": d["user"].get("email", "")}
    _guardar_sesion(s)
    return s


def token():
    s = _sesion()
    if not s.get("refresh"):
        raise ErrorNube("Entrá con tu email para manejar tus anuncios.")
    if time.time() < s.get("vence", 0):
        return s
    try:
        d = _pedir("POST", "/auth/v1/token?grant_type=refresh_token", json={"refresh_token": s["refresh"]})
    except ErrorNube as e:
        if e.codigo not in (400, 401, 403):     # sin internet o servidor caído: la sesión sigue valiendo
            raise
        _guardar_sesion(None)
        raise ErrorNube("Tu sesión venció. Volvé a entrar con tu email.")
    return _tomar_token(d)


def salir():
    s = _sesion()
    if s.get("access"):
        try:
            _pedir("POST", "/auth/v1/logout", token=s["access"], timeout=4)
        except ErrorNube:
            pass
    _guardar_sesion(None)


def quien():
    if not configurado():
        return {"activo": False}
    s = _sesion()
    if not s.get("refresh"):
        return {"activo": True, "conectado": False}
    try:
        s = token()
        perfil = _pedir("GET", f"/rest/v1/perfiles?select=nombre,admin&id=eq.{s['uid']}", token=s["access"]) or []
    except ErrorNube as e:
        return {"activo": True, "conectado": False, "error": str(e)}
    p = perfil[0] if perfil else {}
    return {"activo": True, "conectado": True, "email": s["email"], "nombre": p.get("nombre") or "", "admin": bool(p.get("admin"))}


def guardar_nombre(nombre):
    s = token()
    nombre = (nombre or "").strip()[:60]
    _pedir("POST", "/rest/v1/perfiles?on_conflict=id", token=s["access"],
           headers={"Prefer": "resolution=merge-duplicates"}, json={"id": s["uid"], "nombre": nombre})
    return nombre


# =============================================================================
# MIS ANUNCIOS
# =============================================================================
def mis_anuncios():
    s = token()
    return _pedir("GET", f"/rest/v1/anuncios?select=*&autor=eq.{s['uid']}&order=fecha.desc", token=s["access"]) or []


def _subir_imagen(s, data_url):
    """Recibe la imagen como data URL, la achica a 1200 px (JPEG) y la sube. Devuelve la URL pública."""
    try:
        cab, b64 = data_url.split(",", 1)
        crudo = base64.b64decode(b64)
    except Exception:
        raise ErrorNube("No pude leer la imagen.")
    if len(crudo) > 15e6:
        raise ErrorNube("La imagen es demasiado grande (máximo 15 MB).")
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(crudo))
        img = img.convert("RGB")
    except Exception:
        raise ErrorNube("Ese archivo no es una imagen válida.")
    img.thumbnail((1200, 1200))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)
    ruta = f"{s['uid']}/{uuid.uuid4().hex}.jpg"
    _pedir("POST", f"/storage/v1/object/{BUCKET}/{ruta}", token=s["access"], timeout=30,
           headers={"Content-Type": "image/jpeg", "x-upsert": "false"}, data=out.getvalue())
    return f"{URL.rstrip('/')}/storage/v1/object/public/{BUCKET}/{ruta}"


def _limpiar(a):
    tipo = a.get("tipo") if a.get("tipo") in TIPOS else "Otro"
    titulo = (a.get("titulo") or "").strip()[:80]
    fecha = (a.get("fecha") or "").strip()[:10]
    if not titulo:
        raise ErrorNube("Poné un título.")
    try:
        if datetime.date.fromisoformat(fecha) < datetime.date.today():
            raise ErrorNube("La fecha ya pasó.")
    except ValueError:
        raise ErrorNube("Poné una fecha válida.")
    link = (a.get("link") or "").strip()[:300]
    if link and not link.startswith(("https://", "http://")):
        link = "https://" + link
    pais = (a.get("pais") or "").strip().upper()[:2]
    if not re.fullmatch(r"[A-Z]{2}", pais):
        raise ErrorNube("Elegí el país del anuncio.")
    alcance = a.get("alcance") if a.get("alcance") in ALCANCES else "region"
    region = (a.get("region") or "").strip()[:60]
    if alcance == "region" and not region:
        raise ErrorNube("Elegí la provincia o estado (o mostralo en todo el país).")
    return {"pais": pais, "region": region or None, "alcance": alcance, "tipo": tipo, "titulo": titulo, "fecha": fecha, "hora": (a.get("hora") or "").strip()[:5] or None,
            "lugar": (a.get("lugar") or "").strip()[:80], "ciudad": (a.get("ciudad") or "").strip()[:60],
            "texto": (a.get("texto") or "").strip()[:600], "link": link}


def guardar_anuncio(a):
    s = token()
    datos = _limpiar(a)
    perfil = _pedir("GET", f"/rest/v1/perfiles?select=nombre&id=eq.{s['uid']}", token=s["access"]) or []
    datos["autor_nombre"] = (perfil[0].get("nombre") if perfil else "") or s["email"].split("@")[0]
    if a.get("imagenNueva"):
        datos["imagen"] = _subir_imagen(s, a["imagenNueva"])
    elif a.get("quitarImagen"):
        datos["imagen"] = None
    if a.get("id"):                      # editar: vuelve a revisión (lo fuerza el servidor)
        r = _pedir("PATCH", f"/rest/v1/anuncios?id=eq.{a['id']}&autor=eq.{s['uid']}", token=s["access"],
                   headers={"Prefer": "return=representation"}, json=datos)
    else:
        datos["autor"] = s["uid"]
        r = _pedir("POST", "/rest/v1/anuncios", token=s["access"], headers={"Prefer": "return=representation"}, json=datos)
    if not r:
        raise ErrorNube("No se pudo guardar el anuncio.")
    return r[0]


def borrar_anuncio(aid):
    s = token()
    _pedir("DELETE", f"/rest/v1/anuncios?id=eq.{aid}&autor=eq.{s['uid']}", token=s["access"])


# =============================================================================
# ADMINISTRADOR (los permisos los controla el servidor, no la app)
# =============================================================================
def pendientes():
    s = token()
    return _pedir("GET", "/rest/v1/anuncios?select=*,perfiles(email)&estado=eq.pendiente&order=creado.asc", token=s["access"]) or []


def moderar(aid, estado, motivo="", destacado=None):
    if estado not in ("publicado", "rechazado"):
        raise ErrorNube("Estado inválido.")
    s = token()
    datos = {"estado": estado, "motivo": (motivo or "").strip()[:300] or None}
    if destacado is not None:
        datos["destacado"] = bool(destacado)
    _pedir("PATCH", f"/rest/v1/anuncios?id=eq.{aid}", token=s["access"], json=datos)
    with _lock:
        _cache["cart_cuando"] = 0
