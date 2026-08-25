import os
import logging
import html
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfgen import canvas
from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice, QSize
from PySide6.QtGui import QImage
from app import config
import io
from PIL import Image as PILImage, ExifTags

# --- Costanti di Stile e Layout ---
COLOR_GRID = colors.HexColor('#475569')          # Bordi griglia scuri ben visibili in stampa
COLOR_HEADER_BG = colors.HexColor('#1e3a5f')     # Header blu scuro professionale
COLOR_HEADER_TEXT = colors.HexColor('#ffffff')   # Testo header bianco
COLOR_MAIN_BLUE = colors.HexColor('#1e3a5f')     # Blu principale
COLOR_ACCENT_BLUE = colors.HexColor('#2563eb')   # Blu accent
COLOR_MAIN_OCRA = colors.HexColor('#d97706')     # Arancione moderno
COLOR_FAIL_TEXT = colors.HexColor('#dc2626')     # Rosso per errori
COLOR_FAIL_BG = colors.HexColor('#fee2e2')       # Sfondo rosso chiaro
COLOR_PASS_TEXT = colors.HexColor('#059669')     # Verde per successi
COLOR_PASS_BG = colors.HexColor('#d1fae5')       # Sfondo verde chiaro
COLOR_ROW_EVEN = colors.HexColor('#f8fafc')      # Righe pari
COLOR_TEXT_PRIMARY = colors.HexColor('#1e293b')  # Testo principale
COLOR_TEXT_SECONDARY = colors.HexColor('#64748b') # Testo secondario
FONT_BOLD = 'Helvetica-Bold'
FONT_NORMAL = 'Helvetica'
PAGE_MARGIN = 1.5*cm
SPACER_LARGE = 0.3*cm
SPACER_MEDIUM = 0.2*cm
SPACER_EXTRA_LARGE = 0.8*cm
IMAGE_DPI = 350
LOGO_MAX_W_CM = 18
LOGO_MAX_H_CM = 4
SIGN_MAX_W_CM = 5
SIGN_MAX_H_CM = 3
LANDSCAPE_A4 = landscape(A4)

def _cm_to_px(value_cm, dpi=IMAGE_DPI):
    return int((value_cm / 2.54) * dpi)

def _compress_qimage_to_bytes(image, max_w_cm, max_h_cm, prefer_jpeg=False):
    if image.isNull():
        return None
    target_w = _cm_to_px(max_w_cm)
    target_h = _cm_to_px(max_h_cm)
    scaled = image.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    use_jpeg = prefer_jpeg and not scaled.hasAlphaChannel()
    fmt = "JPG" if use_jpeg else "PNG"
    quality = 100 if use_jpeg else -1
    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QIODevice.WriteOnly)
    if use_jpeg:
        scaled.save(buffer, fmt, quality)
    else:
        scaled.save(buffer, fmt)
    buffer.close()
    return bytes(byte_array)


def _get_attachment_page_metrics(use_landscape=False):
    """Restituisce area utile per una pagina allegati portrait/landscape."""
    page_size = LANDSCAPE_A4 if use_landscape else A4
    max_width = page_size[0] - 2 * PAGE_MARGIN
    max_height = page_size[1] - (2 * PAGE_MARGIN) - (2.5 * cm)
    return {
        "page_size": page_size,
        "max_width": max_width,
        "max_height": max_height,
        "max_width_cm": max_width / cm,
        "max_height_cm": max_height / cm,
    }

def _create_styles():
    """Crea e restituisce un dizionario di stili di paragrafo personalizzati - Design moderno."""
    styles = getSampleStyleSheet()
    styles['Normal'].fontName = FONT_NORMAL
    styles['Normal'].fontSize = 9
    styles['Normal'].leading = 13
    styles['Normal'].textColor = COLOR_TEXT_PRIMARY
    styles.add(ParagraphStyle(name='Nometec', parent=styles['Normal'], fontName=FONT_NORMAL, fontSize=11, leading=15))
    styles.add(ParagraphStyle(name='NormalBold', parent=styles['Normal'], fontName=FONT_BOLD, fontSize=9, leading=13))
    styles.add(ParagraphStyle(name='TableHeaderBold', parent=styles['Normal'], fontName=FONT_BOLD, fontSize=9, leading=13, textColor=colors.white, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='TableHeader', parent=styles['Normal'], fontName=FONT_BOLD, fontSize=9, leading=13, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='ReportTitleocra', fontName=FONT_BOLD, fontSize=16, leading=20, textColor=COLOR_MAIN_OCRA, alignment=TA_CENTER, spaceAfter=2))
    styles.add(ParagraphStyle(name='ReportTitle', fontName=FONT_BOLD, fontSize=16, leading=20, textColor=COLOR_MAIN_BLUE, alignment=TA_CENTER, spaceAfter=2))
    styles.add(ParagraphStyle(name='ReportSubTitle', fontName=FONT_NORMAL, fontSize=9, leading=13, textColor=COLOR_TEXT_SECONDARY, alignment=TA_CENTER, spaceAfter=8))
    styles.add(ParagraphStyle(name='SectionHeader', fontName=FONT_BOLD, fontSize=11, leading=15, textColor=COLOR_MAIN_BLUE, spaceAfter=6, spaceBefore=8))
    styles.add(ParagraphStyle(name='Conforme', fontName=FONT_BOLD, textColor=COLOR_PASS_TEXT, fontSize=10, leading=14))
    styles.add(ParagraphStyle(name='NonConforme', fontName=FONT_BOLD, textColor=COLOR_FAIL_TEXT, fontSize=10, leading=14))
    styles.add(ParagraphStyle(name='FinaleBase', fontName=FONT_BOLD, fontSize=12, leading=16, alignment=TA_CENTER, borderPadding=8, borderWidth=2))
    return styles

def _create_styled_paragraph(text, style):
    """Crea un paragrafo con uno stile specifico, gestendo i 'None' e i ritorni a capo."""
    text_str = str(text) if text is not None else ''
    return Paragraph(text_str.replace('\n', '<br/>'), style)

def _get_modern_table_style(has_header=True, zebra_stripe=True):
    """Restituisce uno stile moderno per le tabelle con padding e griglia ben definiti."""
    style_commands = [
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
    ]
    
    if has_header:
        style_commands.extend([
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_HEADER_TEXT),
            ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, COLOR_MAIN_BLUE),
        ])
    
    return style_commands

# --- Funzioni per la Creazione delle Sezioni del Report ---

def _add_logo(story, report_settings):
    """Aggiunge il logo aziendale al report (scelto dall'utente in 'Imposta Logo Azienda')."""
    logo_path = None
    if isinstance(report_settings, dict):
        logo_path = report_settings.get('logo_path')

    if not logo_path or not os.path.exists(logo_path):
        try:
            from PySide6.QtCore import QSettings
            settings = QSettings("ELSON META", "SafetyTester")
            saved_logo = settings.value("logo_path", "")
            if saved_logo and os.path.exists(str(saved_logo)):
                logo_path = str(saved_logo)
            else:
                settings_alt = QSettings("ELSON META", "Safety Test Manager")
                saved_logo_alt = settings_alt.value("logo_path", "")
                if saved_logo_alt and os.path.exists(str(saved_logo_alt)):
                    logo_path = str(saved_logo_alt)
        except Exception as e:
            logging.debug(f"Impossibile accedere a QSettings per il logo aziendale: {e}")

    if logo_path and os.path.exists(logo_path):
        try:
            logo_image = QImage(logo_path)
            logo_bytes = _compress_qimage_to_bytes(
                logo_image,
                LOGO_MAX_W_CM,
                LOGO_MAX_H_CM,
                prefer_jpeg=True,
            )
            if logo_bytes:
                img = Image(io.BytesIO(logo_bytes), width=LOGO_MAX_W_CM*cm, height=LOGO_MAX_H_CM*cm, kind='proportional')
            else:
                img = Image(logo_path, width=LOGO_MAX_W_CM*cm, height=LOGO_MAX_H_CM*cm, kind='proportional')
            img.hAlign = 'CENTER'
            story.append(img)
            story.append(Spacer(1, 0.8*cm))
        except Exception as e:
            logging.error(f"Impossibile caricare il file del logo aziendale: {e}")

def _add_header(story, styles, verification_data):
    """Aggiunge l'intestazione del report."""
    is_ecografo = bool(verification_data.get('is_ecografo_quality'))
    is_functional = bool(verification_data.get('functional_results'))

    if is_ecografo:
        story.append(_create_styled_paragraph("Report di Controllo Qualità Sonde Ecografo", styles['ReportTitle']))
        story.append(Spacer(1, 0.8*cm))
    elif is_functional:
        story.append(_create_styled_paragraph("Report di Verifica Funzionale", styles['ReportTitle']))
        story.append(Spacer(1, 0.8*cm))
    else:
        story.append(_create_styled_paragraph("Report di Verifica di Sicurezza Elettrica", styles['ReportTitle']))
        # Recupera la norma dal profilo associato alla verifica
        profile_key = verification_data.get('profile_name', '')
        norma_text = ''
        if profile_key:
            profile_obj = config.PROFILES.get(profile_key)
            if profile_obj and getattr(profile_obj, 'norma', ''):
                norma_text = profile_obj.norma
        if norma_text:
            story.append(_create_styled_paragraph(f"(Conforme a {norma_text})", styles['ReportSubTitle']))
        else:
            story.append(_create_styled_paragraph("(Conforme a CEI EN 62353)", styles['ReportSubTitle']))

    # --- INIZIO MODIFICA ---
    # Crea uno stile di paragrafo con allineamento a destra
    right_aligned_style = ParagraphStyle(name='NormalRight', parent=styles['Normal'], alignment=2) # 2 = TA_RIGHT

    date_text = f"<b>Data Verifica:</b> {verification_data.get('date', 'N/A')}"
    code_text = f"<b>Codice Verifica:</b> {verification_data.get('verification_code', 'N/A')}"

    # Usa una tabella per allineare i due elementi sulla stessa riga
    header_data = [
        [
            _create_styled_paragraph(date_text, styles['Normal']),
            _create_styled_paragraph(code_text, right_aligned_style)
        ]
    ]

    # La tabella ha due colonne di larghezza uguale
    header_table = Table(header_data, colWidths=[9*cm, 9*cm])
    # Applica uno stile per rimuovere eventuali bordi o padding
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))

    story.append(header_table)
    # --- FINE MODIFICA ---
    
    story.append(Spacer(1, SPACER_MEDIUM))

def _add_customer_info(story, styles, customer_info, destination_info):
    """Aggiunge la tabella con le informazioni sul cliente e sulla destinazione."""
    story.append(_create_styled_paragraph("Dati Cliente e Destinazione", styles['SectionHeader']))

    cliente = customer_info.get('name', 'N/D')
    destinazione = destination_info.get('name', 'N/D')

    customer_data = [
        [_create_styled_paragraph("Cliente", styles['NormalBold']), _create_styled_paragraph(cliente, styles['Normal']),
         _create_styled_paragraph("Destinazione", styles['NormalBold']), _create_styled_paragraph(destinazione, styles['Normal'])],
    ]

    table = Table(customer_data, colWidths=[3.5*cm, 5.5*cm, 3.5*cm, 5.5*cm])
    table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, COLOR_GRID),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND', (0,0), (0,-1), COLOR_ROW_EVEN),
        ('BACKGROUND', (2,0), (2,-1), COLOR_ROW_EVEN),
    ]))
    story.append(table)
    story.append(Spacer(1, SPACER_LARGE))

