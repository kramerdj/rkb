// ---------------------------------------------------------------- GUÍA DE BIENVENIDA
// Se abre sola una vez (config guia_vista) y se puede volver a ver desde «Acerca de».
// Capturas en web/guia/<paso>-<claro|oscuro>.jpg; ZONA = recuadro a resaltar, en % de la captura (x, y, ancho, alto).
const GUIA = [
  { id: 'backup', vista: 'respaldos', zona: [18.68, 57.04, 12.61, 6], titulo: 'Primero, un backup completo',
    texto: 'Antes de tocar nada, guardá una copia de tu base de Rekordbox y de tu música. Mejor en un disco externo: si algo sale mal, desde acá volvés todo atrás.',
    puntos: ['La base va en un zip con fecha; la música, como copia espejo (después sólo copia lo nuevo).', 'Para la base, Rekordbox tiene que estar cerrado.'],
    accion: 'Ir a hacer el backup' },
  { id: 'coleccion', vista: 'coleccion', zona: [31.4, 1.69, 34.52, 6], titulo: 'Poné en orden tu colección',
    texto: 'En Colección están las herramientas para dejar prolijo lo que ya tenés:',
    puntos: ['Buscar duplicados: elegís qué copia queda y las playlists pasan a esa.', 'Ordenar nombres: «Artista - Título (feat.) (Versión)» en todos los archivos.', 'Actualizar metadata: género, año, álbum, país e idioma desde internet; revisás antes de aceptar.'],
    pie: 'Los cambios quedan pendientes hasta que tocás Sincronizar.' },
  { id: 'mytags', vista: 'mytags', zona: [17.36, 9.86, 23.31, 6], titulo: 'My Tags que se completan solos',
    texto: 'La app arma las 4 categorías de My Tags de Rekordbox con la metadata de cada tema: origen e idioma, género, década y Momento (que ponés vos con las teclas 1 a 4).',
    puntos: ['Simular te muestra qué cambiaría.', 'Actualizar base de Rekordbox lo guarda (con backup y se puede deshacer).'] },
  { id: 'lista', vista: 'lista', zona: [18.68, 14.62, 20.69, 71.27], titulo: 'Lista de temas del evento',
    texto: 'Pegá la lista que te pasaron o el link de una playlist de Spotify, YouTube Music o Deezer. La app la cruza con tu colección y te dice qué ya tenés y qué falta bajar.',
    puntos: ['Te arma la lista depurada con links de búsqueda para lo que falta.', 'Si querés, crea el evento como playlist en Rekordbox.'] },
  { id: 'descargas', vista: 'descargas', zona: [87.58, 4.31, 11.04, 6], titulo: 'Descargas',
    texto: 'Cuando bajás lo que faltaba, la app completa metadata y carátulas, mide la calidad real del audio y te avisa si ya lo tenías.',
    puntos: ['Elegís qué datos actualizar y de qué fuentes.', 'Lo de mala calidad o repetido va a una carpeta aparte, no se borra.'] },
  { id: 'incorporar', vista: 'incorporar', zona: [44.6, 49.85, 12.07, 6], titulo: 'Incorporar a la colección',
    texto: 'Los temas preparados pasan a tu carpeta de música y a Rekordbox, con su metadata y sus My Tags, y si querés a la playlist del evento.',
    puntos: ['Después abrí Rekordbox y analizalos (BPM y forma de onda).'] },
];
const GU = { i: 0, abierta: false };

