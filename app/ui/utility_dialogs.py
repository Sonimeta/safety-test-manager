import json
from datetime import datetime
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QComboBox, QTextEdit, QCalendarWidget, QDialogButtonBox, QFormLayout, QSpinBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QMessageBox, QLineEdit, QStyle, QHeaderView, QAbstractItemView, QListWidget, QListWidgetItem, QApplication)
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

        self.table = QTableWidget(0, 9, self)
        self.table.setHorizontalHeaderLabels([
            "ID", "CLIENTE", "DESTINAZIONE", "DESCRIZIONE",
            "S/N", "COSTRUTTORE", "MODELLO",
            "PROFILO", "PROFILO FUNZ."
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Aggiorna elenco")
        self.refresh_btn.clicked.connect(self.load_data)
        btn_layout.addWidget(self.refresh_btn)

        self.delete_btn = QPushButton("Marca come eliminati i selezionati")
        self.delete_btn.clicked.connect(self.soft_delete_selected)
        btn_layout.addWidget(self.delete_btn)

        btn_layout.addStretch()
        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        self.load_data()

    def load_data(self):
        self.table.setRowCount(0)
        duplicates_serial = services.get_duplicate_devices_by_serial()
        duplicates_chars = services.get_duplicate_devices_by_characteristics()

        def _add_rows(rows, group_label):
            for r in rows:
                row_idx = self.table.rowCount()
                self.table.insertRow(row_idx)
                id_item = QTableWidgetItem(str(r.get("id")))
                id_item.setData(Qt.UserRole, r.get("id"))
                self.table.setItem(row_idx, 0, id_item)
                self.table.setItem(row_idx, 1, QTableWidgetItem(str(r.get("customer_name") or "")))
                self.table.setItem(row_idx, 2, QTableWidgetItem(str(r.get("destination_name") or "")))
                self.table.setItem(row_idx, 3, QTableWidgetItem(str(r.get("description") or "")))
                sn = str(r.get("serial_number") or "")
                if group_label == "serial":
                    sn = f"{sn}  (DUPLICATO SN)"
                self.table.setItem(row_idx, 4, QTableWidgetItem(sn))
                self.table.setItem(row_idx, 5, QTableWidgetItem(str(r.get("manufacturer") or "")))
                self.table.setItem(row_idx, 6, QTableWidgetItem(str(r.get("model") or "")))
                self.table.setItem(row_idx, 7, QTableWidgetItem(str(r.get("default_profile_key") or "")))
                self.table.setItem(row_idx, 8, QTableWidgetItem(str(r.get("default_functional_profile_key") or "")))

        _add_rows(duplicates_serial, "serial")
        _add_rows(duplicates_chars, "chars")

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

class InstrumentSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleziona Strumento")
        self.settings = QSettings("ELSON META", "SafetyTester")
        self.instruments = services.get_all_instruments()
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
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["ORDINE", "NOME PARTE APPLICATA", "CODICE STRUMENTO"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(table)
        table.setRowCount(0)
        for i, part in enumerate(applied_parts):
            row = table.rowCount()
            table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(str(i + 1).upper()))
        table.setItem(row, 1, QTableWidgetItem(f"{part.name.upper()} ({part.description.upper()})"))
        table.setItem(row, 2, QTableWidgetItem(part.code.upper()))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("PRONTO PER INIZIARE")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
    def __init__(self, parent=None, label_text=None):
        super().__init__(parent)
        self.setWindowTitle("SELEZIONA NUOVA DESTINAZIONE")
        self.setMinimumWidth(500)
        self.selected_destination_id = None
        layout = QVBoxLayout(self)
        display_label = label_text or "Seleziona la nuova destinazione per il dispositivo:"
        layout.addWidget(QLabel(display_label))
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
class GlobalSearchDialog(QDialog):
    """
    Una finestra di dialogo per mostrare i risultati di una ricerca globale
    e permettere all'utente di selezionare un cliente o un dispositivo.
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
            # Distinguiamo tra cliente e dispositivo
            if 'address' in item: # È un cliente
                display_text = f"CLIENTE: {item['name'].upper()}"
                list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_ComputerIcon))
            else: # È un dispositivo
                display_text = f"DISPOSITIVO: {str(item['description']).upper()} (S/N: {str(item.get('serial_number', 'N/D')).upper()} - (Inv AMS: {str(item.get('ams_inventory', 'N/D')).upper()}) - (Inv Cliente: {str(item.get('customer_inventory', 'N/D')).upper()}))"
                list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_DriveHDIcon))

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