"""Accounting WOA export — Excel with formatted table + dashboard tab."""

import tempfile, os
from collections import Counter, defaultdict
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.utils import get_column_letter
from fastapi.responses import FileResponse

_SF_BASE = "https://aaawcny.lightning.force.com"


def build_export(items: list, status: str) -> FileResponse:
    """Build a formatted Excel workbook with data table + dashboard."""
    wb = Workbook()
    hdr_font = Font(bold=True, size=11, color='FFFFFF')
    hdr_fill = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')
    green_fill = PatternFill(start_color='D1FAE5', end_color='D1FAE5', fill_type='solid')
    amber_fill = PatternFill(start_color='FEF3C7', end_color='FEF3C7', fill_type='solid')
    link_font = Font(color='0563C1', underline='single', size=10)
    bdr = Border(left=Side(style='thin', color='CBD5E1'), right=Side(style='thin', color='CBD5E1'),
                 top=Side(style='thin', color='CBD5E1'), bottom=Side(style='thin', color='CBD5E1'))
    num_fmt = '#,##0.00'

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1: WO Adjustments
    # ═══════════════════════════════════════════════════════════════════════════
    ws = wb.active
    ws.title = 'WO Adjustments'
    headers = ['#', 'WOA #', 'WOA URL', 'Facility', 'WO #', 'WO URL', 'Product',
               'Requested', 'SF Billed', 'Delta', 'Recommendation', 'Reason',
               'SF Google Est', 'SF Recorded', 'Vehicle', 'WO Line Items',
               'Created', 'Created By']
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = hdr_font; c.fill = hdr_fill; c.border = bdr
        c.alignment = Alignment(horizontal='center', wrap_text=True)

    for idx, r in enumerate(items, 2):
        paid = r.get('currently_paid') or 0
        req = r.get('requested_qty') or 0
        delta = req - paid if paid > 0 else req
        rec = (r.get('recommendation') or '').upper()
        sf = r.get('sf_miles', {}) if isinstance(r.get('sf_miles'), dict) else {}
        ws.cell(row=idx, column=1, value=idx - 1).border = bdr
        ws.cell(row=idx, column=2, value=r.get('woa_number', '')).border = bdr
        url_c = ws.cell(row=idx, column=3, value=f'{_SF_BASE}/{r.get("id","")}')
        url_c.hyperlink = f'{_SF_BASE}/{r.get("id","")}'; url_c.font = link_font; url_c.border = bdr
        ws.cell(row=idx, column=4, value=r.get('facility', '')).border = bdr
        ws.cell(row=idx, column=5, value=r.get('wo_number', '')).border = bdr
        wo_c = ws.cell(row=idx, column=6, value=f'{_SF_BASE}/{r.get("wo_id","")}')
        wo_c.hyperlink = f'{_SF_BASE}/{r.get("wo_id","")}'; wo_c.font = link_font; wo_c.border = bdr
        ws.cell(row=idx, column=7, value=r.get('product', '') or 'No WOLI').border = bdr
        c8 = ws.cell(row=idx, column=8, value=req); c8.border = bdr; c8.number_format = num_fmt
        c9 = ws.cell(row=idx, column=9, value=paid); c9.border = bdr; c9.number_format = num_fmt
        c10 = ws.cell(row=idx, column=10, value=round(delta, 2)); c10.border = bdr; c10.number_format = num_fmt
        rec_c = ws.cell(row=idx, column=11, value='Approve' if rec == 'APPROVE' else 'Review')
        rec_c.fill = green_fill if rec == 'APPROVE' else amber_fill; rec_c.border = bdr
        reason_lines = (r.get('rec_reason') or '').strip().split('\n')
        conclusion = next((l.strip().lstrip('→').strip() for l in reversed(reason_lines) if '→' in l), '')
        if not conclusion:
            conclusion = next((l.strip() for l in reversed(reason_lines) if l.strip()), '')
        ws.cell(row=idx, column=12, value=conclusion).border = bdr
        ws.cell(row=idx, column=13, value=sf.get('estimated_enroute') or sf.get('estimated_tow') or '').border = bdr
        ws.cell(row=idx, column=14, value=sf.get('enroute') or sf.get('tow') or '').border = bdr
        v = r.get('vehicle', {}) if isinstance(r.get('vehicle'), dict) else {}
        veh_str = f'{v.get("make","")} {v.get("model","")} ({v.get("group","")})'.strip() if v.get('make') else ''
        ws.cell(row=idx, column=15, value=veh_str).border = bdr
        ws.cell(row=idx, column=16, value=r.get('woli_summary', '')).border = bdr
        ws.cell(row=idx, column=17, value=r.get('created_date', '')).border = bdr
        ws.cell(row=idx, column=18, value=r.get('created_by', '')).border = bdr

    widths = [5, 14, 55, 30, 12, 55, 28, 12, 12, 12, 14, 70, 14, 14, 25, 40, 12, 20]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:{get_column_letter(len(headers))}{len(items) + 1}'

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 2: Dashboard — KPIs, charts, breakdowns
    # ═══════════════════════════════════════════════════════════════════════════
    ds = wb.create_sheet('Dashboard')
    title_font = Font(bold=True, size=14, color='1E293B')
    section_font = Font(bold=True, size=12, color='334155')
    kpi_font = Font(bold=True, size=18, color='1E293B')
    kpi_label = Font(size=10, color='64748B')
    kpi_fill = PatternFill(start_color='F1F5F9', end_color='F1F5F9', fill_type='solid')

    total = len(items)
    approves = sum(1 for r in items if r.get('recommendation') == 'approve')
    reviews = total - approves
    total_req = sum(r.get('requested_qty') or 0 for r in items)
    total_paid = sum(r.get('currently_paid') or 0 for r in items if r.get('currently_paid'))
    total_delta = total_req - total_paid
    credits = sum(1 for r in items if (r.get('requested_qty') or 0) < 0)

    # Product breakdown data
    prod_counts, prod_approve, prod_req, prod_delta = Counter(), Counter(), defaultdict(float), defaultdict(float)
    for r in items:
        p = r.get('product', '') or '--'
        code = p.split(' - ')[0].strip() if ' - ' in p else p
        prod_counts[code] += 1
        if r.get('recommendation') == 'approve': prod_approve[code] += 1
        prod_req[code] += r.get('requested_qty') or 0
        paid = r.get('currently_paid') or 0
        prod_delta[code] += (r.get('requested_qty') or 0) - paid if paid > 0 else (r.get('requested_qty') or 0)

    # Facility breakdown data
    fac_counts, fac_req = Counter(), defaultdict(float)
    for r in items:
        f = r.get('facility', '') or 'Unknown'
        fac_counts[f] += 1; fac_req[f] += r.get('requested_qty') or 0

    # ── KPI Row ──
    ds.cell(row=1, column=1, value='WO Adjustment Dashboard').font = title_font
    ds.merge_cells('A1:H1')
    kpi_data = [('Total WOAs', total), ('Approve', approves), ('Review', reviews),
                ('Approve %', f'{approves * 100 // total}%' if total else '0%'),
                ('Credits', credits), ('Total Requested', round(total_req, 2)),
                ('Total SF Billed', round(total_paid, 2)), ('Outstanding Delta', round(total_delta, 2))]
    for i, (label, val) in enumerate(kpi_data):
        col = i + 1
        c = ds.cell(row=3, column=col, value=val)
        c.font = kpi_font; c.fill = kpi_fill; c.alignment = Alignment(horizontal='center'); c.border = bdr
        if isinstance(val, float): c.number_format = '#,##0.00'
        lc = ds.cell(row=4, column=col, value=label)
        lc.font = kpi_label; lc.alignment = Alignment(horizontal='center')
        ds.column_dimensions[get_column_letter(col)].width = 16

    # ── Product Breakdown ──
    row = 6
    ds.cell(row=row, column=1, value='By Product').font = section_font; row += 1
    for i, h in enumerate(['Product', 'Count', 'Approve', 'Review', 'Approve %', 'Total Requested', 'Total Delta'], 1):
        c = ds.cell(row=row, column=i, value=h); c.font = hdr_font; c.fill = hdr_fill; c.border = bdr
    prod_start = row + 1
    for code, cnt in prod_counts.most_common():
        row += 1; appr = prod_approve.get(code, 0)
        ds.cell(row=row, column=1, value=code).border = bdr
        ds.cell(row=row, column=2, value=cnt).border = bdr
        ds.cell(row=row, column=3, value=appr).border = bdr
        ds.cell(row=row, column=4, value=cnt - appr).border = bdr
        pc = ds.cell(row=row, column=5, value=appr / cnt if cnt else 0); pc.number_format = '0%'; pc.border = bdr
        rc = ds.cell(row=row, column=6, value=round(prod_req.get(code, 0), 2)); rc.number_format = num_fmt; rc.border = bdr
        dc = ds.cell(row=row, column=7, value=round(prod_delta.get(code, 0), 2)); dc.number_format = num_fmt; dc.border = bdr
    prod_end = row

    # Product bar chart (Approve vs Review by product)
    chart1 = BarChart()
    chart1.type = 'col'; chart1.title = 'WOAs by Product'; chart1.y_axis.title = 'Count'
    chart1.style = 10; chart1.width = 20; chart1.height = 12
    chart1.add_data(Reference(ds, min_col=3, min_row=prod_start - 1, max_row=prod_end), titles_from_data=True)
    chart1.add_data(Reference(ds, min_col=4, min_row=prod_start - 1, max_row=prod_end), titles_from_data=True)
    chart1.set_categories(Reference(ds, min_col=1, min_row=prod_start, max_row=prod_end))
    chart1.series[0].graphicalProperties.solidFill = '22C55E'
    chart1.series[1].graphicalProperties.solidFill = 'F59E0B'
    ds.add_chart(chart1, f'I{prod_start - 2}')

    # Approve/Review pie chart
    pie_row = prod_start - 2
    ds.cell(row=pie_row, column=17, value='Approve'); ds.cell(row=pie_row + 1, column=17, value=approves)
    ds.cell(row=pie_row, column=18, value='Review'); ds.cell(row=pie_row + 1, column=18, value=reviews)
    pie = PieChart(); pie.title = 'Approve vs Review'; pie.width = 12; pie.height = 12
    pie.add_data(Reference(ds, min_col=17, min_row=pie_row, max_col=18, max_row=pie_row + 1), from_rows=True, titles_from_data=True)
    ds.add_chart(pie, f'I{prod_end + 2}')

    # ── Facility Breakdown (Top 15) ──
    row = prod_end + 16
    ds.cell(row=row, column=1, value='Top 15 Facilities by Volume').font = section_font; row += 1
    for i, h in enumerate(['Facility', 'Count', 'Total Requested'], 1):
        c = ds.cell(row=row, column=i, value=h); c.font = hdr_font; c.fill = hdr_fill; c.border = bdr
    fac_start = row + 1
    for fac, cnt in fac_counts.most_common(15):
        row += 1
        ds.cell(row=row, column=1, value=fac).border = bdr
        ds.cell(row=row, column=2, value=cnt).border = bdr
        rc = ds.cell(row=row, column=3, value=round(fac_req.get(fac, 0), 2)); rc.number_format = num_fmt; rc.border = bdr
    fac_end = row

    # Facility bar chart
    chart2 = BarChart()
    chart2.type = 'bar'; chart2.title = 'Top 15 Facilities'; chart2.x_axis.title = 'Count'
    chart2.style = 10; chart2.width = 22; chart2.height = 12
    chart2.add_data(Reference(ds, min_col=2, min_row=fac_start - 1, max_row=fac_end), titles_from_data=True)
    chart2.set_categories(Reference(ds, min_col=1, min_row=fac_start, max_row=fac_end))
    chart2.series[0].graphicalProperties.solidFill = '3B82F6'
    ds.add_chart(chart2, f'E{fac_start - 1}')

    # ── Created By Breakdown ──
    row = fac_end + 16
    ds.cell(row=row, column=1, value='Submitted By').font = section_font; row += 1
    for i, h in enumerate(['Created By', 'Count', 'Total Requested'], 1):
        c = ds.cell(row=row, column=i, value=h); c.font = hdr_font; c.fill = hdr_fill; c.border = bdr
    by_counts, by_req = Counter(), defaultdict(float)
    for r in items:
        by = r.get('created_by', '') or 'Unknown'; by_counts[by] += 1; by_req[by] += r.get('requested_qty') or 0
    for name, cnt in by_counts.most_common(15):
        row += 1
        ds.cell(row=row, column=1, value=name).border = bdr
        ds.cell(row=row, column=2, value=cnt).border = bdr
        rc = ds.cell(row=row, column=3, value=round(by_req.get(name, 0), 2)); rc.number_format = num_fmt; rc.border = bdr

    tmp = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
    wb.save(tmp.name)
    tmp.close()
    return FileResponse(
        path=tmp.name,
        filename=f'WO_Adjustments_{status}.xlsx',
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Cache-Control': 'no-cache, no-store, must-revalidate'},
        background=None,  # cleanup handled below
    )
