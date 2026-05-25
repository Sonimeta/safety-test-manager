"""
server_report_generator.py

Versione del report_generator per il server (real_server.py) che usa
PIL invece di PySide6 per la gestione delle immagini (logo, firma).
Layout, stili e struttura identici al report_generator desktop.
"""

import os
import io
import logging
import html

from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, PageBreak, PageTemplate,
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, NextPageTemplate,
)
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER

from PIL import Image as PILImage, ExifTags

# ─── Costanti (identiche al desktop) ─────────────────────────────────────────
COLOR_GRID          = colors.HexColor('#e2e8f0')
COLOR_HEADER_BG     = colors.HexColor('#1e3a5f')
COLOR_HEADER_TEXT   = colors.HexColor('#ffffff')
COLOR_MAIN_BLUE     = colors.HexColor('#1e3a5f')
COLOR_ACCENT_BLUE   = colors.HexColor('#2563eb')
COLOR_MAIN_OCRA     = colors.HexColor('#d97706')
COLOR_FAIL_TEXT     = colors.HexColor('#dc2626')
COLOR_FAIL_BG       = colors.HexColor('#fee2e2')
COLOR_PASS_TEXT     = colors.HexColor('#059669')
COLOR_PASS_BG       = colors.HexColor('#d1fae5')
COLOR_ROW_EVEN      = colors.HexColor('#f8fafc')
COLOR_TEXT_PRIMARY  = colors.HexColor('#1e293b')
COLOR_TEXT_SECONDARY= colors.HexColor('#64748b')
FONT_BOLD           = 'Helvetica-Bold'
FONT_NORMAL         = 'Helvetica'
PAGE_MARGIN         = 1.5 * cm
SPACER_LARGE        = 0.3 * cm
SPACER_MEDIUM       = 0.2 * cm
SPACER_EXTRA_LARGE  = 0.8 * cm
IMAGE_DPI           = 150
LOGO_MAX_W_CM       = 18
LOGO_MAX_H_CM       = 4
SIGN_MAX_W_CM       = 5
SIGN_MAX_H_CM       = 3
LANDSCAPE_A4        = landscape(A4)


# ─── Utility immagini (PIL invece di PySide6) ─────────────────────────────────

def _cm_to_px(value_cm, dpi=IMAGE_DPI):
    return int((value_cm / 2.54) * dpi)


def _pil_compress_image(pil_img, max_w_cm, max_h_cm, prefer_jpeg=False):
    """Ridimensiona e comprime un'immagine PIL, restituisce bytes."""
    target_w = _cm_to_px(max_w_cm)
    target_h = _cm_to_px(max_h_cm)
    pil_img.thumbnail((target_w, target_h), PILImage.LANCZOS)
    buf = io.BytesIO()
    has_alpha = pil_img.mode in ('RGBA', 'LA', 'PA')
    if prefer_jpeg and not has_alpha:
        if pil_img.mode != 'RGB':
            pil_img = pil_img.convert('RGB')
        pil_img.save(buf, 'JPEG', quality=70)
    else:
        if pil_img.mode not in ('RGBA', 'RGB'):
            pil_img = pil_img.convert('RGBA')
        pil_img.save(buf, 'PNG')
    return buf.getvalue()


def _pil_load_and_fix_orientation(pil_img):
    """Applica rotazione EXIF all'immagine PIL."""
    try:
        exif = pil_img.getexif()
        if exif:
            for tag_id, tag_name in ExifTags.TAGS.items():
                if tag_name == 'Orientation':
                    orientation = exif.get(tag_id)
                    if orientation == 3:
                        pil_img = pil_img.rotate(180, expand=True)
                    elif orientation == 6:
                        pil_img = pil_img.rotate(270, expand=True)
                    elif orientation == 8:
                        pil_img = pil_img.rotate(90, expand=True)
                    break
    except Exception:
        pass
    return pil_img


# ─── Stili ───────────────────────────────────────────────────────────────────

