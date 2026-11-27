/* RKB Collection Manager · backup y restauración */
'use strict';

const RS = { d: null, trabajo: null, shareTam: null };
const fechaTxt = (f) => { try { return new Date(f).toLocaleString('es-AR', { dateStyle: 'medium', timeStyle: 'short' }); } catch (_) { return f || ''; } };

async function pintarRespaldo() {
  let d;
  try { d = await api('/api/respaldo'); } catch (e) { aviso(e.message, true); return; }
  RS.d = d;
  $('#rsDestino').textContent = d.destino; $('#rsDestino').title = d.destino;
  $('#rsLibre').textContent = (d.libre != null ? `Libre en ese disco: ${tamTxt(d.libre)}. ` : '') +
    'Conviene que sea un disco externo: si se rompe la computadora, el backup queda a salvo.';
  if (!RS.trabajo) { $('#rsShare').checked = !!d.opciones.share; $('#rsOtros').checked = !!d.opciones.otros; }
  $('#rsShare').disabled = !d.hayShare;
  if (d.hayShare && RS.shareTam == null) {
    api('/api/respaldo/share').then((r) => { RS.shareTam = r.bytes; $('#rsShareTam').textContent = `cues y waveforms · ${tamTxt(r.bytes)}`; }).catch(() => {});
  }
  // bases
  $('#rsBases').innerHTML = d.bases.length ? d.bases.map((b, i) => `<div class="rs-item"><div><b>${esc(fechaTxt(b.fecha))}</b>${b.motivo === 'antes de restaurar' ? ' <span class="nota">(guardada antes de restaurar)</span>' : ''}
      <small>${b.temas != null ? `${esc(b.temas)} temas · ${esc(b.playlists)} playlists · ` : ''}${b.share ? 'con análisis · ' : ''}${tamTxt(b.bytes)}${b.sistema ? ' · ' + (b.sistema === 'windows' ? 'Windows' : 'Mac') : ''}${b.valido ? '' : ' · <b>no se pudo leer</b>'}</small></div>
      <div class="acciones"><button type="button" class="btn chico" data-rsborrar="${i}">Borrar</button><button type="button" class="btn chico" data-rsbase="${i}" ${b.valido ? '' : 'disabled'}>Restaurar</button></div></div>`).join('')
    : '<p class="rs-vacio">Todavía no hay backups de la base en esta carpeta.</p>';
  // colección
  const c = d.coleccion;
  $('#rsCol2').innerHTML = c ? `<div class="rs-item"><div><b>Copia espejo · ${c.archivos} archivos · ${tamTxt(c.bytes)}</b>
      <small>Actualizada el ${esc(fechaTxt(c.actualizado))}${c.otros ? ` · ${c.otros} de fuera de la carpeta` : ''} · se restaura en ${esc(d.carpetaColeccion)}</small></div>
      <div class="acciones"><button type="button" class="btn chico" data-rscol="todos">Restaurar todo</button><button type="button" class="btn chico prim" data-rscol="faltantes">Restaurar los que faltan</button></div></div>
      ${d.quitados.length ? `<p class="nota" style="margin-top:6px">Apartados del backup porque ya no estaban en tu colección:</p>` + d.quitados.map((q, i) => `<div class="rs-item"><div>Quitados el ${esc(q.nombre)}</div><div class="acciones"><button type="button" class="btn chico" data-rsquit="${i}">Recuperar</button></div></div>`).join('') : ''}`
    : '<p class="rs-vacio">Todavía no hay backup de la colección en esta carpeta.</p>';
  pintarBotonesRs();
}

function pintarBotonesRs() {
  const ocupado = !!RS.trabajo;
  $('#rsHacer').disabled = ocupado || (!$('#rsBase').checked && !$('#rsCol').checked);
  $('#rsShare').closest('label').style.opacity = $('#rsBase').checked ? 1 : 0.45;
  $('#rsOtros').closest('label').style.opacity = $('#rsCol').checked ? 1 : 0.45;
  document.querySelectorAll('#rsBases button, #rsCol2 button, #rsCambiar').forEach((b) => { b.disabled = ocupado || (b.dataset.rsbase != null && RS.d && !RS.d.bases[+b.dataset.rsbase].valido); });
  $('#rsProg').hidden = !ocupado;
}
for (const id of ['rsBase', 'rsCol', 'rsShare', 'rsOtros']) $('#' + id).addEventListener('change', pintarBotonesRs);

