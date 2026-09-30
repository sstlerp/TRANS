/* Generic metadata-driven master/transaction screen in the house design.
   Server metadata: /api/masters/{key}/meta. Page-specific behaviour can be
   added through window.MasterExt[key] = {afterForm, onLoad, collect}. */
'use strict';
window.MasterExt = window.MasterExt || {};
const Master = (() => {
  const { $, $$, esc, get, post, put, del, toast, errToast, modal, confirmBox, money, num, ddmmyyyy, maskDate, pill,
    options, lookups, fillSelect } = ERP;
  let M, KEY, EXT;
  const S = { mode: 'VIEW', id: null, rec: null, page: 1, sort: null, dir: null, q: '', active: '1', filters: {}, extra: {} };

  // ───────────────────────── boot ─────────────────────────
  async function init(key) {
    KEY = key;
    EXT = window.MasterExt[key] || {};
    try { M = await get(`/api/masters/${key}/meta`); } catch (e) { return errToast(e); }
    S.sort = M.default_sort; S.dir = M.default_dir;
    const url = new URLSearchParams(location.search);
    for (const [k, v] of url.entries()) {
      if (k.startsWith('f_')) S.filters[k.slice(2)] = v;
      else if (!['page', 'q'].includes(k)) S.extra[k] = v;
    }
    if (url.get('q')) S.q = url.get('q');
    renderToolbar();
    renderForm();
    await renderListShell();
    await loadList();
    const open = url.get('id');
    if (open) view(+open);
    else if (M.perms.create) doNew(false);
    else setMode('LIST');
  }

  // ───────────────────────── toolbar ─────────────────────────
  function renderToolbar() {
    $('#tb-right').innerHTML = (M.perms.create ? `<button class="tb-btn tb-btn--new" id="btn-new" title="Start a new entry (clears the form)"><i class="ti ti-plus"></i> New</button>` : '') +
      (M.perms.edit ? `<button class="tb-btn tb-btn--new" id="btn-edit" style="display:none"><i class="ti ti-edit"></i> Edit</button>` : '') +
      `<button class="tb-btn tb-btn--save" id="btn-save" style="display:none"><i class="ti ti-device-floppy"></i> <span class="save-lbl">Save</span></button>
       <button class="tb-btn tb-btn--cancel" id="btn-cancel" style="display:none"><i class="ti ti-x"></i> Cancel</button>`;
    $('#form-actions').innerHTML = `<button type="button" class="fa-btn fa-btn--save" id="fa-save"><i class="ti ti-device-floppy"></i> <span class="save-lbl">Save</span></button>
      <button type="button" class="fa-btn fa-btn--clear" id="fa-clear"><i class="ti ti-eraser"></i> Clear</button>`;
    $('#btn-new') && ($('#btn-new').onclick = () => doNew());
    $('#btn-edit') && ($('#btn-edit').onclick = () => setMode('EDIT'));
    $('#btn-save').onclick = () => doSave();
    $('#fa-save').onclick = () => doSave();
    $('#fa-clear').onclick = () => S.id ? doClose() : doNew();
    $('#btn-cancel').onclick = doClose;
    let hidden = false; try { hidden = localStorage.getItem('formhide:' + KEY) === '1'; } catch (_) { }
    const applyHide = () => { $('#form-block').classList.toggle('fb-collapsed', hidden); };
    $('#fb-toggle').onclick = () => { hidden = !hidden; try { localStorage.setItem('formhide:' + KEY, hidden ? '1' : '0'); } catch (_) { } applyHide(); };
    applyHide();
    if (M.description) $('#page-desc').innerHTML = `<div class="note note-info"><i class="ti ti-info-circle"></i><div>${esc(M.description)}</div></div>`;
  }

  // ───────────────────────── form ─────────────────────────
  function sections() {
    const out = [];
    for (const f of M.fields) {
      if (f.hidden) continue;
      let s = out.find(x => x.name === f.section);
      if (!s) { s = { name: f.section || 'General', fields: [] }; out.push(s); }
      s.fields.push(f);
    }
    return out;
  }
  const SEC_ICON = { General: 'ti-forms', Identity: 'ti-id-badge-2', Contact: 'ti-address-book', Remarks: 'ti-notes', Bank: 'ti-building-bank',
    Classification: 'ti-category', 'Make & Ownership': 'ti-car', 'Capacity & Status': 'ti-gauge', Licence: 'ti-license', Engagement: 'ti-briefcase',
    Subject: 'ti-target', Certificate: 'ti-certificate', Payment: 'ti-cash', Policy: 'ti-shield-check', Period: 'ti-calendar', Premium: 'ti-coin',
    Contract: 'ti-file-certificate', Billing: 'ti-receipt', Invoice: 'ti-file-invoice', Dates: 'ti-calendar-event', Amounts: 'ti-currency-rupee',
    Document: 'ti-file-description', Allocation: 'ti-chart-pie', Template: 'ti-template', Layout: 'ti-layout', Transaction: 'ti-arrows-exchange',
    Quantity: 'ti-droplet', Validation: 'ti-shield-check', Override: 'ti-alert-triangle', Plaza: 'ti-road', Review: 'ti-eye-check', Job: 'ti-tools',
    Work: 'ti-hammer', Downtime: 'ti-clock-pause', Specs: 'ti-adjustments', Purchase: 'ti-shopping-cart', Lifecycle: 'ti-refresh' };

  function renderForm() {
    const secs = sections();
    const main = secs.filter(s => s.name !== 'Remarks');
    const rem = secs.filter(s => s.name === 'Remarks');
    let html = '';
    if (main.length <= 1) {
      html += main.map(s => sectionHtml(s, 'fg4')).join('');
    } else {
      const ncol = Math.min(3, main.length);
      const cols = Array.from({ length: ncol }, () => []);
      main.forEach((s, i) => cols[i % ncol].push(s));
      html += `<div class="vfw-cols" style="grid-template-columns:repeat(${ncol},1fr)">` +
        cols.map(c => `<div class="vfw-col">${c.map(s => sectionHtml(s, 'fg2')).join('')}</div>`).join('') + '</div>';
    }
    html += rem.map(s => sectionHtml(s, 'fg3')).join('');
    html += `<div id="ext-sections"></div>`;
    html += M.children.map(childHtml).join('');
    $('#form-wrap').innerHTML = html;
    $$('.vnd-section-head', $('#form-wrap')).forEach(h => h.onclick = () => h.parentElement.classList.toggle('collapsed'));
    for (const f of M.fields) wireField(f, $('#form-wrap'));
    for (const c of M.children) $(`#add-${c.key}`).onclick = () => addChildRow(c, {});
    if (EXT.afterForm) EXT.afterForm(api());
  }

  function sectionHtml(s, grid) {
    return `<div class="vnd-section"><div class="vnd-section-head"><span class="sh-title"><i class="ti ${SEC_ICON[s.name] || 'ti-point'}"></i> ${esc(s.name)}</span>
      <i class="ti ti-chevron-down sh-chevron"></i></div><div class="vnd-section-body"><div class="${grid}">
      ${s.fields.map(f => fieldHtml(f, 'fld-')).join('')}</div></div></div>`;
  }

  function fieldHtml(f, prefix, compact) {
    const id = prefix + f.name;
    const span = f.span >= 3 ? 'full' : f.span === 2 ? 'span2' : '';
    const lbl = compact ? '' : `<label class="f-label" for="${id}">${esc(f.label)}${f.required ? ' <span class="req">*</span>' : ''}${f.hint ? ` <span class="hint">(${esc(f.hint)})</span>` : ''}</label>`;
    let ctl;
    const ro = f.readonly ? ' disabled' : '';
    switch (f.type) {
      case 'textarea': ctl = `<textarea class="f-input" id="${id}" data-f="${f.name}"${ro} maxlength="${f.maxlen || 4000}"></textarea>`; break;
      case 'bool': ctl = `<div class="f-toggle-row"><label class="f-toggle"><input type="checkbox" id="${id}" data-f="${f.name}"${ro}><span class="f-toggle-track"></span><span class="f-toggle-thumb"></span></label>${compact ? '' : '<span class="f-toggle-lbl">Yes</span>'}</div>`; break;
      case 'select': case 'lookup': case 'fk': ctl = `<select class="f-input" id="${id}" data-f="${f.name}"${ro}><option value="">—</option></select>`; break;
      case 'multi': ctl = `<select class="f-input" id="${id}" data-f="${f.name}" multiple${ro}></select>`; break;
      case 'date': ctl = `<input class="f-input" id="${id}" data-f="${f.name}" placeholder="DD/MM/YYYY" inputmode="numeric" autocomplete="off"${ro}>`; break;
      case 'datetime': ctl = `<input class="f-input" id="${id}" data-f="${f.name}" placeholder="DD/MM/YYYY HH:MM" inputmode="numeric" autocomplete="off"${ro}>`; break;
      case 'time': ctl = `<input class="f-input" type="time" id="${id}" data-f="${f.name}"${ro}>`; break;
      case 'password': ctl = `<input class="f-input" type="password" id="${id}" data-f="${f.name}" autocomplete="new-password"${ro}>`; break;
      case 'json': ctl = f.readonly ? `<pre class="f-input" id="${id}" data-f="${f.name}" style="white-space:pre-wrap;max-height:180px;overflow:auto;margin:0"></pre>`
        : `<textarea class="f-input f-json" id="${id}" data-f="${f.name}" spellcheck="false" style="font-family:ui-monospace,Consolas,monospace;min-height:120px"></textarea>`; break;
      case 'int': case 'decimal': case 'money':
        ctl = `<input class="f-input" id="${id}" data-f="${f.name}" inputmode="decimal" style="text-align:right"${ro}>`; break;
      default: ctl = `<input class="f-input" id="${id}" data-f="${f.name}" maxlength="${f.maxlen || 255}"${ro}${f.upper ? ' style="text-transform:uppercase"' : ''}>`;
    }
    return `<div class="f-group ${span}">${lbl}${ctl}<div class="f-err" id="${id}-err"></div></div>`;
  }

  async function loadOptions(f, sel, value, scope) {
    try {
      if (f.type === 'select') fillSelect(sel, (f.choices || []).map(c => ({ id: c, label: c.replace(/_/g, ' ') })), value, '—');
      else if (f.type === 'lookup') fillSelect(sel, (await lookups(f.lookup)).map(l => ({ id: l.code, label: l.label })), value, '—');
      else if (f.type === 'fk' || f.type === 'multi') {
        const flt = { ...(f.fk_filter || {}) };
        if (f.depends_on && scope) {
          const parent = scope.querySelector(`[data-f="${f.depends_on}"]`);
          if (parent && parent.value) flt[f.depends_on] = parent.value;
        }
        const opts = await options(f.fk, flt, Array.isArray(value) ? '' : value);
        fillSelect(sel, opts, value, f.type === 'multi' ? null : '—');
      }
    } catch (e) { /* option load failures are non-fatal */ }
  }

  function wireField(f, scope, prefix = 'fld-') {
    const el = scope.querySelector(`#${prefix}${f.name}`) || scope.querySelector(`[data-f="${f.name}"]`);
    if (!el) return;
    if (f.type === 'date') maskDate(el, false);
    if (f.type === 'datetime') maskDate(el, true);
    if (['select', 'lookup', 'fk', 'multi'].includes(f.type)) loadOptions(f, el, undefined, scope);
    if (f.upper && el.tagName === 'INPUT') el.addEventListener('input', () => { const p = el.selectionStart; el.value = el.value.toUpperCase(); try { el.setSelectionRange(p, p); } catch (_) { } });
    // dependent dropdowns
    const deps = M.fields.concat(...M.children.map(c => c.fields)).filter(x => x.depends_on === f.name);
    if (deps.length) el.addEventListener('change', () => deps.forEach(d => {
      const t = scope.querySelector(`[data-f="${d.name}"]`); if (t) loadOptions(d, t, t.value, scope);
    }));
    el.addEventListener('input', updateVsb);
    el.addEventListener('change', updateVsb);
  }

  function setVal(f, el, v) {
    if (!el) return;
    if (f.type === 'bool') el.checked = !!v;
    else if (f.type === 'date') el.value = ddmmyyyy(v);
    else if (f.type === 'datetime') el.value = ddmmyyyy(v) + (v && String(v).length > 10 && !/ \d\d:\d\d$/.test(ddmmyyyy(v)) ? ' ' + String(v).slice(11, 16) : '');
    else if (f.type === 'time') el.value = v ? String(v).slice(0, 5) : '';
    else if (f.type === 'json') { const t = v ? JSON.stringify(v, null, el.tagName === 'TEXTAREA' ? 2 : 1) : ''; if (el.tagName === 'TEXTAREA') el.value = t; else el.textContent = t; }
    else if (['select', 'lookup', 'fk', 'multi'].includes(f.type)) {
      if (f.type === 'fk' && v && !$$('option', el).some(o => o.value === String(v))) loadOptions(f, el, v, el.closest('form,.vnd-form-wrap,.m-body,tr') || document);
      else if (Array.isArray(v)) $$('option', el).forEach(o => o.selected = v.map(String).includes(o.value));
      else el.value = v === null || v === undefined ? '' : String(v);
      if (f.type === 'fk' || f.type === 'lookup' || f.type === 'multi') el.dataset.pending = JSON.stringify(v ?? '');
    }
    else if (f.type === 'money' && v !== null && v !== undefined && v !== '') el.value = Number(v).toFixed(2);
    else el.value = v === null || v === undefined ? '' : v;
  }

  function getVal(f, el) {
    if (!el) return undefined;
    if (f.type === 'bool') return el.checked;
    if (f.type === 'multi') return $$('option', el).filter(o => o.selected).map(o => o.value);
    const v = (el.value || '').trim();
    if (['int', 'decimal', 'money'].includes(f.type)) return v.replace(/,/g, '') || null;
    return v === '' ? null : v;
  }

  // ───────────────────────── child grids ─────────────────────────
  function childHtml(c) {
    return `<div class="vnd-section" id="child-${c.key}"><div class="vnd-section-head"><span class="sh-title"><i class="ti ti-list-details"></i> ${esc(c.label)}</span>
      <i class="ti ti-chevron-down sh-chevron"></i></div><div class="vnd-section-body"><div class="child-wrap"><table class="child-tbl"><thead><tr>
      ${c.fields.map(f => `<th>${esc(f.label)}${f.required ? ' <span style="color:#DC2626">*</span>' : ''}</th>`).join('')}<th></th></tr></thead>
      <tbody id="rows-${c.key}"></tbody></table></div>
      <div class="child-foot"><button type="button" class="ra-btn ra-edit" id="add-${c.key}"><i class="ti ti-plus"></i> Add line</button><span id="sum-${c.key}"></span></div></div></div>`;
  }
  function addChildRow(c, data) {
    const tb = $(`#rows-${c.key}`);
    const tr = document.createElement('tr');
    tr.innerHTML = c.fields.map(f => `<td>${fieldHtml(f, `c-${c.key}-${tb.children.length}-`, true)}</td>`).join('') +
      `<td class="rm"><button type="button" class="ra-btn ra-del" title="Remove"><i class="ti ti-x"></i></button></td>`;
    tb.appendChild(tr);
    tr.querySelector('.ra-del').onclick = () => { tr.remove(); childSum(c); };
    for (const f of c.fields) {
      const el = tr.querySelector(`[data-f="${f.name}"]`);
      if (f.type === 'date') maskDate(el, false);
      if (['select', 'lookup', 'fk'].includes(f.type)) loadOptions(f, el, data[f.name] ?? f.default, tr);
      setVal(f, el, data[f.name] ?? f.default);
      el.addEventListener('input', () => childSum(c));
    }
    setEditable(S.mode !== 'VIEW');
    childSum(c);
  }
  function childSum(c) {
    const mf = c.fields.find(f => f.type === 'money' && f.name === 'amount');
    const out = $(`#sum-${c.key}`);
    if (!mf || !out) return;
    const tot = $$(`#rows-${c.key} [data-f="amount"]`).reduce((a, el) => a + (parseFloat((el.value || '0').replace(/,/g, '')) || 0), 0);
    out.innerHTML = `Lines total: <b>₹ ${money(tot)}</b>`;
  }
  function collectChildren() {
    const out = {};
    for (const c of M.children) {
      if (c.readonly) continue;
      out[c.key] = $$(`#rows-${c.key} tr`).map(tr => {
        const r = {};
        for (const f of c.fields) r[f.name] = getVal(f, tr.querySelector(`[data-f="${f.name}"]`));
        return r;
      });
    }
    return out;
  }

  // ───────────────────────── modes ─────────────────────────
  function setEditable(on) {
    const edit = S.mode === 'EDIT';
    for (const f of M.fields) {
      const el = $(`#fld-${f.name}`);
      if (!el) continue;
      el.disabled = !on || f.readonly || (edit && f.readonly_on_edit);
    }
    $$('#form-wrap .child-tbl .f-input, #form-wrap .child-tbl input, #form-wrap .child-foot button, #form-wrap .child-tbl .ra-del').forEach(e => e.disabled = !on);
    $$('#ext-sections .f-input, #ext-sections input').forEach(e => e.disabled = !on);
  }
  function setMode(mode) {
    S.mode = mode;
    const show = (id, v) => { const e = $(id); if (e) e.style.display = v ? '' : 'none'; };
    const editing = mode === 'NEW' || mode === 'EDIT';
    $('#form-block').style.display = mode === 'LIST' ? 'none' : '';
    show('#btn-new', true);
    show('#btn-edit', mode === 'VIEW' && S.id && M.perms.edit);
    show('#btn-save', editing);
    show('#btn-cancel', !!S.id);
    show('#form-actions', editing);
    $$('.save-lbl').forEach(e => e.textContent = mode === 'EDIT' ? 'Update' : 'Save');
    $('#vsb').classList.toggle('show', !!S.id && mode !== 'LIST');
    const badge = $('#mode-badge');
    badge.textContent = { NEW: 'New entry', EDIT: 'Editing', VIEW: 'Viewing', LIST: 'Records' }[mode];
    badge.className = 'vnd-mode-badge vnd-mode-badge--' + mode.toLowerCase();
    $('#fb-hint').textContent = mode === 'NEW' ? 'Fill the form and press Save — the record appears in the table below.'
      : mode === 'EDIT' ? 'Change the fields and press Update, or Cancel to discard.' : mode === 'VIEW' ? 'Select another row below to open it.' : '';
    setEditable(mode === 'NEW' || mode === 'EDIT');
    updateVsb();
    if (EXT.onMode) EXT.onMode(api(), mode);
  }
  function clearForm() {
    for (const f of M.fields) {
      const el = $(`#fld-${f.name}`);
      if (el) setVal(f, el, f.default ?? null);
      setErr(f.name, '');
    }
    for (const c of M.children) $(`#rows-${c.key}`).innerHTML = '';
  }
  function doNew(focus = true) {
    S.id = null; S.rec = null;
    $$('#list-body tr.selected').forEach(tr => tr.classList.remove('selected'));
    clearForm();
    $('#vsb-details').innerHTML = ''; $('#vsb-strip').style.display = 'none';
    for (const [k, v] of Object.entries(S.filters)) {
      const f = M.fields.find(x => x.name === k); const el = $(`#fld-${k}`);
      if (f && el && !String(v).includes(',')) setVal(f, el, v);
    }
    for (const c of M.children) if (c.min_rows) addChildRow(c, {});
    setMode('NEW');
    if (EXT.onLoad) EXT.onLoad(api(), null);
    if (focus) {
      const first = M.fields.find(f => !f.readonly); first && $(`#fld-${first.name}`)?.focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }
  async function view(id, mode = 'VIEW') {
    try {
      const r = await get(`/api/masters/${KEY}/${id}`);
      S.id = id; S.rec = r;
      clearForm();
      for (const f of M.fields) setVal(f, $(`#fld-${f.name}`), r[f.name]);
      for (const c of M.children) (r[c.key] || []).forEach(row => addChildRow(c, row));
      setMode(mode);
      renderVsbDetails(r);
      if (EXT.onLoad) EXT.onLoad(api(), r);
      $$('#list-body tr').forEach(tr => tr.classList.toggle('selected', +tr.dataset.id === id));
      $('#form-block').classList.remove('fb-collapsed');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) { errToast(e); }
  }
  function doClose() {
    if (M.perms.create) return doNew(false);
    S.id = null; S.rec = null; clearForm(); setMode('LIST');
    $$('#list-body tr.selected').forEach(tr => tr.classList.remove('selected'));
  }

  function setErr(name, msg) {
    const el = $(`#fld-${name}`), er = $(`#fld-${name}-err`);
    if (el) el.classList.toggle('invalid', !!msg);
    if (er) er.textContent = msg || '';
  }

  function collect() {
    const data = {};
    for (const f of M.fields) {
      if (f.readonly || (S.mode === 'EDIT' && f.readonly_on_edit)) continue;
      const el = $(`#fld-${f.name}`);
      if (!el) continue;
      const v = getVal(f, el);
      if (f.type === 'password' && !v) continue;
      data[f.name] = v;
    }
    Object.assign(data, collectChildren());
    if (EXT.collect) EXT.collect(api(), data);
    return data;
  }

  async function doSave(extra = {}) {
    M.fields.forEach(f => setErr(f.name, ''));
    const data = { ...collect(), ...extra };
    const miss = M.fields.filter(f => f.required && !f.readonly && !(S.mode === 'EDIT' && f.readonly_on_edit) && f.type !== 'bool' &&
      (data[f.name] === null || data[f.name] === undefined || data[f.name] === ''));
    if (miss.length) { miss.forEach(f => setErr(f.name, 'Required')); return toast('Please fill the required fields', 'err'); }
    try {
      const r = S.id ? await put(`/api/masters/${KEY}/${S.id}`, data) : await post(`/api/masters/${KEY}`, data);
      toast(S.id ? 'Updated' : 'Saved');
      (r._warnings || []).forEach(w => toast(w, 'warn', 6000));
      await loadList();
      if (M.perms.create && !EXT.keepAfterSave) doNew(false); else await view(r.id);
      const tr = $(`#list-body tr[data-id="${r.id}"]`);
      if (tr) { tr.classList.add('flash'); setTimeout(() => tr.classList.remove('flash'), 2600); }
    } catch (e) { handleSaveError(e, reason => doSave({ ...extra, override: true, override_reason: reason, reason })); }
  }

  async function handleSaveError(e, retryWithReason) {
    const d = e.data || {};
    (d.errors || []).forEach(x => x.field && setErr(x.field.split('[')[0], x.message));
    if (d.override_permission && retryWithReason) {
      const reason = await confirmBox(d.detail, { title: 'Override required', okText: 'Override & save', danger: true, reason: true });
      if (reason) return retryWithReason(reason);
      return;
    }
    errToast(e);
  }

  // ───────────────────────── VSB summary bar ─────────────────────────
  function updateVsb() {
    const badge = $('#vsb-mode');
    const m = S.mode === 'NEW' ? 'new' : S.mode === 'EDIT' ? 'edit' : 'view';
    badge.className = 'vsb-bar-badge vsb-bar-badge--' + m; badge.textContent = S.mode;
    const val = n => { const f = M.fields.find(x => x.name === n); const el = $(`#fld-${n}`); if (!f || !el) return '';
      if (el.tagName === 'SELECT') { const o = el.options[el.selectedIndex]; return o && o.value ? o.textContent : ''; } return el.value || ''; };
    $('#vsb-id').textContent = M.code_field ? val(M.code_field) || (S.id ? '#' + S.id : '') : (S.id ? '#' + S.id : '');
    $('#vsb-name').textContent = val(M.title_field) || (S.mode === 'NEW' ? 'New ' + M.title : '');
    const nm = val(M.title_field) || (S.id ? '#' + S.id : '');
    $('#fb-title').textContent = S.mode === 'NEW' ? 'New entry' : S.mode === 'EDIT' ? `Edit — ${nm}` : S.mode === 'VIEW' ? `View — ${nm}` : 'Entry form';
    $('#vsb-sub').textContent = (M.subtitle_fields || []).map(val).filter(Boolean).join(' · ');
    const st = M.status_field && S.rec ? S.rec[M.status_field] : null;
    $('#vsb-status').innerHTML = st ? pill(st) : (S.rec && M.has_active ? (S.rec.is_active ? pill('ACTIVE') : pill('CANCELLED').replace('CANCELLED', 'INACTIVE')) : '');
    $('#vsb-actions').innerHTML = S.id ? actionButtons(S.rec, true) : '';
    wireActionButtons($('#vsb-actions'), S.rec);
  }
  function renderVsbDetails(r) {
    const secs = sections().filter(s => s.name !== 'Remarks' && s.name !== 'Override').slice(0, 6);
    $('#vsb-details').innerHTML = secs.map(s => `<div class="vsb-bar-sect"><div class="vsb-bar-sect-title"><i class="ti ${SEC_ICON[s.name] || 'ti-point'}"></i> ${esc(s.name)}</div>
      ${s.fields.filter(f => !f.virtual && f.type !== 'json' && f.type !== 'password' && f.type !== 'multi').slice(0, 7).map(f => {
        const v = fmtCell(f, r); return `<div class="vsb-r"><span class="vsb-k">${esc(f.label)}</span><span class="vsb-v ${v ? '' : 'empty'}">${v || '—'}</span></div>`;
      }).join('')}</div>`).join('');
    const strip = [];
    if (r.days_left !== undefined && r.days_left !== null) strip.push(`<div class="vsb-wss-item" style="color:${r.days_left < 0 ? '#B91C1C' : r.days_left <= 30 ? '#B45309' : '#047857'}"><i class="ti ti-hourglass"></i> ${r.days_left < 0 ? 'Expired ' + (-r.days_left) + ' day(s) ago' : r.days_left + ' day(s) to expiry'}</div>`);
    if (r.current_vehicle) strip.push(`<div class="vsb-wss-item" style="color:#4338CA"><i class="ti ti-truck"></i> ${esc(r.current_vehicle)} · ${esc(r.current_position || '')}</div>`);
    if (r.current_location) strip.push(`<div class="vsb-wss-item" style="color:#B45309"><i class="ti ti-building-warehouse"></i> ${esc(r.current_location)}</div>`);
    if (r.overdue_days) strip.push(`<div class="vsb-wss-item" style="color:#B91C1C"><i class="ti ti-clock-exclamation"></i> Overdue ${r.overdue_days} day(s)</div>`);
    if (r.roles_label) strip.push(`<div class="vsb-wss-item" style="color:#047857"><i class="ti ti-user-shield"></i> ${esc(r.roles_label)}</div>`);
    $('#vsb-strip').innerHTML = strip.join('');
    $('#vsb-strip').style.display = strip.length ? '' : 'none';
  }

  // ───────────────────────── list ─────────────────────────
  const listCols = () => M.fields.filter(f => f.list);
  async function renderListShell() {
    const filters = M.fields.filter(f => f.filter);
    $('#list-wrap').innerHTML = `
      <div class="vnd-list-head">
        <div class="search-wrap"><i class="ti ti-search" style="color:#94A3B8;font-size:.76rem"></i>
          <input class="search-inp" id="list-q" placeholder="Search…" value="${esc(S.q)}">
          <label class="show-inactive-label" title="Exact match"><input type="checkbox" id="list-exact"> exact</label></div>
        <span class="vnd-list-title">${esc(M.title)}</span>
        <div class="vnd-list-head-right">
          ${M.has_active ? `<select class="f-input" id="list-active" style="width:auto;font-size:.66rem"><option value="1">Active</option><option value="0">Inactive</option><option value="all">All</option></select>` : ''}
          <span class="list-count" id="list-count"></span>
          <button class="ra-btn ra-edit" id="exp-xlsx" title="Export Excel"><i class="ti ti-file-spreadsheet"></i> Excel</button>
          <button class="ra-btn ra-edit" id="exp-csv" title="Export CSV"><i class="ti ti-file-text"></i> CSV</button>
          <button class="ra-btn ra-edit" id="exp-pdf" title="Export PDF"><i class="ti ti-file-type-pdf"></i> PDF</button>
          <button class="ra-btn ra-edit" onclick="window.print()" title="Print"><i class="ti ti-printer"></i></button>
        </div></div>
      ${(filters.length || M.date_field) ? `<div class="list-filters" id="list-filters">
        ${M.date_field ? `<div class="f-group" style="min-width:110px"><label class="f-label">From</label><input class="f-input" id="flt-date_from" placeholder="DD/MM/YYYY"></div>
          <div class="f-group" style="min-width:110px"><label class="f-label">To</label><input class="f-input" id="flt-date_to" placeholder="DD/MM/YYYY"></div>` : ''}
        ${filters.map(f => `<div class="f-group"><label class="f-label">${esc(f.label)}</label>${f.type === 'bool' ?
          `<select class="f-input" data-flt="${f.name}"><option value="">All</option><option value="1">Yes</option><option value="0">No</option></select>` :
          ['fk', 'lookup', 'select'].includes(f.type) ? `<select class="f-input" data-flt="${f.name}"><option value="">All</option></select>` :
          `<input class="f-input" data-flt="${f.name}">`}</div>`).join('')}
        <button class="ra-btn ra-deact" id="flt-clear" style="margin-bottom:.1rem"><i class="ti ti-filter-off"></i> Clear</button></div>` : ''}
      <div class="vnd-table-scroll"><table class="vnd-table"><thead><tr>
        ${listCols().map(f => `<th class="sortable ${['int', 'decimal', 'money'].includes(f.type) ? 'num' : ''}" data-sort="${f.name}">${esc(f.label)} <i class="ti ti-arrows-sort" style="opacity:.5"></i></th>`).join('')}
        ${M.has_active ? '<th style="text-align:center">Active</th>' : ''}<th style="text-align:right">Actions</th></tr></thead>
        <tbody id="list-body"><tr><td colspan="99" class="tbl-empty">Loading…</td></tr></tbody></table></div>
      <div class="pager"><span id="pg-info"></span><div class="pg-btns">
        <button class="ra-btn ra-edit" id="pg-prev"><i class="ti ti-chevron-left"></i></button><span id="pg-no"></span>
        <button class="ra-btn ra-edit" id="pg-next"><i class="ti ti-chevron-right"></i></button>
        <select class="f-input" id="pg-size" style="width:auto;font-size:.66rem">${[25, 50, 100, 200, 500].map(n => `<option ${n === M.page_size ? 'selected' : ''}>${n}</option>`).join('')}</select></div></div>`;
    let t;
    $('#list-q').oninput = e => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value; S.page = 1; loadList(); }, 300); };
    $('#list-exact').onchange = () => { S.page = 1; loadList(); };
    if ($('#list-active')) $('#list-active').onchange = e => { S.active = e.target.value; S.page = 1; loadList(); };
    $('#pg-prev').onclick = () => { if (S.page > 1) { S.page--; loadList(); } };
    $('#pg-next').onclick = () => { S.page++; loadList(); };
    $('#pg-size').onchange = () => { S.page = 1; loadList(); };
    $$('th.sortable').forEach(th => th.onclick = () => {
      S.dir = S.sort === th.dataset.sort && S.dir === 'asc' ? 'desc' : 'asc'; S.sort = th.dataset.sort; loadList();
    });
    for (const f of filters) {
      const el = $(`[data-flt="${f.name}"]`);
      if (['fk', 'lookup', 'select'].includes(f.type)) {
        await loadOptions(f, el, undefined, document);
        el.options[0].textContent = 'All';
      }
      if (S.filters[f.name] !== undefined) {
        if (String(S.filters[f.name]).includes(',') && el.tagName === 'SELECT') {
          const o = document.createElement('option'); o.value = S.filters[f.name]; o.textContent = S.filters[f.name].replace(/_/g, ' ').replace(/,/g, ', '); el.appendChild(o);
        }
        el.value = S.filters[f.name];
      }
      el.onchange = () => { S.filters[f.name] = el.value; S.page = 1; loadList(); };
    }
    if (M.date_field) ['date_from', 'date_to'].forEach(k => { const el = $('#flt-' + k); maskDate(el); el.onchange = () => { S.extra[k] = el.value; S.page = 1; loadList(); }; });
    if ($('#flt-clear')) $('#flt-clear').onclick = () => { S.filters = {}; delete S.extra.date_from; delete S.extra.date_to; $$('[data-flt], #list-filters input').forEach(e => e.value = ''); S.page = 1; loadList(); };
    ['xlsx', 'csv', 'pdf'].forEach(fmt => $('#exp-' + fmt).onclick = () => ERP.download(`/api/masters/${KEY}/export?` + new URLSearchParams(ERP.clean({ ...params(), fmt }))));
  }
  function params() {
    const p = { page: S.page, size: $('#pg-size') ? $('#pg-size').value : M.page_size, sort: S.sort, dir: S.dir, q: S.q, active: S.active, ...S.extra };
    if ($('#list-exact') && $('#list-exact').checked) p.exact = 1;
    for (const [k, v] of Object.entries(S.filters)) if (v !== '' && v !== undefined) p['f_' + k] = v;
    return p;
  }
  function fmtCell(f, r) {
    const v = r[f.name];
    if (v === null || v === undefined || v === '') return '';
    if (r[f.name + '__label'] !== undefined) return esc(r[f.name + '__label']);
    switch (f.type) {
      case 'date': return ddmmyyyy(v);
      case 'datetime': return ddmmyyyy(v) + (String(v).length > 10 && !ddmmyyyy(v).includes(':') ? ' ' + String(v).slice(11, 16) : '');
      case 'money': return money(v);
      case 'decimal': return num(v, 3);
      case 'bool': return v ? '<i class="ti ti-check" style="color:#16A34A"></i>' : '<span style="color:#CBD5E1">—</span>';
      case 'json': return esc(JSON.stringify(v)).slice(0, 120);
      case 'select': return /status|recon|direction|severity|match|kind|resolved/i.test(f.name) ? pill(v) : esc(String(v).replace(/_/g, ' '));
      default: return /status$/.test(f.name) ? pill(v) : esc(v);
    }
  }
  async function loadList() {
    try {
      const data = await get(`/api/masters/${KEY}`, params());
      const cols = listCols();
      const body = $('#list-body');
      if (!data.items.length) body.innerHTML = `<tr><td colspan="99"><div class="tbl-empty"><i class="ti ti-database-off"></i>No records</div></td></tr>`;
      else body.innerHTML = data.items.map(r => `<tr data-id="${r.id}" class="clickable ${M.has_active && !r.is_active ? 'inactive' : ''} ${r.id === S.id ? 'selected' : ''}">
        ${cols.map(f => `<td class="${['int', 'decimal', 'money'].includes(f.type) ? 'num' : ''}">${fmtCell(f, r)}</td>`).join('')}
        ${M.has_active ? `<td style="text-align:center"><span class="v-dot ${r.is_active ? 'on' : 'off'}"></span></td>` : ''}
        <td style="text-align:right" class="no-print" onclick="event.stopPropagation()">${actionButtons(r, false)}</td></tr>`).join('');
      $$('#list-body tr.clickable').forEach(tr => {
        tr.onclick = () => view(+tr.dataset.id, M.perms.edit ? 'EDIT' : 'VIEW');
        const r = data.items.find(x => x.id === +tr.dataset.id);
        wireActionButtons(tr, r);
      });
      const pages = Math.max(1, Math.ceil(data.total / data.size));
      if (S.page > pages) { S.page = pages; return loadList(); }
      $('#list-count').textContent = `${data.total.toLocaleString('en-IN')} record(s)`;
      $('#pg-info').textContent = `Showing ${data.total ? (data.page - 1) * data.size + 1 : 0}–${Math.min(data.page * data.size, data.total)} of ${data.total.toLocaleString('en-IN')}`;
      $('#pg-no').textContent = `Page ${data.page} / ${pages}`;
      $('#pg-prev').disabled = data.page <= 1; $('#pg-next').disabled = data.page >= pages;
    } catch (e) { errToast(e); }
  }

  // ───────────────────────── row actions ─────────────────────────
  const visible = (a, r) => !a.visible_when || Object.entries(a.visible_when).every(([k, vals]) => vals.some(v => v === r[k] || String(v) === String(r[k])));
  function actionButtons(r, inBar) {
    if (!r) return '';
    const acts = M.actions.filter(a => a.allowed && visible(a, r));
    const b = [];
    if (!inBar && M.perms.edit) b.push(`<button class="ra-btn ra-edit" data-do="edit" title="Edit"><i class="ti ti-edit"></i></button>`);
    if (inBar) acts.slice(0, 4).forEach(a => b.push(`<button class="ra-btn ra-${a.style}" data-act="${a.key}"><i class="ti ${a.icon}"></i> ${esc(a.label)}</button>`));
    const more = [];
    if (!inBar) acts.forEach(a => more.push(`<button data-act="${a.key}"><i class="ti ${a.icon}"></i> ${esc(a.label)}</button>`));
    if (inBar) acts.slice(4).forEach(a => more.push(`<button data-act="${a.key}"><i class="ti ${a.icon}"></i> ${esc(a.label)}</button>`));
    if (M.documents) more.push(`<button data-do="docs"><i class="ti ti-paperclip"></i> Documents</button>`);
    if (M.perms.audit) more.push(`<button data-do="audit"><i class="ti ti-history"></i> Audit history</button>`);
    if (M.has_active && M.perms.edit) more.push(`<button data-do="toggle"><i class="ti ${r.is_active ? 'ti-toggle-left' : 'ti-toggle-right'}"></i> ${r.is_active ? 'Deactivate' : 'Activate'}</button>`);
    if (M.perms.delete) more.push(`<button data-do="delete" style="color:#991B1B"><i class="ti ti-trash"></i> Delete</button>`);
    if (more.length) b.push(`<span class="ra-more"><button class="ra-btn ra-edit" data-do="more"><i class="ti ti-dots"></i></button><div class="ra-menu">${more.join('')}</div></span>`);
    return `<div class="row-actions" style="justify-content:flex-end">${b.join('')}</div>`;
  }
  function wireActionButtons(scope, r) {
    if (!scope || !r) return;
    $$('[data-do]', scope).forEach(btn => btn.onclick = async ev => {
      ev.stopPropagation();
      const d = btn.dataset.do;
      if (d === 'more') { $$('.ra-menu.open').forEach(m => m !== btn.nextElementSibling && m.classList.remove('open')); btn.nextElementSibling.classList.toggle('open'); return; }
      $$('.ra-menu.open').forEach(m => m.classList.remove('open'));
      if (d === 'edit') return view(r.id, 'EDIT');
      if (d === 'docs') return docsModal(r);
      if (d === 'audit') return auditModal(r);
      if (d === 'toggle') {
        const reason = await confirmBox(`${r.is_active ? 'Deactivate' : 'Activate'} this record?`, { reason: r.is_active, danger: r.is_active });
        if (!reason) return;
        try { await post(`/api/masters/${KEY}/${r.id}/active`, { active: !r.is_active, reason: reason === true ? null : reason }); toast('Updated'); loadList(); if (S.id === r.id) view(r.id); }
        catch (e) { errToast(e); }
      }
      if (d === 'delete') {
        const reason = await confirmBox('Delete this record? Master data is soft-deleted and kept for history.', { danger: true, reason: true, okText: 'Delete' });
        if (!reason) return;
        try { await del(`/api/masters/${KEY}/${r.id}?reason=${encodeURIComponent(reason)}`); toast('Deleted'); if (S.id === r.id) doClose(); loadList(); }
        catch (e) { errToast(e); }
      }
    });
    $$('[data-act]', scope).forEach(btn => btn.onclick = ev => { ev.stopPropagation(); $$('.ra-menu.open').forEach(m => m.classList.remove('open')); actionModal(M.actions.find(a => a.key === btn.dataset.act), r); });
  }
  document.addEventListener('click', e => { if (!e.target.closest('.ra-more')) $$('.ra-menu.open').forEach(m => m.classList.remove('open')); });

  let _onActionDone = null;
  async function runAction(key, rid, actionKey, prefill = {}, onDone = null) {
    if (!M || KEY !== key) { KEY = key; EXT = {}; M = await get(`/api/masters/${key}/meta`); }
    const r = await get(`/api/masters/${key}/${rid}`);
    const a = M.actions.find(x => x.key === actionKey);
    if (!a) return toast('Action not available', 'err');
    if (!a.allowed) return toast('You do not have permission for this action', 'err');
    _onActionDone = onDone;
    actionModal(a, r, prefill);
  }
  async function afterAction(r, res) {
    if ($('#list-body')) await loadList();
    if ($('#form-wrap') && (S.id === r.id || res.new_id)) view(res.new_id || r.id);
    if (_onActionDone) _onActionDone(res);
  }

  function actionModal(a, r, extra = {}) {
    const f2 = a.fields;
    const body = (a.confirm ? `<p>${esc(a.confirm)}</p>` : '') + (f2.length ? `<div class="fg2">${f2.map(f => fieldHtml({ ...f, readonly: false }, 'act-')).join('')}</div>` : '');
    const m = modal({ title: `${a.label} — ${r._label || '#' + r.id}`, icon: a.icon, size: f2.length > 6 ? 'wide' : '', body: body || '<p>Proceed?</p>',
      foot: `<button class="m-btn m-btn--cancel" data-x>Cancel</button><button class="m-btn m-btn--save" data-go><i class="ti ti-check"></i> ${esc(a.label)}</button>` });
    for (const f of f2) {
      const el = m.body.querySelector(`#act-${f.name}`);
      if (f.type === 'date') { maskDate(el); if (/date$/.test(f.name) || f.name === 'date') el.value = ERP.todayStr(); }
      if (f.type === 'datetime') { maskDate(el, true); if (f.required || f.name === 'date') el.value = ERP.nowStr(); }
      if (['select', 'lookup', 'fk'].includes(f.type)) {
        loadOptions(f, el, extra[f.name], m.body);
        const deps = f2.filter(x => x.depends_on === f.name);
        if (deps.length) el.addEventListener('change', () => deps.forEach(d => loadOptions(d, m.body.querySelector(`#act-${d.name}`), undefined, m.body)));
      }
      if (extra[f.name] !== undefined) { if (['fk', 'select', 'lookup'].includes(f.type)) loadOptions(f, el, extra[f.name], m.body).then(() => setVal(f, el, extra[f.name])); else setVal(f, el, extra[f.name]); }
    }
    m.el.querySelector('[data-x]').onclick = m.close;
    m.el.querySelector('[data-go]').onclick = async () => {
      const data = {};
      let bad = false;
      for (const f of f2) {
        const el = m.body.querySelector(`#act-${f.name}`);
        data[f.name] = getVal(f, el);
        const miss = f.required && (data[f.name] === null || data[f.name] === '');
        el.classList.toggle('invalid', miss); bad = bad || miss;
      }
      if (bad) return toast('Please fill the required fields', 'err');
      Object.assign(data, extra._override || {});
      try {
        const res = await post(`/api/masters/${KEY}/${r.id}/actions/${a.key}`, data);
        m.close();
        toast(res.message || 'Done');
        (res.warnings || []).forEach(w => toast(w, 'warn', 6000));
        await afterAction(r, res);
      } catch (e) {
        const d = e.data || {};
        (d.errors || []).forEach(x => { const el = m.body.querySelector(`#act-${x.field}`); if (el) { el.classList.add('invalid'); const er = m.body.querySelector(`#act-${x.field}-err`); if (er) er.textContent = x.message; } });
        if (d.override_permission) {
          const reason = await confirmBox(d.detail, { title: 'Override required', okText: 'Override', danger: true, reason: true });
          if (reason) {
            data.override = true; data.reason = reason; data.override_reason = reason;
            try { const res = await post(`/api/masters/${KEY}/${r.id}/actions/${a.key}`, data); m.close(); toast(res.message || 'Done'); (res.warnings || []).forEach(w => toast(w, 'warn', 6000)); await afterAction(r, res); }
            catch (e2) { errToast(e2); }
          }
          return;
        }
        errToast(e);
      }
    };
  }

  // ───────────────────────── documents / audit ─────────────────────────
  async function docsModal(r) {
    const m = modal({ title: `Documents — ${r._label || '#' + r.id}`, icon: 'ti-paperclip', size: 'wide', body: `
      <div id="doc-list"><div class="tbl-empty">Loading…</div></div>
      ${M.perms.edit ? `<div class="vnd-section" style="margin-top:.6rem"><div class="vnd-section-head"><span class="sh-title"><i class="ti ti-upload"></i> Upload</span></div>
      <div class="vnd-section-body"><div class="fg4">
        <div class="f-group"><label class="f-label">Document Type <span class="req">*</span></label><select class="f-input" id="doc-type"></select></div>
        <div class="f-group span2"><label class="f-label">File <span class="req">*</span> <span class="hint">(pdf, jpg, png, xlsx, docx … max size enforced)</span></label><input type="file" class="f-input" id="doc-file"></div>
        <div class="f-group"><label class="f-label">Replaces (new version of)</label><select class="f-input" id="doc-replaces"><option value="">— new document —</option></select></div>
        <div class="f-group full"><label class="f-label">Remarks</label><input class="f-input" id="doc-remarks"></div></div>
        <button class="m-btn m-btn--save" id="doc-up" style="margin-top:.3rem"><i class="ti ti-upload"></i> Upload</button></div></div>` : ''}` });
    const et = M.entity_type;
    const load = async () => {
      const docs = await get('/api/documents', { entity_type: et, entity_id: r.id });
      $('#doc-list', m.el).innerHTML = docs.length ? `<table class="vnd-table"><thead><tr><th>File</th><th>Type</th><th>Ver.</th><th>Size</th><th>Uploaded</th><th>Remarks</th><th></th></tr></thead><tbody>
        ${docs.map(d => `<tr><td><a href="/api/documents/${d.id}/download?inline=true" target="_blank" rel="noopener">${esc(d.file_name)}</a></td><td>${esc(d.document_type)}</td><td>${d.version}</td>
          <td>${num(d.size_bytes / 1024, 1)} KB</td><td>${ddmmyyyy(d.uploaded_at)}</td><td>${esc(d.remarks || '')}</td>
          <td><a class="ra-btn ra-edit" href="/api/documents/${d.id}/download"><i class="ti ti-download"></i></a>
          ${M.perms.edit ? `<button class="ra-btn ra-del" data-rm="${d.id}"><i class="ti ti-trash"></i></button>` : ''}</td></tr>`).join('')}</tbody></table>`
        : '<div class="tbl-empty"><i class="ti ti-file-off"></i>No documents attached</div>';
      $$('[data-rm]', m.el).forEach(b => b.onclick = async () => {
        const reason = await confirmBox('Remove this document? (It is kept in history.)', { danger: true, reason: true });
        if (reason) { await ERP.api(`/api/documents/${b.dataset.rm}?reason=${encodeURIComponent(reason)}`, { method: 'DELETE' }); load(); }
      });
      const rep = $('#doc-replaces', m.el);
      if (rep) fillSelect(rep, docs.map(d => ({ id: d.id, label: `${d.file_name} (v${d.version})` })), '', '— new document —');
    };
    load().catch(errToast);
    if ($('#doc-type', m.el)) {
      fillSelect($('#doc-type', m.el), (await lookups('DOCUMENT_TYPE')).map(l => ({ id: l.code, label: l.label })), '');
      $('#doc-up', m.el).onclick = async () => {
        const f = $('#doc-file', m.el).files[0], t = $('#doc-type', m.el).value;
        if (!f || !t) return toast('Choose a document type and a file', 'err');
        const fd = new FormData();
        fd.append('entity_type', et); fd.append('entity_id', r.id); fd.append('document_type', t); fd.append('file', f);
        fd.append('remarks', $('#doc-remarks', m.el).value);
        if ($('#doc-replaces', m.el).value) fd.append('replaces_id', $('#doc-replaces', m.el).value);
        try { await ERP.api('/api/documents', { method: 'POST', body: fd }); toast('Uploaded'); $('#doc-file', m.el).value = ''; load(); } catch (e) { errToast(e); }
      };
    }
  }
  async function auditModal(r) {
    const m = modal({ title: `Audit history — ${r._label || '#' + r.id}`, icon: 'ti-history', size: 'wide', body: '<div class="tbl-empty">Loading…</div>' });
    try {
      const rows = await get(`/api/masters/${KEY}/${r.id}/audit`);
      m.body.innerHTML = rows.length ? `<table class="vnd-table"><thead><tr><th>When</th><th>User</th><th>Action</th><th>Changes</th><th>Reason</th></tr></thead><tbody>
        ${rows.map(a => `<tr><td style="white-space:nowrap">${ERP.dt(a.created_at)}</td><td>${esc(a.username)}</td><td>${pill(a.action)}</td>
        <td style="font-size:.66rem">${diffHtml(a.old_values, a.new_values)}</td><td>${esc(a.reason || '')}</td></tr>`).join('')}</tbody></table>`
        : '<div class="tbl-empty">No history</div>';
    } catch (e) { m.close(); errToast(e); }
  }
  function diffHtml(o, n) {
    o = o || {}; n = n || {};
    const keys = [...new Set([...Object.keys(o), ...Object.keys(n)])].filter(k => !k.startsWith('__') && !['updated_at', 'created_at'].includes(k)).slice(0, 14);
    return keys.map(k => `<div><b>${esc(k)}</b>: ${o[k] !== undefined ? `<span style="color:#B91C1C;text-decoration:line-through">${esc(JSON.stringify(o[k]))}</span> → ` : ''}<span style="color:#047857">${esc(JSON.stringify(n[k]))}</span></div>`).join('') || '—';
  }

  function api() { return { M, S, KEY, $, view, loadList, setVal, getVal, setMode, fieldHtml }; }
  return { init, view, loadList, api, runAction };
})();
