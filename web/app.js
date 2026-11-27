/* Kramer DJ · interfaz */
'use strict';
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const E = {
  vista: 'coleccion', config: null, temas: [], porId: {}, playlists: {}, momentos: [],
  pend: { momento: {}, meta: {} }, rbAbierto: false,
  filtros: {}, buscar: '', orden: { k: 'artista', dir: 1 },
  lista: [], sel: null, metaTema: null, multi: new Set(), groupings: new Set(),
};

// ---------------------------------------------------------------- API
async function api(ruta, cuerpo) {
  const r = await fetch(ruta, cuerpo === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo),
  });
  const d = await r.json().catch(() => ({ error: 'Respuesta inválida del servidor' }));
  if (!r.ok || d.error) throw new Error(d.error || ('Error ' + r.status));
  return d;
}
let tAviso;
function aviso(msg, error) {
  const a = $('#aviso');
  a.textContent = msg; a.className = 'aviso' + (error ? ' error' : ''); a.hidden = false;
  clearTimeout(tAviso); tAviso = setTimeout(() => { a.hidden = true; }, error ? 9000 : 4500);
}
function modal(titulo, html, botones) {
  $('#modalTit').textContent = titulo;
  $('#modalCuerpo').innerHTML = html;
  const acc = $('#modalAcc'); acc.innerHTML = '';
  for (const b of botones) {
    const el = document.createElement('button');
    el.type = 'button'; el.className = 'btn' + (b.prim ? ' prim' : '') + (b.peligro ? ' peligro' : ''); el.textContent = b.txt;
    el.onclick = async () => { if (b.fn) { el.disabled = true; try { await b.fn(); } finally { el.disabled = false; } } else cerrarModal(); };
    acc.appendChild(el);
  }
  $('#modal').hidden = false;
}
const cerrarModal = () => { $('#modal').hidden = true; $('#modal .caja').classList.remove('ancha', 'medio'); };

// ---------------------------------------------------------------- MENÚ
const VISTAS = [
  ['lista', 'Lista de temas'], ['descargas', 'Descargas'], ['incorporar', 'Incorporar'],
  ['mytags', 'My Tags'], ['coleccion', 'Colección'], ['-'], ['cartelera', 'Cartelera'], ['misanuncios', 'Mis anuncios'], ['respaldos', 'Backup y restauración'], ['ajustes', 'Ajustes e historial'],
];
function pintarMenu() {
  const n = nPend();
  const nube = typeof CT !== 'undefined' && CT.activo;
  const badge = (id) => (id === 'coleccion' && n ? n : id === 'cartelera' && nube && CT.nuevos ? CT.nuevos : 0);
  $('#menu').innerHTML = VISTAS.filter(([id]) => nube || (id !== 'cartelera' && id !== 'misanuncios')).map(([id, txt]) => id === '-' ? '<div class="sepm"></div>' :
    `<button type="button" data-v="${id}" class="${E.vista === id ? 'act' : ''}"><span>${txt}</span>${badge(id) ? `<span class="badge">${badge(id)}</span>` : ''}</button>`).join('');
}
$('#menu').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-v]'); if (b) irA(b.dataset.v);
});
function irA(v) {
  E.vista = v;
  document.querySelectorAll('.vista').forEach((s) => s.classList.toggle('act', s.dataset.vista === v));
  pintarMenu();
  if (v === 'ajustes') { pintarAjustes(); pintarBackups(); }
  if (v === 'acerca') api('/api/estado').then((d) => { $('#acVersion').textContent = 'Versión ' + d.version; });
  if (v === 'mytags') pintarMyTags();
  if (v === 'respaldos' && typeof pintarRespaldo === 'function') pintarRespaldo();
  if (v === 'cartelera') pintarCartelera();
  if (v === 'misanuncios') pintarMisAnuncios();
  if (typeof alEntrar === 'function') alEntrar(v);
}

// ---------------------------------------------------------------- ESTADO REKORDBOX
async function estado() {
  try {
    const d = await api('/api/estado');
    E.rbAbierto = d.rekordboxAbierto; E.config = d.config;
    $('#permiso').hidden = d.permisoArchivos !== false;
    E.sistema = d.sistema;
    $('#btnFinder').textContent = d.sistema === 'windows' ? 'Mostrar en el Explorador' : 'Mostrar en Finder';
    $('#kbdCmd').textContent = d.sistema === 'windows' ? 'Ctrl' : '⌘';
    $('#kbdSupr').textContent = d.sistema === 'windows' ? 'Supr' : 'fn ⌫';
    pintarPrimeraVez(d);
    if (document.activeElement !== $('#pSeg') && document.activeElement !== $('#pInicio')) pintarInicio();
    $('#version').textContent = 'Versión ' + d.version;
    const el = $('#estadoRb');
    el.className = 'estado-rb ' + (d.rekordboxAbierto ? 'abierto' : 'cerrado');
    el.lastElementChild.textContent = d.rekordboxAbierto ? 'Rekordbox abierto · cambios en espera' : 'Rekordbox cerrado · se puede guardar';
  } catch (e) { /* el servidor puede estar cerrándose */ }
}

// Primer uso: falta Rekordbox o la carpeta de la colección (con una sugerencia sacada de Rekordbox)
let sugerida = null;
async function pintarPrimeraVez(d) {
  const falta = d.rekordboxExiste === false || d.coleccionExiste === false;
  $('#primeraVez').hidden = !falta;
  if (!falta) return;
  if (d.rekordboxExiste === false) {
    $('#primeraVezTit').textContent = 'No encuentro Rekordbox.';
    $('#primeraVezTxt').textContent = 'No está la base de Rekordbox en esta computadora. ¿Está instalado Rekordbox 6 o 7 y lo abriste al menos una vez? Si la base está en otro lugar, elegila en Ajustes → Base de Rekordbox.';
    $('#primeraVezAcc').innerHTML = '<button type="button" class="btn prim chico" data-pv="ajustes">Ir a Ajustes</button>';
    return;
  }
  if (sugerida === null) { try { sugerida = (await api('/api/carpeta_sugerida')).ruta; } catch (_) { sugerida = ''; } }
  $('#primeraVezTit').textContent = 'Falta elegir tu carpeta de música.';
  $('#primeraVezTxt').innerHTML = sugerida
    ? `Según Rekordbox, tus temas están en <b>${esc(sugerida)}</b>. La app la usa para incorporar temas nuevos, ordenar nombres y hacer backups.`
    : 'Elegí la carpeta donde tenés los temas que usa Rekordbox. La app la usa para incorporar temas nuevos, ordenar nombres y hacer backups.';
  $('#primeraVezAcc').innerHTML = (sugerida ? '<button type="button" class="btn chico" data-pv="elegir">Elegir otra…</button><button type="button" class="btn prim chico" data-pv="usar">Usar esa carpeta</button>'
    : '<button type="button" class="btn prim chico" data-pv="elegir">Elegir carpeta…</button>');
}
$('#primeraVezAcc').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-pv]'); if (!b) return;
  if (b.dataset.pv === 'ajustes') { irA('ajustes'); return; }
  let ruta = sugerida;
  if (b.dataset.pv === 'elegir') ruta = (await api('/api/elegir_carpeta', { titulo: 'Elegí la carpeta de tu colección' })).ruta;
  if (!ruta) return;
  const r = await api('/api/config', { coleccion: ruta }); E.config = r.config; aviso('Carpeta de la colección guardada.'); estado();
});

// ---------------------------------------------------------------- COLECCIÓN: datos
const nPend = () => Object.keys(E.pend.momento).length + Object.keys(E.pend.meta).length + Object.keys(E.pend.tags || {}).length;
const val = (t, k) => (E.pend.meta[t.id] && E.pend.meta[t.id][k] !== undefined ? E.pend.meta[t.id][k] : t[k]);
const momentoDe = (t) => (t.id in E.pend.momento ? E.pend.momento[t.id] : t.momento);

async function cargarColeccion() {
  $('#filas').innerHTML = '<div class="fila fila-msg"><span></span><span>Cargando la colección…</span></div>';
  try {
    const d = await api('/api/coleccion');
    E.temas = d.temas; E.playlists = d.playlists; E.momentos = d.momentos; E.pend = d.pendientes;
    E.pend.tags = E.pend.tags || {}; E.categorias = d.categorias || []; armarFiltros();
    E.porId = Object.fromEntries(E.temas.map((t) => [t.id, t]));
    E.multi.clear(); pintarListas(); pintarFiltros(); aplicarFiltros(); pintarMomentos(); pintarSync(); pintarMenu(); pintarPanel();
    if (!E.sel && E.lista.length) seleccionar(E.lista[0].id, false);
  } catch (e) {
    $('#filas').innerHTML = `<div class="fila fila-msg fila-error"><span></span><span>${esc(e.message)}</span></div>`;
  }
}

const FILTROS_BASE = [
  ['genero', 'Género', (t) => val(t, 'genero') || '(sin género)'],
  ['decada', 'Década', (t) => t.decada || '(sin año)'],
  ['momento', 'Momento', (t) => momentoDe(t) || 'Sin momento'],
  ['playlist', 'Playlist', (t) => t.playlists.map((p) => E.playlists[p])],
  ['tocado', 'Tocado', (t) => (!t.tocado ? 'Nunca' : t.tocado < 5 ? '1 a 4 veces' : t.tocado < 15 ? '5 a 14 veces' : '15 o más')],
  ['prep', 'Preparación', (t) => [!t.cues && 'Sin cue points', !t.analizado && 'Sin analizar', !momentoDe(t) && 'Sin Momento',
    !t.cues && !momentoDe(t) && 'Sin cues ni Momento'].filter(Boolean)],
];
let FILTROS = FILTROS_BASE;
function armarFiltros() {
  // un filtro por cada categoría de My Tags (salvo Momento y las que repiten género/década)
  const extra = (E.categorias || []).filter((c) => c.id !== '4' && c.fuente !== 'genero' && c.fuente !== 'decada')
    .map((c) => ['cat' + c.id, c.nombre, (t) => ((t.cats && t.cats[c.id] && t.cats[c.id].length) ? tagsDe(t, c.id) : ['(sin ' + c.nombre.toLowerCase() + ')'])]);
  FILTROS = [FILTROS_BASE[0], FILTROS_BASE[1], ...extra, ...FILTROS_BASE.slice(2)];
  const m = (E.categorias || []).find((c) => c.id === '4');
  if (m) FILTROS = FILTROS.map((f) => (f[0] === 'momento' ? ['momento', m.nombre, f[2]] : f));
}
const tagsDe = (t, cat) => (E.pend.tags && E.pend.tags[t.id] && E.pend.tags[t.id][cat]) || (t.cats && t.cats[cat]) || [];
const ORDEN_FIJO = { tocado: ['Nunca', '1 a 4 veces', '5 a 14 veces', '15 o más'],
  prep: ['Sin cue points', 'Sin analizar', 'Sin Momento', 'Sin cues ni Momento'] };
