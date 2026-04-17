# app/ui/dialogs/system_verification_dialogs.py
"""
Dialogs per le verifiche di sistema (CEI 62353).
Permette di verificare più dispositivi insieme come un unico sistema.
"""
import json
import os
import re
import logging
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QListWidget, QListWidgetItem,
    QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox, QSizePolicy,
    QFileDialog, QFrame, QTextEdit, QCheckBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont

from app import config, services
import database


class SystemDeviceSelectionDialog(QDialog):
    """
    Dialog per selezionare i dispositivi da includere in una verifica di sistema.
    Mostra tutti i dispositivi della destinazione corrente con checkbox per selezione multipla.
    """

    def __init__(self, destination_id: int, destination_name: str = "",
                 preselected_device_id: int = None, parent=None):
        super().__init__(parent)
        self.destination_id = destination_id
        self.destination_name = destination_name
        self.preselected_device_id = preselected_device_id
        self.selected_device_ids = []
        self.selected_devices_info = []

        self.setWindowTitle("Verifica di Sistema — Selezione Dispositivi")
        self.setMinimumSize(800, 600)
        self.setup_ui()
        self.load_devices()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Intestazione
        header = QLabel(
            f"<h3>🔗 Verifica di Sistema — CEI 62353</h3>"
            f"<p>Selezionare i dispositivi che compongono il sistema da verificare.</p>"
            f"<p><b>Destinazione:</b> {self.destination_name}</p>"
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        # Nome sistema
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("<b>Nome Sistema (opzionale):</b>"))
        self.system_name_input = QLineEdit()
        self.system_name_input.setPlaceholderText("Es: Sistema Monitoraggio Paziente, Carrello Anestesia...")
        self.system_name_input.setMinimumHeight(36)
        name_layout.addWidget(self.system_name_input)
        layout.addLayout(name_layout)

        # Filtro ricerca
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Cerca dispositivo per nome, matricola, modello...")
        self.search_input.setMinimumHeight(36)
        self.search_input.textChanged.connect(self.filter_devices)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Pulsanti seleziona/deseleziona tutto
        sel_layout = QHBoxLayout()
        btn_select_all = QPushButton("✅ Seleziona Tutti")
        btn_select_all.clicked.connect(self.select_all)
        sel_layout.addWidget(btn_select_all)
        btn_deselect_all = QPushButton("❌ Deseleziona Tutti")
        btn_deselect_all.clicked.connect(self.deselect_all)
        sel_layout.addWidget(btn_deselect_all)
        sel_layout.addStretch()
        self.selection_count_label = QLabel("<b>0 dispositivi selezionati</b>")
        sel_layout.addWidget(self.selection_count_label)
        layout.addLayout(sel_layout)

        # Lista dispositivi con checkbox
        self.device_list = QListWidget()
        self.device_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.device_list.setMinimumHeight(300)
        layout.addWidget(self.device_list)

        # Selezione profilo di verifica
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("<b>Profilo di verifica:</b>"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumHeight(36)
        for key, profile in config.PROFILES.items():
            self.profile_combo.addItem(profile.name.upper(), key)
        profile_layout.addWidget(self.profile_combo, 1)
        layout.addLayout(profile_layout)

        # Pulsanti OK/Annulla
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("Annulla")
        btn_cancel.setMinimumHeight(40)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        self.btn_confirm = QPushButton("▶ Avvia Verifica di Sistema")
        self.btn_confirm.setMinimumHeight(40)
        self.btn_confirm.setObjectName("primaryButton")
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.clicked.connect(self.on_confirm)
        btn_layout.addWidget(self.btn_confirm)

        layout.addLayout(btn_layout)

    def load_devices(self):
        """Carica i dispositivi dalla destinazione."""
        self.device_list.clear()
        self._all_devices = []

        devices = database.get_devices_for_destination(self.destination_id)
        if not devices:
            return

        for dev_row in devices:
            dev = dict(dev_row)
            if dev.get('is_deleted'):
                continue
            # Decodifica applied_parts_json in applied_parts
            ap_json = dev.get('applied_parts_json')
            if ap_json and isinstance(ap_json, str):
                try:
                    dev['applied_parts'] = json.loads(ap_json)
                except (json.JSONDecodeError, TypeError):
                    dev['applied_parts'] = []
            elif not dev.get('applied_parts'):
                dev['applied_parts'] = []
            self._all_devices.append(dev)

            desc = dev.get('description') or 'Dispositivo'
            serial = dev.get('serial_number') or 'N/D'
            manufacturer = dev.get('manufacturer') or ''
            model = dev.get('model') or ''

            display_text = f"{desc}  —  S/N: {serial}"
            if manufacturer:
                display_text += f"  |  {manufacturer}"
            if model:
                display_text += f" {model}"

            item = QListWidgetItem()
            item.setText(display_text)
            item.setData(Qt.UserRole, dev['id'])
            item.setData(Qt.UserRole + 1, dev)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if dev['id'] == self.preselected_device_id else Qt.Unchecked)
            self.device_list.addItem(item)

        self.device_list.itemChanged.connect(self.update_selection_count)
        self.update_selection_count()

    def filter_devices(self, text):
        """Filtra la lista dispositivi."""
        text = text.lower()
        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            item.setHidden(text not in item.text().lower())

    def select_all(self):
        """Seleziona tutti i dispositivi visibili."""
        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Checked)

    def deselect_all(self):
        """Deseleziona tutti i dispositivi."""
        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            item.setCheckState(Qt.Unchecked)

    def update_selection_count(self):
        """Aggiorna il conteggio e abilita/disabilita il pulsante conferma."""
        count = 0
        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            if item.checkState() == Qt.Checked:
                count += 1

        self.selection_count_label.setText(f"<b>{count} dispositivi selezionati</b>")
        self.btn_confirm.setEnabled(count >= 2)

        if count < 2:
            self.btn_confirm.setToolTip("Selezionare almeno 2 dispositivi per una verifica di sistema")
        else:
            self.btn_confirm.setToolTip("")

    def on_confirm(self):
        """Conferma la selezione e chiude il dialog."""
        self.selected_device_ids = []
        self.selected_devices_info = []

        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            if item.checkState() == Qt.Checked:
                dev_id = item.data(Qt.UserRole)
                dev_info = item.data(Qt.UserRole + 1)
                self.selected_device_ids.append(dev_id)
                self.selected_devices_info.append(dev_info)

        if len(self.selected_device_ids) < 2:
            QMessageBox.warning(self, "Attenzione",
                                "Selezionare almeno 2 dispositivi per una verifica di sistema.")
            return

        self.accept()

    def get_system_name(self):
        """Restituisce il nome del sistema."""
        return self.system_name_input.text().strip()

    def get_selected_device_ids(self):
        """Restituisce gli ID dei dispositivi selezionati."""
        return self.selected_device_ids

    def get_selected_devices_info(self):
        """Restituisce le informazioni complete dei dispositivi selezionati."""
        return self.selected_devices_info

    def get_selected_profile_key(self):
        """Restituisce la chiave del profilo di verifica selezionato."""
        return self.profile_combo.currentData()