def _add_device_info(story, styles, device_info, verification_data):
    """Aggiunge la tabella con le informazioni sul dispositivo."""
    story.append(_create_styled_paragraph("Dati Apparecchio", styles['SectionHeader']))

    descrizione = device_info.get('description', 'N/D')
    reparto = device_info.get('department', 'N/D') 
    inventario_ams = device_info.get('ams_inventory', 'N/D') 
    marca = device_info.get('manufacturer', 'N/D')
    modello = device_info.get('model', 'N/D')
    inventario_cliente = device_info.get('customer_inventory', 'N/D')
    
    # Distingue tra profilo elettrico e funzionale
    is_functional = bool(verification_data.get('functional_results'))
    profile_key = verification_data.get('profile_name', '')
    if is_functional:
        # Per verifiche funzionali, il profile_name è già il nome del profilo (non la chiave)
        profile_display_name = profile_key if profile_key else 'N/D'
    else:
        # Per verifiche elettriche, cerca il profilo in config.PROFILES
        profile = config.PROFILES.get(profile_key)
        profile_display_name = profile.name if profile else profile_key

    device_data = [
        
        [_create_styled_paragraph("Tipo Apparecchio", styles['NormalBold']), _create_styled_paragraph(descrizione, styles['Normal']),
         _create_styled_paragraph("Marca", styles['NormalBold']), _create_styled_paragraph(marca, styles['Normal'])],

        [_create_styled_paragraph("Modello", styles['NormalBold']), _create_styled_paragraph(modello, styles['Normal']),
         _create_styled_paragraph("Profilo di Verifica" if verification_data.get('functional_results') else "Classe Isolamento", styles['NormalBold']), _create_styled_paragraph(profile_display_name, styles['Normal'])],

        [_create_styled_paragraph("Numero di Serie", styles['NormalBold']), _create_styled_paragraph(device_info.get('serial_number', ''), styles['Normal']),
         _create_styled_paragraph("Reparto", styles['NormalBold']), _create_styled_paragraph(reparto, styles['Normal'])],

        [_create_styled_paragraph("Inventario Cliente", styles['NormalBold']), _create_styled_paragraph(inventario_cliente, styles['Normal']),
         _create_styled_paragraph("Inventario AMS", styles['NormalBold']), _create_styled_paragraph(inventario_ams, styles['Normal'])],
    ]
    table = Table(device_data, colWidths=[3.5*cm, 5.5*cm, 3.5*cm, 5.5*cm])
    table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, COLOR_GRID),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND', (0,0), (0,-1), COLOR_ROW_EVEN),
        ('BACKGROUND', (2,0), (2,-1), COLOR_ROW_EVEN),
    ]))
    story.append(table)
    story.append(Spacer(1, SPACER_LARGE))

def _add_instrument_info(story, styles, mti_info, verification_data=None):
    """Aggiunge la tabella con le informazioni sullo strumento di misura."""
    # Se ci sono più strumenti usati nella verifica funzionale, mostra tutti
    used_instruments = verification_data.get('used_instruments') if verification_data else None

    # Nessun strumento selezionato: non mostrare la sezione
    _mti_valid = mti_info and any(mti_info.get(k) for k in ('instrument', 'serial', 'cal_date'))
    _used_valid = used_instruments and len(used_instruments) > 0
    if not _mti_valid and not _used_valid:
        return

    if used_instruments and len(used_instruments) > 1:
        # Mostra tutti gli strumenti usati
        story.append(_create_styled_paragraph("Strumenti Utilizzati", styles['SectionHeader']))
        mti_data = [
            [_create_styled_paragraph("Strumento", styles['TableHeaderBold']),
             _create_styled_paragraph("Matricola", styles['TableHeaderBold']),
             _create_styled_paragraph("Versione", styles['TableHeaderBold']),
             _create_styled_paragraph("Data Cal.", styles['TableHeaderBold'])]
        ]
        
        for inst in used_instruments:
            mti_data.append([
                _create_styled_paragraph(inst.get('instrument', 'N/A'), styles['Normal']),
                _create_styled_paragraph(inst.get('serial', 'N/A'), styles['Normal']),
                _create_styled_paragraph(inst.get('version', 'N/A'), styles['Normal']),
                _create_styled_paragraph(inst.get('cal_date', 'N/A'), styles['Normal']),
            ])
        
        table = Table(mti_data, colWidths=[5*cm, 4.5*cm, 4.5*cm, 4*cm])
        style_cmds = _get_modern_table_style(has_header=True)
        # Aggiungi zebra striping
        for i in range(2, len(mti_data), 2):
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), COLOR_ROW_EVEN))
        table.setStyle(TableStyle(style_cmds))
    else:
        # Mostra un singolo strumento (comportamento originale o se c'è solo uno strumento)
        story.append(_create_styled_paragraph("Dati Strumento", styles['SectionHeader']))
        nome_strumento = mti_info.get('instrument', 'N/A')
        mti_data = [
            [_create_styled_paragraph("<b>Strumento:</b>", styles['NormalBold']), _create_styled_paragraph(nome_strumento, styles['Normal'])],
            [_create_styled_paragraph("<b>Matricola:</b>", styles['NormalBold']), _create_styled_paragraph(mti_info.get('serial', 'N/A'), styles['Normal'])],
            [_create_styled_paragraph("<b>Data Cal.:</b>", styles['NormalBold']), _create_styled_paragraph(mti_info.get('cal_date', 'N/A'), styles['Normal'])],
        ]
        table = Table(mti_data, colWidths=[9*cm, 9*cm])
        table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, COLOR_GRID),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('BACKGROUND', (0,0), (0,-1), COLOR_ROW_EVEN),
        ]))
    
    story.append(table)
    story.append(Spacer(1, SPACER_LARGE))

def _add_summary_sections(story, styles, verification_data):
    """Aggiunge le sezioni spuntate come riassunto nella prima pagina."""
    results = verification_data.get('functional_results', {})
    if not results:
        return
    
    # Filtra solo le sezioni con show_in_summary=True
    summary_sections = []
    for section_key, section_data in results.items():
        if section_data.get('show_in_summary', False):
            summary_sections.append((section_key, section_data))
    
    # Ordina per campo 'order' per mantenere l'ordine originale del profilo
    summary_sections.sort(key=lambda x: x[1].get('order', 999))
    
    if not summary_sections:
        return
    
    story.append(_create_styled_paragraph("Riepilogo Verifiche", styles['SectionHeader']))
    story.append(Spacer(1, 0.2 * cm))
    
    for section_key, section_data in summary_sections:
        section_title = section_data.get('title', section_key)
        story.append(_create_styled_paragraph(section_title, styles['NormalBold']))
        story.append(Spacer(1, 0.1 * cm))
        
        # Mostra i campi della sezione
        fields = section_data.get('fields') or []
        if fields:
            field_rows = []
            for field in fields:
                label = field.get('label') or field.get('key', '').replace('_', ' ').title()
                value = field.get('value', '')
                field_rows.append([
                    _create_styled_paragraph(label, styles['Normal']),
                    _create_styled_paragraph(str(value), styles['Normal']),
                ])
            if field_rows:
                table = Table(field_rows, colWidths=[6.5 * cm, 11.5 * cm])
                table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
                    ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(table)
                story.append(Spacer(1, 0.2 * cm))
        
        # Mostra le righe della sezione
        rows = section_data.get('rows') or []
        if rows:
            is_checklist = section_data.get('section_type') == 'checklist'
            
            # Crea l'intestazione
            header_cells = []
            if is_checklist:
                header_cells.append(_create_styled_paragraph("Verifica", styles['TableHeaderBold']))
            
            header_keys = []
            first_row_values = rows[0].get('values', []) if rows else []
            for value_entry in first_row_values:
                header_cells.append(
                    _create_styled_paragraph(
                        value_entry.get('label') or value_entry.get('key', ''),
                        styles['TableHeaderBold']
                    )
                )
                header_keys.append(value_entry.get('key'))
            
            table_data = [header_cells]
            
            for row in rows:
                row_cells = []
                if is_checklist:
                    row_cells.append(_create_styled_paragraph(row.get('label') or row.get('key', ''), styles['Normal']))
                
                value_map = {entry.get('key'): entry.get('value') for entry in row.get('values', [])}
                for key in header_keys:
                    row_cells.append(_create_styled_paragraph(str(value_map.get(key, '')), styles['Normal']))
                table_data.append(row_cells)
            
            if table_data:
                table = Table(table_data, repeatRows=1)
                table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
                    ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
                    ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_HEADER_TEXT),
                    ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                story.append(table)
                story.append(Spacer(1, 0.2 * cm))
    
    story.append(Spacer(1, 0.3 * cm))


def _add_final_evaluation(story, styles, verification_data):
    """Aggiunge il riquadro con la valutazione finale."""
    # Distingue tra verifica elettrica e funzionale
    is_functional = bool(verification_data.get('functional_results'))
    if is_functional:
        story.append(_create_styled_paragraph("Esito Verifica Funzionale", styles['SectionHeader']))
    else:
        story.append(_create_styled_paragraph("Esito Verifica Sicurezza Elettrica", styles['SectionHeader']))
    story.append(Spacer(1, SPACER_MEDIUM))
    
    overall_status = verification_data.get('overall_status', '')
    is_pass = overall_status in ('PASSATO', 'CONFORME')
    is_conforme_con_annotazione = overall_status == 'CONFORME CON ANNOTAZIONE'
    
    if is_conforme_con_annotazione:
        finale_text = "APPARECCHIO CONFORME CON ANNOTAZIONE"
        finale_style = ParagraphStyle(name='FinaleDynamic', parent=styles['FinaleBase'])
        finale_style.borderColor = colors.orange
        finale_style.textColor = colors.orange
    elif is_pass:
        finale_text = "APPARECCHIO CONFORME"
        finale_style = ParagraphStyle(name='FinaleDynamic', parent=styles['FinaleBase'])
        finale_style.borderColor = colors.darkgreen
        finale_style.textColor = colors.darkgreen
    else:
        finale_text = "APPARECCHIO NON CONFORME"
        finale_style = ParagraphStyle(name='FinaleDynamic', parent=styles['FinaleBase'])
        finale_style.borderColor = colors.red
        finale_style.textColor = colors.red
    
    story.append(_create_styled_paragraph(finale_text, finale_style))
    story.append(Spacer(1, SPACER_LARGE))
    visual_data = verification_data.get('visual_inspection_data', {})
    notes_raw = visual_data.get('notes')
    notes = (notes_raw or '').strip()
    if notes:
        story.append(Spacer(1, 0.2*cm))
        # Esegui l'escape del contenuto delle note per evitare errori di parsing HTML
        story.append(_create_styled_paragraph(f"<b>Note:</b> {html.escape(notes)}", styles['Normal']))
    

    story.append(Spacer(1, SPACER_EXTRA_LARGE))

def _add_signature(story, styles, technician_name, signature_data): # <-- 2. Usa signature_data
    """Aggiunge la sezione per la firma leggendo i dati binari."""
    technician_paragraph = _create_styled_paragraph(f"<b>Tecnico Verificatore:</b> {technician_name or 'N/D'}", styles['Nometec'])
    
    signature_content = Paragraph("<b>Firma:</b>________________________", styles['Normal'])
    
    # --- 3. MODIFICA CHIAVE: Crea l'immagine dai dati binari ---
    if signature_data:
        try:
            signature_image = QImage.fromData(signature_data)
            signature_bytes = _compress_qimage_to_bytes(
                signature_image,
                SIGN_MAX_W_CM,
                SIGN_MAX_H_CM,
                prefer_jpeg=False,
            )
            if signature_bytes:
                image_file = io.BytesIO(signature_bytes)
                signature_img = Image(image_file, width=SIGN_MAX_W_CM*cm, height=SIGN_MAX_H_CM*cm, kind='proportional')
            else:
                image_file = io.BytesIO(signature_data)
                signature_img = Image(image_file, width=SIGN_MAX_W_CM*cm, height=SIGN_MAX_H_CM*cm, kind='proportional')
            signature_img.hAlign = 'CENTER'
            signature_content = signature_img
        except Exception as e:
            logging.warning(f"Impossibile caricare l'immagine della firma dai dati del DB: {e}")

    table = Table([[technician_paragraph, signature_content]], colWidths=[9*cm, 9*cm])
    table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'CENTER'), ('LEFTPADDING', (0,0), (-1,-1), 0)]))
    story.append(table)

def _add_visual_inspection(story, styles, verification_data):
    """Aggiunge la tabella con i risultati dell'ispezione visiva."""
    visual_data = verification_data.get('visual_inspection_data', {})
    if not visual_data or not visual_data.get('checklist'):
        return # Non aggiunge la sezione se non ci sono dati
        
    story.append(_create_styled_paragraph("Ispezione Visiva", styles['SectionHeader']))
    header = [_create_styled_paragraph("Controllo", styles['TableHeaderBold']), _create_styled_paragraph("Esito", styles['TableHeaderBold'])]
    table_data = [header]
    
    # --- MODIFICA CHIAVE: Leggiamo il nuovo campo 'result' ---
    for item in visual_data.get('checklist', []):
        esito_text = item.get('result', 'N/D') # Prende il testo salvato: OK, KO, N/A
        
        # Opzionale: Applica uno stile diverso in base al risultato
    
        if esito_text == "KO":
            esito_paragraph = _create_styled_paragraph("NON CONFORME", styles['NonConforme'])
        elif esito_text == "OK":
            esito_paragraph = _create_styled_paragraph("CONFORME", styles['Conforme'])
        else: # Per N/A o altro
            esito_paragraph = _create_styled_paragraph("NON APPLICABILE", styles['Normal'])

        table_data.append([
            _create_styled_paragraph(item.get('item', ''), styles['Normal']), 
            esito_paragraph
        ])
                           
    table = Table(table_data, colWidths=[14.5*cm, 3.5*cm], repeatRows=1)
    style_cmds = _get_modern_table_style(has_header=True)
    # Aggiungi zebra striping
    for i in range(2, len(table_data), 2):
        style_cmds.append(('BACKGROUND', (0, i), (-1, i), COLOR_ROW_EVEN))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    

    story.append(Spacer(1, SPACER_LARGE))

