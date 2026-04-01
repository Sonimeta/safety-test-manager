# app/ui/dialogs/manager_dialogs.py

import logging
from datetime import datetime
import pandas as pd
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QLineEdit, QLabel, QPushButton,
    QHeaderView, QAbstractItemView, QStyle, QMessageBox, QFileDialog, QProgressDialog, QFrame,
    QStyledItemDelegate
)
from PySide6.QtCore import Qt, QThread, QSize, QSettings, QTimer
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QPainter
import re
import os

from app import services, auth_manager, config  # Import config
from .detail_dialogs import CustomerDialog, DeviceDialog, InstrumentDetailDialog
from .utility_dialogs import (DateRangeSelectionDialog, VerificationStatusDialog, MonthYearSelectionDialog,
                              MappingDialog, ImportReportDialog, VerificationViewerDialog, FunctionalVerificationViewerDialog,
                              DateSelectionDialog, DestinationDetailDialog, DestinationSelectionDialog, SingleCalendarRangeDialog,
                              GlobalSearchDialog, ReportNamingFormatDialog, EditVerificationDialog)
from app.workers.import_worker import ImportWorker
from app.workers.stm_import_worker import StmImportWorker
from app.workers.export_worker import DailyExportWorker
from app.workers.bulk_report_worker import BulkReportWorker
from app.workers.table_export_worker import TableExportWorker
import database


class NumericTableWidgetItem(QTableWidgetItem):
    """Un QTableWidgetItem personalizzato che si ordina numericamente."""
    def __lt__(self, other):
        try:
            return float(self.text()) < float(other.text())
        except (ValueError, TypeError):
            return super().__lt__(other)


class ColoredItemDelegate(QStyledItemDelegate):
    """Delegate che applica i colori personalizzati ignorando gli stili QSS."""
    def paint(self, painter, option, index):
        # Controlla se c'è un colore personalizzato (prova prima il ruolo personalizzato, poi ForegroundRole)
        custom_color = None
        
        # Prova prima dal ruolo personalizzato (più affidabile)
        color_name = index.data(Qt.UserRole + 1)
        if color_name:
            try:
                custom_color = QColor(color_name)
            except:
                pass
        
        # Fallback: prova dal ForegroundRole
        if not custom_color:
            foreground_brush = index.data(Qt.ForegroundRole)
            if foreground_brush and isinstance(foreground_brush, QBrush):
                custom_color = foreground_brush.color()
        
        # Se c'è un colore personalizzato, disegna manualmente (necessario per ignorare QSS)
        if custom_color and custom_color.isValid():
            # Disegna lo sfondo (usa il rendering standard per lo sfondo che è veloce)
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, option.palette.highlight())
            elif option.state & QStyle.State_MouseOver:
                painter.fillRect(option.rect, option.palette.midlight())
            else:
                # Sfondo alternato solo se necessario (ottimizzazione)
                if index.row() % 2 == 1:
                    painter.fillRect(option.rect, option.palette.alternateBase())
            
            # Disegna il testo con il colore personalizzato (solo questa parte è necessaria)
            text = index.data(Qt.DisplayRole) or ""
            if text:  # Solo se c'è testo da disegnare
                painter.setPen(custom_color)
                # Centra il testo e rispetta eventuale allineamento esplicito dell'item
                alignment = index.data(Qt.TextAlignmentRole)
                if alignment is None:
                    alignment = Qt.AlignCenter | Qt.AlignVCenter
                painter.drawText(option.rect.adjusted(8, 0, -8, 0), int(alignment), str(text))
        else:
            # Nessun colore personalizzato, usa il rendering standard (veloce)
            super().paint(painter, option, index)


