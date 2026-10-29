/* Trips screen: live freight total while typing, and links to the trip's e-way bills, advances, settlement and the
   e-way bill JSON for the GST portal. */
'use strict';
MasterExt.trips = (() => {
  const { $, esc, money, toast } = ERP;
  const num = id => parseFloat(($('#fld-' + id)?.value || '').replace(/,/g, '')) || 0;
  const MONEY = ['freight_amount', 'loading_charges', 'unloading_charges', 'detention_charges', 'other_charges', 'advance_received'];

  function recalc() {
    const basis = $('#fld-freight_basis')?.value;
    let freight = num('freight_amount');
    if (basis === 'PER_TONNE' || basis === 'PER_KM') {
      const qty = basis === 'PER_TONNE' ? num('weight_tonnes') : (num('actual_km') || num('planned_km'));
      freight = Math.round(num('freight_rate') * qty * 100) / 100;
      const f = $('#fld-freight_amount'); if (f && !f.disabled) f.value = freight ? freight.toFixed(2) : '';
    }
    const total = freight + num('loading_charges') + num('unloading_charges') + num('detention_charges') + num('other_charges');
    const t = $('#fld-total_freight'), b = $('#fld-balance_freight');
    if (t) t.value = money(total);
    if (b) b.value = money(total - num('advance_received'));
  }

  function afterForm() {
    for (const id of [...MONEY, 'freight_basis', 'freight_rate', 'weight_tonnes', 'planned_km']) {
      const el = $('#fld-' + id);
      if (el) { el.addEventListener('input', recalc); el.addEventListener('change', recalc); }
    }
  }

  function onLoad(a, rec) {
    let box = $('#tp-links');
    if (!box) { box = document.createElement('span'); box.id = 'tp-links'; box.className = 'tp-links'; $('#fb-hint').after(box); }
    if (!rec) { box.innerHTML = ''; return; }
    const id = rec.id;
    box.innerHTML = `
      <a href="/masters/eway_bills?f_trip_id=${id}"><i class="ti ti-file-certificate"></i> E-way bill${rec.eway_bill ? ` ${esc(rec.eway_bill)}` : 's'}</a>
      <a href="#" id="tp-ewb-json" title="E-way bill details in the GST portal's bulk-upload JSON layout"><i class="ti ti-download"></i> E-way JSON</a>
      <a href="/masters/driver_advances?f_trip_id=${id}"><i class="ti ti-cash-banknote"></i> Advances</a>
      <a href="/masters/driver_settlements?f_trip_id=${id}"><i class="ti ti-receipt-rupee"></i> Settlement</a>`;
    $('#tp-ewb-json').onclick = async e => {
      e.preventDefault();
      try {
        const r = await fetch(`/api/trips/${id}/eway-json`, { credentials: 'same-origin' });
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        const missing = r.headers.get('X-Missing-Fields');
        const blob = await r.blob(), url = URL.createObjectURL(blob), link = document.createElement('a');
        link.href = url; link.download = `ewaybill_${(rec.trip_number || id).replace(/\//g, '-')}.json`;
        document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
        if (missing) toast('Downloaded — fill these before uploading to the GST portal: ' + missing.replace(/,/g, ', '), 'warn', 8000);
      } catch (err) { toast(err.message, 'err'); }
    };
    recalc();
  }
  return { afterForm, onLoad };
})();
