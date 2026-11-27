# CLAUDE.md — contexto para trabajar en RKB Collection Manager

Lo lee Claude Code al abrir el proyecto. Mantenelo al día cuando cambie algo importante.

## Quiénes y cómo

- Dueño del producto: **Guido (KRAMER DJ)**, DJ de eventos en Argentina. **No es programador**: hablale en castellano rioplatense, simple, sin jerga; explicá qué cambia para el usuario, no cómo está hecho.
- Colabora **Mauro** (ingeniero de software), que administra la organización `kramerdj` en GitHub. Guido decide: los cambios se suben directo a `main`, sin esperar revisión de Mauro.
- Toda la interfaz, los mensajes y los comentarios del código están en castellano (voseo). El inglés como idioma de la interfaz está pendiente (ver abajo).

## Qué es

App de escritorio (Mac Apple Silicon y Windows 10/11) que gestiona la colección de Rekordbox 6/7 de un DJ. Python + interfaz web local en una ventana propia.

```
kramer_arranque.py       arranque: elige si carga el código incluido o un paquete de actualización firmado (ed25519) más nuevo.
                         Queda fuera de kramer/ a propósito: ninguna actualización lo reemplaza
kramer_ventana.py        entrada de la app (pywebview, puerto al azar). --version, --mytags (modo línea de comandos viejo)
kramer_app.py            modo desarrollo en navegador (puerto 8765)
publicar_actualizacion.py  herramienta del desarrollador: genera la clave y arma/firma paquetes de actualización
kramer/
  servidor.py            ThreadingHTTPServer: sirve web/ y la API JSON (/api/...). VERSION se lee de web/version.txt
  rb.py                  todo lo que lee/escribe la base de Rekordbox (pyrekordbox 0.5.0, MasterDatabase)
  historial.py           Operacion: backup de la base y de archivos antes de cada cambio + deshacer
  categorias.py          reglas de My Tags automáticos (origen/idioma, década, versión, BPM)
  nombres.py             nombres de archivo prolijos «Artista - Título (feat. X) (Versión)»
  ingreso.py             pasos 2 y 3: metadata, análisis de calidad (ffmpeg de imageio-ffmpeg), incorporar
  oc.py                  motor de metadata (MusicBrainz, Wikidata, iTunes, Deezer, Last.fm, Discogs, CAA)
  lista.py / streaming.py  paso 1: leer listas y links (Spotify, YouTube, Deezer); crear playlist en Spotify (PKCE)
  respaldo.py            backup completo (zip de la base + copia espejo de la colección) y restauración
  nube.py                Cartelera / Mis anuncios contra Supabase (apagado si URL/CLAVE vacías) + versión mínima desde GitHub
  plataforma.py          diferencias Mac/Windows (carpetas, abrir/mostrar archivos)
  config.py              config.json por usuario (Mac: ~/Library/Application Support/KramerDJ, Win: %APPDATA%\KramerDJ)
  trabajos.py            tareas largas en segundo plano con progreso
web/                     index.html + app.js (colección, ajustes), pasos.js (pasos 1–3), respaldo.js, cartelera.js
supabase.sql             esquema y permisos del servidor (se puede correr más de una vez)
web/version.txt          ÚNICA fuente de la versión (la leen la app, los scripts y el pipeline)
tests/                   pruebas sin Rekordbox: python -m unittest discover -s tests -v
  herramientas/supabase_simulado.py  servidor de prueba para Cartelera y Mis anuncios
.github/workflows/       pruebas.yml (cada push y PR) · publicar.yml (armado Mac+Windows, paquete firmado y Release, a mano)
                         · obligar.yml (obligar a actualizar / liberar, a mano)
control/versiones.json   última versión y versión mínima obligatoria (la leen las apps instaladas)
```

## Reglas que no se rompen