function opcionesDe(f) {
  const cuenta = {};
  for (const t of E.temas) for (const v of [].concat(f[2](t))) if (v) cuenta[v] = (cuenta[v] || 0) + 1;
  let vals = Object.keys(cuenta);
  if (f[0] === 'decada') vals.sort((a, b) => (parseInt(a) < 100 ? parseInt(a) + 1900 : parseInt(a) || 9999) - (parseInt(b) < 100 ? parseInt(b) + 1900 : parseInt(b) || 9999));
  else if (f[0] === 'momento') vals = ['Sin momento', ...E.momentos].filter((v) => cuenta[v] || v === 'Sin momento');
  else if (ORDEN_FIJO[f[0]]) vals = ORDEN_FIJO[f[0]].filter((v) => cuenta[v]);
  else vals.sort((a, b) => (f[0] === 'playlist' ? a.localeCompare(b, 'es') : cuenta[b] - cuenta[a]));
  return vals.map((v) => [v, cuenta[v] || 0]);
}
function pintarFiltros() {
  const cont = $('#filtros');
  cont.querySelectorAll('label, .cuenta, .limpiar').forEach((n) => n.remove());
  for (const f of FILTROS) {
    const actual = E.filtros[f[0]] || '';
    const lab = document.createElement('label');
    lab.className = actual ? 'activo' : '';
    lab.innerHTML = `${f[1]} <select data-f="${f[0]}"><option value="">Todos</option>${opcionesDe(f).map(([v, n]) =>
      `<option value="${esc(v)}" ${v === actual ? 'selected' : ''}>${esc(v)} (${n})</option>`).join('')}</select>`;
    cont.appendChild(lab);
  }
  const c = document.createElement('span'); c.className = 'cuenta'; c.id = 'cuenta'; cont.appendChild(c);
  const l = document.createElement('button'); l.type = 'button'; l.className = 'limpiar'; l.textContent = 'Limpiar filtros';
  l.onclick = () => { E.filtros = {}; E.buscar = ''; $('#buscar').value = ''; pintarFiltros(); aplicarFiltros(); };
  cont.appendChild(l);
}
$('#filtros').addEventListener('change', (e) => {
  const s = e.target.closest('select[data-f]'); if (!s) return;
  E.filtros[s.dataset.f] = s.value; s.parentElement.className = s.value ? 'activo' : '';
  aplicarFiltros(); s.blur();
});
$('#buscar').addEventListener('input', (e) => { E.buscar = e.target.value; aplicarFiltros(); });

const sinAcentos = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const COLADOR = new Intl.Collator('es', { sensitivity: 'base' });
function aplicarFiltros() {
  const q = sinAcentos(E.buscar).trim();
  E.lista = E.temas.filter((t) => {
    for (const f of FILTROS) {
      const v = E.filtros[f[0]];
      if (v && ![].concat(f[2](t)).includes(v)) return false;
    }
    if (q && !sinAcentos(`${val(t, 'titulo')} ${val(t, 'artista')} ${val(t, 'album')} ${(t.ruta || '').split(/[\\/]/).pop()}`).includes(q)) return false;
    return true;
  });
  const { k, dir } = E.orden;
  E.lista.sort((a, b) => {
    const num = k === 'bpm' || k === 'tocado';
    const x = num ? a[k] : val(a, k), y = num ? b[k] : val(b, k);
    const r = num ? x - y : COLADOR.compare(String(x || '￿'), String(y || '￿'));
    return r * dir || COLADOR.compare(String(val(a, 'titulo')), String(val(b, 'titulo')));
  });
  $('#cuenta') && ($('#cuenta').textContent = `${E.lista.length} de ${E.temas.length} temas`);
  $('#filas').scrollTop = 0;
  pintarTabla();
}

// ---------------------------------------------------------------- COLECCIÓN: tabla
function pintarEncabezado() {
  const col = (k, txt) => `<button type="button" data-k="${k}" class="${E.orden.k === k ? 'act' : ''}">${txt} ${E.orden.k === k ? (E.orden.dir > 0 ? '↑' : '↓') : ''}</button>`;
  $('#encabezado').innerHTML = `<span></span>${col('titulo', 'Tema')}${col('artista', 'Artista')}<span>Género</span>${col('bpm', 'BPM')}<span>Tono</span><span>Década</span><span>Origen</span>${col('tocado', 'Tocado')}<span>Momento</span>`;
}
$('#encabezado').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-k]'); if (!b) return;
  const k = b.dataset.k;
  E.orden = { k, dir: E.orden.k === k ? -E.orden.dir : 1 };
  aplicarFiltros();
  if (E.sel) verFila(E.sel, 'center');
});
function htmlFila(t) {
  const mom = momentoDe(t), cambioMom = t.id in E.pend.momento, cambioMeta = !!E.pend.meta[t.id];
  const ico = E.sel === t.id ? (audio.paused ? '❚❚' : '▶') : '';
  return `<div class="fila${E.sel === t.id ? ' sel' : ''}${E.multi.has(t.id) ? ' multi' : ''}${t.existe ? '' : ' falta'}" data-id="${t.id}" title="${t.existe ? '' : 'No encuentro el archivo'}">
    <span class="ico">${ico}</span>
    <span class="t">${cambioMeta ? '<span class="pend">• </span>' : ''}${esc(val(t, 'titulo'))}</span>
    <span class="a">${esc(val(t, 'artista'))}</span>
    <span class="g">${esc(val(t, 'genero'))}</span>
    <span class="bpm">${t.bpm ? Math.round(t.bpm) : ''}</span>
    <span class="tono">${esc(t.tono)}</span>
    <span>${esc(t.decada)}</span>
    <span class="o">${esc(t.origen.join(' · '))}</span>
    <span class="toc${t.tocado ? '' : ' cero'}" title="${t.ultimaVez ? 'Última vez: ' + t.ultimaVez : 'Nunca tocado'}">${t.tocado || '—'}</span>
    <span class="mom${mom ? '' : ' vacio'}${cambioMom ? ' cambio' : ''}">${esc(mom || '—')}</span></div>`;
}
// La tabla dibuja sólo las filas que se ven (con 30.000 temas sigue siendo instantánea).
const VT = { alto: 35, desde: -1, hasta: -1 };
function pintarTabla() {
  pintarEncabezado();
  const cont = $('#filas');
  if (!E.lista.length) { cont.innerHTML = '<div class="fila fila-msg"><span></span><span>Ningún tema con estos filtros.</span></div>'; VT.desde = -1; return; }
  if (!$('#vEsp')) cont.innerHTML = '<div id="vEsp"><div id="vVis"></div></div>';
  $('#vEsp').style.height = (E.lista.length * VT.alto) + 'px';
  VT.desde = -1; pintarVentana();
}
function pintarVentana() {
  const cont = $('#filas'); const vis = $('#vVis'); if (!vis) return;
  const desde = Math.max(0, Math.floor(cont.scrollTop / VT.alto) - 15);
  const hasta = Math.min(E.lista.length, desde + Math.ceil((cont.clientHeight || 800) / VT.alto) + 30);
  if (desde === VT.desde && hasta === VT.hasta) return;
  VT.desde = desde; VT.hasta = hasta;
  vis.style.transform = `translateY(${desde * VT.alto}px)`;
  vis.innerHTML = E.lista.slice(desde, hasta).map(htmlFila).join('');
  const f = vis.firstElementChild;
  if (f && f.offsetHeight && Math.abs(f.offsetHeight - VT.alto) > 0.5) { VT.alto = f.offsetHeight; pintarTabla(); }
}
let vtPend = false;
$('#filas').addEventListener('scroll', () => { if (!vtPend) { vtPend = true; requestAnimationFrame(() => { vtPend = false; pintarVentana(); }); } });
window.addEventListener('resize', () => { VT.desde = -1; pintarVentana(); });
function verFila(id, bloque) {           // lleva la tabla hasta el tema (aunque no esté dibujado)
  const i = E.lista.findIndex((t) => t.id === id); if (i < 0) return;
  const cont = $('#filas'); const y = i * VT.alto;
  if (bloque === 'center') cont.scrollTop = y - cont.clientHeight / 2 + VT.alto / 2;
  else if (y < cont.scrollTop) cont.scrollTop = y;
  else if (y + VT.alto > cont.scrollTop + cont.clientHeight) cont.scrollTop = y + VT.alto - cont.clientHeight;
  pintarVentana();
}
const filaDe = (id) => $('#filas').querySelector(`.fila[data-id="${CSS.escape(id)}"]`);
function repintarFila(id) {
  const f = filaDe(id); const t = E.porId[id];
  if (f && t) { const tmp = document.createElement('div'); tmp.innerHTML = htmlFila(t); f.replaceWith(tmp.firstElementChild); }
}
$('#filas').addEventListener('click', (e) => {
  const f = e.target.closest('.fila[data-id]'); if (!f) return;
  const id = f.dataset.id;
  if (e.metaKey || e.ctrlKey) {
    if (!E.multi.size && E.sel) E.multi.add(E.sel);
    if (E.multi.has(id)) E.multi.delete(id); else E.multi.add(id);
    [...E.multi, id].forEach(repintarFila); pintarPanel();
  } else if (e.shiftKey && E.sel) {
    const ids = E.lista.map((t) => t.id);
    const a = ids.indexOf(E.sel), b = ids.indexOf(id);
    const antes = [...E.multi];
    E.multi = new Set(ids.slice(Math.min(a, b), Math.max(a, b) + 1));
    if (E.multi.size > 300) pintarTabla(); else [...antes, ...E.multi].forEach(repintarFila);
    pintarPanel();
  } else {
    if (E.multi.size) limpiarMulti();
    seleccionar(id, true);
  }
});
function limpiarMulti() {
  const antes = [...E.multi]; E.multi.clear();
  if (antes.length > 300) pintarTabla(); else antes.forEach(repintarFila);
  pintarPanel();
}

// ---------------------------------------------------------------- SELECCIÓN y REPRODUCTOR
const audio = $('#audio');
function seleccionar(id, reproducir) {
  const antes = E.sel; E.sel = id;
  if (antes) repintarFila(antes);
  repintarFila(id);
  verFila(id, 'nearest');
  const t = E.porId[id];
  $('#pTitulo').textContent = val(t, 'titulo') || '(sin título)';
  $('#pSub').textContent = [val(t, 'artista'), t.bpm ? Math.round(t.bpm) + ' BPM' : '', val(t, 'genero')].filter(Boolean).join(' · ');
  pintarMomentos();
  cargarMeta(id);
  pintarSiguen();
  pintarTagsMan();
  pintarBtnEliminar();
  if (reproducir && t.existe) tocar(t); else { audio.pause(); audio.removeAttribute('src'); audio.load(); pintarTiempo(); }
}
function tocar(t) {
  audio.src = '/audio?id=' + encodeURIComponent(t.id);
  const modo = (E.config && E.config.inicio) || '30';
  const seg = Number((E.config && E.config.inicio_seg) || 0);
  audio.onloadedmetadata = () => {
    let s = 0;
    if (modo === 'cue' && t.cue != null) s = t.cue / 1000;
    else if (modo === 'seg') s = Math.min(seg, Math.max(0, (audio.duration || t.duracion || 0) - 5));
    else if (modo !== 'inicio') s = (audio.duration || t.duracion || 0) * 0.3;
    try { audio.currentTime = s; } catch (_) { /* nada */ }
  };
  audio.play().catch(() => {});
}
function moverSel(delta) {
  if (!E.lista.length) return;
  let i = E.lista.findIndex((t) => t.id === E.sel);
  i = i < 0 ? 0 : Math.max(0, Math.min(E.lista.length - 1, i + delta));
  seleccionar(E.lista[i].id, true);
}
const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
function pintarTiempo() {
  const d = audio.duration || (E.porId[E.sel]?.duracion || 0);
  $('#pTiempo').textContent = `${fmt(audio.currentTime)} / ${fmt(d)}`;
  $('#barraIn').style.width = d ? (100 * audio.currentTime / d) + '%' : '0';
}
audio.addEventListener('timeupdate', pintarTiempo);
audio.addEventListener('play', () => { $('#btnPlay').textContent = '❚❚'; if (E.sel) repintarFila(E.sel); });
audio.addEventListener('pause', () => { $('#btnPlay').textContent = '▶'; if (E.sel) repintarFila(E.sel); });
audio.addEventListener('error', () => { if (audio.getAttribute('src')) aviso('No se puede reproducir este archivo en la app.', true); });
const playPausa = () => {
  if (!E.sel) return;
  if (!audio.getAttribute('src')) tocar(E.porId[E.sel]); else if (audio.paused) audio.play(); else audio.pause();
};
$('#btnPlay').onclick = playPausa;
$('#barra').addEventListener('click', (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  if (audio.duration) audio.currentTime = audio.duration * (e.clientX - r.left) / r.width;
});

