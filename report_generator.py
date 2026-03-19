import os
import re
import logging
import html
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER
from PySide6.QtCore import QSettings, Qt, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage
from app import config
import io

# --- Costanti di Stile e Layout - Design Moderno ---
COLOR_GRID = colors.HexColor('#e2e8f0')          # Bordi griglia eleganti
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
IMAGE_DPI = 150
LOGO_MAX_W_CM = 18
LOGO_MAX_H_CM = 4
SIGN_MAX_W_CM = 5
SIGN_MAX_H_CM = 3

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
    quality = 70 if use_jpeg else -1
    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QIODevice.WriteOnly)
    if use_jpeg:
        scaled.save(buffer, fmt, quality)
    else:
        scaled.save(buffer, fmt)
    buffer.close()
    return bytes(byte_array)

def _create_styles():
    """Crea e restituisce un dizionario di stili di paragrafo personalizzati - Design moderno."""
    styles = getSampleStyleSheet()
    styles['Normal'].fontName = FONT_NORMAL
    styles['Normal'].fontSize = 9
    styles['Normal'].leading = 12
    styles['Normal'].textColor = COLOR_TEXT_PRIMARY
    styles.add(ParagraphStyle(name='Nometec', parent=styles['Normal'], fontName=FONT_NORMAL, fontSize=11))
    styles.add(ParagraphStyle(name='NormalBold', parent=styles['Normal'], fontName=FONT_BOLD))
    styles.add(ParagraphStyle(name='TableHeaderBold', parent=styles['Normal'], fontName=FONT_BOLD, textColor=colors.white))
    styles.add(ParagraphStyle(name='ReportTitleocra', fontName=FONT_BOLD, fontSize=16, textColor=COLOR_MAIN_OCRA, alignment=TA_CENTER, spaceAfter=2))
    styles.add(ParagraphStyle(name='ReportTitle', fontName=FONT_BOLD, fontSize=16, textColor=COLOR_MAIN_BLUE, alignment=TA_CENTER, spaceAfter=2))
    styles.add(ParagraphStyle(name='ReportSubTitle', fontName=FONT_NORMAL, fontSize=9, textColor=COLOR_TEXT_SECONDARY, alignment=TA_CENTER, spaceAfter=8))
    styles.add(ParagraphStyle(name='SectionHeader', fontName=FONT_BOLD, fontSize=10, textColor=COLOR_MAIN_BLUE, spaceAfter=4, spaceBefore=6))
    styles.add(ParagraphStyle(name='Conforme', fontName=FONT_BOLD, textColor=COLOR_PASS_TEXT, fontSize=10))
    styles.add(ParagraphStyle(name='NonConforme', fontName=FONT_BOLD, textColor=COLOR_FAIL_TEXT, fontSize=10))
    styles.add(ParagraphStyle(name='FinaleBase', fontName=FONT_BOLD, fontSize=12, alignment=TA_CENTER, borderPadding=8, borderWidth=2))
    return styles

def _create_styled_paragraph(text, style):
    """Crea un paragrafo con uno stile specifico, gestendo i 'None' e i ritorni a capo."""
    text_str = str(text) if text is not None else ''
    return Paragraph(text_str.replace('\n', '<br/>'), style)

def _get_modern_table_style(has_header=True, zebra_stripe=True):
    """Restituisce uno stile moderno per le tabelle."""
    style_commands = [
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (0, -1), (-1, -1), 1, COLOR_GRID),
        ('LINEABOVE', (0, 0), (-1, 0), 1, COLOR_GRID),
        ('LINEBEFORE', (0, 0), (0, -1), 1, COLOR_GRID),
        ('LINEAFTER', (-1, 0), (-1, -1), 1, COLOR_GRID),
    ]
    
    if has_header:
        style_commands.extend([
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_HEADER_TEXT),
            ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
            ('LINEBELOW', (0, 0), (-1, 0), 2, COLOR_ACCENT_BLUE),
        ])
    
    return style_commands

# --- Funzioni per la Creazione delle Sezioni del Report ---

def _add_logo(story, report_settings):
    """Aggiunge il logo al report se presente."""
    logo_path = report_settings.get('logo_path')
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
            logging.error(f"Impossibile caricare il file del logo: {e}")

def _add_header(story, styles, verification_data):
    """Aggiunge l'intestazione del report."""
    # Distingue tra verifica elettrica e funzionale
    is_functional = bool(verification_data.get('functional_results'))
    if is_functional:
        story.append(_create_styled_paragraph("Report di Verifica Funzionale", styles['ReportTitle']))
    else:
        story.append(_create_styled_paragraph("Report di Verifica di Sicurezza Elettrica", styles['ReportTitle']))
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
    indirizzo_cliente = customer_info.get('address', 'N/D')
    telefono_cliente = customer_info.get('phone', 'N/D')
    email_cliente = customer_info.get('email', 'N/D')

    destinazione = destination_info.get('name', 'N/D')
    indirizzo_destinazione = destination_info.get('address', 'N/D')

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
    is_pass = overall_status == 'PASSATO'
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
    detail_sections = [
        (section_key, section_data)
        for section_key, section_data in results.items()
        if not section_data.get('show_in_summary', False)
    ]

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
                    row_cells.append(_create_styled_paragraph(str(value_map.get(key, '')), styles['Normal']))
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



def _add_footer(canvas, doc, device_info, verification_data):
    """Disegna il piè di pagina su ogni pagina."""
    canvas.saveState()
    canvas.setFont(FONT_NORMAL, 9)
    canvas.setStrokeColor(COLOR_GRID)
    canvas.line(doc.leftMargin, 1.4*cm, doc.width + doc.leftMargin, 1.4*cm)
    footer_text = f"Dispositivo S/N: {device_info.get('serial_number', 'N/A')}   |   Verifica del: {verification_data.get('date', 'N/A')}   |   Email: assistenza@amstrento.it"
    canvas.drawString(doc.leftMargin, 1*cm, footer_text)
    canvas.drawRightString(doc.width + doc.leftMargin, 1*cm, f"Pagina {doc.page}")
    canvas.restoreState()

# --- Funzione Principale per Creare il Report ---

def create_report(filename, device_info, customer_info, destination_info, mti_info, report_settings, verification_data, technician_name, signature_data):
    """
    Genera il report PDF assemblando le varie sezioni con la nuova struttura a due pagine.
    """
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=PAGE_MARGIN,
        leftMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title="Rapporto di Verifica",
        pageCompression=1,
    )

    styles = _create_styles()
    story = []

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


    # Il resto della funzione per costruire il documento rimane invariato
    footer_callback = lambda canvas, doc: _add_footer(canvas, doc, device_info, verification_data)
    try:
        doc.build(story, onFirstPage=footer_callback, onLaterPages=footer_callback)
        logging.info(f"Report PDF generato con successo: {filename}")
    except Exception as e:
        logging.error(f"Errore durante la creazione del PDF: {e}", exc_info=True)
        raise