def _add_electrical_measurements(story, styles, verification_data):
    """Aggiunge la tabella con le misure elettriche usando la nuova struttura dati."""
    measurements = verification_data.get('results') or []
    if not measurements:
        return

    story.append(_create_styled_paragraph("Misure Elettriche", styles['SectionHeader']))
    
    header = [_create_styled_paragraph(h, styles['TableHeaderBold']) for h in ["Misura", "Valore Misurato", "Limite Norma", "Esito"]]
    table_data = [header]
    
    for res in measurements:
        esito_style = styles['Conforme'] if res.get('passed') else styles['NonConforme']
        esito_text = "CONFORME" if res.get('passed') else "NON CONFORME"
        
        valore = res.get('value', 'N/A')
        limite = res.get('limit_value')
        unita = res.get('unit', '')
        
        # --- AGGIUNTA POLARITÀ ---
        nome_misura = res.get('name', '')
        
        # Controlla se c'è informazione sulla polarità
        polarity = res.get('polarity', '')  # Nuovo campo per la polarità
        if polarity:
            nome_misura = f"{nome_misura} ({polarity})"
        
        valore_misurato = f"{valore} {unita}".strip() if valore != 'N/A' else 'N/A'
        limite_norma = f"≤ {limite} {unita}".strip() if limite is not None else 'N/A'
        
        table_data.append([
            _create_styled_paragraph(nome_misura, styles['Normal']),
            _create_styled_paragraph(valore_misurato, styles['Normal']),
            _create_styled_paragraph(limite_norma, styles['Normal']),
            _create_styled_paragraph(esito_text, esito_style)
        ])
        
    table = Table(table_data, colWidths=[7*cm, 3.5*cm, 4.5*cm, 3*cm], repeatRows=1)
    style_cmds = _get_modern_table_style(has_header=True)
    # Aggiungi zebra striping e colorazione per esiti
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, i), (2, i), COLOR_ROW_EVEN))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    story.append(Spacer(1, SPACER_LARGE))


def _add_functional_sections(story, styles, verification_data):
    """Stampa il dettaglio delle verifiche funzionali in modo leggibile."""
    results = verification_data.get('functional_results', {})
    if not results:
        return

    # Se una sezione è marcata per il riepilogo in prima pagina,
    # non va ristampata nel dettaglio della seconda pagina.
    detail_sections = sorted(
        [
            (section_key, section_data)
            for section_key, section_data in results.items()
            if not section_data.get('show_in_summary', False)
        ],
        key=lambda x: x[1].get('order', 999),
    )

    if not detail_sections:
        return

    story.append(_create_styled_paragraph("Verifica Funzionale", styles['SectionHeader']))

    for section_key, section_data in detail_sections:
        story.append(_create_styled_paragraph(section_data.get('title', section_key).upper(), styles['NormalBold']))
        story.append(Spacer(1, 0.2 * cm))

        fields = section_data.get('fields') or []
        if fields:
            field_rows = []
            for field in fields:
                label = field.get('label') or field.get('key', '').replace('_', ' ').title()
                value = field.get('value', '')
                if value is None:
                    value = ''
                field_rows.append([
                    _create_styled_paragraph(label, styles['NormalBold']),
                    _create_styled_paragraph(str(value), styles['Normal']),
                ])
            table = Table(field_rows, colWidths=[6.5 * cm, 11.5 * cm])
            table.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
                ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(table)
            story.append(Spacer(1, 0.2 * cm))

        rows = section_data.get('rows') or []
        if rows:
            first_row_values = rows[0].get('values', [])
            # Determina se è una checklist o una tabella
            is_checklist = section_data.get('section_type') == 'checklist'
            
            # Crea l'intestazione
            header_cells = []
            if is_checklist:
                # Per le checklist: includi la colonna "Verifica"
                header_cells.append(_create_styled_paragraph("Verifica", styles['TableHeaderBold']))
            
            header_keys = []
            for value_entry in first_row_values:
                header_cells.append(
                    _create_styled_paragraph(
                        value_entry.get('label') or value_entry.get('key', ''),
                        styles['TableHeaderBold']
                    )
                )
                header_keys.append(value_entry.get('key'))
            table_data = [header_cells]

            for row in rows:
                row_cells = []
                if is_checklist:
                    # Per le checklist: includi il nome della riga nella prima colonna
                    row_cells.append(_create_styled_paragraph(row.get('label') or row.get('key', ''), styles['Normal']))
                
                value_map = {entry.get('key'): entry.get('value') for entry in row.get('values', [])}
                for key in header_keys:
                    cell_value = value_map.get(key, '')
                    if cell_value is None:
                        cell_value = ''
                    row_cells.append(_create_styled_paragraph(str(cell_value), styles['Normal']))
                table_data.append(row_cells)

            table = Table(table_data, repeatRows=1)
            table.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
                ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
                ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_HEADER_TEXT),
                ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(table)
            story.append(Spacer(1, 0.3 * cm))

        story.append(Spacer(1, 0.3 * cm))



def _preprocess_image_for_pdf(abs_path, max_pixels=3500):
    """Pre-processa un'immagine con PIL per garantire compatibilità con ReportLab.
    
    - Applica la rotazione EXIF (foto da smartphone)
    - Converte in RGB se necessario (CMYK, palette, RGBA, ecc.)
    - Ridimensiona se troppo grande per evitare problemi di memoria
    - Restituisce un BytesIO con l'immagine in formato JPEG/PNG
    """
    pil_img = PILImage.open(abs_path)
    
    # Forza il caricamento completo per verificare che l'immagine non sia corrotta
    pil_img.load()
    
    # Applica rotazione EXIF (foto da smartphone ruotate)
    try:
        exif = pil_img.getexif()
        if exif:
            orientation_key = None
            for tag_id, tag_name in ExifTags.TAGS.items():
                if tag_name == 'Orientation':
                    orientation_key = tag_id
                    break
            if orientation_key and orientation_key in exif:
                orientation = exif[orientation_key]
                if orientation == 3:
                    pil_img = pil_img.rotate(180, expand=True)
                elif orientation == 6:
                    pil_img = pil_img.rotate(270, expand=True)
                elif orientation == 8:
                    pil_img = pil_img.rotate(90, expand=True)
    except Exception:
        pass  # Ignora errori EXIF, procedi con l'immagine com'è
    
    # Ridimensiona se troppo grande (limita il lato più lungo)
    w, h = pil_img.size
    if max(w, h) > max_pixels:
        ratio = max_pixels / max(w, h)
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        pil_img = pil_img.resize((new_w, new_h), PILImage.LANCZOS)
    
    # Determina il formato di output
    has_transparency = pil_img.mode in ('RGBA', 'LA', 'PA') or \
        (pil_img.mode == 'P' and 'transparency' in pil_img.info)
    
    buf = io.BytesIO()
    if has_transparency:
        # Mantieni PNG per immagini con trasparenza
        if pil_img.mode != 'RGBA':
            pil_img = pil_img.convert('RGBA')
        pil_img.save(buf, format='PNG', optimize=True)
    else:
        # Converti in RGB e salva come JPEG per tutte le altre
        if pil_img.mode != 'RGB':
            pil_img = pil_img.convert('RGB')
        pil_img.save(buf, format='JPEG', quality=100)
    
    buf.seek(0)
    return buf


def _render_pdf_attachment_pages(abs_path):
    """Renderizza le pagine di un PDF allegato come immagini da inserire nel report."""
    try:
        from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions
    except ImportError as exc:
        raise RuntimeError("QtPdf non disponibile per includere PDF allegati nel report.") from exc

    pdf_doc = QPdfDocument()
    load_status = pdf_doc.load(abs_path)

    load_ok = True
    if hasattr(QPdfDocument, "Error"):
        none_error = getattr(QPdfDocument.Error, "None_", None)
        no_error = getattr(QPdfDocument.Error, "NoError", None)
        valid_results = {result for result in (none_error, no_error) if result is not None}
        if valid_results and load_status not in valid_results:
            load_ok = False
    elif hasattr(QPdfDocument, "Status"):
        ready_status = getattr(QPdfDocument.Status, "Ready", None)
        if ready_status is not None and load_status != ready_status:
            load_ok = False

    if not load_ok:
        raise ValueError(f"Impossibile caricare il PDF allegato (status={load_status}).")

    page_count = pdf_doc.pageCount()
    if page_count <= 0:
        raise ValueError("Il PDF allegato non contiene pagine renderizzabili.")

    render_options = QPdfDocumentRenderOptions()
    rendered_pages = []

    for page_index in range(page_count):
        use_landscape = False
        metrics = _get_attachment_page_metrics(use_landscape=False)
        render_width = max(1, _cm_to_px(metrics["max_width_cm"]))
        render_height = max(1, _cm_to_px(metrics["max_height_cm"]))

        try:
            page_size = pdf_doc.pagePointSize(page_index)
            page_width = float(page_size.width())
            page_height = float(page_size.height())
            if page_width > 0 and page_height > 0:
                use_landscape = page_width > page_height
                metrics = _get_attachment_page_metrics(use_landscape=use_landscape)
                max_width_px = max(1, _cm_to_px(metrics["max_width_cm"]))
                max_height_px = max(1, _cm_to_px(metrics["max_height_cm"]))
                page_ratio = min(max_width_px / page_width, max_height_px / page_height)
                render_width = max(1, int(page_width * page_ratio))
                render_height = max(1, int(page_height * page_ratio))
        except Exception:
            pass

        image = pdf_doc.render(page_index, QSize(render_width, render_height), render_options)
        if image.isNull():
            raise ValueError(f"Rendering non riuscito per il PDF allegato, pagina {page_index + 1}.")

        page_bytes = _compress_qimage_to_bytes(
            image,
            max_w_cm=metrics["max_width_cm"],
            max_h_cm=metrics["max_height_cm"],
            prefer_jpeg=True,
        )
        if not page_bytes:
            raise ValueError(f"Compressione non riuscita per il PDF allegato, pagina {page_index + 1}.")

        page_buffer = io.BytesIO(page_bytes)
        page_buffer.seek(0)
        rendered_pages.append({
            "buffer": page_buffer,
            "use_landscape": use_landscape,
        })

    return rendered_pages


