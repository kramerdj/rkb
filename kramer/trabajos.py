"""Trabajos largos en segundo plano (analizar descargas, etc.) con progreso consultable."""
import threading
import time
import traceback
import uuid

_trabajos = {}
_lock = threading.Lock()


class Trabajo:
    def __init__(self, tipo, total=0):
        self.id = uuid.uuid4().hex[:10]
        self.tipo, self.total, self.hechos = tipo, total, 0
        self.estado = "corriendo"            # corriendo | listo | error | cancelado
        self.mensaje, self.error = "", ""
        self.items, self.resultado = [], None
        self.cancelar = False
        self.inicio = time.time()

    def avanzar(self, item=None, mensaje=None):
        with _lock:
            self.hechos += 1
            if item is not None:
                self.items.append(item)
            if mensaje:
                self.mensaje = mensaje

    def dict(self, desde=0):
        with _lock:
            resto = None
            if self.hechos and self.total and self.estado == "corriendo":
                resto = (time.time() - self.inicio) / self.hechos * (self.total - self.hechos)
            return {"id": self.id, "tipo": self.tipo, "estado": self.estado, "total": self.total,
                    "hechos": self.hechos, "mensaje": self.mensaje, "error": self.error,
                    "resta": resto, "items": self.items[desde:], "desde": desde,
                    "resultado": self.resultado}


def lanzar(tipo, funcion, total=0):
    t = Trabajo(tipo, total)
    with _lock:
        _trabajos[t.id] = t

    def correr():
        try:
            t.resultado = funcion(t)
            t.estado = "cancelado" if t.cancelar else "listo"
        except Exception as e:
            traceback.print_exc()
            t.estado, t.error = "error", (str(e) if type(e) is RuntimeError else f"{type(e).__name__}: {e}")

    threading.Thread(target=correr, daemon=True).start()
    return t


def obtener(tid):
    return _trabajos.get(tid)
