"""Servidor Supabase SIMULADO para probar la Cartelera y Mis anuncios sin crear el proyecto real.

Uso:
    python tests/herramientas/supabase_simulado.py 8790
    KRAMER_APP_DIR=/tmp/x KRAMER_NUBE_URL=http://127.0.0.1:8790 KRAMER_NUBE_CLAVE=anon python kramer_app.py

Un segundo argumento opcional es la fila de app_config en JSON, por ejemplo para probar el aviso
o el bloqueo de versión:
    python tests/herramientas/supabase_simulado.py 8790 '{"id":1,"ultima":"0.9","minima":"0.9","minima_desde":"2026-11-01","gracia_dias":7}'

- Login: cualquier email; el código es siempre 123456. Un email que empieza con "guido" entra como administrador.
- Trae anuncios de ejemplo en Buenos Aires, Córdoba, Miami, Auckland y uno para todo el mundo.
- Imita sólo lo que usa kramer/nube.py. Los permisos reales están en supabase.sql (probarlos contra Postgres).
"""
import json, re, sys, uuid, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qsl
hoy = datetime.date.today()
d = lambda n: (hoy + datetime.timedelta(days=n)).isoformat()
OTRO = "cccccccc-0000-0000-0000-000000000003"
ADMIN, USER = "aaaaaaaa-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002"
CONFIG = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {"id": 1, "ultima": "0.8", "minima": None}
PERF = {ADMIN: {"id": ADMIN, "email": "guido@kramerdj.com", "nombre": "KRAMER DJ", "admin": True},
        OTRO: {"id": OTRO, "email": "otro@x.com", "nombre": "Otro", "admin": False},
        USER: {"id": USER, "email": "dj@ejemplo.com", "nombre": "DJ Nico", "admin": False}}
def A(**k):
    base = dict(id=str(uuid.uuid4()), tipo="Evento", hora=None, lugar="", ciudad="", texto="", link="", imagen=None,
                autor=OTRO, autor_nombre="DJ Nico", estado="publicado", destacado=False, motivo=None, alcance="region", region=None, creado=hoy.isoformat())
    base.update(k); return base