def _add_attachments_to_report(story, styles, verification_data):
    """Aggiunge immagini e PDF allegati alla verifica nel report PDF."""
    attachments = verification_data.get('attachments', [])
    if not attachments:
        return

    first_attachment = True

    def _start_attachment_page(use_landscape, title=None, description_text=None, include_section_header=False):
        template_name = "Landscape" if use_landscape else "Portrait"
        story.append(NextPageTemplate(template_name))
        story.append(PageBreak())
        if include_section_header:
            story.append(_create_styled_paragraph("Allegati", styles['SectionHeader']))
            story.append(Spacer(1, SPACER_MEDIUM))
        if title:
            story.append(_create_styled_paragraph(title, styles['NormalBold']))
        if description_text:
            story.append(_create_styled_paragraph(description_text, styles['Normal']))
        if title or description_text:
            story.append(Spacer(1, SPACER_MEDIUM))

    for att in attachments:
        file_path = att.get('file_path')
        filename = att.get('filename', 'Allegato')
        description = att.get('description') or filename

        if not file_path:
            logging.warning(f"Allegato {filename} saltato: percorso file vuoto.")
            _start_attachment_page(
                use_landscape=False,
                title=filename,
                description_text=f"Allegato non disponibile: {filename} (file non presente in cache locale)",
                include_section_header=first_attachment,
            )
            story.append(_create_styled_paragraph(
                "⚠ Il file allegato non è disponibile localmente e non è stato possibile recuperarlo.",
                styles['Normal']
            ))
            story.append(Spacer(1, SPACER_MEDIUM))
            first_attachment = False
            continue

        abs_path = os.path.join(config.ATTACHMENTS_DIR, file_path)
        if not os.path.exists(abs_path):
            logging.warning(f"File allegato non trovato per il report: {abs_path}")
            _start_attachment_page(
                use_landscape=False,
                title=filename,
                description_text=f"File non trovato: {filename}",
                include_section_header=first_attachment,
            )
            story.append(_create_styled_paragraph(
                f"⚠ File allegato non trovato: {file_path}",
                styles['Normal']
            ))
            story.append(Spacer(1, SPACER_MEDIUM))
            first_attachment = False
            continue

        mime = (att.get('mime_type') or '').lower()

        if mime == 'application/pdf' or filename.lower().endswith('.pdf'):
            try:
                pdf_pages = _render_pdf_attachment_pages(abs_path)
                total_pages = len(pdf_pages)
                for page_index, page_info in enumerate(pdf_pages):
                    use_landscape = bool(page_info.get("use_landscape"))
                    metrics = _get_attachment_page_metrics(use_landscape=use_landscape)
                    title = f"Pagina {page_index + 1}/{total_pages}" if total_pages > 1 else None
                    _start_attachment_page(
                        use_landscape=use_landscape,
                        title=title,
                        description_text=None,
                        include_section_header=first_attachment and page_index == 0,
                    )

                    pdf_img = Image(page_info["buffer"])
                    iw, ih = pdf_img.drawWidth, pdf_img.drawHeight
                    if iw > 0 and ih > 0:
                        ratio = min(
                            metrics["max_width"] / iw,
                            metrics["max_height"] / ih,
                            1.0,
                        )
                        pdf_img.drawWidth = iw * ratio
                        pdf_img.drawHeight = ih * ratio
                    pdf_img.hAlign = 'CENTER'
                    story.append(pdf_img)
                first_attachment = False
            except Exception as e:
                logging.warning(f"Impossibile inserire PDF allegato nel report: {e}")
                story.append(_create_styled_paragraph(
                    f"Impossibile includere il PDF allegato: {filename}",
                    styles['Normal']
                ))
                story.append(Spacer(1, SPACER_MEDIUM))
            continue

        if not mime.startswith('image/'):
            _start_attachment_page(
                use_landscape=False,
                title=filename,
                description_text=f"Allegato non incorporato: {filename} ({mime or 'formato sconosciuto'})",
                include_section_header=first_attachment,
            )
            story.append(_create_styled_paragraph(
                f"Allegato non incorporato: {filename} ({mime or 'formato sconosciuto'})",
                styles['Normal']
            ))
            story.append(Spacer(1, SPACER_MEDIUM))
            first_attachment = False
            continue

        try:
            img_buffer = _preprocess_image_for_pdf(abs_path)
            img = Image(img_buffer)
            iw, ih = img.drawWidth, img.drawHeight
            use_landscape = iw > ih
            metrics = _get_attachment_page_metrics(use_landscape=use_landscape)
            _start_attachment_page(
                use_landscape=use_landscape,
                title=None,
                description_text=None,
                include_section_header=first_attachment,
            )
            if iw > 0 and ih > 0:
                ratio = min(metrics["max_width"] / iw, metrics["max_height"] / ih, 1.0)
                img.drawWidth = iw * ratio
                img.drawHeight = ih * ratio
            img.hAlign = 'CENTER'
            story.append(img)
            first_attachment = False
        except Exception as e:
            logging.warning(f"Impossibile inserire immagine allegata nel report: {e}")
            story.append(_create_styled_paragraph(
                f"Impossibile caricare l'immagine: {filename}",
                styles['Normal']
            ))
            story.append(Spacer(1, SPACER_MEDIUM))


def _add_footer(canvas, doc, device_info, verification_data):
    """Disegna il piè di pagina su ogni pagina."""
    canvas.saveState()
    canvas.setFont(FONT_NORMAL, 9)
    canvas.setStrokeColor(COLOR_GRID)
    page_width = canvas._pagesize[0]
    canvas.line(doc.leftMargin, 1.4*cm, page_width - doc.rightMargin, 1.4*cm)
    footer_text = f"Dispositivo S/N: {device_info.get('serial_number', 'N/A')}   |   Verifica del: {verification_data.get('date', 'N/A')}   |   Email: assistenza@amstrento.it"
    canvas.drawString(doc.leftMargin, 1*cm, footer_text)
    canvas.drawRightString(page_width - doc.rightMargin, 1*cm, f"Pagina {doc.page}")
    canvas.restoreState()


def _build_report_doc(filename, title, footer_callback):
    """Crea un documento PDF con template portrait/landscape."""
    doc = BaseDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=PAGE_MARGIN,
        leftMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title=title,
        pageCompression=1,
    )

    portrait_frame = Frame(
        PAGE_MARGIN,
        PAGE_MARGIN,
        A4[0] - 2 * PAGE_MARGIN,
        A4[1] - 2 * PAGE_MARGIN,
        id="portrait_frame",
    )
    landscape_frame = Frame(
        PAGE_MARGIN,
        PAGE_MARGIN,
        LANDSCAPE_A4[0] - 2 * PAGE_MARGIN,
        LANDSCAPE_A4[1] - 2 * PAGE_MARGIN,
        id="landscape_frame",
    )
    doc.addPageTemplates([
        PageTemplate(id="Portrait", frames=[portrait_frame], onPage=footer_callback, pagesize=A4),
        PageTemplate(id="Landscape", frames=[landscape_frame], onPage=footer_callback, pagesize=LANDSCAPE_A4),
    ])
    return doc

# --- Funzione Principale per Creare il Report ---

def create_report(filename, device_info, customer_info, destination_info, mti_info, report_settings, verification_data, technician_name, signature_data):
    """
    Genera il report PDF assemblando le varie sezioni con la nuova struttura a due pagine.
    """
    styles = _create_styles()
    story = []
    footer_callback = lambda canvas, doc: _add_footer(canvas, doc, device_info, verification_data)
    doc = _build_report_doc(filename, "Rapporto di Verifica", footer_callback)

    # --- ASSEMBLAGGIO PAGINA 1: DATI, ESITO E FIRMA ---
    _add_logo(story, report_settings)
    _add_header(story, styles, verification_data)
    _add_customer_info(story, styles, customer_info, destination_info)
    _add_device_info(story, styles, device_info, verification_data)
    _add_instrument_info(story, styles, mti_info, verification_data)
    _add_summary_sections(story, styles, verification_data)
    _add_final_evaluation(story, styles, verification_data)
    _add_signature(story, styles, technician_name, signature_data)

    # --- INSERIMENTO INTERRUZIONE DI PAGINA ---
    story.append(PageBreak())

    # --- ASSEMBLAGGIO PAGINA 2: DETTAGLI TECNICI ---
    _add_visual_inspection(story, styles, verification_data)
    _add_electrical_measurements(story, styles, verification_data)
    _add_functional_sections(story, styles, verification_data)

    # --- ALLEGATI (se presenti) ---
    _add_attachments_to_report(story, styles, verification_data)

    try:
        doc.build(story)
        logging.info(f"Report PDF generato con successo: {filename}")
    except Exception as e:
        # Se il build fallisce e ci sono allegati, riprova senza allegati
        if verification_data.get('attachments'):
            logging.warning(f"Build PDF fallito con allegati, ritento senza allegati: {e}", exc_info=True)
            doc2 = _build_report_doc(filename, "Rapporto di Verifica", footer_callback)
            story_no_att = []
            _add_logo(story_no_att, report_settings)
            _add_header(story_no_att, styles, verification_data)
            _add_customer_info(story_no_att, styles, customer_info, destination_info)
            _add_device_info(story_no_att, styles, device_info, verification_data)
            _add_instrument_info(story_no_att, styles, mti_info, verification_data)
            _add_summary_sections(story_no_att, styles, verification_data)
            _add_final_evaluation(story_no_att, styles, verification_data)
            _add_signature(story_no_att, styles, technician_name, signature_data)
            story_no_att.append(PageBreak())
            _add_visual_inspection(story_no_att, styles, verification_data)
            _add_electrical_measurements(story_no_att, styles, verification_data)
            _add_functional_sections(story_no_att, styles, verification_data)
            # Aggiungi nota al posto degli allegati
            story_no_att.append(PageBreak())
            story_no_att.append(_create_styled_paragraph(
                "⚠ Allegati non inclusi: impossibile elaborare le immagini allegate.",
                styles['Normal']
            ))
            try:
                doc2.build(story_no_att)
                logging.info(f"Report PDF generato senza allegati: {filename}")
            except Exception as e2:
                logging.error(f"Errore durante la creazione del PDF (anche senza allegati): {e2}", exc_info=True)
                raise
        else:
            logging.error(f"Errore durante la creazione del PDF: {e}", exc_info=True)
            raise


def _add_system_devices_info(story, styles, devices_info, verification_data):
    """Aggiunge la tabella con l'elenco dei dispositivi del sistema."""
    story.append(_create_styled_paragraph("Dispositivi del Sistema", styles['SectionHeader']))

    # Header della tabella
    header_row = [
        _create_styled_paragraph("N.", styles['TableHeaderBold']),
        _create_styled_paragraph("Tipo Apparecchio", styles['TableHeaderBold']),
        _create_styled_paragraph("Matricola", styles['TableHeaderBold']),
        _create_styled_paragraph("Costruttore / Modello", styles['TableHeaderBold']),
        _create_styled_paragraph("Inv. AMS", styles['TableHeaderBold']),
    ]

    table_data = [header_row]

    for idx, dev in enumerate(devices_info, start=1):
        desc = dev.get('description', 'N/D')
        serial = dev.get('serial_number', '')
        manufacturer = dev.get('manufacturer', '')
        model = dev.get('model', '')
        mfg_model = f"{manufacturer} {model}".strip() or 'N/D'
        ams_inv = dev.get('ams_inventory', '')

        row = [
            _create_styled_paragraph(str(idx), styles['Normal']),
            _create_styled_paragraph(desc, styles['Normal']),
            _create_styled_paragraph(serial, styles['Normal']),
            _create_styled_paragraph(mfg_model, styles['Normal']),
            _create_styled_paragraph(ams_inv, styles['Normal']),
        ]
        table_data.append(row)

    col_widths = [1*cm, 6*cm, 3.5*cm, 4.5*cm, 3*cm]
    table = Table(table_data, colWidths=col_widths)
    style_commands = [
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_HEADER_TEXT),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    # Alternating row colors
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            style_commands.append(('BACKGROUND', (0, i), (-1, i), COLOR_ROW_EVEN))

    table.setStyle(TableStyle(style_commands))
    story.append(table)
    story.append(Spacer(1, SPACER_LARGE))


def _add_system_final_evaluation(story, styles, verification_data):
    """Aggiunge il riquadro con la valutazione finale per una verifica di sistema."""
    story.append(_create_styled_paragraph("Esito Verifica di Sistema", styles['SectionHeader']))
    story.append(Spacer(1, SPACER_MEDIUM))

    overall_status = verification_data.get('overall_status', '')
    is_pass = overall_status in ('PASSATO', 'CONFORME')
    is_conforme_con_annotazione = overall_status == 'CONFORME CON ANNOTAZIONE'

    if is_conforme_con_annotazione:
        finale_text = "SISTEMA CONFORME CON ANNOTAZIONE"
        finale_style = ParagraphStyle(name='FinaleDynamic', parent=styles['FinaleBase'])
        finale_style.borderColor = colors.orange
        finale_style.textColor = colors.orange
    elif is_pass:
        finale_text = "SISTEMA CONFORME"
        finale_style = ParagraphStyle(name='FinaleDynamic', parent=styles['FinaleBase'])
        finale_style.borderColor = colors.darkgreen
        finale_style.textColor = colors.darkgreen
    else:
        finale_text = "SISTEMA NON CONFORME"
        finale_style = ParagraphStyle(name='FinaleDynamic', parent=styles['FinaleBase'])
        finale_style.borderColor = colors.red
        finale_style.textColor = colors.red

    story.append(_create_styled_paragraph(finale_text, finale_style))
    story.append(Spacer(1, SPACER_LARGE))

    visual_data = verification_data.get('visual_inspection_data', {})
    notes_raw = visual_data.get('notes')
    notes = (notes_raw or '').strip()
    if notes:
        story.append(Spacer(1, 0.2*cm))
        story.append(_create_styled_paragraph(f"<b>Note:</b> {html.escape(notes)}", styles['Normal']))

    story.append(Spacer(1, SPACER_EXTRA_LARGE))