1. **La base de Rekordbox es sagrada.** Toda escritura va dentro de `historial.Operacion` (backup previo + registro para deshacer) y sólo con Rekordbox cerrado (`requiere_cerrado()` / `rb.rekordbox_abierto()`).
2. **My Tags:** en la config las categorías son lugares "1".."4" (1ª..4ª columna de Rekordbox), no ID de la base. Pasar siempre por `rb.ids_categorias(db)`: en algunas bases (Windows) las categorías no tienen los ID 1 a 4. Las categorías automáticas no muestran tags sin temas (los de fábrica de Rekordbox). Una categoría automática se llena sola recién cuando en Rekordbox ya lleva el nombre de la app (después de «Actualizar base de Rekordbox» en el paso 4): antes puede tener tags propios del usuario, y el paso 4 avisa cuáles se reemplazan.
3. **Rutas:** comparar siempre normalizadas (NFC + casefold, `rb._clave_path`). macOS mezcla NFC/NFD y no distingue mayúsculas. En Windows Rekordbox guarda rutas con `/`.
4. **Nunca borrar archivos del usuario.** Se mueven a carpetas de backup; el backup de la colección aparta en `_quitados`, no borra.
5. **macOS:** sin «Acceso total al disco» falla con PermissionError → el servidor lo traduce a un mensaje con la solución. Las escrituras de historial son *create-only* (archivo nuevo por operación) por eso.
6. **Nada de integraciones con descargadores** (Soulseek, deezload, yt-dlp, etc.). Decisión tomada: la app no descarga música.
7. **Telemetría:** no se envía nada de la colección. Sólo existe el aviso de riesgo (`acepto_riesgo`). No agregar envío de datos sin que Guido lo pida.
8. **Seguridad de la nube:** la app sólo lleva la *anon key*. Todos los permisos están en `supabase.sql` (RLS + triggers): un usuario común no puede publicar, destacar, marcar pagado ni hacerse admin. Cualquier cambio de permisos va en `supabase.sql` y se prueba contra Postgres.
9. **Licencia GPL-3.0-or-later** (por mutagen). La app lleva su código fuente adentro (`codigo-fuente.zip`). Mantener créditos en Acerca de.
10. Errores para el usuario: en castellano, qué pasó y qué hacer. Nunca un traceback crudo en pantalla.
11. **Servidor local:** sólo atiende a la página de la app (`Handler._de_la_app`: Host local, Origin propio y POST en JSON). Toda ruta de archivo que llegue en un pedido se revisa contra las carpetas de la app o la lista de preparados antes de usarla. La interfaz escapa con `esc()` todo lo que no sea texto fijo.

## Cómo probar

- Pruebas: `python -m unittest discover -s tests -v` (crean todo en carpetas temporales con `KRAMER_APP_DIR`). Corren en Mac, Windows y Linux en cada cambio. `tests/base_rb.py` arma una base de Rekordbox de prueba con las tablas reales; `tests/test_defectos.py` reúne las pruebas que salieron de la revisión de noviembre de 2026: las marcadas `expectedFailure` son defectos sin arreglar (al arreglar uno, sacarle la marca).
- App sin tocar datos reales: `KRAMER_APP_DIR=/tmp/x python kramer_app.py` y en Ajustes apuntar a una **copia** de `master.db`.
- La interfaz se probó con Playwright (Chromium) contra el servidor local.
- Colecciones grandes: la tabla de Colección está virtualizada (sólo dibuja lo visible); con 30.000 temas debe seguir fluida.

## Armado y versiones

