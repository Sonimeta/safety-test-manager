import json
import os
from datetime import datetime
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QComboBox, QTextEdit, QCalendarWidget, QDialogButtonBox, QFormLayout, QSpinBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QMessageBox, QLineEdit, QStyle, QHeaderView, QAbstractItemView, QListWidget, QListWidgetItem, QApplication,
    QFileDialog, QCheckBox, QWidget, QDateEdit, QTabWidget)
from PySide6.QtCore import Qt, QDate, QSettings, QLocale
from PySide6.QtGui import QTextCharFormat, QBrush, QColor
from app import services

class SingleCalendarRangeDialog(QDialog):
    """
    Una dialog che permette di selezionare un intervallo di date
    su un singolo QCalendarWidget. (Versione corretta e ottimizzata)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SELEZIONA INTERVALLO DI DATE")
        self.setMinimumWidth(400)

        self.start_date = None
        self.end_date = None
        self.selecting_start = True
        self.previous_range = None

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        self.start_label = QLabel("NESSUNA")
        self.end_label = QLabel("NESSUNA")
        form_layout.addRow("<b>Data Inizio:</b>", self.start_label)
        form_layout.addRow("<b>Data Fine:</b>", self.end_label)
        layout.addLayout(form_layout)
        
        self.calendar = QCalendarWidget(self)
        self.calendar.setGridVisible(True)
        self.calendar.setNavigationBarVisible(True)
        self.calendar.setLocale(QLocale(QLocale.Italian, QLocale.Italy))
        self.calendar.setFirstDayOfWeek(Qt.Monday)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        layout.addWidget(self.calendar)

        self.info_label = QLabel("FAI CLIC SU UNA DATA PER SELEZIONARE L'INIZIO DELL'INTERVALLO.")
        self.info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        layout.addWidget(self.buttons)
        
        self.calendar.clicked.connect(self._on_date_clicked)
        
        self.range_format = QTextCharFormat()
        self.range_format.setBackground(QBrush(QColor("#dbeafe")))
    
    def get_date_range(self):
        """
        Restituisce le date di inizio e fine selezionate come oggetti QDate.
        """
        return self.start_date, self.end_date

    def _on_date_clicked(self, date):
        if self.start_date and self.end_date:
            self.previous_range = (self.start_date, self.end_date)
        
        if self.selecting_start:
            self.start_date = date
            self.end_date = None
            self.start_label.setText(f"<b>{date.toString('dd/MM/yyyy')}</b>".upper())
            self.end_label.setText("NESSUNA")
            self.info_label.setText("ORA FAI CLIC SULLA DATA DI FINE DELL'INTERVALLO.")
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            self.selecting_start = False
        else:
            self.end_date = date
            if self.start_date > self.end_date:
                self.start_date, self.end_date = self.end_date, self.start_date
            
            self.start_label.setText(f"<b>{self.start_date.toString('dd/MM/yyyy')}</b>".upper())
            self.end_label.setText(f"<b>{self.end_date.toString('dd/MM/yyyy')}</b>".upper())
            self.info_label.setText("INTERVALLO SELEZIONATO. CLICCA DI NUOVO PER RICOMINCIARE.")
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)
            self.selecting_start = True
        
        self._update_highlight()

    def _update_highlight(self):
        default_format = QTextCharFormat()
        if self.previous_range:
            d = self.previous_range[0]
            while d <= self.previous_range[1]:
                self.calendar.setDateTextFormat(d, default_format)
                d = d.addDays(1)
        
        if self.start_date and self.end_date:
            d = self.start_date
            while d <= self.end_date:
                self.calendar.setDateTextFormat(d, self.range_format)
                d = d.addDays(1)
        elif self.start_date:
             self.calendar.setDateTextFormat(self.start_date, self.range_format)

    def get_date_range(self):
        if self.start_date and self.end_date:
            return (self.start_date.toString("yyyy-MM-dd"), 
                    self.end_date.toString("yyyy-MM-dd"))
        return None, None


class AdvancedReportDialog(QDialog):
    """Dialog per la generazione avanzata dei report."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GENERA REPORT AVANZATO")
        self.setMinimumWidth(520)

        self.start_date = None
        self.end_date = None

        layout = QVBoxLayout(self)

        # --- Ambito ---
        scope_group = QGroupBox("Ambito")
        scope_layout = QFormLayout(scope_group)
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("Tutto il database", "all")
        self.scope_combo.addItem("Cliente", "customer")
        self.scope_combo.addItem("Destinazione", "destination")
        self.scope_combo.currentIndexChanged.connect(self._update_scope_controls)

        self.customer_combo = QComboBox()
        self.customer_combo.currentIndexChanged.connect(self._on_customer_changed)
        self.destination_combo = QComboBox()

        scope_layout.addRow("Selezione:", self.scope_combo)
        scope_layout.addRow("Cliente:", self.customer_combo)
        scope_layout.addRow("Destinazione:", self.destination_combo)
        layout.addWidget(scope_group)

        # --- Intervallo date ---
        date_group = QGroupBox("Intervallo Date")
        date_layout = QHBoxLayout(date_group)
        self.date_label = QLabel("NESSUN INTERVALLO SELEZIONATO")
        select_date_btn = QPushButton("Seleziona intervallo")
        select_date_btn.clicked.connect(self._select_date_range)
        date_layout.addWidget(self.date_label, 1)
        date_layout.addWidget(select_date_btn)
        layout.addWidget(date_group)

        # --- Opzioni report ---
        options_group = QGroupBox("Opzioni Report")
        options_layout = QFormLayout(options_group)
        self.electrical_check = QCheckBox("Verifiche Elettriche")
        self.functional_check = QCheckBox("Verifiche Funzionali")
        self.electrical_check.setChecked(True)
        self.functional_check.setChecked(True)

        self.latest_only_check = QCheckBox("Solo ultima verifica per dispositivo")
        self.latest_only_check.setChecked(True)

        self.naming_format_combo = QComboBox()
        self.naming_format_combo.addItem("Inventario AMS", "ams_inventory")
        self.naming_format_combo.addItem("Numero di Serie", "serial_number")
        self.naming_format_combo.addItem("Inventario Cliente", "customer_inventory")

        self.merge_pdf_check = QCheckBox("Fascicola in un unico PDF")
        self.merge_pdf_check.setChecked(False)
        self.merge_pdf_check.toggled.connect(self._update_merge_controls)
        self.merged_intro_combo = QComboBox()
        self.merged_intro_combo.addItem("Frontespizio + Tabella", "cover_and_table")
        self.merged_intro_combo.addItem("Solo Tabella", "table_only")
        self.merged_intro_combo.addItem("Solo Frontespizio", "cover_only")
        self.export_cover_single_check = QCheckBox("Esporta Frontespizio come file singolo")
        self.export_table_single_check = QCheckBox("Esporta Tabella come file singolo")
        self.keep_individual_check = QCheckBox("Genera anche i report singoli")
        self.keep_individual_check.setChecked(True)
        self.keep_individual_check.setEnabled(False)
        self.merge_pdf_path = QLineEdit()
        self.merge_pdf_browse_btn = QPushButton("Sfoglia...")
        self.merge_pdf_browse_btn.clicked.connect(self._browse_merge_pdf)

        options_layout.addRow(self.electrical_check, self.functional_check)
        options_layout.addRow(self.latest_only_check)
        options_layout.addRow("Formato nome file:", self.naming_format_combo)
        options_layout.addRow(self.merge_pdf_check)
        options_layout.addRow("Contenuto fascicolo:", self.merged_intro_combo)
        options_layout.addRow(self.export_cover_single_check)
        options_layout.addRow(self.export_table_single_check)
        options_layout.addRow(self.keep_individual_check)
        # Il percorso del file merged viene generato automaticamente nel formato: ANNO-MESE_Fascicolo verifiche_NOME DESTINAZIONE
        layout.addWidget(options_group)

        # --- Output ---
        output_group = QGroupBox("Cartella di destinazione")
        output_layout = QHBoxLayout(output_group)
        self.output_path_edit = QLineEdit()
        browse_btn = QPushButton("Sfoglia...")
        browse_btn.clicked.connect(self._browse_output_folder)
        output_layout.addWidget(self.output_path_edit, 1)
        output_layout.addWidget(browse_btn)
        layout.addWidget(output_group)

        # --- Pulsanti ---
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_customers()
        self._update_scope_controls()
        self._update_merge_controls()

    def _merge_path_row(self):
        row = QHBoxLayout()
        row.addWidget(self.merge_pdf_path, 1)
        row.addWidget(self.merge_pdf_browse_btn)
        wrapper = QWidget()
        wrapper.setLayout(row)
        return wrapper

    def _load_customers(self):
        self.customer_combo.clear()
        self.customer_combo.addItem("Seleziona cliente...", None)
        customers = services.database.get_all_customers()
        for cust in customers:
            cust_data = dict(cust)
            self.customer_combo.addItem(cust_data.get("name", "N/D"), cust_data.get("id"))

    def _load_destinations(self, customer_id: int | None):
        self.destination_combo.clear()
        self.destination_combo.addItem("Seleziona destinazione...", None)
        if not customer_id:
            return
        destinations = services.database.get_destinations_for_customer(customer_id)
        for dest in destinations:
            dest_data = dict(dest)
            self.destination_combo.addItem(dest_data.get("name", "N/D"), dest_data.get("id"))

    def _on_customer_changed(self):
        scope = self.scope_combo.currentData()
        if scope == "destination":
            customer_id = self.customer_combo.currentData()
            self._load_destinations(customer_id)

    def _update_scope_controls(self):
        scope = self.scope_combo.currentData()
        if scope == "all":
            self.customer_combo.setEnabled(False)
            self.destination_combo.setEnabled(False)
        elif scope == "customer":
            self.customer_combo.setEnabled(True)
            self.destination_combo.setEnabled(False)
        else:
            self.customer_combo.setEnabled(True)
            self.destination_combo.setEnabled(True)
            self._on_customer_changed()

    def _select_date_range(self):
        dialog = SingleCalendarRangeDialog(self)
        if dialog.exec():
            start_date, end_date = dialog.get_date_range()
            self.start_date = start_date
            self.end_date = end_date
            if start_date and end_date:
                self.date_label.setText(f"{start_date}  →  {end_date}")
            else:
                self.date_label.setText("NESSUN INTERVALLO SELEZIONATO")

    def _browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "SELEZIONA CARTELLA DI DESTINAZIONE")
        if folder:
            self.output_path_edit.setText(folder)
            self._update_default_merge_path()

    def _browse_merge_pdf(self):
        # Usa il percorso selezionato oppure apri il file dialog nella cartella di output
        # Senza precompilare un nome di file - il worker genererà il nome automaticamente
        output_folder = self.output_path_edit.text().strip() or os.path.expanduser("~")
        file_path, _ = QFileDialog.getSaveFileName(self, "SALVA PDF UNICO", output_folder, "PDF Files (*.pdf)")
        if file_path:
            self.merge_pdf_path.setText(file_path)

    def _update_default_merge_path(self):
        # Non impostare un percorso di default - lasciare vuoto affinché il worker generi il nome automaticamente
        # nel formato: ANNO-MESE_Fascicolo verifiche_NOME DESTINAZIONE
        pass

    def _update_merge_controls(self):
        enabled = self.merge_pdf_check.isChecked()
        # Il percorso del file viene generato automaticamente - non serve modificarlo
        self.merged_intro_combo.setEnabled(enabled)
        self.keep_individual_check.setEnabled(enabled)
        if not enabled:
            self.keep_individual_check.setChecked(True)

    def get_options(self):
        return {
            "scope": self.scope_combo.currentData(),
            "customer_id": self.customer_combo.currentData(),
            "destination_id": self.destination_combo.currentData(),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "include_electrical": self.electrical_check.isChecked(),
            "include_functional": self.functional_check.isChecked(),
            "latest_only": self.latest_only_check.isChecked(),
            "naming_format": self.naming_format_combo.currentData(),
            "output_folder": self.output_path_edit.text().strip(),
            "merge_into_one": self.merge_pdf_check.isChecked(),
            "merged_output_path": self.merge_pdf_path.text().strip(),
            "merged_intro_mode": self.merged_intro_combo.currentData(),
            "export_cover_single": self.export_cover_single_check.isChecked(),
            "export_table_single": self.export_table_single_check.isChecked(),
            "keep_individual_reports": (
                self.keep_individual_check.isChecked() if self.merge_pdf_check.isChecked() else True
            ),
        }

    def accept(self):
        options = self.get_options()
        if not options["start_date"] or not options["end_date"]:
            QMessageBox.warning(self, "DATI MANCANTI", "Seleziona un intervallo di date.")
            return
        if not options["include_electrical"] and not options["include_functional"]:
            QMessageBox.warning(self, "DATI MANCANTI", "Seleziona almeno un tipo di verifica.")
            return
        if options["scope"] == "customer" and not options["customer_id"]:
            QMessageBox.warning(self, "DATI MANCANTI", "Seleziona un cliente.")
            return
        if options["scope"] == "destination" and not options["destination_id"]:
            QMessageBox.warning(self, "DATI MANCANTI", "Seleziona una destinazione.")
            return
        requires_output_folder = (
            options["keep_individual_reports"]
            or options["export_cover_single"]
            or options["export_table_single"]
        )
        if not options["output_folder"]:
            if requires_output_folder:
                QMessageBox.warning(self, "DATI MANCANTI", "Seleziona una cartella di destinazione.")
                return
        # Il percorso del file merged viene generato automaticamente dal worker nel formato:
        # ANNO-MESE_Fascicolo verifiche_NOME DESTINAZIONE
        # Non servono validazioni per merged_output_path
        super().accept()