def _add_system_footer(canvas, doc, devices_info, verification_data):
    """Aggiunge il footer per il report di sistema."""
    canvas.saveState()
    footer_style = ParagraphStyle(
        name='Footer', fontName=FONT_NORMAL, fontSize=7,
        textColor=COLOR_TEXT_SECONDARY, alignment=TA_CENTER
    )
    system_name = verification_data.get('system_name', 'Sistema')
    code = verification_data.get('verification_code', '')
    device_count = len(devices_info)
    footer_text = f"Verifica di Sistema: {system_name} | Codice: {code} | {device_count} dispositivi | Pagina {doc.page}"
    canvas.restoreState()


def _make_signature_image(signature_data: bytes | None, width_cm: float = 3.5, height_cm: float = 1.2):
    """Crea un oggetto Image ReportLab a partire dai dati binari della firma."""
    if not signature_data:
        return None
    try:
        sig_qimg = QImage.fromData(signature_data)
        if sig_qimg.isNull():
            return None
        sig_bytes = _compress_qimage_to_bytes(sig_qimg, width_cm, height_cm, prefer_jpeg=False)
        buf = io.BytesIO(sig_bytes) if sig_bytes else io.BytesIO(signature_data)
        img = Image(buf, width=width_cm * cm, height=height_cm * cm, kind='proportional')
        img.hAlign = 'CENTER'
        return img
    except Exception as e:
        logging.warning(f"Impossibile creare la firma visiva per il report: {e}")
        return None


def _add_ecografo_quality_cover_page(story, styles, device_info, customer_info, destination_info, check):
    """Pagina 1: Copertina 'Manuale di qualità per apparecchio ecografico' con grafica curata."""
    story.append(Spacer(1, 1.2 * cm))
    story.append(_create_styled_paragraph("Manuale di qualità", ParagraphStyle(
        name='CoverTitle1', fontName=FONT_BOLD, fontSize=26, leading=30, alignment=TA_CENTER, textColor=COLOR_MAIN_BLUE
    )))
    story.append(Spacer(1, 0.4 * cm))
    story.append(_create_styled_paragraph("per", ParagraphStyle(
        name='CoverTitle2', fontName=FONT_NORMAL, fontSize=20, leading=24, alignment=TA_CENTER, textColor=COLOR_TEXT_SECONDARY
    )))
    story.append(Spacer(1, 0.4 * cm))
    story.append(_create_styled_paragraph("apparecchio ecografico", ParagraphStyle(
        name='CoverTitle3', fontName=FONT_BOLD, fontSize=26, leading=30, alignment=TA_CENTER, textColor=COLOR_MAIN_BLUE
    )))
    story.append(Spacer(1, 2.0 * cm))

    year = check.verification_date.split("-")[0] if (check and check.verification_date) else "2025"
    story.append(_create_styled_paragraph(f"<u><b>Anno creazione:</b></u> &nbsp;&nbsp;<font color='#2563eb'><b>{year}</b></font>", ParagraphStyle(
        name='CoverYear', fontName=FONT_NORMAL, fontSize=13, alignment=TA_CENTER
    )))
    story.append(Spacer(1, 2.5 * cm))

    marca = device_info.get("manufacturer") or ""
    modello = device_info.get("model") or ""
    inv = device_info.get("customer_inventory") or device_info.get("ams_inventory") or ""
    sn = device_info.get("serial_number") or ""
    struttura = customer_info.get("name") or destination_info.get("name") or ""
    reparto = device_info.get("department") or ""

    grid_data = [
        [
            _create_styled_paragraph("<b>Marca:</b> " + marca, styles['Normal']),
            _create_styled_paragraph("<b>Modello:</b> " + modello, styles['Normal']),
        ],
        [
            _create_styled_paragraph("<b>Nr. inv.:</b> " + inv, styles['Normal']),
            _create_styled_paragraph("<b>s/n:</b> " + sn, styles['Normal']),
        ],
        [
            _create_styled_paragraph("<b>Struttura:</b> " + struttura, styles['Normal']),
            _create_styled_paragraph("<b>Reparto:</b> " + reparto, styles['Normal']),
        ],
    ]
    grid_table = Table(grid_data, colWidths=[9 * cm, 9 * cm])
    grid_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLOR_ROW_EVEN),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(grid_table)


