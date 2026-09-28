/* TRANS ERP — shared client helpers (no framework; server-rendered pages + REST) */
'use strict';
const ERP = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = v => (v === null || v === undefined) ? '' : String(v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const cookie = n => (document.cookie.split('; ').find(c => c.startsWith(n + '=')) || '').split('=').slice(1).join('=');

  // ── API with CSRF double-submit token ──────────────────────────
  async function api(url, opts = {}) {
    const o = { method: 'GET', credentials: 'same-origin', headers: {}, ...opts };
    if (o.body && !(o.body instanceof FormData) && typeof o.body !== 'string') {
      o.body = JSON.stringify(o.body); o.headers['Content-Type'] = 'application/json';
    }
    if (o.method !== 'GET') o.headers['X-CSRF-Token'] = decodeURIComponent(cookie('erp_csrf'));
    const r = await fetch(url, o);
    if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search); throw new Error('Not authenticated'); }
    const ct = r.headers.get('content-type') || '';
    const data = ct.includes('json') ? await r.json() : await r.text();
    if (!r.ok) { const e = new Error((data && data.detail) || r.statusText); e.data = data; e.status = r.status; throw e; }
    return data;
  }
  const get = (u, p) => api(p ? u + '?' + new URLSearchParams(clean(p)) : u);
  const post = (u, b) => api(u, { method: 'POST', body: b || {} });
  const put = (u, b) => api(u, { method: 'PUT', body: b });
  const del = u => api(u, { method: 'DELETE' });
  const clean = o => Object.fromEntries(Object.entries(o || {}).filter(([, v]) => v !== '' && v !== null && v !== undefined));

  // ── toast ──────────────────────────────────────────────────────
  let _tt;
  function toast(msg, kind = 'ok', ms = 3800) {
    let t = $('#vnd-toast');
    if (!t) { t = document.createElement('div'); t.id = 'vnd-toast'; t.className = 'vnd-toast'; document.body.appendChild(t); }
    const icon = kind === 'ok' ? 'ti-circle-check' : kind === 'warn' ? 'ti-alert-triangle' : 'ti-alert-circle';
    t.className = 'vnd-toast ' + kind; t.innerHTML = `<i class="ti ${icon}"></i><span>${esc(msg)}</span>`; t.style.display = 'flex';
    clearTimeout(_tt); _tt = setTimeout(() => t.style.display = 'none', ms);
  }
  function errToast(e) {
    const d = e && e.data;
    let msg = (d && d.detail) || (e && e.message) || 'Error';
    if (d && d.errors && d.errors.length) msg += '\n• ' + d.errors.slice(0, 6).map(x => x.message || x).join('\n• ');
    toast(msg, 'err', 7000);
  }

  // ── modal ──────────────────────────────────────────────────────
  function modal({ title, icon = 'ti-forms', body = '', foot = '', size = '' }) {
    const bg = document.createElement('div');
    bg.className = 'vnd-modal-bg open';
    bg.innerHTML = `<div class="vnd-modal ${size}" role="dialog" aria-modal="true">
      <div class="m-head"><i class="ti ${icon}"></i><h3>${esc(title)}</h3><button class="m-x" aria-label="Close">&times;</button></div>
      <div class="m-body">${body}</div>${foot ? `<div class="m-foot">${foot}</div>` : ''}</div>`;
    document.body.appendChild(bg);
    const close = () => bg.remove();
    $('.m-x', bg).onclick = close;
    bg.addEventListener('mousedown', ev => { if (ev.target === bg) close(); });
    document.addEventListener('keydown', function k(ev) { if (ev.key === 'Escape') { close(); document.removeEventListener('keydown', k); } });
    return { el: bg, body: $('.m-body', bg), close };
  }
  function confirmBox(message, { title = 'Confirm', okText = 'Yes', danger = false, reason = false } = {}) {
    return new Promise(res => {
      const m = modal({
        title, icon: danger ? 'ti-alert-triangle' : 'ti-help', body: `<p>${esc(message)}</p>` +
          (reason ? `<div class="f-group"><label class="f-label">Reason <span class="req">*</span></label><textarea class="f-input" id="cf-reason"></textarea></div>` : ''),
        foot: `<button class="m-btn m-btn--cancel" data-a="no">Cancel</button><button class="m-btn ${danger ? 'm-btn--del' : 'm-btn--ok'}" data-a="yes">${esc(okText)}</button>`
      });
      m.el.querySelector('[data-a=no]').onclick = () => { m.close(); res(false); };
      m.el.querySelector('[data-a=yes]').onclick = () => {
        if (reason) { const r = $('#cf-reason', m.el).value.trim(); if (!r) { $('#cf-reason', m.el).classList.add('invalid'); return; } m.close(); res(r); }
        else { m.close(); res(true); }
      };
    });
  }

  // ── formatting (Indian grouping, DD/MM/YYYY) ────────────────────
  const nf = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const money = v => (v === null || v === undefined || v === '') ? '' : nf.format(Number(v));
  const num = (v, d = 2) => (v === null || v === undefined || v === '') ? '' :
    new Intl.NumberFormat('en-IN', { maximumFractionDigits: d }).format(Number(v));
  function ddmmyyyy(v) {
    if (!v) return '';
    const s = String(v);
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
    if (!m) return s;
    const d = `${m[3]}/${m[2]}/${m[1]}`;
    return m[4] && !(m[4] === '00' && m[5] === '00') ? `${d} ${m[4]}:${m[5]}` : d;
  }
  const toIsoInput = v => v; // backend accepts DD/MM/YYYY directly
  const dt = v => v ? `${ddmmyyyy(String(v).slice(0, 10))} ${String(v).slice(11, 16)}`.trim() : '';

  // live DD/MM/YYYY [HH:MM] mask
  function maskDate(inp, withTime) {
    inp.addEventListener('input', () => {
      const d = inp.value.replace(/\D/g, '').slice(0, withTime ? 12 : 8);
      let o = d.slice(0, 2);
      if (d.length > 2) o += '/' + d.slice(2, 4);
      if (d.length > 4) o += '/' + d.slice(4, 8);
      if (withTime && d.length > 8) o += ' ' + d.slice(8, 10);
      if (withTime && d.length > 10) o += ':' + d.slice(10, 12);
      inp.value = o;
    });
    inp.addEventListener('blur', () => {
      if (!inp.value) return inp.classList.remove('invalid');
      const m = inp.value.match(/^(\d{2})\/(\d{2})\/(\d{4})(?: (\d{2}):(\d{2}))?$/);
      let ok = !!m;
      if (m) { const dt = new Date(+m[3], +m[2] - 1, +m[1]); ok = dt.getDate() === +m[1] && dt.getMonth() === +m[2] - 1; }
      inp.classList.toggle('invalid', !ok);
    });
  }
  function todayStr() { const d = new Date(); return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`; }
  function nowStr() { const d = new Date(); return todayStr() + ` ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; }
  function monthStartStr() { const d = new Date(); return `01/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`; }

  const STATUS_PILL = {
    ACTIVE: 'green', VALIDATED: 'green', MATCHED: 'green', ALLOCATED: 'green', PAID: 'green', COMPLETED: 'green', RENEWED: 'green',
    NOT_DUE: 'green', INSTALLED: 'green', FITTED_AFTER_RETREAD: 'green', APPROVED: 'green', IMPORTED: 'sky', VALID: 'green', RETURNED: 'green', SETTLED: 'green',
    UNMATCHED: 'red', EXPIRED: 'red', ERROR: 'red', VEHICLE_UNMATCHED: 'red', FAILED: 'red', REJECTED: 'red', CANCELLED: 'grey', SCRAPPED: 'grey', LOST: 'grey', SOLD: 'grey',
    PARTIALLY_MATCHED: 'amber', PARTIALLY_PAID: 'amber', UPCOMING: 'amber', DUE: 'amber', PENDING: 'amber', PENDING_APPROVAL: 'amber', FLAGGED: 'amber',
    PLAZA_UNMATCHED: 'amber', WARNING: 'amber', DUPLICATE: 'violet', AUTO_SUGGESTED: 'violet', OVERRIDDEN: 'violet', IGNORED: 'grey', REVERSED: 'grey',
    OPEN: 'blue', IN_PROGRESS: 'blue', PREVIEWED: 'blue', PROCESSING: 'blue', QUEUED: 'blue', NEW: 'blue', IN_STOCK: 'blue', IN_GODOWN: 'blue',
    REMOVED: 'amber', SHIFTED: 'green', SENT_FOR_RETREADING: 'violet', RETREADED: 'sky', DAMAGED: 'red', WARRANTY: 'violet', UNDER_INSPECTION: 'amber',
    OVERPAID: 'violet', COMPLETED_WITH_ERRORS: 'amber', VEHICLE_MATCHED: 'sky', UNCLASSIFIED: 'grey', SKIPPED: 'grey', CR: 'green', DR: 'red'
  };
  const pill = s => s ? `<span class="pill pill-${STATUS_PILL[s] || 'grey'}">${esc(String(s).replace(/_/g, ' '))}</span>` : '';

  // ── options cache for FK dropdowns ──────────────────────────────
  const _opt = {};
  async function options(key, filters = {}, includeId) {
    const qs = new URLSearchParams(clean({ limit: 500, ...filters, include_id: includeId || '' })).toString();
    const ck = key + '?' + qs;
    if (!_opt[ck]) _opt[ck] = get(`/api/masters/${key}/options?${qs}`).catch(e => { delete _opt[ck]; throw e; });
    return _opt[ck];
  }
  const _lk = {};
  async function lookups(cat) {
    if (!_lk[cat]) _lk[cat] = get('/api/masters/lookup_values', { f_category: cat, size: 500, sort: 'sort_order', dir: 'asc' }).then(r => r.items);
    return _lk[cat];
  }
  function fillSelect(sel, items, value, blank = '— Select —') {
    sel.innerHTML = (blank !== null ? `<option value="">${esc(blank)}</option>` : '') +
      items.map(o => `<option value="${esc(o.id ?? o.code)}">${esc(o.label)}</option>`).join('');
    if (value !== undefined && value !== null) {
      if (Array.isArray(value)) $$('option', sel).forEach(o => o.selected = value.map(String).includes(o.value));
      else sel.value = String(value);
    }
  }
  function download(url) { const a = document.createElement('a'); a.href = url; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); }

  // ── shell behaviours ───────────────────────────────────────────
  function initShell() {
    const btn = $('#side-toggle');
    if (btn) btn.onclick = () => {
      if (window.innerWidth <= 1000) document.body.classList.toggle('side-open');
      else document.body.classList.toggle('side-collapsed');
    };
    $$('.nav-group-h').forEach(h => h.onclick = () => {
      const g = h.parentElement; g.classList.toggle('closed');
      try { localStorage.setItem('nav:' + g.dataset.g, g.classList.contains('closed') ? '0' : '1'); } catch (_) { }
    });
    const here = location.pathname + location.search;
    let best = null;
    $$('.nav-items a').forEach(a => {
      const href = a.getAttribute('href');
      if (href === here || (href === location.pathname && !best)) best = a;
    });
    $$('.nav-group').forEach(g => {
      let open = null; try { open = localStorage.getItem('nav:' + g.dataset.g); } catch (_) { }
      if (open === '0') g.classList.add('closed');
    });
    if (best) { best.classList.add('active'); best.closest('.nav-group').classList.remove('closed'); }
    // unread alerts badge
    get('/api/notifications/unread-count').then(r => {
      const b = $('#notif-count'); if (b && r.count) { b.textContent = r.count > 99 ? '99+' : r.count; b.style.display = 'inline'; }
    }).catch(() => { });
    // global search
    const gs = $('#global-search'), res = $('#global-search-results');
    if (gs) {
      let tmr;
      gs.addEventListener('input', () => {
        clearTimeout(tmr);
        const q = gs.value.trim();
        if (q.length < 2) { res.style.display = 'none'; return; }
        tmr = setTimeout(async () => {
          try {
            const hits = await get('/api/search', { q });
            res.innerHTML = hits.length ? hits.map(h => `<a href="${esc(h.url)}"><span class="k">${esc(h.kind)}</span><span>${esc(h.label)}</span></a>`).join('')
              : '<div class="tbl-empty" style="padding:1rem">No matches</div>';
            res.style.display = 'block';
          } catch (e) { res.style.display = 'none'; }
        }, 250);
      });
      document.addEventListener('click', e => { if (!e.target.closest('.hdr-search')) res.style.display = 'none'; });
    }
    document.addEventListener('focusin', e => {
      if (e.target.matches('.f-input')) setTimeout(() => e.target.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 80);
    });
  }
  document.addEventListener('DOMContentLoaded', initShell);

  return { $, $$, esc, api, get, post, put, del, toast, errToast, modal, confirmBox, money, num, ddmmyyyy, dt, maskDate, todayStr, nowStr,
    monthStartStr, pill, options, lookups, fillSelect, download, clean, toIsoInput };
})();
