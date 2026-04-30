"""WOA audit PDF export — one-page calculation sheet per Work Order Adjustment."""

import tempfile, os
from fastapi.responses import FileResponse
from routers.accounting_calc import _SF_BASE
_BRAND = "#1E293B"
_GREEN = "#16A34A"
_AMBER = "#D97706"
_RED   = "#DC2626"
_MUTED = "#64748B"


def _rec_color(rec: str) -> str:
    r = (rec or '').upper()
    if r == 'APPROVE':  return _GREEN
    if r == 'DENY':     return _RED
    return _AMBER


def _fmt(v, suffix='') -> str:
    if v is None: return '—'
    if isinstance(v, float): return f"{v:,.2f}{suffix}"
    return f"{v}{suffix}"


def _reason_html(rec_reason: str) -> str:
    if not rec_reason:
        return '<p class="muted">No reasoning available.</p>'
    lines = rec_reason.strip().split('\n')
    out = []
    for ln in lines:
        ln = ln.rstrip()
        if not ln:
            out.append('<br>')
        elif ln.startswith('→'):
            out.append(f'<p class="conclusion">{ln}</p>')
        else:
            out.append(f'<p class="step">{ln}</p>')
    return '\n'.join(out)


def _timeline_rows(sa_timeline: list) -> str:
    if not sa_timeline:
        return '<tr><td colspan="4" class="muted" style="text-align:center">No timeline data</td></tr>'
    rows = []
    for t in sa_timeline:
        elapsed = ''
        s = t.get('elapsed_seconds')
        if s is not None:
            if s < 60: elapsed = f"{int(s)}s"
            else: elapsed = f"{int(s//60)}m {int(s%60)}s"
        rows.append(
            f'<tr><td>{t.get("time","")}</td>'
            f'<td>{t.get("from","")}</td>'
            f'<td><strong>{t.get("to","")}</strong></td>'
            f'<td class="muted">{elapsed}</td></tr>'
        )
    return '\n'.join(rows)


def _woli_rows(woli_items: list) -> str:
    if not woli_items:
        return '<tr><td colspan="5" class="muted" style="text-align:center">No line items</td></tr>'
    rows = []
    for w in woli_items:
        rows.append(
            f'<tr>'
            f'<td>{w.get("product","")}</td>'
            f'<td style="text-align:right">{_fmt(w.get("quantity"))}</td>'
            f'<td style="text-align:right">{_fmt(w.get("unit_price"), " /unit")}</td>'
            f'<td style="text-align:right">{_fmt(w.get("subtotal"), " $")}</td>'
            f'<td style="text-align:center"><span class="badge-sm">{w.get("status","")}</span></td>'
            f'</tr>'
        )
    return '\n'.join(rows)