- Versión: `web/version.txt`. Los scripts y el pipeline la leen de ahí.
- Mac: `armar_app.command` (PyInstaller onedir .app, firma ad-hoc con requisito fijo `identifier "ar.kramerdj.rkbcollectionmanager"` para que macOS conserve los permisos entre versiones). Sólo Apple Silicon.
- Windows: `armar_app_windows.bat` → `armar_app_windows.ps1` (PyInstaller onefile .exe, WebView2). Reintenta copias porque Defender bloquea el .exe recién creado.
- Con `KRAMER_SALIDA` los dos scripts dejan el zip y el registro en esa carpeta y no instalan ni abren la app (así corren en GitHub).
- Publicar: subir `web/version.txt`, y en GitHub **Actions → Publicar versión → Run workflow** con «Publicar» tildado → arma Mac (macos-15) y Windows (windows-2025) y crea la Release `vX.Y` con `RKB-Collection-Manager-Mac.zip` y `RKB-Collection-Manager-Windows.zip` (nombres fijos: los botones del sitio apuntan ahí). Sin tildar, sólo arma (sirve para probar).
- Actualizaciones del código sin reinstalar (desde la 0.9.1): «Publicar versión» también firma un paquete con kramer/ + web/ (`publicar_actualizacion.py armar`) y sube `codigo-X.zip` + `manifiesto.json` a la Release. La app **armada** los busca en `releases/latest/download` (`URL_DEFECTO`/`CLAVE_DEFECTO` en `kramer_arranque.py`); corriendo desde el código fuente está apagado salvo con `KRAMER_ACTUALIZACION_URL` / `KRAMER_ACTUALIZACION_CLAVE`. La clave privada está en el secreto de GitHub `ACTUALIZACION_CLAVE_PRIVADA` y Guido guarda una copia de respaldo; nunca va al repositorio. Si se pierde, las apps instaladas dejan de aceptar actualizaciones. Si un cambio toca algo fuera de kramer/ y web/ (librerías, kramer_arranque.py, kramer_ventana.py), subir `SHELL` en `kramer_arranque.py`: las apps viejas no toman ese paquete y hay que reinstalar (y conviene hacerla obligatoria).
- Versión obligatoria: `control/versiones.json` en `main` (ultima, minima, minima_desde, gracia_dias, mensaje), que la app lee de raw.githubusercontent.com (`nube.CONTROL_URL`). Lo cambian «Publicar versión» (tilde «Obligatoria») y el botón **Actions → Versión obligatoria** (`control/control.py`). Sin internet o si el archivo no se puede leer, **nunca bloquea** (pedido de Guido). La tabla `app_config` de Supabase ya no se usa para esto.

## Estado y pendientes (26 de noviembre de 2026)

- Versión 0.9.1 en prueba piloto con DJs conocidos; se reparte desde https://kramerdj.github.io/ (repo `kramerdj/kramerdj.github.io`, botones a `releases/latest`, la versión se lee sola de GitHub). La 0.9.1 es la primera con actualización automática y control de versión: quien tenga 0.8 o 0.9 tiene que reinstalar una vez. En la 0.9 se quitó la pestaña «Eventos tocados» (el filtro «Tocado» de Colección sigue). Guido usa una Mac con chip Apple (Rekordbox 7) y una PC con Windows 11.
- Windows: la primera compilación en la PC de Guido armó el .exe bien; falló sólo el zip final porque Defender tenía el .exe tomado. Corregido en `armar_app_windows.ps1` (cierra el .exe de prueba, reintenta y arma el zip desde la copia de trabajo).
- Pipeline: confirmar que «Publicar versión» arma bien Mac y Windows (correrlo sin tildar «Publicar») antes de la primera Release.
- El repositorio `kramerdj/rkb` es público: las Releases se bajan sin cuenta.
- **Supabase todavía no creado**: Cartelera y Mis anuncios están apagados hasta cargar URL/CLAVE en `nube.py`. Para activarlo: crear el proyecto (plan gratis), correr `supabase.sql`, cambiar la plantilla del email «Magic Link» para que mande el código (`{{ .Token }}`), entrar una vez desde la app con el email de Guido y marcarlo admin (`update perfiles set admin = true where email = …`). Probar la interfaz sin servidor real con `tests/herramientas/supabase_simulado.py`.
- Spotify: cada usuario crea su propia app de desarrollador (guía dentro de la app). El modo desarrollo exige Premium y admite pocos usuarios por app, por eso no se comparte un Client ID.
- Pendientes pedidos por Guido:
  - Interfaz en **inglés** (selector de idioma). Todo el texto está hoy en castellano dentro de html/js/py.
  - **YouTube Music**: crear playlists (YouTube Data API, OAuth por usuario, ~190 temas/día por cuota) + **exportar CSV** para importar en otras plataformas. Deezer no da API nueva desde 2025.
  - Pago de anuncios con Mercado Pago (siempre del lado del servidor, nunca en la app).
  - Versión para Mac Intel (hoy sólo Apple Silicon).