def _create_styles():
    styles = getSampleStyleSheet()
    styles['Normal'].fontName   = FONT_NORMAL
    styles['Normal'].fontSize   = 9
    styles['Normal'].leading    = 12
    styles['Normal'].textColor  = COLOR_TEXT_PRIMARY
    styles.add(ParagraphStyle(name='Nometec',       parent=styles['Normal'], fontName=FONT_NORMAL, fontSize=11))
    styles.add(ParagraphStyle(name='NormalBold',    parent=styles['Normal'], fontName=FONT_BOLD))
    styles.add(ParagraphStyle(name='TableHeaderBold', parent=styles['Normal'], fontName=FONT_BOLD, textColor=colors.white))
    styles.add(ParagraphStyle(name='ReportTitleocra', fontName=FONT_BOLD, fontSize=16, textColor=COLOR_MAIN_OCRA, alignment=TA_CENTER, spaceAfter=2))
    styles.add(ParagraphStyle(name='ReportTitle',   fontName=FONT_BOLD, fontSize=16, textColor=COLOR_MAIN_BLUE, alignment=TA_CENTER, spaceAfter=2))
    styles.add(ParagraphStyle(name='ReportSubTitle',fontName=FONT_NORMAL, fontSize=9, textColor=COLOR_TEXT_SECONDARY, alignment=TA_CENTER, spaceAfter=8))
    styles.add(ParagraphStyle(name='SectionHeader', fontName=FONT_BOLD, fontSize=10, textColor=COLOR_MAIN_BLUE, spaceAfter=4, spaceBefore=6))
    styles.add(ParagraphStyle(name='Conforme',      fontName=FONT_BOLD, textColor=COLOR_PASS_TEXT, fontSize=10))
    styles.add(ParagraphStyle(name='NonConforme',   fontName=FONT_BOLD, textColor=COLOR_FAIL_TEXT, fontSize=10))
    styles.add(ParagraphStyle(name='FinaleBase',    fontName=FONT_BOLD, fontSize=12, alignment=TA_CENTER, borderPadding=8, borderWidth=2))
    return styles


def _p(text, style):
    text_str = str(text) if text is not None else ''
    return Paragraph(text_str.replace('\n', '<br/>'), style)


def _get_modern_table_style(has_header=True, zebra_stripe=True):
    cmds = [
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW',     (0, -1), (-1, -1), 1, COLOR_GRID),
        ('LINEABOVE',     (0,  0), (-1,  0), 1, COLOR_GRID),
        ('LINEBEFORE',    (0,  0), ( 0, -1), 1, COLOR_GRID),
        ('LINEAFTER',    (-1,  0), (-1, -1), 1, COLOR_GRID),
    ]
    if has_header:
        cmds.extend([
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
            ('TEXTCOLOR',  (0, 0), (-1, 0), COLOR_HEADER_TEXT),
            ('FONTNAME',   (0, 0), (-1, 0), FONT_BOLD),
            ('LINEBELOW',  (0, 0), (-1, 0), 2, COLOR_ACCENT_BLUE),
        ])
    return cmds


# ─── Sezioni del report (identiche al desktop) ───────────────────────────────

def _add_logo(story, report_settings):
    logo_path = report_settings.get('logo_path')
    if logo_path and os.path.exists(logo_path):
        try:
            pil_img = PILImage.open(logo_path)
            pil_img = _pil_load_and_fix_orientation(pil_img)
            logo_bytes = _pil_compress_image(pil_img, LOGO_MAX_W_CM, LOGO_MAX_H_CM, prefer_jpeg=True)
            img = Image(io.BytesIO(logo_bytes), width=LOGO_MAX_W_CM*cm, height=LOGO_MAX_H_CM*cm, kind='proportional')
            img.hAlign = 'CENTER'
            story.append(img)
            story.append(Spacer(1, 0.8*cm))
        except Exception as e:
            logging.error(f"Impossibile caricare il logo: {e}")