// ---------------------------------------------------------------- MOMENTO
function pintarMomentos() {
  const teclas = (E.config && E.config.teclas) || [];
  const t = E.sel && E.porId[E.sel]; const actual = t ? momentoDe(t) : '';
  $('#momBtns').innerHTML = E.momentos.map((m) => {
    const k = teclas.indexOf(m);
    return `<button type="button" data-m="${esc(m)}" class="${m === actual ? 'sel' : ''}"><kbd class="${k < 0 ? 'no' : ''}">${k < 0 ? '·' : k + 1}</kbd>${esc(m)}</button>`;
  }).join('');
}
$('#momBtns').addEventListener('click', (e) => { const b = e.target.closest('button[data-m]'); if (b) ponerMomento(b.dataset.m); });
async function ponerMomento(m) {
  if (E.multi.size > 1) {
    const items = [...E.multi].map((id) => {
      const t = E.porId[id];
      if (m === t.momento) { delete E.pend.momento[id]; return { id, quitarMomento: true }; }
      E.pend.momento[id] = m; return { id, momento: m };
    });
    try { const d = await api('/api/pendiente_lote', { items }); E.pend = d.pendientes; } catch (e) { aviso(e.message, true); }
    aviso(`Momento «${m || 'sin momento'}» en ${items.length} temas (pendiente de sincronizar).`);
    aplicarFiltros(); pintarSync(); pintarMenu();
    return;
  }
  if (!E.sel) return;
  const t = E.porId[E.sel];
  if (m === t.momento) delete E.pend.momento[t.id]; else E.pend.momento[t.id] = m;
  repintarFila(t.id); pintarSync(); pintarMenu();
  api('/api/pendiente', m === t.momento ? { id: t.id, quitarMomento: true } : { id: t.id, momento: m })
    .catch((e) => aviso(e.message, true));
  const filtroMom = E.filtros.momento;
  if (filtroMom && filtroMom !== (m || 'Sin momento')) {
    // el tema deja de cumplir el filtro: pasa al siguiente sin perder el lugar
    const i = E.lista.findIndex((x) => x.id === t.id);
    E.lista.splice(i, 1); pintarTabla();
    $('#cuenta').textContent = `${E.lista.length} de ${E.temas.length} temas`;
    if (E.lista.length) seleccionar(E.lista[Math.min(i, E.lista.length - 1)].id, true);
  } else if (m) moverSel(1);
  else pintarMomentos();
}

// ---------------------------------------------------------------- PANEL DE METADATA
const CAMPOS = [['titulo', 'Título'], ['artista', 'Artista'], ['album', 'Álbum'], ['anio', 'Año'],
  ['genero', 'Género'], ['grouping', 'Grouping'], ['pais', 'País'], ['idioma', 'Idioma']];
const LISTAS = ['genero', 'grouping', 'pais', 'idioma'];
const IDIOMAS_BASE = ['Español', 'Inglés', 'Portugués', 'Italiano', 'Francés', 'Otro', 'Instrumental'];
const GROUPING_BASE = ['Pop Latino', 'Cumbia Santafesina', 'Cumbia Villera', 'Cumbia Pop', 'Cuarteto', 'Reggaetón Old School',
  'Dembow', 'Synth-pop', 'Dance-pop', 'Eurodance', 'Disco', 'Funk', 'House', 'Tech House', 'Deep House', 'Rock Nacional', 'Pop Rock'];
function pintarListas() {
  const cuenta = (f) => { const c = {}; for (const t of E.temas) { const v = f(t); if (v) c[v] = (c[v] || 0) + 1; } return c; };
  for (const p of Object.values(E.pend.meta)) for (const k of LISTAS) if (p[k] && k === 'grouping') E.groupings.add(p[k]);
  const ordenar = (c, extra = []) => [...new Set([...Object.keys(c).sort((a, b) => c[b] - c[a]), ...extra])];
  const llenar = (id, vals) => { $('#dl-' + id).innerHTML = vals.map((v) => `<option value="${esc(v)}"></option>`).join(''); };
  llenar('genero', ordenar(cuenta((t) => val(t, 'genero'))));
  llenar('pais', ordenar(cuenta((t) => val(t, 'pais'))));
  llenar('idioma', ordenar(cuenta((t) => val(t, 'idioma')), IDIOMAS_BASE));
  llenar('grouping', [...new Set([...E.groupings, ...GROUPING_BASE])]);
}
const LOTE = [['genero', 'Género'], ['grouping', 'Grouping'], ['anio', 'Año'], ['album', 'Álbum'], ['artista', 'Artista'], ['pais', 'País'], ['idioma', 'Idioma']];
function pintarPanel() {
  const multi = E.multi.size > 1;
  setTimeout(pintarTagsMan, 0);
  $('#meta').classList.toggle('lote', multi);
  $('#lote').hidden = !multi;
  if (multi) {
    $('#metaEstado').textContent = '';
    $('.meta-cab h2').textContent = `${E.multi.size} temas seleccionados`;
    const ts = [...E.multi].map((id) => E.porId[id]);
    $('#loteForm').innerHTML = LOTE.map(([k, l]) => {
      const vals = new Set(ts.map((t) => val(t, k) || ''));
      const ph = k === 'grouping' ? 'No cambiar' : vals.size === 1 ? ([...vals][0] || '(vacío)') + ' · igual en todos' : 'Varios — no cambiar';
      return `<label>${l}<input name="${k}" ${LISTAS.includes(k) ? `data-dl="dl-${k}"` : ''} placeholder="${esc(ph)}" spellcheck="false"></label>`;
    }).join('');
  } else {
    $('.meta-cab h2').textContent = 'Metadata';
  }
  pintarBtnEliminar();
}
function pintarBtnEliminar() {
  const n = idsElegidos().length;
  $('#btnEliminar').hidden = !n;
  $('#btnEliminar').textContent = n > 1 ? `Eliminar ${n} temas` : 'Eliminar';
}
const idsElegidos = () => (E.multi.size > 1 ? [...E.multi] : (E.sel ? [E.sel] : []));

// ---------------------------------------------------------------- ELIMINAR TEMAS
async function eliminarTemas() {
  const ids = idsElegidos();
  if (!ids.length) return;
  let d;
  try { d = await api('/api/eliminar/revisar', { ids }); } catch (e) { aviso(e.message, true); return; }
  if (!d.temas.length) return;
  const n = d.temas.length, uno = n === 1;
  const enPl = d.temas.filter((t) => t.playlists.length);
  const fila = (t) => `<div>${esc(t.artista ? `${t.artista} – ${t.titulo}` : t.titulo)}${t.playlists.length ? ` <small>· en ${esc(t.playlists.join(', '))}</small>` : ''}</div>`;
  const html = `<p>${uno ? 'Este tema sale' : `Estos ${n} temas salen`} de Rekordbox y ${uno ? 'su archivo va' : 'sus archivos van'} a la carpeta <b>«eliminados»</b>. No se borra nada del disco y se puede deshacer desde Ajustes e historial.</p>
    ${enPl.length ? `<p class="el-aviso"><b>Atención:</b> ${enPl.length === n ? (uno ? 'está' : 'todos están') : `${enPl.length} de ${n} ${enPl.length === 1 ? 'está' : 'están'}`} en alguna playlist. Si seguís, ${enPl.length === 1 ? 'sale' : 'salen'} también de esas playlists.</p>` : ''}
    <div class="el-lista">${[...enPl, ...d.temas.filter((t) => !t.playlists.length)].map(fila).join('')}</div>
    <p class="nota">Carpeta «eliminados»: ${esc(d.carpeta)}</p>`;
  modal(uno ? '¿Eliminar este tema?' : `¿Eliminar ${n} temas?`, html, [
    { txt: 'Cancelar', fn: cerrarModal },
    { txt: enPl.length ? 'Eliminar igual' : (uno ? 'Eliminar' : `Eliminar ${n} temas`), prim: true, peligro: true, fn: async () => {
      await estado();
      if (E.rbAbierto) { aviso('Cerrá Rekordbox para eliminar (la app tiene que guardar en su base).', true); return; }
      try {
        const r = await api('/api/eliminar', { ids: d.temas.map((t) => t.id) });
        cerrarModal();
        if (r.errores && r.errores.length) aviso(`${r.mensaje} Ojo: ${r.errores.join(' · ')}`, true); else aviso(r.mensaje);
        E.multi.clear(); E.sel = null; await cargarColeccion();
      } catch (e) { aviso(e.message, true); }
    } },
  ]);
}
$('#btnEliminar').onclick = eliminarTemas;
$('#btnLoteCancelar').onclick = limpiarMulti;
$('#loteForm').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('#btnLote').click(); } });
$('#btnLote').onclick = async () => {
  const nuevos = {};
  for (const inp of $('#loteForm').querySelectorAll('input')) if (inp.value.trim()) nuevos[inp.name] = inp.value.trim();
  if (!Object.keys(nuevos).length) { aviso('Completá al menos un campo.'); return; }
  const items = [...E.multi].map((id) => {
    const t = E.porId[id], pm = { ...(E.pend.meta[id] || {}) };
    for (const [k, v] of Object.entries(nuevos)) { if (k !== 'grouping' && v === (t[k] || '')) delete pm[k]; else pm[k] = v; }
    return { id, meta: pm };
  });
  try {
    const d = await api('/api/pendiente_lote', { items });
    E.pend = d.pendientes;
    if (nuevos.grouping) E.groupings.add(nuevos.grouping);
    aviso(`Listo: ${Object.keys(nuevos).map((k) => LOTE.find((x) => x[0] === k)[1].toLowerCase()).join(', ')} en ${items.length} temas. Queda pendiente hasta que sincronices.`);
    pintarListas(); pintarFiltros(); aplicarFiltros(); pintarSync(); pintarMenu(); pintarPanel();
  } catch (e) { aviso(e.message, true); }
};
function pintarTapa(id) {
  const t = E.porId[id], el = $('#tapa');
  $('#tapaTit').textContent = val(t, 'titulo') || '(sin título)';
  $('#tapaSub').textContent = [val(t, 'artista'), val(t, 'album'), val(t, 'anio')].filter(Boolean).join(' · ');
  el.classList.remove('con'); el.style.backgroundImage = '';
  if (!t.existe) return;
  const url = '/caratula?id=' + encodeURIComponent(id) + '&v=' + Date.now();
  const img = new Image();
  img.onload = () => { if (E.sel === id && img.naturalWidth) { el.style.backgroundImage = `url("${url}")`; el.classList.add('con'); el.dataset.url = url; } };
  img.src = url;
}
$('#tapa').onclick = (e) => {
  const el = e.currentTarget; if (!el.classList.contains('con')) return;
  modal($('#tapaTit').textContent, `<img class="grande" src="${el.dataset.url}" alt="Carátula">`, [{ txt: 'Cerrar' }]);
};
async function cargarMeta(id) {
  const t = E.porId[id];
  pintarTapa(id);
  $('#metaArchivo').textContent = t.ruta;
  $('#btnDescTema').hidden = !(E.pend.meta[id] || id in E.pend.momento);
  let base = { titulo: t.titulo, artista: t.artista, album: t.album, anio: t.anio, genero: t.genero, grouping: '', pais: t.pais, idioma: t.idioma };
  pintarMeta(id, base);
  if (!t.existe) { $('#metaEstado').textContent = 'Archivo no encontrado'; return; }
  try {
    const f = await api('/api/tema?id=' + encodeURIComponent(id));
    if (E.sel !== id) return;
    base = { ...base, grouping: f.grouping || '' };
    if (f.grouping && !E.groupings.has(f.grouping)) { E.groupings.add(f.grouping); pintarListas(); }
    if (!base.pais) base.pais = f.pais; if (!base.idioma) base.idioma = f.idioma;
    E.metaTema = base; pintarMeta(id, base);
  } catch (_) { /* queda lo de la base */ }
}
function pintarMeta(id, base) {
  E.metaTema = base;
  const p = E.pend.meta[id] || {};
  const n = Object.keys(p).length;
  $('#metaEstado').textContent = n ? `${n} cambio${n > 1 ? 's' : ''} sin guardar` : '';
  const foco = document.activeElement && document.activeElement.name;
  $('#metaForm').innerHTML = CAMPOS.map(([k, l]) =>
    `<label>${l}<input name="${k}" ${LISTAS.includes(k) ? `data-dl="dl-${k}"` : ''} value="${esc(p[k] !== undefined ? p[k] : base[k] || '')}" class="${p[k] !== undefined ? 'cambio' : ''}" spellcheck="false"></label>`).join('');
  if (foco) $('#metaForm').querySelector(`[name="${foco}"]`)?.focus();
}
$('#metaForm').addEventListener('change', async (e) => {
  const inp = e.target; if (!inp.name || !E.sel) return;
  const id = E.sel, k = inp.name, v = inp.value.trim();
  const orig = (E.metaTema && E.metaTema[k]) || '';
  const pm = { ...(E.pend.meta[id] || {}) };
  if (v === orig) delete pm[k]; else pm[k] = v;
  try {
    const d = await api('/api/pendiente', { id, meta: pm });
    E.pend = d.pendientes;
  } catch (err) { aviso(err.message, true); }
  inp.classList.toggle('cambio', v !== orig);
  const n = Object.keys(E.pend.meta[id] || {}).length;
  $('#metaEstado').textContent = n ? `${n} cambio${n > 1 ? 's' : ''} sin guardar` : '';
  $('#btnDescTema').hidden = !(E.pend.meta[id] || id in E.pend.momento);
  repintarFila(id); pintarSync(); pintarMenu();
});
$('#metaForm').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); }
  if (e.key === 'Escape') { e.preventDefault(); e.target.blur(); }
});
$('#btnFinder').onclick = () => E.sel && api('/api/mostrar', { id: E.sel }).catch((e) => aviso(e.message, true));
$('#btnDescTema').onclick = async () => {
  if (!E.sel) return;
  const d = await api('/api/pendiente', { id: E.sel, descartar: true });
  E.pend = d.pendientes; repintarFila(E.sel); cargarMeta(E.sel); pintarMomentos(); pintarSync(); pintarMenu();
};

