/* RKB Collection Manager · pasos 1, 2 y 3 */
'use strict';

function alEntrar(v) {
  if (v === 'descargas' && !DS.cargado) cargarDescargas();
  if (v === 'incorporar') cargarIncorporar();
}
async function seguir(id, alAvanzar) {          // sigue un trabajo de fondo hasta que termina
  let desde = 0;
  for (;;) {
    const t = await api(`/api/trabajo?id=${id}&desde=${desde}`);
    desde += t.items.length;
    alAvanzar(t);
    if (t.estado !== 'corriendo') return t;
    await new Promise((r) => setTimeout(r, 700));
  }
}
const tiempo = (s) => (s == null ? '' : s > 90 ? `falta ~${Math.round(s / 60)} min` : `falta ~${Math.round(s)} s`);

// ======================================================================= 1 · LISTA
const LS = { items: [], bajar: {}, tab: 'todos' };
$('#lsCargar').onclick = () => $('#lsArchivo').click();
$('#lsArchivo').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const texto = await f.text();
  LS.archivo = f.name;
  if (!$('#lsNombre').value) $('#lsNombre').value = f.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
  $('#lsTexto').value = texto;
  e.target.value = '';
  comparar();
};
$('#lsComparar').onclick = () => comparar();
$('#lsNueva').onclick = () => {
  LS.items = []; LS.bajar = {}; LS.tab = 'todos'; LS.archivo = '';
  $('#lsTexto').value = ''; $('#lsNombre').value = ''; $('#lsLink').value = '';
  $('#lsEvento').checked = false;
  $('#lsTabs').innerHTML = '';
  $('#lsFilas').innerHTML = '<p class="nota">Pegá o cargá una lista y tocá «Comparar con la colección».</p>';
  $('#lsPie').hidden = true;
  $('#lsLink').focus();
};
$('#lsLinkForm').onsubmit = async (e) => {
  e.preventDefault();
  const url = $('#lsLink').value.trim(); if (!url) return;
  const b = $('#lsTraer'); b.disabled = true; b.textContent = 'Leyendo la lista…';
  try {
    const r = await api('/api/lista/link', { url });
    $('#lsTexto').value = r.texto;
    if (!$('#lsNombre').value && r.nombre) $('#lsNombre').value = r.nombre;
    LS.archivo = '';
    aviso(`${r.fuente}: ${r.temas.length} temas de «${r.nombre || 'la lista'}».` + (r.completa ? '' :
      '\nPuede que falten temas: sin claves solo se leen los primeros ~100. Cargá las claves en Ajustes para traer la lista completa.'), !r.completa);
    comparar();
  } catch (err) { aviso(err.message, true); } finally { b.disabled = false; b.textContent = 'Traer la lista'; }
};
async function comparar() {
  const texto = $('#lsTexto').value;
  if (!texto.trim()) { aviso('Pegá o cargá una lista primero.'); return; }
  $('#lsFilas').innerHTML = '<p class="nota">Comparando con la colección…</p>';
  try {
    const d = await api('/api/lista/comparar', { texto, nombre: LS.archivo || '' });
    LS.items = d.items; LS.bajar = {};
    for (const it of LS.items) LS.bajar[it.n] = it.estado === 'falta' || it.estado === 'posible';
    LS.tab = 'todos'; pintarLista();
  } catch (e) { $('#lsFilas').innerHTML = `<p class="nota">${esc(e.message)}</p>`; }
}
function pintarLista() {
  const n = (e) => LS.items.filter((i) => i.estado === e).length;
  const tabs = [['todos', `Todos (${LS.items.length})`], ['falta', `Faltan (${n('falta')})`], ['posible', `Posibles duplicados (${n('posible')})`],
    ['tengo', `Ya los tengo (${n('tengo')})`], ['repetido', `Repetidos en la lista (${n('repetido')})`]];
  $('#lsTabs').innerHTML = tabs.map(([k, l]) => `<button type="button" data-lt="${k}" class="${LS.tab === k ? 'act' : ''}">${l}</button>`).join('');
  const nombres = { falta: 'Falta', posible: 'Posible dup.', tengo: 'Ya lo tengo', repetido: 'Repetido' };
  const vis = LS.items.filter((i) => LS.tab === 'todos' || i.estado === LS.tab);
  $('#lsFilas').innerHTML = vis.map((i) => `<div class="ls-fila">
    <span class="chip ${i.estado === 'posible' ? 'posible' : i.estado}">${nombres[i.estado]}</span>
    ${i.match ? `<button type="button" class="mini" data-lplay="${i.match}" title="Escuchar el de la colección">▶</button>` : '<span></span>'}
    <span>${esc(i.artista ? i.artista + ' – ' : '')}${esc(i.titulo)}</span>
    <span class="det">${esc(i.detalle)}</span>
    <button type="button" class="tg-bajar${LS.bajar[i.n] ? ' si' : ''}" data-lb="${i.n}">${LS.bajar[i.n] ? 'Bajar' : 'Quitar'}</button></div>`).join('')
    || '<p class="nota">Nada en esta categoría.</p>';
  $('#lsPie').hidden = !LS.items.length;
  const nb = LS.items.filter((i) => LS.bajar[i.n]).length;
  $('#lsGenerar').textContent = `Generar lista depurada (${nb} para bajar)`;
}
$('#lsTabs').addEventListener('click', (e) => { const b = e.target.closest('[data-lt]'); if (b) { LS.tab = b.dataset.lt; pintarLista(); } });
$('#lsFilas').addEventListener('click', (e) => {
  const b = e.target.closest('[data-lb]'); if (b) { LS.bajar[b.dataset.lb] = !LS.bajar[b.dataset.lb]; pintarLista(); return; }
  const p = e.target.closest('[data-lplay]');
  if (p) { const t = E.porId[p.dataset.lplay]; if (t) { if (!audio.paused && audio.dataset.id === t.id) audio.pause(); else { tocar(t); audio.dataset.id = t.id; } } }
});
$('#lsGenerar').onclick = async () => {
  const nombre = $('#lsNombre').value.trim() || 'Lista';
  const filas = LS.items.filter((i) => LS.bajar[i.n]).map((i) => ({ artista: i.artista, titulo: i.titulo }));
  try {
    const r = await api('/api/lista/txt', { nombre, filas, links: $('#lsLinks').checked });
    let msg = r.mensaje;
    if ($('#lsEvento').checked) {
      await estado();
      if (E.rbAbierto) msg += '\n\nNo creé la playlist porque Rekordbox está abierto: cerralo y volvé a tocar el botón.';
      else {
        const ids = LS.items.filter((i) => i.match && (i.estado === 'tengo' || (i.estado === 'posible' && !LS.bajar[i.n]))).map((i) => i.match);
        const ev = await api('/api/lista/evento', { nombre, ids });
        msg += '\n' + ev.mensaje + ' Cuando incorpores los que faltan, se suman a esa misma playlist.';
      }
    }
    modal('Lista depurada', `<p>${esc(msg).replace(/\n/g, '<br>')}</p>`, [
      { txt: 'Cerrar' },
      { txt: 'Abrir el txt', fn: () => api('/api/abrir', { ruta: r.ruta }) },
      { txt: 'Mostrar en la carpeta', fn: () => api('/api/abrir', { ruta: r.ruta, mostrar: true }) },
      { txt: 'Seguir con Descargas', prim: true, fn: () => { cerrarModal(); DS.cargado = false; irA('descargas'); } },
    ]);
  } catch (e) { aviso(e.message, true); }
};

