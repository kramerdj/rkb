"""Estadísticas anónimas de uso con Aptabase (pedido de Guido, noviembre de 2026).

Qué se envía, y nada más:
  · "instalada": una sola vez, la primera vez que se abre la app (con las estadísticas prendidas).
  · "abierta": como mucho una vez por día. Datos: versión, sistema (Mac/Windows), en cuántos días
    distintos se usó (1, 2-3, 4-7, 8-15, 16+) y semanas desde que se instaló.
  · "uso": cuando se hace una acción real (ver ACCIONES), con el nombre de la acción.
    Como mucho una vez por día por acción.

Nunca se envía nada de la colección ni de la persona: ni temas, ni rutas, ni nombres, ni cantidades
de temas, ni identificadores. Cada apertura de la app usa una sesión al azar que no se guarda.
Aptabase deduce el país de la conexión y no guarda la IP (https://aptabase.com/docs).

Todo va en segundo plano: sin internet o si Aptabase falla, no pasa nada (se reintenta otro día).
Sólo envía la app armada (no el código fuente ni las pruebas) y sólo después de que la persona vio
la explicación: en el aviso del primer arranque o, si ya usaba la app antes, en un aviso propio. Se apaga en Ajustes («Enviar estadísticas anónimas de uso»).
Usa sólo `requests`, que ya viene en la app: llega también por la actualización automática.
"""
import datetime
import json
import os
import random
import sys
import threading
import time

from . import config

APP_KEY = "A-US-3833382263"
URL = os.environ.get("KRAMER_ESTADISTICAS_URL", "https://us.aptabase.com/api/v0/events")
ACCIONES = {"comparar lista", "analizar descargas", "incorporar", "sincronizar", "duplicados",
            "backup", "playlist Spotify", "My Tags"}

_lock = threading.Lock()
_en_vuelo = set()           # eventos que se están enviando (para no mandar dos veces el mismo)
_sesion = f"{int(time.time())}{random.randint(0, 99999999):08d}"   # al azar, sólo vive mientras la app está abierta
_version = ""
_chequeado = None         # día en que ya se revisó al abrir (la página pide el estado seguido)


def _activas():
    """La app armada (o forzada con KRAMER_ESTADISTICAS=1), con el aviso aceptado y el interruptor prendido."""
    if os.environ.get("KRAMER_ESTADISTICAS") == "0":
        return False
    if not (getattr(sys, "frozen", False) or os.environ.get("KRAMER_ESTADISTICAS") == "1"):
        return False
    c = config.cargar()
    return bool(c.get("acepto_riesgo") and c.get("estadisticas_avisado")) and c.get("estadisticas", True) is not False


def _sistema():
    return "Windows" if sys.platform.startswith("win") else "Mac"


def _hoy():
    return datetime.date.today().isoformat()


def rango_dias(n):
    return "1" if n <= 1 else "2-3" if n <= 3 else "4-7" if n <= 7 else "8-15" if n <= 15 else "16+"


def _estado():
    e = config.cargar().get("estadisticas_estado")
    return dict(e) if isinstance(e, dict) else {}


def _guardar(cambiar):
    """Cambia el estado local (sólo en esta compu): cambiar(estado) lo modifica. Si no se puede escribir, sigue igual."""
    try:
        with _lock:
            e = _estado()
            cambiar(e)
            config.guardar({"estadisticas_estado": e})
    except Exception:
        pass


def _post(nombre, props):
    """Un evento a Aptabase (formato de https://github.com/aptabase/aptabase/wiki/How-to-build-your-own-SDK)."""
    import requests
    ahora = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    evento = {"timestamp": ahora, "sessionId": _sesion, "eventName": nombre,
              "systemProps": {"isDebug": not getattr(sys, "frozen", False), "appVersion": _version,
                              "osName": "Windows" if _sistema() == "Windows" else "macOS",
                              "sdkVersion": "rkb-collection-manager@1"},
              "props": props}
    r = requests.post(URL, data=json.dumps([evento]), timeout=8,
                      headers={"Content-Type": "application/json", "App-Key": APP_KEY})
    return 200 <= r.status_code < 300


def _enviar(clave, nombre, props, al_salir_bien):
    """Manda en segundo plano; si sale bien, anota con al_salir_bien(estado) para no repetirlo."""
    with _lock:
        if clave in _en_vuelo:
            return None
        _en_vuelo.add(clave)

    def trabajo():
        try:
            if _post(nombre, props):
                _guardar(al_salir_bien)
        except Exception:
            pass                    # sin internet o Aptabase caído: no se nota, se reintenta otro día
        finally:
            with _lock:
                _en_vuelo.discard(clave)

    hilo = threading.Thread(target=trabajo, daemon=True)
    hilo.start()
    return hilo


def al_abrir(version, de_nuevo=False):
    """Se llama al abrir la app (y cuando se acepta el aviso). Manda «instalada» y «abierta» si corresponde."""
    global _version, _chequeado
    _version = version
    try:
        hoy = _hoy()
        if (_chequeado == hoy and not de_nuevo) or not config.cargar().get("acepto_riesgo"):
            return []
        _chequeado = hoy
        e = _estado()
        if e.get("ultimo_dia") != hoy:          # días distintos de uso: se cuentan sólo en esta compu
            e = {**e, "dias": int(e.get("dias") or 0) + 1, "ultimo_dia": hoy}
            e.setdefault("desde", hoy)
            _guardar(lambda x: x.update({k: e[k] for k in ("dias", "ultimo_dia", "desde")}))
        if not _activas():
            return []
        hilos = []
        if not e.get("instalada"):
            hilos.append(_enviar("instalada", "instalada", {},
                                 lambda x: x.update(instalada=hoy)))
        if e.get("abierta") != hoy:
            try:
                semanas = max(0, (datetime.date.fromisoformat(hoy) - datetime.date.fromisoformat(e["desde"])).days // 7)
            except (KeyError, ValueError):
                semanas = 0
            hilos.append(_enviar("abierta", "abierta", {
                "version": version, "sistema": _sistema(), "dias_de_uso": rango_dias(int(e.get("dias") or 1)),
                "semanas_instalada": semanas}, lambda x: x.update(abierta=hoy)))
        return [h for h in hilos if h]
    except Exception:
        return []


def uso(accion):
    """Una acción real hecha (una de ACCIONES). Como mucho una vez por día por acción."""
    try:
        if accion not in ACCIONES or not _activas():
            return None
        hoy = _hoy()
        if (_estado().get("uso") or {}).get(accion) == hoy:
            return None

        def anotar(e):
            e["uso"] = {**(e.get("uso") or {}), accion: hoy}
        return _enviar(f"uso:{accion}", "uso", {"accion": accion}, anotar)
    except Exception:
        return None
