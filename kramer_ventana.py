"""RKB Collection Manager: ventana propia (sin navegador). Punto de entrada de la app."""
import os
import sys

if getattr(sys, "frozen", False) or sys.stdout is None or sys.stderr is None:
    # La app armada no tiene consola: los mensajes y errores van a un registro (sirve para «Reportar un problema»).
    try:
        from kramer import plataforma
        _d = plataforma.dir_app()
        _d.mkdir(parents=True, exist_ok=True)
        if (_d / "registro.txt").exists():
            os.replace(_d / "registro.txt", _d / "registro-anterior.txt")
        _reg = open(_d / "registro.txt", "w", encoding="utf-8", buffering=1)
    except Exception:
        _reg = open(os.devnull, "w")
    sys.stdout = sys.stderr = _reg

if len(sys.argv) > 1 and sys.argv[1] == "--mytags":
    # la app se llama a sí misma para correr My Tags en un proceso aparte
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    from kramer import mytags
    mytags.main()
    sys.exit(0)

import threading

import webview

from kramer import servidor


def main():
    srv = servidor.crear(0)                       # puerto libre cualquiera
    puerto = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    ventana = webview.create_window(
        "RKB Collection Manager", f"http://127.0.0.1:{puerto}/", width=1440, height=900,
        min_size=(1100, 700), background_color="#121316", text_select=True)

    def elegir(titulo):
        r = ventana.create_file_dialog(webview.FOLDER_DIALOG)
        return r[0] if r else ""

    servidor.EN_VENTANA = True
    servidor.ELEGIR_CARPETA = elegir
    servidor.AL_SALIR = ventana.destroy
    webview.start()
    srv.shutdown()


if __name__ == "__main__":
    main()