class SystemVerificationViewerDialog(QDialog):
    """
    Viewer per i dettagli di una verifica di sistema.
    Mostra i risultati dei test e l'elenco dei dispositivi inclusi.
    """

    def __init__(self, sv_id: int, parent=None):
        super().__init__(parent)
        self.sv_id = sv_id
        self.sv_data = None
        self.devices_info = []
        self.setWindowTitle("Dettagli Verifica di Sistema")
        self.setMinimumSize(900, 650)
        self.load_data()
        self.setup_ui()

    def load_data(self):
        """Carica i dati della verifica di sistema."""
        self.sv_data = database.get_system_verification_by_id(self.sv_id)
        if self.sv_data:
            devices_rows = database.get_system_verification_devices(self.sv_id)
            self.devices_info = [dict(d) for d in devices_rows]

    def setup_ui(self):
        if not self.sv_data:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("Verifica di sistema non trovata."))
            btn = QPushButton("Chiudi")
            btn.clicked.connect(self.accept)
            layout.addWidget(btn)
            return

        data = self.sv_data
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # === INTESTAZIONE ===
        system_name = data.get('system_name') or 'Sistema'
        header_text = (
            f"<h3>🔗 Verifica di Sistema: {system_name}</h3>"
            f"<b>Codice:</b> {data.get('verification_code', 'N/A')}<br>"
            f"<b>Data:</b> {data.get('verification_date', 'N/D')}<br>"
            f"<b>Profilo:</b> {str(data.get('profile_name', '')).upper()}<br>"
            f"<b>Tecnico:</b> {data.get('technician_name', 'N/D')}<br>"
            f"<b>Destinazione:</b> {data.get('destination_name', 'N/D')}"
        )
        header_label = QLabel(header_text)
        header_label.setWordWrap(True)
        layout.addWidget(header_label)

        # === ESITO ===
        status = data.get('overall_status', 'N/D')
        status_color = "#28a745" if status == "PASSATO" else "#dc3545" if status == "FALLITO" else "#ffc107"
        status_label = QLabel(
            f"<h2 style='color: {status_color};'>ESITO: {status.upper()}</h2>"
        )
        status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(status_label)

        # === DISPOSITIVI DEL SISTEMA ===
        devices_group = QGroupBox(f"📱 Dispositivi nel Sistema ({len(self.devices_info)})")
        devices_layout = QVBoxLayout(devices_group)

        devices_table = QTableWidget(0, 5)
        devices_table.setHorizontalHeaderLabels([
            "Descrizione", "Matricola", "Costruttore", "Modello", "Inv. AMS"
        ])
        devices_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        devices_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        devices_table.setMaximumHeight(180)

        for dev in self.devices_info:
            row = devices_table.rowCount()
            devices_table.insertRow(row)
            devices_table.setItem(row, 0, QTableWidgetItem(dev.get('description', '')))
            devices_table.setItem(row, 1, QTableWidgetItem(dev.get('serial_number', '')))
            devices_table.setItem(row, 2, QTableWidgetItem(dev.get('manufacturer', '')))
            devices_table.setItem(row, 3, QTableWidgetItem(dev.get('model', '')))
            devices_table.setItem(row, 4, QTableWidgetItem(dev.get('ams_inventory', '')))

        devices_table.resizeColumnsToContents()
        devices_layout.addWidget(devices_table)
        layout.addWidget(devices_group)

        # === ISPEZIONE VISIVA ===
        visual_data = data.get('visual_inspection', {})
        if visual_data:
            visual_group = QGroupBox("👁 Ispezione Visiva")
            visual_layout = QVBoxLayout(visual_group)
            for item in visual_data.get('checklist', []):
                result_text = str(item.get('result', '')).upper()
                color = "#28a745" if result_text == "OK" else "#dc3545"
                lbl = QLabel(f"• {item.get('item', '')} — <b style='color:{color}'>{result_text}</b>")
                visual_layout.addWidget(lbl)
            notes = visual_data.get('notes', '')
            if notes:
                visual_layout.addWidget(QLabel(f"<b>Note:</b> {notes}"))
            layout.addWidget(visual_group)

        # === RISULTATI TEST ===
        results = data.get('results', [])
        if results:
            results_group = QGroupBox(f"📊 Risultati Test ({len(results)} prove)")
            results_layout = QVBoxLayout(results_group)

            results_table = QTableWidget(0, 4)
            results_table.setHorizontalHeaderLabels([
                "Test / P.A.", "Limite", "Valore", "Esito"
            ])
            results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

            for res in results:
                row = results_table.rowCount()
                results_table.insertRow(row)
                results_table.setItem(row, 0, QTableWidgetItem(
                    str(res.get('name', '')).upper()))

                limit_val = res.get('limit_value') or res.get('limit', '')
                unit = res.get('unit', '')
                limit_text = f"{limit_val} {unit}".strip() if limit_val else ''
                results_table.setItem(row, 1, QTableWidgetItem(limit_text.upper()))

                value = res.get('value', '')
                results_table.setItem(row, 2, QTableWidgetItem(str(value).upper()))

                is_passed = res.get('passed', False)
                passed_item = QTableWidgetItem("CONFORME" if is_passed else "NON CONFORME")
                passed_item.setBackground(QColor('#D4EDDA') if is_passed else QColor('#F8D7DA'))
                results_table.setItem(row, 3, passed_item)

            results_table.resizeColumnsToContents()
            results_layout.addWidget(results_table)
            layout.addWidget(results_group)

        # === STRUMENTO ===
        mti_instrument = data.get('mti_instrument', '')
        if mti_instrument:
            mti_group = QGroupBox("🔧 Strumento di Misura")
            mti_layout = QGridLayout(mti_group)
            mti_layout.addWidget(QLabel("<b>Strumento:</b>"), 0, 0)
            mti_layout.addWidget(QLabel(mti_instrument), 0, 1)
            mti_layout.addWidget(QLabel("<b>Seriale:</b>"), 0, 2)
            mti_layout.addWidget(QLabel(data.get('mti_serial', '')), 0, 3)
            mti_layout.addWidget(QLabel("<b>Data Calibrazione:</b>"), 1, 0)
            mti_layout.addWidget(QLabel(data.get('mti_cal_date', '')), 1, 1)
            layout.addWidget(mti_group)

        # === PULSANTI ===
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_pdf = QPushButton("📄 Genera PDF")
        btn_pdf.setMinimumHeight(36)
        btn_pdf.clicked.connect(self._generate_pdf)
        btn_layout.addWidget(btn_pdf)

        btn_close = QPushButton("Chiudi")
        btn_close.setMinimumHeight(36)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def _generate_pdf(self):
        """Genera il report PDF della verifica di sistema."""
        data = self.sv_data
        system_name = (data.get('system_name') or 'Sistema').strip()
        safe_name = re.sub(r'[\\/*?:"<>|]', '_', system_name)
        code = data.get('verification_code', '')
        default_filename = os.path.join(os.getcwd(), f"{safe_name}_{code}_VS.pdf")

        filename, _ = QFileDialog.getSaveFileName(
            self, "Salva Report Verifica di Sistema", default_filename, "PDF Files (*.pdf)"
        )
        if not filename:
            return

        try:
            report_settings = {}
            parent = self.parent()
            if parent and hasattr(parent, 'logo_path'):
                report_settings['logo_path'] = parent.logo_path

            services.generate_system_pdf_report(filename, self.sv_id, report_settings)
            QMessageBox.information(self, "Successo", f"Report generato con successo:\n{filename}")
        except Exception as e:
            logging.error(f"Errore generazione report verifica di sistema: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile generare il report:\n{e}")