ANUNCIOS = [
  A(titulo="Fiesta Retro 80s & 90s", fecha=d(9), hora="23:30", lugar="Niceto Club", ciudad="Palermo", pais="AR", region="Ciudad de Buenos Aires", destacado=True, autor=USER, autor_nombre="DJ Nico",
    texto="Toda la noche clásicos de los 80 y 90 en vinilo y digital. Entradas anticipadas con descuento.", link="https://instagram.com/ejemplo", imagen="http://127.0.0.1:8790/img/1"),
  A(tipo="Curso o taller", titulo="Taller de armado de sets para casamientos", fecha=d(16), hora="19:00", lugar="Online por Zoom", pais="AR", alcance="pais", autor_nombre="Escuela Mix",
    texto="Cómo leer la pista, armar la previa, el vals y el carnaval. 3 clases de 2 horas.", imagen="http://127.0.0.1:8790/img/2"),
  A(tipo="Equipos", titulo="Vendo Pioneer DDJ-FLX6 con case", fecha=d(25), ciudad="Belgrano", pais="AR", region="Ciudad de Buenos Aires", autor_nombre="Martín B.",
    texto="Impecable, poco uso, con caja y case rígido. Acepto ofertas.", imagen="http://127.0.0.1:8790/img/3"),
  A(tipo="Busco DJ", titulo="Busco DJ para casamiento en marzo", fecha=d(40), ciudad="Pilar", pais="AR", region="Buenos Aires (provincia)", autor_nombre="Salón Las Lomas",
    texto="Casamiento de 180 personas, música variada. Mandá tu propuesta por WhatsApp."),
  A(titulo="Noche de cuarteto", fecha=d(6), ciudad="Córdoba", pais="AR", region="Córdoba", autor_nombre="DJ Fer"),
  A(titulo="Miami Beach Sunset Session", fecha=d(12), ciudad="Miami", pais="US", region="Florida", autor_nombre="DJ Ana"),
  A(titulo="Auckland Harbour Party", fecha=d(8), ciudad="Auckland", pais="NZ", region="Auckland", autor_nombre="DJ Kiri"),
  A(tipo="Curso o taller", titulo="Masterclass: armonía y mezcla en clave (online)", fecha=d(20), hora="18:00", alcance="mundo", pais="ES", region="Cataluña", autor_nombre="Mix Academy",
    texto="Clase abierta y gratuita en español sobre Camelot, energía y transiciones.", imagen="http://127.0.0.1:8790/img/4"),
  A(titulo="Fiesta vieja", fecha=d(-3), pais="AR", region="Ciudad de Buenos Aires"),
  A(titulo="After Office Electrónico", fecha=d(14), hora="19:00", lugar="Terraza Madero", ciudad="Puerto Madero", pais="AR", region="Ciudad de Buenos Aires", estado="pendiente", autor=USER, autor_nombre="DJ Nico",
    texto="Primer jueves de cada mes, house y nu disco.", link="https://instagram.com/afteroffice"),
  A(titulo="Mi fiesta de egresados", fecha=d(30), estado="rechazado", motivo="Falta el lugar y la fecha exacta.", autor=USER, pais="AR", region="Ciudad de Buenos Aires"),
]
IMGS = {}
TOK = {"tok-admin": ADMIN, "tok-user": USER}
def match(a, k, v):
    op, _, val = v.partition(".")
    x = a.get(k)
    if op == "eq": return str(x).lower() == val.lower()
    if op == "gte": return str(x) >= val
    return True
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, o, c=200):
        b = json.dumps(o).encode(); self.send_response(c); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def uid(self): return TOK.get(self.headers.get("Authorization","").split()[-1])
    def body(self):
        n=int(self.headers.get("Content-Length") or 0); return self.rfile.read(n)
    def filtrar(self, rows, q):
        for k, v in q:
            if k in ("select","order","limit","on_conflict"): continue
            if k == "or":
                conds = [c.split(".",2) for c in v.strip("()").split(",")]
                rows = [r for r in rows if any(str(r.get(c[0])).lower()==c[2].lower() for c in conds)]
            else: rows = [r for r in rows if match(r, k, v)]
        return rows
    def do_GET(self):
        u = urlparse(self.path); q = parse_qsl(u.query)
        if u.path.startswith("/img/") or u.path.startswith("/storage/v1/object/public/"):
            n = u.path.split("/")[-1]
            if n in IMGS: data = IMGS[n]
            else:
                import io; from PIL import Image, ImageDraw
                cols = {"1":(140,40,120),"2":(30,90,140),"3":(40,40,40),"4":(160,90,20)}
                im = Image.new("RGB",(800,500),cols.get(n,(80,80,80))); dr = ImageDraw.Draw(im)
                for i in range(0,800,40): dr.line([(i,0),(i+300,500)], fill=tuple(min(255,c+40) for c in cols.get(n,(80,80,80))), width=12)
                bio = io.BytesIO(); im.save(bio,"JPEG"); data = bio.getvalue()
            self.send_response(200); self.send_header("Content-Type","image/jpeg"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        if u.path == "/rest/v1/app_config": return self._j([CONFIG])
        if u.path == "/rest/v1/perfiles":
            return self._j([p for p in PERF.values() if self.uid() and match(p,"id",dict(q).get("id","eq.x"))])
        if u.path == "/rest/v1/anuncios":
            me = self.uid(); adm = me and PERF[me]["admin"]
            rows = [a for a in ANUNCIOS if a["estado"]=="publicado" or a["autor"]==me or adm]
            rows = self.filtrar(rows, q)
            if "perfiles(email)" in dict(q).get("select",""):
                rows = [dict(r, perfiles={"email": PERF[r["autor"]]["email"]}) for r in rows]
            rows = sorted(rows, key=lambda r: (not r["destacado"], r["fecha"]))
            return self._j(rows)
        self._j({"message":"no"},404)
    def do_POST(self):
        u = urlparse(self.path); b = self.body()
        if u.path == "/auth/v1/otp": return self._j({})
        if u.path == "/auth/v1/verify":
            j = json.loads(b)
            if j["token"] != "123456": return self._j({"msg":"Token has expired or is invalid"},403)
            t = "tok-admin" if j["email"].startswith("guido") else "tok-user"
            return self._j({"access_token":t,"refresh_token":"r-"+t,"expires_in":3600,"user":{"id":TOK[t],"email":j["email"]}})
        if u.path == "/auth/v1/token":
            t = json.loads(b)["refresh_token"][2:]; return self._j({"access_token":t,"refresh_token":"r-"+t,"expires_in":3600,"user":{"id":TOK[t],"email":PERF[TOK[t]]["email"]}})
        if u.path == "/auth/v1/logout": self.send_response(204); self.end_headers(); return
        if u.path.startswith("/storage/v1/object/flyers/"):
            IMGS[u.path.split("/")[-1]] = b; return self._j({"Key":u.path})
        if u.path == "/rest/v1/perfiles":
            j = json.loads(b); PERF[j["id"]]["nombre"] = j["nombre"]; self.send_response(201); self.end_headers(); return
        if u.path == "/rest/v1/anuncios":
            j = json.loads(b); a = A(**j); a.update(estado="pendiente", destacado=False, autor=self.uid()); ANUNCIOS.append(a); return self._j([a],201)
        self._j({"message":"no"},404)
    def do_PATCH(self):
        u = urlparse(self.path); q = parse_qsl(u.query); j = json.loads(self.body()); me = self.uid()
        for a in self.filtrar(ANUNCIOS, q):
            if PERF[me]["admin"]: a.update(j)
            elif a["autor"] == me: a.update(j); a.update(estado="pendiente", motivo=None)
        return self._j([a for a in self.filtrar(ANUNCIOS,q)])
    def do_DELETE(self):
        u = urlparse(self.path); q = parse_qsl(u.query)
        for a in self.filtrar(ANUNCIOS, q): ANUNCIOS.remove(a)
        self.send_response(204); self.end_headers()
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