async function correrRs(ruta, cuerpo, titulo) {
  let r;
  try { r = await api(ruta, cuerpo); } catch (e) { aviso(e.message, true); return null; }
  RS.trabajo = r.trabajo; pintarBotonesRs();
  $('#rsProgTxt').textContent = titulo; $('#rsProgIn').style.width = '0';
  const fin = await seguir(r.trabajo, (t) => {
    const pct = t.total ? Math.min(100, (t.hechos / t.total) * 100) : 0;
    $('#rsProgIn').style.width = pct + '%';
    $('#rsProgTxt').textContent = t.mensaje || titulo;
  });
  RS.trabajo = null;
  await pintarRespaldo();
  if (fin.estado === 'error') { aviso(fin.error, true); return null; }
  return fin;
}
$('#rsCancelar').onclick = () => RS.trabajo && api('/api/trabajo/cancelar', { id: RS.trabajo });

$('#rsHacer').onclick = async () => {
  const cuerpo = { base: $('#rsBase').checked, coleccion: $('#rsCol').checked, respaldo_share: $('#rsShare').checked, respaldo_otros: $('#rsOtros').checked };
  if (cuerpo.base && E.rbAbierto) { aviso('Rekordbox está abierto: cerralo para respaldar la base (o destildá «Base de Rekordbox»).', true); return; }
  const fin = await correrRs('/api/respaldo/hacer', cuerpo, 'Preparando el backup…');
  if (!fin) return;
  const r = fin.resultado || {};
  const partes = [];
  if (r.base) partes.push(`Base de Rekordbox: ${r.base.temas != null ? r.base.temas + ' temas, ' + r.base.playlists + ' playlists, ' : ''}${tamTxt(r.base.bytes)}.`);
  if (r.coleccion) partes.push(`Colección: ${r.coleccion.copiados} archivos copiados (${tamTxt(r.coleccion.bytes)})${r.coleccion.apartados ? `, ${r.coleccion.apartados} apartados en «_quitados»` : ''}; en total ${r.coleccion.total} archivos respaldados.`);
  const cancel = fin.estado === 'cancelado' || (r.coleccion && r.coleccion.cancelado);
  $('#rsUltimo').innerHTML = `<div class="rs-ok"><b>${cancel ? 'Backup interrumpido' : 'Backup listo'}</b> · ${esc(fechaTxt(new Date().toISOString()))}<br>${partes.map(esc).join('<br>')}${cancel ? '<br>Lo que alcanzó a copiarse quedó guardado; la próxima vez sigue desde ahí.' : ''}</div>`;
  aviso(cancel ? 'Backup interrumpido.' : 'Backup listo.');
};

$('#rsCambiar').onclick = async () => {
  const { ruta } = await api('/api/elegir_carpeta', { titulo: 'Elegí dónde guardar los backups' });
  if (!ruta) return;
  try { await api('/api/respaldo/destino', { ruta }); aviso('Carpeta de backups guardada.'); pintarRespaldo(); } catch (e) { aviso(e.message, true); }
};
$('#rsAbrir').onclick = () => api('/api/respaldo/abrir', {}).catch((e) => aviso(e.message, true));