class SystemVerificationListDialog(QDialog):
    """
    Dialog per visualizzare e gestire le verifiche di sistema di una destinazione.
    Accessibile come pannello embedded nella finestra principale.
    """

    def __init__(self, destination_id: int, destination_name: str = "", parent=None):
        super().__init__(parent)
        self.destination_id = destination_id
        self.destination_name = destination_name
        self.setWindowTitle(f"Verifiche di Sistema — {destination_name}")
        self.setMinimumSize(900, 500)
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel(
            f"<h3>🔗 Verifiche di Sistema</h3>"
            f"<p>Destinazione: <b>{self.destination_name}</b></p>"
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        # Tabella verifiche di sistema
        self.sv_table = QTableWidget(0, 6)
        self.sv_table.setHorizontalHeaderLabels([
            "Data", "Codice", "Nome Sistema", "Profilo", "Dispositivi", "Esito"
        ])
        self.sv_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.sv_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sv_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sv_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.sv_table.doubleClicked.connect(self._view_selected)
        layout.addWidget(self.sv_table)

        # Pulsanti
        btn_layout = QHBoxLayout()

        btn_view = QPushButton("👁 Visualizza Dettagli")
        btn_view.setMinimumHeight(36)
        btn_view.clicked.connect(self._view_selected)
        btn_layout.addWidget(btn_view)

        btn_pdf = QPushButton("📄 Genera PDF")
        btn_pdf.setMinimumHeight(36)
        btn_pdf.clicked.connect(self._generate_pdf_selected)
        btn_layout.addWidget(btn_pdf)

        btn_delete = QPushButton("🗑 Elimina")
        btn_delete.setMinimumHeight(36)
        btn_delete.clicked.connect(self._delete_selected)
        btn_layout.addWidget(btn_delete)

        btn_layout.addStretch()

        btn_close = QPushButton("Chiudi")
        btn_close.setMinimumHeight(36)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def load_data(self):
        """Carica le verifiche di sistema per la destinazione."""
        self.sv_table.setRowCount(0)
        verifications = services.get_system_verifications_for_destination(self.destination_id)

        for sv in verifications:
            row = self.sv_table.rowCount()
            self.sv_table.insertRow(row)

            # Data
            date_item = QTableWidgetItem(sv.get('verification_date', ''))
            date_item.setData(Qt.UserRole, sv.get('id'))
            self.sv_table.setItem(row, 0, date_item)

            # Codice
            self.sv_table.setItem(row, 1, QTableWidgetItem(sv.get('verification_code', '')))

            # Nome sistema
            self.sv_table.setItem(row, 2, QTableWidgetItem(sv.get('system_name', '') or ''))

            # Profilo
            self.sv_table.setItem(row, 3, QTableWidgetItem(
                str(sv.get('profile_name', '')).upper()))

            # Numero dispositivi
            device_count = sv.get('device_count', 0)
            count_item = QTableWidgetItem(str(device_count))
            count_item.setTextAlignment(Qt.AlignCenter)
            self.sv_table.setItem(row, 4, count_item)

            # Esito
            status = sv.get('overall_status', '')
            status_item = QTableWidgetItem(status.upper())
            if status == 'PASSATO':
                status_item.setBackground(QColor('#D4EDDA'))
            elif status == 'FALLITO':
                status_item.setBackground(QColor('#F8D7DA'))
            else:
                status_item.setBackground(QColor('#FFF3CD'))
            self.sv_table.setItem(row, 5, status_item)

        self.sv_table.resizeColumnsToContents()

    def _get_selected_sv_id(self):
        """Restituisce l'ID della verifica selezionata."""
        row = self.sv_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Info", "Selezionare una verifica dalla tabella.")
            return None
        return self.sv_table.item(row, 0).data(Qt.UserRole)

    def _view_selected(self):
        """Apre il viewer della verifica selezionata."""
        sv_id = self._get_selected_sv_id()
        if sv_id is None:
            return
        viewer = SystemVerificationViewerDialog(sv_id, self)
        viewer.exec()

    def _generate_pdf_selected(self):
        """Genera PDF per la verifica selezionata."""
        sv_id = self._get_selected_sv_id()
        if sv_id is None:
            return

        sv_data = database.get_system_verification_by_id(sv_id)
        if not sv_data:
            QMessageBox.critical(self, "Errore", "Verifica di sistema non trovata.")
            return

        system_name = (sv_data.get('system_name') or 'Sistema').strip()
        safe_name = re.sub(r'[\\/*?:"<>|]', '_', system_name)
        code = sv_data.get('verification_code', '')
        default_filename = os.path.join(os.getcwd(), f"{safe_name}_{code}_VS.pdf")

        filename, _ = QFileDialog.getSaveFileName(
            self, "Salva Report", default_filename, "PDF Files (*.pdf)"
        )
        if not filename:
            return

        try:
            report_settings = {}
            parent = self.parent()
            if parent and hasattr(parent, 'logo_path'):
                report_settings['logo_path'] = parent.logo_path
            services.generate_system_pdf_report(filename, sv_id, report_settings)
            QMessageBox.information(self, "Successo", f"Report generato:\n{filename}")
        except Exception as e:
            logging.error(f"Errore generazione report: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore:\n{e}")

    def _delete_selected(self):
        """Elimina la verifica di sistema selezionata."""
        sv_id = self._get_selected_sv_id()
        if sv_id is None:
            return

        reply = QMessageBox.question(
            self, "Conferma Eliminazione",
            "Sei sicuro di voler eliminare questa verifica di sistema?\n"
            "L'operazione è irreversibile.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            services.delete_system_verification(sv_id)
            self.load_data()
            QMessageBox.information(self, "Eliminato", "Verifica di sistema eliminata con successo.")
        except Exception as e:
            logging.error(f"Errore eliminazione verifica di sistema: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore durante l'eliminazione:\n{e}")