// ======================================================================= 2 · DESCARGAS
const DS = { cargado: false, archivos: [], sel: new Set(), res: {}, abiertos: new Set(), trabajo: null };
async function cargarDescargas() {
  $('#dsFilas').innerHTML = '<p class="nota" style="padding:14px">Buscando temas…</p>';
  try {
    const d = await api('/api/descargas');
    DS.cargado = true; DS.d = d; DS.archivos = d.archivos; DS.sel = new Set(d.archivos.map((a) => a.ruta)); DS.res = {};
    $('#dsCarpeta').textContent = `Carpeta: ${d.carpeta} · ${d.archivos.length} temas`;
    $('#dsCampos').innerHTML = Object.entries(d.nombresCampos).map(([k, l]) =>
      `<label><input type="checkbox" data-campo="${k}" ${d.campos[k] ? 'checked' : ''}>${esc(l)}</label>`).join('');
    $('#dsFuentes').innerHTML = Object.entries(d.nombresFuentes).map(([k, l]) => {
      const falta = (k === 'lastfm' || k === 'discogs') && !d.claves[k];
      return `<label><input type="checkbox" data-fuente="${k}" ${d.fuentes[k] && !falta ? 'checked' : ''} ${falta ? 'disabled' : ''}>${esc(l)}${falta ? '<small>falta clave (Ajustes)</small>' : ''}</label>`;
    }).join('');
    pintarDescargas();
  } catch (e) { $('#dsFilas').innerHTML = `<p class="nota" style="padding:14px">${esc(e.message)}</p>`; }
}
function resumenMeta(m) {
  return [m.genero && (m.genero + (m.grouping ? ' · ' + m.grouping : '')), m.anio, m.album, m.pais, m.idioma].filter(Boolean).map(esc).join(' · ') || '—';
}
function pintarDescargas() {
  const filas = DS.archivos.map((a) => {
    const r = DS.res[a.ruta];
    if (!r) {
      return `<div class="ds-fila"><input type="checkbox" data-dsel="${esc(a.ruta)}" ${DS.sel.has(a.ruta) ? 'checked' : ''}>
        <span><span class="nom">${esc(a.archivo)}</span><span class="sub2">${esc(a.carpeta && a.carpeta !== '.' ? a.carpeta + ' · ' : '')}${a.mb} MB</span></span>
        <span class="meta-txt">${DS.trabajo && DS.sel.has(a.ruta) ? 'En espera…' : ''}</span><span></span><span></span></div>`;
    }
    const m = r.meta || {};
    const abierto = DS.abiertos.has(a.ruta);
    return `<div class="ds-fila"><span></span>
      <span><span class="nom" title="${esc(r.archivo)}">${esc(r.nuevoNombre || r.archivo)}</span><span class="sub2">antes: ${esc(r.archivo)}</span></span>
      <span class="meta-txt">${resumenMeta(m)}${(r.notas || []).map((n) => `<span class="notas">${esc(n)}</span>`).join('')}
        <button type="button" class="editar" data-dedit="${esc(a.ruta)}">${abierto ? 'Cerrar' : 'Editar datos'}</button></span>
      <span><span class="cal ${r.calidad || ''}">${esc(r.calidad === 'SIN ANALIZAR' ? '—' : (r.calidad || '—'))}</span><span class="sub2">${r.corte ? r.corte + ' kHz' : ''}${r.bitrate ? ' · ' + r.bitrate + ' kbps' : ''}</span></span>
      <button type="button" class="accion${r.accion === 'eliminar' ? ' eliminar' : ''}" data-dacc="${esc(a.ruta)}">${r.accion === 'eliminar' ? 'Eliminar' : 'Conservar'}</button>
      ${abierto ? `<div class="ds-edit">${[['artista', 'Artista'], ['titulo', 'Título'], ['genero', 'Género'], ['grouping', 'Grouping'], ['anio', 'Año'], ['album', 'Álbum'], ['pais', 'País'], ['idioma', 'Idioma']].map(([k, l]) =>
        `<label>${l}<input data-dm="${k}" data-dr="${esc(a.ruta)}" value="${esc(m[k] || '')}" ${['genero', 'grouping', 'pais', 'idioma'].includes(k) ? `data-dl="dl-${k}"` : ''}></label>`).join('')}</div>` : ''}
    </div>`;
  }).join('');
  const hay = Object.keys(DS.res).length;
  $('#dsFilas').innerHTML = DS.archivos.length ? `<div class="ds-fila enc"><input type="checkbox" id="dsTodos" ${DS.sel.size === DS.archivos.length ? 'checked' : ''} ${hay ? 'style="visibility:hidden"' : ''}><span>Tema</span><span>Metadata encontrada</span><span>Calidad</span><span>Acción</span></div>${filas}`
    : '<p class="nota" style="padding:14px">No hay temas de audio en esta carpeta.</p>';
  $('#dsAnalizar').textContent = `Analizar ${DS.sel.size} tema${DS.sel.size === 1 ? '' : 's'}`;
  $('#dsAnalizar').disabled = !DS.sel.size || !!DS.trabajo;
  const res = Object.values(DS.res);
  $('#dsPie').hidden = !res.length || !!DS.trabajo;
  const nc = res.filter((r) => r.accion !== 'eliminar').length, ne = res.length - nc;
  $('#dsPieTxt').textContent = `${nc} para incorporar${ne ? ` · ${ne} a _descartados (no se borran del todo)` : ''}. Se escribe la metadata (con backup de cada archivo) y se renombran.`;
  $('#dsGuardar').textContent = `Guardar y preparar ${nc} tema${nc === 1 ? '' : 's'}`;
}
$('#dsFilas').addEventListener('change', (e) => {
  const el = e.target;
  if (el.id === 'dsTodos') { DS.sel = el.checked ? new Set(DS.archivos.map((a) => a.ruta)) : new Set(); pintarDescargas(); return; }
  if (el.dataset.dsel) { if (el.checked) DS.sel.add(el.dataset.dsel); else DS.sel.delete(el.dataset.dsel); pintarDescargas(); return; }
  if (el.dataset.dm) {
    const r = DS.res[el.dataset.dr]; r.meta = { ...(r.meta || {}), [el.dataset.dm]: el.value.trim() };
    if (el.dataset.dm === 'artista' || el.dataset.dm === 'titulo') {
      const ext = r.archivo.slice(r.archivo.lastIndexOf('.'));
      if (r.nuevoNombre !== r.archivo) r.nuevoNombre = `${r.meta.artista ? r.meta.artista + ' - ' : ''}${r.meta.titulo}${ext}`.replace(/[/\\:*?"<>|]+/g, ' ');
    }
    pintarDescargas();
  }
});
$('#dsFilas').addEventListener('click', (e) => {
  const a = e.target.closest('[data-dacc]');
  if (a) { const r = DS.res[a.dataset.dacc]; r.accion = r.accion === 'eliminar' ? 'conservar' : 'eliminar'; pintarDescargas(); return; }
  const ed = e.target.closest('[data-dedit]');
  if (ed) { const k = ed.dataset.dedit; if (DS.abiertos.has(k)) DS.abiertos.delete(k); else DS.abiertos.add(k); pintarDescargas(); }
});
$('#dsActualizar').onclick = () => { if (!DS.trabajo) cargarDescargas(); };
$('#dsCambiar').onclick = async () => {
  const { ruta } = await api('/api/elegir_carpeta', { titulo: 'Carpeta de temas a incorporar' });
  if (ruta) { await api('/api/config', { incorporar: ruta }); cargarDescargas(); }
};
$('#dsAnalizar').onclick = async () => {
  const campos = {}, fuentes = {};
  document.querySelectorAll('#dsCampos input').forEach((i) => { campos[i.dataset.campo] = i.checked; });
  document.querySelectorAll('#dsFuentes input').forEach((i) => { fuentes[i.dataset.fuente] = i.checked; });
  const rutas = DS.archivos.map((a) => a.ruta).filter((r) => DS.sel.has(r));
  DS.res = {}; DS.archivos = DS.archivos.filter((a) => DS.sel.has(a.ruta));
  try {
    const { trabajo } = await api('/api/descargas/analizar', { rutas, campos, fuentes });
    DS.trabajo = trabajo; $('#dsProg').hidden = false; pintarDescargas();
    const fin = await seguir(trabajo, (t) => {
      for (const it of t.items) DS.res[it.ruta] = it;
      $('#dsProgIn').style.width = (t.total ? 100 * t.hechos / t.total : 0) + '%';
      $('#dsProgTxt').textContent = `${t.hechos} de ${t.total} · ${tiempo(t.resta)}`;
      if (t.items.length) pintarDescargas();
    });
    if (fin.estado === 'error') aviso('Falló el análisis: ' + fin.error, true);
  } catch (e) { aviso(e.message, true); }
  DS.trabajo = null; $('#dsProg').hidden = true; pintarDescargas();
};
$('#dsCancelar').onclick = () => DS.trabajo && api('/api/trabajo/cancelar', { id: DS.trabajo });
$('#dsGuardar').onclick = async () => {
  const items = Object.values(DS.res);
  $('#dsGuardar').disabled = true;
  try {
    const r = await api('/api/descargas/aplicar', { items });
    aviso(r.mensaje + (r.errores.length ? '\n\nProblemas:\n' + r.errores.join('\n') : ''), !!r.errores.length);
    DS.cargado = false; DS.res = {};
    irA('incorporar');
  } catch (e) { aviso(e.message, true); } finally { $('#dsGuardar').disabled = false; }
};

// ======================================================================= 3 · INCORPORAR
const IN = { d: null, sel: new Set() };
async function cargarIncorporar() {
  $('#inFilas').innerHTML = '<p class="nota">Cargando…</p>';
  try {
    const d = await api('/api/incorporar');
    IN.d = d; IN.sel = new Set(d.preparados.map((p) => p.ruta));
    $('#inSub').textContent = `Mueve los temas preparados a ${d.coleccion} y los agrega a Rekordbox.`;
    const ops = (sel) => `<option value="">(ninguna)</option>` + d.playlists.map((p) => `<option value="${p.id}" ${p.id === sel ? 'selected' : ''}>${esc(p.nombre)}</option>`).join('');
    $('#inPlaylist').innerHTML = ops(d.evento ? d.evento.id : '');
    $('#chPlaylist').innerHTML = ops(d.evento ? d.evento.id : '');
    pintarIncorporar(); pintarChequeo(d.chequeo);
  } catch (e) { $('#inFilas').innerHTML = `<p class="nota">${esc(e.message)}</p>`; }
}
function pintarIncorporar() {
  const p = IN.d.preparados;
  $('#inTit').textContent = `Temas preparados (${p.length})`;
  $('#inFilas').innerHTML = p.length ? p.map((x) => `<div class="in-fila${IN.sonando === x.ruta ? ' sonando' : ''}"><input type="checkbox" data-isel="${esc(x.ruta)}" ${IN.sel.has(x.ruta) ? 'checked' : ''} aria-label="Incorporar">
    <button type="button" class="mini" data-iplay="${esc(x.ruta)}" title="Escuchar">${IN.sonando === x.ruta && !audio.paused ? '❚❚' : '▶'}</button>
    <span>${esc(x.ruta.split('/').pop())}<small>${resumenMeta(x.meta || {})}</small></span>
    <span class="cal ${x.calidad || ''}">${esc(x.calidad && x.calidad !== 'SIN ANALIZAR' ? x.calidad : '—')}</span>
    <button type="button" class="in-quitar" data-iquitar="${esc(x.ruta)}" title="Quitar de la lista">×</button></div>`).join('')
    : '<p class="nota">No hay temas preparados. Pasalos primero por la solapa Descargas.</p>';
  $('#inIncorporar').textContent = `Incorporar ${IN.sel.size} tema${IN.sel.size === 1 ? '' : 's'}`;
  $('#inIncorporar').disabled = !IN.sel.size;
}
$('#inFilas').addEventListener('change', (e) => {
  const r = e.target.dataset.isel; if (!r) return;
  if (e.target.checked) IN.sel.add(r); else IN.sel.delete(r); pintarIncorporar();
});
$('#inIncorporar').onclick = async () => {
  await estado();
  if (E.rbAbierto) { aviso('Cerrá Rekordbox para incorporar (la app agrega los temas a su base).', true); return; }
  const pl = $('#inPlaylist').value;
  const nombre = pl ? $('#inPlaylist').selectedOptions[0].textContent : '';
  modal('Incorporar', `<p>Se van a mover <b>${IN.sel.size}</b> temas a la colección y agregar a Rekordbox${pl ? `, dentro de la playlist <b>${esc(nombre)}</b>` : ''}.${$('#inFecha').checked ? ' También quedan en una playlist nueva con la fecha de hoy, dentro de la carpeta <b>Importaciones</b>.' : ''}</p><p class="nota">Antes se hace un backup de la base. Se puede deshacer desde Ajustes e historial.</p>`, [
    { txt: 'Cancelar' },
    { txt: 'Incorporar', prim: true, fn: async () => {
      try {
        const r = await api('/api/incorporar', { rutas: [...IN.sel], playlist: pl || null, playlistFecha: $('#inFecha').checked });
        cerrarModal(); aviso(r.mensaje + (r.errores.length ? '\n\nProblemas:\n' + r.errores.join('\n') : ''), !!r.errores.length);
        await cargarIncorporar(); cargarColeccion();
      } catch (e) { cerrarModal(); aviso(e.message, true); }
    } },
  ]);
};
$('#chPlaylist').onchange = async (e) => {
  const pid = e.target.value;
  if (!pid) { pintarChequeo(null); return; }
  $('#chRes').innerHTML = '<p class="nota">Revisando…</p>';
  const { chequeo } = await api('/api/chequeo?playlist=' + encodeURIComponent(pid));
  pintarChequeo(chequeo);
};
function pintarChequeo(c) {
  IN.ch = c;
  if (!c) { $('#chRes').innerHTML = '<p class="nota">Elegí la playlist del evento para revisarla antes de exportar al USB.</p>'; return; }
  const mal = c.temas.filter((t) => !t.existe || !t.analizado || (t.calidad && t.calidad !== 'OK'));
  $('#chRes').innerHTML = `<div class="ch-res">
      <span class="chip ${c.perdidos ? 'falta' : 'tengo'}">${c.perdidos} archivos perdidos</span>
      <span class="chip ${c.sinAnalizar ? 'posible' : 'tengo'}">${c.sinAnalizar} sin analizar</span>
      <span class="chip">${c.temas.length} temas</span>
      ${c.calidad ? `<span class="chip ${c.calidad.malos ? 'falta' : c.calidad.dudosos ? 'posible' : 'tengo'}">calidad: ${c.calidad.malos} malos · ${c.calidad.dudosos} dudosos</span>` : ''}
    </div>
    ${mal.length ? mal.map((t) => `<div class="ch-fila"><span>${esc(t.tema)}</span><span>${!t.existe ? 'Archivo perdido' : !t.analizado ? 'Sin analizar' : ''}</span><span>${t.calidad && t.calidad !== 'OK' ? `<span class="cal ${t.calidad}">${t.calidad}</span>` : ''}</span></div>`).join('')
      : '<p class="nota">Todo en orden para exportar.</p>'}
    <div class="acciones fin"><button type="button" class="btn chico" id="chCalidad">${c.calidad ? 'Volver a analizar calidad' : 'Analizar calidad de los temas'}</button></div>`;
  $('#chCalidad').onclick = async () => {
    const rutas = c.temas.filter((t) => t.existe).map((t) => t.ruta);
    $('#chCalidad').disabled = true;
    try {
      const { trabajo } = await api('/api/calidad', { rutas });
      const porRuta = {};
      await seguir(trabajo, (t) => { for (const it of t.items) porRuta[it.ruta] = it; $('#chCalidad').textContent = `Analizando ${t.hechos} de ${t.total}…`; });
      for (const t of c.temas) if (porRuta[t.ruta]) t.calidad = porRuta[t.ruta].calidad;
      c.calidad = { malos: c.temas.filter((t) => t.calidad === 'MALO').length, dudosos: c.temas.filter((t) => t.calidad === 'DUDOSO').length };
      pintarChequeo(c);
    } catch (e) { aviso(e.message, true); }
  };
}

// ---------------------------------------------------------------- crear playlist en Spotify
$('#lsSpotify').onclick = async () => {
  if (!LS.items.length) { aviso('Primero cargá y compará una lista.'); return; }
  const s = await api('/api/spotify');
  if (!s.conectado) { guiaSpotify(() => $('#lsSpotify').click()); return; }
  const n = (e) => LS.items.filter((i) => i.estado === e).length;
  const nombre = $('#lsNombre').value.trim() || 'Lista';
  modal('Crear playlist en Spotify', `
    <label class="campo-v">Nombre de la playlist<input id="spNombre" value="${esc(nombre)}"></label>
    <div class="ls-opc" style="margin-top:6px">
      <label><input type="radio" name="spQue" value="todos" checked> Toda la lista (${LS.items.filter((i) => i.estado !== 'repetido').length} temas)</label>
      <label><input type="radio" name="spQue" value="bajar"> Solo los que marcaste «Bajar» (${LS.items.filter((i) => LS.bajar[i.n]).length})</label>
      <label><input type="radio" name="spQue" value="tengo"> Solo los que ya tenés (${n('tengo')})</label>
      <label style="margin-top:6px"><input type="checkbox" id="spPublica"> Pública (si no, queda privada en tu cuenta)</label>
    </div>
    <p class="nota">Spotify busca cada tema por artista y título. Los que no encuentre te los muestro al final.</p>`, [
    { txt: 'Cancelar' },
    { txt: 'Crear', prim: true, fn: async () => {
      const que = document.querySelector('input[name="spQue"]:checked').value;
      const sel = LS.items.filter((i) => (que === 'todos' ? i.estado !== 'repetido' : que === 'bajar' ? LS.bajar[i.n] : i.estado === 'tengo'));
      const temas = sel.map((i) => ({ artista: i.artista, titulo: i.titulo }));
      const nom = $('#spNombre').value.trim() || nombre, publica = $('#spPublica').checked;
      try {
        const { trabajo } = await api('/api/spotify/playlist', { nombre: nom, temas, publica });
        $('#modalAcc').innerHTML = '';
        const fin = await seguir(trabajo, (t) => { $('#modalCuerpo').innerHTML = `<p>Buscando en Spotify: ${t.hechos} de ${t.total}…</p>`; });
        if (fin.estado === 'error') throw new Error(fin.error.replace(/^\w+: /, ''));
        const r = fin.resultado;
        modal('Playlist creada', `<p>«${esc(nom)}» quedó en tu Spotify con <b>${r.agregados}</b> temas.</p>${r.noEncontrados.length
          ? `<p class="nota">No encontré ${r.noEncontrados.length}:</p><ul class="nota">${r.noEncontrados.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}`, [
          { txt: 'Cerrar' }, { txt: 'Abrir en Spotify', prim: true, fn: () => api('/api/abrir_url', { url: r.url }) },
        ]);
      } catch (e) { cerrarModal(); aviso(e.message, true); }
    } },
  ]);
};

// ---------------------------------------------------------------- reproductor y quitar en Incorporar
function tocarRuta(ruta) {
  audio.src = '/audio?ruta=' + encodeURIComponent(ruta);
  audio.dataset.id = '';
  const modo = (E.config && E.config.inicio) || '30', seg = Number((E.config && E.config.inicio_seg) || 0);
  audio.onloadedmetadata = () => {
    const d = audio.duration || 0;
    let s = modo === 'seg' ? Math.min(seg, Math.max(0, d - 5)) : modo === 'inicio' ? 0 : d * 0.3;
    try { audio.currentTime = s; } catch (_) { /* nada */ }
  };
  audio.play().catch(() => {});
}
$('#inFilas').addEventListener('click', (e) => {
  const p = e.target.closest('[data-iplay]');
  if (p) {
    const r = p.dataset.iplay;
    if (IN.sonando === r && !audio.paused) audio.pause();
    else if (IN.sonando === r) audio.play();
    else { IN.sonando = r; tocarRuta(r); }
    $('#inPlayer').hidden = false; $('#inAhora').textContent = r.split('/').pop();
    pintarIncorporar();
    return;
  }
  const q = e.target.closest('[data-iquitar]');
  if (q) {
    const r = q.dataset.iquitar, nombre = r.split('/').pop();
    modal('Quitar tema', `<p>¿Qué hago con <b>${esc(nombre)}</b>?</p>`, [
      { txt: 'Cancelar' },
      { txt: 'Solo sacarlo de la lista', fn: () => quitarPreparado(r, false) },
      { txt: 'Eliminarlo (a _descartados)', prim: true, fn: () => quitarPreparado(r, true) },
    ]);
  }
});
async function quitarPreparado(ruta, eliminar) {
  if (IN.sonando === ruta) { audio.pause(); IN.sonando = null; $('#inPlayer').hidden = true; }
  try {
    const r = await api('/api/incorporar/quitar', { ruta, eliminar });
    cerrarModal(); aviso(r.mensaje);
    IN.d.preparados = IN.d.preparados.filter((p) => p.ruta !== ruta); IN.sel.delete(ruta); pintarIncorporar();
  } catch (e) { cerrarModal(); aviso(e.message, true); }
}
$('#inPlay').onclick = () => { if (audio.paused) audio.play(); else audio.pause(); };
$('#inBarra').addEventListener('click', (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  if (audio.duration) audio.currentTime = audio.duration * (e.clientX - r.left) / r.width;
});
audio.addEventListener('timeupdate', () => {
  if (!IN.sonando || E.vista !== 'incorporar') return;
  const d = audio.duration || 0;
  $('#inBarraIn').style.width = d ? (100 * audio.currentTime / d) + '%' : '0';
  $('#inTiempo').textContent = `${fmt(audio.currentTime)} / ${fmt(d)}`;
});
['play', 'pause'].forEach((ev) => audio.addEventListener(ev, () => {
  $('#inPlay').textContent = audio.paused ? '▶' : '❚❚';
  if (IN.sonando && E.vista === 'incorporar') {
    document.querySelectorAll('[data-iplay]').forEach((b) => { b.textContent = b.dataset.iplay === IN.sonando && !audio.paused ? '❚❚' : '▶'; });
  }
}));
