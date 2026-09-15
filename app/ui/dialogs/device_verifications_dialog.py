# app/ui/dialogs/device_verifications_dialog.py

import os
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QWidget,
    QGroupBox,
    QFrame,
    QHeaderView,
    QAbstractItemView,
    QMessageBox,
    QFileDialog,
    QApplication,
)

from app import config, services, auth_manager
import database
from app.ui.dialogs.utility_dialogs import (
    VerificationViewerDialog,
    FunctionalVerificationViewerDialog,
    EditVerificationDialog,
)
from app.ui.dialogs.ecografo_quality_dialog import EcografoQualityDialog


class NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem con ordinamento numerico corretto."""
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except (ValueError, TypeError, AttributeError):
            return super().__lt__(other)


class DeviceVerificationsDialog(QDialog):
    """
    Dialog per consultare lo storico completo delle verifiche eseguite su uno specifico apparecchio
    (Verifiche Elettriche, Funzionali, Controllo Qualità Sonde Ecografo e Verifiche di Sistema)
    direttamente dalla schermata principale.
    """

    def __init__(self, device_id: int, parent: Optional[QWidget] = None, main_window: Optional[Any] = None):
        super().__init__(parent)
        self.device_id = device_id
        self.main_window = main_window or (parent if hasattr(parent, 'logo_path') else None)
        self.user_role = auth_manager.get_current_role()

        # Carica dati dispositivo
        device_row = services.database.get_device_by_id(self.device_id)
        if not device_row:
            raise ValueError(f"Dispositivo con ID {self.device_id} non trovato.")
        self.device_data = dict(device_row)

        # Destinazione e Cliente
        dest_id = self.device_data.get("destination_id")
        dest_row = services.database.get_destination_by_id(dest_id) if dest_id else None
        self.dest_data = dict(dest_row) if dest_row else {}

        customer_id = self.dest_data.get("customer_id")
        cust_row = services.database.get_customer_by_id(customer_id) if customer_id else None
        self.cust_data = dict(cust_row) if cust_row else {}

        # Dati caricati in memoria per filtro
        self._electrical_entries: List[Dict[str, Any]] = []
        self._functional_entries: List[Dict[str, Any]] = []
        self._ecografo_entries: List[Dict[str, Any]] = []
        self._system_entries: List[Dict[str, Any]] = []

        self._setup_window()
        self._build_ui()
        self.load_all_verifications()

    def _setup_window(self):
        desc = self.device_data.get("description", "Dispositivo")
        serial = self.device_data.get("serial_number", "N/D") or "N/D"
        self.setWindowTitle(f"Storico Verifiche — {desc.upper()} (S/N: {serial})")
        self.resize(1100, 700)
        self.setMinimumSize(900, 550)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Scheda Informativa Dispositivo (Banner)
        header_group = QGroupBox("Dettagli Dispositivo")
        header_group.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; "
            "border-radius: 8px; margin-top: 6px; padding-top: 10px; background: #f8fafc; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }"
        )
        header_layout = QVBoxLayout(header_group)
        header_layout.setSpacing(8)

        # Titolo dispositivo principale
        desc = self.device_data.get("description", "Dispositivo")
        manu = self.device_data.get("manufacturer", "—") or "—"
        model = self.device_data.get("model", "—") or "—"
        serial = self.device_data.get("serial_number", "—") or "—"
        inv_ams = self.device_data.get("ams_inventory", "—") or "—"
        inv_cust = self.device_data.get("customer_inventory", "—") or "—"
        dept = self.device_data.get("department", "—") or "—"
        cust_name = self.cust_data.get("name", "—") or "—"
        dest_name = self.dest_data.get("name", "—") or "—"

        top_row = QHBoxLayout()
        title_label = QLabel(f"<span style='font-size: 14pt; font-weight: bold; color: #0f172a;'>{desc}</span>")
        top_row.addWidget(title_label)
        top_row.addStretch()

        # Pills riassuntivi verifiche
        self.summary_badge_label = QLabel("Caricamento...")
        self.summary_badge_label.setStyleSheet(
            "background: #e0f2fe; color: #0369a1; font-weight: bold; "
            "padding: 4px 12px; border-radius: 12px; border: 1px solid #bae6fd;"
        )
        top_row.addWidget(self.summary_badge_label)
        header_layout.addLayout(top_row)

        # Griglia dettagli
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(4)

        def make_field(label: str, value: str):
            lbl = QLabel(f"<span style='color:#64748b; font-weight:600;'>{label}:</span> <b>{value}</b>")
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return lbl

        grid.addWidget(make_field("🏢 Cliente", cust_name), 0, 0)
        grid.addWidget(make_field("📍 Destinazione", dest_name), 0, 1)
        grid.addWidget(make_field("🏥 Reparto", dept), 0, 2)

        grid.addWidget(make_field("🏭 Costruttore", manu), 1, 0)
        grid.addWidget(make_field("🏷️ Modello", model), 1, 1)
        grid.addWidget(make_field("🔢 Matricola (S/N)", serial), 1, 2)

        grid.addWidget(make_field("🗂️ Inv. AMS", inv_ams), 2, 0)
        grid.addWidget(make_field("📋 Inv. Cliente", inv_cust), 2, 1)

        header_layout.addLayout(grid)
        main_layout.addWidget(header_group)

        # 2. Barra di Ricerca Veloce
        search_layout = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Cerca per data, esito, tecnico, codice verifica, note...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumHeight(32)
        self.search_box.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_box)

        self.btn_refresh = QPushButton("🔄 Aggiorna")
        self.btn_refresh.setMinimumHeight(32)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.load_all_verifications)
        search_layout.addWidget(self.btn_refresh)

        main_layout.addLayout(search_layout)

        # 3. Tab Widget con le diverse tipologie di verifica
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabBar::tab { font-size: 12px; font-weight: bold; padding: 8px 18px; "
            "border-top-left-radius: 6px; border-top-right-radius: 6px; } "
            "QTabBar::tab:selected { background: #1e3a5f; color: white; }"
        )
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Tab 1: Verifiche Elettriche
        self.tab_electrical = QWidget()
        lay_elec = QVBoxLayout(self.tab_electrical)
        lay_elec.setContentsMargins(0, 8, 0, 0)
        self.table_electrical = QTableWidget(0, 8)
        self.table_electrical.setHorizontalHeaderLabels([
            "ID", "Data Verifica", "Esito", "Profilo di Test", "Tecnico", "Codice Verifica", "Strumento MTI", "S/N Strumento"
        ])
        self._setup_table(self.table_electrical)
        self.table_electrical.itemSelectionChanged.connect(self._update_action_buttons)
        self.table_electrical.itemDoubleClicked.connect(lambda: self._view_selected_verification())
        lay_elec.addWidget(self.table_electrical)
        self.tabs.addTab(self.tab_electrical, "⚡ Verifiche Elettriche")

        # Tab 2: Verifiche Funzionali
        self.tab_functional = QWidget()
        lay_func = QVBoxLayout(self.tab_functional)
        lay_func.setContentsMargins(0, 8, 0, 0)
        self.table_functional = QTableWidget(0, 7)
        self.table_functional.setHorizontalHeaderLabels([
            "ID", "Data Verifica", "Esito", "Profilo Funzionale", "Tecnico", "Codice Verifica", "Note"
        ])
        self._setup_table(self.table_functional)
        self.table_functional.itemSelectionChanged.connect(self._update_action_buttons)
        self.table_functional.itemDoubleClicked.connect(lambda: self._view_selected_verification())
        lay_func.addWidget(self.table_functional)
        self.tabs.addTab(self.tab_functional, "🩺 Verifiche Funzionali")

        # Tab 3: CQ Sonde Ecografo
        self.tab_ecografo = QWidget()
        lay_eco = QVBoxLayout(self.tab_ecografo)
        lay_eco.setContentsMargins(0, 8, 0, 0)
        self.table_ecografo = QTableWidget(0, 7)
        self.table_ecografo.setHorizontalHeaderLabels([
            "ID", "Data Verifica", "Esito", "Tecnico", "Codice Verifica", "N. Sonde", "Note"
        ])
        self._setup_table(self.table_ecografo)
        self.table_ecografo.itemSelectionChanged.connect(self._update_action_buttons)
        self.table_ecografo.itemDoubleClicked.connect(lambda: self._view_selected_verification())
        lay_eco.addWidget(self.table_ecografo)
        self.tabs.addTab(self.tab_ecografo, "📡 CQ Sonde Ecografo")

        # Tab 4: Verifiche di Sistema
        self.tab_system = QWidget()
        lay_sys = QVBoxLayout(self.tab_system)
        lay_sys.setContentsMargins(0, 8, 0, 0)
        self.table_system = QTableWidget(0, 6)
        self.table_system.setHorizontalHeaderLabels([
            "ID", "Data Verifica", "Esito", "Nome Sistema", "Profilo", "Codice Verifica"
        ])
        self._setup_table(self.table_system)
        self.table_system.itemSelectionChanged.connect(self._update_action_buttons)
        self.table_system.itemDoubleClicked.connect(lambda: self._view_selected_verification())
        lay_sys.addWidget(self.table_system)
        self.tabs.addTab(self.tab_system, "🔗 Verifiche di Sistema")

        main_layout.addWidget(self.tabs, 1)

        # 4. Barra Azioni Inferiore
        action_card = QWidget()
        action_card.setStyleSheet(
            "background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 6px;"
        )
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(12, 6, 12, 6)
        action_layout.setSpacing(10)

        self.btn_view = QPushButton("👁️ Visualizza Dettagli")
        self.btn_view.setObjectName("editButton")
        self.btn_view.setMinimumHeight(36)
        self.btn_view.setCursor(Qt.PointingHandCursor)
        self.btn_view.clicked.connect(self._view_selected_verification)
        self.btn_view.setEnabled(False)
        action_layout.addWidget(self.btn_view)

        self.btn_pdf = QPushButton("📄 Genera PDF Report")
        self.btn_pdf.setObjectName("autoButton")
        self.btn_pdf.setMinimumHeight(36)
        self.btn_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_pdf.clicked.connect(self._generate_pdf_report)
        self.btn_pdf.setEnabled(False)
        action_layout.addWidget(self.btn_pdf)

        self.btn_print = QPushButton("🖨️ Stampa Report")
        self.btn_print.setObjectName("secondaryButton")
        self.btn_print.setMinimumHeight(36)
        self.btn_print.setCursor(Qt.PointingHandCursor)
        self.btn_print.clicked.connect(self._print_report)
        self.btn_print.setEnabled(False)
        action_layout.addWidget(self.btn_print)

        self.btn_edit = QPushButton("✏️ Modifica")
        self.btn_edit.setObjectName("editButton")
        self.btn_edit.setMinimumHeight(36)
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.clicked.connect(self._edit_selected_verification)
        self.btn_edit.setEnabled(False)
        action_layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton("🗑️ Elimina")
        self.btn_delete.setObjectName("deleteButton")
        self.btn_delete.setStyleSheet(
            "QPushButton { background-color: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; font-weight: bold; border-radius: 6px; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #fecaca; }"
            "QPushButton:disabled { background-color: #f1f5f9; color: #94a3b8; border-color: #e2e8f0; }"
        )
        self.btn_delete.setMinimumHeight(36)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self._delete_selected_verification)
        self.btn_delete.setEnabled(False)
        if self.user_role == 'technician':
            self.btn_delete.setVisible(False)
        action_layout.addWidget(self.btn_delete)

        action_layout.addStretch()

        self.btn_close = QPushButton("Chiudi")
        self.btn_close.setMinimumHeight(36)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet("padding: 6px 20px; font-size: 13px;")
        self.btn_close.clicked.connect(self.accept)
        action_layout.addWidget(self.btn_close)

        main_layout.addWidget(action_card)

    def _setup_table(self, table: QTableWidget):
        """Configura le proprietà visive e interattive di una tabella verifiche."""
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setSortingEnabled(True)

        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        header.setMinimumSectionSize(60)

        table.verticalHeader().setDefaultSectionSize(36)
        table.verticalHeader().setMinimumSectionSize(30)
        table.hideColumn(0)  # Nasconde colonna ID

    # ─── CARICAMENTO E FILTRAGGIO DATI ──────────────────────────────────────────

    def load_all_verifications(self):
        """Carica tutte le tipologie di verifiche dal database per questo apparecchio."""
        # 1. Verifiche Elettriche
        try:
            raw_elec = services.get_verifications_for_device(self.device_id) or []
            self._electrical_entries = []
            for v in raw_elec:
                p_key = v.get('profile_name', '')
                profile = config.PROFILES.get(p_key)
                p_name = profile.name if profile else p_key
                date_val = v.get('verification_date', '') or ''
                try:
                    sort_date = datetime.strptime(date_val, "%Y-%m-%d")
                except (ValueError, TypeError):
                    sort_date = datetime.min

                self._electrical_entries.append({
                    "id": v.get("id"),
                    "date": date_val,
                    "sort_date": sort_date,
                    "status": v.get("overall_status", ""),
                    "profile_display": p_name,
                    "technician": v.get("technician_name", ""),
                    "code": v.get("verification_code", ""),
                    "mti_instrument": v.get("mti_instrument", ""),
                    "mti_serial": v.get("mti_serial", ""),
                    "raw": v,
                    "type": "ELETTRICA"
                })
            self._electrical_entries.sort(key=lambda e: (e["sort_date"], e["id"] or 0), reverse=True)
        except Exception as e:
            logging.error(f"Errore caricamento verifiche elettriche: {e}", exc_info=True)
            self._electrical_entries = []

        # 2. Verifiche Funzionali
        try:
            raw_func = services.get_functional_verifications_for_device(self.device_id) or []
            self._functional_entries = []
            for v in raw_func:
                p_key = v.get('profile_key', '')
                profile = config.FUNCTIONAL_PROFILES.get(p_key)
                p_name = profile.name if profile else p_key
                date_val = v.get('verification_date', '') or ''
                try:
                    sort_date = datetime.strptime(date_val, "%Y-%m-%d")
                except (ValueError, TypeError):
                    sort_date = datetime.min

                self._functional_entries.append({
                    "id": v.get("id"),
                    "date": date_val,
                    "sort_date": sort_date,
                    "status": v.get("overall_status", ""),
                    "profile_display": p_name,
                    "technician": v.get("technician_name", ""),
                    "code": v.get("verification_code", ""),
                    "notes": v.get("notes", "") or "",
                    "raw": v,
                    "type": "FUNZIONALE"
                })
            self._functional_entries.sort(key=lambda e: (e["sort_date"], e["id"] or 0), reverse=True)
        except Exception as e:
            logging.error(f"Errore caricamento verifiche funzionali: {e}", exc_info=True)
            self._functional_entries = []

        # 3. Controllo Qualità Sonde Ecografo
        try:
            raw_eco = database.get_ecografo_quality_checks_for_device(self.device_id) or []
            self._ecografo_entries = []
            for v in raw_eco:
                check_id = v.get("id")
                full_check = database.get_ecografo_quality_check(check_id) if check_id else None
                num_probes = len(full_check.probes) if full_check else 0
                date_val = v.get('verification_date', '') or ''
                try:
                    sort_date = datetime.strptime(date_val, "%Y-%m-%d")
                except (ValueError, TypeError):
                    sort_date = datetime.min

                self._ecografo_entries.append({
                    "id": v.get("id"),
                    "date": date_val,
                    "sort_date": sort_date,
                    "status": v.get("overall_status", "CONFORME"),
                    "technician": v.get("technician_name", ""),
                    "code": v.get("verification_code", ""),
                    "num_probes": num_probes,
                    "notes": v.get("notes", "") or "",
                    "raw": v,
                    "full_check": full_check,
                    "type": "ECOGRAFO_CQ"
                })
            self._ecografo_entries.sort(key=lambda e: (e["sort_date"], e["id"] or 0), reverse=True)
        except Exception as e:
            logging.error(f"Errore caricamento CQ sonde ecografo: {e}", exc_info=True)
            self._ecografo_entries = []

        # 4. Verifiche di Sistema
        try:
            raw_sys = services.get_system_verifications_for_device(self.device_id) or []
            self._system_entries = []
            for v in raw_sys:
                date_val = v.get('verification_date', '') or ''
                try:
                    sort_date = datetime.strptime(date_val, "%Y-%m-%d")
                except (ValueError, TypeError):
                    sort_date = datetime.min

                self._system_entries.append({
                    "id": v.get("id"),
                    "date": date_val,
                    "sort_date": sort_date,
                    "status": v.get("overall_status", ""),
                    "system_name": v.get("system_name", ""),
                    "profile_name": v.get("profile_name", ""),
                    "code": v.get("verification_code", ""),
                    "raw": v,
                    "type": "SISTEMA"
                })
            self._system_entries.sort(key=lambda e: (e["sort_date"], e["id"] or 0), reverse=True)
        except Exception as e:
            logging.error(f"Errore caricamento verifiche di sistema: {e}", exc_info=True)
            self._system_entries = []

        # Aggiorna titoli tab e badge riassuntivo
        n_elec = len(self._electrical_entries)
        n_func = len(self._functional_entries)
        n_eco = len(self._ecografo_entries)
        n_sys = len(self._system_entries)
        n_tot = n_elec + n_func + n_eco + n_sys

        self.tabs.setTabText(0, f"⚡ Verifiche Elettriche ({n_elec})")
        self.tabs.setTabText(1, f"🩺 Verifiche Funzionali ({n_func})")
        self.tabs.setTabText(2, f"📡 CQ Sonde Ecografo ({n_eco})")
        self.tabs.setTabText(3, f"🔗 Verifiche di Sistema ({n_sys})")

        self.summary_badge_label.setText(
            f"Totale Verifiche: {n_tot}  (⚡ {n_elec} | 🩺 {n_func} | 📡 {n_eco} | 🔗 {n_sys})"
        )

        self._render_tables()

    def _render_tables(self):
        query = (self.search_box.text() or "").strip().lower()

        # 1. Popola Verifiche Elettriche
        self.table_electrical.setSortingEnabled(False)
        self.table_electrical.setRowCount(0)
        for entry in self._electrical_entries:
            if query and not self._matches_query(entry, query, ["date", "status", "profile_display", "technician", "code", "mti_instrument"]):
                continue
            row = self.table_electrical.rowCount()
            self.table_electrical.insertRow(row)

            id_item = NumericTableWidgetItem(str(entry.get("id", "")))
            id_item.setData(Qt.UserRole, entry)
            self.table_electrical.setItem(row, 0, id_item)
            self.table_electrical.setItem(row, 1, QTableWidgetItem(entry.get("date", "")))

            status_item = self._create_status_item(entry.get("status", ""))
            self.table_electrical.setItem(row, 2, status_item)

            self.table_electrical.setItem(row, 3, QTableWidgetItem(entry.get("profile_display", "")))
            self.table_electrical.setItem(row, 4, QTableWidgetItem(entry.get("technician", "")))
            self.table_electrical.setItem(row, 5, QTableWidgetItem(entry.get("code", "")))
            self.table_electrical.setItem(row, 6, QTableWidgetItem(entry.get("mti_instrument", "")))
            self.table_electrical.setItem(row, 7, QTableWidgetItem(entry.get("mti_serial", "")))

        self._center_table_items(self.table_electrical)
        self.table_electrical.setSortingEnabled(True)

        # 2. Popola Verifiche Funzionali
        self.table_functional.setSortingEnabled(False)
        self.table_functional.setRowCount(0)
        for entry in self._functional_entries:
            if query and not self._matches_query(entry, query, ["date", "status", "profile_display", "technician", "code", "notes"]):
                continue
            row = self.table_functional.rowCount()
            self.table_functional.insertRow(row)

            id_item = NumericTableWidgetItem(str(entry.get("id", "")))
            id_item.setData(Qt.UserRole, entry)
            self.table_functional.setItem(row, 0, id_item)
            self.table_functional.setItem(row, 1, QTableWidgetItem(entry.get("date", "")))

            status_item = self._create_status_item(entry.get("status", ""))
            self.table_functional.setItem(row, 2, status_item)

            self.table_functional.setItem(row, 3, QTableWidgetItem(entry.get("profile_display", "")))
            self.table_functional.setItem(row, 4, QTableWidgetItem(entry.get("technician", "")))
            self.table_functional.setItem(row, 5, QTableWidgetItem(entry.get("code", "")))
            self.table_functional.setItem(row, 6, QTableWidgetItem(entry.get("notes", "")))

        self._center_table_items(self.table_functional)
        self.table_functional.setSortingEnabled(True)

        # 3. Popola CQ Sonde Ecografo
        self.table_ecografo.setSortingEnabled(False)
        self.table_ecografo.setRowCount(0)
        for entry in self._ecografo_entries:
            if query and not self._matches_query(entry, query, ["date", "status", "technician", "code", "notes"]):
                continue
            row = self.table_ecografo.rowCount()
            self.table_ecografo.insertRow(row)

            id_item = NumericTableWidgetItem(str(entry.get("id", "")))
            id_item.setData(Qt.UserRole, entry)
            self.table_ecografo.setItem(row, 0, id_item)
            self.table_ecografo.setItem(row, 1, QTableWidgetItem(entry.get("date", "")))

            status_item = self._create_status_item(entry.get("status", ""))
            self.table_ecografo.setItem(row, 2, status_item)

            self.table_ecografo.setItem(row, 3, QTableWidgetItem(entry.get("technician", "")))
            self.table_ecografo.setItem(row, 4, QTableWidgetItem(entry.get("code", "")))
            self.table_ecografo.setItem(row, 5, NumericTableWidgetItem(str(entry.get("num_probes", 0))))
            self.table_ecografo.setItem(row, 6, QTableWidgetItem(entry.get("notes", "")))

        self._center_table_items(self.table_ecografo)
        self.table_ecografo.setSortingEnabled(True)

        # 4. Popola Verifiche di Sistema
        self.table_system.setSortingEnabled(False)
        self.table_system.setRowCount(0)
        for entry in self._system_entries:
            if query and not self._matches_query(entry, query, ["date", "status", "system_name", "profile_name", "code"]):
                continue
            row = self.table_system.rowCount()
            self.table_system.insertRow(row)

            id_item = NumericTableWidgetItem(str(entry.get("id", "")))
            id_item.setData(Qt.UserRole, entry)
            self.table_system.setItem(row, 0, id_item)
            self.table_system.setItem(row, 1, QTableWidgetItem(entry.get("date", "")))

            status_item = self._create_status_item(entry.get("status", ""))
            self.table_system.setItem(row, 2, status_item)

            self.table_system.setItem(row, 3, QTableWidgetItem(entry.get("system_name", "")))
            self.table_system.setItem(row, 4, QTableWidgetItem(entry.get("profile_name", "")))
            self.table_system.setItem(row, 5, QTableWidgetItem(entry.get("code", "")))

        self._center_table_items(self.table_system)
        self.table_system.setSortingEnabled(True)

        self._update_action_buttons()

    def _matches_query(self, entry: Dict[str, Any], query: str, fields: List[str]) -> bool:
        for f in fields:
            val = str(entry.get(f, "") or "").lower()
            if query in val:
                return True
        return False

    def _create_status_item(self, status: str) -> QTableWidgetItem:
        status_up = (status or "").upper().strip()
        item = QTableWidgetItem(status_up or "N/D")
        if status_up in ("PASSATO", "CONFORME"):
            item.setBackground(QColor("#A3BE8C"))  # Verde morbido
            item.setForeground(QColor("#1e3a5f"))
        elif status_up in ("CONFORME CON ANNOTAZIONE", "PARZIALE", "SUFFICIENTE"):
            item.setBackground(QColor("#EBCB8B"))  # Giallo / ocra
            item.setForeground(QColor("#1e3a5f"))
        elif status_up in ("NON CONFORME", "FALLITO", "INSUFFICIENTE", "NON SUFFICIENTE"):
            item.setBackground(QColor("#BF616A"))  # Rosso morbido
            item.setForeground(QColor("#ffffff"))
        return item

    def _center_table_items(self, table: QTableWidget):
        centered = Qt.AlignCenter | Qt.AlignVCenter
        for row in range(table.rowCount()):
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item is not None:
                    item.setTextAlignment(centered)

    def _on_search_changed(self):
        self._render_tables()

    def _on_tab_changed(self, _index: int):
        self._update_action_buttons()

    # ─── GESTIONE SELEZIONE ED AZIONI ──────────────────────────────────────────

    def _get_current_table(self) -> Optional[QTableWidget]:
        idx = self.tabs.currentIndex()
        if idx == 0:
            return self.table_electrical
        elif idx == 1:
            return self.table_functional
        elif idx == 2:
            return self.table_ecografo
        elif idx == 3:
            return self.table_system
        return None

    def _get_selected_entry(self) -> Optional[Dict[str, Any]]:
        table = self._get_current_table()
        if not table:
            return None
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        id_item = table.item(row, 0)
        return id_item.data(Qt.UserRole) if id_item else None

    def _update_action_buttons(self):
        if not hasattr(self, 'btn_view'):
            return
        entry = self._get_selected_entry()
        has_sel = entry is not None
        v_type = entry.get("type") if entry else None

        self.btn_view.setEnabled(has_sel)
        self.btn_pdf.setEnabled(has_sel)
        self.btn_print.setEnabled(has_sel and v_type in ("ELETTRICA", "FUNZIONALE", "ECOGRAFO_CQ"))
        self.btn_edit.setEnabled(has_sel and v_type in ("ELETTRICA", "FUNZIONALE", "ECOGRAFO_CQ"))
        self.btn_delete.setEnabled(has_sel and self.user_role != 'technician')

    def _view_selected_verification(self):
        entry = self._get_selected_entry()
        if not entry:
            return

        v_type = entry.get("type")
        v_id = entry.get("id")

        try:
            if v_type == "ELETTRICA":
                verifs = services.get_verifications_for_device(self.device_id)
                verif_data = next((v for v in verifs if v.get('id') == v_id), entry.get("raw"))
                if verif_data:
                    dlg = VerificationViewerDialog(verif_data, parent=self)
                    dlg.exec()
                else:
                    QMessageBox.warning(self, "Attenzione", "Impossibile recuperare i dati completi della verifica.")

            elif v_type == "FUNZIONALE":
                verifs = services.get_functional_verifications_for_device(self.device_id)
                verif_data = next((v for v in verifs if v.get('id') == v_id), entry.get("raw"))
                if verif_data:
                    dlg = FunctionalVerificationViewerDialog(verif_data, parent=self)
                    dlg.exec()
                else:
                    QMessageBox.warning(self, "Attenzione", "Impossibile recuperare i dati completi della verifica funzionale.")

            elif v_type == "ECOGRAFO_CQ":
                full_check = database.get_ecografo_quality_check(v_id)
                if full_check:
                    dlg = EcografoQualityDialog(
                        device_info=self.device_data,
                        check=full_check,
                        parent=self
                    )
                    dlg.exec()
                    self.load_all_verifications()
                else:
                    QMessageBox.warning(self, "Attenzione", "Impossibile recuperare il controllo qualità sonde.")

            elif v_type == "SISTEMA":
                from app.ui.dialogs.system_verification_dialogs import SystemVerificationViewDialog
                sv_data = database.get_system_verification_by_id(v_id)
                if sv_data:
                    dlg = SystemVerificationViewDialog(sv_data, parent=self)
                    dlg.exec()
                else:
                    QMessageBox.warning(self, "Attenzione", "Impossibile recuperare la verifica di sistema.")

        except Exception as e:
            logging.error(f"Errore visualizzazione dettagli verifica: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore durante l'apertura dei dettagli:\n{e}")

    def _generate_pdf_report(self):
        entry = self._get_selected_entry()
        if not entry:
            return

        v_type = entry.get("type")
        v_id = entry.get("id")

        ams_inv = (self.device_data.get('ams_inventory') or '').strip()
        serial_num = (self.device_data.get('serial_number') or '').strip()
        verification_code = entry.get("code") or ""

        if ams_inv:
            base_name = ams_inv
        elif serial_num:
            base_name = serial_num
        elif verification_code:
            base_name = verification_code
        else:
            base_name = f"Report_Verifica_{v_id}"

        safe_base_name = re.sub(r'[\\/*?:"<>|]', '_', base_name)

        if v_type == "ELETTRICA":
            default_filename = f"{safe_base_name} VE.pdf"
        elif v_type == "FUNZIONALE":
            default_filename = f"{safe_base_name} VF.pdf"
        elif v_type == "ECOGRAFO_CQ":
            default_filename = f"{safe_base_name} CQ.pdf"
        else:
            default_filename = f"{safe_base_name} VS.pdf"

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Salva Report PDF",
            default_filename,
            "PDF Files (*.pdf)"
        )
        if not filename:
            return

        try:
            logo_path = getattr(self.main_window, "logo_path", None)
            report_settings = {"logo_path": logo_path} if logo_path else {}

            if v_type == "ELETTRICA":
                services.generate_pdf_report(filename, v_id, self.device_id, report_settings)
            elif v_type == "FUNZIONALE":
                services.generate_functional_pdf_report(filename, v_id, self.device_id, report_settings)
            elif v_type == "ECOGRAFO_CQ":
                from report_generator import create_ecografo_quality_report
                check = database.get_ecografo_quality_check(v_id)
                check_info = database.get_ecografo_quality_check_with_device_info(v_id)
                signature_data = database.get_signature_by_username(check.technician_username or "") if check else None
                create_ecografo_quality_report(
                    filename=filename,
                    check=check,
                    device_info=self.device_data,
                    destination_info=self.dest_data,
                    customer_info=self.cust_data,
                    signature_data=signature_data,
                    report_settings=report_settings
                )
            elif v_type == "SISTEMA":
                services.generate_system_verification_pdf(filename, v_id, report_settings)

            QMessageBox.information(self, "PDF Generato", f"Report PDF salvato con successo:\n{filename}")
        except Exception as e:
            logging.error(f"Errore generazione report PDF: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore PDF", f"Impossibile generare il report PDF:\n{e}")

    def _print_report(self):
        entry = self._get_selected_entry()
        if not entry:
            return

        v_type = entry.get("type")
        v_id = entry.get("id")

        try:
            logo_path = getattr(self.main_window, "logo_path", None)
            report_settings = {"logo_path": logo_path} if logo_path else {}

            if v_type == "ELETTRICA":
                services.print_pdf_report(v_id, self.device_id, report_settings, parent_widget=self)
            elif v_type == "FUNZIONALE":
                services.print_functional_pdf_report(v_id, self.device_id, report_settings, parent_widget=self)
            elif v_type == "ECOGRAFO_CQ":
                # Stampa temporanea per ecografo
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    temp_pdf_path = tmp.name
                from report_generator import create_ecografo_quality_report
                check = database.get_ecografo_quality_check(v_id)
                signature_data = database.get_signature_by_username(check.technician_username or "") if check else None
                create_ecografo_quality_report(
                    filename=temp_pdf_path,
                    check=check,
                    device_info=self.device_data,
                    destination_info=self.dest_data,
                    customer_info=self.cust_data,
                    signature_data=signature_data,
                    report_settings=report_settings
                )
                from app.utils.printer import print_pdf_file
                print_pdf_file(temp_pdf_path, parent=self)
            else:
                QMessageBox.information(self, "Info", "Funzione di stampa diretta non disponibile per questa tipologia.")
        except Exception as e:
            logging.error(f"Errore durante la stampa: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore Stampa", f"Impossibile avviare la stampa del report:\n{e}")

    def _edit_selected_verification(self):
        entry = self._get_selected_entry()
        if not entry:
            return

        v_type = entry.get("type")
        v_id = entry.get("id")

        try:
            if v_type == "ECOGRAFO_CQ":
                full_check = database.get_ecografo_quality_check(v_id)
                if full_check:
                    dlg = EcografoQualityDialog(
                        device_info=self.device_data,
                        check=full_check,
                        parent=self
                    )
                    if dlg.exec() == QDialog.Accepted:
                        # Salva modifiche
                        timestamp = datetime.utcnow().isoformat()
                        database.save_ecografo_quality_check(dlg.get_check(), timestamp=timestamp)
                        QMessageBox.information(self, "Successo", "Controllo qualità sonde aggiornato con successo.")
                        self.load_all_verifications()
                return

            # Per verifiche elettriche e funzionali
            if v_type == "FUNZIONALE":
                verifs = services.get_functional_verifications_for_device(self.device_id)
                verif_data = next((v for v in verifs if v.get('id') == v_id), entry.get("raw"))
            else:
                verifs = services.get_verifications_for_device(self.device_id)
                verif_data = next((v for v in verifs if v.get('id') == v_id), entry.get("raw"))

            if not verif_data:
                QMessageBox.critical(self, "Errore", "Impossibile trovare i dati completi della verifica.")
                return

            dialog = EditVerificationDialog(verif_data, v_type, self)
            if dialog.exec() != QDialog.Accepted:
                return

            new_data = dialog.get_data()
            if v_type == "FUNZIONALE":
                updated = services.update_functional_verification(
                    v_id,
                    new_data['verification_date'],
                    new_data['overall_status'],
                    new_data['technician_name'],
                    new_data.get('notes', ''),
                    results=None,
                    structured_results=new_data.get('structured_results'),
                    mti_instrument=new_data.get('mti_instrument'),
                    mti_serial=new_data.get('mti_serial'),
                    mti_version=new_data.get('mti_version'),
                    mti_cal_date=new_data.get('mti_cal_date'),
                )
            else:
                updated = services.update_verification(
                    v_id,
                    new_data['verification_date'],
                    new_data['overall_status'],
                    new_data['technician_name'],
                    results=new_data.get('results'),
                    visual_inspection_data=new_data.get('visual_inspection'),
                    mti_instrument=new_data.get('mti_instrument'),
                    mti_serial=new_data.get('mti_serial'),
                    mti_version=new_data.get('mti_version'),
                    mti_cal_date=new_data.get('mti_cal_date'),
                )

            if updated:
                QMessageBox.information(self, "Successo", "Verifica aggiornata con successo.")
                self.load_all_verifications()
            else:
                QMessageBox.warning(self, "Attenzione", "Nessuna modifica effettuata.")

        except Exception as e:
            logging.error(f"Errore durante la modifica della verifica: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile aggiornare la verifica:\n{e}")

    def _delete_selected_verification(self):
        entry = self._get_selected_entry()
        if not entry:
            return

        v_type = entry.get("type")
        v_id = entry.get("id")
        code = entry.get("code") or f"ID {v_id}"

        reply = QMessageBox.question(
            self,
            "Conferma Eliminazione",
            f"Sei sicuro di voler eliminare la verifica {v_type} '{code}'?\nL'operazione non è reversibile dal client.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            deleted = False
            if v_type == "ELETTRICA":
                deleted = services.delete_verification(v_id)
            elif v_type == "FUNZIONALE":
                deleted = services.delete_functional_verification(v_id)
            elif v_type == "ECOGRAFO_CQ":
                deleted = services.delete_ecografo_quality_check(v_id)
            elif v_type == "SISTEMA":
                deleted = services.delete_system_verification(v_id)

            if deleted:
                QMessageBox.information(self, "Eliminato", "Verifica eliminata con successo.")
                self.load_all_verifications()
            else:
                QMessageBox.critical(self, "Errore", "Impossibile eliminare la verifica selezionata.")
        except Exception as e:
            logging.error(f"Errore durante l'eliminazione della verifica: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile eliminare la verifica:\n{e}")