// ---------------------------------------------------------------- SINCRONIZAR
function pintarSync() {
  const n = nPend();
  $('#btnSync').textContent = n ? `Sincronizar (${n})` : 'Sincronizado';
  $('#btnSync').disabled = !n;
  $('#btnDescartar').hidden = !n;
}
$('#btnSync').onclick = async () => {
  await estado();
  if (E.rbAbierto) { aviso('Rekordbox está abierto. Cerralo y tocá Sincronizar de nuevo: tus cambios quedan guardados mientras tanto.', true); return; }
  const nm = Object.keys(E.pend.meta).length, nmo = Object.keys(E.pend.momento).length;
  modal('Sincronizar', `<p>Se van a guardar:</p><ul>${nm ? `<li>Metadata de <b>${nm}</b> temas, en los archivos y en Rekordbox (con los My Tags automáticos recalculados)</li>` : ''}${nmo ? `<li>Momento de <b>${nmo}</b> temas, en Rekordbox</li>` : ''}</ul><p class="nota">Antes se hace un backup de la base y de cada archivo que se modifica. Se puede deshacer desde Ajustes e historial.</p>`, [
    { txt: 'Cancelar' },
    { txt: 'Sincronizar', prim: true, fn: async () => {
      try {
        const r = await api('/api/sincronizar', {});
        cerrarModal();
        aviso(r.mensaje + (r.errores && r.errores.length ? '\n\nProblemas:\n' + r.errores.join('\n') : ''), !!(r.errores && r.errores.length));
        await cargarColeccion();
        if (E.sel) { repintarFila(E.sel); cargarMeta(E.sel); }
      } catch (e) { cerrarModal(); aviso(e.message, true); }
    } },
  ]);
};
$('#btnDescartar').onclick = () => modal('Descartar cambios', `<p>¿Descartar los ${nPend()} cambios sin guardar? No se tocó nada todavía, así que no hay nada que deshacer.</p>`, [
  { txt: 'Cancelar' },
  { txt: 'Descartar', prim: true, fn: async () => { await api('/api/descartar', {}); cerrarModal(); await cargarColeccion(); if (E.sel) { seleccionar(E.sel, false); } } },
]);

// ---------------------------------------------------------------- TRAER CAMBIOS DE REKORDBOX
$('#btnTraer').onclick = async () => {
  modal('Traer cambios de Rekordbox', '<p>Comparando los datos de Rekordbox con cada archivo… puede tardar un minuto.</p>', [{ txt: 'Cerrar' }]);
  try {
    const { diferencias } = await api('/api/traer');
    if (!diferencias.length) { $('#modalCuerpo').innerHTML = '<p>Todo coincide: los archivos ya tienen lo mismo que Rekordbox.</p>'; return; }
    const nombres = { titulo: 'Título', artista: 'Artista', album: 'Álbum', genero: 'Género', anio: 'Año', comentario: 'Comentario' };
    $('#modalCuerpo').innerHTML = `<p>${diferencias.length} temas tienen en Rekordbox datos distintos a los del archivo. Los marcados se escriben en el archivo (con backup).</p>` +
      diferencias.map((d, i) => `<label class="dif"><input type="checkbox" data-i="${i}" checked><span><b>${esc(d.tema)}</b>${Object.entries(d.cambios).map(([k, v]) =>
        `<small>${nombres[k] || k}: «${esc(d.antes[k] || '—')}» → «${esc(v)}»</small>`).join('')}</span></label>`).join('');
    modal('Traer cambios de Rekordbox', $('#modalCuerpo').innerHTML, [
      { txt: 'Cancelar' },
      { txt: 'Escribir en los archivos', prim: true, fn: async () => {
        const ids = [...document.querySelectorAll('#modalCuerpo input[data-i]:checked')].map((c) => diferencias[+c.dataset.i].id);
        if (!ids.length) { cerrarModal(); return; }
        try {
          const r = await api('/api/traer', { ids });
          cerrarModal(); aviso(r.mensaje + (r.errores.length ? '\n' + r.errores.join('\n') : ''), !!r.errores.length);
        } catch (e) { cerrarModal(); aviso(e.message, true); }
      } },
    ]);
  } catch (e) { $('#modalCuerpo').innerHTML = `<p>${esc(e.message)}</p>`; }
};

