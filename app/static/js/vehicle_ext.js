/* Vehicle master extension: configurable technical attributes per sub-category. */
'use strict';
MasterExt.vehicles = (() => {
  const { $, $$, esc, get, maskDate, ddmmyyyy } = ERP;
  let defs = [], current = {};
  async function render(api, subId, values) {
    const box = $('#ext-sections');
    if (!subId) { box.innerHTML = ''; defs = []; return; }
    defs = await get(`/api/vehicles/attribute-definitions/${subId}`);
    if (!defs.length) { box.innerHTML = `<div class="note note-info"><i class="ti ti-info-circle"></i><div>No technical attributes configured for this sub-category (Fleet → Sub-category Attributes).</div></div>`; return; }
    box.innerHTML = `<div class="vnd-section"><div class="vnd-section-head"><span class="sh-title"><i class="ti ti-adjustments"></i> Technical Attributes (by sub-category)</span></div>
      <div class="vnd-section-body"><div class="fg4">${defs.map(d => {
        const lbl = `<label class="f-label">${esc(d.name)}${d.unit ? ` <span class="hint">(${esc(d.unit)})</span>` : ''}${d.is_mandatory ? ' <span class="req">*</span>' : ''}</label>`;
        let ctl;
        if (d.data_type === 'BOOLEAN') ctl = `<div class="f-toggle-row"><label class="f-toggle"><input type="checkbox" data-attr="${d.id}"><span class="f-toggle-track"></span><span class="f-toggle-thumb"></span></label></div>`;
        else if (d.data_type === 'DROPDOWN') ctl = `<select class="f-input" data-attr="${d.id}"><option value="">—</option>${d.options.map(o => `<option>${esc(o)}</option>`).join('')}</select>`;
        else ctl = `<input class="f-input" data-attr="${d.id}" ${d.data_type === 'DATE' ? 'placeholder="DD/MM/YYYY"' : ''} ${['INTEGER', 'DECIMAL'].includes(d.data_type) ? 'inputmode="decimal" style="text-align:right"' : ''}>`;
        return `<div class="f-group">${lbl}${ctl}<div class="f-err" id="fld-attr_${d.id}-err"></div></div>`;
      }).join('')}</div></div></div>`;
    for (const d of defs) {
      const el = box.querySelector(`[data-attr="${d.id}"]`);
      const v = (values || {})[d.id];
      if (d.data_type === 'DATE') { maskDate(el); el.value = ddmmyyyy(v); }
      else if (d.data_type === 'BOOLEAN') el.checked = !!v;
      else el.value = v ?? '';
      el.disabled = !['NEW', 'EDIT'].includes(api.S.mode);
    }
  }
  return {
    afterForm(api) {
      const sub = $('#fld-sub_category_id');
      sub.addEventListener('change', () => render(api, sub.value, current));
    },
    onLoad(api, rec) { current = rec ? rec.attributes || {} : {}; render(api, rec ? rec.sub_category_id : $('#fld-sub_category_id').value, current); },
    onMode(api, mode) { $$('#ext-sections [data-attr]').forEach(e => e.disabled = !['NEW', 'EDIT'].includes(mode)); },
    collect(api, data) {
      if (!defs.length) return;
      data.attributes = {};
      for (const d of defs) {
        const el = $(`[data-attr="${d.id}"]`);
        data.attributes[d.id] = d.data_type === 'BOOLEAN' ? el.checked : (el.value.trim() || null);
      }
    },
  };
})();
