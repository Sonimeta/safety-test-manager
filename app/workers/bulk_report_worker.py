# app/workers/bulk_report_worker.py
import os
import logging
import re
import shutil
import tempfile
from datetime import datetime
import io
from PySide6.QtCore import QObject, Signal

from app import services

class BulkReportWorker(QObject):
    """
    Esegue la generazione massiva di report PDF in un thread separato.
    """
    progress_updated = Signal(int, str)
    finished = Signal(int, list)
    
    def __init__(
        self,
        verifications_to_process,
        output_folder,
        report_settings,
        naming_format='ams_inventory',
        merge_into_one=False,
        merged_output_path=None,
        merged_intro_mode='cover_and_table',
        export_cover_single=False,
        export_table_single=False,
        keep_individual_reports=True,
        cover_info=None,
    ):
        super().__init__()
        self.verifications = [dict(v) for v in verifications_to_process]
        self.output_folder = output_folder
        self.report_settings = report_settings
        self.naming_format = naming_format  # 'ams_inventory', 'serial_number', o 'customer_inventory'
        self.merge_into_one = merge_into_one
        self.merged_output_path = merged_output_path
        self.merged_intro_mode = merged_intro_mode
        self.export_cover_single = export_cover_single
        self.export_table_single = export_table_single
        self.keep_individual_reports = keep_individual_reports
        self.cover_info = cover_info or {}
        self._temp_output_dir = None
        self._is_cancelled = False

    def cancel(self):
        """Richiede l'annullamento dell'operazione."""
        logging.warning("Richiesta di annullamento della generazione massiva di report.")
        self._is_cancelled = True

    def run(self):
        """Esegue il lavoro pesante."""
        total_reports = len(self.verifications)
        success_count = 0
        failed_reports = []
        
        # Se serve solo il PDF unico, usa una cartella temporanea per i singoli
        if self.merge_into_one and not self.keep_individual_reports and not self.output_folder:
            self._temp_output_dir = tempfile.mkdtemp(prefix="stm_reports_")
            self.output_folder = self._temp_output_dir

        # Traccia i nomi di file già usati per evitare duplicati
        used_base_names = set()
        generated_files = []

        logging.info(f"Avvio generazione massiva di {total_reports} report in: {self.output_folder}")

        for i, verif in enumerate(self.verifications):
            if self._is_cancelled:
                logging.warning("Generazione massiva interrotta dall'utente.")
                break
            
            verif_id = verif.get('id')
            dev_id = verif.get('device_id')
            verification_type = verif.get('verification_type', 'ELETTRICA')
            type_label = "Funzionale" if verification_type == "FUNZIONALE" else "Elettrica"
            
            progress_percent = int(((i + 1) / total_reports) * 100)
            progress_message = f"Generazione report {i + 1} di {total_reports} (Verifica {type_label} ID: {verif_id})..."
            self.progress_updated.emit(progress_percent, progress_message)

            try:
                if not dev_id or not verif_id:
                    raise ValueError("ID dispositivo o verifica mancante.")

                # --- NUOVA LOGICA PER IL NOME DEL FILE ---
                # Gestisce i valori None convertendoli in stringa vuota prima di chiamare strip()
                ams_inv = (verif.get('ams_inventory') or '').strip()
                serial_num = (verif.get('serial_number') or '').strip()
                customer_inv = (verif.get('customer_inventory') or '').strip()
                
                # Determina il tipo di verifica e il suffisso del file
                verification_type = verif.get('verification_type', 'ELETTRICA')  # Default a ELETTRICA per retrocompatibilità
                file_suffix = "VF" if verification_type == "FUNZIONALE" else "VE"
                
                # Determina il nome base in base al formato selezionato
                if self.naming_format == 'ams_inventory':
                    base_name = ams_inv if ams_inv else serial_num  # Fallback a serial_number se ams_inventory è vuoto
                elif self.naming_format == 'serial_number':
                    base_name = serial_num if serial_num else ams_inv  # Fallback a ams_inventory se serial_number è vuoto
                elif self.naming_format == 'customer_inventory':
                    base_name = customer_inv if customer_inv else (ams_inv if ams_inv else serial_num)  # Fallback a ams_inventory o serial_number
                else:
                    # Default al comportamento precedente
                    base_name = ams_inv if ams_inv else serial_num
                
                if not base_name:
                    base_name = f"Report_Verifica_{verif_id}" # Nome di fallback
                
                # Pulisce il nome da caratteri non validi per un file
                safe_base_name = re.sub(r'[\\/*?:"<>|]', '_', base_name)
                
                # Controlla duplicati includendo il suffisso VE/VF (lo stesso nome può essere usato per VE e VF)
                full_key = f"{safe_base_name} {file_suffix}"
                original_safe_name = safe_base_name
                counter = 1
                while full_key in used_base_names:
                    safe_base_name = f"{original_safe_name}_{counter}"
                    full_key = f"{safe_base_name} {file_suffix}"
                    counter += 1
                
                os.makedirs(self.output_folder, exist_ok=True)
                
                # Crea il nome file completo e verifica che non esista già
                full_base_name = f"{safe_base_name} {file_suffix}"
                filename = os.path.join(self.output_folder, f"{full_base_name}.pdf")
                
                # Se il file esiste già, aggiungi un contatore
                file_counter = 1
                while os.path.exists(filename):
                    filename = os.path.join(self.output_folder, f"{safe_base_name}_{file_counter} {file_suffix}.pdf")
                    file_counter += 1
                
                # Registra il nome completo (con suffisso VE/VF) per il controllo duplicati
                used_base_names.add(full_key)
                # --- FINE NUOVA LOGICA ---

                # Genera il report appropriato in base al tipo
                if verification_type == "FUNZIONALE":
                    services.generate_functional_pdf_report(
                        filename=filename,
                        verification_id=verif_id,
                        device_id=dev_id,
                        report_settings=self.report_settings,
                    )
                else:
                    services.generate_pdf_report(
                        filename=filename,
                        verification_id=verif_id,
                        device_id=dev_id,
                        report_settings=self.report_settings,
                    )
                success_count += 1
                generated_files.append(filename)

            except Exception as e:
                error_message = f"Report per Verifica ID {verif_id}: Fallito ({e})"
                logging.error(f"Errore durante la generazione massiva: {error_message}", exc_info=True)
                failed_reports.append(error_message)
        
        # Fascicolazione in un unico PDF (opzionale)
        merge_success = False
        cover_path = None

        # Esportazione opzionale di frontespizio/tabella come file singoli
        if not self._is_cancelled and self.cover_info and (self.export_cover_single or self.export_table_single):
            try:
                if not self.output_folder:
                    raise ValueError("Cartella di destinazione mancante per export frontespizio/tabella.")
                os.makedirs(self.output_folder, exist_ok=True)

                if self.export_cover_single:
                    cover_single_path = self._unique_output_path(self.output_folder, "Frontespizio.pdf")
                    self._create_cover_pdf(self.cover_info, cover_single_path, include_cover=True, include_table=False)

                if self.export_table_single:
                    table_single_path = self._unique_output_path(self.output_folder, "Tabella_Verifiche.pdf")
                    self._create_cover_pdf(self.cover_info, table_single_path, include_cover=False, include_table=True)
            except Exception as e:
                error_message = f"Esportazione frontespizio/tabella fallita: {e}"
                logging.error(error_message, exc_info=True)
                failed_reports.append(error_message)

        if self.merge_into_one and not self._is_cancelled and generated_files:
            try:
                if self.cover_info:
                    temp_dir = self.output_folder or tempfile.gettempdir()
                    cover_path = self._unique_output_path(temp_dir, "_temp_frontespizio_merge.pdf")
                    include_cover = self.merged_intro_mode != "table_only"
                    include_table = self.merged_intro_mode != "cover_only"
                    self._create_cover_pdf(
                        self.cover_info,
                        cover_path,
                        include_cover=include_cover,
                        include_table=include_table,
                    )
                merged_path = self._get_merged_output_path()
                self.progress_updated.emit(99, "Fascicolazione in un unico PDF...")
                sorted_reports = sorted(generated_files, key=self._natural_sort_key_for_path)
                merge_list = [p for p in ([cover_path] + sorted_reports) if p]
                self._merge_pdfs(merge_list, merged_path)
                self.progress_updated.emit(100, f"PDF unico creato: {os.path.basename(merged_path)}")
                merge_success = True
            except Exception as e:
                error_message = f"Fascicolazione fallita: {e}"
                logging.error(error_message, exc_info=True)
                failed_reports.append(error_message)
            finally:
                if cover_path:
                    try:
                        if os.path.exists(cover_path):
                            os.remove(cover_path)
                    except Exception as e:
                        logging.warning(f"Impossibile rimuovere il frontespizio '{cover_path}': {e}")

        if self.merge_into_one and merge_success and not self.keep_individual_reports:
            removed_count = 0
            for path in generated_files:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                        removed_count += 1
                except Exception as e:
                    logging.warning(f"Impossibile eliminare il report singolo '{path}': {e}")
            if removed_count:
                logging.info(f"Report singoli eliminati dopo fascicolazione: {removed_count}")

        if self._temp_output_dir:
            try:
                shutil.rmtree(self._temp_output_dir, ignore_errors=True)
            except Exception as e:
                logging.warning(f"Impossibile rimuovere la cartella temporanea report: {e}")

        self.finished.emit(success_count, failed_reports)

    def _get_merged_output_path(self):
        # Se è stato specificato un percorso, usalo (a meno che sia il default Report_Unico)
        if self.merged_output_path:
            try:
                if os.path.basename(self.merged_output_path).lower() == "report_unico.pdf":
                    base_path = None
                else:
                    base_path = self.merged_output_path
            except Exception:
                base_path = self.merged_output_path
        else:
            base_path = None

        if base_path:
            if not base_path.lower().endswith(".pdf"):
                base_path += ".pdf"
            if not os.path.exists(base_path):
                return base_path
            root, ext = os.path.splitext(base_path)
            counter = 1
            new_path = f"{root}_{counter}{ext}"
            while os.path.exists(new_path):
                counter += 1
                new_path = f"{root}_{counter}{ext}"
            return new_path
        
        # Altrimenti genera il nome nel formato: ANNO-MESE_Fascicolo verifiche_NOME DESTINAZIONE
        try:
            # Estrai la data e il nome della destinazione dalla prima verifica
            first_verif = self.verifications[0] if self.verifications else {}
            verification_date = first_verif.get('verification_date', '')
            destination_name = first_verif.get('destination_name', 'Fascicolo')
            
            # Formatta la data come ANNO-MESE (es: 2026-02)
            if verification_date and len(verification_date) >= 7:
                year_month = verification_date[:7]  # YYYY-MM
            else:
                from datetime import datetime
                year_month = datetime.now().strftime('%Y-%m')
            
            # Sanifica il nome della destinazione
            safe_destination = destination_name.replace('/', '_').replace('\\', '_').replace('"', '').strip()
            
            # Crea il nome del file
            filename = f"{year_month}_Fascicolo verifiche_{safe_destination}.pdf"
            base_path = os.path.join(self.output_folder, filename)
            
            if not os.path.exists(base_path):
                return base_path
            
            # Se esiste già, aggiungi un numero
            root, ext = os.path.splitext(base_path)
            counter = 1
            new_path = f"{root}_{counter}{ext}"
            while os.path.exists(new_path):
                counter += 1
                new_path = f"{root}_{counter}{ext}"
            return new_path
        except Exception as e:
            logging.warning(f"Errore nella generazione del nome fascicolo, uso nome di default: {e}")
            base_path = os.path.join(self.output_folder, "Report_Unico.pdf")
            if not os.path.exists(base_path):
                return base_path
            root, ext = os.path.splitext(base_path)
            counter = 1
            new_path = f"{root}_{counter}{ext}"
            while os.path.exists(new_path):
                counter += 1
                new_path = f"{root}_{counter}{ext}"
            return new_path

    def _merge_pdfs(self, pdf_paths, output_path):
        merger_cls = None
        try:
            from PyPDF2 import PdfMerger as _PdfMerger
            from PyPDF2 import PdfReader as _PdfReader
            merger_cls = _PdfMerger
            reader_cls = _PdfReader
        except Exception:
            from pypdf import PdfMerger as _PdfMerger
            from pypdf import PdfReader as _PdfReader
            merger_cls = _PdfMerger
            reader_cls = _PdfReader

        merger = merger_cls()
        try:
            current_page = 0
            for path in pdf_paths:
                if os.path.exists(path):
                    reader = reader_cls(path)
                    num_pages = len(reader.pages)
                    merger.append(reader)
                    title = os.path.splitext(os.path.basename(path))[0]
                    self._add_bookmark(merger, title, current_page)
                    current_page += num_pages
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                merger.write(f)
        finally:
            try:
                merger.close()
            except Exception:
                pass

    def _add_bookmark(self, merger, title: str, page_index: int):
        try:
            if hasattr(merger, "add_outline_item"):
                merger.add_outline_item(title, page_index)
            elif hasattr(merger, "addBookmark"):
                merger.addBookmark(title, page_index)
        except Exception as e:
            logging.warning(f"Impossibile creare segnalibro '{title}': {e}")

    def _natural_sort_key_for_path(self, file_path: str):
        """Restituisce una chiave di ordinamento alfanumerico naturale basata sul nome file."""
        base_name = os.path.basename(str(file_path or ""))
        parts = re.split(r'(\d+)', base_name.lower())
        key = []
        for part in parts:
            if part.isdigit():
                key.append(int(part))
            else:
                key.append(part)
        return key

    def _unique_output_path(self, folder: str, filename: str) -> str:
        os.makedirs(folder, exist_ok=True)
        base_path = os.path.join(folder, filename)
        if not os.path.exists(base_path):
            return base_path
        root, ext = os.path.splitext(base_path)
        counter = 1
        new_path = f"{root}_{counter}{ext}"
        while os.path.exists(new_path):
            counter += 1
            new_path = f"{root}_{counter}{ext}"
        return new_path

    def _create_cover_pdf(self, info: dict, output_path: str, include_cover: bool = True, include_table: bool = True) -> None:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import cm
        from reportlab.lib.colors import HexColor
        from reportlab.lib.utils import ImageReader, simpleSplit
        from reportlab.pdfgen import canvas
        from reportlab.platypus import Table, TableStyle
        from reportlab.lib import colors
        from PySide6.QtGui import QImage
        from report_generator import LOGO_MAX_W_CM, LOGO_MAX_H_CM, _compress_qimage_to_bytes

        def fmt_date(date_str: str) -> str:
            if not date_str:
                return ""
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                return dt.strftime("%d/%m/%Y")
            except Exception:
                return date_str

        def fmt_month_year(start: str, end: str) -> str:
            if not start:
                return ""
            try:
                mesi = [
                    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
                    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
                ]
                s_dt = datetime.strptime(start, "%Y-%m-%d")
                e_dt = datetime.strptime(end, "%Y-%m-%d") if end else s_dt
                s_label = f"{mesi[s_dt.month - 1]} {s_dt.year}"
                e_label = f"{mesi[e_dt.month - 1]} {e_dt.year}"
                if s_dt.year == e_dt.year and s_dt.month == e_dt.month:
                    return s_label
                return f"{s_label} - {e_label}"
            except Exception:
                return f"{start} - {end}" if end else start

        # === COLORI MODERNI ===
        COLOR_PRIMARY = HexColor("#1e3a5f")      # Blu scuro professionale
        COLOR_ACCENT = HexColor("#2563eb")       # Blu accent
        COLOR_SUCCESS = HexColor("#059669")      # Verde
        COLOR_TEXT = HexColor("#1e293b")         # Testo scuro
        COLOR_TEXT_LIGHT = HexColor("#64748b")   # Testo grigio
        
        width, height = A4
        c = canvas.Canvas(output_path, pagesize=A4)

        if not include_cover and not include_table:
            include_cover = True

        if include_cover:
            # Logo (più grande e largo)
            logo_path = info.get("logo_path")
            logo_drawn = False
            if logo_path and os.path.exists(logo_path):
                try:
                    logo_image = QImage(logo_path)
                    # Logo più largo
                    cover_logo_w_cm = 18  # Larghezza maggiore
                    cover_logo_h_cm = 4   # Altezza proporzionata
                    logo_bytes = _compress_qimage_to_bytes(
                        logo_image,
                        cover_logo_w_cm,
                        cover_logo_h_cm,
                        prefer_jpeg=True,
                    )
                    if logo_bytes:
                        reader = ImageReader(io.BytesIO(logo_bytes))
                    else:
                        reader = ImageReader(logo_path)
                    iw, ih = reader.getSize()
                    max_w = cover_logo_w_cm * cm
                    max_h = cover_logo_h_cm * cm
                    scale = min(max_w / iw, max_h / ih)
                    draw_w = iw * scale
                    draw_h = ih * scale
                    x = (width - draw_w) / 2
                    y = height - draw_h - 1*cm  # Posizionato in alto
                    c.drawImage(reader, x, y, width=draw_w, height=draw_h, mask='auto')
                    logo_drawn = True
                except Exception as e:
                    logging.warning(f"Impossibile caricare il logo nel frontespizio: {e}")

            # Titolo
            title_y1 = height - 6.5*cm if logo_drawn else height - 3*cm
            title_y2 = title_y1 - 0.8*cm
            
            c.setFillColor(COLOR_PRIMARY)
            c.setFont("Helvetica-Bold", 20)
            c.drawCentredString(width / 2, title_y1, "FASCICOLO VERIFICHE APPARECCHI")
            c.setFont("Helvetica-Bold", 20)
            c.setFillColor(COLOR_PRIMARY)
            c.drawCentredString(width / 2, title_y2, "ELETTROMEDICALI")

            # Linea decorativa sotto titolo
            c.setStrokeColor(COLOR_ACCENT)
            c.setLineWidth(2)
            c.line(width/2 - 4*cm, title_y2 - 0.4*cm, width/2 + 4*cm, title_y2 - 0.4*cm)

            # Blocco sinistro
            left_x = 2*cm
            relazione_y = title_y2 - 2*cm
            
            c.setFillColor(COLOR_TEXT_LIGHT)
            c.setFont("Helvetica", 10)
            c.drawString(left_x, relazione_y, "RELAZIONE DI INTERVENTO")
            
            c.setFillColor(COLOR_TEXT)
            c.setFont("Helvetica-Bold", 12)
            c.drawString(left_x, relazione_y - 0.7*cm, fmt_month_year(info.get("start_date"), info.get("end_date")))

            # Cliente
            committente_y = relazione_y - 2.2*cm
            max_text_width = (width / 2) - 2.5*cm

            c.setFillColor(COLOR_TEXT_LIGHT)
            c.setFont("Helvetica", 10)
            c.drawString(left_x, committente_y, "CLIENTE")

            customer_name = info.get("customer_name", "")
            c.setFillColor(COLOR_PRIMARY)
            c.setFont("Helvetica-Bold", 16)
            customer_lines = simpleSplit(customer_name, "Helvetica-Bold", 16, max_text_width)
            customer_y = committente_y - 0.8*cm
            for line in customer_lines[:3]:
                c.drawString(left_x, customer_y, line)
                customer_y -= 0.7*cm

            # Destinazione
            dest_label_y = customer_y - 0.5*cm
            c.setFillColor(COLOR_TEXT_LIGHT)
            c.setFont("Helvetica", 10)
            c.drawString(left_x, dest_label_y, "DESTINAZIONE")

            destination_name = info.get("destination_name", "")
            destination_address = info.get("destination_address", "")
            c.setFillColor(COLOR_TEXT)
            c.setFont("Helvetica", 11)
            dest_lines = simpleSplit(f" {destination_name} \n {destination_address}", "Helvetica", 11, max_text_width)
            dest_y = dest_label_y - 0.7*cm
            for line in dest_lines[:3]:
                c.drawString(left_x, dest_y, line)
                dest_y -= 0.5*cm

            # Data compilazione in basso a sinistra
            c.setFillColor(COLOR_TEXT_LIGHT)
            c.setFont("Helvetica", 8)
            c.drawString(2*cm, 2.5*cm, "Data compilazione")
            c.setFillColor(COLOR_TEXT)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(2*cm, 1.9*cm, datetime.now().strftime("%d/%m/%Y"))
            
            # Nome creatore in basso a destra
            created_by = info.get("created_by", "")
            if created_by:
                c.setFillColor(COLOR_TEXT_LIGHT)
                c.setFont("Helvetica", 8)
                c.drawRightString(width - 2*cm, 2.5*cm, "Compilato da")
                c.setFillColor(COLOR_TEXT)
                c.setFont("Helvetica-Bold", 10)
                c.drawRightString(width - 2*cm, 1.9*cm, created_by)

            # === BOX RIASSUNTO MODERNO ===
            box_w = 7.5*cm
            box_h = 12*cm
            box_x = width - box_w - 1.5*cm
            box_y = height - 20*cm
            
            # Sfondo box con gradiente simulato (due rettangoli)
            c.setFillColor(COLOR_PRIMARY)
            c.roundRect(box_x, box_y, box_w, box_h, 0.4*cm, fill=1, stroke=0)
            
            # Linea accent in alto nel box
            c.setStrokeColor(COLOR_ACCENT)
            c.setLineWidth(3)
            c.line(box_x + 0.5*cm, box_y + box_h - 0.3*cm, box_x + box_w - 0.5*cm, box_y + box_h - 0.3*cm)

            # Contenuto box
            c.setFillColor(HexColor("#ffffff"))
            c.setFont("Helvetica-Bold", 11)
            c.drawString(box_x + 0.8*cm, box_y + box_h - 1.2*cm, "RIEPILOGO VERIFICHE")
            
            # Numero grande centrale (dispositivi unici)
            devices_count = info.get('devices_count', info.get('total_count', 0))
            c.setFont("Helvetica-Bold", 48)
            c.drawCentredString(box_x + box_w/2, box_y + box_h - 3.5*cm, str(devices_count))
            
            c.setFont("Helvetica", 10)
            c.drawCentredString(box_x + box_w/2, box_y + box_h - 4.2*cm, "apparecchi controllati")
            
            # Dettagli
            c.setFont("Helvetica", 9)
            detail_y = box_y + box_h - 5.5*cm
            
            # Verifiche elettriche
            c.setFillColor(HexColor("#93c5fd"))  # Blu chiaro
            c.circle(box_x + 1.2*cm, detail_y + 0.15*cm, 0.2*cm, fill=1, stroke=0)
            c.setFillColor(HexColor("#ffffff"))
            c.drawString(box_x + 1.8*cm, detail_y, f"{info.get('electrical_count', 0)} verifiche elettriche")
            
            # Verifiche funzionali
            detail_y -= 0.8*cm
            c.setFillColor(HexColor("#86efac"))  # Verde chiaro
            c.circle(box_x + 1.2*cm, detail_y + 0.15*cm, 0.2*cm, fill=1, stroke=0)
            c.setFillColor(HexColor("#ffffff"))
            c.drawString(box_x + 1.8*cm, detail_y, f"{info.get('functional_count', 0)} verifiche funzionali")
            
            # Linea separatrice
            detail_y -= 0.6*cm
            c.setStrokeColor(HexColor("#ffffff"))
            c.setLineWidth(0.5)
            c.line(box_x + 0.8*cm, detail_y, box_x + box_w - 0.8*cm, detail_y)
            
            # Verifiche conformi
            detail_y -= 0.7*cm
            c.setFillColor(COLOR_SUCCESS)  # Verde
            c.circle(box_x + 1.2*cm, detail_y + 0.15*cm, 0.2*cm, fill=1, stroke=0)
            c.setFillColor(HexColor("#ffffff"))
            c.drawString(box_x + 1.8*cm, detail_y, f"{info.get('conformi_count', 0)} CONFORMI")

            # Verifiche conformi con annotazione
            detail_y -= 0.8*cm
            c.setFillColor(HexColor("#f59e0b"))  # Arancione
            c.circle(box_x + 1.2*cm, detail_y + 0.15*cm, 0.2*cm, fill=1, stroke=0)
            c.setFillColor(HexColor("#ffffff"))
            c.drawString(
                box_x + 1.8*cm,
                detail_y,
                f"{info.get('conformi_con_annotazione_count', 0)} CONFORMI CON ANNOTAZIONE",
            )
            
            # Verifiche non conformi
            detail_y -= 0.8*cm
            c.setFillColor(HexColor("#dc2626"))  # Rosso
            c.circle(box_x + 1.2*cm, detail_y + 0.15*cm, 0.2*cm, fill=1, stroke=0)
            c.setFillColor(HexColor("#ffffff"))
            c.drawString(box_x + 1.8*cm, detail_y, f"{info.get('non_conformi_count', 0)} NON CONFORMI")

            if include_table:
                c.showPage()
        
        # === NUOVA PAGINA: TABELLA ESITI ===
        if include_table:
            self._add_results_table_pages(c, info)
        
        c.save()
    
    def _add_results_table_pages(self, c, info: dict) -> None:
        """Aggiunge le pagine con la tabella degli esiti delle verifiche."""
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import cm, mm
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import Table, TableStyle, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        
        # Usa formato landscape per la tabella
        width, height = landscape(A4)
        c.setPageSize(landscape(A4))
        
        # === COLORI ===
        COLOR_HEADER_BG = HexColor("#1e3a5f")    # Header tabella blu scuro
        COLOR_HEADER_TEXT = HexColor("#ffffff")  # Testo header bianco
        COLOR_ROW_EVEN = HexColor("#f0f4f8")     # Righe pari - grigio chiaro
        COLOR_ROW_ODD = HexColor("#ffffff")      # Righe dispari - bianco
        COLOR_PASS = HexColor("#059669")         # Verde per CONFORME
        COLOR_PASS_BG = HexColor("#09ad0b")      # Sfondo verde chiaro
        COLOR_ANNOTATION = HexColor("#f59e0b")   # Arancione/Giallo per CONFORME CON ANNOTAZIONE
        COLOR_ANNOTATION_BG = HexColor("#f2d305") # Sfondo giallo chiaro
        COLOR_FAIL = HexColor("#dc2626")         # Rosso per NON CONFORME
        COLOR_FAIL_BG = HexColor("#fee2e2")      # Sfondo rosso chiaro
        COLOR_BORDER = HexColor("#cbd5e1")       # Bordo grigio
        COLOR_TEXT = HexColor("#1e293b")         # Testo principale
        
        # Stile per il testo nelle celle - leggibile ma compatto
        styles = getSampleStyleSheet()
        cell_style = ParagraphStyle(
            'CellStyle',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
            wordWrap='CJK',
            textColor=COLOR_TEXT
        )
        cell_style_center = ParagraphStyle(
            'CellStyleCenter',
            parent=cell_style,
            alignment=TA_CENTER
        )
        header_style = ParagraphStyle(
            'HeaderStyle',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
            fontName='Helvetica-Bold',
            textColor=COLOR_HEADER_TEXT,
            alignment=TA_CENTER
        )
        
        # Intestazioni tabella
        headers = ["INV. AMS", "INV. CLIENTE", "DENOMINAZIONE", "MARCA", "MODELLO", 
                   "MATRICOLA", "REPARTO", "ESITO", "NOTE"]
        
        # Funzione per convertire lo status
        def convert_status(status):
            if not status:
                return ""
            status_upper = status.upper()
            if status_upper == "PASSATO":
                return "CONFORME"
            elif status_upper == "FALLITO":
                return "NON CONFORME"
            elif status_upper == "CONFORME CON ANNOTAZIONE":
                return "CONFORME CON ANNOTAZIONE"
            return status
        
        # Estrai l'anno dalle verifiche
        verification_year = ""
        if self.verifications:
            first_date = self.verifications[0].get('verification_date', '')
            if first_date and len(first_date) >= 4:
                verification_year = first_date[:4]
        
        # Prepara i dati dalle verifiche - consolidando per dispositivo
        # Raggruppa per device_id per evitare duplicati (elettrica + funzionale)
        devices_map = {}
        for verif in self.verifications:
            device_id = verif.get('device_id')
            if device_id not in devices_map:
                devices_map[device_id] = {
                    'data': verif,
                    'esito_elettrico': '',
                    'esito_funzionale': '',
                    'note_parts': []
                }
            
            verification_type = verif.get('verification_type', 'ELETTRICA')
            raw_status = verif.get('overall_status', '')
            status = convert_status(raw_status)
            
            if verification_type == "FUNZIONALE":
                devices_map[device_id]['esito_funzionale'] = status if status else ""
            else:
                devices_map[device_id]['esito_elettrico'] = status if status else ""
            
            # Accumula le note (potrebbe venire da entrambe le verifiche)
            # Per verifiche FUNZIONALI il campo è 'notes' (diretto)
            # Per ELETTRICHE le note sono in visual_inspection_json (JSON da parsare)
            note = ""
            if verification_type == "FUNZIONALE":
                note = str(verif.get('notes') or '').strip()
                if note:
                    devices_map[device_id]['note_parts'].append(f"VFUN: {note}")
            else:
                # Per verifiche ELETTRICHE, le note sono in visual_inspection_json
                try:
                    import json
                    visual_json_str = verif.get('visual_inspection_json', '{}')
                    if visual_json_str:
                        visual_data = json.loads(visual_json_str)
                        note = str(visual_data.get('notes') or '').strip()
                        if note:
                            devices_map[device_id]['note_parts'].append(f"VSEL: {note}")
                except (json.JSONDecodeError, TypeError):
                    pass
        
        # Costruisci la tabella consolidata
        table_data = []
        esiti_unificati = []  # Lista parallela con gli esiti per colorare le celle
        for device_id, device_info in devices_map.items():
            verif = device_info['data']
            esito_elettrico = device_info['esito_elettrico']
            esito_funzionale = device_info['esito_funzionale']
            
            # ===== NUOVO ESITO UNIFICATO =====
            # Priorità assoluta: NON CONFORME > CONFORME CON ANNOTAZIONE > CONFORME
            
            # Paso 1: Controlla se c'è NON CONFORME (ha priorità massima)
            has_non_conforme = (
                ("NON CONFORME" in esito_elettrico if esito_elettrico else False) or
                ("NON CONFORME" in esito_funzionale if esito_funzionale else False)
            )
            
            if has_non_conforme:
                esito_unificato = "NON CONFORME"
            else:
                # Passo 2: Se ci sono note (anche senza non conforme), diventa CONFORME CON ANNOTAZIONE
                if device_info['note_parts']:
                    esito_unificato = "CONFORME CON ANNOTAZIONE"
                else:
                    # Passo 3: Altrimenti determina l'esito basato sugli stati presenti
                    if esito_elettrico and esito_funzionale:
                        # Entrambi presenti
                        if "CONFORME CON ANNOTAZIONE" in [esito_elettrico, esito_funzionale]:
                            esito_unificato = "CONFORME CON ANNOTAZIONE"
                        else:
                            esito_unificato = "CONFORME"
                    elif esito_elettrico:
                        esito_unificato = esito_elettrico
                    elif esito_funzionale:
                        esito_unificato = esito_funzionale
                    else:
                        esito_unificato = ""
            
            # ===== CAMPO NOTE =====
            # Contiene i testi da entrambe le verifiche (se presenti)
            note = " | ".join(device_info['note_parts']) if device_info['note_parts'] else ""
            
            row = [
                Paragraph(str(verif.get('ams_inventory') or ''), cell_style_center),
                Paragraph(str(verif.get('customer_inventory') or ''), cell_style_center),
                Paragraph(str(verif.get('description') or ''), cell_style),
                Paragraph(str(verif.get('manufacturer') or ''), cell_style),
                Paragraph(str(verif.get('model') or ''), cell_style),
                Paragraph(str(verif.get('serial_number') or ''), cell_style_center),
                Paragraph(str(verif.get('department') or ''), cell_style),
                Paragraph(esito_unificato, cell_style_center),
                Paragraph(note, cell_style),
            ]
            table_data.append(row)
            esiti_unificati.append(esito_unificato)  # Salva l'esito per la colorazione
        
        if not table_data:
            return
        
        # Paginazione dinamica: evita che la tabella venga tagliata in fondo pagina
        rows_per_page = 24
        header_row = [Paragraph(h, header_style) for h in headers]
        
        # Larghezze colonne - TABELLA PIU' LARGA (quasi tutta la pagina)
        # Totale circa 28cm per landscape A4 (29.7cm - margini minimi)
        # DATA rimossa, spazio aggiunto a NOTE
        col_widths = [1.8*cm, 2.2*cm, 3.0*cm, 2.8*cm, 2.8*cm, 2.5*cm, 2.8*cm, 2.8*cm, 7.7*cm]
        
        table_start_y = height - 1.6*cm
        min_bottom_margin = 1.0*cm
        available_table_height = table_start_y - min_bottom_margin

        # Precalcola i blocchi di righe che entrano realmente in pagina
        page_chunks: list[tuple[int, int]] = []
        cursor = 0
        total_rows = len(table_data)
        while cursor < total_rows:
            take = min(rows_per_page, total_rows - cursor)
            if take <= 0:
                break

            while take > 1:
                candidate_data = [header_row] + table_data[cursor:cursor + take]
                candidate_table = Table(candidate_data, colWidths=col_widths, repeatRows=1)
                _, candidate_height = candidate_table.wrap(width - 1.6*cm, height)
                if candidate_height <= available_table_height:
                    break
                take -= 1

            # Fallback: garantisce avanzamento anche con righe molto alte
            if take <= 0:
                take = 1

            page_chunks.append((cursor, cursor + take))
            cursor += take

        total_pages = len(page_chunks)

        # Disegna le pagine
        for page_num, (page_start, page_end) in enumerate(page_chunks, start=1):
            page_data = [header_row] + table_data[page_start:page_end]
            
            # === HEADER PAGINA - SFONDO BIANCO ===
            # A sinistra: TABELLA VERIFICHE + Anno
            c.setFillColor(COLOR_TEXT)
            c.setFont("Helvetica-Bold", 12)
            c.drawString(0.8*cm, height - 1.0*cm, f"TABELLA VERIFICHE {verification_year}")
            
            # Al centro: Destinazione
            destination_name = info.get('destination_name', '')[:60]
            c.setFont("Helvetica-Bold", 11)
            text_width = c.stringWidth(destination_name, "Helvetica-Bold", 11)
            c.drawString((width - text_width) / 2, height - 1.0*cm, destination_name)
            
            # A destra: Pagine e totale verifiche
            c.setFont("Helvetica", 10)
            c.drawRightString(width - 0.8*cm, height - 0.8*cm, f"Pagina {page_num} di {total_pages}")
            c.setFont("Helvetica", 9)
            c.drawRightString(width - 0.8*cm, height - 1.2*cm, f"Totale: {len(table_data)} verifiche")
            
            # Linea sotto header
            c.setStrokeColor(COLOR_BORDER)
            c.setLineWidth(1)
            c.line(0.8*cm, height - 1.4*cm, width - 0.8*cm, height - 1.4*cm)
            
            # Crea la tabella
            table = Table(page_data, colWidths=col_widths, repeatRows=1)
            
            # Stile base della tabella
            style_commands = [
                # Header styling
                ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
                ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_HEADER_TEXT),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, 0), 4),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
                
                # Body styling
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 1), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                
                # Bordi
                ('GRID', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
            ]
            
            # Zebra striping per le righe
            for row_idx in range(1, len(page_data)):
                if row_idx % 2 == 0:
                    style_commands.append(('BACKGROUND', (0, row_idx), (-1, row_idx), COLOR_ROW_EVEN))
            
            # Colorazione condizionale per gli esiti
            for row_idx, esito in enumerate(esiti_unificati[page_start:page_end], start=1):
                # Colonna esito unificato (indice 7)
                if esito == "NON CONFORME":
                    style_commands.append(('BACKGROUND', (7, row_idx), (7, row_idx), COLOR_FAIL_BG))
                    style_commands.append(('TEXTCOLOR', (7, row_idx), (7, row_idx), COLOR_FAIL))
                elif esito == "CONFORME CON ANNOTAZIONE":
                    style_commands.append(('BACKGROUND', (7, row_idx), (7, row_idx), COLOR_ANNOTATION_BG))
                    style_commands.append(('TEXTCOLOR', (7, row_idx), (7, row_idx), COLOR_ANNOTATION))
                else:  # CONFORME
                    style_commands.append(('BACKGROUND', (7, row_idx), (7, row_idx), COLOR_PASS_BG))
                    style_commands.append(('TEXTCOLOR', (7, row_idx), (7, row_idx), COLOR_PASS))
            
            table.setStyle(TableStyle(style_commands))
            
            # Disegna la tabella - posizionata subito sotto l'header
            table_width, table_height = table.wrap(width - 1.6*cm, height)
            # Disegna la tabella partendo dalla posizione corretta
            table.drawOn(c, 0.8*cm, table_start_y - table_height)
            
            if page_num < total_pages:
                c.showPage()
                c.setPageSize(landscape(A4))