def _add_header(story, styles, verification_data):
    is_functional = bool(verification_data.get('functional_results'))
    if is_functional:
        story.append(_p("Report di Verifica Funzionale", styles['ReportTitle']))
    else:
        story.append(_p("Report di Verifica di Sicurezza Elettrica", styles['ReportTitle']))
        story.append(_p("(Conforme a CEI EN 62353)", styles['ReportSubTitle']))

    right_style = ParagraphStyle(name='NormalRight', parent=styles['Normal'], alignment=2)
    header_data = [[
        _p(f"<b>Data Verifica:</b> {verification_data.get('date', 'N/A')}", styles['Normal']),
        _p(f"<b>Codice Verifica:</b> {verification_data.get('verification_code', 'N/A')}", right_style),
    ]]
    ht = Table(header_data, colWidths=[9*cm, 9*cm])
    ht.setStyle(TableStyle([
        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',  (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(ht)
    story.append(Spacer(1, SPACER_MEDIUM))


def _add_customer_info(story, styles, customer_info, destination_info):
    story.append(_p("Dati Cliente e Destinazione", styles['SectionHeader']))
    data = [[
        _p("Cliente",      styles['NormalBold']), _p(customer_info.get('name', 'N/D'),    styles['Normal']),
        _p("Destinazione", styles['NormalBold']), _p(destination_info.get('name', 'N/D'), styles['Normal']),
    ]]
    t = Table(data, colWidths=[3.5*cm, 5.5*cm, 3.5*cm, 5.5*cm])
    t.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND',    (0, 0), (0, -1),  COLOR_ROW_EVEN),
        ('BACKGROUND',    (2, 0), (2, -1),  COLOR_ROW_EVEN),
    ]))
    story.append(t)
    story.append(Spacer(1, SPACER_LARGE))


def _add_device_info(story, styles, device_info, verification_data):
    story.append(_p("Dati Apparecchio", styles['SectionHeader']))
    is_functional  = bool(verification_data.get('functional_results'))
    profile_key    = verification_data.get('profile_name', '')
    profile_display_name = profile_key  # server doesn't have config.PROFILES lookup

    data = [
        [_p("Tipo Apparecchio", styles['NormalBold']), _p(device_info.get('description', 'N/D'), styles['Normal']),
         _p("Marca",            styles['NormalBold']), _p(device_info.get('manufacturer', 'N/D'), styles['Normal'])],

        [_p("Modello", styles['NormalBold']), _p(device_info.get('model', 'N/D'), styles['Normal']),
         _p("Profilo di Verifica" if is_functional else "Classe Isolamento", styles['NormalBold']),
         _p(profile_display_name, styles['Normal'])],

        [_p("Numero di Serie",   styles['NormalBold']), _p(device_info.get('serial_number', ''),   styles['Normal']),
         _p("Reparto",           styles['NormalBold']), _p(device_info.get('department', 'N/D'),    styles['Normal'])],

        [_p("Inventario Cliente",styles['NormalBold']), _p(device_info.get('customer_inventory', '') or '', styles['Normal']),
         _p("Inventario AMS",    styles['NormalBold']), _p(device_info.get('ams_inventory', '') or '',      styles['Normal'])],
    ]
    t = Table(data, colWidths=[3.5*cm, 5.5*cm, 3.5*cm, 5.5*cm])
    t.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND',    (0, 0), (0, -1), COLOR_ROW_EVEN),
        ('BACKGROUND',    (2, 0), (2, -1), COLOR_ROW_EVEN),
    ]))
    story.append(t)
    story.append(Spacer(1, SPACER_LARGE))


