/* RKB Collection Manager · versión obligatoria, Cartelera y Mis anuncios */
'use strict';
const urlCss = (u) => esc(encodeURI(String(u || ''))).replace(/'/g, '%27').replace(/\\/g, '%5C');

const CT = { activo: false, nuevos: 0, anuncios: [], tipo: 'Todos', ubic: { pais: '', region: '' }, nov: null };
const MA = { quien: null, anuncios: [], email: '', pend: [] };
const TIPOS = ['Evento', 'Curso o taller', 'Equipos', 'Busco DJ', 'Otro'];
const ALCANCES = [['region', 'Sólo en mi provincia / estado'], ['pais', 'En todo el país'], ['mundo', 'En todo el mundo']];

// ---------------------------------------------------------------- países y regiones
const PAISES = ('AR UY CL PY BO PE EC CO VE MX US CA ES PT IT FR DE GB IE NL BE CH AT SE NO DK FI PL CZ GR TR IL AE BR CR PA GT HN SV NI DO PR CU ' +
  'AU NZ JP KR CN IN ZA MA EG NG SG TH PH ID MY RU UA RO HU HR RS').split(' ');
const REGIONES = {
  AR: ['Buenos Aires (provincia)', 'Ciudad de Buenos Aires', 'Catamarca', 'Chaco', 'Chubut', 'Córdoba', 'Corrientes', 'Entre Ríos', 'Formosa', 'Jujuy', 'La Pampa', 'La Rioja', 'Mendoza', 'Misiones', 'Neuquén', 'Río Negro', 'Salta', 'San Juan', 'San Luis', 'Santa Cruz', 'Santa Fe', 'Santiago del Estero', 'Tierra del Fuego', 'Tucumán'],
  UY: ['Artigas', 'Canelones', 'Cerro Largo', 'Colonia', 'Durazno', 'Flores', 'Florida', 'Lavalleja', 'Maldonado', 'Montevideo', 'Paysandú', 'Río Negro', 'Rivera', 'Rocha', 'Salto', 'San José', 'Soriano', 'Tacuarembó', 'Treinta y Tres'],
  CL: ['Arica y Parinacota', 'Tarapacá', 'Antofagasta', 'Atacama', 'Coquimbo', 'Valparaíso', 'Metropolitana de Santiago', "O'Higgins", 'Maule', 'Ñuble', 'Biobío', 'La Araucanía', 'Los Ríos', 'Los Lagos', 'Aysén', 'Magallanes'],
  MX: ['Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche', 'Chiapas', 'Chihuahua', 'Ciudad de México', 'Coahuila', 'Colima', 'Durango', 'Estado de México', 'Guanajuato', 'Guerrero', 'Hidalgo', 'Jalisco', 'Michoacán', 'Morelos', 'Nayarit', 'Nuevo León', 'Oaxaca', 'Puebla', 'Querétaro', 'Quintana Roo', 'San Luis Potosí', 'Sinaloa', 'Sonora', 'Tabasco', 'Tamaulipas', 'Tlaxcala', 'Veracruz', 'Yucatán', 'Zacatecas'],
  ES: ['Andalucía', 'Aragón', 'Asturias', 'Islas Baleares', 'Canarias', 'Cantabria', 'Castilla-La Mancha', 'Castilla y León', 'Cataluña', 'Comunidad Valenciana', 'Extremadura', 'Galicia', 'La Rioja', 'Comunidad de Madrid', 'Región de Murcia', 'Navarra', 'País Vasco', 'Ceuta', 'Melilla'],
  US: ['Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware', 'District of Columbia', 'Florida', 'Georgia', 'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts', 'Michigan', 'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey', 'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington', 'West Virginia', 'Wisconsin', 'Wyoming'],
  CO: ['Amazonas', 'Antioquia', 'Arauca', 'Atlántico', 'Bogotá D.C.', 'Bolívar', 'Boyacá', 'Caldas', 'Caquetá', 'Casanare', 'Cauca', 'Cesar', 'Chocó', 'Córdoba', 'Cundinamarca', 'Guainía', 'Guaviare', 'Huila', 'La Guajira', 'Magdalena', 'Meta', 'Nariño', 'Norte de Santander', 'Putumayo', 'Quindío', 'Risaralda', 'San Andrés y Providencia', 'Santander', 'Sucre', 'Tolima', 'Valle del Cauca', 'Vaupés', 'Vichada'],
  BR: ['Acre', 'Alagoas', 'Amapá', 'Amazonas', 'Bahia', 'Ceará', 'Distrito Federal', 'Espírito Santo', 'Goiás', 'Maranhão', 'Mato Grosso', 'Mato Grosso do Sul', 'Minas Gerais', 'Pará', 'Paraíba', 'Paraná', 'Pernambuco', 'Piauí', 'Rio de Janeiro', 'Rio Grande do Norte', 'Rio Grande do Sul', 'Rondônia', 'Roraima', 'Santa Catarina', 'São Paulo', 'Sergipe', 'Tocantins'],
};
let nombresPais;
try { nombresPais = new Intl.DisplayNames(['es'], { type: 'region' }); } catch (_) { nombresPais = null; }
const nombrePais = (c) => { try { return (nombresPais && nombresPais.of(c)) || c; } catch (_) { return c; } };
const paisesOrdenados = () => PAISES.map((c) => [c, nombrePais(c)]).sort((a, b) => a[1].localeCompare(b[1], 'es'));
const optsPais = (sel) => '<option value="">Elegí…</option>' + paisesOrdenados().map(([c, n]) => `<option value="${c}" ${c === sel ? 'selected' : ''}>${esc(n)}</option>`).join('');
function campoRegion(id, pais, valor) {
  const lista = REGIONES[pais];
  if (lista) return `<select id="${id}"><option value="">Elegí…</option>${lista.map((r) => `<option ${r === valor ? 'selected' : ''}>${esc(r)}</option>`).join('')}</select>`;
  return `<input id="${id}" value="${esc(valor || '')}" placeholder="Provincia, estado o región">`;
}
const ubicTxt = (u) => (u && u.pais ? `${u.region ? u.region + ', ' : ''}${nombrePais(u.pais)}` : '');
const fechaCorta = (f, h) => {
  try {
    const d = new Date(f + 'T12:00:00');
    return d.toLocaleDateString('es-AR', { weekday: 'short', day: 'numeric', month: 'short' }) + (h ? ` · ${h} h` : '');
  } catch (_) { return f; }
};

// ---------------------------------------------------------------- al abrir la app: versión y novedades
async function chequearNovedades() {
  if (!E.config || !E.config.acepto_riesgo || !$('#modal').hidden) { setTimeout(chequearNovedades, 1500); return; }
  let d;
  try { d = await api('/api/novedades'); } catch (_) { return; }
  CT.nov = d; CT.activo = !!d.activo; CT.nuevos = d.nuevos || 0;
  if (d.ubicacion) CT.ubic = d.ubicacion;
  pintarMenu();
  if (d.auto === 'buscando' && (CT.esperas = (CT.esperas || 0) + 1) < 20) { setTimeout(chequearNovedades, 3000); return; }
  if (d.bloqueo) { bloquearPorVersion(d); return; }       // sin internet no llega acá: nunca se bloquea offline
  if (d.hayNueva && d.auto !== 'lista') {
    let visto = '';
    try { visto = localStorage.getItem('rkb_version_avisada') || ''; } catch (_) { /* nada */ }
    if (d.diasGracia != null || visto !== d.ultima) {
      avisoVersion(d);
      try { localStorage.setItem('rkb_version_avisada', d.ultima); } catch (_) { /* nada */ }
      return;
    }
  }
  if (CT.nuevos && d.mostrarAlInicio) toastCartelera();
}
function bloquearPorVersion(d) {
  audio.pause();
  const b = document.createElement('div');
  b.className = 'bloqueo';
  if (d.auto === 'lista') {
    b.innerHTML = `<div class="caja"><h2>Falta un paso para actualizar</h2><p>La versión <b>${esc(d.ultima)}</b> ya se bajó. Cerrá la app y volvé a abrirla para empezar a usarla.</p><p class="nota">Tu colección, tus ajustes y tus backups no se tocan.</p>
      <div class="acciones"><button type="button" class="btn prim" id="blSalir">Cerrar la app</button></div></div>`;
    document.body.appendChild(b);
    b.querySelector('#blSalir').onclick = salir;
    return;
  }
  b.innerHTML = `<div class="caja"><h2>Hay que actualizar la app</h2><p>Esta versión (${esc(d.actual)}) ya no se puede usar: hace falta la <b>${esc(d.ultima)}</b> o más nueva.</p>${d.mensaje ? `<p class="nota">${esc(d.mensaje)}</p>` : ''}<p class="nota">Bajala, reemplazá la app y volvé a abrirla. Tu colección, tus ajustes y tus backups no se tocan.</p>
    <div class="acciones"><button type="button" class="btn" id="blSalir">Cerrar la app</button><button type="button" class="btn prim" id="blBajar">Descargar la nueva versión</button></div></div>`;
  document.body.appendChild(b);
  b.querySelector('#blSalir').onclick = salir;
  b.querySelector('#blBajar').onclick = () => api('/api/abrir_descarga', {});
}
function avisoVersion(d) {
  const urgente = d.diasGracia != null;
  modal('Hay una versión nueva', `<p>Ya está la versión <b>${esc(d.ultima)}</b> (tenés la ${esc(d.actual)}).</p>${d.mensaje ? `<p class="nota">${esc(d.mensaje)}</p>` : ''}${urgente ? `<p><b>Es obligatoria:</b> ${d.diasGracia ? `en ${d.diasGracia} ${d.diasGracia === 1 ? 'día' : 'días'} esta versión deja de funcionar.` : 'a partir de mañana esta versión deja de funcionar.'}</p>` : ''}`, [
    { txt: 'Más tarde', fn: () => { cerrarModal(); if (CT.nuevos && d.mostrarAlInicio) toastCartelera(); } },
    { txt: 'Descargar', prim: true, fn: () => api('/api/abrir_descarga', {}) },
  ]);
}
function toastCartelera() {
  const t = $('#ctToast');
  t.innerHTML = `<div><b>${CT.nuevos === 1 ? 'Hay 1 anuncio nuevo' : `Hay ${CT.nuevos} anuncios nuevos`}</b><small>en la Cartelera${CT.ubic.pais ? ' de ' + esc(ubicTxt(CT.ubic)) : ''}</small></div><button type="button" class="btn chico prim" id="ctVer">Ver</button><button type="button" class="ct-x" id="ctCerrar" aria-label="Cerrar">×</button>`;
  t.hidden = false;
  $('#ctVer').onclick = () => { t.hidden = true; irA('cartelera'); };
  $('#ctCerrar').onclick = () => { t.hidden = true; };
  setTimeout(() => { t.hidden = true; }, 15000);
}
setTimeout(chequearNovedades, 1200);

async function chequearActualizacion() {
  let d;
  try { d = await api('/api/actualizacion'); } catch (_) { return; }
  if (d.buscando) { setTimeout(chequearActualizacion, 3000); return; }
  if (!d.lista) return;
  const t = $('#actToast');
  t.innerHTML = `<div><b>Actualización lista: versión ${esc(d.lista)}</b><small>Se instala sola la próxima vez que abras la app. Cuando puedas, cerrala y volvé a abrirla.</small></div><button type="button" class="ct-x" id="actCerrar" aria-label="Cerrar">×</button>`;
  t.hidden = false;
  $('#actCerrar').onclick = () => { t.hidden = true; };
  setTimeout(() => { t.hidden = true; }, 20000);
}
setTimeout(chequearActualizacion, 3000);

// ---------------------------------------------------------------- CARTELERA
async function pintarCartelera(forzar) {
  $('#ctInicio').checked = !E.config || E.config.cartelera_inicio !== false;
  $('#ctLista').innerHTML = '<p class="nota">Cargando…</p>';
  let d;
  try { d = await api('/api/cartelera' + (forzar ? '?forzar=1' : '')); } catch (e) { $('#ctLista').innerHTML = `<p class="nota">${esc(e.message)}</p>`; return; }
  CT.anuncios = d.anuncios || []; if (d.ubicacion) CT.ubic = d.ubicacion;
  $('#ctUbic').textContent = CT.ubic.pais ? `📍 ${ubicTxt(CT.ubic)}` : '📍 Elegí tu zona';
  $('#ctTipos').innerHTML = ['Todos', ...TIPOS].map((t) => {
    const n = t === 'Todos' ? CT.anuncios.length : CT.anuncios.filter((a) => a.tipo === t).length;
    return `<button type="button" data-tipo="${esc(t)}" class="${CT.tipo === t ? 'act' : ''}">${esc(t)} · ${n}</button>`;
  }).join('');
  if (!CT.ubic.pais) {
    $('#ctLista').innerHTML = `<div class="panel ct-vacio"><h2>¿Dónde tocás?</h2><p class="nota">Elegí tu país y tu provincia o estado para ver los anuncios de tu zona. Mientras tanto sólo ves los que son para todo el mundo.</p><div class="acciones"><button type="button" class="btn prim" id="ctElegir">Elegir mi zona</button></div></div>` + tarjetas();
    $('#ctElegir').onclick = elegirUbicacion;
  } else {
    $('#ctLista').innerHTML = tarjetas() || `<div class="panel ct-vacio"><h2>Todavía no hay anuncios en tu zona</h2><p class="nota">¿Tenés un evento, un curso o equipos para vender? Publicalo y lo ven todos los DJs de ${esc(ubicTxt(CT.ubic))} que usan la app.</p></div>`;
  }
  if (d.error) aviso(d.error, true);
  const ids = CT.anuncios.map((a) => a.id);
  if (ids.length) { api('/api/cartelera/vistos', { ids }).catch(() => {}); CT.nuevos = 0; pintarMenu(); }
}
function tarjeta(a, extra) {
  return `<article class="ct-card${a.destacado ? ' dest' : ''}">
    ${a.imagen ? `<div class="ct-img" style="background-image:url('${urlCss(a.imagen)}')"></div>` : `<div class="ct-img vacia"><span>${esc(a.tipo || '')}</span></div>`}
    <div class="ct-info">
      <div class="ct-chips"><span class="chip">${esc(a.tipo)}</span>${a.destacado ? '<span class="chip posible">Destacado</span>' : ''}${a.alcance === 'mundo' ? '<span class="chip">Todo el mundo</span>' : ''}</div>
      <h3>${esc(a.titulo)}</h3>
      <p class="ct-cuando">${esc(fechaCorta(a.fecha, a.hora))}</p>
      ${a.lugar || a.ciudad ? `<p class="ct-donde">${esc([a.lugar, a.ciudad].filter(Boolean).join(' · '))}</p>` : ''}
      ${a.texto ? `<p class="ct-texto">${esc(a.texto)}</p>` : ''}
      <div class="ct-pie"><small>${a.autor_nombre ? 'Por ' + esc(a.autor_nombre) : ''}</small>${a.link && !extra ? `<button type="button" class="btn chico" data-link="${esc(a.link)}">Más info</button>` : ''}</div>
      ${extra || ''}
    </div></article>`;
}
function tarjetas() {
  return CT.anuncios.filter((a) => CT.tipo === 'Todos' || a.tipo === CT.tipo).map((a) => tarjeta(a)).join('');
}
$('#ctTipos').addEventListener('click', (e) => { const b = e.target.closest('[data-tipo]'); if (b) { CT.tipo = b.dataset.tipo; pintarCartelera(); } });
$('#ctLista').addEventListener('click', (e) => { const b = e.target.closest('[data-link]'); if (b) api('/api/abrir_anuncio', { url: b.dataset.link }); });
$('#ctUbic').onclick = elegirUbicacion;
$('#ctPublicar').onclick = () => irA('misanuncios');
$('#ctInicio').onchange = async (e) => { const d = await api('/api/config', { cartelera_inicio: e.target.checked }); E.config = d.config; aviso('Guardado.'); };

function elegirUbicacion() {
  const u = CT.ubic || {};
  modal('Tu zona', `<p class="nota">Ves los anuncios de tu provincia o estado, los de todo tu país y los que son para todo el mundo. A la cartelera sólo se le dice tu país.</p>
    <div class="ma-form"><label>País<select id="ubPais">${optsPais(u.pais)}</select></label>
    <label>Provincia / estado<span id="ubRegWrap">${campoRegion('ubReg', u.pais, u.region)}</span></label></div>`, [
    { txt: 'Cancelar' },
    { txt: 'Guardar', prim: true, fn: async () => {
      try {
        const d = await api('/api/ubicacion', { pais: $('#ubPais').value, region: $('#ubReg').value });
        CT.ubic = d.ubicacion; cerrarModal(); pintarCartelera();
      } catch (e) { aviso(e.message, true); }
    } },
  ]);
  $('#ubPais').onchange = (e) => { $('#ubRegWrap').innerHTML = campoRegion('ubReg', e.target.value, ''); };
}

// ---------------------------------------------------------------- MIS ANUNCIOS
async function pintarMisAnuncios() {
  $('#maAcc').innerHTML = '';
  $('#maCuerpo').innerHTML = '<p class="nota">Cargando…</p>';
  try { MA.quien = await api('/api/nube/quien'); } catch (e) { $('#maCuerpo').innerHTML = `<p class="nota">${esc(e.message)}</p>`; return; }
  if (!MA.quien.conectado) { pintarLogin(); return; }
  $('#maAcc').innerHTML = `<span class="nota">${esc(MA.quien.email)}</span><button type="button" class="btn" id="maSalir">Salir</button><button type="button" class="btn prim" id="maNuevo">Nuevo anuncio</button>`;
  $('#maSalir').onclick = async () => { await api('/api/nube/salir', {}); pintarMisAnuncios(); };
  $('#maNuevo').onclick = () => formAnuncio({});
  try { MA.anuncios = (await api('/api/nube/mis')).anuncios; } catch (e) { aviso(e.message, true); MA.anuncios = []; }
  const hoy = new Date().toISOString().slice(0, 10);
  const estado = (a) => (a.fecha < hoy ? ['Vencido', ''] : a.estado === 'publicado' ? ['Publicado', 'tengo'] : a.estado === 'rechazado' ? ['Rechazado', 'falta'] : ['En revisión', 'posible']);
  $('#maCuerpo').innerHTML = `<div class="panel ma-perfil"><label class="campo">Nombre que ven los demás<input id="maNombre" value="${esc(MA.quien.nombre)}" placeholder="Tu nombre de DJ"></label><p class="nota">Aparece como «Por …» en tus anuncios. Tu email no se muestra.</p></div>
    ${MA.quien.admin ? '<div class="panel" id="maAdmin"><h2>Para aprobar</h2><p class="nota">Cargando…</p></div>' : ''}
    <h2 class="ma-tit">Tus anuncios</h2>
    <div class="ct-grilla">${MA.anuncios.length ? MA.anuncios.map((a) => {
      const [txt, cls] = estado(a);
      return tarjeta(a, `<div class="ma-est"><span class="chip ${cls}">${txt}</span>${a.estado === 'rechazado' && a.motivo ? `<small>${esc(a.motivo)}</small>` : ''}<small>${esc(ALCANCES.find((x) => x[0] === a.alcance)?.[1] || '')}${a.pais ? ' · ' + esc(ubicTxt(a)) : ''}</small></div>
        <div class="acciones"><button type="button" class="btn chico" data-mborrar="${a.id}">Borrar</button><button type="button" class="btn chico" data-meditar="${a.id}">Editar</button></div>`);
    }).join('') : '<div class="panel ct-vacio"><h2>Todavía no publicaste nada</h2><p class="nota">Tocá «Nuevo anuncio». Cada anuncio se revisa antes de aparecer en la Cartelera.</p></div>'}</div>`;
  $('#maNombre').onchange = async (e) => { try { const r = await api('/api/nube/nombre', { nombre: e.target.value }); aviso(r.mensaje); } catch (err) { aviso(err.message, true); } };
  if (MA.quien.admin) pintarAdmin();
}
function pintarLogin() {
  const paso2 = !!MA.email;
  $('#maCuerpo').innerHTML = `<div class="panel ma-login">
    <h2>${paso2 ? 'Revisá tu email' : 'Entrá con tu email'}</h2>
    <p class="nota">${paso2 ? `Te mandamos un código a <b>${esc(MA.email)}</b>. Puede tardar un minuto; fijate también en spam.` : 'Te mandamos un código para entrar: no hace falta contraseña. Tu email no se muestra en los anuncios.'}</p>
    ${paso2 ? '<label class="campo">Código<input id="maCodigo" inputmode="numeric" autocomplete="one-time-code" maxlength="10" placeholder="123456"></label>'
      : `<label class="campo">Email<input id="maEmail" type="email" value="${esc(MA.email)}" placeholder="tu@email.com"></label>`}
    <div class="acciones">${paso2 ? '<button type="button" class="btn" id="maOtro">Usar otro email</button>' : ''}<button type="button" class="btn prim" id="maSeguir">${paso2 ? 'Entrar' : 'Enviarme el código'}</button></div>
    <p class="nota">Para mostrar la Cartelera y tus anuncios, la app se conecta al servidor de RKB Collection Manager. Se guarda sólo tu email, tu nombre de DJ y lo que publicás.</p></div>`;
  const ir = async () => {
    try {
      if (!paso2) { const r = await api('/api/nube/codigo', { email: $('#maEmail').value }); MA.email = r.email; pintarLogin(); }
      else { await api('/api/nube/verificar', { email: MA.email, codigo: $('#maCodigo').value }); MA.email = ''; aviso('¡Listo, entraste!'); pintarMisAnuncios(); }
    } catch (e) { aviso(e.message, true); }
  };
  $('#maSeguir').onclick = ir;
  const campo = $('#maCodigo') || $('#maEmail');
  campo.focus(); campo.onkeydown = (e) => { if (e.key === 'Enter') ir(); };
  if (paso2) $('#maOtro').onclick = () => { MA.email = ''; pintarLogin(); };
}
$('#maCuerpo').addEventListener('click', (e) => {
  const ed = e.target.closest('[data-meditar]'); const bo = e.target.closest('[data-mborrar]');
  if (ed) formAnuncio(MA.anuncios.find((a) => a.id === ed.dataset.meditar));
  if (bo) {
    const a = MA.anuncios.find((x) => x.id === bo.dataset.mborrar);
    modal('Borrar anuncio', `<p>Se borra «${esc(a.titulo)}» y deja de verse en la Cartelera.</p>`, [
      { txt: 'Cancelar' },
      { txt: 'Borrar', prim: true, fn: async () => { try { const r = await api('/api/nube/borrar', { id: a.id }); cerrarModal(); aviso(r.mensaje); pintarMisAnuncios(); } catch (err) { aviso(err.message, true); } } },
    ]);
  }
});

function formAnuncio(a) {
  const u = CT.ubic || {};
  const pais = a.pais || u.pais || ''; const region = a.region || (a.id ? '' : u.region) || '';
  const hoy = new Date().toISOString().slice(0, 10);
  let imagenNueva = null; let quitarImagen = false;
  modal(a.id ? 'Editar anuncio' : 'Nuevo anuncio', `<div class="ma-form">
    <label>Tipo<select id="faTipo">${TIPOS.map((t) => `<option ${t === (a.tipo || 'Evento') ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
    <label class="ancho">Título<input id="faTitulo" maxlength="80" value="${esc(a.titulo || '')}" placeholder="Ej.: Fiesta Retro 80s y 90s"></label>
    <label>Fecha<input id="faFecha" type="date" min="${hoy}" value="${esc(a.fecha || '')}"></label>
    <label>Hora (opcional)<input id="faHora" type="time" value="${esc(a.hora || '')}"></label>
    <label>Lugar<input id="faLugar" maxlength="80" value="${esc(a.lugar || '')}" placeholder="Salón, boliche, dirección…"></label>
    <label>Ciudad<input id="faCiudad" maxlength="60" value="${esc(a.ciudad || '')}"></label>
    <label>País<select id="faPais">${optsPais(pais)}</select></label>
    <label>Provincia / estado<span id="faRegWrap">${campoRegion('faRegion', pais, region)}</span></label>
    <label class="ancho">¿Quién lo ve?<select id="faAlcance">${ALCANCES.map(([v, t]) => `<option value="${v}" ${v === (a.alcance || 'region') ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
    <label class="ancho">Texto <small id="faCuenta"></small><textarea id="faTexto" maxlength="600" rows="4" placeholder="Contá de qué se trata, precio, contacto…">${esc(a.texto || '')}</textarea></label>
    <label class="ancho">Link (opcional)<input id="faLink" value="${esc(a.link || '')}" placeholder="Instagram, entradas, WhatsApp…"></label>
    <div class="ancho fa-img"><div class="fa-prev" id="faPrev" style="${a.imagen ? `background-image:url('${urlCss(a.imagen)}')` : ''}">${a.imagen ? '' : 'Sin imagen'}</div>
      <div class="acciones"><button type="button" class="btn chico" id="faElegir">${a.imagen ? 'Cambiar imagen' : 'Agregar flyer o foto'}</button><button type="button" class="btn chico" id="faQuitar" ${a.imagen ? '' : 'hidden'}>Quitar</button></div><input type="file" id="faArchivo" accept="image/*" hidden></div>
    <label class="ancho fa-acepto"><input type="checkbox" id="faAcepto" ${a.id ? 'checked' : ''}> El anuncio es real y es mío. Sé que se revisa antes de publicarse y que puede rechazarse si no tiene que ver con la música o los DJs.</label>
  </div>${a.id && a.estado === 'publicado' ? '<p class="nota">Al editarlo vuelve a revisión hasta que se apruebe de nuevo.</p>' : ''}`, [
    { txt: 'Cancelar' },
    { txt: a.id ? 'Guardar cambios' : 'Enviar a revisión', prim: true, fn: async () => {
      if (!$('#faAcepto').checked) { aviso('Marcá la casilla de confirmación.', true); return; }
      const datos = { id: a.id, tipo: $('#faTipo').value, titulo: $('#faTitulo').value, fecha: $('#faFecha').value, hora: $('#faHora').value,
        lugar: $('#faLugar').value, ciudad: $('#faCiudad').value, pais: $('#faPais').value, region: $('#faRegion').value,
        alcance: $('#faAlcance').value, texto: $('#faTexto').value, link: $('#faLink').value, imagenNueva, quitarImagen };
      try { const r = await api('/api/nube/guardar', datos); cerrarModal(); aviso(r.mensaje); pintarMisAnuncios(); } catch (e) { aviso(e.message, true); }
    } },
  ]);
  $('#modal .caja').classList.add('medio');
  const cuenta = () => { $('#faCuenta').textContent = `${$('#faTexto').value.length} / 600`; };
  cuenta(); $('#faTexto').oninput = cuenta;
  $('#faPais').onchange = (e) => { $('#faRegWrap').innerHTML = campoRegion('faRegion', e.target.value, ''); };
  $('#faElegir').onclick = () => $('#faArchivo').click();
  $('#faQuitar').onclick = () => { imagenNueva = null; quitarImagen = true; $('#faPrev').style.backgroundImage = ''; $('#faPrev').textContent = 'Sin imagen'; $('#faQuitar').hidden = true; };
  $('#faArchivo').onchange = (e) => {
    const f = e.target.files[0]; if (!f) return;
    if (f.size > 15e6) { aviso('La imagen es demasiado grande (máximo 15 MB).', true); return; }
    const r = new FileReader();
    r.onload = () => { imagenNueva = r.result; quitarImagen = false; $('#faPrev').style.backgroundImage = `url('${r.result}')`; $('#faPrev').textContent = ''; $('#faQuitar').hidden = false; };
    r.readAsDataURL(f);
  };
}

// ---------------------------------------------------------------- moderación (sólo administrador)
async function pintarAdmin() {
  try { MA.pend = (await api('/api/nube/pendientes')).anuncios; } catch (e) { $('#maAdmin').innerHTML = `<h2>Para aprobar</h2><p class="nota">${esc(e.message)}</p>`; return; }
  $('#maAdmin').innerHTML = `<h2>Para aprobar · ${MA.pend.length}</h2>${MA.pend.length ? `<div class="ct-grilla">${MA.pend.map((a) => tarjeta(a, `<div class="ma-est"><small>${esc(a.perfiles?.email || '')} · ${esc(ALCANCES.find((x) => x[0] === a.alcance)?.[1] || '')}${a.pais ? ' · ' + esc(ubicTxt(a)) : ''}</small>${a.link ? `<small>${esc(a.link)}</small>` : ''}</div>
      <div class="acciones"><button type="button" class="btn chico" data-mod="rechazado" data-id="${a.id}">Rechazar</button><button type="button" class="btn chico" data-mod="destacado" data-id="${a.id}">Publicar destacado</button><button type="button" class="btn chico prim" data-mod="publicado" data-id="${a.id}">Publicar</button></div>`)).join('')}</div>` : '<p class="nota">No hay anuncios esperando.</p>'}`;
}
$('#maCuerpo').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-mod]'); if (!b) return;
  const id = b.dataset.id;
  if (b.dataset.mod === 'rechazado') {
    modal('Rechazar anuncio', '<label class="campo">Motivo (lo ve quien lo publicó)<input id="modMotivo" maxlength="300" placeholder="Ej.: no tiene que ver con DJs"></label>', [
      { txt: 'Cancelar' },
      { txt: 'Rechazar', prim: true, fn: async () => { try { await api('/api/nube/moderar', { id, estado: 'rechazado', motivo: $('#modMotivo').value }); cerrarModal(); pintarAdmin(); } catch (err) { aviso(err.message, true); } } },
    ]);
    return;
  }
  try { const r = await api('/api/nube/moderar', { id, estado: 'publicado', destacado: b.dataset.mod === 'destacado' }); aviso(r.mensaje); pintarAdmin(); } catch (err) { aviso(err.message, true); }
});