class ImportReportDialog(QDialog):
    """Finestra che mostra un report dettagliato (es. righe ignorate)."""
    def __init__(self, title, report_details, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(self)
        label = QLabel("LE SEGUENTI RIGHE DEL FILE NON SONO STATE IMPORTATE:")
        layout.addWidget(label)
        
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setText("\n".join(report_details).upper())
        layout.addWidget(text_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

class DateSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SELEZIONA DATA")
        layout = QVBoxLayout(self)
        self.calendar = QCalendarWidget(self)
        self.calendar.setGridVisible(True)
        self.calendar.setSelectedDate(QDate.currentDate())
        layout.addWidget(self.calendar)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    def getSelectedDate(self):
        return self.calendar.selectedDate().toString("yyyy-MM-dd")
    
class MappingDialog(QDialog):
    def __init__(self, file_columns, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MAPPATURA COLONNE IMPORTAZIONE")
        self.setMinimumWidth(450)
        self.required_fields = { 'matricola': 'Matricola (S/N)', 'descrizione': 'Descrizione', 'costruttore': 'Costruttore', 'modello': 'Modello', 'reparto': 'Reparto (Opzionale)', 'inv_cliente': 'Inventario Cliente (Opzionale)', 'inv_ams': 'Inventario AMS (Opzionale)', 'verification_interval': 'Intervallo Verifica (Mesi, Opzionale)' }
        self.file_columns = ["<Nessuna>"] + file_columns
        self.combo_boxes = {}
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        info_label = QLabel("ASSOCIA LE COLONNE DEL TUO FILE CON I CAMPI DEL PROGRAMMA. \n I CAMPI OBBLIGATORI SONO MATRICOLA E DESCRIZIONE.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        for key, display_name in self.required_fields.items():
            label = QLabel(f"{display_name}:")
            combo = QComboBox()
            combo.addItems(self.file_columns)
            form_layout.addRow(label, combo)
            self.combo_boxes[key] = combo
        layout.addLayout(form_layout)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.try_auto_mapping()

    def try_auto_mapping(self):
        for key, combo in self.combo_boxes.items():
            for i, col_name in enumerate(self.file_columns):
                if key.lower().replace("_", "") in col_name.lower().replace(" ", "").replace("/", ""):
                    combo.setCurrentIndex(i); break

    def get_mapping(self):
        mapping = {}
        for key, combo in self.combo_boxes.items():
            selected_col = combo.currentText()
            if selected_col not in ("<Nessuna>", "<NESSUNA>"): mapping[key] = selected_col
        if 'matricola' not in mapping or 'descrizione' not in mapping:
            QMessageBox.warning(self, "CAMPI MANCANTI", "ASSICURATI DI AVER MAPPATO ALMENO I CAMPI MATRICOLA E DESCRIZIONE.")
            return None
        return mapping
    
class VisualInspectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ISPEZIONE VISIVA PRELIMINARE")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("VALUTARE TUTTI I PUNTI SEGUENTI PRIMA DI PROCEDERE CON LE MISURE ELETTRICHE."))
        
        self.checklist_items = [
            "Involucro e parti meccaniche integri, senza danni.",
            "Cavo di alimentazione e spina senza danneggiamenti.",
            "Cavi paziente, connettori e accessori integri.",
            "Marcature e targhette di sicurezza leggibili.",
            "Assenza di sporcizia o segni di versamento di liquidi.",
            "Fusibili (se accessibili) di tipo e valore corretti."
        ]
        
        self.controls = []
        form_layout = QFormLayout()

        for item_text in self.checklist_items:
            combo = QComboBox()
            combo.addItems(["Seleziona...", "OK", "KO", "N/A"])
            combo.currentIndexChanged.connect(self.check_all_selected)
            
            form_layout.addRow(QLabel(item_text), combo)
            self.controls.append((item_text, combo))
        
        layout.addLayout(form_layout)
            
        layout.addWidget(QLabel("\nNOTE AGGIUNTIVE:"))
        self.notes_edit = QTextEdit()
        layout.addWidget(self.notes_edit)
        
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("CONFERMA E PROCEDI")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        
        self.check_all_selected()

    def check_all_selected(self):
        is_all_selected = all(combo.currentIndex() > 0 for _, combo in self.controls)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(is_all_selected)

    def get_data(self):
        return {
            "notes": self.notes_edit.toPlainText().upper(),
            "checklist": [{"item": text, "result": combo.currentText()} for text, combo in self.controls]
        }

class VerificationViewerDialog(QDialog):
    def __init__(self, verification_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"DETTAGLI VERIFICA DEL {verification_data.get('verification_date')}")
        self.setMinimumSize(700, 400)
        data = verification_data or {}
        layout = QVBoxLayout(self)
        info_label = QLabel(f"<b>PROFILO:</b> {str(data.get('profile_name')).upper()}<br><b>ESITO GLOBALE:</b> {str(data.get('overall_status')).upper()}")
        layout.addWidget(info_label)
        visual_data = data.get('visual_inspection', {})
        if visual_data:
            visual_group = QGroupBox("ISPEZIONE VISIVA")
            visual_layout = QVBoxLayout(visual_group)
            visual_data = data.get('visual_inspection', {})
            for item in visual_data.get('checklist', []): visual_layout.addWidget(QLabel(f"- {item['item'].upper()} [{item['result'].upper()}]"))
            if visual_data.get('notes'): visual_layout.addWidget(QLabel(f"\n<b>NOTE:</b> {visual_data['notes'].upper()}"))
            layout.addWidget(visual_group)
        results_table = QTableWidget(); results_table.setColumnCount(4); results_table.setHorizontalHeaderLabels(["TEST / P.A.", "LIMITE", "VALORE", "ESITO"]); layout.addWidget(results_table)
        results = data.get('results', [])
        for res in results:
            row = results_table.rowCount(); results_table.insertRow(row)
            results_table.setItem(row, 0, QTableWidgetItem(str(res.get('name', '')).upper()))
            results_table.setItem(row, 1, QTableWidgetItem(str(res.get('limit', '')).upper()))
            results_table.setItem(row, 2, QTableWidgetItem(str(res.get('value', '')).upper()))
            is_passed = res.get('passed', False) 
            passed_item = QTableWidgetItem("CONFORME" if is_passed else "NON CONFORME")
            passed_item.setBackground(QColor('#D4EDDA') if is_passed else QColor('#F8D7DA'))
            results_table.setItem(row, 3, passed_item)
        results_table.resizeColumnsToContents()
        close_button = QPushButton("CHIUDI"); close_button.clicked.connect(self.accept); layout.addWidget(close_button)


class FunctionalVerificationViewerDialog(QDialog):
    """Viewer dettagliato per verifiche funzionali."""

    def __init__(self, verification_data, parent=None):
        super().__init__(parent)
        data = verification_data or {}
        self.setWindowTitle(f"DETTAGLI VERIFICA FUNZIONALE DEL {data.get('verification_date', 'N/D')}")
        self.setMinimumSize(840, 520)

        layout = QVBoxLayout(self)

        profile_name = data.get('profile_name') or data.get('profile_key') or "N/D"
        info_label = QLabel(
            f"<b>PROFILO:</b> {str(profile_name).upper()}<br>"
            f"<b>ESITO GLOBALE:</b> {str(data.get('overall_status', 'N/D')).upper()}<br>"
            f"<b>TECNICO:</b> {str(data.get('technician_name', 'N/D')).upper()}<br>"
            f"<b>CODICE:</b> {str(data.get('verification_code', 'N/D')).upper()}"
        )
        layout.addWidget(info_label)

        notes = str(data.get('notes') or '').strip()
        if notes:
            notes_group = QGroupBox("NOTE")
            notes_layout = QVBoxLayout(notes_group)
            notes_view = QTextEdit()
            notes_view.setReadOnly(True)
            notes_view.setPlainText(notes)
            notes_layout.addWidget(notes_view)
            layout.addWidget(notes_group)

        details_group = QGroupBox("RISULTATI")
        details_layout = QVBoxLayout(details_group)
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["SEZIONE", "VOCE", "CAMPO", "VALORE"])
        table.horizontalHeader().setStretchLastSection(True)

        def add_row(section: str, item: str, field: str, value):
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(section).upper()))
            table.setItem(row, 1, QTableWidgetItem(str(item).upper()))
            table.setItem(row, 2, QTableWidgetItem(str(field).upper()))
            table.setItem(row, 3, QTableWidgetItem(str(value if value is not None else '').upper()))

        structured = data.get('structured_results')
        if isinstance(structured, dict) and structured:
            for section_key, section_data in structured.items():
                if not isinstance(section_data, dict):
                    add_row(section_key, '-', 'valore', section_data)
                    continue

                section_title = section_data.get('title') or section_key

                for field_entry in section_data.get('fields', []) or []:
                    if isinstance(field_entry, dict):
                        add_row(
                            section_title,
                            '-',
                            field_entry.get('label') or field_entry.get('key') or 'campo',
                            field_entry.get('value', ''),
                        )

                for row_entry in section_data.get('rows', []) or []:
                    if not isinstance(row_entry, dict):
                        add_row(section_title, '-', 'valore', row_entry)
                        continue
                    row_label = row_entry.get('label') or row_entry.get('key') or '-'
                    for value_entry in row_entry.get('values', []) or []:
                        if isinstance(value_entry, dict):
                            add_row(
                                section_title,
                                row_label,
                                value_entry.get('label') or value_entry.get('key') or 'campo',
                                value_entry.get('value', ''),
                            )
        else:
            raw_results = data.get('results')
            if isinstance(raw_results, dict):
                for k, v in raw_results.items():
                    add_row('RISULTATI', '-', k, v)
            elif isinstance(raw_results, list):
                for idx, v in enumerate(raw_results, start=1):
                    add_row('RISULTATI', f'RIGA {idx}', 'valore', v)

        table.resizeColumnsToContents()
        details_layout.addWidget(table)
        layout.addWidget(details_group)

        close_button = QPushButton("CHIUDI")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

class InstrumentSelectionDialog(QDialog):
    def __init__(self, parent=None, instrument_type: str = None):
        super().__init__(parent)
        self.setWindowTitle("Seleziona Strumento")
        self.settings = QSettings("ELSON META", "SafetyTester")
        self.instrument_type = instrument_type
        self.instruments = services.get_all_instruments(instrument_type)
        layout = QFormLayout(self)
        self.combo = QComboBox()
        default_idx = -1
        if self.instruments:
            for i, inst_row in enumerate(self.instruments):
                instrument = dict(inst_row)
                self.combo.addItem(f"{str(instrument.get('instrument_name')).upper()} (S/N: {str(instrument.get('serial_number')).upper()})", instrument.get('id'))
                if instrument.get('is_default'): default_idx = i
            if default_idx != -1: self.combo.setCurrentIndex(default_idx)
        layout.addRow("STRUMENTO:", self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def getSelectedInstrumentData(self):
        if not self.instruments:
            return None
        selected_id = self.combo.currentData()
        instrument_row = next((inst for inst in self.instruments if inst['id'] == selected_id), None)
        if instrument_row:
            instrument = dict(instrument_row)
            settings = QSettings("ELSON META", "SafetyTester")
            global_com_port = settings.value("global_com_port", "COM1")
            return {
                "instrument": instrument.get('instrument_name'),
                "serial": instrument.get('serial_number'), 
                "version": instrument.get('fw_version'), 
                "cal_date": instrument.get('calibration_date'),
                "com_port": global_com_port
            }
        return None
    
    def getTechnicianName(self):
        user = services.auth_manager.get_current_user()
        return user["full_name"] if user else ""
    
class MonthYearSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SELEZIONA PERIODO")
        layout = QFormLayout(self)
        self.month_combo = QComboBox()
        mesi = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", 
                "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
        self.month_combo.addItems(mesi)
        self.month_combo.setCurrentIndex(datetime.now().month - 1)
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2020, 2099)
        self.year_spin.setValue(datetime.now().year)
        layout.addRow("MESE:", self.month_combo)
        layout.addRow("ANNO:", self.year_spin)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selected_period(self):
        month = self.month_combo.currentIndex() + 1
        year = self.year_spin.value()
        return month, year

class AppliedPartsOrderDialog(QDialog):
    def __init__(self, applied_parts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ORDINE COLLEGAMENTO PARTI APPLICATE")
        self.setMinimumSize(500, 300)
        layout = QVBoxLayout(self)
        info_label = QLabel(
            "<b>ATTENZIONE:</b> COLLEGARE LE SEGUENTI PARTI APPLICATE ALLO STRUMENTO NELL'ORDINE INDICATO PRIMA DI PROCEDERE."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["ORDINE", "NOME", "TIPO", "CODICE STRUMENTO"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(table)
        table.setRowCount(0)
        for i, part in enumerate(applied_parts):
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(i + 1).upper()))
            table.setItem(row, 1, QTableWidgetItem(part.name.upper()))
            table.setItem(row, 2, QTableWidgetItem(part.part_type.upper()))
            table.setItem(row, 3, QTableWidgetItem(part.code.upper()))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("PRONTO PER INIZIARE")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class DuplicateDevicesDialog(QDialog):
    """
    Mostra dispositivi potenzialmente duplicati e permette di marcarli come eliminati.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DISPOSITIVI POTENZIALMENTE DUPLICATI")
        self.setMinimumSize(1100, 500)

        layout = QVBoxLayout(self)

        info = QLabel("I dispositivi sono raggruppati per potenziali duplicati.\n"
                      "Verifica con attenzione prima di eliminare un record.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(0, 10, self)
        self.table.setHorizontalHeaderLabels([
            "ID", "CLIENTE", "DESTINAZIONE", "DESCRIZIONE",
            "S/N", "INV. CLIENTE", "INV. AMS",
            "COSTRUTTORE", "MODELLO", "DUPLICATO PER"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Aggiorna elenco")
        self.refresh_btn.clicked.connect(self.load_data)
        btn_layout.addWidget(self.refresh_btn)

        self.open_btn = QPushButton("Apri dispositivo selezionato")
        self.open_btn.clicked.connect(self.open_selected_device)
        btn_layout.addWidget(self.open_btn)

        self.delete_btn = QPushButton("Marca come eliminati i selezionati")
        self.delete_btn.clicked.connect(self.soft_delete_selected)
        btn_layout.addWidget(self.delete_btn)

        btn_layout.addStretch()
        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        self.load_data()

    def open_selected_device(self):
        """Apre la dialog di dettaglio per il dispositivo selezionato."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "NESSUNA SELEZIONE", "Seleziona un dispositivo da aprire.")
            return

        # Prende solo la prima riga selezionata
        index = selected_rows[0]
        item = self.table.item(index.row(), 0)
        if not item:
            return

        dev_id = item.data(Qt.UserRole)
        try:
            # Import locale per evitare import circolari
            from app.ui.dialogs.detail_dialogs import DeviceDialog

            device_row = services.get_device_by_id(int(dev_id))
            if not device_row:
                QMessageBox.warning(self, "ERRORE", "Impossibile trovare i dati del dispositivo selezionato.")
                return

            device_data = dict(device_row)
            dest_id = device_data.get("destination_id")
            if not dest_id:
                QMessageBox.warning(self, "ERRORE", "Il dispositivo non ha una destinazione associata.")
                return

            destination_info = services.database.get_destination_by_id(dest_id)
            if not destination_info:
                QMessageBox.warning(self, "ERRORE", "Impossibile trovare la destinazione del dispositivo.")
                return

            customer_id = destination_info["customer_id"]

            dlg = DeviceDialog(
                customer_id=customer_id,
                destination_id=dest_id,
                device_data=device_data,
                parent=self,
            )
            dlg.exec()

            # Dopo eventuali modifiche, ricarica l'elenco duplicati
            self.load_data()

        except Exception as e:
            QMessageBox.warning(self, "ERRORE", f"Errore durante l'apertura del dispositivo:\n{e}")

    def load_data(self):
        self.table.setRowCount(0)
        rows = services.get_duplicate_devices_by_serial()

        for r in rows:
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            id_item = QTableWidgetItem(str(r.get("id")))
            id_item.setData(Qt.UserRole, r.get("id"))
            self.table.setItem(row_idx, 0, id_item)
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(r.get("customer_name") or "")))
            self.table.setItem(row_idx, 2, QTableWidgetItem(str(r.get("destination_name") or "")))
            self.table.setItem(row_idx, 3, QTableWidgetItem(str(r.get("description") or "")))
            self.table.setItem(row_idx, 4, QTableWidgetItem(str(r.get("serial_number") or "")))
            self.table.setItem(row_idx, 5, QTableWidgetItem(str(r.get("customer_inventory") or "")))
            self.table.setItem(row_idx, 6, QTableWidgetItem(str(r.get("ams_inventory") or "")))
            self.table.setItem(row_idx, 7, QTableWidgetItem(str(r.get("manufacturer") or "")))
            self.table.setItem(row_idx, 8, QTableWidgetItem(str(r.get("model") or "")))
            # Colonna "DUPLICATO PER": usa il campo calcolato dal DB
            reason = r.get("duplicate_reason") or ""
            self.table.setItem(row_idx, 9, QTableWidgetItem(reason))

    def soft_delete_selected(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "NESSUNA SELEZIONE", "Seleziona almeno un dispositivo da eliminare.")
            return

        reply = QMessageBox.question(
            self,
            "CONFERMA ELIMINAZIONE",
            "I dispositivi selezionati verranno marcati come ELIMINATI.\n"
            "Questa operazione non cancella le verifiche ma li nasconde dall'inventario.\n\n"
            "Vuoi continuare?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        from app import services as app_services

        count = 0
        for index in selected_rows:
            item = self.table.item(index.row(), 0)
            if not item:
                continue
            dev_id = item.data(Qt.UserRole)
            try:
                app_services.delete_device(int(dev_id))
                count += 1
            except Exception as e:
                QMessageBox.warning(self, "ERRORE", f"Impossibile eliminare dispositivo ID {dev_id}:\n{e}")

        QMessageBox.information(self, "OPERAZIONE COMPLETATA", f"{count} dispositivi marcati come eliminati.")
        self.load_data()


class DeviceDataQualityDialog(QDialog):
    """
    Mostra un elenco di problemi di qualità dati sui dispositivi.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CONTROLLO QUALITÀ DATI DISPOSITIVI")
        self.setMinimumSize(1100, 500)

        layout = QVBoxLayout(self)

        info = QLabel("Elenco dei problemi rilevati sui dati dei dispositivi.\n"
                      "Correggi i dati dalla gestione anagrafiche o modificando il dispositivo.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(0, 8, self)
        self.table.setHorizontalHeaderLabels([
            "ID", "CLIENTE", "DESTINAZIONE", "DESCRIZIONE",
            "S/N", "COSTRUTTORE", "MODELLO", "PROBLEMA"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Ricalcola problemi")
        self.refresh_btn.clicked.connect(self.load_data)
        btn_layout.addWidget(self.refresh_btn)

        btn_layout.addStretch()
        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self.load_data()

    def load_data(self):
        self.table.setRowCount(0)
        issues = services.get_device_data_quality_issues()
        for issue in issues:
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(issue.get("device_id"))))
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(issue.get("customer_name") or "")))
            self.table.setItem(row_idx, 2, QTableWidgetItem(str(issue.get("destination_name") or "")))
            self.table.setItem(row_idx, 3, QTableWidgetItem(str(issue.get("description") or "")))
            self.table.setItem(row_idx, 4, QTableWidgetItem(str(issue.get("serial_number") or "")))
            self.table.setItem(row_idx, 5, QTableWidgetItem(str(issue.get("manufacturer") or "")))
            self.table.setItem(row_idx, 6, QTableWidgetItem(str(issue.get("model") or "")))
            self.table.setItem(row_idx, 7, QTableWidgetItem(str(issue.get("issue_message") or "")))

class DateRangeSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SELEZIONA PERIODO DI RIFERIMENTO")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("DATA DI INIZIO:"))
        self.start_calendar = QCalendarWidget(self)
        self.start_calendar.setGridVisible(True)
        self.start_calendar.setSelectedDate(QDate.currentDate().addMonths(-1))
        layout.addWidget(self.start_calendar)
        layout.addWidget(QLabel("DATA DI FINE:"))
        self.end_calendar = QCalendarWidget(self)
        self.end_calendar.setGridVisible(True)
        self.end_calendar.setSelectedDate(QDate.currentDate())
        layout.addWidget(self.end_calendar)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_date_range(self):
        start_date = self.start_calendar.selectedDate().toString("yyyy-MM-dd")
        end_date = self.end_calendar.selectedDate().toString("yyyy-MM-dd")
        return start_date, end_date

class VerificationStatusDialog(QDialog):
    def __init__(self, verified_devices, unverified_devices, parent=None):
        super().__init__(parent)
        self.setWindowTitle("STATO VERIFICHE DISPOSITIVI")
        self.setMinimumSize(800, 600)
        layout = QVBoxLayout(self)
        verified_group = QGroupBox(f"DISPOSITIVI VERIFICATI ({len(verified_devices)})")
        verified_layout = QVBoxLayout(verified_group)
        self.verified_list = QListWidget()
        for device in verified_devices:
            self.verified_list.addItem(f"{str(device['description']).upper()} (S/N: {str(device['serial_number']).upper()})")
        verified_layout.addWidget(self.verified_list)
        layout.addWidget(verified_group)
        unverified_group = QGroupBox(f"DISPOSITIVI DA VERIFICARE ({len(unverified_devices)})")
        unverified_layout = QVBoxLayout(unverified_group)
        self.unverified_list = QListWidget()
        for device in unverified_devices:
            self.unverified_list.addItem(f"{str(device['description']).upper()} (S/N: {str(device['serial_number']).upper()})")
        unverified_layout.addWidget(self.unverified_list)
        layout.addWidget(unverified_group)
        close_button = QPushButton("CHIUDI")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

class DeviceSearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CERCA DISPOSITIVO")
        self.setMinimumSize(500, 300)
        self.selected_device_data = None
        layout = QVBoxLayout(self)
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("CERCA PER DESCRIZIONE, MODELLO O S/N...")
        search_button = QPushButton("CERCA")
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_button)
        layout.addLayout(search_layout)
        self.results_list = QListWidget()
        layout.addWidget(self.results_list)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        search_button.clicked.connect(self.perform_search)
        self.search_input.returnPressed.connect(self.perform_search)
        self.results_list.itemDoubleClicked.connect(self.accept_selection)

    def perform_search(self):
        search_term = self.search_input.text().strip()
        if len(search_term) < 3:
            QMessageBox.warning(self, "RICERCA", "INSERISCI ALMENO 3 CARATTERI PER AVVIARE LA RICERCA.")
            return
        results = services.search_device_globally(search_term)
        self.results_list.clear()
        if not results:
            self.results_list.addItem("NESSUN DISPOSITIVO TROVATO.")
        else:
            for device_row in results:
                device = dict(device_row)
                customer_name = str(device.get('customer_name', 'SCONOSCIUTO')).upper()
                display_text = f"{str(device['description']).upper()} (MODELLO: {str(device['model']).upper()}) - CLIENTE: {customer_name}"
                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, device)
                self.results_list.addItem(item)

    def accept_selection(self):
        selected_item = self.results_list.currentItem()
        if not selected_item or not selected_item.data(Qt.UserRole):
            QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONA UN DISPOSITIVO DALLA LISTA.")
            return
        self.selected_device_data = selected_item.data(Qt.UserRole)
        self.accept()


class CustomerSelectionDialog(QDialog):
    def __init__(self, customers, current_customer_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SPOSTA DISPOSITIVO")
        self.setMinimumWidth(400)
        self.selected_customer_id = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"SELEZIONA IL NUOVO CLIENTE DI DESTINAZIONE PER IL DISPOSITIVO."))
        layout.addWidget(QLabel(f"<b>CLIENTE ATTUALE:</b> {current_customer_name.upper()}"))
        self.customer_combo = QComboBox()
        for customer in customers:
            self.customer_combo.addItem(customer['name'].upper(), customer['id'])
        layout.addWidget(self.customer_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        self.selected_customer_id = self.customer_combo.currentData()
        super().accept()

class DestinationDetailDialog(QDialog):
    def __init__(self, destination_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DETTAGLI DESTINAZIONE / SEDE")
        data = destination_data or {}
        layout = QFormLayout(self)
        self.name_edit = QLineEdit(data.get('name', ''))
        self.address_edit = QLineEdit(data.get('address', ''))
        layout.addRow("NOME DESTINAZIONE/REPARTO:", self.name_edit)
        layout.addRow("INDIRIZZO (OPZIONALE):", self.address_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        return {
            "name": self.name_edit.text().strip().upper(),
            "address": self.address_edit.text().strip().upper()
        }

class DestinationSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SELEZIONA NUOVA DESTINAZIONE")
        self.setMinimumWidth(500)
        self.selected_destination_id = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Seleziona la nuova destinazione per il dispositivo:"))
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.completer().setFilterMode(Qt.MatchContains)
        self.combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
        all_customers = services.get_all_customers()
        for cust in all_customers:
            self.combo.addItem(f"--- {cust['name'].upper()} ---")
            last_index = self.combo.count() - 1
            self.combo.model().item(last_index).setSelectable(False)
            destinations = services.database.get_destinations_for_customer(cust['id'])
            if destinations:
                for dest in destinations:
                    self.combo.addItem(f"  {dest['name'].upper()} ({cust['name'].upper()})", dest['id'])
        layout.addWidget(self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept_selection(self):
        self.selected_destination_id = self.combo.currentData()
        if not self.selected_destination_id or not isinstance(self.selected_destination_id, int):
            QMessageBox.warning(self, "SELEZIONE NON VALIDA", "PER FAVORE, SELEZIONA UNA DESTINAZIONE VALIDA DALL'ELENCO.")
            return
        super().accept()

class ExportDestinationSelectionDialog(QDialog):
    """
    Dialog per selezionare una destinazione da cui esportare l'inventario.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SELEZIONA DESTINAZIONE DA ESPORTARE")
        self.setMinimumWidth(500)
        self.selected_destination_id = None
        self.selected_destination_name = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("SELEZIONA LA DESTINAZIONE PER CUI VUOI ESPORTARE L'INVENTARIO:"))

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.completer().setFilterMode(Qt.MatchContains)
        self.combo.completer().setCaseSensitivity(Qt.CaseInsensitive)

        destinations = services.database.get_all_destinations_with_customer()
        for dest in destinations:
            display_text = f"{str(dest['customer_name']).upper()} / {str(dest['name']).upper()}"
            self.combo.addItem(display_text, dest['id'])

        layout.addWidget(self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selected_destination(self):
        self.selected_destination_id = self.combo.currentData()
        self.selected_destination_name = self.combo.currentText()
        return self.selected_destination_id, self.selected_destination_name

# --- NUOVO CODICE DA AGGIUNGERE ---
class ReportNamingFormatDialog(QDialog):
    """
    Dialog per selezionare il formato del nome file per i report generati in massa.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Formato Nome Report")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        
        info_label = QLabel("Seleziona come devono essere nominati i report:")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        self.format_combo = QComboBox()
        self.format_combo.addItem("Inventario AMS VE/VF", "ams_inventory")
        self.format_combo.addItem("Numero di Serie VE/VF", "serial_number")
        self.format_combo.addItem("Inventario Cliente VE/VF", "customer_inventory")
        layout.addWidget(self.format_combo)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_selected_format(self):
        """Restituisce il formato selezionato: 'ams_inventory', 'serial_number', o 'customer_inventory'."""
        return self.format_combo.currentData()

class GlobalSearchDialog(QDialog):
    """
    Una finestra di dialogo per mostrare i risultati di una ricerca globale
    e permettere all'utente di selezionare un cliente, una destinazione o un dispositivo.
    """
    def __init__(self, search_results, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RISULTATI RICERCA")
        self.setMinimumSize(600, 400)
        self.selected_item = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"TROVATI {len(search_results)} RISULTATI:"))

        self.results_list = QListWidget()
        for item in search_results:
            list_item = QListWidgetItem()
            # Distinguiamo tra cliente, destinazione e dispositivo
            if 'serial_number' in item: # È un dispositivo
                display_text = f"📦 DISPOSITIVO: {str(item['description']).upper()} (S/N: {str(item.get('serial_number', 'N/D')).upper()} - (Inv AMS: {str(item.get('ams_inventory', 'N/D')).upper()}) - (Inv Cliente: {str(item.get('customer_inventory', 'N/D')).upper()}))"
                list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_DriveHDIcon))
            elif 'customer_id' in item and 'customer_name' in item: # È una destinazione
                display_text = f"📍 DESTINAZIONE: {item['name'].upper()} - Cliente: {item['customer_name'].upper()}"
                list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_DirIcon))
            else: # È un cliente
                display_text = f"👤 CLIENTE: {item['name'].upper()}"
                list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_ComputerIcon))

            list_item.setText(display_text)
            list_item.setData(Qt.UserRole, item)
            self.results_list.addItem(list_item)

        layout.addWidget(self.results_list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.results_list.itemDoubleClicked.connect(self.accept_selection)

    def accept_selection(self):
        selected_item = self.results_list.currentItem()
        if selected_item:
            self.selected_item = selected_item.data(Qt.UserRole)
            self.accept()
        else:
            QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONA UN ELEMENTO DALLA LISTA.")

class TemplateSelectionDialog(QDialog):
    """
    Una semplice dialog per permettere all'utente di scegliere un template 
    per un nuovo profilo di verifica.
    """
    def __init__(self, templates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SCEGLI UN MODELLO")
        self.selected_template_key = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("DA QUALE MODELLO VUOI INIZIARE?"))

        self.list_widget = QListWidget()
        for template_name in templates.keys():
            self.list_widget.addItem(template_name.upper())
        
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.list_widget.itemDoubleClicked.connect(self.accept)
        self.list_widget.setCurrentRow(0) # Pre-seleziona il primo

    def accept(self):
        selected_item = self.list_widget.currentItem()
        if selected_item:
            self.selected_template_key = selected_item.text()
            super().accept()

class ExportCustomerSelectionDialog(QDialog):
    """Dialog for selecting a customer for inventory export."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SELEZIONA CLIENTE")
        self.setModal(True)
        self.selected_customer_id = None
        
        # Create layout
        layout = QVBoxLayout(self)
        
        # Add customer selection combo
        self.customer_combo = QComboBox()
        self.customer_combo.setMinimumWidth(300)
        layout.addWidget(QLabel("SELEZIONA IL CLIENTE:"))
        layout.addWidget(self.customer_combo)
        
        # Add buttons
        button_box = QHBoxLayout()
        self.ok_button = QPushButton("Conferma")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("ANNULLA")
        self.cancel_button.clicked.connect(self.reject)
        button_box.addWidget(self.ok_button)
        button_box.addWidget(self.cancel_button)
        layout.addLayout(button_box)
        
        # Load customers
        self.load_customers()
        
    def load_customers(self):
        """Load customers into combo box."""
        import database
        customers = database.get_all_customers()
        self.customer_combo.clear()
        for customer in customers:
            self.customer_combo.addItem(customer['name'].upper(), customer['id'])
            
    def get_selected_customer(self) -> tuple[int | None, str | None]:
        """Return the selected customer ID as integer."""
        customer_id = self.customer_combo.currentData()
        return int(customer_id) if customer_id is not None else None