def _add_ecografo_quality_connected_probes_page(story, styles, device_info, check):
    """Pagina 2: DATI APPARECCHIO & DATI SONDE COLLEGATE con stile colorato e moderno."""
    section_title_style = ParagraphStyle(
        name='ColorCenterHeader', fontName=FONT_BOLD, fontSize=12, leading=15, alignment=TA_CENTER, textColor=colors.white
    )
    
    # Barra di intestazione DATI APPARECCHIO
    sec1_table = Table([[_create_styled_paragraph("DATI APPARECCHIO", section_title_style)]], colWidths=[18 * cm])
    sec1_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLOR_HEADER_BG),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(sec1_table)
    story.append(Spacer(1, 0.2 * cm))

    inv = device_info.get("customer_inventory") or device_info.get("ams_inventory") or ""
    sn = device_info.get("serial_number") or ""
    reparto = device_info.get("department") or ""
    costruttore = device_info.get("manufacturer") or ""
    modello = device_info.get("model") or ""
    struttura = device_info.get("customer_name") or device_info.get("destination_name") or ""

    notes_str = (check.notes if check else "") or ""

    label_style = ParagraphStyle(name='DevLabelStyle', parent=styles['NormalBold'], textColor=COLOR_MAIN_BLUE)

    dev_data = [
        [
            _create_styled_paragraph("Inventario:", label_style), _create_styled_paragraph(inv, styles['Normal']),
            _create_styled_paragraph("Reparto:", label_style), _create_styled_paragraph(reparto, styles['Normal']),
            _create_styled_paragraph("Costruttore:", label_style), _create_styled_paragraph(costruttore, styles['Normal']),
        ],
        [
            _create_styled_paragraph("S/N:", label_style), _create_styled_paragraph(sn, styles['Normal']),
            _create_styled_paragraph("Struttura:", label_style), _create_styled_paragraph(struttura, styles['Normal']),
            _create_styled_paragraph("Modello:", label_style), _create_styled_paragraph(modello, styles['Normal']),
        ],
        [
            _create_styled_paragraph("Note Ecografo:", label_style),
            _create_styled_paragraph(notes_str, styles['Normal']),
            "", "", "", ""
        ]
    ]
    dev_table = Table(dev_data, colWidths=[2.5 * cm, 3.5 * cm, 2.5 * cm, 3.5 * cm, 2.5 * cm, 3.5 * cm])
    dev_table.setStyle(TableStyle([
        ('SPAN', (1, 2), (5, 2)),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f1f5f9')),
        ('BACKGROUND', (2, 0), (2, 1), colors.HexColor('#f1f5f9')),
        ('BACKGROUND', (4, 0), (4, 1), colors.HexColor('#f1f5f9')),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(dev_table)
    story.append(Spacer(1, 0.8 * cm))

    # Barra di intestazione DATI SONDE COLLEGATE
    sec2_table = Table([[_create_styled_paragraph("DATI SONDE COLLEGATE", section_title_style)]], colWidths=[18 * cm])
    sec2_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLOR_HEADER_BG),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(sec2_table)
    story.append(Spacer(1, 0.3 * cm))

    probes_list = check.probes if check else []
    for i, probe in enumerate(probes_list):
        probe_data = [
            [
                _create_styled_paragraph(f"<b>Sonda {i + 1}</b>", ParagraphStyle(
                    name='ProbeHeaderLabel', fontName=FONT_BOLD, fontSize=11, leading=14, alignment=TA_CENTER, textColor=colors.white
                )),
                _create_styled_paragraph("Inventario:", label_style),
                _create_styled_paragraph(probe.inventory or "", styles['Normal']),
                _create_styled_paragraph("Costruttore:", label_style),
                _create_styled_paragraph(probe.manufacturer or "", styles['Normal']),
            ],
            [
                "",
                _create_styled_paragraph("Tipo:", label_style),
                _create_styled_paragraph(probe.probe_type or "", styles['Normal']),
                _create_styled_paragraph("S/N / Modello:", label_style),
                _create_styled_paragraph(f"{probe.serial_number or ''} / {probe.model or ''}".strip(" /"), styles['Normal']),
            ]
        ]
        p_table = Table(probe_data, colWidths=[3.2 * cm, 2.5 * cm, 3.5 * cm, 2.5 * cm, 6.3 * cm])
        p_table.setStyle(TableStyle([
            ('SPAN', (0, 0), (0, 1)),
            ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
            ('BACKGROUND', (0, 0), (0, 1), COLOR_HEADER_BG),
            ('BACKGROUND', (1, 0), (1, 1), colors.HexColor('#f1f5f9')),
            ('BACKGROUND', (3, 0), (3, 1), colors.HexColor('#f1f5f9')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(p_table)
def _get_max_vertical_scarto(val_str: str) -> str:
    """Estrae solo lo scarto massimo (più alto) dalle misure verticali per la tabella riassuntiva."""
    if not val_str:
        return ""
    if ";" not in val_str:
        return val_str
    vals = val_str.split(";")
    effs = [20, 40, 60, 80, 100, 120, 140, 160]
    max_scarto = -1.0
    for idx, eff in enumerate(effs):
        if idx < len(vals) and vals[idx].strip():
            try:
                m_val = float(vals[idx].strip().replace(",", "."))
                scarto = abs(m_val - eff)
                if scarto > max_scarto:
                    max_scarto = scarto
            except ValueError:
                pass
    return f"{max_scarto:.1f}" if max_scarto >= 0 else ""


def _get_max_horizontal_scarto(val_str: str) -> str:
    """Estrae solo lo scarto massimo (più alto) dalle misure orizzontali per la tabella riassuntiva."""
    if not val_str:
        return ""
    if val_str == "N/A":
        return "N/A"
    if ";" not in val_str:
        return val_str
    vals = val_str.split(";")
    targets = [(-20, 0), (-40, 1), (-60, 2), (-80, 3), (40, 4), (20, 5)]
    max_scarto = -1.0
    for eff, idx in targets:
        if idx < len(vals) and vals[idx].strip() and vals[idx].strip() != "N/A":
            try:
                m_val = float(vals[idx].strip().replace(",", "."))
                scarto = abs(abs(m_val) - abs(eff))
                if scarto > max_scarto:
                    max_scarto = scarto
            except ValueError:
                pass
    return f"{max_scarto:.1f}" if max_scarto >= 0 else ""


def _get_mass_area(val_str: str) -> str:
    """Estrae solo il valore dell'area dalle misurazioni di massa anecoica/iperecogena."""
    if not val_str:
        return ""
    if val_str == "N/A":
        return "N/A"
    if "=" in val_str:
        parts = dict(p.split("=") for p in val_str.split(";") if "=" in p)
        return parts.get("area", "")
    return val_str


def _get_dead_zone_value(val_str: str) -> str:
    """Estrae solo il valore numerico della zona morta per la tabella riassuntiva."""
    if not val_str:
        return ""
    if val_str == "N/A":
        return "N/A"
    if "=" in val_str:
        parts = dict(p.split("=") for p in val_str.split(";") if "=" in p)
        return parts.get("zona_morta", "")
    return val_str


def _add_ecografo_quality_probe_summary_table(story, styles, probe, probe_history_list, check, signature_data: bytes | None = None):
    """Tabella riassuntiva per la sonda con valori sintetici (scarto max, area massa, zona morta), giudizio e firma."""
    title_style = ParagraphStyle(
        name='SummaryTitle', fontName=FONT_BOLD, fontSize=12, leading=15, alignment=TA_CENTER, textColor=COLOR_MAIN_BLUE
    )
    story.append(_create_styled_paragraph("<u>Tabella riassuntiva Controlli di Qualità:</u>", title_style))
    story.append(Spacer(1, 0.3 * cm))

    sn = probe.serial_number or ""
    sonda_desc = probe.model or probe.probe_type or ""
    header_info = [
        [_create_styled_paragraph(f"<b>Sonda:</b> {sonda_desc}", styles['Normal']), _create_styled_paragraph(f"<b>s/n:</b> {sn}", styles['Normal'])],
        [_create_styled_paragraph(f"<b>Mod. usata per test:</b> {probe.test_model or ''}", styles['Normal']), ""],
        [_create_styled_paragraph(f"<b>Preset impostato:</b> {probe.preset or ''}", styles['Normal']), ""],
        [_create_styled_paragraph(f"<b>Gain:</b> {probe.gain or ''}", styles['Normal']), ""],
        [_create_styled_paragraph(f"<b>Power:</b> {probe.power or ''}", styles['Normal']), ""],
    ]
    h_table = Table(header_info, colWidths=[12 * cm, 6 * cm])
    h_table.setStyle(TableStyle([
        ('SPAN', (0, 1), (1, 1)),
        ('SPAN', (0, 2), (1, 2)),
        ('SPAN', (0, 3), (1, 3)),
        ('SPAN', (0, 4), (1, 4)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(h_table)
    story.append(Spacer(1, 0.4 * cm))

    # Raccogli tutti gli stadi presenti nello storico di questa sonda
    found_stages = set()
    for p in probe_history_list:
        if p.control_stage:
            found_stages.add(p.control_stage)
    if probe.control_stage:
        found_stages.add(probe.control_stage)

    def stage_key(st):
        if not st:
            return (3, "")
        st_lower = st.lower()
        if st_lower == "baseline":
            return (0, 0)
        if st_lower.startswith("controllo"):
            try:
                num = int(st.split()[-1])
                return (1, num)
            except Exception:
                pass
        return (2, st)

    stages_sorted = sorted(list(found_stages), key=stage_key)
    standard_stages = ["Baseline", "Controllo 1", "Controllo 2", "Controllo 3"]
    for s_st in standard_stages:
        if s_st not in stages_sorted and len(stages_sorted) < 4:
            stages_sorted.append(s_st)
    stages = sorted(list(set(stages_sorted)), key=stage_key)
    if not stages:
        stages = ["Baseline"]
    
    stage_probe_map = {}
    for p in probe_history_list:
        st = p.control_stage or "Baseline"
        stage_probe_map[st] = p
    curr_stage = probe.control_stage or "Baseline"
    stage_probe_map[curr_stage] = probe

    param_keys = [
        ("date", "Data"),
        ("ispezione_visiva", "Ispezione visiva"),
        ("uniformita", "Uniformità"),
        ("profondita_max", "Profondità max (cm)"),
        ("misure_verticali", "Misure verticali\n(scarto max mm)"),
        ("misure_orizzontali", "Misure orizzontali\n(scarto max mm)"),
        ("zona_morta", "Zona Morta (mm)"),
        ("risoluzione_3cm_assiale", "Risoluzione assiale\n3 cm (mm)"),
        ("risoluzione_3cm_laterale", "Risoluzione laterale\n3 cm (mm)"),
        ("risoluzione_11cm_assiale", "Risoluzione assiale\n11 cm (mm)"),
        ("risoluzione_11cm_laterale", "Risoluzione laterale\n11 cm (mm)"),
        ("massa_anecoica", "Massa anecoica\narea (mm²)"),
        ("massa_iperecogena", "Massa iperecogena\narea (mm²)"),
    ]

    MAX_STAGES_PER_TABLE = 4
    stage_chunks = [stages[i:i + MAX_STAGES_PER_TABLE] for i in range(0, len(stages), MAX_STAGES_PER_TABLE)]

    summary_tables = []
    param_label_style = ParagraphStyle(name='ParamLabelStyle', parent=styles['NormalBold'], textColor=COLOR_MAIN_BLUE, fontSize=8, leading=11)
    sig_cache = {}

    for chunk_idx, sub_stages in enumerate(stage_chunks):
        # Intestazione della tabella con fondo blu e testo bianco (VISIBILITÀ GARANTITA)
        header_row = [_create_styled_paragraph("<b>Parametro</b>", styles['TableHeaderBold'])] + [
            _create_styled_paragraph(f"<b>{st}</b>", styles['TableHeaderBold']) for st in sub_stages
        ]
        table_rows = [header_row]

        for p_key, p_label in param_keys:
            row = [_create_styled_paragraph(p_label, param_label_style)]
            for st in sub_stages:
                p_obj = stage_probe_map.get(st)
                if not p_obj:
                    row.append(_create_styled_paragraph("", styles['Normal']))
                    continue
                if p_key == "date":
                    val_str = getattr(p_obj, 'verification_date', None) or (check.verification_date if (check and p_obj == probe) else "") or ""
                    row.append(_create_styled_paragraph(val_str, styles['Normal']))
                elif p_key == "misure_verticali":
                    ctrl = next((c for c in p_obj.controls if c.control_key == p_key), None)
                    raw_val = ctrl.value if (ctrl and ctrl.value) else ""
                    row.append(_create_styled_paragraph(_get_max_vertical_scarto(raw_val), styles['Normal']))
                elif p_key == "misure_orizzontali":
                    ctrl = next((c for c in p_obj.controls if c.control_key == p_key), None)
                    raw_val = ctrl.value if (ctrl and ctrl.value) else ""
                    row.append(_create_styled_paragraph(_get_max_horizontal_scarto(raw_val), styles['Normal']))
                elif p_key == "zona_morta":
                    ctrl = next((c for c in p_obj.controls if c.control_key == p_key), None)
                    raw_val = ctrl.value if (ctrl and ctrl.value) else ""
                    row.append(_create_styled_paragraph(_get_dead_zone_value(raw_val), styles['Normal']))
                elif p_key in ("massa_anecoica", "massa_iperecogena"):
                    ctrl = next((c for c in p_obj.controls if c.control_key == p_key), None)
                    raw_val = ctrl.value if (ctrl and ctrl.value) else ""
                    row.append(_create_styled_paragraph(_get_mass_area(raw_val), styles['Normal']))
                else:
                    ctrl = next((c for c in p_obj.controls if c.control_key == p_key), None)
                    val_str = ctrl.value if (ctrl and ctrl.value) else ""
                    row.append(_create_styled_paragraph(val_str, styles['Normal']))
            table_rows.append(row)

        # Riga Giudizio complessivo (CON BADGE COLORATO)
        giudizio_row = [_create_styled_paragraph("<b>Giudizio complessivo</b>", param_label_style)]
        for st in sub_stages:
            p_obj = stage_probe_map.get(st)
            if p_obj:
                raw_j = getattr(p_obj, 'overall_judgment', None) or (check.overall_status if (check and p_obj == probe) else "") or "BUONO"
                j_upper = raw_j.upper()
                if j_upper in ("CONFORME", "PASSATO", "BUONO"):
                    j_p = _create_styled_paragraph(f"<b>{raw_j}</b>", styles['Conforme'])
                elif j_upper in ("SUFFICIENTE", "CONFORME CON ANNOTAZIONE"):
                    j_p = _create_styled_paragraph(f"<b>{raw_j}</b>", ParagraphStyle(name='SuffStyle', fontName=FONT_BOLD, textColor=COLOR_MAIN_OCRA, fontSize=10, leading=14))
                elif j_upper in ("NON CONFORME", "NON SUFFICIENTE", "FALLITO", "INSUFFICIENTE"):
                    j_p = _create_styled_paragraph(f"<b>{raw_j}</b>", styles['NonConforme'])
                else:
                    j_p = _create_styled_paragraph(f"<b>{raw_j}</b>", styles['NormalBold'])
            else:
                j_p = _create_styled_paragraph("", styles['Normal'])
            giudizio_row.append(j_p)
        table_rows.append(giudizio_row)

        # Riga Nome e firma del tecnico
        tech_row = [_create_styled_paragraph("<b>Nome e firma del\ntecnico</b>", param_label_style)]
        for st in sub_stages:
            p_obj = stage_probe_map.get(st)
            if p_obj:
                t_name = getattr(p_obj, 'technician_name', None) or (check.technician_name if (check and p_obj == probe) else "") or ""
                t_username = getattr(p_obj, 'technician_username', None) or (check.technician_username if (check and p_obj == probe) else "") or ""
                
                cell_flowables = []
                if t_name:
                    cell_flowables.append(_create_styled_paragraph(t_name, styles['Normal']))
                
                sig_bytes = None
                if check and p_obj == probe and signature_data:
                    sig_bytes = signature_data
                elif t_username:
                    if t_username not in sig_cache:
                        import database
                        sig_cache[t_username] = database.get_signature_by_username(t_username)
                    sig_bytes = sig_cache[t_username]
                
                if sig_bytes:
                    sig_img = _make_signature_image(sig_bytes, width_cm=2.6, height_cm=0.9)
                    if sig_img:
                        cell_flowables.append(Spacer(1, 0.1 * cm))
                        cell_flowables.append(sig_img)
                tech_row.append(cell_flowables if cell_flowables else _create_styled_paragraph("", styles['Normal']))
            else:
                tech_row.append(_create_styled_paragraph("", styles['Normal']))
        table_rows.append(tech_row)

        w_stage = 3.0
        col_widths = [6 * cm] + [w_stage * cm] * len(sub_stages)

        summary_table = Table(table_rows, colWidths=col_widths)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),       # Intestazione blu scuro
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f1f5f9')), # Colonna parametri grigio slate
            ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]

        # Righe alternate a colori per la leggibilità
        for r_i in range(1, len(table_rows) - 2):
            if r_i % 2 == 0:
                style_cmds.append(('BACKGROUND', (1, r_i), (-1, r_i), COLOR_ROW_EVEN))

        # Evidenziazione della riga Giudizio complessivo
        g_row_idx = len(table_rows) - 2
        style_cmds.append(('BACKGROUND', (0, g_row_idx), (-1, g_row_idx), colors.HexColor('#f8fafc')))

        summary_table.setStyle(TableStyle(style_cmds))
        summary_tables.append(summary_table)

    for st_tbl in summary_tables:
        story.append(st_tbl)
        story.append(Spacer(1, 0.4 * cm))


def _add_ecografo_quality_probe_detail(story, styles, probe, index, check, signature_data: bytes | None = None):
    """Dettaglio Controlli di Qualità a 10 punti con tabelle colorate e firma del tecnico in calce."""
    title_style = ParagraphStyle(
        name='DetailHeaderTitle', fontName=FONT_BOLD, fontSize=12, leading=15, alignment=TA_CENTER, textColor=COLOR_MAIN_BLUE
    )
    story.append(_create_styled_paragraph("<u>Dettaglio Controlli di Qualità</u>", title_style))
    story.append(Spacer(1, 0.3 * cm))

    year = check.verification_date.split("-")[0] if (check and check.verification_date) else "2025"
    sn = probe.serial_number or "____"
    sonda_desc = probe.model or probe.probe_type or "____"

    header_info = [
        [
            _create_styled_paragraph(f"<b>Anno:</b> {year}", styles['Normal']),
            _create_styled_paragraph(f"<b>Sonda:</b> {sonda_desc}", styles['Normal']),
            _create_styled_paragraph(f"<b>s/n:</b> {sn}", styles['Normal']),
        ]
    ]
    h_table = Table(header_info, colWidths=[6 * cm, 6 * cm, 6 * cm])
    h_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f1f5f9')),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(h_table)
    story.append(Spacer(1, 0.3 * cm))

    c_map = {c.control_key: c for c in probe.controls}
    sec_title_style = ParagraphStyle(name='SecTitleStyle', fontName=FONT_BOLD, fontSize=10, leading=13, textColor=COLOR_MAIN_BLUE)

    def _fmt_check(target_val, cur_val):
        if cur_val == target_val:
            if target_val == 'BUONO':
                return "<font color='#059669'><b>[X] BUONO</b></font>"
            elif target_val == 'SUFFICIENTE':
                return "<font color='#d97706'><b>[X] SUFFICIENTE</b></font>"
            elif target_val == 'INSUFFICIENTE':
                return "<font color='#dc2626'><b>[X] INSUFFICIENTE</b></font>"
            return f"<b>[X] {target_val}</b>"
        return f"[  ] {target_val}"

    # 1. ISPEZIONE VISIVA
    c1_val = (c_map.get("ispezione_visiva").value or "BUONO").upper() if c_map.get("ispezione_visiva") else "BUONO"
    c1_block = [
        _create_styled_paragraph("1. ISPEZIONE VISIVA:", sec_title_style),
        Spacer(1, 0.1 * cm),
        _create_styled_paragraph(f"{_fmt_check('BUONO', c1_val)} &nbsp;&nbsp;&nbsp;&nbsp;(non vi sono crepe/tagli/altre non conformità né sulla sonda né sulla guaina)", styles['Normal']),
        _create_styled_paragraph(f"{_fmt_check('SUFFICIENTE', c1_val)} &nbsp;&nbsp;&nbsp;&nbsp;(vi sono delle non conformità di lieve entità)", styles['Normal']),
        _create_styled_paragraph(f"{_fmt_check('INSUFFICIENTE', c1_val)} &nbsp;&nbsp;&nbsp;&nbsp;(vi sono delle non conformità di entità non lieve)", styles['Normal']),
        Spacer(1, 0.3 * cm)
    ]
    story.append(KeepTogether(c1_block))

    # 2. UNIFORMITÀ
    c2_val = (c_map.get("uniformita").value or "BUONO").upper() if c_map.get("uniformita") else "BUONO"
    c2_block = [
        _create_styled_paragraph("2. UNIFORMITÀ:", sec_title_style),
        Spacer(1, 0.1 * cm),
        _create_styled_paragraph(f"{_fmt_check('BUONO', c2_val)} &nbsp;&nbsp;&nbsp;&nbsp;(immagine uniforme in tutte le zone lungo tutta la profondità di penetrazione)", styles['Normal']),
        _create_styled_paragraph(f"{_fmt_check('SUFFICIENTE', c2_val)} &nbsp;&nbsp;&nbsp;&nbsp;(vi sono delle zone non uniformi che però non pregiudicano la visione dei pin)", styles['Normal']),
        _create_styled_paragraph(f"{_fmt_check('INSUFFICIENTE', c2_val)} &nbsp;&nbsp;&nbsp;&nbsp;(vi sono delle zone non uniformi che pregiudicano la visione dei pin)", styles['Normal']),
        Spacer(1, 0.3 * cm)
    ]
    story.append(KeepTogether(c2_block))

    # 3. MASSIMA PROFONDITA' DI PENETRAZIONE
    c3_val = c_map.get("profondita_max").value if c_map.get("profondita_max") else ""
    c3_block = [
        _create_styled_paragraph("3. MASSIMA PROFONDITA’ DI PENETRAZIONE:", sec_title_style),
        Spacer(1, 0.1 * cm),
        _create_styled_paragraph("E’ determinata dalla frequenza del trasduttore, dal sistema di attenuazione utilizzato e dall’impostazione dei parametri di sistema.", styles['Normal']),
        Spacer(1, 0.15 * cm),
        _create_styled_paragraph(f"DISTANZA DELL’ULTIMO BERSAGLIO VISIBILE (cm): &nbsp;<font color='#1e3a5f'><b>{c3_val or '___'}</b></font>", styles['Normal']),
        Spacer(1, 0.15 * cm),
        _create_styled_paragraph("<font color='#475569'>Valori di riferimento: &nbsp;&nbsp;frequenze minori di 2.5 MHz &rarr; > 16 cm &nbsp;&nbsp;&nbsp;&nbsp; frequenze fra 2,5 e 5 MHz &rarr; > 13 cm<br/>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;frequenze fra 5 e 8 MHz &rarr; > 6 cm &nbsp;&nbsp;&nbsp;&nbsp; frequenze fra 8 e 12 Mhz &rarr; > 4 cm</font>", styles['Normal']),
        Spacer(1, 0.3 * cm)
    ]
    story.append(KeepTogether(c3_block))

    # 4. MISURE VERTICALI
    c4_raw = c_map.get("misure_verticali").value if c_map.get("misure_verticali") else ""
    c4_vals = c4_raw.split(";") if (c4_raw and ";" in c4_raw) else []
    v_rows = [[_create_styled_paragraph("<b>Effettivo (mm)</b>", styles['TableHeaderBold']), _create_styled_paragraph("<b>Misurato (mm)</b>", styles['TableHeaderBold']), _create_styled_paragraph("<b>Scarto (mm)</b>", styles['TableHeaderBold'])]]
    effs_v = [20, 40, 60, 80, 100, 120, 140, 160]
    for idx, eff in enumerate(effs_v):
        meas_str = c4_vals[idx] if idx < len(c4_vals) else ""
        try:
            m_val = float(meas_str.replace(",", "."))
            scarto_str = f"{abs(m_val - eff):.1f}"
        except ValueError:
            scarto_str = ""
        v_rows.append([
            _create_styled_paragraph(str(eff), styles['NormalBold']),
            _create_styled_paragraph(meas_str, styles['Normal']),
            _create_styled_paragraph(scarto_str, styles['Normal']),
        ])
    v_table = Table(v_rows, colWidths=[5.5 * cm, 5.5 * cm, 5.5 * cm])
    v_style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    for r_i in range(1, len(v_rows)):
        if r_i % 2 == 0:
            v_style_cmds.append(('BACKGROUND', (0, r_i), (-1, r_i), COLOR_ROW_EVEN))
    v_table.setStyle(TableStyle(v_style_cmds))

    c4_block = [
        _create_styled_paragraph("4. MISURE VERTICALI:", sec_title_style),
        Spacer(1, 0.1 * cm),
        v_table,
        Spacer(1, 0.15 * cm),
        _create_styled_paragraph("<font color='#475569'>Valori di riferimento: scarto < 1,5 mm fra due misure contigue</font>", styles['Normal']),
        Spacer(1, 0.3 * cm)
    ]
    story.append(KeepTogether(c4_block))

    # 5. MISURE ORIZZONTALI
    c5_raw = c_map.get("misure_orizzontali").value if c_map.get("misure_orizzontali") else ""
    is_c5_na = (c5_raw == "N/A")
    c5_vals = c5_raw.split(";") if (c5_raw and ";" in c5_raw) else []

    def _calc_scarto_h(eff_num, val_str):
        if not val_str or val_str in ("N/A", ""):
            return ""
        try:
            m_val = float(val_str.replace(",", "."))
            return f"{abs(abs(m_val) - abs(eff_num)):.1f}"
        except ValueError:
            return ""

    def _get_m_h(idx):
        if is_c5_na:
            return "N/A"
        return c5_vals[idx] if idx < len(c5_vals) and c5_vals[idx] else ""

    h_rows = [
        [
            _create_styled_paragraph("<b>Effettivo (mm)</b>", styles['TableHeaderBold']),
            _create_styled_paragraph("<b>Misurato (mm)</b>", styles['TableHeaderBold']),
            _create_styled_paragraph("<b>Scarto (mm)</b>", styles['TableHeaderBold']),
            _create_styled_paragraph("<b>Effettivo (mm)</b>", styles['TableHeaderBold']),
            _create_styled_paragraph("<b>Misurato (mm)</b>", styles['TableHeaderBold']),
            _create_styled_paragraph("<b>Scarto (mm)</b>", styles['TableHeaderBold']),
        ]
    ]

    left_effs = [-20, -40, -60, -80]
    left_indices = [0, 1, 2, 3]

    right_effs = [40, 20, None, None]
    right_indices = [4, 5, None, None]

    for r in range(4):
        l_eff = left_effs[r]
        l_idx = left_indices[r]
        l_meas = _get_m_h(l_idx)
        l_scarto = _calc_scarto_h(l_eff, l_meas)

        r_eff = right_effs[r]
        if r_eff is not None:
            r_idx = right_indices[r]
            r_meas = _get_m_h(r_idx)
            r_scarto = _calc_scarto_h(r_eff, r_meas)
            r_eff_str = str(r_eff)
        else:
            r_meas = ""
            r_scarto = ""
            r_eff_str = ""

        row_cells = [
            _create_styled_paragraph(str(l_eff), styles['NormalBold']),
            _create_styled_paragraph(l_meas, styles['Normal']),
            _create_styled_paragraph(l_scarto, styles['Normal']),
            _create_styled_paragraph(r_eff_str, styles['NormalBold']) if r_eff_str else _create_styled_paragraph("", styles['Normal']),
            _create_styled_paragraph(r_meas, styles['Normal']),
            _create_styled_paragraph(r_scarto, styles['Normal']),
        ]
        h_rows.append(row_cells)

    h_table = Table(h_rows, colWidths=[2.8 * cm, 2.8 * cm, 2.8 * cm, 2.8 * cm, 2.8 * cm, 2.8 * cm])
    h_style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    for r_i in range(1, len(h_rows)):
        if r_i % 2 == 0:
            h_style_cmds.append(('BACKGROUND', (0, r_i), (-1, r_i), COLOR_ROW_EVEN))
    h_table.setStyle(TableStyle(h_style_cmds))
    
    c5_block = [
        _create_styled_paragraph("5. MISURE ORIZZONTALI:", sec_title_style),
        Spacer(1, 0.1 * cm),
        h_table,
        Spacer(1, 0.15 * cm),
        _create_styled_paragraph("<font color='#475569'>Valori di riferimento: scarto < 2 mm fra due misure contigue</font>", styles['Normal']),
        Spacer(1, 0.1 * cm),
        _create_styled_paragraph(f"[{'X' if is_c5_na else '  '}] <b>TEST NON APPLICABILE A QUESTA SONDA</b>", styles['Normal']),
        Spacer(1, 0.3 * cm)
    ]
    story.append(KeepTogether(c5_block))

    # 6. ZONA MORTA
    c6_raw = c_map.get("zona_morta").value if c_map.get("zona_morta") else ""
    is_c6_na = (c6_raw == "N/A")
    c6_parts = dict(p.split("=") for p in c6_raw.split(";") if "=" in p) if (c6_raw and ";" in c6_raw) else {}
    c6_block = [
        _create_styled_paragraph("6. ZONA MORTA:", sec_title_style),
        Spacer(1, 0.1 * cm),
        _create_styled_paragraph(f"NUMERO TOTALE BERSAGLI: &nbsp;<font color='#1e3a5f'><b>{c6_parts.get('targets', '___')}</b></font> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ZONA MORTA (mm): &nbsp;<font color='#1e3a5f'><b>{c6_parts.get('zona_morta', '___')}</b></font>", styles['Normal']),
        Spacer(1, 0.15 * cm),
        _create_styled_paragraph("<font color='#475569'>Valori di riferimento: &nbsp;&nbsp;< 7 mm per frequenze < 3 MHz<br/>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;< 5 mm per frequenze comprese tra 3 e 7 MHz<br/>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;< 3 mm per frequenze > 7 MHz</font>", styles['Normal']),
        Spacer(1, 0.1 * cm),
        _create_styled_paragraph(f"[{'X' if is_c6_na else '  '}] <b>TEST NON APPLICABILE A QUESTA SONDA</b>", styles['Normal']),
        Spacer(1, 0.3 * cm)
    ]
    story.append(KeepTogether(c6_block))

    # 7. RISOLUZIONE 3 CM
    c7_ax = c_map.get("risoluzione_3cm_assiale").value if c_map.get("risoluzione_3cm_assiale") else ""
    c7_lat = c_map.get("risoluzione_3cm_laterale").value if c_map.get("risoluzione_3cm_laterale") else ""
    r3_headers = ["Ultima coppia\nbersagli distinguibili", "1ª\n(4 mm)", "2ª\n(3 mm)", "3ª\n(2 mm)", "4ª\n(1 mm)", "5ª\n(.5 mm)", "6ª\n(.25 mm)", "N/A"]
    r3_rows = [[_create_styled_paragraph(f"<b>{h}</b>", styles['TableHeaderBold']) for h in r3_headers]]
    opts_3 = ["1a (4 mm)", "2a (3 mm)", "3a (2 mm)", "4a (1 mm)", "5a (.5 mm)", "6a (.25 mm)", "N/A"]
    ax_row = [_create_styled_paragraph("Assiale", styles['NormalBold'])] + [_create_styled_paragraph("[X]" if c7_ax == o else "[  ]", styles['Normal']) for o in opts_3]
    lat_row = [_create_styled_paragraph("Laterale", styles['NormalBold'])] + [_create_styled_paragraph("[X]" if c7_lat == o else "[  ]", styles['Normal']) for o in opts_3]
    r3_rows.append(ax_row)
    r3_rows.append(lat_row)
    r3_table = Table(r3_rows, colWidths=[4.6 * cm] + [1.9 * cm] * 7)
    r3_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f1f5f9')),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    c7_block = [
        _create_styled_paragraph("7. RISOLUZIONE 3 CM:", sec_title_style),
        Spacer(1, 0.1 * cm),
        r3_table,
        Spacer(1, 0.15 * cm),
        _create_styled_paragraph("<font color='#475569'>Valori di riferimento: non deve superare di 1 mm i valori indicati dal costruttore</font>", styles['Normal']),
        Spacer(1, 0.3 * cm)
    ]
    story.append(KeepTogether(c7_block))

    # 8. RISOLUZIONE 11 CM
    c8_ax = c_map.get("risoluzione_11cm_assiale").value if c_map.get("risoluzione_11cm_assiale") else ""
    c8_lat = c_map.get("risoluzione_11cm_laterale").value if c_map.get("risoluzione_11cm_laterale") else ""
    r11_headers = ["Ultima coppia\nbersagli distinguibili", "1ª\n(5 mm)", "2ª\n(4 mm)", "3ª\n(3 mm)", "4ª\n(2 mm)", "5ª\n(1 mm)", "Non\nApplicabile"]
    r11_rows = [[_create_styled_paragraph(f"<b>{h}</b>", styles['TableHeaderBold']) for h in r11_headers]]
    opts_11 = ["1a (5 mm)", "2a (4 mm)", "3a (3 mm)", "4a (2 mm)", "5a (1 mm)", "Non Applicabile"]
    ax11_row = [_create_styled_paragraph("Assiale", styles['NormalBold'])] + [_create_styled_paragraph("[X]" if c8_ax == o else "[  ]", styles['Normal']) for o in opts_11]
    lat11_row = [_create_styled_paragraph("Laterale", styles['NormalBold'])] + [_create_styled_paragraph("[X]" if c8_lat == o else "[  ]", styles['Normal']) for o in opts_11]
    r11_rows.append(ax11_row)
    r11_rows.append(lat11_row)
    r11_table = Table(r11_rows, colWidths=[4.5 * cm] + [2.25 * cm] * 6)
    r11_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f1f5f9')),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    c8_block = [
        _create_styled_paragraph("8. RISOLUZIONE 11 CM:", sec_title_style),
        Spacer(1, 0.1 * cm),
        r11_table,
        Spacer(1, 0.15 * cm),
        _create_styled_paragraph("<font color='#475569'>Valori di riferimento: non deve superare di 1 mm i valori indicati dal costruttore</font>", styles['Normal']),
        Spacer(1, 0.3 * cm)
    ]
    story.append(KeepTogether(c8_block))

    # 9. ANALISI DELLE MASSE ANECOICHE
    c9_raw = c_map.get("massa_anecoica").value if c_map.get("massa_anecoica") else ""
    is_c9_na = (c9_raw == "N/A")
    c9_parts = dict(p.split("=") for p in c9_raw.split(";") if "=" in p) if (c9_raw and ";" in c9_raw) else {}
    m9_data = [
        [_create_styled_paragraph("<b>Diametro orizzontale (mm)</b>", styles['TableHeaderBold']), _create_styled_paragraph("<b>Diametro verticale (mm)</b>", styles['TableHeaderBold']), _create_styled_paragraph("<b>Rapporto diametri</b>", styles['TableHeaderBold']), _create_styled_paragraph("<b>Area (mm²)</b>", styles['TableHeaderBold'])],
        [_create_styled_paragraph(c9_parts.get('oriz', ''), styles['Normal']), _create_styled_paragraph(c9_parts.get('vert', ''), styles['Normal']), _create_styled_paragraph(c9_parts.get('rapporto', ''), styles['Normal']), _create_styled_paragraph(c9_parts.get('area', ''), styles['Normal'])]
    ]
    m9_table = Table(m9_data, colWidths=[4.4 * cm, 4.4 * cm, 4.4 * cm, 4.4 * cm])
    m9_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    c9_block = [
        _create_styled_paragraph("9. ANALISI DELLE MASSE ANECOICHE:", sec_title_style),
        Spacer(1, 0.1 * cm),
        m9_table,
        Spacer(1, 0.15 * cm),
        _create_styled_paragraph(f"[{'X' if is_c9_na else '  '}] <b>TEST NON APPLICABILE A QUESTA SONDA</b>", styles['Normal']),
        Spacer(1, 0.1 * cm),
        _create_styled_paragraph("<font color='#475569'>Valori di riferimento: non esiste una standardizzazione tale da indicare dei limiti di tolleranza su scala quantitativa</font>", styles['Normal']),
        Spacer(1, 0.3 * cm)
    ]
    story.append(KeepTogether(c9_block))

    # 10. ANALISI DELLE MASSE IPERECOGENE
    c10_raw = c_map.get("massa_iperecogena").value if c_map.get("massa_iperecogena") else ""
    is_c10_na = (c10_raw == "N/A")
    c10_parts = dict(p.split("=") for p in c10_raw.split(";") if "=" in p) if (c10_raw and ";" in c10_raw) else {}
    m10_data = [
        [_create_styled_paragraph("<b>Diametro orizzontale (mm)</b>", styles['TableHeaderBold']), _create_styled_paragraph("<b>Diametro verticale (mm)</b>", styles['TableHeaderBold']), _create_styled_paragraph("<b>Rapporto diametri</b>", styles['TableHeaderBold']), _create_styled_paragraph("<b>Area (mm²)</b>", styles['TableHeaderBold'])],
        [_create_styled_paragraph(c10_parts.get('oriz', ''), styles['Normal']), _create_styled_paragraph(c10_parts.get('vert', ''), styles['Normal']), _create_styled_paragraph(c10_parts.get('rapporto', ''), styles['Normal']), _create_styled_paragraph(c10_parts.get('area', ''), styles['Normal'])]
    ]
    m10_table = Table(m10_data, colWidths=[4.4 * cm, 4.4 * cm, 4.4 * cm, 4.4 * cm])
    m10_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    c10_block = [
        _create_styled_paragraph("10. ANALISI DELLE MASSE IPERECOGENE:", sec_title_style),
        Spacer(1, 0.1 * cm),
        m10_table,
        Spacer(1, 0.15 * cm),
        _create_styled_paragraph(f"[{'X' if is_c10_na else '  '}] <b>TEST NON APPLICABILE A QUESTA SONDA</b>", styles['Normal']),
        Spacer(1, 0.1 * cm),
        _create_styled_paragraph("<font color='#475569'>Valori di riferimento: non esiste una standardizzazione tale da indicare dei limiti di tolleranza su scala quantitativa</font>", styles['Normal']),
        Spacer(1, 0.5 * cm)
    ]
    story.append(KeepTogether(c10_block))

    # CONCLUSIONI, DATA, IL TECNICO + FIRMA
    note_text = check.notes or ""
    conc_box_table = Table([[ _create_styled_paragraph(note_text, styles['Normal']) ]], colWidths=[17.8 * cm])
    conc_box_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.5, COLOR_MAIN_BLUE),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))

    tech_label_p = _create_styled_paragraph(f"<b>IL TECNICO:</b> &nbsp;&nbsp;<font color='#1e3a5f'><b>{(check.technician_name or '').upper()}</b></font>", styles['Normal'])
    if signature_data:
        sig_img = _make_signature_image(signature_data, width_cm=4.5, height_cm=1.3)
        if sig_img:
            tech_table = Table([[tech_label_p, sig_img]], colWidths=[9 * cm, 8.8 * cm])
            tech_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            tech_footer = tech_table
        else:
            tech_footer = tech_label_p
    else:
        tech_footer = tech_label_p

    conc_block = [
        _create_styled_paragraph("CONCLUSIONI:", sec_title_style),
        Spacer(1, 0.2 * cm),
        conc_box_table,
        Spacer(1, 0.6 * cm),
        _create_styled_paragraph(f"<b>DATA:</b> &nbsp;&nbsp;<font color='#1e3a5f'><b>{check.verification_date or ''}</b></font>", styles['Normal']),
        Spacer(1, 0.6 * cm),
        tech_footer,
        Spacer(1, 0.5 * cm)
    ]
    story.append(KeepTogether(conc_block))


def create_ecografo_quality_report(
    filename: str = None,
    device_info: dict = None,
    customer_info: dict = None,
    destination_info: dict = None,
    check = None,
    technician_name: str = "",
    signature_data: bytes | None = None,
    report_settings: dict | None = None,
    output_path: str = None,
    **kwargs,
):
    """Genera il report PDF per il Controllo Qualità Sonde Ecografo con lo stesso header/footer delle altre verifiche."""
    target_filename = output_path or filename
    if not target_filename:
        raise ValueError("Percorso di output mancante per la generazione del report.")

    device_info = device_info or {}
    customer_info = customer_info or {}
    destination_info = destination_info or {}

    styles = _create_styles()
    story = []

    verification_data = {
        "date": check.verification_date if check else "",
        "verification_code": (check.verification_code if check else "N/A") or "N/A",
        "overall_status": check.overall_status if check else "",
        "is_ecografo_quality": True,
    }

    # Stesso piè di pagina e documento di verifica elettrica / funzionale
    footer_callback = lambda canvas, doc: _add_footer(canvas, doc, device_info, verification_data)
    doc = _build_report_doc(target_filename, "Report Controllo Qualità Ecografo", footer_callback)

    # 1. Logo e Intestazione identici a verifica elettrica / funzionale
    _add_logo(story, report_settings or {})
    _add_header(story, styles, verification_data)

    # 2. Copertina (Pagina 1)
    _add_ecografo_quality_cover_page(story, styles, device_info, customer_info, destination_info, check)

    # 3. Dati Apparecchio e Sonde collegate (Pagina 2)
    story.append(PageBreak())
    _add_ecografo_quality_connected_probes_page(story, styles, device_info, check)

    # Recupera lo storico pluriennale dal database
    import database
    history = database.get_probe_history_for_device(check.device_id) if (check and check.device_id) else {}

    # 4. Pagine per ciascuna sonda: Tabella Riassuntiva + Dettaglio su foglio dedicato
    probes_list = check.probes if check else []
    for i, probe in enumerate(probes_list):
        story.append(PageBreak())
        key = (probe.serial_number or probe.inventory or f"probe_order_{probe.probe_order}").strip()
        probe_history_list = history.get(key, [])
        
        # Tabella riassuntiva per la sonda (su una pagina dedicata)
        _add_ecografo_quality_probe_summary_table(story, styles, probe, probe_history_list, check, signature_data=signature_data)
        
        # Dettaglio Controlli di Qualità parte SEMPRE su un NUOVO foglio
        story.append(PageBreak())
        _add_ecografo_quality_probe_detail(story, styles, probe, i, check, signature_data=signature_data)

    doc.build(story)
    logging.info(f"Report controllo qualità sonde ecografo generato con successo: {target_filename}")


def create_system_report(filename, devices_info, customer_info, destination_info,
                         mti_info, report_settings, verification_data,
                         technician_name, signature_data):
    """
    Genera il report PDF per una verifica di sistema (CEI 62353).
    Simile a create_report ma con sezione dispositivi multipli.
    """
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=PAGE_MARGIN,
        leftMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title="Rapporto di Verifica di Sistema",
        pageCompression=1,
    )

    styles = _create_styles()
    story = []

    # --- PAGINA 1: DATI, DISPOSITIVI, ESITO E FIRMA ---
    _add_logo(story, report_settings)

    # Header specifico per sistema
    story.append(_create_styled_paragraph("Report di Verifica di Sistema", styles['ReportTitle']))
    story.append(_create_styled_paragraph("(Conforme a CEI EN 62353)", styles['ReportSubTitle']))

    system_name = verification_data.get('system_name', '')
    if system_name:
        story.append(_create_styled_paragraph(
            f"<b>Sistema:</b> {system_name}", styles['Normal']))
        story.append(Spacer(1, SPACER_MEDIUM))

    # Data e codice verifica
    right_aligned_style = ParagraphStyle(name='NormalRight', parent=styles['Normal'], alignment=2)
    header_data = [[
        _create_styled_paragraph(
            f"<b>Data Verifica:</b> {verification_data.get('date', 'N/A')}", styles['Normal']),
        _create_styled_paragraph(
            f"<b>Codice Verifica:</b> {verification_data.get('verification_code', 'N/A')}", right_aligned_style)
    ]]
    header_table = Table(header_data, colWidths=[9*cm, 9*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, SPACER_MEDIUM))

    # Dati cliente e destinazione
    _add_customer_info(story, styles, customer_info, destination_info)

    # Elenco dispositivi del sistema
    _add_system_devices_info(story, styles, devices_info, verification_data)

    # Strumento di misura
    _add_instrument_info(story, styles, mti_info, verification_data)

    # Esito finale
    _add_system_final_evaluation(story, styles, verification_data)

    # Firma
    _add_signature(story, styles, technician_name, signature_data)

    # --- PAGINA 2: DETTAGLI TECNICI ---
    story.append(PageBreak())

    # Ispezione visiva
    _add_visual_inspection(story, styles, verification_data)

    # Misure elettriche
    _add_electrical_measurements(story, styles, verification_data)

    # Build del documento
    footer_callback = lambda canvas, doc: _add_system_footer(canvas, doc, devices_info, verification_data)
    try:
        doc.build(story, onFirstPage=footer_callback, onLaterPages=footer_callback)
        logging.info(f"Report verifica di sistema generato: {filename}")
    except Exception as e:
        logging.error(f"Errore generazione report di sistema: {e}", exc_info=True)
        raise