function abrirGuia(desde = 0) {
  GU.i = desde; GU.abierta = true;
  let g = $('#guia');
  if (!g) {
    g = document.createElement('div');
    g.id = 'guia'; g.className = 'guia';
    g.setAttribute('role', 'dialog'); g.setAttribute('aria-modal', 'true'); g.setAttribute('aria-labelledby', 'guiaTit');
    g.innerHTML = `<div class="guia-caja">
      <div class="guia-pasos" aria-hidden="true">${GUIA.map(() => '<i></i>').join('')}</div>
      <div class="guia-cuerpo">
        <figure class="guia-foto"><div class="guia-lienzo"><img alt=""><span class="guia-zona" aria-hidden="true"></span></div></figure>
        <div class="guia-texto" aria-live="polite"></div>
      </div>
      <div class="guia-acc">
        <button type="button" class="guia-saltar" data-g="saltar">Saltar la guía</button>
        <span class="guia-cuenta"></span>
        <button type="button" class="btn" data-g="atras">Anterior</button>
        <button type="button" class="btn prim" data-g="sigue">Siguiente</button>
      </div></div>`;
    document.body.appendChild(g);
    g.addEventListener('click', (e) => {
      const b = e.target.closest('[data-g]'); if (!b) return;
      const a = b.dataset.g;
      if (a === 'saltar') cerrarGuia();
      else if (a === 'atras') pasoGuia(GU.i - 1);
      else if (a === 'sigue') { if (GU.i < GUIA.length - 1) pasoGuia(GU.i + 1); else cerrarGuia(); }
      else if (a === 'ir') { const v = GUIA[GU.i].vista; cerrarGuia(); irA(v); }
    });
  }
  g.hidden = false;
  pasoGuia(GU.i, true);
}

function pasoGuia(i, primero) {
  if (i < 0 || i >= GUIA.length) return;
  const atras = i < GU.i;
  GU.i = i;
  const p = GUIA[i], g = $('#guia');
  const tema = document.documentElement.getAttribute('data-tema') === 'oscuro' ? 'oscuro' : 'claro';
  g.querySelectorAll('.guia-pasos i').forEach((el, k) => { el.className = k < i ? 'hecho' : k === i ? 'act' : ''; });
  const foto = g.querySelector('.guia-foto'), img = foto.querySelector('img'), zona = foto.querySelector('.guia-zona');
  const texto = g.querySelector('.guia-texto');
  // reinicia las animaciones de entrada
  for (const el of [foto, texto]) { el.classList.remove('entra', 'desde-atras'); void el.offsetWidth; }
  img.src = `guia/${p.id}-${tema}.jpg`;
  img.alt = `Captura de la sección ${p.titulo}`;
  const [x, y, w, h] = p.zona;
  Object.assign(zona.style, { left: x + '%', top: y + '%', width: w + '%', height: h + '%' });
  const lienzo = foto.querySelector('.guia-lienzo');
  lienzo.style.transformOrigin = `${x + w / 2}% ${y + h / 2}%`;
  texto.innerHTML = `<h2 id="guiaTit">${esc(p.titulo)}</h2><p>${esc(p.texto)}</p>
    ${p.puntos ? `<ul>${p.puntos.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>` : ''}
    ${p.pie ? `<p class="nota">${esc(p.pie)}</p>` : ''}
    ${p.accion ? `<button type="button" class="btn guia-ir" data-g="ir">${esc(p.accion)}</button>` : ''}`;
  for (const el of [foto, texto]) { el.classList.add('entra'); if (atras) el.classList.add('desde-atras'); }
  g.querySelector('.guia-cuenta').textContent = `${i + 1} de ${GUIA.length}`;
  g.querySelector('[data-g=atras]').hidden = i === 0;
  const sigue = g.querySelector('[data-g=sigue]');
  sigue.textContent = i === GUIA.length - 1 ? 'Empezar' : 'Siguiente';
  if (primero) sigue.focus();
}

function cerrarGuia() {
  const g = $('#guia'); if (!g) return;
  g.hidden = true; GU.abierta = false;
  if (!(E.config && E.config.guia_vista)) {
    api('/api/config', { guia_vista: true }).then((d) => { E.config = d.config; }).catch(() => {});
  }
}

document.addEventListener('keydown', (e) => {
  if (!GU.abierta) return;
  e.stopPropagation();                 // la guía tapa todo: los atajos de Colección no corren detrás
  if (e.key === 'Escape') { e.preventDefault(); cerrarGuia(); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); pasoGuia(GU.i + 1); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); pasoGuia(GU.i - 1); }
}, true);

// las capturas se piden antes, así el paso siguiente aparece sin espera
function precargarGuia() {
  const tema = document.documentElement.getAttribute('data-tema') === 'oscuro' ? 'oscuro' : 'claro';
  GUIA.forEach((p) => { const im = new Image(); im.src = `guia/${p.id}-${tema}.jpg`; });
}