def _add_instrument_info(story, styles, mti_info, verification_data=None):
    used_instruments = verification_data.get('used_instruments') if verification_data else None

    if used_instruments and len(used_instruments) > 1:
        story.append(_p("Strumenti Utilizzati", styles['SectionHeader']))
        rows = [[
            _p("Strumento",  styles['TableHeaderBold']),
            _p("Matricola",  styles['TableHeaderBold']),
            _p("Versione",   styles['TableHeaderBold']),
            _p("Data Cal.",  styles['TableHeaderBold']),
        ]]
        for inst in used_instruments:
            rows.append([
                _p(inst.get('instrument', 'N/A'), styles['Normal']),
                _p(inst.get('serial',     'N/A'), styles['Normal']),
                _p(inst.get('version',    'N/A'), styles['Normal']),
                _p(inst.get('cal_date',   'N/A'), styles['Normal']),
            ])
        t = Table(rows, colWidths=[5*cm, 4.5*cm, 4.5*cm, 4*cm])
        cmds = _get_modern_table_style(has_header=True)
        for i in range(2, len(rows), 2):
            cmds.append(('BACKGROUND', (0, i), (-1, i), COLOR_ROW_EVEN))
        t.setStyle(TableStyle(cmds))
    else:
        story.append(_p("Dati Strumento", styles['SectionHeader']))
        rows = [
            [_p("<b>Strumento:</b>", styles['NormalBold']), _p(mti_info.get('instrument', 'N/A'), styles['Normal'])],
            [_p("<b>Matricola:</b>", styles['NormalBold']), _p(mti_info.get('serial',     'N/A'), styles['Normal'])],
            [_p("<b>Data Cal.:</b>", styles['NormalBold']), _p(mti_info.get('cal_date',   'N/A'), styles['Normal'])],
        ]
        t = Table(rows, colWidths=[9*cm, 9*cm])
        t.setStyle(TableStyle([
            ('GRID',          (0, 0), (-1, -1), 0.5, COLOR_GRID),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('TOPPADDING',    (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('BACKGROUND',    (0, 0), (0, -1),  COLOR_ROW_EVEN),
        ]))
    story.append(t)
    story.append(Spacer(1, SPACER_LARGE))


def _add_summary_sections(story, styles, verification_data):
    results = verification_data.get('functional_results', {})
    if not results:
        return

    summary_sections = sorted(
        [(sk, sd) for sk, sd in results.items() if sd.get('show_in_summary', False)],
        key=lambda x: x[1].get('order', 999),
    )
    if not summary_sections:
        return

    story.append(_p("Riepilogo Verifiche", styles['SectionHeader']))
    story.append(Spacer(1, 0.2*cm))

    for section_key, section_data in summary_sections:
        story.append(_p(section_data.get('title', section_key), styles['NormalBold']))
        story.append(Spacer(1, 0.1*cm))

        for field in (section_data.get('fields') or []):
            label = field.get('label') or field.get('key', '').replace('_', ' ').title()
            value = field.get('value', '')
            t = Table([[_p(label, styles['Normal']), _p(str(value), styles['Normal'])]],
                      colWidths=[6.5*cm, 11.5*cm])
            t.setStyle(TableStyle([
                ('GRID',       (0, 0), (-1, -1), 0.5, COLOR_GRID),
                ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
                ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(t)
        if section_data.get('fields'):
            story.append(Spacer(1, 0.2*cm))

        rows = section_data.get('rows') or []
        if rows:
            is_checklist = section_data.get('section_type') == 'checklist'
            header_cells = []
            header_keys  = []
            if is_checklist:
                header_cells.append(_p("Verifica", styles['TableHeaderBold']))
            for ve in rows[0].get('values', []):
                header_cells.append(_p(ve.get('label') or ve.get('key', ''), styles['TableHeaderBold']))
                header_keys.append(ve.get('key'))

            tdata = [header_cells]
            for row in rows:
                rcells = []
                if is_checklist:
                    rcells.append(_p(row.get('label') or row.get('key', ''), styles['Normal']))
                vmap = {ve.get('key'): ve.get('value') for ve in row.get('values', [])}
                for k in header_keys:
                    rcells.append(_p(str(vmap.get(k, '') or ''), styles['Normal']))
                tdata.append(rcells)

            t = Table(tdata, repeatRows=1)
            t.setStyle(TableStyle([
                ('GRID',       (0, 0), (-1, -1), 0.5, COLOR_GRID),
                ('BACKGROUND', (0, 0), (-1,  0), COLOR_HEADER_BG),
                ('TEXTCOLOR',  (0, 0), (-1,  0), COLOR_HEADER_TEXT),
                ('FONTNAME',   (0, 0), (-1,  0), FONT_BOLD),
                ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(t)
            story.append(Spacer(1, 0.2*cm))

    story.append(Spacer(1, 0.3*cm))


def _add_final_evaluation(story, styles, verification_data):
    is_functional = bool(verification_data.get('functional_results'))
    if is_functional:
        story.append(_p("Esito Verifica Funzionale", styles['SectionHeader']))
    else:
        story.append(_p("Esito Verifica Sicurezza Elettrica", styles['SectionHeader']))
    story.append(Spacer(1, SPACER_MEDIUM))

    overall_status = verification_data.get('overall_status', '')
    is_pass        = overall_status in ('PASSATO', 'CONFORME')
    is_annotazione = overall_status == 'CONFORME CON ANNOTAZIONE'

    if is_annotazione:
        text = "APPARECCHIO CONFORME CON ANNOTAZIONE"
        col  = colors.orange
    elif is_pass:
        text = "APPARECCHIO CONFORME"
        col  = colors.darkgreen
    else:
        text = "APPARECCHIO NON CONFORME"
        col  = colors.red

    fs = ParagraphStyle(name='FinaleDynamic', parent=styles['FinaleBase'])
    fs.borderColor = col
    fs.textColor   = col
    story.append(_p(text, fs))
    story.append(Spacer(1, SPACER_LARGE))

    notes = (verification_data.get('visual_inspection_data', {}).get('notes') or '').strip()
    if notes:
        story.append(Spacer(1, 0.2*cm))
        story.append(_p(f"<b>Note:</b> {html.escape(notes)}", styles['Normal']))

    story.append(Spacer(1, SPACER_EXTRA_LARGE))


def _add_signature(story, styles, technician_name, signature_data):
    technician_p = _p(f"<b>Tecnico Verificatore:</b> {technician_name or 'N/D'}", styles['Nometec'])
    sig_content  = _p("<b>Firma:</b>________________________", styles['Normal'])

    if signature_data:
        try:
            pil_img = PILImage.open(io.BytesIO(signature_data))
            pil_img = _pil_load_and_fix_orientation(pil_img)
            sig_bytes = _pil_compress_image(pil_img, SIGN_MAX_W_CM, SIGN_MAX_H_CM, prefer_jpeg=False)
            img = Image(io.BytesIO(sig_bytes), width=SIGN_MAX_W_CM*cm, height=SIGN_MAX_H_CM*cm, kind='proportional')
            img.hAlign = 'CENTER'
            sig_content = img
        except Exception as e:
            logging.warning(f"Impossibile caricare firma: {e}")

    t = Table([[technician_p, sig_content]], colWidths=[9*cm, 9*cm])
    t.setStyle(TableStyle([
        ('VALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(t)


def _add_visual_inspection(story, styles, verification_data):
    visual_data = verification_data.get('visual_inspection_data', {})
    if not visual_data or not visual_data.get('checklist'):
        return

    story.append(_p("Ispezione Visiva", styles['SectionHeader']))
    header = [
        _p("Controllo", styles['TableHeaderBold']),
        _p("Esito",     styles['TableHeaderBold']),
    ]
    tdata = [header]
    for item in visual_data.get('checklist', []):
        esito_text = item.get('result', 'N/D')
        if esito_text == 'KO':
            esito_p = _p("NON CONFORME", styles['NonConforme'])
        elif esito_text == 'OK':
            esito_p = _p("CONFORME",     styles['Conforme'])
        else:
            esito_p = _p("NON APPLICABILE", styles['Normal'])
        tdata.append([_p(item.get('item', ''), styles['Normal']), esito_p])

    t = Table(tdata, colWidths=[14.5*cm, 3.5*cm], repeatRows=1)
    cmds = _get_modern_table_style(has_header=True)
    for i in range(2, len(tdata), 2):
        cmds.append(('BACKGROUND', (0, i), (-1, i), COLOR_ROW_EVEN))
    t.setStyle(TableStyle(cmds))
    story.append(t)
    story.append(Spacer(1, SPACER_LARGE))


def _add_electrical_measurements(story, styles, verification_data):
    measurements = verification_data.get('results') or []
    if not measurements:
        return

    story.append(_p("Misure Elettriche", styles['SectionHeader']))
    header = [_p(h, styles['TableHeaderBold']) for h in ["Misura", "Valore Misurato", "Limite Norma", "Esito"]]
    tdata  = [header]

    for res in measurements:
        esito_style = styles['Conforme'] if res.get('passed') else styles['NonConforme']
        esito_text  = "CONFORME" if res.get('passed') else "NON CONFORME"
        valore   = res.get('value', 'N/A')
        limite   = res.get('limit_value')
        unita    = res.get('unit', '')
        nome     = res.get('name', '')
        polarity = res.get('polarity', '')
        if polarity:
            nome = f"{nome} ({polarity})"
        valore_str = f"{valore} {unita}".strip() if valore not in (None, 'N/A', '') else 'N/A'
        limite_str = f"≤ {limite} {unita}".strip() if limite is not None else 'N/A'
        tdata.append([
            _p(nome,        styles['Normal']),
            _p(valore_str,  styles['Normal']),
            _p(limite_str,  styles['Normal']),
            _p(esito_text,  esito_style),
        ])

    t = Table(tdata, colWidths=[7*cm, 3.5*cm, 4.5*cm, 3*cm], repeatRows=1)
    cmds = _get_modern_table_style(has_header=True)
    for i in range(1, len(tdata)):
        if i % 2 == 0:
            cmds.append(('BACKGROUND', (0, i), (2, i), COLOR_ROW_EVEN))
    t.setStyle(TableStyle(cmds))
    story.append(t)
    story.append(Spacer(1, SPACER_LARGE))


def _add_functional_sections(story, styles, verification_data):
    results = verification_data.get('functional_results', {})
    if not results:
        return

    detail_sections = sorted(
        [(sk, sd) for sk, sd in results.items() if not sd.get('show_in_summary', False)],
        key=lambda x: x[1].get('order', 999),
    )
    if not detail_sections:
        return

    story.append(_p("Verifica Funzionale", styles['SectionHeader']))

    for section_key, section_data in detail_sections:
        story.append(_p(section_data.get('title', section_key).upper(), styles['NormalBold']))
        story.append(Spacer(1, 0.2*cm))

        fields = section_data.get('fields') or []
        if fields:
            rows_data = []
            for field in fields:
                label = field.get('label') or field.get('key', '').replace('_', ' ').title()
                value = field.get('value') or ''
                rows_data.append([_p(label, styles['NormalBold']), _p(str(value), styles['Normal'])])
            t = Table(rows_data, colWidths=[6.5*cm, 11.5*cm])
            t.setStyle(TableStyle([
                ('GRID',       (0, 0), (-1, -1), 0.5, COLOR_GRID),
                ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
                ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(t)
            story.append(Spacer(1, 0.2*cm))

        rows = section_data.get('rows') or []
        if rows:
            is_checklist = section_data.get('section_type') == 'checklist'
            header_cells = []
            header_keys  = []
            if is_checklist:
                header_cells.append(_p("Verifica", styles['TableHeaderBold']))
            for ve in (rows[0].get('values', []) if rows else []):
                header_cells.append(_p(ve.get('label') or ve.get('key', ''), styles['TableHeaderBold']))
                header_keys.append(ve.get('key'))

            tdata = [header_cells]
            for row in rows:
                rcells = []
                if is_checklist:
                    rcells.append(_p(row.get('label') or row.get('key', ''), styles['Normal']))
                vmap = {ve.get('key'): ve.get('value') for ve in row.get('values', [])}
                for k in header_keys:
                    rcells.append(_p(str(vmap.get(k, '') or ''), styles['Normal']))
                tdata.append(rcells)

            t = Table(tdata, repeatRows=1)
            t.setStyle(TableStyle([
                ('GRID',       (0, 0), (-1, -1), 0.5, COLOR_GRID),
                ('BACKGROUND', (0, 0), (-1,  0), COLOR_HEADER_BG),
                ('TEXTCOLOR',  (0, 0), (-1,  0), COLOR_HEADER_TEXT),
                ('FONTNAME',   (0, 0), (-1,  0), FONT_BOLD),
                ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(t)
            story.append(Spacer(1, 0.3*cm))

        story.append(Spacer(1, 0.3*cm))


def _add_footer(canvas, doc, device_info, verification_data):
    canvas.saveState()
    canvas.setFont(FONT_NORMAL, 9)
    canvas.setStrokeColor(COLOR_GRID)
    page_width = canvas._pagesize[0]
    canvas.line(doc.leftMargin, 1.4*cm, page_width - doc.rightMargin, 1.4*cm)
    footer_text = (
        f"Dispositivo S/N: {device_info.get('serial_number', 'N/A')}   |   "
        f"Verifica del: {verification_data.get('date', 'N/A')}   |   "
        f"Email: assistenza@amstrento.it"
    )
    canvas.drawString(doc.leftMargin, 1*cm, footer_text)
    canvas.drawRightString(page_width - doc.rightMargin, 1*cm, f"Pagina {doc.page}")
    canvas.restoreState()


def _build_report_doc(filename, footer_callback):
    doc = BaseDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=PAGE_MARGIN, leftMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,   bottomMargin=PAGE_MARGIN,
        title="Rapporto di Verifica",
        pageCompression=1,
    )
    portrait_frame  = Frame(PAGE_MARGIN, PAGE_MARGIN,
                            A4[0] - 2*PAGE_MARGIN, A4[1] - 2*PAGE_MARGIN,
                            id="portrait_frame")
    landscape_frame = Frame(PAGE_MARGIN, PAGE_MARGIN,
                            LANDSCAPE_A4[0] - 2*PAGE_MARGIN, LANDSCAPE_A4[1] - 2*PAGE_MARGIN,
                            id="landscape_frame")
    doc.addPageTemplates([
        PageTemplate(id="Portrait",  frames=[portrait_frame],  onPage=footer_callback, pagesize=A4),
        PageTemplate(id="Landscape", frames=[landscape_frame], onPage=footer_callback, pagesize=LANDSCAPE_A4),
    ])
    return doc


# ─── Funzione principale ─────────────────────────────────────────────────────

def create_report(filename, device_info, customer_info, destination_info,
                  mti_info, report_settings, verification_data,
                  technician_name, signature_data):
    """
    Genera il report PDF con lo stesso layout del desktop.
    Usa PIL invece di PySide6 per la gestione di logo e firma.
    """
    styles   = _create_styles()
    story    = []
    footer_cb = lambda canvas, doc: _add_footer(canvas, doc, device_info, verification_data)
    doc = _build_report_doc(filename, footer_cb)

    # Pagina 1: dati, esito, firma
    _add_logo(story, report_settings)
    _add_header(story, styles, verification_data)
    _add_customer_info(story, styles, customer_info, destination_info)
    _add_device_info(story, styles, device_info, verification_data)
    _add_instrument_info(story, styles, mti_info, verification_data)
    _add_summary_sections(story, styles, verification_data)
    _add_final_evaluation(story, styles, verification_data)
    _add_signature(story, styles, technician_name, signature_data)

    # Pagina 2: dettagli tecnici
    story.append(PageBreak())
    _add_visual_inspection(story, styles, verification_data)
    _add_electrical_measurements(story, styles, verification_data)
    _add_functional_sections(story, styles, verification_data)

    doc.build(story)
    logging.info(f"[server_report_generator] PDF generato: {filename}")