class DbManagerDialog(QDialog):
    def __init__(self, role, parent=None):
        super().__init__(parent)
        # Abilita il maiuscolo automatico per questa finestra
        self.setProperty("_stm_uppercase_window", True)
        self.main_window = parent
        self._pending_navigation_data = None # Nuovo attributo per memorizzare i dati di navigazione
        self.user_role = role
        self.setWindowTitle("GESTIONE ANAGRAFICHE")
        self.resize(1400, 850)
        self._navigate_on_load_item = None
        
        # Applica il tema corrente dalla main window o usa quello di default
        if parent and hasattr(parent, 'current_theme'):
            theme = parent.current_theme
        else:
            settings = QSettings("ELSON META", "SafetyTester")
            theme = settings.value("theme", "light")
        self.setStyleSheet(config.get_theme_stylesheet(theme))
        
        self.setup_ui()
        self.load_customers_table()

    def showEvent(self, event):
        """
        Override showEvent per eseguire la navigazione dopo che la dialog è stata mostrata.
        """
        super().showEvent(event)
        if self._pending_navigation_data:
            self._perform_pending_navigation()

    def navigate_on_load(self, item_data):
        """
        Memorizza i dati di navigazione per essere elaborati dopo che la dialog è completamente caricata.
        """
        self._pending_navigation_data = item_data

    def _perform_pending_navigation(self):
        """
        Esegue la logica di navigazione memorizzata.
        """
        item_data = self._pending_navigation_data
        if not item_data:
            return

        if item_data.get('type') == 'customer':
            self.find_and_select_item(self.customer_table, item_data['id'])
            self.tabs.setCurrentWidget(self.customer_tab)
        elif item_data.get('type') == 'device':
            device_info = services.database.get_device_by_id(item_data['id'])
            if device_info:
                destination_info = services.database.get_destination_by_id(device_info['destination_id'])
                if destination_info:
                    self.find_and_select_item(self.customer_table, destination_info['customer_id'])
                    self.tabs.setCurrentWidget(self.destination_tab)
                    # Assicurati che i dati siano caricati prima di selezionare nella scheda successiva
                    QApplication.processEvents()
                    self.find_and_select_item(self.destination_table, device_info['destination_id'])
                    self.tabs.setCurrentWidget(self.device_tab)
                    QApplication.processEvents()
                    self.find_and_select_item(self.device_table, item_data['id'])
        elif item_data.get('type') == 'verification':
            device_id = item_data['device_id']
            verification_id = item_data['verification_id']
            
            device_info = services.database.get_device_by_id(device_id)
            if device_info:
                destination_info = services.database.get_destination_by_id(device_info['destination_id'])
                if destination_info:
                    self.find_and_select_item(self.customer_table, destination_info['customer_id'])
                    self.tabs.setCurrentWidget(self.destination_tab)
                    QApplication.processEvents()
                    self.find_and_select_item(self.destination_table, device_info['destination_id'])
                    self.tabs.setCurrentWidget(self.device_tab)
                    QApplication.processEvents()
                    self.find_and_select_item(self.device_table, device_id)
                    self.tabs.setCurrentWidget(self.verification_tab)
                    QApplication.processEvents()
                    self.find_and_select_verification(verification_id)
        
        self._pending_navigation_data = None # Cancella dopo l'elaborazione

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Header con titolo e informazioni
        header = self.create_header()
        main_layout.addWidget(header)

        # Barra delle azioni principali
        top_actions_layout = self.create_top_actions()
        main_layout.addLayout(top_actions_layout)

        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        main_layout.addWidget(self.tabs)

        self.setup_customer_tab()
        self.setup_destination_tab()
        self.setup_device_tab()
        self.setup_verification_tab()

        # Connessioni dei segnali
        self.customer_table.itemSelectionChanged.connect(self.customer_selected)
        self.destination_table.itemSelectionChanged.connect(self.destination_selected)
        self.device_table.itemSelectionChanged.connect(self.device_selected)
        self.customer_table.itemDoubleClicked.connect(self.navigate_to_destinations_tab)
        self.destination_table.itemDoubleClicked.connect(self.navigate_to_devices_tab)
        self.device_table.itemDoubleClicked.connect(self.navigate_to_verifications_tab)
        self.customer_search_box.textChanged.connect(self.load_customers_table)
        self.destination_search_box.textChanged.connect(self.customer_selected)
        self.device_search_box.textChanged.connect(self.destination_selected)
        self.verification_search_box.textChanged.connect(self.device_selected)
        
        self.reset_views(level='customer')

    def create_header(self):
        """Crea un header moderno per la finestra"""
        header_widget = QFrame()
        header_widget.setObjectName("headerFrame")
        # Gli stili sono gestiti dal QSS del tema
        
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(15, 10, 15, 10)
        
        # Titolo principale
        title_layout = QVBoxLayout()
        title = QLabel("📋 GESTIONE ANAGRAFICHE")
        title.setObjectName("headerTitle")
        title.setStyleSheet("border: none;")

        
        subtitle = QLabel("Sistema di gestione clienti, destinazioni e dispositivi")
        subtitle.setObjectName("headerSubtitle")
        subtitle.setStyleSheet("border: none; margin-top: 3px;")
        
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        header_layout.addLayout(title_layout)
        header_layout.addSpacing(20)

        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)
        self.global_device_search_box = QLineEdit()
        self.global_device_search_box.setPlaceholderText("🔎 Cerca cliente, destinazione o dispositivo...")
        self.global_device_search_box.setMinimumWidth(320)
        self.global_device_search_box.setClearButtonEnabled(True)
        self.global_device_search_box.returnPressed.connect(self.perform_header_device_search)

        search_button = QPushButton("Cerca")
        search_button.setObjectName("primaryButton")
        search_button.setMinimumWidth(110)
        search_button.clicked.connect(self.perform_header_device_search)

        search_layout.addWidget(self.global_device_search_box)
        search_layout.addWidget(search_button)

        header_layout.addLayout(search_layout)
        header_layout.addStretch()

        # Info utente
        ruolo = "AMMINISTRATORE" if self.user_role == "admin" else "TECNICO"
        user_info = QLabel(f"👤 {ruolo.upper()}")
        user_info.setObjectName("userInfoLabel")
        # Gli stili sono gestiti dal QSS del tema
        
        header_layout.addWidget(user_info)
        
        return header_widget

    def perform_header_device_search(self):
        """Ricerca rapida globale (clienti, destinazioni, dispositivi) e naviga tra le schede."""
        term = self.global_device_search_box.text().strip()
        if len(term) < 3:
            QMessageBox.information(self, "Ricerca", "Inserisci almeno 3 caratteri per avviare la ricerca.")
            return

        try:
            results = services.search_globally(term)
        except Exception as exc:
            logging.error("Errore durante la ricerca globale anagrafiche", exc_info=True)
            QMessageBox.critical(self, "Ricerca", f"Si è verificato un errore durante la ricerca:\n{exc}")
            return

        if not results:
            QMessageBox.information(self, "Ricerca", "Nessun risultato trovato per il criterio inserito.")
            return

        if len(results) == 1:
            selected_item = dict(results[0])
        else:
            chooser = GlobalSearchDialog(results, self)
            if chooser.exec() != QDialog.Accepted or not chooser.selected_item:
                return
            selected_item = chooser.selected_item

        self._handle_header_global_search_selection(selected_item)

    def _handle_header_global_search_selection(self, selected_item):
        """Instrada il risultato selezionato al navigatore corretto."""
        if not selected_item:
            return

        item = dict(selected_item)
        if 'serial_number' in item:
            self._navigate_to_device_from_global_search(item)
            return

        if 'customer_id' in item and 'customer_name' in item:
            self._navigate_to_destination_from_global_search(item)
            return

        self._navigate_to_customer_from_global_search(item)

    def _clear_local_search_filters(self):
        """Azzera i filtri locali delle tre tabelle prima della navigazione."""
        self.customer_search_box.blockSignals(True)
        self.customer_search_box.clear()
        self.customer_search_box.blockSignals(False)

        self.destination_search_box.blockSignals(True)
        self.destination_search_box.clear()
        self.destination_search_box.blockSignals(False)

        self.device_search_box.blockSignals(True)
        self.device_search_box.clear()
        self.device_search_box.blockSignals(False)

    def _navigate_to_customer_from_global_search(self, customer_data):
        if not customer_data:
            return

        customer = dict(customer_data)
        customer_id = customer.get('id')
        if not customer_id:
            QMessageBox.warning(self, "Navigazione", "Impossibile determinare il cliente selezionato.")
            return

        self._clear_local_search_filters()
        self.load_customers_table()
        QApplication.processEvents()

        self.find_and_select_item(self.customer_table, customer_id)
        QApplication.processEvents()
        self.customer_selected()
        self.tabs.setCurrentWidget(self.customer_tab)

    def _navigate_to_destination_from_global_search(self, destination_data):
        if not destination_data:
            return

        destination = dict(destination_data)
        destination_id = destination.get('id')
        customer_id = destination.get('customer_id')

        if not destination_id:
            QMessageBox.warning(self, "Navigazione", "Impossibile determinare la destinazione selezionata.")
            return

        if not customer_id:
            destination_info = services.database.get_destination_by_id(destination_id)
            if destination_info:
                customer_id = destination_info.get('customer_id')

        if not customer_id:
            QMessageBox.warning(self, "Navigazione", "Impossibile determinare il cliente associato alla destinazione.")
            return

        self._clear_local_search_filters()
        self.load_customers_table()
        QApplication.processEvents()

        self.find_and_select_item(self.customer_table, customer_id)
        QApplication.processEvents()
        self.customer_selected()

        self.tabs.setCurrentWidget(self.destination_tab)
        QApplication.processEvents()
        self.find_and_select_item(self.destination_table, destination_id)
        QApplication.processEvents()
        self.destination_selected()

    def _navigate_to_device_from_global_search(self, device_data):
        if not device_data:
            return

        device = dict(device_data)
        destination_id = device.get('destination_id')
        if not destination_id:
            QMessageBox.warning(self, "Navigazione", "Impossibile determinare la destinazione del dispositivo selezionato.")
            return

        destination_info = services.database.get_destination_by_id(destination_id)
        if not destination_info:
            QMessageBox.warning(self, "Navigazione", "Destinazione associata non trovata o rimossa.")
            return

        customer_id = destination_info['customer_id']

        # Assicura che le ricerche locali non filtrino i dati
        self._clear_local_search_filters()

        self.load_customers_table()
        QApplication.processEvents()

        self.find_and_select_item(self.customer_table, customer_id)
        QApplication.processEvents()
        self.customer_selected()

        self.tabs.setCurrentWidget(self.destination_tab)
        QApplication.processEvents()

        self.find_and_select_item(self.destination_table, destination_id)
        QApplication.processEvents()
        self.destination_selected()

        self.tabs.setCurrentWidget(self.device_tab)
        QApplication.processEvents()

        self.find_and_select_item(self.device_table, device.get('id'))
        QApplication.processEvents()
        self.device_selected()

    # --- Setup delle Schede (Tabs) ---
    def setup_customer_tab(self):
        self.customer_tab = QWidget()
        self.tabs.addTab(self.customer_tab, "👥 CLIENTI")
        layout = QVBoxLayout(self.customer_tab)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.customer_search_box = QLineEdit()
        self.customer_search_box.setPlaceholderText("🔍 Cerca cliente per nome, indirizzo, telefono o email...")
        
        self.customer_table = QTableWidget(0, 5)
        self.customer_table.setHorizontalHeaderLabels(["ID", "NOME", "INDIRIZZO", "TELEFONO", "EMAIL"])
        self.setup_table_style(self.customer_table)
        
        buttons_layout = self.create_customer_buttons()
        
        layout.addWidget(self.customer_search_box)
        layout.addWidget(self.customer_table)
        layout.addLayout(buttons_layout)

    def setup_destination_tab(self):
        self.destination_tab = QWidget()
        self.tabs.addTab(self.destination_tab, "📍 DESTINAZIONI")
        layout = QVBoxLayout(self.destination_tab)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.destination_label = QLabel("ℹ️ Seleziona un cliente dalla scheda precedente")
        self.destination_label.setStyleSheet("background-color: #f1f5f9; border-radius: 6px; padding: 8px; margin-bottom: 8px; font-weight: 600;")

        self.destination_search_box = QLineEdit()
        self.destination_search_box.setPlaceholderText("🔍 Cerca destinazione per nome o indirizzo...")
        
        self.destination_table = QTableWidget(0, 3)
        self.destination_table.setHorizontalHeaderLabels(["ID", "NOME", "INDIRIZZO"])
        self.setup_table_style(self.destination_table)
        
        buttons_layout = self.create_destination_buttons()
        
        layout.addWidget(self.destination_label)
        layout.addWidget(self.destination_search_box)
        layout.addWidget(self.destination_table)
        layout.addLayout(buttons_layout)
        
    def setup_device_tab(self):
        self.device_tab = QWidget()
        self.tabs.addTab(self.device_tab, "⚙️ DISPOSITIVI")
        layout = QVBoxLayout(self.device_tab)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.device_label = QLabel("ℹ️ Seleziona una destinazione dalla scheda precedente")
        self.device_label.setObjectName("sectionLabel")
        # Gli stili sono gestiti dal QSS del tema
        
        self.device_search_box = QLineEdit()
        self.device_search_box.setPlaceholderText("🔍 Cerca dispositivo per descrizione, S/N, costruttore, modello...")
        
        self.device_table = QTableWidget(0, 11)
        self.device_table.setObjectName("deviceTable")  # ObjectName per regole QSS specifiche
        self.device_table.setHorizontalHeaderLabels([
            "ID", "DESCRIZIONE", "REPARTO", "S/N", "COSTRUTTORE",
            "MODELLO", "INV. CLIENTE", "INV. AMS", "INT. VERIFICA", "STATO", "ULTIMA VERIFICA"
        ])
        # Imposta un delegate personalizzato per applicare i colori correttamente
        self.device_table.setItemDelegate(ColoredItemDelegate(self.device_table))
        self.setup_table_style(self.device_table)
        
        buttons_layout = self.create_device_buttons()
        
        layout.addWidget(self.device_label)
        layout.addWidget(self.device_search_box)
        layout.addWidget(self.device_table)
        layout.addLayout(buttons_layout)

    def setup_verification_tab(self):
        self.verification_tab = QWidget()
        self.tabs.addTab(self.verification_tab, "📊 VERIFICHE")
        layout = QVBoxLayout(self.verification_tab)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.verification_label = QLabel("ℹ️ Seleziona un dispositivo dalla scheda precedente")
        self.verification_label.setObjectName("sectionLabel")
        # Gli stili sono gestiti dal QSS del tema

        self.verification_search_box = QLineEdit()
        self.verification_search_box.setPlaceholderText("🔍 Cerca per data, tecnico, codice verifica...")
        
        tables_container = QHBoxLayout()
        tables_container.setSpacing(12)
        
        # Tabella verifiche elettriche
        electro_layout = QVBoxLayout()
        electro_layout.setSpacing(6)
        electro_label = QLabel("Verifiche Elettriche")
        electro_label.setStyleSheet("font-weight: 600;")
        electro_layout.addWidget(electro_label)
        self.electrical_table = QTableWidget(0, 6)
        self.electrical_table.setHorizontalHeaderLabels(["ID", "Data", "Esito", "Profilo", "Tecnico", "Codice"])
        self.setup_table_style(self.electrical_table, hide_id=False)
        self.electrical_table.itemSelectionChanged.connect(self.on_electrical_selection_changed)
        electro_layout.addWidget(self.electrical_table)
        tables_container.addLayout(electro_layout)
        
        # Tabella verifiche funzionali
        functional_layout = QVBoxLayout()
        functional_layout.setSpacing(6)
        functional_label = QLabel("Verifiche Funzionali")
        functional_label.setStyleSheet("font-weight: 600;")
        functional_layout.addWidget(functional_label)
        self.functional_table = QTableWidget(0, 6)
        self.functional_table.setHorizontalHeaderLabels(["ID", "Data", "Esito", "Profilo", "Tecnico", "Codice"])
        self.setup_table_style(self.functional_table, hide_id=False)
        self.functional_table.itemSelectionChanged.connect(self.on_functional_selection_changed)
        functional_layout.addWidget(self.functional_table)
        tables_container.addLayout(functional_layout)
        
        layout.addWidget(self.verification_label)
        layout.addWidget(self.verification_search_box)
        layout.addLayout(tables_container)
        layout.addLayout(self.create_verification_buttons())

    # --- Metodi per la Navigazione con Doppio Click ---
    def navigate_to_destinations_tab(self):
        if self.get_selected_id(self.customer_table) is not None:
            self.tabs.setCurrentWidget(self.destination_tab)

    def navigate_to_devices_tab(self):
        if self.get_selected_id(self.destination_table) is not None:
            self.tabs.setCurrentWidget(self.device_tab)

    def navigate_to_verifications_tab(self):
        if self.get_selected_id(self.device_table) is not None:
            self.tabs.setCurrentWidget(self.verification_tab)

    # --- METODI HELPER E CREAZIONE BOTTONI ---
    def setup_table_style(self, table, hide_id=True, stretch_last=True):
        """
        Configura lo stile della tabella per essere responsive e leggibile.
        
        Args:
            table: QTableWidget da configurare
            hide_id: Se nascondere la colonna ID (default True)
            stretch_last: Se estendere l'ultima colonna (default True)
        """
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        
        # Miglioramenti per scrollbar responsive
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        
        header = table.horizontalHeader()
        # Le colonne si adattano al contenuto
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(stretch_last)
        header.setDefaultAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        header.setMinimumSectionSize(50)  # Larghezza minima delle colonne
        header.setSortIndicatorShown(True)
        
        # Imposta altezza minima delle righe per leggibilità
        table.verticalHeader().setDefaultSectionSize(38)
        table.verticalHeader().setMinimumSectionSize(32)
        
        if hide_id:
            table.hideColumn(0)

    def _fit_table_columns(self, table: QTableWidget):
        """Adatta le colonne al contenuto dopo il popolamento dati."""
        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        # Mantieni allineamento leggibile e consenti scroll orizzontale se necessario
        table.horizontalHeader().setStretchLastSection(False)

    def _center_table_items(self, table: QTableWidget):
        """Centra il testo di tutte le celle valorizzate in tabella."""
        centered = Qt.AlignCenter | Qt.AlignVCenter
        for row in range(table.rowCount()):
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item is not None:
                    item.setTextAlignment(centered)

    def create_button(self, text, slot, button_type="primary", icon=None, enabled=True):
        btn = QPushButton(text.upper())
        btn.setObjectName(f"{button_type}Button")
        btn.setCursor(Qt.PointingHandCursor)
        
        if icon:
            btn.setIcon(QApplication.style().standardIcon(icon))
            btn.setIconSize(QSize(16, 16))
        
        btn.clicked.connect(slot)
        btn.setEnabled(enabled)
        return btn

    def create_top_actions(self):
        layout = QHBoxLayout()
        layout.setSpacing(12)
        
        layout.addWidget(self.create_button("⬆️ Importa Dispositivi", self.import_from_file, "autoButton"))
        layout.addWidget(self.create_button("📥 Importa Archivio", self.import_from_stm, "autoButton"))
        layout.addWidget(self.create_button("💾 Esporta Verifiche", self.export_daily_verifications, "secondaryButton"))
        
        layout.addStretch()

        # Pulsante Scanner QR (collegato alla MainWindow)
        self.qr_scanner_btn = QPushButton("📱 Scanner QR")
        self.qr_scanner_btn.setCursor(Qt.PointingHandCursor)
        self.qr_scanner_btn.setToolTip("Attiva/gestisci lo scanner QR per il telefono")
        self.qr_scanner_btn.clicked.connect(self._on_qr_scanner_clicked)
        self._update_qr_scanner_btn_style()
        layout.addWidget(self.qr_scanner_btn)
        
        layout.addWidget(self.create_button("📄 Genera Report", self.generate_monthly_reports, "editButton"))
        layout.addWidget(self.create_button("🔍 Filtra Periodo", self.open_period_filter_dialog, "secondaryButton"))
        
        return layout

    def _on_qr_scanner_clicked(self):
        """Gestisce il click sul pulsante QR Scanner nel dialog anagrafiche."""
        mw = self.main_window
        if not mw:
            return
        if hasattr(mw, 'qr_scanner_server_running') and mw.qr_scanner_server_running:
            # Server attivo: mostra menu
            from PySide6.QtWidgets import QMenu
            menu = QMenu(self)
            show_qr_action = menu.addAction("📱 Mostra QR Code")
            show_qr_action.triggered.connect(mw._show_qr_scanner_dialog)
            menu.addSeparator()
            stop_action = menu.addAction("🔴 Disattiva Scanner")
            stop_action.triggered.connect(lambda: (mw._stop_qr_scanner_server(), self._update_qr_scanner_btn_style()))
            btn_pos = self.qr_scanner_btn.mapToGlobal(self.qr_scanner_btn.rect().bottomLeft())
            menu.exec(btn_pos)
        else:
            # Server non attivo: avvia
            mw._start_qr_scanner_server()
            self._update_qr_scanner_btn_style()

    def _update_qr_scanner_btn_style(self):
        """Aggiorna l'aspetto del pulsante QR in base allo stato del server."""
        mw = self.main_window
        is_active = mw and hasattr(mw, 'qr_scanner_server_running') and mw.qr_scanner_server_running
        if is_active:
            self.qr_scanner_btn.setText("📱 Scanner QR 🟢")
            self.qr_scanner_btn.setStyleSheet(
                "QPushButton { color: #2E7D32; font-weight: bold; padding: 6px 16px; "
                "border: 2px solid #4CAF50; border-radius: 6px; background: rgba(76, 175, 80, 0.12); font-size: 10pt; }"
                "QPushButton:hover { background: rgba(76, 175, 80, 0.25); }"
            )
        else:
            self.qr_scanner_btn.setText("📱 Scanner QR")
            self.qr_scanner_btn.setStyleSheet(
                "QPushButton { color: #888; padding: 6px 16px; border: 1px solid #aaa; "
                "border-radius: 6px; background: transparent; font-size: 10pt; }"
                "QPushButton:hover { background: rgba(136, 136, 136, 0.15); }"
            )

    def create_customer_buttons(self):
        layout = QHBoxLayout()
        layout.setSpacing(10)
        
        self.add_cust_btn = self.create_button("➕ Aggiungi", self.add_customer, "autoButton")
        self.add_cust_btn.setObjectName("autoButton")
        self.edit_cust_btn = self.create_button("✏️ Modifica", self.edit_customer, "editButton", enabled=False)
        self.edit_cust_btn.setObjectName("editButton")
        self.del_cust_btn = self.create_button("🗑️ Elimina", self.delete_customer, "deleteButton", enabled=False)
        self.del_cust_btn.setObjectName("deleteButton")
        self.show_all_devices_btn = self.create_button("📋 Tutti Dispositivi", self.show_all_customer_devices, "secondaryButton", enabled=False)
        
        layout.addWidget(self.add_cust_btn)
        layout.addWidget(self.edit_cust_btn)
        layout.addWidget(self.del_cust_btn)
        layout.addWidget(self.show_all_devices_btn)
        
        if self.user_role == 'technician':
            self.del_cust_btn.setVisible(False)
            
        return layout

    def create_destination_buttons(self):
        layout = QHBoxLayout()
        layout.setSpacing(10)
        
        self.add_dest_btn = self.create_button("➕ Aggiungi", self.add_destination, "addButton", enabled=False)
        self.add_dest_btn.setObjectName("autoButton")
        self.edit_dest_btn = self.create_button("✏️ Modifica", self.edit_destination, "editButton", enabled=False)
        self.edit_dest_btn.setObjectName("editButton")
        self.del_dest_btn = self.create_button("🗑️ Elimina", self.delete_destination, "deleteButton", enabled=False)
        self.del_dest_btn.setObjectName("deleteButton")
        self.export_dest_table_btn = self.create_button("📊 Excel", self.export_destination_table, "secondaryButton", enabled=False)
        
        layout.addWidget(self.add_dest_btn)
        layout.addWidget(self.edit_dest_btn)
        layout.addWidget(self.del_dest_btn)
        layout.addWidget(self.export_dest_table_btn)
       
        if self.user_role == 'technician':
            self.del_dest_btn.setVisible(False)
        return layout

    def create_device_buttons(self):
        layout = QHBoxLayout()
        layout.setSpacing(10)
        
        self.add_dev_btn = self.create_button("➕ Aggiungi", self.add_device, "addButton", enabled=False)
        self.add_dev_btn.setObjectName("autoButton")
        self.edit_dev_btn = self.create_button("✏️ Modifica", self.edit_device, "editButton", enabled=False)
        self.edit_dev_btn.setObjectName("editButton")
        self.move_dev_btn = self.create_button("↔️ Sposta", self.move_device, "secondaryButton", enabled=False)
        self.decommission_dev_btn = self.create_button("❌ Dismetti", self.decommission_device, "warningButton", enabled=False)
        self.decommission_dev_btn.setObjectName("warningButton")
        self.decommission_dev_btn.setVisible(False)
        self.reactivate_dev_btn = self.create_button("✅ Riattiva", self.reactivate_device, "addButton", enabled=False)
        self.reactivate_dev_btn.setObjectName("autoButton")
        self.reactivate_dev_btn.setVisible(False)
        self.del_dev_btn = self.create_button("🗑️ Elimina", self.delete_device, "deleteButton", enabled=False)
        self.del_dev_btn.setObjectName("deleteButton")

        layout.addWidget(self.add_dev_btn)
        layout.addWidget(self.edit_dev_btn)
        layout.addWidget(self.move_dev_btn)
        layout.addWidget(self.decommission_dev_btn)
        layout.addWidget(self.reactivate_dev_btn)
        layout.addWidget(self.del_dev_btn)
        
        return layout
        
    def create_verification_buttons(self):
        layout = QHBoxLayout()
        layout.setSpacing(10)
        
        self.view_verif_btn = self.create_button("👁️ Visualizza", self.view_verification_details, "editButton", enabled=False)
        self.view_verif_btn.setObjectName("editButton")
        self.edit_verif_btn = self.create_button("✏️ Modifica", self.edit_verification, "editButton", enabled=False)
        self.edit_verif_btn.setObjectName("editButton")
        self.gen_report_btn = self.create_button("📄 PDF", self.generate_old_report, "addButton", enabled=False)
        self.gen_report_btn.setObjectName("autoButton")
        self.print_report_btn = self.create_button("🖨️ Stampa", self.print_old_report, "secondaryButton", enabled=False)
        self.print_report_btn.setObjectName("secondaryButton")
        self.delete_verif_btn = self.create_button("🗑️ Elimina", self.delete_verification, "deleteButton", enabled=False)
        self.delete_verif_btn.setObjectName("deleteButton")
        
        layout.addWidget(self.view_verif_btn)
        layout.addWidget(self.edit_verif_btn)
        layout.addWidget(self.gen_report_btn)
        layout.addWidget(self.print_report_btn)
        layout.addWidget(self.delete_verif_btn)
        
        return layout
    # --- LOGICA DI GESTIONE DATI ---
    def get_selected_id(self, table: QTableWidget):
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows: return None
        id_item = table.item(selected_rows[0].row(), 0)
        return int(id_item.text()) if id_item else None

    def reset_views(self, level='customer'):
        if level == 'customer':
            self.destination_table.setRowCount(0)
            self.destination_label.setText("ℹ️ Seleziona un cliente dalla scheda precedente")
            self.set_destination_buttons_enabled(False, False)
        if level in ['customer', 'destination']:
            self.device_table.setRowCount(0)
            self.device_label.setText("ℹ️ Seleziona una destinazione dalla scheda precedente")
            self.set_device_buttons_enabled(False)
        if level in ['customer', 'destination', 'device']:
            if hasattr(self, 'electrical_table'):
                self.electrical_table.setRowCount(0)
            if hasattr(self, 'functional_table'):
                self.functional_table.setRowCount(0)
            self.verification_label.setText("ℹ️ Seleziona un dispositivo dalla scheda precedente")
            self.set_verification_buttons_enabled(False)


    def set_customer_buttons_enabled(self, enabled):
        self.edit_cust_btn.setEnabled(enabled)
        self.del_cust_btn.setEnabled(enabled)

    def set_destination_buttons_enabled(self, add_enabled, other_enabled):
        self.add_dest_btn.setEnabled(add_enabled)
        self.edit_dest_btn.setEnabled(other_enabled)
        self.del_dest_btn.setEnabled(other_enabled)
        self.export_dest_table_btn.setEnabled(other_enabled)

    def set_device_buttons_enabled(self, enabled):
        self.add_dev_btn.setEnabled(enabled)
        self.edit_dev_btn.setEnabled(enabled)
        self.move_dev_btn.setEnabled(enabled)
        self.del_dev_btn.setEnabled(enabled)

    def set_verification_buttons_enabled(self, enabled):
        self.view_verif_btn.setEnabled(enabled)
        self.edit_verif_btn.setEnabled(enabled)
        self.gen_report_btn.setEnabled(enabled)
        self.print_report_btn.setEnabled(enabled)
        self.delete_verif_btn.setEnabled(enabled)

    def find_and_select_verification(self, verification_id: int):
        """
        Seleziona il record di verifica con l'ID dato nella tabella appropriata.
        """
        if not verification_id:
            return
        for table in (self.electrical_table, self.functional_table):
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item and item.text().isdigit() and int(item.text()) == verification_id:
                    table.selectRow(row)
                    table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                    return

    def find_and_select_verification(self, verification_id: int):
        if not verification_id:
            return
        for table in (self.electrical_table, self.functional_table):
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item and item.text().isdigit() and int(item.text()) == verification_id:
                    table.selectRow(row)
                    table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                    return

    def get_selected_verification_info(self):
        selection_model_e = self.electrical_table.selectionModel()
        if selection_model_e and selection_model_e.selectedRows():
            row = selection_model_e.selectedRows()[0].row()
            item = self.electrical_table.item(row, 0)
            data = item.data(Qt.UserRole) if item else None
            if data is None and item and item.text().isdigit():
                data = {"id": int(item.text())}
            if data:
                data["type"] = "ELETTRICA"
            return data

        selection_model_f = self.functional_table.selectionModel()
        if selection_model_f and selection_model_f.selectedRows():
            row = selection_model_f.selectedRows()[0].row()
            item = self.functional_table.item(row, 0)
            data = item.data(Qt.UserRole) if item else None
            if data is None and item and item.text().isdigit():
                data = {"id": int(item.text())}
            if data:
                data["type"] = "FUNZIONALE"
            return data
        return None

    def clear_other_table_selection(self, source_table):
        if source_table is self.electrical_table:
            self.functional_table.blockSignals(True)
            self.functional_table.clearSelection()
            self.functional_table.blockSignals(False)
        elif source_table is self.functional_table:
            self.electrical_table.blockSignals(True)
            self.electrical_table.clearSelection()
            self.electrical_table.blockSignals(False)

    def on_electrical_selection_changed(self):
        if self.electrical_table.selectionModel().selectedRows():
            self.clear_other_table_selection(self.electrical_table)
            self.set_verification_buttons_enabled(True)
            self.view_verif_btn.setEnabled(True)
            self.edit_verif_btn.setEnabled(True)
            self.gen_report_btn.setEnabled(True)
            self.print_report_btn.setEnabled(True)
            self.delete_verif_btn.setEnabled(True)
        else:
            if not self.functional_table.selectionModel().selectedRows():
                self.set_verification_buttons_enabled(False)

    def on_functional_selection_changed(self):
        if self.functional_table.selectionModel().selectedRows():
            self.clear_other_table_selection(self.functional_table)
            self.set_verification_buttons_enabled(True)
            self.view_verif_btn.setEnabled(True)
            self.edit_verif_btn.setEnabled(True)
            self.gen_report_btn.setEnabled(True)
            self.print_report_btn.setEnabled(True)
            self.delete_verif_btn.setEnabled(True)
        else:
            if not self.electrical_table.selectionModel().selectedRows():
                self.set_verification_buttons_enabled(False)

    def load_customers_table(self):
        self.reset_views(level='customer') 
        self.customer_table.setRowCount(0)
        self.customer_table.setSortingEnabled(False) 
        customers = services.get_all_customers(self.customer_search_box.text())
        
        for cust in customers:
            row = self.customer_table.rowCount()
            self.customer_table.insertRow(row)
            customer_dict = dict(cust)
            
            self.customer_table.setItem(row, 0, NumericTableWidgetItem(str(customer_dict['id'])))
            self.customer_table.setItem(row, 1, QTableWidgetItem(customer_dict['name'].upper()))
            self.customer_table.setItem(row, 2, QTableWidgetItem(customer_dict['address'].upper()))
            self.customer_table.setItem(row, 3, QTableWidgetItem(customer_dict.get('phone', '').upper()))
            self.customer_table.setItem(row, 4, QTableWidgetItem(customer_dict.get('email', '').upper()))
        
        self._center_table_items(self.customer_table)
        self.customer_table.setSortingEnabled(True)
        self._fit_table_columns(self.customer_table)

    def customer_selected(self):
        self.reset_views(level='destination')
        cust_id = self.get_selected_id(self.customer_table)
        self.set_customer_buttons_enabled(cust_id is not None)
        self.show_all_devices_btn.setEnabled(cust_id is not None)
        if cust_id:
            customer_name = self.customer_table.item(self.customer_table.currentRow(), 1).text()
            self.destination_label.setText(f"DESTINAZIONI '{customer_name.upper()}'")
            # Passa anche il testo di ricerca
            search_text = self.destination_search_box.text().strip()
            self.load_destinations_table(cust_id, search_query=search_text if search_text else None)
            self.set_destination_buttons_enabled(True, False)
    
    def load_destinations_table(self, customer_id, search_query=None):
        """Load destinations into the table with device counts."""
        self.destination_table.setRowCount(0)
        self.destination_table.setSortingEnabled(False)

        # Se c'è una query di ricerca, usa la funzione con filtro
        if search_query:
            destinations = services.get_destinations_with_device_count_for_customer(
                customer_id, 
                search_query=search_query
            )
        else:
            destinations = services.get_destinations_with_device_count_for_customer(customer_id)
        
        for dest in destinations:
            row = self.destination_table.rowCount()
            self.destination_table.insertRow(row)
            
            # Format destination name with device count
            dest_name = f"{dest['name']} ({dest['device_count']} dispositivi)"
            
            self.destination_table.setItem(row, 0, NumericTableWidgetItem(str(dest['id'])))
            self.destination_table.setItem(row, 1, QTableWidgetItem(dest_name))
            self.destination_table.setItem(row, 2, QTableWidgetItem(dest['address'].upper()))
        
        self._center_table_items(self.destination_table)
        self.destination_table.setSortingEnabled(True)
        self._fit_table_columns(self.destination_table)

    def destination_selected(self):
        self.reset_views(level='device')
        dest_id = self.get_selected_id(self.destination_table)
        is_dest_selected = dest_id is not None
        self.set_destination_buttons_enabled(self.get_selected_id(self.customer_table) is not None, is_dest_selected)
        if dest_id:
            dest_name = self.destination_table.item(self.destination_table.currentRow(), 1).text()
            self.device_label.setText(f"DISPOSITIVI '{dest_name.upper()}'")
            self.load_devices_table(dest_id)
            self.set_device_buttons_enabled(True)

    def load_devices_table(self, destination_id):
        self.device_table.setSortingEnabled(False)
        self.device_table.setRowCount(0)
        search_text = self.device_search_box.text()

        # --- INIZIO BLOCCO MODIFICATO ---
        
        # 1. Recupera i dati arricchiti dalla nuova funzione del database
        all_devices = database.get_devices_with_last_verification()
        
        # 2. Filtra i dispositivi per la destinazione corrente e la ricerca
        devices_to_show = [
            dev for dev in all_devices 
            if dev.get('destination_id') == destination_id and (
                not search_text or 
                any(search_text.lower() in str(dev.get(field, '') or '').lower() for field in 
                    ['description', 'serial_number', 'model', 'manufacturer', 'department', 'ams_inventory', 'customer_inventory'])
            )
        ]

        # Colori per le righe in base all'esito
        color_pass = QColor("#0b5f1e")  # Verde chiaro
        color_fail = QColor("#fc0217")  # Rosso chiaro
        
        for dev in devices_to_show:
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            
            status = dev.get('status', 'active')
            status_text = 'ATTIVO' if status == 'active' else 'DISMESSO'
            
            # Popola le celle come prima
            self.device_table.setItem(row, 0, NumericTableWidgetItem(str(dev.get('id'))))
            self.device_table.setItem(row, 1, QTableWidgetItem(str(dev.get('description')).upper()))
            self.device_table.setItem(row, 2, QTableWidgetItem(str(dev.get('department')).upper()))
            self.device_table.setItem(row, 3, QTableWidgetItem(str(dev.get('serial_number')).upper()))
            self.device_table.setItem(row, 4, QTableWidgetItem(str(dev.get('manufacturer')).upper()))
            self.device_table.setItem(row, 5, QTableWidgetItem(str(dev.get('model')).upper()))
            self.device_table.setItem(row, 6, QTableWidgetItem(str(dev.get('customer_inventory')).upper()))
            self.device_table.setItem(row, 7, QTableWidgetItem(str(dev.get('ams_inventory')).upper()))
            interval = dev.get('verification_interval')
            interval_text = str(interval).upper() if interval is not None else "N/A"
            self.device_table.setItem(row, 8, NumericTableWidgetItem(interval_text))
            self.device_table.setItem(row, 9, QTableWidgetItem(status_text.upper()))
            
            # 3. Popola la nuova colonna "ULTIMA VERIFICA"
            last_ver_date = dev.get('last_verification_date', '') or "N/A"
            self.device_table.setItem(row, 10, QTableWidgetItem(str(last_ver_date).upper()))

            # 4. Applica la colorazione alla riga
            target_color = None
            last_outcome_raw = dev.get('last_verification_outcome')

            if last_outcome_raw:
                # Pulisce la stringa da spazi e la converte in maiuscolo per un confronto sicuro
                last_outcome = last_outcome_raw.strip().upper()
                
                # Log per debug (solo per i primi dispositivi)
                if row < 3:
                    logging.debug(
                        f"Device {dev.get('id')} ({dev.get('description')}): "
                        f"last_verification_outcome='{last_outcome_raw}' -> normalized='{last_outcome}'"
                    )
                
                # Controlla diverse possibili diciture per l'esito
                # Solo "PASSATO" o "CONFORME" sono considerati positivi
                # Tutti gli altri esiti (FALLITO, NON CONFORME, CONFORME CON ANNOTAZIONE) sono negativi
                if last_outcome in ("PASSATO", "CONFORME"):
                    target_color = color_pass
                else:
                    # FALLITO, NON CONFORME, CONFORME CON ANNOTAZIONE, o qualsiasi altro esito
                    target_color = color_fail
            
            # Applica il colore a tutte le celle della riga
            if target_color:
                for col_index in range(self.device_table.columnCount()):
                    # Se una cella fosse vuota, crea un item per poterla colorare
                    if not self.device_table.item(row, col_index):
                         self.device_table.setItem(row, col_index, QTableWidgetItem())
                    item = self.device_table.item(row, col_index)
                    # Usa un ruolo personalizzato per memorizzare il colore (più affidabile)
                    item.setData(Qt.UserRole + 1, target_color.name())  # Salva il nome del colore come stringa
                    # Usa anche setData con Qt.ForegroundRole per compatibilità
                    item.setData(Qt.ForegroundRole, QBrush(target_color))
                    # Forza anche setForeground come backup
                    item.setForeground(QBrush(target_color))

            # Colora il testo di blu per i dispositivi dismessi (sovrascrive lo sfondo)
            if status == 'decommissioned':
                blue_color = QColor("blue")
                for col in range(self.device_table.columnCount()):
                    if not self.device_table.item(row, col):
                         self.device_table.setItem(row, col, QTableWidgetItem())
                    item = self.device_table.item(row, col)
                    item.setData(Qt.UserRole + 1, blue_color.name())  # Salva il nome del colore
                    item.setData(Qt.ForegroundRole, QBrush(blue_color))
                    item.setForeground(QBrush(blue_color))

        # --- FINE BLOCCO MODIFICATO ---

                self._center_table_items(self.device_table)
        self.device_table.setSortingEnabled(True)
        self._fit_table_columns(self.device_table)

    def decommission_device(self):
        dev_id = self.get_selected_id(self.device_table)
        dest_id = self.get_selected_id(self.destination_table)
        if not dev_id or not dest_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA DISMISSIONE', 
                                     "SEI SICURO DI VOLER MARCARE QUESTO DISPOSITIVO COME DISMESSO?\nNON APPARIRÀ PIÙ NELLE LISTE PER NUOVE VERIFICHE.",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            services.decommission_device(dev_id)
            self.load_devices_table(dest_id)

    def reactivate_device(self):
        dev_id = self.get_selected_id(self.device_table)
        dest_id = self.get_selected_id(self.destination_table)
        if not dev_id or not dest_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA RIATTIVAZIONE', 
                                     "SEI SICURO DI VOLER RIATTIVARE QUESTO DISPOSITIVO?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            services.reactivate_device(dev_id)
            self.load_devices_table(dest_id)

    def device_selected(self):
        self.reset_views(level='verification')
        dev_id = self.get_selected_id(self.device_table)
        self.edit_dev_btn.setEnabled(False)
        self.del_dev_btn.setEnabled(False)
        self.move_dev_btn.setEnabled(False)
        self.decommission_dev_btn.setEnabled(False)
        self.reactivate_dev_btn.setVisible(False)
        self.decommission_dev_btn.setVisible(True)
        if dev_id:
            current_row = self.device_table.currentRow()
            status_item = self.device_table.item(current_row, 9)
            status = status_item.text().lower() if status_item else 'attivo'
            is_active = (status == 'attivo')
            self.edit_dev_btn.setEnabled(True)
            self.del_dev_btn.setEnabled(True)
            self.move_dev_btn.setEnabled(is_active)
            self.decommission_dev_btn.setVisible(is_active)
            self.decommission_dev_btn.setEnabled(is_active)
            self.reactivate_dev_btn.setVisible(not is_active)
            self.reactivate_dev_btn.setEnabled(not is_active)
            dev_desc = self.device_table.item(current_row, 1).text()
            serial = self.device_table.item(current_row, 3).text()
            self.verification_label.setText(f"STORICO VERIFICHE '{dev_desc.upper()}' - SN: '{serial.upper()}'")
            self.load_verifications_table(dev_id)
    
    def load_verifications_table(self, device_id):
        raw_search = (self.verification_search_box.text() or "").strip()
        search_query_lower = raw_search.lower()

        self.electrical_table.setSortingEnabled(False)
        self.functional_table.setSortingEnabled(False)

        self.electrical_table.setRowCount(0)
        electrical_verifs = services.get_verifications_for_device(device_id, search_query_lower)
        electrical_entries = []
        for verif in electrical_verifs:
            profile_key = verif.get('profile_name', '')
            profile = config.PROFILES.get(profile_key)
            profile_display_name = profile.name if profile else profile_key
            date_val = verif.get('verification_date', '')
            try:
                sort_date = datetime.strptime(date_val, "%Y-%m-%d")
            except (ValueError, TypeError):
                sort_date = datetime.min
            electrical_entries.append({
                "id": verif.get('id'),
                "date": date_val,
                "sort_date": sort_date,
                "status": verif.get('overall_status', ''),
                "profile_display": profile_display_name,
                "technician": verif.get('technician_name', ''),
                "code": verif.get('verification_code', ''),
                "raw": verif,
            })

        electrical_entries.sort(key=lambda e: (e["sort_date"], e["id"] or 0), reverse=True)
        for entry in electrical_entries:
            row = self.electrical_table.rowCount()
            self.electrical_table.insertRow(row)
            id_item = NumericTableWidgetItem(str(entry.get('id', '')))
            id_item.setData(Qt.UserRole, entry)
            self.electrical_table.setItem(row, 0, id_item)
            self.electrical_table.setItem(row, 1, QTableWidgetItem(str(entry.get('date', '')).upper()))
            status = str(entry.get('status', '')).upper()
            status_item = QTableWidgetItem(status)
            status_item.setBackground(QColor('#A3BE8C') if status == 'PASSATO' else QColor('#BF616A'))
            self.electrical_table.setItem(row, 2, status_item)
            self.electrical_table.setItem(row, 3, QTableWidgetItem(str(entry.get('profile_display', '')).upper()))
            self.electrical_table.setItem(row, 4, QTableWidgetItem(str(entry.get('technician', '')).upper()))
            self.electrical_table.setItem(row, 5, QTableWidgetItem(str(entry.get('code', '')).upper()))

        self.functional_table.setRowCount(0)
        functional_verifs = services.get_functional_verifications_for_device(device_id)
        functional_entries = []
        for verif in functional_verifs:
            profile_key = verif.get('profile_key', '')
            profile = config.FUNCTIONAL_PROFILES.get(profile_key)
            profile_display_name = profile.name if profile else profile_key
            if search_query_lower:
                haystack = [
                    verif.get('verification_date', ''),
                    profile_display_name,
                    verif.get('overall_status', ''),
                    verif.get('technician_name', ''),
                    verif.get('notes', ''),
                    verif.get('verification_code', ''),
                ]
                if not any(search_query_lower in str(field).lower() for field in haystack if field is not None):
                    continue
            date_val = verif.get('verification_date', '')
            try:
                sort_date = datetime.strptime(date_val, "%Y-%m-%d")
            except (ValueError, TypeError):
                sort_date = datetime.min
            functional_entries.append({
                "id": verif.get('id'),
                "date": date_val,
                "sort_date": sort_date,
                "status": verif.get('overall_status', ''),
                "profile_display": profile_display_name,
                "technician": verif.get('technician_name', ''),
                "code": verif.get('verification_code', ''),
                "raw": verif,
            })

        functional_entries.sort(key=lambda e: (e["sort_date"], e["id"] or 0), reverse=True)
        for entry in functional_entries:
            row = self.functional_table.rowCount()
            self.functional_table.insertRow(row)
            id_item = NumericTableWidgetItem(str(entry.get('id', '')))
            id_item.setData(Qt.UserRole, entry)
            self.functional_table.setItem(row, 0, id_item)
            self.functional_table.setItem(row, 1, QTableWidgetItem(str(entry.get('date', '')).upper()))
            status = str(entry.get('status', '')).upper()
            status_item = QTableWidgetItem(status)
            status_item.setBackground(QColor('#A3BE8C') if status == 'PASSATO' else QColor('#BF616A'))
            self.functional_table.setItem(row, 2, status_item)
            self.functional_table.setItem(row, 3, QTableWidgetItem(str(entry.get('profile_display', '')).upper()))
            self.functional_table.setItem(row, 4, QTableWidgetItem(str(entry.get('technician', '')).upper()))
            self.functional_table.setItem(row, 5, QTableWidgetItem(str(entry.get('code', '')).upper()))

        self._center_table_items(self.electrical_table)
        self._center_table_items(self.functional_table)

        if self.electrical_table.rowCount() > 0:
            self.electrical_table.selectRow(0)
        elif self.functional_table.rowCount() > 0:
            self.functional_table.selectRow(0)
        else:
            self.set_verification_buttons_enabled(False)

        self.electrical_table.setSortingEnabled(True)
        self.functional_table.setSortingEnabled(True)
        self._fit_table_columns(self.electrical_table)
        self._fit_table_columns(self.functional_table)
        self.electrical_table.resizeRowsToContents()
        self.functional_table.resizeRowsToContents()

    def add_customer(self):
        dialog = CustomerDialog(parent=self)
        if dialog.exec():
            try:
                services.add_customer(**dialog.get_data())
                self.load_customers_table()
            except ValueError as e:
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def edit_customer(self):
        cust_id = self.get_selected_id(self.customer_table)
        if not cust_id:
            return
        customer_data = dict(services.database.get_customer_by_id(cust_id))
        dialog = CustomerDialog(customer_data, self)
        if dialog.exec():
            try:
                services.update_customer(cust_id, **dialog.get_data())
                self.load_customers_table()
            except ValueError as e:
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def delete_customer(self):
        cust_id = self.get_selected_id(self.customer_table)
        if not cust_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA', 'ELIMINARE IL CLIENTE E TUTTE LE SUE DESTINAZIONI E DISPOSITIVI?')
        if reply == QMessageBox.Yes:
            success, message = services.delete_customer(cust_id)
            if success:
                self.load_customers_table()
            else:
                QMessageBox.critical(self, "ERRORE", message.upper())

    def add_destination(self):
        cust_id = self.get_selected_id(self.customer_table)
        if not cust_id:
            return
        dialog = DestinationDetailDialog(parent=self)
        if dialog.exec():
            try:
                data = dialog.get_data()
                services.add_destination(cust_id, data['name'], data['address'])
                self.load_destinations_table(cust_id)
            except ValueError as e:
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def edit_destination(self):
        dest_id = self.get_selected_id(self.destination_table)
        cust_id = self.get_selected_id(self.customer_table)
        if not dest_id or not cust_id:
            return
        dest_data = dict(services.database.get_destination_by_id(dest_id))
        dialog = DestinationDetailDialog(destination_data=dest_data, parent=self)
        if dialog.exec():
            try:
                data = dialog.get_data()
                services.update_destination(dest_id, data['name'], data['address'])
                self.load_destinations_table(cust_id)
            except ValueError as e:
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def delete_destination(self):
        dest_id = self.get_selected_id(self.destination_table)
        cust_id = self.get_selected_id(self.customer_table)
        if not dest_id or not cust_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA', 'ELIMINARE QUESTA DESTINAZIONE? (VERRANNO ELIMINATI ANCHE TUTTI I DISPOSITIVI AL SUO INTERNO)')
        if reply == QMessageBox.Yes:
            try:
                services.delete_destination(dest_id)
                self.load_destinations_table(cust_id)
            except ValueError as e:
                QMessageBox.critical(self, "ERRORE", str(e).upper())

    def add_device(self):
        cust_id = self.get_selected_id(self.customer_table)
        dest_id = self.get_selected_id(self.destination_table)
        if not dest_id or not cust_id:
            return QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONA UN CLIENTE E UNA DESTINAZIONE.")
        dialog = DeviceDialog(customer_id=cust_id, destination_id=dest_id, parent=self)
        if dialog.exec():
            try:
                services.add_device(**dialog.get_data())
                self.load_devices_table(dest_id)
            except services.DeletedDeviceFoundException as e:
                # Dispositivo eliminato trovato con lo stesso S/N
                from app.ui.dialogs.reactivate_device_dialog import ReactivateDeviceDialog
                reactivate_dialog = ReactivateDeviceDialog(e.deleted_device, parent=self)
                
                if reactivate_dialog.exec():
                    if reactivate_dialog.reactivate_choice:
                        # Utente ha scelto di riattivare
                        try:
                            device_data = dialog.get_data()
                            services.update_device(
                                dev_id=e.deleted_device['id'],
                                destination_id=device_data['destination_id'],
                                serial=device_data['serial'],
                                desc=device_data['desc'],
                                mfg=device_data['mfg'],
                                model=device_data['model'],
                                department=device_data['department'],
                                applied_parts=device_data['applied_parts'],
                                customer_inv=device_data['customer_inv'],
                                ams_inv=device_data['ams_inv'],
                                verification_interval=device_data['verification_interval'],
                                default_profile_key=device_data['default_profile_key'],
                                default_functional_profile_key=device_data['default_functional_profile_key'],
                                reactivate=True
                            )
                            self.load_devices_table(dest_id)
                            QMessageBox.information(self, "✓ Dispositivo Riattivato", 
                                                  "Il dispositivo è stato riattivato con successo!")
                        except Exception as ex:
                            QMessageBox.critical(self, "ERRORE", 
                                               f"IMPOSSIBILE RIATTIVARE IL DISPOSITIVO:\n{str(ex).upper()}")
                    else:
                        # Utente ha scelto di creare un nuovo dispositivo
                        try:
                            device_data = dialog.get_data()
                            services.add_device(**device_data, force_create=True)
                            self.load_devices_table(dest_id)
                            QMessageBox.information(self, "✓ Dispositivo Creato", 
                                                  "Nuovo dispositivo creato con successo!")
                        except Exception as ex:
                            QMessageBox.critical(self, "ERRORE", 
                                               f"IMPOSSIBILE CREARE IL DISPOSITIVO:\n{str(ex).upper()}")
            except ValueError as e:
                QMessageBox.warning(self, "ERRORE VALIDAZIONE", str(e).upper())
                return
            except Exception as e:
                QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE SALVARE IL DISPOSITIVO:\n{str(e).upper()}")
                return

    def edit_device(self):
        cust_id = self.get_selected_id(self.customer_table)
        dev_id = self.get_selected_id(self.device_table)
        dest_id = self.get_selected_id(self.destination_table)
        if not dev_id or not cust_id or not dest_id:
            return
        device_data = dict(services.database.get_device_by_id(dev_id))
        dialog = DeviceDialog(customer_id=cust_id, device_data=device_data, parent=self)
        if dialog.exec():
            try:
                services.update_device(dev_id, **dialog.get_data())
                self.load_devices_table(dest_id)
            except ValueError as e:
                QMessageBox.warning(self, "ERRORE VALIDAZIONE", str(e).upper())
                return
            except Exception as e:
                QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE SALVARE IL DISPOSITIVO:\n{str(e).upper()}")
                return

    def delete_device(self):
        dev_id = self.get_selected_id(self.device_table)
        dest_id = self.get_selected_id(self.destination_table)
        if not dev_id or not dest_id:
            return
        reply = QMessageBox.question(self, 'CONFERMA', 'ELIMINARE QUESTO DISPOSITIVO E TUTTE LE SUE VERIFICHE?')
        if reply == QMessageBox.Yes:
            services.delete_device(dev_id)
            self.load_devices_table(dest_id)

    def move_device(self):
        dev_id = self.get_selected_id(self.device_table)
        old_dest_id = self.get_selected_id(self.destination_table)
        if not dev_id:
            return QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONA UN DISPOSITIVO DA SPOSTARE.")
        dialog = DestinationSelectionDialog(self)
        if dialog.exec():
            new_dest_id = dialog.selected_destination_id
            if new_dest_id and new_dest_id != old_dest_id:
                try:
                    services.move_device_to_destination(dev_id, new_dest_id)
                    self.load_devices_table(old_dest_id)
                    QMessageBox.information(self, "SUCCESSO", "DISPOSITIVO SPOSTATO.")
                except Exception as e:
                    QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE SPOSTARE IL DISPOSITIVO: {str(e).upper()}")

    def import_from_file(self):
        dest_id = self.get_selected_id(self.destination_table)
        if not dest_id:
            return QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONA UNA DESTINAZIONE IN CUI IMPORTARE.")
        filename, _ = QFileDialog.getOpenFileName(self, "SELEZIONA FILE", "", "File Excel/CSV (*.xlsx *.xls *.csv)")
        if not filename:
            return
        try:
            if filename.endswith('.csv'):
                # Leggi CSV - prova diversi separatori e trova quello che produce più colonne
                df_headers = None
                best_sep = ';'
                max_cols = 0
                separators = [';', ',', '\t', '|']
                
                for sep in separators:
                    try:
                        # Leggi almeno 10 righe per assicurarsi che tutte le colonne vengano rilevate
                        # Usa error_bad_lines=False per pandas < 1.3, on_bad_lines per pandas >= 1.3
                        try:
                            df_test = pd.read_csv(filename, sep=sep, dtype=str, nrows=10, encoding='utf-8', on_bad_lines='skip')
                        except TypeError:
                            # Fallback per versioni più vecchie di pandas
                            df_test = pd.read_csv(filename, sep=sep, dtype=str, nrows=10, encoding='utf-8', error_bad_lines=False, warn_bad_lines=False)
                        num_cols = len(df_test.columns)
                        if num_cols > max_cols:
                            max_cols = num_cols
                            df_headers = df_test.columns.tolist()
                            best_sep = sep
                    except Exception as e:
                        logging.debug(f"Separatore {sep} fallito: {e}")
                        continue
                
                # Se nessun separatore ha funzionato, prova con i separatori comuni
                if df_headers is None or len(df_headers) <= 1:
                    for sep in [';', ',']:
                        try:
                            try:
                                df_test = pd.read_csv(filename, sep=sep, dtype=str, nrows=10, encoding='utf-8', on_bad_lines='skip')
                            except TypeError:
                                df_test = pd.read_csv(filename, sep=sep, dtype=str, nrows=10, encoding='utf-8', error_bad_lines=False, warn_bad_lines=False)
                            num_cols = len(df_test.columns)
                            if num_cols > max_cols:
                                max_cols = num_cols
                                df_headers = df_test.columns.tolist()
                                best_sep = sep
                        except Exception:
                            continue
                
                if df_headers is None or len(df_headers) <= 1:
                    raise Exception("Impossibile leggere le colonne dal file CSV. Verifica il formato e il separatore.")
                
                logging.info(f"CSV: separatore rilevato '{best_sep}', colonne trovate: {len(df_headers)}")
            else:
                # Leggi Excel - prova diversi engine e metodi
                # Leggi almeno 5 righe per assicurarsi che tutte le colonne vengano rilevate
                df_headers = None
                error_messages = []
                
                # Prova prima con openpyxl (per .xlsx)
                if filename.endswith('.xlsx'):
                    try:
                        df_test = pd.read_excel(
                            filename, 
                            dtype=str, 
                            nrows=5,  # Leggi 5 righe invece di 0
                            engine='openpyxl',
                            sheet_name=0  # Leggi il primo foglio
                        )
                        df_headers = df_test.columns.tolist()
                    except Exception as e:
                        error_messages.append(f"openpyxl: {str(e)}")
                
                # Se fallisce, prova con xlrd (per .xls)
                if df_headers is None or len(df_headers) <= 1:
                    try:
                        df_test = pd.read_excel(
                            filename, 
                            dtype=str, 
                            nrows=5,  # Leggi 5 righe invece di 0
                            engine='xlrd',
                            sheet_name=0  # Leggi il primo foglio
                        )
                        df_headers = df_test.columns.tolist()
                    except Exception as e:
                        error_messages.append(f"xlrd: {str(e)}")
                
                # Se ancora fallisce, prova senza specificare engine
                if df_headers is None or len(df_headers) <= 1:
                    try:
                        df_test = pd.read_excel(
                            filename, 
                            dtype=str, 
                            nrows=5,  # Leggi 5 righe invece di 0
                            sheet_name=0  # Leggi il primo foglio
                        )
                        df_headers = df_test.columns.tolist()
                    except Exception as e:
                        error_messages.append(f"default: {str(e)}")
                
                if df_headers is None or len(df_headers) <= 1:
                    raise Exception(f"Impossibile leggere le colonne dal file Excel. Errori provati:\n" + "\n".join(error_messages))
            
            # Pulisci i nomi delle colonne (rimuovi spazi iniziali/finali e caratteri invisibili)
            # e normalizza in MAIUSCOLO per coerenza con il mapping
            df_headers = [str(col).strip().upper() if col is not None else "" for col in df_headers]
            
            # Rimuovi colonne vuote o None, ma mantieni tutte le colonne anche se hanno nomi vuoti
            # (potrebbero essere colonne con dati ma senza intestazione)
            df_headers = [col if col else f"COLONNA_{i+1}" for i, col in enumerate(df_headers)]
            
            if not df_headers:
                raise Exception("Nessuna colonna trovata nel file. Assicurati che il file contenga una riga di intestazione.")
            
            logging.info(f"Colonne rilevate: {len(df_headers)} - {df_headers}")
                
        except Exception as e:
            QMessageBox.critical(self, "ERRORE LETTURA FILE", f"IMPOSSIBILE LEGGERE LE INTESTAZIONI:\n{str(e).upper()}")
            return
        map_dialog = MappingDialog(df_headers, self)
        if map_dialog.exec() == QDialog.Accepted:
            mapping = map_dialog.get_mapping()
            if mapping is None:
                return
            self.progress_dialog = QProgressDialog("IMPORTAZIONE...", "ANNULLA", 0, 100, self)
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.thread = QThread()
            self.worker = ImportWorker(filename, mapping, dest_id)
            self.worker.moveToThread(self.thread)
            self.worker.progress_updated.connect(self.progress_dialog.setValue)
            self.progress_dialog.canceled.connect(self.worker.cancel)
            self.thread.started.connect(self.worker.run)
            self.worker.finished.connect(self.on_import_finished)
            self.worker.error.connect(self.on_import_error)
            self.worker.finished.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            self.thread.finished.connect(self.progress_dialog.close)
            self.thread.start()
            self.progress_dialog.exec()

    def on_import_finished(self, added_count, skipped_rows_details, status):
        dest_id = self.get_selected_id(self.destination_table)
        if dest_id:
            self.load_devices_table(dest_id)
        if status == "Annullato":
            QMessageBox.warning(self, "IMPORTAZIONE ANNULLATA", "OPERAZIONE ANNULLATA.")
            return
        summary = f"IMPORTAZIONE TERMINATA.\n- DISPOSITIVI AGGIUNTI: {added_count}\n- RIGHE IGNORATE: {len(skipped_rows_details)}"
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle("IMPORTAZIONE COMPLETATA")
        msg_box.setText(summary)
        if skipped_rows_details:
            details_button = msg_box.addButton("VISUALIZZA DETTAGLI...", QMessageBox.ActionRole)
        msg_box.addButton("Conferma", QMessageBox.AcceptRole)
        msg_box.exec()
        if skipped_rows_details and msg_box.clickedButton() == details_button:
            report_dialog = ImportReportDialog("DETTAGLIO RIGHE IGNORATE", skipped_rows_details, self)
            report_dialog.exec()

    def on_import_error(self, error_message):
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()
        QMessageBox.critical(self, "ERRORE DI IMPORTAZIONE", error_message.upper())

    def import_from_stm(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "SELEZIONA ARCHIVIO .STM", "", "File STM (*.stm)")
        if not filepath:
            return
        self.thread = QThread()
        self.worker = StmImportWorker(filepath)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_stm_import_finished)
        self.worker.error.connect(self.on_import_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.setWindowTitle("MANAGER ANAGRAFICHE (IMPORTAZIONE...)")
        self.thread.start()

    def on_stm_import_finished(self, verif_imported, verif_skipped, dev_new, cust_new):
        self.setWindowTitle("MANAGER ANAGRAFICHE")
        self.load_customers_table()
        QMessageBox.information(self, "IMPORTAZIONE COMPLETATA", f"IMPORTAZIONE DA ARCHIVIO COMPLETATA.\n- VERIFICHE IMPORTATE: {verif_imported}\n- VERIFICHE SALTATE: {verif_skipped}\n- NUOVI DISPOSITIVI: {dev_new}")

    def export_daily_verifications(self):
        date_dialog = DateSelectionDialog(self)
        if date_dialog.exec() == QDialog.Accepted:
            target_date = date_dialog.getSelectedDate()
            default_filename = f"Export_Verifiche_{target_date.replace('-', '')}.stm"
            output_path, _ = QFileDialog.getSaveFileName(self, "SALVA ESPORTAZIONE", default_filename, "File STM (*.stm)")
            if not output_path:
                return
            self.thread = QThread()
            self.worker = DailyExportWorker(target_date, output_path)
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.finished.connect(self.on_export_finished)
            self.worker.error.connect(self.on_export_error)
            self.worker.finished.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            self.setWindowTitle("MANAGER ANAGRAFICHE (ESPORTAZIONE...)")
            self.thread.start()

    def on_export_finished(self, status, message):
        self.setWindowTitle("MANAGER ANAGRAFICHE")
        if status == "Success":
            QMessageBox.information(self, "ESPORTAZIONE COMPLETATA", message.upper())
        else:
            QMessageBox.warning(self, "ESPORTAZIONE", message.upper())

    def on_export_error(self, error_message):
        self.setWindowTitle("MANAGER ANAGRAFICHE")
        QMessageBox.critical(self, "ERRORE ESPORTAZIONE", error_message.upper())

    def generate_monthly_reports(self):
        dest_id = self.get_selected_id(self.destination_table)
        if not dest_id: 
            return QMessageBox.warning(self, "Selezione Mancante", "Seleziona una destinazione.")
        period_dialog = SingleCalendarRangeDialog(self)
        if not period_dialog.exec(): 
            return
        start_date, end_date = period_dialog.get_date_range()
        
        # Recupera sia le verifiche elettriche che quelle funzionali
        electrical_verifications = services.database.get_verifications_for_destination_by_date_range(dest_id, start_date, end_date)
        functional_verifications = services.database.get_functional_verifications_for_destination_by_date_range(dest_id, start_date, end_date)
        
        # Filtra per mantenere solo l'ultima verifica per ogni dispositivo
        # Per le verifiche elettriche: mantieni solo l'ultima per device_id
        electrical_dict = {}
        for verif in electrical_verifications:
            verif_dict = dict(verif)
            device_id = verif_dict.get('device_id')
            if device_id:
                # Se non abbiamo ancora una verifica per questo dispositivo, o se questa è più recente
                if device_id not in electrical_dict:
                    electrical_dict[device_id] = verif_dict
                else:
                    # Confronta le date per vedere quale è più recente
                    current_date = electrical_dict[device_id].get('verification_date', '')
                    new_date = verif_dict.get('verification_date', '')
                    if new_date > current_date:
                        electrical_dict[device_id] = verif_dict
        
        # Per le verifiche funzionali: mantieni solo l'ultima per device_id
        functional_dict = {}
        for verif in functional_verifications:
            verif_dict = dict(verif)
            device_id = verif_dict.get('device_id')
            if device_id:
                # Se non abbiamo ancora una verifica per questo dispositivo, o se questa è più recente
                if device_id not in functional_dict:
                    functional_dict[device_id] = verif_dict
                else:
                    # Confronta le date per vedere quale è più recente
                    current_date = functional_dict[device_id].get('verification_date', '')
                    new_date = verif_dict.get('verification_date', '')
                    if new_date > current_date:
                        functional_dict[device_id] = verif_dict
        
        # Combina le verifiche in una lista unificata con campo "verification_type"
        all_verifications = []
        for verif_dict in electrical_dict.values():
            verif_dict['verification_type'] = 'ELETTRICA'
            all_verifications.append(verif_dict)
        for verif_dict in functional_dict.values():
            verif_dict['verification_type'] = 'FUNZIONALE'
            all_verifications.append(verif_dict)
        
        if not all_verifications: 
            return QMessageBox.information(self, "NESSUNA VERIFICA", f"NESSUNA VERIFICA TROVATA NEL PERIODO SELEZIONATO.")
        
        # Chiedi all'utente di selezionare il formato del nome file
        naming_dialog = ReportNamingFormatDialog(self)
        if not naming_dialog.exec():
            return
        naming_format = naming_dialog.get_selected_format()
        
        output_folder = QFileDialog.getExistingDirectory(self, "SELEZIONA CARTELLA DI DESTINAZIONE PER I REPORT")
        if not output_folder: 
            return
        report_settings = {"logo_path": self.main_window.logo_path}
        self.progress_dialog = QProgressDialog("GENERAZIONE REPORT...", "ANNULLA", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.thread = QThread()
        self.worker = BulkReportWorker(all_verifications, output_folder, report_settings, naming_format)
        self.worker.moveToThread(self.thread)
        self.progress_dialog.canceled.connect(self.worker.cancel)
        self.worker.progress_updated.connect(self.on_bulk_report_progress)
        self.worker.finished.connect(self.on_bulk_report_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.progress_dialog.close)
        self.thread.started.connect(self.worker.run)
        self.progress_dialog.show()
        self.thread.start()

    def on_bulk_report_progress(self, percent, message):
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.setValue(percent)
            self.progress_dialog.setLabelText(message)

    def on_bulk_report_finished(self, success_count, failed_reports):
        summary = f"GENERAZIONE COMPLETATA.\n- REPORT CREATI: {success_count}"
        if failed_reports:
            summary += f"\n- ERRORI: {len(failed_reports)}"
        msg_box = QMessageBox(QMessageBox.Information, "OPERAZIONE TERMINATA", summary, parent=self)
        if failed_reports:
            msg_box.setDetailedText("Dettaglio errori:\n" + "\n".join(failed_reports))
        msg_box.exec()

    def open_period_filter_dialog(self):
        dest_id = self.get_selected_id(self.destination_table)
        if not dest_id:
            return QMessageBox.warning(self, "Selezione Mancante", "Seleziona una destinazione.")
        date_dialog = SingleCalendarRangeDialog(self)
        if not date_dialog.exec():
            return
        start_date, end_date = date_dialog.get_date_range()
        try:
            verified, unverified = services.database.get_devices_verification_status_by_period(dest_id, start_date, end_date)
            results_dialog = VerificationStatusDialog(verified, unverified, self)
            results_dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE RECUPERARE LO STATO: {str(e).upper()}")

    def edit_verification(self):
        """Apre il dialog per modificare la verifica selezionata (elettrica o funzionale)."""
        info = self.get_selected_verification_info()
        dev_id = self.get_selected_id(self.device_table)
        if not info or not dev_id:
            return
        verif_type = info.get("type")
        verif_id = info.get("id")
        verif_data = info.get("raw")

        # Se non abbiamo i dati completi, recuperali dal DB
        if verif_type == "FUNZIONALE":
            if not verif_data:
                all_verifs = services.get_functional_verifications_for_device(dev_id)
                verif_data = next((v for v in all_verifs if v.get('id') == verif_id), None)
        else:
            if not verif_data:
                all_verifs = services.get_verifications_for_device(dev_id)
                verif_data = next((v for v in all_verifs if v.get('id') == verif_id), None)

        if not verif_data:
            QMessageBox.critical(self, "Errore", "Impossibile trovare i dati della verifica.")
            return

        dialog = EditVerificationDialog(verif_data, verif_type, self)
        if dialog.exec() != QDialog.Accepted:
            return

        new_data = dialog.get_data()
        try:
            if verif_type == "FUNZIONALE":
                updated = services.update_functional_verification(
                    verif_id,
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
                    verif_id,
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
                self.load_verifications_table(dev_id)
            else:
                QMessageBox.warning(self, "Attenzione", "Nessuna modifica effettuata.")
        except Exception as e:
            logging.error(f"Errore durante la modifica della verifica: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile aggiornare la verifica:\n{e}")
        
    def view_verification_details(self):
        info = self.get_selected_verification_info()
        dev_id = self.get_selected_id(self.device_table)
        if not info or not dev_id:
            return
        verif_type = info.get("type")
        verif_data = info.get("raw")

        if verif_type == "FUNZIONALE":
            if not verif_data:
                all_verifs = services.get_functional_verifications_for_device(dev_id)
                verif_data = next((v for v in all_verifs if v.get('id') == info.get("id")), None)
            if verif_data:
                dialog = FunctionalVerificationViewerDialog(verif_data, self)
                dialog.exec()
            else:
                QMessageBox.critical(self, "ERRORE DATI", "IMPOSSIBILE TROVARE I DATI PER LA VERIFICA FUNZIONALE.")
            return

        if not verif_data:
            all_verifs = services.get_verifications_for_device(dev_id)
            verif_data = next((v for v in all_verifs if v.get('id') == info.get("id")), None)
        if verif_data:
            dialog = VerificationViewerDialog(verif_data, self)
            dialog.exec()
        else:
            QMessageBox.critical(self, "ERRORE DATI", "IMPOSSIBILE TROVARE I DATI PER LA VERIFICA.")

    def generate_old_report(self):
        info = self.get_selected_verification_info()
        dev_id = self.get_selected_id(self.device_table)
        if not info or not dev_id:
            return
        verif_type = info.get("type")
        verif_id = info.get("id")
        device_info = services.get_device_by_id(dev_id)
        if not device_info:
            return QMessageBox.critical(self, "ERRORE", "IMPOSSIBILE TROVARE I DATI DEL DISPOSITIVO.")
        ams_inv = (device_info.get('ams_inventory') or '').strip()
        serial_num = (device_info.get('serial_number') or '').strip()
        verification_code = info.get("raw", {}).get("verification_code")

        # Ordine richiesto:
        # 1) Inventario AMS
        # 2) Numero di serie
        # 3) Codice verifica
        # Se nessuno è disponibile, usa un fallback generico.
        if ams_inv:
            base_name = ams_inv
        elif serial_num:
            base_name = serial_num
        elif verification_code:
            base_name = verification_code
        else:
            base_name = "Report_Verifica"

        safe_base_name = re.sub(r'[\\/*?:"<>|]', '_', base_name)
        suffix = "VE" if verif_type == "ELETTRICA" else "VF"
        default_filename = f"{safe_base_name} {suffix}.pdf"
        filename, _ = QFileDialog.getSaveFileName(self, "SALVA REPORT PDF", default_filename, "PDF Files (*.pdf)")
        if not filename:
            return
        try:
            report_settings = {"logo_path": self.main_window.logo_path}
            if verif_type == "FUNZIONALE":
                services.generate_functional_pdf_report(filename, verif_id, dev_id, report_settings)
            else:
                services.generate_pdf_report(filename, verif_id, dev_id, report_settings)
            QMessageBox.information(self, "SUCCESSO", f"REPORT GENERATO CON SUCCESSO:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE GENERARE IL REPORT: {str(e).upper()}")

    def print_old_report(self):
        info = self.get_selected_verification_info()
        dev_id = self.get_selected_id(self.device_table)
        if not info or not dev_id:
            return
        verif_type = info.get("type")
        verif_id = info.get("id")
        try:
            report_settings = {"logo_path": self.main_window.logo_path}
            if verif_type == "FUNZIONALE":
                services.print_functional_pdf_report(verif_id, dev_id, report_settings, parent_widget=self)
            else:
                services.print_pdf_report(verif_id, dev_id, report_settings, parent_widget=self)
        except Exception as e:
            QMessageBox.critical(self, "ERRORE DI STAMPA", f"IMPOSSIBILE STAMPARE IL REPORT:\n{str(e).upper()}")

    def delete_verification(self):
        info = self.get_selected_verification_info()
        dev_id = self.get_selected_id(self.device_table)
        if not info or not dev_id:
            return
        verif_id = info.get("id")
        verif_type = info.get("type")
        type_label = "FUNZIONALE" if verif_type == "FUNZIONALE" else "ELETTRICA"
        reply = QMessageBox.question(
            self,
            'CONFERMA',
            f"SEI SICURO DI VOLER ELIMINARE LA VERIFICA {type_label} ID {verif_id}?"
        )
        if reply == QMessageBox.Yes:
            if verif_type == "FUNZIONALE":
                services.delete_functional_verification(verif_id)
            else:
                services.delete_verification(verif_id)
            self.load_verifications_table(dev_id)

    def show_all_customer_devices(self):
        cust_id = self.get_selected_id(self.customer_table)
        if not cust_id:
            return
        self.destination_table.clearSelection()
        customer_name = self.customer_table.item(self.customer_table.currentRow(), 1).text()
        self.device_label.setText(f"TUTTI I DISPOSITIVI PER '{customer_name.upper()}'")
        self.set_device_buttons_enabled(False)
        self.device_table.setSortingEnabled(False)
        self.device_table.setRowCount(0)
        search_text = self.device_search_box.text()
        devices = services.database.get_all_devices_for_customer(cust_id, search_text)
        for dev_row in devices:
            dev = dict(dev_row)
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)
            status = dev.get('status', 'active')
            status_text = 'ATTIVO' if status == 'active' else 'DISMESSO'
            self.device_table.setItem(row, 0, QTableWidgetItem(str(dev.get('id'))))
            self.device_table.setItem(row, 1, QTableWidgetItem(str(dev.get('description')).upper()))
            self.device_table.setItem(row, 2, QTableWidgetItem(str(dev.get('department')).upper()))
            self.device_table.setItem(row, 3, QTableWidgetItem(str(dev.get('serial_number')).upper()))
            self.device_table.setItem(row, 4, QTableWidgetItem(str(dev.get('manufacturer')).upper()))
            self.device_table.setItem(row, 5, QTableWidgetItem(str(dev.get('model')).upper()))
            self.device_table.setItem(row, 6, QTableWidgetItem(str(dev.get('customer_inventory')).upper()))
            self.device_table.setItem(row, 7, QTableWidgetItem(str(dev.get('ams_inventory')).upper()))
            interval = dev.get('verification_interval')
            interval_text = str(interval) if interval is not None else "N/A"
            self.device_table.setItem(row, 8, QTableWidgetItem(interval_text.upper()))
            self.device_table.setItem(row, 9, QTableWidgetItem(status_text.upper()))
            if status == 'decommissioned':
                for col in range(self.device_table.columnCount()):
                    self.device_table.item(row, col).setForeground(QBrush(QColor("blue")))
        self.device_table.setSortingEnabled(True)
        self.device_table.resizeRowsToContents()
        self.tabs.setCurrentWidget(self.device_tab)
        
    def find_and_select_item(self, table: QTableWidget, item_id: int):
        for row in range(table.rowCount()):
            table_item = table.item(row, 0)
            if table_item and int(table_item.text()) == item_id:
                table.selectRow(row)
                table.scrollToItem(table_item, QAbstractItemView.ScrollHint.PositionAtCenter)
                break
    
    def export_destination_table(self):
        dest_id = self.get_selected_id(self.destination_table)
        if not dest_id:
            QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONA UNA DESTINAZIONE PER CUI GENERARE LA TABELLA.")
            return

        date_dialog = SingleCalendarRangeDialog(self)
        if date_dialog.exec() == QDialog.Accepted:
            start_date_obj, end_date_obj = date_dialog.get_date_range()
            if not start_date_obj or not end_date_obj:
                QMessageBox.warning(self, "SELEZIONE MANCANTE", "DEVI SELEZIONARE UN INTERVALLO DI DATE VALIDO.")
                return
            
            start_date = start_date_obj.toString("yyyy-MM-dd") if hasattr(start_date_obj, 'toString') else str(start_date_obj)
            end_date = end_date_obj.toString("yyyy-MM-dd") if hasattr(end_date_obj, 'toString') else str(end_date_obj)
            
            destination_name = self.destination_table.item(self.destination_table.currentRow(), 1).text()
            safe_name = re.sub(r'[\\/*?:"<>|]', '_', f"{destination_name}_{start_date}_al_{end_date}")
            default_filename = f"Tabella Verifiche_{safe_name}.xlsx"

            output_path, _ = QFileDialog.getSaveFileName(self, "SALVA TABELLA EXCEL", default_filename, "File Excel (*.xlsx)")
            if not output_path:
                return

            self.thread = QThread()
            self.worker = TableExportWorker(dest_id, output_path, start_date, end_date)
            self.worker.moveToThread(self.thread)

            self.thread.started.connect(self.worker.run)
            self.worker.finished.connect(self.on_table_export_finished)
            self.worker.error.connect(self.on_table_export_error)
            self.worker.finished.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            
            self.setWindowTitle("MANAGER ANAGRAFICHE (ESPORTAZIONE TABELLA...)")
            self.thread.start()

    def on_table_export_finished(self, message):
        self.setWindowTitle("MANAGER ANAGRAFICHE")
        QMessageBox.information(self, "ESPORTAZIONE COMPLETATA", message.upper())

    def on_table_export_error(self, error_message):
        self.setWindowTitle("MANAGER ANAGRAFICHE")
        QMessageBox.critical(self, "ERRORE ESPORTAZIONE", error_message.upper())

# --- Classe InstrumentManagerDialog (inclusa per completezza) ---
class InstrumentManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Abilita il maiuscolo automatico per questa finestra
        self.setProperty("_stm_uppercase_window", True)
        self.setWindowTitle("GESTIONE ANAGRAFICA STRUMENTI")
        self.setMinimumSize(800, 500)
        # Applica il tema corrente
        self.setStyleSheet(config.get_current_stylesheet())
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "NOME STRUMENTO", "SERIALE", "NR CERTIFICATO CAL.", "DATA CAL."])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader(); header.setSectionResizeMode(0, QHeaderView.ResizeToContents); header.setSectionResizeMode(1, QHeaderView.Stretch); header.setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)
        buttons_layout = QHBoxLayout()
        add_btn = QPushButton("AGGIUNGI"); add_btn.clicked.connect(self.add_instrument)
        edit_btn = QPushButton("MODIFICA"); edit_btn.clicked.connect(self.edit_instrument)
        delete_btn = QPushButton("ELIMINA"); delete_btn.clicked.connect(self.delete_instrument)
        default_btn = QPushButton("IMPOSTA COME PREDEFINITO"); default_btn.clicked.connect(self.set_default)
        buttons_layout.addWidget(add_btn); buttons_layout.addWidget(edit_btn); buttons_layout.addWidget(delete_btn); buttons_layout.addStretch(); buttons_layout.addWidget(default_btn)
        layout.addLayout(buttons_layout)
        self.load_instruments()

    def get_selected_id(self) -> int | None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows: return None
        try: return int(self.table.item(selected_rows[0].row(), 0).text())
        except (ValueError, AttributeError): return None

    def load_instruments(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        instruments_rows = services.get_all_instruments()
        for inst_row in instruments_rows:
            instrument = dict(inst_row); row = self.table.rowCount(); self.table.insertRow(row)
            id_item = QTableWidgetItem(str(instrument.get('id'))); id_item.setFlags(id_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, id_item); self.table.setItem(row, 1, QTableWidgetItem(str(instrument.get('instrument_name', '')).upper())); self.table.setItem(row, 2, QTableWidgetItem(str(instrument.get('serial_number', '')).upper())); self.table.setItem(row, 3, QTableWidgetItem(str(instrument.get('fw_version', '')).upper())); self.table.setItem(row, 4, QTableWidgetItem(str(instrument.get('calibration_date', '')).upper()))
            if instrument.get('is_default'):
                for col in range(5): self.table.item(row, col).setBackground(QColor("#E0F7FA"))
        self.table.setSortingEnabled(True)

    def add_instrument(self):
        dialog = InstrumentDetailDialog(parent=self)
        if dialog.exec():
            try: 
                data = dialog.get_data()
                services.add_instrument(
                    instrument_name=data['instrument_name'],
                    serial_number=data['serial_number'],
                    fw_version=data['fw_version'],
                    calibration_date=data['calibration_date'],
                    instrument_type=data.get('instrument_type', 'electrical')
                )
                self.load_instruments()
            except ValueError as e: 
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def edit_instrument(self):
        inst_id = self.get_selected_id()
        if not inst_id: return
        all_instruments = services.get_all_instruments()
        inst_row = next((inst for inst in all_instruments if inst['id'] == inst_id), None)
        inst_data_dict = dict(inst_row) if inst_row else None
        dialog = InstrumentDetailDialog(inst_data_dict, self)
        if dialog.exec():
            try: 
                data = dialog.get_data()
                services.update_instrument(
                    inst_id,
                    instrument_name=data['instrument_name'],
                    serial_number=data['serial_number'],
                    fw_version=data['fw_version'],
                    calibration_date=data['calibration_date'],
                    instrument_type=data.get('instrument_type')
                )
                self.load_instruments()
            except ValueError as e: 
                QMessageBox.warning(self, "DATI NON VALIDI", str(e).upper())

    def delete_instrument(self):
        inst_id = self.get_selected_id()
        if not inst_id: return
        reply = QMessageBox.question(self, "CONFERMA ELIMINAZIONE", "SEI SICURO DI VOLER ELIMINARE LO STRUMENTO SELEZIONATO?")
        if reply == QMessageBox.Yes: 
            services.delete_instrument(inst_id)
            self.load_instruments()
            
    def set_default(self):
        inst_id = self.get_selected_id()
        if not inst_id: return
        services.set_default_instrument(inst_id)
        self.load_instruments()