$('#rsBases').addEventListener('click', (e) => {
  const bb = e.target.closest('[data-rsbase]'); const bd = e.target.closest('[data-rsborrar]');
  if (bd) {
    const b = RS.d.bases[+bd.dataset.rsborrar];
    modal('Borrar backup', `<p>Se borra el backup del <b>${esc(fechaTxt(b.fecha))}</b> (${tamTxt(b.bytes)}). <b>No se puede deshacer.</b></p>`, [
      { txt: 'Cancelar' },
      { txt: 'Borrar', prim: true, fn: async () => { try { await api('/api/respaldo/borrar', { ruta: b.ruta }); cerrarModal(); aviso('Backup borrado.'); pintarRespaldo(); } catch (err) { cerrarModal(); aviso(err.message, true); } } },
    ]);
    return;
  }
  if (!bb) return;
  const b = RS.d.bases[+bb.dataset.rsbase];
  const otroSO = b.sistema && b.sistema !== (navigator.userAgent.includes('Windows') ? 'windows' : 'mac');
  modal('Restaurar la base de Rekordbox', `<p>La base de Rekordbox vuelve a como estaba el <b>${esc(fechaTxt(b.fecha))}</b>: playlists, cues, My Tags, historial y metadata.</p>
    <p class="nota">Todo lo que hiciste en Rekordbox después de esa fecha se pierde, pero antes de restaurar la app guarda la base actual: si te arrepentís, restaurás ese backup («guardada antes de restaurar»).</p>
    ${b.share ? '<label class="campo-in" style="margin-top:8px"><input type="checkbox" id="rsConShare" checked> Restaurar también análisis y carátulas</label>' : ''}
    ${otroSO ? '<p class="nota" style="margin-top:8px"><b>Ojo:</b> este backup es de otra computadora (' + (b.sistema === 'windows' ? 'Windows' : 'Mac') + '). Las rutas de los temas van a ser las de esa computadora: después usá «Reubicar» en Rekordbox para encontrarlos.</p>' : ''}
    <p class="nota" style="margin-top:8px">Rekordbox tiene que estar cerrado.</p>`, [
    { txt: 'Cancelar' },
    { txt: 'Restaurar', prim: true, fn: async () => {
      const share = $('#rsConShare') ? $('#rsConShare').checked : false;
      cerrarModal();
      const fin = await correrRs('/api/respaldo/restaurar_base', { ruta: b.ruta, share }, 'Restaurando la base…');
      if (!fin) return;
      const r = fin.resultado || {};
      modal('Base restaurada', `<p>Listo: la base de Rekordbox volvió al ${esc(fechaTxt(b.fecha))}.</p>${r.previo ? '<p class="nota">La base que tenías antes quedó guardada como un backup nuevo («guardada antes de restaurar»).</p>' : ''}<p class="nota">Ya podés abrir Rekordbox.</p>`, [{ txt: 'Listo', prim: true }]);
      cargarColeccion();
    } },
  ]);
});

$('#rsCol2').addEventListener('click', (e) => {
  const bc = e.target.closest('[data-rscol]'); const bq = e.target.closest('[data-rsquit]');
  if (!bc && !bq) return;
  let cuerpo, txt;
  if (bq) {
    const q = RS.d.quitados[+bq.dataset.rsquit];
    cuerpo = { modo: 'faltantes', carpeta: q.ruta };
    txt = `<p>Vuelven a tu carpeta de la colección los archivos que se apartaron el <b>${esc(q.nombre)}</b> (sólo los que no estén).</p><p class="nota">Después, si querés que aparezcan en Rekordbox, incorporalos desde la solapa 3 o arrastralos a Rekordbox.</p>`;
  } else if (bc.dataset.rscol === 'todos') {
    cuerpo = { modo: 'todos' };
    txt = '<p>Se copian de vuelta <b>todos</b> los archivos del backup: los que faltan y también los que cambiaron desde el backup (se pisan con la versión del backup).</p><p class="nota">Si después del backup editaste tags o carátulas de algún tema, esos cambios se pierden en esos archivos.</p>';
  } else {
    cuerpo = { modo: 'faltantes' };
    txt = '<p>Se copian de vuelta sólo los archivos que <b>no están</b> en tu colección. No se toca nada de lo que ya tenés.</p>';
  }
  modal('Restaurar la colección', txt, [
    { txt: 'Cancelar' },
    { txt: 'Restaurar', prim: true, fn: async () => {
      cerrarModal();
      const fin = await correrRs('/api/respaldo/restaurar_coleccion', cuerpo, 'Restaurando la colección…');
      if (!fin) return;
      const r = fin.resultado || {};
      modal('Colección restaurada', `<p>${r.restaurados ? `Listo: volvieron ${r.restaurados} archivos (${tamTxt(r.bytes)}).` : 'No faltaba nada: tu colección ya tiene todo lo del backup.'}</p>${r.nErrores ? `<p class="nota">${r.nErrores} no se pudieron copiar:<br>${r.errores.map(esc).join('<br>')}</p>` : ''}`, [{ txt: 'Listo', prim: true }]);
      cargarColeccion();
    } },
  ]);
});