// ---------------------------------------------------------------- DUPLICADOS
const D = { grupos: [], sel: {}, filtro: 'todos' };
$('#btnDup').onclick = async () => {
  modal('Duplicados', '<p>Buscando duplicados en la colección…</p>', [{ txt: 'Cerrar' }]);
  $('#modal .caja').classList.add('ancha');
  try {
    const { grupos } = await api('/api/duplicados');
    D.grupos = grupos; D.sel = {};
    for (const g of grupos) D.sel[g.id] = { queda: g.conservar, borrar: new Set(g.conservar ? g.copias.filter((c) => c.id !== g.conservar).map((c) => c.id) : []) };
    pintarDup();
  } catch (e) { $('#modalCuerpo').innerHTML = `<p>${esc(e.message)}</p>`; }
};
function resumenDup() {
  let n = 0, pls = 0;
  for (const g of D.grupos) {
    const s = D.sel[g.id]; if (!s.queda) continue;
    for (const c of g.copias) if (s.borrar.has(c.id) && c.id !== s.queda) { n++; pls += c.playlists.length; }
  }
  return { n, pls };
}
function pintarDup() {
  const cuenta = { todos: D.grupos.length, sugeridos: D.grupos.filter((g) => g.conservar).length, revisar: D.grupos.filter((g) => !g.conservar).length };
  const vis = D.grupos.filter((g) => D.filtro === 'todos' || (D.filtro === 'sugeridos' ? g.conservar : !g.conservar));
  const { n, pls } = resumenDup();
  const filtros = [['todos', 'Todos'], ['sugeridos', 'Con sugerencia'], ['revisar', 'Para revisar']].map(([k, l]) =>
    `<button type="button" data-df="${k}" class="${D.filtro === k ? 'act' : ''}">${l} (${cuenta[k]})</button>`).join('');
  const html = !D.grupos.length ? '<p>No encontré duplicados. 🎉</p>' : `
    <p class="nota">Se busca por artista + título (sin «Official Video», «feat.», etc.) y por archivo idéntico. La app sugiere cuál queda: primero la que tiene <b>cue points</b>, después la que está en <b>playlists</b>, después la de mejor calidad. Las que se borran se reemplazan por la que queda en sus playlists y pasan su Momento si la otra no tiene. Los archivos van al backup.</p>
    <div class="dup-filtros">${filtros}</div>
    ${vis.map((g) => {
      const s = D.sel[g.id];
      const tipoCls = g.tipo === 'Posible' ? 'posible' : g.tipo === 'Archivo idéntico' ? 'ident' : '';
      const filas = g.copias.map((c) => {
        const queda = s.queda === c.id, bor = !queda && s.queda && s.borrar.has(c.id);
        return `<div class="copia${bor ? ' borrar' : ''}">
          <label class="queda"><input type="radio" name="q-${g.id}" data-g="${g.id}" data-queda="${c.id}" ${queda ? 'checked' : ''}>Queda</label>
          <label class="bor${queda || !s.queda ? ' no' : ''}"><input type="checkbox" data-g="${g.id}" data-bor="${c.id}" ${bor ? 'checked' : ''}>Borrar</label>
          <button type="button" class="mini" data-play="${c.id}" title="Escuchar">▶</button>
          <span class="arch" title="${esc(c.ruta)}">${esc(c.archivo)}${c.existe ? '' : ' (no está el archivo)'}</span>
          <span class="cues${c.hot + c.mem ? ' si' : ''}">${c.hot + c.mem ? (c.hot + c.mem) + ' cues' : 'sin cues'}</span>
          <span class="pls${c.playlists.length ? ' si' : ''}" title="${esc(c.playlists.join('\n'))}">${c.playlists.length ? c.playlists.length + ' pl: ' + esc(c.playlists.join(', ')) : 'en ninguna playlist'}</span>
          <span>${esc(c.momento || '—')}</span><span>${c.bitrate ? c.bitrate + ' kbps' : ''}</span><span>${fmt(c.duracion)}</span><span>${c.agregado}</span></div>`;
      }).join('');
      const aPl = g.copias.filter((c) => s.queda && c.id !== s.queda && s.borrar.has(c.id) && c.playlists.length);
      return `<div class="grupo"><div class="grupo-cab"><b>${esc(g.titulo)}</b><span class="chip ${tipoCls}">${g.tipo}</span>${g.mismoArchivo ? '<span class="chip">mismo archivo cargado dos veces: se borra solo la entrada repetida, el archivo queda</span>' : ''}<span class="motivo">${esc(g.motivo)}</span></div>
        <div class="copia enc"><span>Queda</span><span>Borrar</span><span></span><span>Archivo</span><span>Cues</span><span>Playlists</span><span>Momento</span><span>Calidad</span><span>Dur.</span><span>Agregado</span></div>
        ${filas}${aPl.length ? `<div class="aviso-pl">⚠ ${aPl.map((c) => `«${esc(c.archivo)}» está en ${c.playlists.length} playlist${c.playlists.length > 1 ? 's' : ''}`).join('; ')}: se reemplaza por la que queda, en la misma posición.</div>` : ''}</div>`;
    }).join('')}`;
  $('#modalCuerpo').innerHTML = html;
  const acc = $('#modalAcc'); acc.innerHTML = '';
  const cerrar = document.createElement('button'); cerrar.type = 'button'; cerrar.className = 'btn'; cerrar.textContent = 'Cerrar';
  cerrar.onclick = () => { cerrarModal(); $('#modal .caja').classList.remove('ancha'); };
  const ok = document.createElement('button'); ok.type = 'button'; ok.className = 'btn prim';
  ok.textContent = n ? `Borrar ${n} duplicado${n > 1 ? 's' : ''}` : 'Nada para borrar'; ok.disabled = !n;
  ok.onclick = () => confirmarDup(n, pls);
  acc.append(cerrar, ok);
}
$('#modalCuerpo').addEventListener('click', (e) => {
  const f = e.target.closest('[data-df]'); if (f) { D.filtro = f.dataset.df; pintarDup(); return; }
  const p = e.target.closest('[data-play]'); if (p) { const t = E.porId[p.dataset.play]; if (t) { if (!audio.paused && audio.dataset.id === t.id) audio.pause(); else { tocar(t); audio.dataset.id = t.id; } } }
});
$('#modalCuerpo').addEventListener('change', (e) => {
  const el = e.target; if (!el.dataset.g) return;
  const s = D.sel[el.dataset.g], g = D.grupos.find((x) => x.id === el.dataset.g);
  if (el.dataset.queda) { s.queda = el.dataset.queda; s.borrar = new Set(g.copias.filter((c) => c.id !== s.queda).map((c) => c.id)); }
  if (el.dataset.bor) { if (el.checked) s.borrar.add(el.dataset.bor); else s.borrar.delete(el.dataset.bor); }
  const y = $('#modalCuerpo').scrollTop; pintarDup(); $('#modalCuerpo').scrollTop = y;
});
async function confirmarDup(n, pls) {
  await estado();
  if (E.rbAbierto) { aviso('Cerrá Rekordbox para borrar duplicados (la app modifica su base).', true); return; }
  const grupos = D.grupos.filter((g) => D.sel[g.id].queda).map((g) => ({
    conservar: D.sel[g.id].queda, borrar: [...D.sel[g.id].borrar].filter((id) => id !== D.sel[g.id].queda),
  })).filter((g) => g.borrar.length);
  const cont = $('#modalCuerpo').innerHTML;
  $('#modalCuerpo').innerHTML = `<p>Se van a sacar <b>${n}</b> temas de Rekordbox y sus archivos van al backup.${pls ? ` Se hacen <b>${pls}</b> reemplazos en playlists.` : ''}</p><p class="nota">Antes se hace un backup de la base. Se puede deshacer desde Ajustes e historial.</p>`;
  const acc = $('#modalAcc'); acc.innerHTML = '';
  const vol = document.createElement('button'); vol.type = 'button'; vol.className = 'btn'; vol.textContent = 'Volver';
  vol.onclick = () => { $('#modalCuerpo').innerHTML = cont; pintarDup(); };
  const ok = document.createElement('button'); ok.type = 'button'; ok.className = 'btn prim'; ok.textContent = 'Borrar duplicados';
  ok.onclick = async () => {
    ok.disabled = true; ok.textContent = 'Borrando…';
    try {
      const r = await api('/api/duplicados', { grupos });
      cerrarModal(); $('#modal .caja').classList.remove('ancha');
      aviso(r.mensaje + (r.errores && r.errores.length ? '\n\nProblemas:\n' + r.errores.join('\n') : ''), !!(r.errores && r.errores.length));
      E.sel = null; await cargarColeccion();
    } catch (e) { aviso(e.message, true); ok.disabled = false; ok.textContent = 'Borrar duplicados'; }
  };
  acc.append(vol, ok);
}

// ---------------------------------------------------------------- SUGERENCIAS
// Género, Grouping, País e Idioma sugieren valores de la colección con una lista propia:
// el desplegable del sistema (<datalist>) en modo oscuro casi no se lee, sobre todo en Mac.
const SUG = { inp: null, items: [], i: -1, el: null };
const sinTildes = (s) => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
function sugCaja() {
  if (SUG.el) return SUG.el;
  SUG.el = document.createElement('div');
  SUG.el.className = 'sug'; SUG.el.id = 'sug'; SUG.el.setAttribute('role', 'listbox'); SUG.el.hidden = true;
  SUG.el.addEventListener('mousedown', (e) => { e.preventDefault(); const o = e.target.closest('[data-i]'); if (o) elegirSug(+o.dataset.i, true); });
  document.body.append(SUG.el);
  return SUG.el;
}
// todos: al entrar al campo o hacerle clic se ve la lista entera; al escribir, se filtra
function abrirSug(inp, todos) {
  const dl = document.getElementById(inp.dataset.dl); if (!dl) return;
  const q = todos ? '' : sinTildes(inp.value), empiezan = [], contienen = [];
  for (const o of dl.options) {
    const n = sinTildes(o.value);
    if (!q || n.startsWith(q)) empiezan.push(o.value); else if (n.includes(q)) contienen.push(o.value);
  }
  SUG.items = [...empiezan, ...contienen].slice(0, 80);
  if (!SUG.items.length || (SUG.items.length === 1 && sinTildes(SUG.items[0]) === q)) { cerrarSug(); return; }
  SUG.inp = inp; SUG.i = -1;
  const actual = SUG.items.findIndex((v) => sinTildes(v) === sinTildes(inp.value));
  const caja = sugCaja();
  const marcar = (v) => {
    const k = q ? sinTildes(v).indexOf(q) : -1;
    return k < 0 ? esc(v) : esc(v.slice(0, k)) + '<b>' + esc(v.slice(k, k + q.length)) + '</b>' + esc(v.slice(k + q.length));
  };
  caja.innerHTML = SUG.items.map((v, i) => `<div class="sug-op" role="option" id="sug-${i}" data-i="${i}">${marcar(v)}</div>`).join('');
  caja.hidden = false;
  const r = inp.getBoundingClientRect(), alto = Math.min(260, caja.scrollHeight + 2);
  caja.style.left = r.left + 'px';
  caja.style.width = Math.max(r.width, 180) + 'px';
  caja.style.top = (r.bottom + 4 + alto > innerHeight && r.top - 4 - alto > 0 ? r.top - 4 - alto : r.bottom + 4) + 'px';
  inp.setAttribute('aria-expanded', 'true');
  if (actual >= 0) { SUG.i = actual; caja.querySelector(`[data-i="${actual}"]`).classList.add('act'); caja.querySelector(`[data-i="${actual}"]`).scrollIntoView({ block: 'nearest' }); }
}
function cerrarSug() {
  if (SUG.el) SUG.el.hidden = true;
  if (SUG.inp) { SUG.inp.setAttribute('aria-expanded', 'false'); SUG.inp.removeAttribute('aria-activedescendant'); }
  SUG.inp = null; SUG.i = -1;
}
function marcarSug(i) {
  SUG.i = i;
  SUG.el.querySelectorAll('.sug-op').forEach((o) => o.classList.toggle('act', +o.dataset.i === i));
  const o = SUG.el.querySelector(`[data-i="${i}"]`);
  if (o) { o.scrollIntoView({ block: 'nearest' }); SUG.inp.setAttribute('aria-activedescendant', o.id); }
}
function elegirSug(i, conMouse) {
  const inp = SUG.inp; if (!inp || !(i in SUG.items)) return;
  inp.value = SUG.items[i];
  cerrarSug();
  // con el mouse se guarda en el momento; con Enter lo guarda el propio formulario al soltar el campo
  if (conMouse) inp.dispatchEvent(new Event('change', { bubbles: true }));
}
const esSug = (el) => el && el.tagName === 'INPUT' && el.dataset && el.dataset.dl;
document.addEventListener('focusin', (e) => {
  if (!esSug(e.target)) return;
  const inp = e.target;
  inp.setAttribute('role', 'combobox'); inp.setAttribute('aria-autocomplete', 'list'); inp.setAttribute('aria-controls', 'sug');
  abrirSug(inp, true);
});
document.addEventListener('focusout', (e) => { if (e.target === SUG.inp) cerrarSug(); });
document.addEventListener('input', (e) => { if (esSug(e.target)) abrirSug(e.target); });
document.addEventListener('mousedown', (e) => { if (esSug(e.target) && document.activeElement === e.target && !SUG.inp) abrirSug(e.target, true); });
document.addEventListener('keydown', (e) => {
  if (!esSug(e.target)) return;
  if (!SUG.inp) { if (e.key === 'ArrowDown') { e.preventDefault(); abrirSug(e.target, true); } return; }
  if (e.key === 'ArrowDown') { e.preventDefault(); marcarSug(Math.min(SUG.i + 1, SUG.items.length - 1)); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); marcarSug(Math.max(SUG.i - 1, 0)); }
  else if (e.key === 'Enter' && SUG.i >= 0) elegirSug(SUG.i, false);
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cerrarSug(); }
  else if (e.key === 'Tab') cerrarSug();
}, true);
addEventListener('resize', cerrarSug);
document.addEventListener('scroll', (e) => { if (SUG.inp && !(SUG.el && SUG.el.contains(e.target))) cerrarSug(); }, true);

// ---------------------------------------------------------------- TECLADO
document.addEventListener('keydown', (e) => {
  if (E.vista !== 'coleccion' || !$('#modal').hidden) return;
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'a') {
    e.preventDefault(); E.multi = new Set(E.lista.map((t) => t.id)); pintarTabla(); pintarPanel(); return;
  }
  if (e.key === 'Escape' && E.multi.size) { e.preventDefault(); limpiarMulti(); return; }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const teclas = (E.config && E.config.teclas) || [];
  if (e.key === 'Tab') { e.preventDefault(); if (E.multi.size) limpiarMulti(); moverSel(e.shiftKey ? -1 : 1); }
  else if (e.key >= '1' && e.key <= '4') { e.preventDefault(); if (teclas[+e.key - 1]) ponerMomento(teclas[+e.key - 1]); }
  else if (e.key === '0' || e.key === 'Backspace') { e.preventDefault(); ponerMomento(''); }
  else if (e.key === 'Delete') { e.preventDefault(); eliminarTemas(); }
  else if (e.key === ' ') { e.preventDefault(); playPausa(); }
  else if (e.key === 'ArrowDown') { e.preventDefault(); moverSel(1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); moverSel(-1); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); audio.currentTime += 10; }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); audio.currentTime -= 10; }
});

