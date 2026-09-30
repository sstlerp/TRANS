/* Toll Plazas screen: "Fetch from Internet" — update the toll plaza master from OpenStreetMap, data.gov.in or a
   FASTag / toll API (Administration → API Integrations, type TOLL_PLAZA_MASTER). Toll ID, name, place and state are
   compulsory; records without them are skipped and listed. */
'use strict';
MasterExt.toll_plazas = (() => {
  const { $, $$, esc, get, post, toast, errToast, modal, pill, ddmmyyyy } = ERP;
  let added = false;

  function afterForm(a) {  // a = Master.api(): { M, S, loadList, ... }
    if (added || !a.M.perms.edit) return;
    added = true;
    const b = document.createElement('button');
    b.className = 'tb-btn tb-btn--ghost'; b.id = 'btn-fetch-plazas';
    b.innerHTML = '<i class="ti ti-cloud-download"></i> Fetch from Internet';
    b.onclick = () => open(a);
    $('#tb-right').prepend(b);
  }

  const counts = r => `<div class="kpis" style="margin:.5rem 0">
      ${[['Fetched', r.fetched, ''], ['New', r.created, 'green'], ['Updated', r.updated, 'blue'], ['Unchanged', r.unchanged, ''],
         ['Skipped', r.skipped, r.skipped ? 'amber' : '']].map(([l, v, c]) => `<div class="kpi ${c}"><div class="l">${l}</div><div class="v">${v ?? 0}</div></div>`).join('')}
    </div>`;

  async function open(a) {
    let sources, states;
    try { [sources, states] = await Promise.all([get('/api/toll-plazas/sync/sources'), get('/api/toll-plazas/sync/states')]); }
    catch (e) { return errToast(e); }
    const m = modal({
      title: 'Fetch toll plazas from the internet', icon: 'ti-cloud-download', size: 'wide', body: `
      <div class="note note-info"><i class="ti ti-info-circle"></i><div>Toll plazas are added or updated with <b>toll ID, toll plaza name, place and state</b>
        (all compulsory — records without them are skipped and listed below). Existing plazas are updated, never deleted.
        Sources are configured in <a href="/masters/api_integrations?f_integration_type=TOLL_PLAZA_MASTER">Administration → API Integrations</a>.</div></div>
      <div class="fg2">
        <div class="f-group"><label class="f-label">Source <span class="req">*</span></label>
          <select class="f-input" id="ts-source">${sources.map(s => `<option value="${s.id}" ${s.is_active ? '' : 'disabled'}>${esc(s.name)}${s.is_active ? '' : ' (inactive)'}</option>`).join('')}</select>
          <div class="f-err" id="ts-src-note" style="color:#64748B"></div></div>
        <div class="f-group"><label class="f-label">Mode</label>
          <div class="f-toggle-row"><label class="f-toggle"><input type="checkbox" id="ts-dry"><span class="f-toggle-track"></span><span class="f-toggle-thumb"></span></label>
          <span class="f-toggle-lbl">Dry run — only count what would change</span></div></div>
      </div>
      <div class="f-group" style="margin-top:.4rem"><label class="f-label">States <span class="hint">(none ticked = all of India; a whole-India fetch from OpenStreetMap takes several minutes)</span>
        <a href="#" id="ts-none" style="margin-left:auto;font-weight:600">Clear</a></label>
        <div class="ts-states">${states.map(s => `<label><input type="checkbox" value="${s.code}"> ${esc(s.name)}</label>`).join('')}</div></div>
      <div id="ts-result"></div>`,
      foot: `<button class="m-btn m-btn--cancel" data-x>Close</button><button class="m-btn m-btn--save" id="ts-go"><i class="ti ti-cloud-download"></i> Fetch</button>` });
    const note = () => {
      const s = sources.find(x => String(x.id) === $('#ts-source', m.el).value);
      $('#ts-src-note', m.el).textContent = !s ? 'No source configured.' :
        s.adapter === 'OSM_OVERPASS' ? 'Free, no key. Data © OpenStreetMap contributors (ODbL).' :
        s.needs_key ? `Needs the API key in environment variable ${s.key_env_var || '(set Credential Env Variable)'}.` : '';
    };
    $('#ts-source', m.el).onchange = note;
    const firstActive = sources.find(s => s.is_active); if (firstActive) $('#ts-source', m.el).value = firstActive.id;
    note();
    $('#ts-none', m.el).onclick = e => { e.preventDefault(); $$('.ts-states input', m.el).forEach(c => c.checked = false); };
    m.el.querySelector('[data-x]').onclick = m.close;
    $('#ts-go', m.el).onclick = async () => {
      const btn = $('#ts-go', m.el);
      const body = { integration_id: +$('#ts-source', m.el).value || null, dry_run: $('#ts-dry', m.el).checked,
        states: $$('.ts-states input:checked', m.el).map(c => c.value) };
      btn.disabled = true;
      try {
        let run = await post('/api/toll-plazas/sync', body);
        while (['QUEUED', 'RUNNING'].includes(run.status)) {
          show(run);
          await new Promise(r => setTimeout(r, 2000));
          if (!document.body.contains(m.el)) return;
          run = await get(`/api/toll-plazas/sync/runs/${run.id}`);
        }
        show(run);
        if (!run.dry_run) a.loadList();
        toast(run.status === 'SUCCESS' ? 'Toll plazas updated' : `Finished: ${run.status}`, run.status === 'FAILED' ? 'err' : run.status === 'PARTIAL' ? 'warn' : 'ok');
      } catch (e) { errToast(e); }
      finally { btn.disabled = false; }
    };
    function show(r) {
      const pct = r.states_total ? Math.round(100 * r.states_done / r.states_total) : 0;
      $('#ts-result', m.el).innerHTML = `<div class="vnd-section" style="margin-top:.6rem"><div class="vnd-section-head"><span class="sh-title"><i class="ti ti-activity"></i>
        Run #${r.id} ${r.dry_run ? '(dry run)' : ''}</span><span>${pill(r.status)}</span></div><div class="vnd-section-body">
        <div class="bar-row" style="grid-template-columns:110px 1fr 60px"><span>States ${r.states_done}/${r.states_total}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div><b style="text-align:right">${pct}%</b></div>
        ${counts(r)}
        ${r.error_message ? `<div class="note note-err"><i class="ti ti-alert-circle"></i><div style="white-space:pre-line">${esc(r.error_message)}</div></div>` : ''}
        ${(r.skipped_samples || []).length ? `<details><summary style="cursor:pointer;font-size:.74rem;font-weight:700;color:#92400E">Skipped records (${r.skipped}) — reasons</summary>
          <ul style="font-size:.7rem;max-height:180px;overflow:auto;margin:.3rem 0">${r.skipped_samples.map(x => `<li>${esc(x)}</li>`).join('')}</ul></details>` : ''}
      </div></div>`;
    }
  }
  return { afterForm };
})();