def render_woa_pdf_html(d: dict) -> str:
    ev = d.get('evidence') or {}
    pricing = d.get('wo_pricing') or {}
    rec = (d.get('recommendation') or 'REVIEW').upper()
    rec_label = 'APPROVE' if rec == 'APPROVE' else ('DENY' if rec == 'DENY' else 'REVIEW')
    rec_col = _rec_color(rec)
    woa_url = (d.get('sf_urls') or {}).get('woa', '')
    wo_url  = (d.get('sf_urls') or {}).get('wo', '')

    product   = ev.get('product') or '—'
    requested = _fmt(ev.get('requested'))
    paid      = _fmt(ev.get('currently_paid'))
    qty_interp = ev.get('qty_interpretation') or ''
    city      = ev.get('call_location_city') or ''
    state     = ev.get('call_location_state') or ''
    location  = f"{city}, {state}".strip(', ') or '—'
    v_make    = ev.get('vehicle_make') or ''
    v_model   = ev.get('vehicle_model') or ''
    v_group   = ev.get('vehicle_group') or ''
    vehicle   = f"{v_make} {v_model}".strip() or '—'
    if v_group: vehicle += f" ({v_group})"
    garage_note = (ev.get('garage_note') or '').replace('\n', '<br>')

    sf_er     = _fmt(ev.get('sf_enroute_miles'), ' mi')
    sf_er_est = _fmt(ev.get('sf_estimated_miles'), ' mi')
    sf_tow    = _fmt(ev.get('sf_tow_miles'), ' mi')
    sf_tow_est= _fmt(ev.get('sf_estimated_tow_miles'), ' mi')
    on_loc    = _fmt(ev.get('on_location_minutes'), ' min')
    long_tow  = 'Yes' if ev.get('long_tow_used') else 'No'
    lt_miles  = _fmt(ev.get('long_tow_miles'), ' mi') if ev.get('long_tow_used') else '—'

    trouble   = ev.get('trouble_code') or '—'
    resol     = ev.get('resolution_code') or '—'
    coverage  = ev.get('coverage') or '—'
    contract  = ev.get('contract_name') or '—'
    axles     = _fmt(ev.get('axle_count'))
    weight    = _fmt(ev.get('vehicle_weight'), ' lbs')

    woa_sf_link = f'<a href="{woa_url}">{d.get("woa_number","")}</a>' if woa_url else d.get("woa_number", "")
    wo_sf_link  = f'<a href="{wo_url}">{ev.get("facility_id","")}</a>' if wo_url else ''

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 11px;
          color: #1E293B; background: #fff; padding: 24px; }}
  h1 {{ font-size: 18px; font-weight: 700; }}
  h2 {{ font-size: 13px; font-weight: 600; color: {_BRAND}; margin: 16px 0 6px; border-bottom: 1px solid #E2E8F0; padding-bottom: 3px; }}
  .header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }}
  .badge {{ display: inline-block; padding: 6px 18px; border-radius: 6px; font-size: 15px;
             font-weight: 700; color: #fff; background: {rec_col}; letter-spacing: 1px; }}
  .badge-sm {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; background: #E2E8F0; color: #334155; }}
  .meta {{ font-size: 10px; color: {_MUTED}; margin-top: 2px; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px 24px; margin-bottom: 8px; }}
  .grid3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px 16px; margin-bottom: 8px; }}
  .field {{ margin-bottom: 4px; }}
  .label {{ font-size: 9px; text-transform: uppercase; letter-spacing: .5px; color: {_MUTED}; }}
  .value {{ font-size: 11px; font-weight: 500; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; }}
  th {{ background: {_BRAND}; color: #fff; font-size: 10px; padding: 5px 8px; text-align: left; }}
  td {{ padding: 4px 8px; border-bottom: 1px solid #F1F5F9; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #F8FAFC; }}
  .step {{ color: #334155; line-height: 1.5; margin: 1px 0; }}
  .conclusion {{ color: {_GREEN}; font-weight: 600; margin: 4px 0 0; }}
  .muted {{ color: {_MUTED}; }}
  .note-box {{ background: #FFFBEB; border-left: 3px solid #F59E0B; padding: 8px 12px;
               border-radius: 0 4px 4px 0; margin-bottom: 8px; font-size: 10px; }}
  a {{ color: #2563EB; text-decoration: none; }}
  @page {{ size: A4; margin: 0; }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>WOA Audit Sheet — {woa_sf_link}</h1>
    <div class="meta">Facility: <strong>{d.get("facility","")}</strong> &nbsp;|&nbsp;
      Product: <strong>{product}</strong> &nbsp;|&nbsp;
      WO: {wo_sf_link}
    </div>
    <div class="meta" style="margin-top:4px">Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M ET')}</div>
  </div>
  <div style="text-align:right">
    <div class="badge">{rec_label}</div>
    <div class="meta" style="margin-top:4px">Confidence: {d.get("confidence","")}</div>
  </div>
</div>

<h2>Quantity &amp; Calculation</h2>
<div class="grid3">
  <div class="field"><div class="label">Requested (WOA)</div><div class="value">{requested}</div></div>
  <div class="field"><div class="label">Currently Paid (SF)</div><div class="value">{paid}</div></div>
  <div class="field"><div class="label">Interpretation</div><div class="value">{qty_interp}</div></div>
</div>
<div class="grid3">
  <div class="field"><div class="label">SF En Route (actual)</div><div class="value">{sf_er}</div></div>
  <div class="field"><div class="label">SF En Route (est)</div><div class="value">{sf_er_est}</div></div>
  <div class="field"><div class="label">On Location</div><div class="value">{on_loc}</div></div>
  <div class="field"><div class="label">SF Tow Miles (actual)</div><div class="value">{sf_tow}</div></div>
  <div class="field"><div class="label">SF Tow Miles (est)</div><div class="value">{sf_tow_est}</div></div>
  <div class="field"><div class="label">Long Tow / Miles</div><div class="value">{long_tow} / {lt_miles}</div></div>
</div>

<h2>Rule-Based Reasoning</h2>
{_reason_html(d.get("rec_reason",""))}

<h2>WO Line Items</h2>
<table>
  <tr><th>Product</th><th style="text-align:right">Qty</th><th style="text-align:right">Rate</th><th style="text-align:right">Subtotal</th><th style="text-align:center">Status</th></tr>
  {_woli_rows(d.get("woli_items") or [])}
</table>

<h2>Work Order Classification</h2>
<div class="grid3">
  <div class="field"><div class="label">Trouble Code</div><div class="value">{trouble}</div></div>
  <div class="field"><div class="label">Resolution Code</div><div class="value">{resol}</div></div>
  <div class="field"><div class="label">Coverage</div><div class="value">{coverage}</div></div>
  <div class="field"><div class="label">Contract</div><div class="value">{contract}</div></div>
  <div class="field"><div class="label">Axle Count</div><div class="value">{axles}</div></div>
  <div class="field"><div class="label">Vehicle Weight</div><div class="value">{weight}</div></div>
</div>

<h2>Vehicle &amp; Location</h2>
<div class="grid2">
  <div class="field"><div class="label">Vehicle</div><div class="value">{vehicle}</div></div>
  <div class="field"><div class="label">Call Location</div><div class="value">{location}</div></div>
</div>
{f'<div class="note-box"><strong>Garage Note:</strong> {garage_note}</div>' if ev.get("garage_note") else ""}

<h2>Status Timeline</h2>
<table>
  <tr><th>Time (ET)</th><th>From</th><th>To</th><th>Elapsed</th></tr>
  {_timeline_rows(d.get("sa_timeline") or [])}
</table>

<h2>WO Pricing</h2>
<div class="grid3">
  <div class="field"><div class="label">Basic Cost</div><div class="value">{_fmt(pricing.get("basic_cost"), " $")}</div></div>
  <div class="field"><div class="label">Plus Cost</div><div class="value">{_fmt(pricing.get("plus_cost"), " $")}</div></div>
  <div class="field"><div class="label">Other Cost</div><div class="value">{_fmt(pricing.get("other_cost"), " $")}</div></div>
  <div class="field"><div class="label">Tax</div><div class="value">{_fmt(pricing.get("tax"), " $")}</div></div>
  <div class="field"><div class="label">Grand Total</div><div class="value">{_fmt(pricing.get("grand_total"), " $")}</div></div>
  <div class="field"><div class="label">Total Invoiced</div><div class="value">{_fmt(pricing.get("total_invoiced"), " $")}</div></div>
</div>
</body>
</html>"""


def build_woa_pdf(d: dict) -> bytes:
    from weasyprint import HTML as _WP
    html = render_woa_pdf_html(d)
    return _WP(string=html, base_url=None).write_pdf()