// ---------------------------------------------------------------- MY TAGS
async function pintarMyTags(resumen) {
  let d;
  try { d = await api('/api/mytags'); } catch (e) { $('#mtCats').innerHTML = `<p class="nota">${esc(e.message)}</p>`; return; }
  MT.cats = d.categorias; MT.fuentes = d.fuentes;
  const prev = {}; (resumen || []).forEach((r) => { prev[r.id] = r; });
  $('#mtCats').innerHTML = MT.cats.map((c) => {
    const opciones = Object.entries(MT.fuentes).map(([k, l]) => `<option value="${k}" ${c.fuente === k ? 'selected' : ''}>${esc(l)}</option>`).join('');
    const cab = `<div class="mt-cab"><input class="mt-nombre" data-catnom="${c.id}" value="${esc(c.nombre)}" aria-label="Nombre de la categoría">
      <select class="mt-fuente" data-catfuente="${c.id}" ${c.id === '4' ? 'disabled title="La 4 es la de etiquetado rápido con las teclas 1–4"' : ''}>${opciones}</select></div>`;
    if (!c.manual) {
      const p = prev[c.id];
      const filas = p ? Object.entries(p.tags) : c.tags.map((t) => [t.nombre, t.temas]);
      return `<div class="cat">${cab}
        ${p ? `<p class="nota" style="color:var(--acento2)">Simulación: cambiarían ${p.cambios} temas</p>` : ''}
        <div class="tg-lista">${filas.map(([n, k]) => `<div class="tg"><span>${esc(n)}</span><span>${k}</span></div>`).join('') || '<p class="nota">Sin tags todavía: tocá «Actualizar base de Rekordbox».</p>'}</div>
        <p class="nota">Se completa solo con la metadata de cada tema.</p></div>`;
    }
    return `<div class="cat manual">${cab}
      <div class="tg-lista">${c.tags.map((t, i) => `<div class="tg ed">
        <input value="${esc(t.nombre)}" data-mtren="${t.id}" data-cat="${c.id}" data-viejo="${esc(t.nombre)}" aria-label="Nombre del tag">
        <span class="n">${t.temas}</span>
        <button type="button" class="mt-b" data-mtmov="${i}" data-cat="${c.id}" data-dir="-1" ${i ? '' : 'disabled'} title="Subir">↑</button>
        <button type="button" class="mt-b" data-mtmov="${i}" data-cat="${c.id}" data-dir="1" ${i < c.tags.length - 1 ? '' : 'disabled'} title="Bajar">↓</button>
        <button type="button" class="mt-b x" data-mtdel="${t.id}" data-cat="${c.id}" data-viejo="${esc(t.nombre)}" data-n="${t.temas}" title="Borrar">×</button></div>`).join('')}</div>
      <form class="mt-add" data-mtadd="${c.id}"><input placeholder="Nuevo tag"><button type="submit" class="btn chico prim">Agregar</button></form>
      <p class="nota">${c.id === '4' ? 'Se pone a mano en Colección (teclas 1–4, elegidas en Ajustes).' : 'Se pone a mano en Colección, en el panel de cada tema.'}</p></div>`;
  }).join('');
}
const MT = { cats: [], fuentes: {} };
async function guardarCategorias() {
  const cats = MT.cats.map((c) => ({
    id: c.id, nombre: $(`[data-catnom="${c.id}"]`).value.trim() || c.nombre, fuente: $(`[data-catfuente="${c.id}"]`).value,
  }));
  try { const r = await api('/api/mytags/config', { categorias: cats }); aviso(r.mensaje); await pintarMyTags(); cargarColeccion(); }
  catch (e) { aviso(e.message, true); }
}
async function editarMT(cambios) {
  await estado();
  if (E.rbAbierto) { aviso('Cerrá Rekordbox para editar los tags (se guardan en su base).', true); pintarMyTags(); return; }
  try {
    const r = await api('/api/mytags/editar', { cambios });
    aviso(r.mensaje);
    const d = await api('/api/estado'); E.config = d.config;
    await cargarColeccion(); pintarMyTags();
  } catch (e) { aviso(e.message, true); pintarMyTags(); }
}
$('#mtCats').addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset.catnom || el.dataset.catfuente) { guardarCategorias(); return; }
  if (!el.dataset.mtren) return;
  const nombre = el.value.trim();
  if (nombre && nombre !== el.dataset.viejo) editarMT([{ cat: el.dataset.cat, accion: 'renombrar', id: el.dataset.mtren, nombre, viejo: el.dataset.viejo }]);
  else el.value = el.dataset.viejo;
});
$('#mtCats').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.target.dataset.mtren || e.target.dataset.catnom)) { e.preventDefault(); e.target.blur(); } });
$('#mtCats').addEventListener('submit', (e) => {
  const f = e.target.closest('[data-mtadd]'); if (!f) return;
  e.preventDefault();
  const n = f.querySelector('input').value.trim();
  if (n) editarMT([{ cat: f.dataset.mtadd, accion: 'agregar', nombre: n }]);
});
$('#mtCats').addEventListener('click', (e) => {
  const mv = e.target.closest('[data-mtmov]');
  if (mv) {
    const cat = mv.dataset.cat;
    const tags = MT.cats.find((c) => c.id === cat).tags.map((t) => t.id);
    const i = +mv.dataset.mtmov, j = i + +mv.dataset.dir;
    [tags[i], tags[j]] = [tags[j], tags[i]];
    editarMT([{ cat, accion: 'ordenar', ids: tags }]);
    return;
  }
  const del = e.target.closest('[data-mtdel]');
  if (del) {
    const n = +del.dataset.n;
    modal('Borrar tag', `<p>¿Borrar el tag <b>${esc(del.dataset.viejo)}</b>?${n ? ` Está puesto en <b>${n}</b> temas: se les quita.` : ''}</p><p class="nota">Se puede deshacer desde Ajustes e historial.</p>`, [
      { txt: 'Cancelar' },
      { txt: 'Borrar', prim: true, fn: async () => { cerrarModal(); await editarMT([{ cat: del.dataset.cat, accion: 'borrar', id: del.dataset.mtdel, viejo: del.dataset.viejo }]); } },
    ]);
  }
});
async function correrMyTags(simular) {
  if (!simular) { await estado(); if (E.rbAbierto) { aviso('Cerrá Rekordbox para actualizar la base.', true); return; } }
  $('#mtSimular').disabled = $('#mtAplicar').disabled = true;
  const txt = $('#mtAplicar').textContent;
  if (!simular) $('#mtAplicar').textContent = 'Actualizando…'; else $('#mtSimular').textContent = 'Simulando…';
  try {
    const r = await api('/api/mytags', { simular });
    if (simular) { await pintarMyTags(r.resumen); aviso('Simulación lista: mirá en cada categoría cuántos temas cambiarían.'); }
    else { aviso(r.mensaje); await cargarColeccion(); await pintarMyTags(); }
  } catch (e) { aviso(e.message, true); } finally {
    $('#mtSimular').disabled = $('#mtAplicar').disabled = false; $('#mtAplicar').textContent = txt; $('#mtSimular').textContent = 'Simular';
  }
}
$('#mtSimular').onclick = () => correrMyTags(true);
$('#mtAplicar').onclick = async () => {
  let resumen;
  try { resumen = (await api('/api/mytags', { simular: true })).resumen; } catch (e) { aviso(e.message, true); return; }
  const propios = resumen.filter((c) => c.seQuitan && c.seQuitan.temas);
  if (!propios.length) { correrMyTags(false); return; }
  modal('Vas a reemplazar My Tags que ya tenías', `<p>Estas categorías pasan a armarse solas, y los tags que tenías ahí se sacan de Rekordbox:</p>
    <ul>${propios.map((c) => `<li><b>${esc(c.nombre)}</b>: ${esc(c.seQuitan.tags.slice(0, 8).join(', '))}${c.seQuitan.tags.length > 8 ? '…' : ''} (en ${c.seQuitan.temas} temas)</li>`).join('')}</ul>
    <p class="nota">Si querés conservarlos, cancelá y poné esa categoría en «Manual» acá arriba. Antes de cambiar nada se hace un backup y se puede deshacer desde Ajustes.</p>`, [
    { txt: 'Cancelar' },
    { txt: 'Reemplazar y actualizar', prim: true, fn: async () => { cerrarModal(); await correrMyTags(false); } },
  ]);
};

// ---------------------------------------------------------------- AJUSTES
const CARPETAS = [['coleccion', 'Colección', 'Donde viven los temas que usa Rekordbox.'],
  ['incorporar', 'Temas a incorporar', 'Donde bajás los temas de la lista depurada. La solapa 2 lee de acá.'],
  ['backup', 'Backups', 'Copias de los archivos originales y de la base de Rekordbox antes de cada cambio.'],
  ['rekordbox', 'Base de Rekordbox', 'Carpeta de master.db. No hace falta cambiarla.']];