class EditVerificationDialog(QDialog):
    """Dialog completo per la modifica di TUTTI i campi di una verifica (elettrica o funzionale)."""

    def __init__(self, verification_data: dict, verification_type: str = "ELETTRICA", parent=None):
        super().__init__(parent)
        self.verification_type = verification_type
        self.data = verification_data or {}
        type_label = "Funzionale" if verification_type == "FUNZIONALE" else "Elettrica"
        self.setWindowTitle(f"Modifica Verifica {type_label}")
        self.setMinimumSize(750, 550)
        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_general_tab()
        if self.verification_type != "FUNZIONALE":
            self._build_visual_inspection_tab()
        self._build_results_tab()
        self._build_instrument_tab()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Salva")
        buttons.button(QDialogButtonBox.Cancel).setText("Annulla")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Tab Generale ────────────────────────────────────────────────────
    def _build_general_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        form.setLabelAlignment(Qt.AlignRight)

        code = self.data.get('verification_code', 'N/D')
        code_label = QLabel(str(code))
        code_label.setStyleSheet("font-weight: 700;")
        form.addRow("Codice:", code_label)

        profile = self.data.get('profile_name') or self.data.get('profile_key') or 'N/D'
        profile_label = QLabel(str(profile))
        form.addRow("Profilo:", profile_label)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        raw_date = self.data.get('verification_date', '')
        try:
            qd = QDate.fromString(raw_date, "yyyy-MM-dd")
            if qd.isValid():
                self.date_edit.setDate(qd)
            else:
                self.date_edit.setDate(QDate.currentDate())
        except Exception:
            self.date_edit.setDate(QDate.currentDate())
        form.addRow("Data verifica:", self.date_edit)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["PASSATO", "CONFORME CON ANNOTAZIONE", "FALLITO"])
        current_status = str(self.data.get('overall_status', '')).upper()
        idx = self.status_combo.findText(current_status)
        if idx >= 0:
            self.status_combo.setCurrentIndex(idx)
        form.addRow("Esito globale:", self.status_combo)

        self.technician_edit = QLineEdit(self.data.get('technician_name', ''))
        form.addRow("Tecnico:", self.technician_edit)

        if self.verification_type == "FUNZIONALE":
            self.notes_edit = QTextEdit()
            self.notes_edit.setPlainText(self.data.get('notes', '') or '')
            self.notes_edit.setMaximumHeight(120)
            form.addRow("Note:", self.notes_edit)

        self.tabs.addTab(tab, "Generale")

    # ── Tab Ispezione Visiva (solo elettrica) ───────────────────────────
    def _build_visual_inspection_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.checklist_items_labels = [
            "Involucro e parti meccaniche integri, senza danni.",
            "Cavo di alimentazione e spina senza danneggiamenti.",
            "Cavi paziente, connettori e accessori integri.",
            "Marcature e targhette di sicurezza leggibili.",
            "Assenza di sporcizia o segni di versamento di liquidi.",
            "Fusibili (se accessibili) di tipo e valore corretti.",
        ]

        vi = self.data.get('visual_inspection') or self.data.get('visual_inspection_json') or {}
        if isinstance(vi, str):
            try:
                vi = json.loads(vi)
            except (json.JSONDecodeError, TypeError):
                vi = {}
        existing_checklist = {item['item']: item['result'] for item in vi.get('checklist', []) if isinstance(item, dict)}

        form = QFormLayout()
        self.vi_combos: list[tuple[str, QComboBox]] = []
        for text in self.checklist_items_labels:
            combo = QComboBox()
            combo.addItems(["OK", "KO", "N/A"])
            existing_val = existing_checklist.get(text, 'OK')
            idx = combo.findText(str(existing_val).upper())
            if idx >= 0:
                combo.setCurrentIndex(idx)
            form.addRow(QLabel(text), combo)
            self.vi_combos.append((text, combo))
        layout.addLayout(form)

        layout.addWidget(QLabel("Note ispezione visiva:"))
        self.vi_notes = QTextEdit()
        self.vi_notes.setPlainText(vi.get('notes', '') or '')
        self.vi_notes.setMaximumHeight(100)
        layout.addWidget(self.vi_notes)

        self.tabs.addTab(tab, "Ispezione Visiva")

    # ── Tab Risultati ───────────────────────────────────────────────────
    def _build_results_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        if self.verification_type == "FUNZIONALE":
            self._build_functional_results(layout)
        else:
            self._build_electrical_results(layout)

        self.tabs.addTab(tab, "Risultati")

    def _build_electrical_results(self, layout: QVBoxLayout):
        layout.addWidget(QLabel("Modifica i valori misurati e gli esiti dei test:"))
        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(["Test / P.A.", "Limite", "Valore", "Esito"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)

        results = self.data.get('results') or []
        if isinstance(results, str):
            try:
                results = json.loads(results)
            except (json.JSONDecodeError, TypeError):
                results = []

        for res in results:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)

            name_item = QTableWidgetItem(str(res.get('name', '')))
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.results_table.setItem(row, 0, name_item)

            limit_item = QTableWidgetItem(str(res.get('limit_value', res.get('limit', ''))))
            limit_item.setFlags(limit_item.flags() & ~Qt.ItemIsEditable)
            self.results_table.setItem(row, 1, limit_item)

            self.results_table.setItem(row, 2, QTableWidgetItem(str(res.get('value', ''))))

            esito_combo = QComboBox()
            esito_combo.addItems(["CONFORME", "NON CONFORME"])
            is_passed = res.get('passed', False)
            esito_combo.setCurrentIndex(0 if is_passed else 1)
            self.results_table.setCellWidget(row, 3, esito_combo)

        self.results_table.resizeColumnsToContents()
        layout.addWidget(self.results_table)

    def _build_functional_results(self, layout: QVBoxLayout):
        layout.addWidget(QLabel("Modifica i valori dei risultati della verifica funzionale:"))
        self.func_results_table = QTableWidget(0, 4)
        self.func_results_table.setHorizontalHeaderLabels(["Sezione", "Voce", "Campo", "Valore"])
        self.func_results_table.horizontalHeader().setStretchLastSection(True)

        structured = self.data.get('structured_results') or {}
        if isinstance(structured, str):
            try:
                structured = json.loads(structured)
            except (json.JSONDecodeError, TypeError):
                structured = {}

        self._func_cell_map: list[tuple[str, int | None, int | None]] = []

        if isinstance(structured, dict) and structured:
            for section_key, section_data in structured.items():
                if not isinstance(section_data, dict):
                    continue
                section_title = section_data.get('title') or section_key

                for fi, field_entry in enumerate(section_data.get('fields', []) or []):
                    if not isinstance(field_entry, dict):
                        continue
                    row = self.func_results_table.rowCount()
                    self.func_results_table.insertRow(row)

                    sec_item = QTableWidgetItem(str(section_title))
                    sec_item.setFlags(sec_item.flags() & ~Qt.ItemIsEditable)
                    self.func_results_table.setItem(row, 0, sec_item)

                    voce_item = QTableWidgetItem("-")
                    voce_item.setFlags(voce_item.flags() & ~Qt.ItemIsEditable)
                    self.func_results_table.setItem(row, 1, voce_item)

                    campo_item = QTableWidgetItem(str(field_entry.get('label') or field_entry.get('key') or ''))
                    campo_item.setFlags(campo_item.flags() & ~Qt.ItemIsEditable)
                    self.func_results_table.setItem(row, 2, campo_item)

                    self.func_results_table.setItem(row, 3, QTableWidgetItem(str(field_entry.get('value', ''))))
                    self._func_cell_map.append((section_key, fi, None))

                for ri, row_entry in enumerate(section_data.get('rows', []) or []):
                    if not isinstance(row_entry, dict):
                        continue
                    row_label = row_entry.get('label') or row_entry.get('key') or '-'
                    for vi_idx, value_entry in enumerate(row_entry.get('values', []) or []):
                        if not isinstance(value_entry, dict):
                            continue
                        row = self.func_results_table.rowCount()
                        self.func_results_table.insertRow(row)

                        sec_item = QTableWidgetItem(str(section_title))
                        sec_item.setFlags(sec_item.flags() & ~Qt.ItemIsEditable)
                        self.func_results_table.setItem(row, 0, sec_item)

                        voce_item = QTableWidgetItem(str(row_label))
                        voce_item.setFlags(voce_item.flags() & ~Qt.ItemIsEditable)
                        self.func_results_table.setItem(row, 1, voce_item)

                        campo_item = QTableWidgetItem(str(value_entry.get('label') or value_entry.get('key') or ''))
                        campo_item.setFlags(campo_item.flags() & ~Qt.ItemIsEditable)
                        self.func_results_table.setItem(row, 2, campo_item)

                        self.func_results_table.setItem(row, 3, QTableWidgetItem(str(value_entry.get('value', ''))))
                        self._func_cell_map.append((section_key, ri, vi_idx))
        else:
            raw_results = self.data.get('results') or {}
            if isinstance(raw_results, dict):
                for k, v in raw_results.items():
                    row = self.func_results_table.rowCount()
                    self.func_results_table.insertRow(row)
                    key_item = QTableWidgetItem("Risultati")
                    key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
                    self.func_results_table.setItem(row, 0, key_item)
                    dash_item = QTableWidgetItem("-")
                    dash_item.setFlags(dash_item.flags() & ~Qt.ItemIsEditable)
                    self.func_results_table.setItem(row, 1, dash_item)
                    campo_item = QTableWidgetItem(str(k))
                    campo_item.setFlags(campo_item.flags() & ~Qt.ItemIsEditable)
                    self.func_results_table.setItem(row, 2, campo_item)
                    self.func_results_table.setItem(row, 3, QTableWidgetItem(str(v)))
                    self._func_cell_map.append(('__raw__', k, None))

        self.func_results_table.resizeColumnsToContents()
        layout.addWidget(self.func_results_table)

    # ── Tab Strumento MTI ───────────────────────────────────────────────
    def _build_instrument_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        form.setLabelAlignment(Qt.AlignRight)

        self.mti_instrument_edit = QLineEdit(str(self.data.get('mti_instrument', '') or ''))
        form.addRow("Strumento:", self.mti_instrument_edit)

        self.mti_serial_edit = QLineEdit(str(self.data.get('mti_serial', '') or ''))
        form.addRow("Seriale:", self.mti_serial_edit)

        self.mti_version_edit = QLineEdit(str(self.data.get('mti_version', '') or ''))
        form.addRow("Versione:", self.mti_version_edit)

        self.mti_cal_date_edit = QDateEdit()
        self.mti_cal_date_edit.setCalendarPopup(True)
        self.mti_cal_date_edit.setDisplayFormat("yyyy-MM-dd")
        raw_cal = str(self.data.get('mti_cal_date', '') or '')
        try:
            qd = QDate.fromString(raw_cal, "yyyy-MM-dd")
            if qd.isValid():
                self.mti_cal_date_edit.setDate(qd)
            else:
                self.mti_cal_date_edit.setDate(QDate.currentDate())
        except Exception:
            self.mti_cal_date_edit.setDate(QDate.currentDate())
        form.addRow("Data calibrazione:", self.mti_cal_date_edit)

        self.tabs.addTab(tab, "Strumento MTI")

    # ── Validazione ─────────────────────────────────────────────────────
    def _validate_and_accept(self):
        if not self.technician_edit.text().strip():
            QMessageBox.warning(self, "Dati mancanti", "Il campo tecnico non può essere vuoto.")
            return
        if not self.date_edit.date().isValid():
            QMessageBox.warning(self, "Dati mancanti", "La data inserita non è valida.")
            return
        self.accept()

    # ── Raccolta dati ───────────────────────────────────────────────────
    def get_data(self) -> dict:
        result: dict = {
            'verification_date': self.date_edit.date().toString("yyyy-MM-dd"),
            'overall_status': self.status_combo.currentText(),
            'technician_name': self.technician_edit.text().strip(),
            'mti_instrument': self.mti_instrument_edit.text().strip(),
            'mti_serial': self.mti_serial_edit.text().strip(),
            'mti_version': self.mti_version_edit.text().strip(),
            'mti_cal_date': self.mti_cal_date_edit.date().toString("yyyy-MM-dd"),
        }

        if self.verification_type == "FUNZIONALE":
            result['notes'] = self.notes_edit.toPlainText().strip()
            result['structured_results'] = self._collect_functional_results()
        else:
            result['results'] = self._collect_electrical_results()
            result['visual_inspection'] = self._collect_visual_inspection()

        return result

    def _collect_electrical_results(self) -> list[dict]:
        original_results = self.data.get('results') or []
        if isinstance(original_results, str):
            try:
                original_results = json.loads(original_results)
            except (json.JSONDecodeError, TypeError):
                original_results = []

        updated: list[dict] = []
        for i in range(self.results_table.rowCount()):
            if i < len(original_results):
                entry = dict(original_results[i])
            else:
                entry = {'name': self.results_table.item(i, 0).text() if self.results_table.item(i, 0) else ''}

            value_item = self.results_table.item(i, 2)
            entry['value'] = value_item.text() if value_item else ''

            combo = self.results_table.cellWidget(i, 3)
            if isinstance(combo, QComboBox):
                entry['passed'] = combo.currentText() == "CONFORME"

            updated.append(entry)
        return updated

    def _collect_visual_inspection(self) -> dict:
        return {
            'notes': self.vi_notes.toPlainText().strip(),
            'checklist': [{'item': text, 'result': combo.currentText()} for text, combo in self.vi_combos],
        }

    def _collect_functional_results(self) -> dict:
        structured = self.data.get('structured_results') or {}
        if isinstance(structured, str):
            try:
                structured = json.loads(structured)
            except (json.JSONDecodeError, TypeError):
                structured = {}

        import copy
        updated = copy.deepcopy(structured) if isinstance(structured, dict) else {}

        for table_row, mapping in enumerate(self._func_cell_map):
            value_item = self.func_results_table.item(table_row, 3)
            new_value = value_item.text() if value_item else ''

            section_key, idx1, idx2 = mapping

            if section_key == '__raw__':
                continue

            section = updated.get(section_key)
            if not isinstance(section, dict):
                continue

            if idx2 is None:
                fields = section.get('fields') or []
                if isinstance(idx1, int) and idx1 < len(fields) and isinstance(fields[idx1], dict):
                    fields[idx1]['value'] = new_value
            else:
                rows = section.get('rows') or []
                if isinstance(idx1, int) and idx1 < len(rows):
                    row_entry = rows[idx1]
                    if isinstance(row_entry, dict):
                        values = row_entry.get('values') or []
                        if isinstance(idx2, int) and idx2 < len(values) and isinstance(values[idx2], dict):
                            values[idx2]['value'] = new_value

        return updated