async function pintarAjustes() {
  await estado();
  const c = E.config;
  $('#carpetas').innerHTML = CARPETAS.map(([k, l, n]) => `<div class="carpeta"><b>${l}</b><div class="fila2"><span class="ruta" title="${esc(c[k])}">${esc(c[k])}</span><button type="button" class="btn chico" data-carpeta="${k}">Cambiar…</button></div><span class="nota">${n}</span></div>`).join('');
  $('#teclas').innerHTML = [0, 1, 2, 3].map((i) => `<label>Tecla ${i + 1}<select data-tecla="${i}">${`<option value="" ${c.teclas[i] ? '' : 'selected'}>(ninguno)</option>` + (E.momentos.length ? E.momentos : ['Previa', 'Warm Up', 'Main', 'Peak', 'Close', 'Lentos']).map((m) =>
    `<option ${c.teclas[i] === m ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select></label>`).join('');
  $('#inicio').value = c.inicio; $('#inicioSeg').value = c.inicio_seg; $('#lastfm').value = c.lastfm;
  for (const k of ['spotify_id', 'spotify_secret', 'youtube_key']) $('#' + k).value = c[k] || '';
  pintarSpotify(); $('#discogs').value = c.discogs;
  $('#estadisticas').checked = c.estadisticas !== false;
  pintarHistorial();
}
$('#estadisticas').onchange = async (e) => {
  try { const d = await api('/api/config', { estadisticas: e.target.checked, estadisticas_avisado: true }); E.config = d.config; aviso(e.target.checked ? 'Estadísticas anónimas prendidas. Gracias.' : 'Listo: no se envía ninguna estadística.'); }
  catch (err) { aviso(err.message, true); e.target.checked = !e.target.checked; }
};
$('#carpetas').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-carpeta]'); if (!b) return;
  const { ruta } = await api('/api/elegir_carpeta', { titulo: 'Elegí la carpeta' });
  if (ruta) { await api('/api/config', { [b.dataset.carpeta]: ruta }); aviso('Carpeta guardada.'); pintarAjustes(); }
});
$('#teclas').addEventListener('change', async () => {
  const teclas = [...document.querySelectorAll('#teclas select')].map((s) => s.value);
  const d = await api('/api/config', { teclas }); E.config = d.config; pintarMomentos(); aviso('Teclas guardadas.');
});
for (const id of ['inicioSeg']) {
  $('#' + id).addEventListener('change', async (e) => { const d = await api('/api/config', { inicio_seg: Math.max(0, Number(e.target.value) || 0) }); E.config = d.config; pintarInicio(); aviso('Guardado.'); });
}
function pintarInicio() {
  if (!E.config) return;
  $('#pInicio').value = E.config.inicio; $('#pSeg').value = E.config.inicio_seg;
  const conSeg = E.config.inicio === 'seg';
  $('#pSeg').hidden = $('#pSegTxt').hidden = !conSeg;
}
$('#pInicio').addEventListener('change', async (e) => { const d = await api('/api/config', { inicio: e.target.value }); E.config = d.config; pintarInicio(); e.target.blur(); });
$('#pSeg').addEventListener('change', async (e) => { const d = await api('/api/config', { inicio_seg: Math.max(0, Number(e.target.value) || 0) }); E.config = d.config; pintarInicio(); e.target.blur(); });
$('#pSeg').addEventListener('keydown', (e) => { if (e.key === 'Enter') e.target.blur(); });
$('#btnPrivacidad').onclick = () => api('/api/abrir_privacidad', {});
for (const id of ['inicio', 'lastfm', 'discogs', 'spotify_id', 'spotify_secret', 'youtube_key']) {
  $('#' + id).addEventListener('change', async (e) => { const d = await api('/api/config', { [id]: e.target.value.trim() }); E.config = d.config; pintarInicio(); aviso('Guardado.'); });
}
async function pintarHistorial() {
  const { historial } = await api('/api/historial');
  const vigente = historial.find((h) => !h.deshecho);
  $('#historial').innerHTML = historial.length ? historial.map((h) => `<div class="hist${h.deshecho ? ' deshecho' : ''}"><div><b>${esc(h.que)}</b><small>${new Date(h.cuando).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' })} · ${esc(h.detalle)}${h.archivos ? ` · ${esc(h.archivos)} archivos respaldados` : ''}${h.deshecho ? ' · deshecho' : ''}</small></div>${!h.deshecho && vigente && vigente.id === h.id ? `<button type="button" class="btn chico" data-deshacer="${esc(h.id)}">Deshacer</button>` : ''}</div>`).join('')
    : '<p class="nota">Todavía no hay operaciones.</p>';
}
$('#historial').addEventListener('click', (e) => {
  const b = e.target.closest('[data-deshacer]'); if (!b) return;
  modal('Deshacer', '<p>Se vuelve la base de Rekordbox y los archivos al estado anterior a esta operación. Rekordbox tiene que estar cerrado.</p>', [
    { txt: 'Cancelar' },
    { txt: 'Deshacer', prim: true, fn: async () => {
      try { const r = await api('/api/deshacer', { id: b.dataset.deshacer }); cerrarModal(); aviso(r.mensaje); pintarHistorial(); cargarColeccion(); } catch (err) { cerrarModal(); aviso(err.message, true); }
    } },
  ]);
});

// ---------------------------------------------------------------- SALIR
async function salir() {
  audio.pause();
  try { await api('/api/salir', {}); } catch (_) { /* nada */ }
  document.body.innerHTML = '<p style="padding:40px;color:#9AA0AA">La app se cerró. Ya podés cerrar esta ventana.</p>';
}
$('#btnSalir').onclick = () => {
  if (!nPend()) { salir(); return; }
  modal('Cerrar la app', `<p>Tenés ${nPend()} cambios sin sincronizar. Quedan guardados para la próxima vez.</p>`, [
    { txt: 'Cancelar' }, { txt: 'Cerrar igual', prim: true, fn: salir },
  ]);
};

// ---------------------------------------------------------------- INICIO
function avisoEstadisticas() {
  // para quien ya usaba la app antes de que existieran las estadísticas: se explica una sola vez
  const guardar = async (prendidas) => {
    const d = await api('/api/config', { estadisticas: prendidas, estadisticas_avisado: true });
    E.config = d.config; cerrarModal();
    if (!prendidas) aviso('Listo: no se envía ninguna estadística.');
  };
  modal('Estadísticas anónimas de uso', `
    <p>Para saber cuánta gente usa la app de verdad, ahora envía <b>estadísticas anónimas</b>: cuántas veces se instala y se abre, qué versión y sistema, y qué funciones se usan (como mucho una vez por día cada una).</p>
    <p>Nunca se envía nada de tu música ni de vos: ni temas, ni carpetas, ni nombres, ni cantidades. Se puede cambiar cuando quieras en Ajustes.</p>`, [
    { txt: 'No enviar', fn: () => guardar(false) },
    { txt: 'Dejar prendidas', prim: true, fn: () => guardar(true) },
  ]);
}
function avisoRiesgo() {
  modal('Antes de empezar', `
    <p><b>RKB Collection Manager</b> es una herramienta gratuita hecha por un DJ para DJs. Trabaja directamente sobre tus archivos de música y sobre la base de datos de Rekordbox.</p>
    <ul>
      <li>Puede tener errores. <b>La usás bajo tu propia responsabilidad</b>: ni el autor ni nadie que la comparta se hace responsable por pérdidas de datos, de archivos o problemas con Rekordbox.</li>
      <li>Antes de cada cambio la app hace un backup y casi todo se puede deshacer, pero igual <b>tené tu propio backup</b> de la música y de Rekordbox (Archivo › Biblioteca › Hacer copia de seguridad).</li>
      <li>No está afiliada ni respaldada por AlphaTheta / Pioneer DJ (Rekordbox) ni por ninguna otra empresa.</li>
    </ul>
    <label class="campo-in"><input type="checkbox" id="rgEstadisticas" checked> Enviar estadísticas anónimas de uso: sólo cuántas veces se abre la app y qué funciones se usan, nunca nada de tu música ni de vos (se cambia en Ajustes).</label>`, [
    { txt: 'Salir', fn: salir },
    { txt: 'Entiendo y acepto', prim: true, fn: async () => { const d = await api('/api/config', { acepto_riesgo: true, estadisticas: $('#rgEstadisticas').checked, estadisticas_avisado: true }); E.config = d.config; cerrarModal(); } },
  ]);
}
(async () => {
  pintarMenu(); irA('coleccion');
  await estado();
  if (E.config && !E.config.acepto_riesgo) avisoRiesgo();
  else if (E.config && !E.config.estadisticas_avisado) avisoEstadisticas();
  await cargarColeccion();
  setInterval(estado, 5000);
})();

// ---------------------------------------------------------------- SIGUEN BIEN (sugerencias de mezcla)
function camelotVecinos(k) {
  const m = /^(\d{1,2})([AB])$/.exec(k || ''); if (!m) return null;
  const n = +m[1], l = m[2], otro = l === 'A' ? 'B' : 'A';
  const mas = n % 12 + 1, menos = (n + 10) % 12 + 1;
  return { [`${n}${l}`]: 'mismo tono', [`${mas}${l}`]: 'tono +1', [`${menos}${l}`]: 'tono −1', [`${n}${otro}`]: 'relativo' };
}
function pintarSiguen() {
  const t = E.sel && E.porId[E.sel];
  if (!t || E.multi.size > 1) { $('#sgLista').innerHTML = ''; $('#sgCuenta').textContent = ''; return; }
  const pct = +$('#sgBpm').value / 100, conGenero = $('#sgGenero').checked, conMom = $('#sgMomento').checked, conTono = $('#sgTono').checked;
  const vecinos = camelotVecinos(t.tono), gen = val(t, 'genero'), mom = momentoDe(t);
  const out = [];
  for (const o of E.temas) {
    if (o.id === t.id || !o.existe) continue;
    if (conGenero && gen && val(o, 'genero') !== gen) continue;
    if (conMom && mom && momentoDe(o) !== mom) continue;
    let dif = null;
    if (t.bpm && o.bpm) {
      for (const f of [1, 2, 0.5]) { const d = Math.abs(o.bpm * f - t.bpm) / t.bpm; if (dif === null || d < dif) dif = d; }
      if (dif > pct) continue;
    } else continue;
    const rel = vecinos && vecinos[o.tono];
    if (conTono && vecinos && !rel) continue;
    const puntos = (rel === 'mismo tono' ? 3 : rel ? 2 : 0) + (1 - dif / pct) * 2 + (mom && momentoDe(o) === mom ? 1 : 0)
      + (val(o, 'artista') === val(t, 'artista') ? -0.5 : 0);
    out.push({ o, puntos, dif, rel });
  }
  out.sort((a, b) => b.puntos - a.puntos);
  $('#sgCuenta').textContent = out.length ? `${out.length} temas` : '';
  $('#sgLista').innerHTML = out.slice(0, 10).map(({ o, rel }) => `<div class="sg" data-sg="${o.id}">
      <span><b>${esc(val(o, 'titulo'))}</b><small>${esc(val(o, 'artista'))}${momentoDe(o) ? ' · ' + esc(momentoDe(o)) : ''}</small></span>
      <span class="por">${Math.round(o.bpm)} · ${esc(o.tono || '?')}${rel && rel !== 'mismo tono' ? '<br><small>' + rel + '</small>' : ''}</span></div>`).join('')
    || `<p class="nota">${t.bpm ? 'Nada que cumpla todo: probá ampliar el BPM o destildar algún criterio.' : 'Este tema no tiene BPM: analizalo en Rekordbox.'}</p>`;
}
['sgGenero', 'sgMomento', 'sgTono', 'sgBpm'].forEach((id) => $('#' + id).addEventListener('change', (e) => { pintarSiguen(); e.target.blur(); }));
$('#sgLista').addEventListener('click', (e) => {
  const f = e.target.closest('[data-sg]'); if (!f) return;
  const id = f.dataset.sg;
  if (!E.lista.some((x) => x.id === id)) { E.filtros = {}; E.buscar = ''; $('#buscar').value = ''; pintarFiltros(); aplicarFiltros(); }
  seleccionar(id, true); verFila(id, 'center');
});


// ---------------------------------------------------------------- LIMPIEZA DE BACKUPS
const tamTxt = (b) => (b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : b >= 1e6 ? Math.round(b / 1e6) + ' MB' : Math.round(b / 1e3) + ' KB');
async function pintarBackups() {
  let d;
  try { d = await api('/api/backups'); } catch (e) { $('#backups').innerHTML = `<p class="nota">${esc(e.message)}</p>`; return; }
  BK.d = d;
  const hoy = new Date();
  const viejo = (f) => (hoy - new Date(f)) / 864e5 > 30;
  $('#backups').innerHTML = `<p class="nota">En total ocupan <b>${tamTxt(d.total)}</b> (${esc(d.carpeta)}). Borrar el backup de una operación hace que ya no se pueda deshacer.</p>
    <div class="bk-acc"><button type="button" class="btn chico" id="bkViejos">Marcar operaciones de más de 30 días</button><button type="button" class="btn chico prim" id="bkBorrar" disabled>Borrar marcados</button></div>
    ${d.items.map((it, i) => `<label class="bk"><input type="checkbox" data-bk="${i}"><span>${esc(it.nombre)}<br><small>${it.tipo === 'operacion' ? 'Operación de la app' : 'Otro backup'} · ${esc(it.fecha)}${it.deshecho ? ' · ya deshecha' : ''}</small></span><span class="tam">${tamTxt(it.bytes)}</span><small>${it.tipo === 'operacion' && viejo(it.fecha) ? '+30 días' : ''}</small></label>`).join('')}`;
  const actualizar = () => {
    const sel = [...document.querySelectorAll('[data-bk]:checked')].map((c) => d.items[+c.dataset.bk]);
    $('#bkBorrar').disabled = !sel.length;
    $('#bkBorrar').textContent = sel.length ? `Borrar marcados (${tamTxt(sel.reduce((a, x) => a + x.bytes, 0))})` : 'Borrar marcados';
  };
  $('#backups').onchange = actualizar;
  $('#bkViejos').onclick = () => { document.querySelectorAll('[data-bk]').forEach((c) => { const it = d.items[+c.dataset.bk]; c.checked = it.tipo === 'operacion' && viejo(it.fecha); }); actualizar(); };
  $('#bkBorrar').onclick = () => {
    const sel = [...document.querySelectorAll('[data-bk]:checked')].map((c) => d.items[+c.dataset.bk]);
    const otros = sel.filter((x) => x.tipo !== 'operacion');
    modal('Borrar backups', `<p>Se van a borrar <b>${sel.length}</b> backups (${tamTxt(sel.reduce((a, x) => a + x.bytes, 0))}). <b>No se puede deshacer.</b></p>${otros.length ? `<p class="nota">Incluye ${otros.length} que no son de la app: ${otros.map((x) => esc(x.nombre)).join(', ')}.</p>` : ''}`, [
      { txt: 'Cancelar' },
      { txt: 'Borrar', prim: true, fn: async () => {
        try { const r = await api('/api/backups/borrar', { rutas: sel.map((x) => x.ruta) }); cerrarModal(); aviso(r.mensaje + (r.errores.length ? '\n' + r.errores.join('\n') : ''), !!r.errores.length); pintarBackups(); pintarHistorial(); } catch (e) { cerrarModal(); aviso(e.message, true); }
      } },
    ]);
  };
}
const BK = { d: null };

// ---------------------------------------------------------------- SPOTIFY (conexión)
async function pintarSpotify() {
  const s = await api('/api/spotify');
  $('#spCon').innerHTML = s.conectado
    ? `<span>Spotify conectado${s.usuario ? ' como <b>' + esc(s.usuario) + '</b>' : ''}: la app puede crear playlists.</span><button type="button" class="btn chico" id="spDesc">Desconectar</button>`
    : `<span>Para crear playlists en Spotify hay que conectar tu cuenta.</span><button type="button" class="btn chico prim" id="spCon2">Conectar con Spotify</button>`;
  $('#spDesc') && ($('#spDesc').onclick = async () => { await api('/api/spotify/desconectar', {}); pintarSpotify(); });
  $('#spCon2') && ($('#spCon2').onclick = () => guiaSpotify());
  return s;
}
async function guiaSpotify(despues) {
  const s = await api('/api/spotify');
  const pasos = `<ol class="sp-pasos">
      <li>Entrá a <a href="#" data-url="https://developer.spotify.com/dashboard">developer.spotify.com/dashboard</a> con tu cuenta de Spotify y tocá <b>Create app</b>.</li>
      <li>Nombre: <code>RKB Collection Manager</code>. En <b>Redirect URI</b> pegá <code>${esc(s.redirect)}</code> y tocá <b>Add</b>. En «Which API» marcá <b>Web API</b>. Guardá.</li>
      <li>En la app que creaste, abrí <b>Settings</b>, copiá el <b>Client ID</b> y pegalo acá:</li>
    </ol>
    <label class="campo-v" style="margin-top:8px">Client ID<input id="spIdModal" value="${esc((E.config && E.config.spotify_id) || '')}" spellcheck="false"></label>
    <p class="nota">Después tocá «Conectar»: se abre el navegador, entrás a Spotify y aceptás. Se hace una sola vez.</p>`;
  modal('Conectar con Spotify', pasos, [
    { txt: 'Cancelar' },
    { txt: 'Conectar', prim: true, fn: async () => {
      const id = $('#spIdModal').value.trim();
      if (!id) { aviso('Pegá el Client ID.', true); return; }
      const d = await api('/api/config', { spotify_id: id }); E.config = d.config;
      $('#modalCuerpo').innerHTML = '<p>Se abrió el navegador: entrá a Spotify y tocá <b>Aceptar</b>. Te espero acá…</p>';
      try { await api('/api/spotify/conectar', {}); cerrarModal(); aviso('Spotify conectado.'); pintarSpotify(); if (despues) despues(); }
      catch (e) { cerrarModal(); aviso(e.message, true); }
    } },
  ]);
  $('#modalCuerpo').querySelectorAll('[data-url]').forEach((a) => { a.onclick = (e) => { e.preventDefault(); api('/api/abrir_url', { url: a.dataset.url }); }; });
}

// ---------------------------------------------------------------- ORDENAR NOMBRES DE ARCHIVO
const NM = { cambios: [], sel: new Set(), q: '' };
$('#btnNombres').onclick = async () => {
  modal('Ordenar nombres de archivo', '<p>Armando la propuesta con la metadata de cada tema…</p>', [{ txt: 'Cerrar' }]);
  $('#modal .caja').classList.add('ancha');
  try {
    NM.cambios = (await api('/api/nombres')).cambios; NM.sel = new Set(NM.cambios.map((c) => c.id)); NM.q = '';
    pintarNombres();
  } catch (e) { $('#modalCuerpo').innerHTML = `<p>${esc(e.message)}</p>`; }
};
function pintarNombres() {
  const q = sinAcentos(NM.q);
  const vis = NM.cambios.filter((c) => !q || sinAcentos(c.viejo + ' ' + c.nuevo).includes(q));
  $('#modalCuerpo').innerHTML = !NM.cambios.length ? '<p>Todos los nombres ya están prolijos. 👌</p>' : `
    <p class="nota">Formato: <b>Artista - Título (feat. Invitado) (Versión)</b>, armado con la metadata de cada tema. Se sacan «Official Video», «320», números de pista, guiones bajos, etc. Los samples no se tocan. El archivo se renombra y Rekordbox se actualiza (cues, análisis y playlists siguen igual). Se puede deshacer.</p>
    <div class="nm-cab"><input type="search" id="nmBuscar" placeholder="Buscar…" value="${esc(NM.q)}">
      <span class="nota">${NM.sel.size} de ${NM.cambios.length} marcados · <a href="#" id="nmTodos">marcar todos</a> · <a href="#" id="nmNinguno">ninguno</a></span></div>
    ${vis.slice(0, 600).map((c) => `<label class="nm-fila"><input type="checkbox" data-nm="${c.id}" ${NM.sel.has(c.id) ? 'checked' : ''}>
      <span class="v" title="${esc(c.viejo)}">${esc(c.viejo)}</span><span>→</span><span class="n" title="${esc(c.nuevo)}">${esc(c.nuevo)}</span></label>`).join('')}`;
  const acc = $('#modalAcc'); acc.innerHTML = '';
  const cerrar = document.createElement('button'); cerrar.type = 'button'; cerrar.className = 'btn'; cerrar.textContent = 'Cerrar'; cerrar.onclick = cerrarModal;
  const ok = document.createElement('button'); ok.type = 'button'; ok.className = 'btn prim';
  ok.textContent = `Renombrar ${NM.sel.size} archivos`; ok.disabled = !NM.sel.size;
  ok.onclick = async () => {
    await estado();
    if (E.rbAbierto) { aviso('Cerrá Rekordbox para renombrar (la app actualiza su base).', true); return; }
    ok.disabled = true; ok.textContent = 'Renombrando…';
    try {
      const r = await api('/api/nombres', { cambios: NM.cambios.filter((c) => NM.sel.has(c.id)).map((c) => ({ id: c.id, nuevo: c.nuevo })) });
      cerrarModal(); aviso(r.mensaje + (r.errores.length ? '\n\nNo se pudo:\n' + r.errores.join('\n') : ''), !!r.errores.length);
      await cargarColeccion();
    } catch (e) { cerrarModal(); aviso(e.message, true); }
  };
  acc.append(cerrar, ok);
  const b = $('#nmBuscar');
  if (b) { b.oninput = (e) => { NM.q = e.target.value; const pos = e.target.selectionStart; pintarNombres(); const nb = $('#nmBuscar'); nb.focus(); nb.setSelectionRange(pos, pos); }; }
  $('#nmTodos') && ($('#nmTodos').onclick = (e) => { e.preventDefault(); vis.forEach((c) => NM.sel.add(c.id)); pintarNombres(); });
  $('#nmNinguno') && ($('#nmNinguno').onclick = (e) => { e.preventDefault(); vis.forEach((c) => NM.sel.delete(c.id)); pintarNombres(); });
}
$('#modalCuerpo').addEventListener('change', (e) => {
  const id = e.target.dataset.nm; if (!id) return;
  if (e.target.checked) NM.sel.add(id); else NM.sel.delete(id);
  const ok = $('#modalAcc .btn.prim'); if (ok) { ok.textContent = `Renombrar ${NM.sel.size} archivos`; ok.disabled = !NM.sel.size; }
});

// ---------------------------------------------------------------- ACERCA DE
$('#btnAcerca').onclick = () => irA('acerca');
$('#acLicencia').onclick = async () => {
  const r = await fetch('/LICENSE.txt'); const t = r.ok ? await r.text() : 'No encontré el texto de la licencia.';
  modal('GNU General Public License v3', `<div class="licencia">${esc(t)}</div>`, [{ txt: 'Cerrar' }]);
  $('#modal .caja').classList.add('ancha');
};
$('#acFuente').onclick = async () => { try { const r = await api('/api/fuente', {}); aviso(r.mensaje); } catch (e) { aviso(e.message, true); } };


// ---------------------------------------------------------------- TAGS MANUALES (categorías 1–3 configuradas como manuales)
function pintarTagsMan() {
  const cats = (E.categorias || []).filter((c) => c.id !== '4' && c.fuente === 'manual');
  const ids = E.multi.size > 1 ? [...E.multi] : (E.sel ? [E.sel] : []);
  if (!cats.length || !ids.length) { $('#tagsMan').innerHTML = ''; return; }
  $('#tagsMan').innerHTML = cats.map((c) => `<div class="tm-cat"><b>${esc(c.nombre)}</b><div class="tm-chips">${(c.tags || []).map((n) => {
    const en = ids.filter((id) => tagsDe(E.porId[id], c.id).includes(n)).length;
    return `<button type="button" class="tm-chip${en === ids.length ? ' si' : en ? ' algo' : ''}" data-tmcat="${c.id}" data-tm="${esc(n)}">${esc(n)}</button>`;
  }).join('') || '<span class="nota">Agregá tags en la solapa My Tags.</span>'}</div></div>`).join('');
}
$('#tagsMan').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-tm]'); if (!b) return;
  const cat = b.dataset.tmcat, n = b.dataset.tm;
  const ids = E.multi.size > 1 ? [...E.multi] : [E.sel];
  const todos = ids.every((id) => tagsDe(E.porId[id], cat).includes(n));
  const items = ids.map((id) => {
    const act = new Set(tagsDe(E.porId[id], cat));
    if (todos) act.delete(n); else act.add(n);
    E.pend.tags[id] = { ...(E.pend.tags[id] || {}), [cat]: [...act] };
    return { id, tags: E.pend.tags[id] };
  });
  try { const d = await api('/api/pendiente_lote', { items }); E.pend = d.pendientes; E.pend.tags = E.pend.tags || {}; } catch (err) { aviso(err.message, true); }
  pintarTagsMan(); ids.forEach(repintarFila); pintarSync(); pintarMenu();
});

// ---------------------------------------------------------------- REPORTAR UN PROBLEMA
$('#acInforme').onclick = () => {
  modal('Reportar un problema', `<p class="nota">Contá en pocas palabras qué estabas haciendo y qué pasó. Se arma un archivo .zip en Descargas para mandar por WhatsApp o email.</p>
    <label class="campo-col">Qué pasó<textarea id="infTexto" rows="5" placeholder="Ej.: toqué Sincronizar con 20 temas y apareció un error…"></textarea></label>`, [
    { txt: 'Cancelar' },
    { txt: 'Crear informe', prim: true, fn: async () => {
      try { const r = await api('/api/informe', { texto: $('#infTexto').value }); cerrarModal(); aviso(r.mensaje); } catch (e) { aviso(e.message, true); }
    } },
  ]);
  setTimeout(() => $('#infTexto').focus(), 50);
};
