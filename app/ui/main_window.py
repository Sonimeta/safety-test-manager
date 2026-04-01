import shutil
import qtawesome as qta
from datetime import date, timedelta, datetime
import logging, pandas as pd
import json
import sys
import os   
import socket
import platform
import ctypes
from urllib.parse import urlparse
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QComboBox, QGroupBox, QFormLayout, QMessageBox, QFileDialog, 
    QStyle, QStatusBar, QGridLayout, QListWidget, QListWidgetItem, QLineEdit, QDialog, QMenu, QInputDialog, QCheckBox, QTableWidgetItem,
    QScrollArea, QSplitter, QFrame, QButtonGroup, QRadioButton, QProgressDialog, QDialogButtonBox)
from PySide6.QtGui import QAction, QIcon, QFont, QPalette, QColor
from PySide6.QtCore import Qt, QSettings, QDate, QCoreApplication, QThread, QProcess, QObject, Signal, QTimer
from app.data_models import AppliedPart
from app.ui.dialogs.user_manager_dialog import UserManagerDialog
from app.ui.dialogs.correction_dialog import CorrectionDialog
from app.ui.dialogs.stats_dashboard_dialog import StatsDashboardDialog
from app.ui.dialogs.advanced_search_dialog import AdvancedSearchDialog

# La main_window importa solo i moduli necessari per la UI e i servizi
from app import auth_manager, config, services
from app.config import SYNC_INTERVAL_MINUTES
from app.ui.dialogs.utility_dialogs import (
    AppliedPartsOrderDialog,
    GlobalSearchDialog,
    DuplicateDevicesDialog,
    DeviceDataQualityDialog,
    AdvancedReportDialog,
)
from app.ui.state_manager import AppState, StateManager
from app.updater import UpdateChecker
from app.ui.dialogs.update_dialog import UpdateDialog
from app.ui.dialogs.changelog_dialog import ChangelogDialog
from app.ui.dialogs.utility_dialogs import ExportCustomerSelectionDialog, SingleCalendarRangeDialog
from app.ui.overlay_widget import OverlayWidget
from app.ui.widgets import FunctionalTestRunnerWidget, TestRunnerWidget
from app.backup_manager import restore_from_backup
from app.ui.dialogs import (DbManagerDialog, VisualInspectionDialog, DeviceDialog, 
                            InstrumentManagerDialog, InstrumentSelectionDialog)
from app.ui.dialogs.expiring_devices_dialog import ExpiringDevicesDialog
from app.workers.sync_worker import SyncWorker
from app.workers.bulk_report_worker import BulkReportWorker
from app import auth_manager
from app.ui.dialogs.signature_manager_dialog import SignatureManagerDialog
from app.hardware.fluke_esa612 import FlukeESA612
from app.ui.dialogs.profile_manager_dialog import ProfileManagerDialog
from app.ui.dialogs.functional_profile_manager_dialog import FunctionalProfileManagerDialog
from app.ui.dialogs.qr_device_scanner_dialog import QRDeviceScannerDialog
from app.config import LOG_DIR
import database
from app.workers.table_export_worker import InventoryExportWorker
from PySide6.QtCore import QThread


class MainWindow(QMainWindow):
    # Segnale per ricezione scansioni QR (thread-safe)
    _qr_code_received = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # Abilita il maiuscolo automatico per questa finestra
        self.setProperty("_stm_uppercase_window", True)
        self.setWindowTitle(f"Safety Test Manager - {config.VERSIONE}")
        app_icon = QIcon("logo.png") 
        self.setWindowIcon(app_icon)
        # Imposta dimensione minima ragionevole per evitare warning di geometria
        # quando lo schermo è più piccolo della somma dei widget
        self.setMinimumSize(1024, 700)
        self.setWindowState(Qt.WindowMaximized)
        
        self.settings = QSettings("ELSON META", "SafetyTester")
        
        # Carica il tema salvato o usa quello di default (light)
        self.current_theme = self.settings.value("theme", "light")
        self.apply_theme(self.current_theme)
        self.logo_path = self.settings.value("logo_path", "")
        self.relogin_requested = False
        self.restart_after_sync = False
        self._auto_sync_started = False  # Flag per distinguere la sync automatica da quella manuale
        self.current_mti_info = None
        self.current_technician_name = ""
        self.test_runner_widget = None

        # Intervallo selezionabile per i filtri verifiche dispositivi (default: ultimi 60 giorni)
        self.device_filter_end_date = date.today()
        self.device_filter_start_date = self.device_filter_end_date - timedelta(days=60)
        
        # Scanner QR in background
        self.qr_scanner_server = None
        self.qr_scanner_dialog = None
        self._phone_scan_callback = None  # Intercept callback per DeviceDialog UDI scan
        
        # Connetti il segnale per ricezione QR thread-safe
        self._qr_code_received.connect(self._on_qr_scan_received)
        
        # Inizializza widget dummy per compatibilità con codice legacy
        self._init_legacy_widgets()

        # Flag sincronizzazione automatica (resettato ad ogni avvio)
        self._auto_sync_disabled = False

        # --- INIZIO MODIFICA: Integrazione StateManager ---
        self.state_manager = StateManager()
        self.state_manager.state_changed.connect(self.handle_state_change)
        self.state_manager.message_changed.connect(self.handle_state_message_change)

        # Crea l'overlay come figlio della main window
        self.overlay = OverlayWidget(self)
        # --- FINE MODIFICA ---

        self.create_menu_bar()
        # Aggiorna le icone del menu dopo la creazione per applicare il tema corretto
        self._update_menu_icons(self.current_theme)
        self.setStatusBar(QStatusBar(self))
        
        # Indicatore sync automatica disattivata (permanente nella status bar)
        self._auto_sync_status_label = QLabel("")
        self._auto_sync_status_label.setStyleSheet(
            "color: #dc2626; font-weight: bold; padding: 0 12px;"
        )
        self.statusBar().addPermanentWidget(self._auto_sync_status_label)
        self._auto_sync_status_label.hide()
        
        # Indicatore conflitti nella status bar
        self._setup_conflict_indicator()

        # Indicatore/toggle server QR nella status bar (visibile da qualsiasi schermata)
        self._setup_qr_server_statusbar()

        main_widget = QWidget()
        self.main_layout = QHBoxLayout(main_widget)
        self.setCentralWidget(main_widget)

        self.create_left_panel()
        self.create_right_panel()

        self.apply_permissions()
        self.load_all_data()
        
        # Controlla e mostra il changelog se necessario
        QTimer.singleShot(1000, self._check_and_show_changelog)
        
        # Avvia una sincronizzazione automatica all'avvio se è disponibile la rete
        QTimer.singleShot(3000, self._auto_sync_on_startup)
        
        # --- INIZIO AGGIUNTA: Timer per sincronizzazione periodica in background ---
        self._setup_periodic_sync_timer()
    
    def _init_legacy_widgets(self):
        """Inizializza widget dummy per compatibilità con codice legacy."""
        # Crea widget nascosti per mantenere compatibilità
        self.destination_selector = QComboBox()
        self.device_selector = QComboBox()
        self.device_verification_filter_combo = QComboBox()

    def create_menu_bar(self):
        menubar = self.menuBar()

        # ===================== MENU FILE =====================
        file_menu = menubar.addMenu("&File")

        # Esporta inventario cliente
        self.export_inventory_action = QAction(qta.icon('fa5s.file-excel'), "Esporta Inventario Cliente...", self)
        self.export_inventory_action.triggered.connect(self.export_customer_inventory)
        file_menu.addAction(self.export_inventory_action)

        # Esporta file di log
        self.export_log_action = QAction(qta.icon('fa5s.file-alt'), "Esporta File Log...", self)
        self.export_log_action.triggered.connect(self.export_log_file)
        file_menu.addAction(self.export_log_action)

        file_menu.addSeparator()

        # Logout
        self.logout_action = QAction(qta.icon('fa5s.sign-out-alt'), "Esci", self)
        self.logout_action.triggered.connect(self.logout)
        file_menu.addAction(self.logout_action)

        # ===================== MENU SINCRONIZZAZIONE / SISTEMA =====================
        sync_menu = menubar.addMenu("&Sincronizzazione")

        self.full_sync_action = QAction(qta.icon('fa5s.server'), "Sincronizza Tutto (Reset Locale)...", self)
        self.full_sync_action.triggered.connect(lambda: self.run_synchronization(full_sync=True))
        sync_menu.addAction(self.full_sync_action)

        self.force_push_action = QAction(qta.icon('fa5s.cloud-upload-alt'), "Forza Upload (tutti i dati)...", self)
        self.force_push_action.triggered.connect(self.confirm_and_force_push)
        sync_menu.addAction(self.force_push_action)

        self.view_conflicts_action = QAction(qta.icon('fa5s.exclamation-triangle'), "Gestisci Conflitti...", self)
        self.view_conflicts_action.triggered.connect(self._open_conflict_resolution_panel)
        sync_menu.addAction(self.view_conflicts_action)

        sync_menu.addSeparator()

        # Toggle sincronizzazione automatica
        self.disable_auto_sync_action = QAction(qta.icon('fa5s.pause-circle'), "Disattiva Sincronizzazione Automatica", self)
        self.disable_auto_sync_action.setCheckable(True)
        self.disable_auto_sync_action.setChecked(False)
        self.disable_auto_sync_action.toggled.connect(self._toggle_auto_sync)
        sync_menu.addAction(self.disable_auto_sync_action)

        sync_menu.addSeparator()

        # Operazioni di manutenzione avanzata
        self.ripristina_db_action = QAction(qta.icon('fa5s.database'), "Ripristina Database...", self)
        self.ripristina_db_action.triggered.connect(self.restore_database)
        sync_menu.addAction(self.ripristina_db_action)

        # ===================== MENU DATI E STRUMENTI =====================
        data_menu = menubar.addMenu("&Dati / Strumenti")

        self.advanced_search_action = QAction(qta.icon('fa5s.search'), "Ricerca Avanzata...", self)
        self.advanced_search_action.triggered.connect(self.open_advanced_search)
        data_menu.addAction(self.advanced_search_action)

        self.advanced_report_action = QAction(qta.icon('fa5s.file-pdf'), "Genera Report...", self)
        self.advanced_report_action.triggered.connect(self.open_advanced_report_dialog)
        data_menu.addAction(self.advanced_report_action)

        data_menu.addSeparator()

        self.correction_action = QAction(qta.icon('fa5s.magic'), "Correggi Descrizioni Dispositivi...", self)
        self.correction_action.triggered.connect(self.open_correction_dialog)
        data_menu.addAction(self.correction_action)

        # Controllo duplicati e qualità dati dispositivi
        data_menu.addSeparator()

        self.duplicates_action = QAction(qta.icon('fa5s.clone'), "Trova Dispositivi Duplicati...", self)
        self.duplicates_action.triggered.connect(self.open_duplicate_devices_dialog)
        data_menu.addAction(self.duplicates_action)

        self.data_quality_action = QAction(qta.icon('fa5s.check-circle'), "Controllo Qualità Dati Dispositivi...", self)
        self.data_quality_action.triggered.connect(self.open_device_data_quality_dialog)
        data_menu.addAction(self.data_quality_action)

        data_menu.addSeparator()

        # Dashboard statistiche e log attività
        self.stats_action = QAction(qta.icon('fa5s.chart-bar'), "Dashboard Statistiche...", self)
        self.stats_action.triggered.connect(self.open_stats_dashboard)
        data_menu.addAction(self.stats_action)

        self.audit_log_action = QAction(qta.icon('fa5s.history'), "Log Attività (Chi ha fatto cosa)...", self)
        self.audit_log_action.triggered.connect(self.open_audit_log)
        data_menu.addAction(self.audit_log_action)

        # ===================== MENU IMPOSTAZIONI =====================
        settings_menu = menubar.addMenu("&Impostazioni")

        self.set_com_port_action = QAction(qta.icon('fa5s.plug'), "Imposta Porta COM...", self)
        self.set_com_port_action.triggered.connect(self.configure_com_port)
        settings_menu.addAction(self.set_com_port_action)

        self.manage_instruments_action = QAction(qta.icon('fa5s.tools'), "Gestisci Strumenti di Misura...", self)
        self.manage_instruments_action.triggered.connect(self.open_instrument_manager)
        settings_menu.addAction(self.manage_instruments_action)

        settings_menu.addSeparator()

        self.set_logo_action = QAction(qta.icon('fa5s.image'), "Imposta Logo Azienda...", self)
        self.set_logo_action.triggered.connect(self.set_company_logo)
        settings_menu.addAction(self.set_logo_action)
        
        self.manage_users_action = QAction(qta.icon('fa5s.users-cog'), "Gestisci Utenti...", self)
        self.manage_users_action.triggered.connect(self.open_user_manager)
        settings_menu.addAction(self.manage_users_action)

        self.manage_profiles_action = QAction(qta.icon('fa5s.clipboard-list'), "Gestisci Profili...", self)
        self.manage_profiles_action.triggered.connect(self.open_profile_manager)
        settings_menu.addAction(self.manage_profiles_action)

        self.manage_functional_profiles_action = QAction(qta.icon('fa5s.heartbeat'), "Gestisci Profili Funzionali...", self)
        self.manage_functional_profiles_action.triggered.connect(self.open_functional_profile_manager)
        settings_menu.addAction(self.manage_functional_profiles_action)

        self.manage_signature_action = QAction(qta.icon('fa5s.file-signature'), "Gestisci Firma...", self)
        self.manage_signature_action.triggered.connect(self.open_signature_manager)
        settings_menu.addAction(self.manage_signature_action)

        settings_menu.addSeparator()

        # Gestione dati eliminati (solo admin)
        self.deleted_data_action = QAction(qta.icon('fa5s.trash-alt'), "Gestione Dati Eliminati...", self)
        self.deleted_data_action.triggered.connect(self.open_deleted_data_manager)
        settings_menu.addAction(self.deleted_data_action)

        settings_menu.addSeparator()

        # Cambia tema
        self.theme_action = QAction(qta.icon('fa5s.palette'), "Cambia Tema", self)
        self.theme_action.triggered.connect(self.toggle_theme)
        settings_menu.addAction(self.theme_action)
        self.update_theme_action_text()

        # ===================== MENU AIUTO =====================
        help_menu = menubar.addMenu("&Aiuto")

        self.changelog_action = QAction(qta.icon('fa5s.list-alt'), "Visualizza Changelog...", self)
        self.changelog_action.triggered.connect(self.show_changelog)
        help_menu.addAction(self.changelog_action)

        help_menu.addSeparator()

        self.update_action = QAction(qta.icon('fa5s.download'), "Controlla Aggiornamenti...", self)
        self.update_action.triggered.connect(self.check_for_updates)
        help_menu.addAction(self.update_action)

        help_menu.addSeparator()

        self.about_action = QAction(qta.icon('fa5s.info-circle'), "Informazioni su Safety Test Manager...", self)
        self.about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(self.about_action)

    def open_duplicate_devices_dialog(self):
        """Apre la finestra per la gestione dei dispositivi duplicati."""
        dialog = DuplicateDevicesDialog(self)
        dialog.exec()

    def open_device_data_quality_dialog(self):
        """Apre la finestra per il controllo qualità dei dati dispositivi."""
        dialog = DeviceDataQualityDialog(self)
        dialog.exec()
    
    def open_stats_dashboard(self):
        """Apre la finestra di dialogo con le statistiche."""
        dialog = StatsDashboardDialog(self)
        dialog.exec()
    
    def open_audit_log(self):
        """Apre la finestra di dialogo con il log delle attività."""
        from app.ui.dialogs.audit_log_dialog import AuditLogDialog
        dialog = AuditLogDialog(self)
        dialog.exec()

    def open_deleted_data_manager(self):
        """Apre la finestra di gestione dati eliminati (solo admin)."""
        from app.ui.dialogs.deleted_data_dialog import DeletedDataDialog
        dialog = DeletedDataDialog(self)
        dialog.exec()

    # ================== SINCRONIZZAZIONE AUTOMATICA ALL'AVVIO ==================
    def _has_network_connectivity(self) -> bool:
        """
        Controlla in modo veloce se il PC è connesso a una rete
        e se il server di sincronizzazione è raggiungibile a livello di rete.
        
        Non mostra messaggi all'utente: serve solo per decidere se avviare
        la sincronizzazione automatica all'avvio.
        """
        try:
            # 1) Su Windows chiediamo prima allo stesso sistema operativo se c'è rete
            if platform.system() == "Windows":
                try:
                    flags = ctypes.c_ulong()
                    # InternetGetConnectedState ritorna 0 se non c'è nessuna connessione
                    if not ctypes.windll.wininet.InternetGetConnectedState(ctypes.byref(flags), 0):
                        logging.info("Windows riporta: nessuna connessione di rete attiva. Skip sync automatica.")
                        return False
                except Exception as e:
                    # Se questo controllo fallisce, proseguiamo comunque con il check TCP
                    logging.warning(f"Impossibile verificare lo stato rete via Windows API: {e}")

            # 2) Verifica connessione TCP verso il server configurato
            parsed = urlparse(config.SERVER_URL)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if not host:
                logging.warning(f"SERVER_URL non valido: {config.SERVER_URL}")
                return False

            logging.info(f"Verifica connessione TCP verso {host}:{port} per sync automatica...")
            with socket.create_connection((host, port), timeout=3):
                logging.info("Connessione di rete al server di sincronizzazione riuscita.")
                return True
        except Exception as e:
            logging.warning(f"Nessuna connessione al server sync all'avvio ({e}). Sincronizzazione automatica saltata.")
            return False

    def _check_and_show_changelog(self):
        """
        Controlla se c'è una nuova versione e mostra il changelog se necessario.
        """
        try:
            # Ottieni l'ultima versione visualizzata
            last_viewed_version = self.settings.value("last_changelog_version", "")
            current_version = config.VERSIONE
            
            # Se la versione corrente è diversa da quella visualizzata, mostra il changelog
            if last_viewed_version != current_version:
                dialog = ChangelogDialog(self)
                dialog.exec()
                
                # Salva la versione corrente come ultima visualizzata
                self.settings.setValue("last_changelog_version", current_version)
                logging.info(f"Changelog mostrato per la versione {current_version}")
        except Exception as e:
            logging.error(f"Errore nel controllo del changelog: {e}", exc_info=True)
            # Non bloccare l'avvio dell'app se c'è un errore
    
    def show_changelog(self):
        """Mostra il changelog manualmente dal menu."""
        dialog = ChangelogDialog(self)
        dialog.exec()

    def _show_about_dialog(self):
        """Mostra la finestra Informazioni con versione, autore e licenze terze parti."""
        import os
        import sys

        licenses_text = ""
        # Supporta sia esecuzione da sorgente che da PyInstaller frozen
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        licenses_path = os.path.join(base_dir, "THIRD_PARTY_LICENSES.txt")
        try:
            with open(licenses_path, "r", encoding="utf-8") as f:
                licenses_text = f.read()
        except Exception:
            licenses_text = "(File THIRD_PARTY_LICENSES.txt non trovato)"

        dialog = QDialog(self)
        dialog.setWindowTitle("Informazioni su Safety Test Manager")
        dialog.resize(700, 550)
        layout = QVBoxLayout(dialog)

        # Header con logo e info
        header = QLabel(
            f"<h2>Safety Test Manager</h2>"
            f"<p><b>Versione:</b> {config.VERSIONE}</p>"
            f"<p><b>Sviluppato da:</b> ELSON META</p>"
            f"<p><b>© 2026</b> — Tutti i diritti riservati</p>"
            f"<hr>"
            f"<p style='color: gray; font-size: 11px;'>"
            f"Questo software utilizza librerie open-source di terze parti.<br>"
            f"PySide6 è utilizzato sotto licenza LGPLv3. "
            f"Consulta le licenze complete qui sotto.</p>"
        )
        header.setTextFormat(Qt.RichText)
        header.setWordWrap(True)
        layout.addWidget(header)

        # Area scrollabile con le licenze
        licenses_label = QLabel("<b>Licenze librerie di terze parti:</b>")
        layout.addWidget(licenses_label)

        from PySide6.QtWidgets import QTextEdit
        text_area = QTextEdit()
        text_area.setReadOnly(True)
        text_area.setPlainText(licenses_text)
        text_area.setFont(QApplication.font())
        layout.addWidget(text_area, 1)

        # Pulsante chiudi
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.accepted.connect(dialog.accept)
        layout.addWidget(btn_box)

        dialog.exec()

    def _setup_periodic_sync_timer(self):
        """
        Configura il timer per la sincronizzazione periodica in background.
        L'intervallo è configurabile da config.ini nella sezione [sync].
        """
        self.periodic_sync_timer = QTimer(self)
        self.periodic_sync_timer.timeout.connect(self._periodic_background_sync)
        
        if SYNC_INTERVAL_MINUTES > 0:
            interval_ms = SYNC_INTERVAL_MINUTES * 60 * 1000  # Converti minuti in millisecondi
            self.periodic_sync_timer.start(interval_ms)
            logging.info(f"Timer sincronizzazione periodica avviato: ogni {SYNC_INTERVAL_MINUTES} minuti")
        else:
            logging.info("Sincronizzazione periodica disabilitata (interval_minutes = 0)")
    
    def _toggle_auto_sync(self, disabled):
        """Attiva/disattiva la sincronizzazione automatica (periodica e all'avvio)."""
        self._auto_sync_disabled = disabled
        if disabled:
            if hasattr(self, 'periodic_sync_timer') and self.periodic_sync_timer.isActive():
                self.periodic_sync_timer.stop()
            logging.info("Sincronizzazione automatica DISATTIVATA dall'utente.")
            self._auto_sync_status_label.setText("⏸ Sincronizzazione automatica disattivata")
            self._auto_sync_status_label.show()
        else:
            # Riavvia il timer se l'intervallo è configurato
            if SYNC_INTERVAL_MINUTES > 0 and hasattr(self, 'periodic_sync_timer'):
                interval_ms = SYNC_INTERVAL_MINUTES * 60 * 1000
                self.periodic_sync_timer.start(interval_ms)
            logging.info("Sincronizzazione automatica RIATTIVATA dall'utente.")
            self._auto_sync_status_label.hide()

    def _periodic_background_sync(self):
        """
        Esegue una sincronizzazione in background se le condizioni lo permettono.
        Viene chiamata periodicamente dal timer.
        Non mostra messaggi di errore all'utente per non disturbarlo.
        """
        try:
            # Non sincronizzare se disattivata dall'utente
            if self._auto_sync_disabled:
                logging.debug("Sincronizzazione periodica saltata: disattivata dall'utente")
                return
            # Non sincronizzare se l'app non è in stato IDLE
            if not self.state_manager.can_sync():
                logging.debug("Sincronizzazione periodica saltata: app non in stato IDLE")
                return
            
            # Non sincronizzare se la rete non è disponibile
            if not self._has_network_connectivity():
                logging.debug("Sincronizzazione periodica saltata: rete non disponibile")
                return
            
            logging.info("Avvio sincronizzazione periodica in background...")
            # Segna che questa sincronizzazione è stata avviata in automatico
            self._auto_sync_started = True
            # Avvia una sincronizzazione incrementale silenziosa
            self.run_synchronization(full_sync=False)
            
        except Exception as e:
            # Qualsiasi errore qui non deve bloccare l'app
            logging.error(f"Errore durante la sincronizzazione periodica: {e}", exc_info=True)
    
    def _auto_sync_on_startup(self):
        """
        Avvia automaticamente una sincronizzazione (incrementale) all'avvio,
        solo se:
        - l'app è in stato IDLE
        - il server di sincronizzazione è raggiungibile.
        - la sincronizzazione automatica non è stata disattivata.
        """
        try:
            # Non sincronizzare se disattivata dall'utente
            if self._auto_sync_disabled:
                logging.info("Sincronizzazione automatica all'avvio saltata: disattivata dall'utente.")
                return

            # Evita di avviare la sync se l'app non è in stato IDLE
            if not self.state_manager.can_sync():
                logging.info("Stato non IDLE all'avvio, sincronizzazione automatica non eseguita.")
                return

            # Controllo rete/server
            if not self._has_network_connectivity():
                return

            logging.info("Rete disponibile all'avvio: avvio sincronizzazione automatica (incrementale).")
            # Segna che questa sincronizzazione è stata avviata in automatico
            self._auto_sync_started = True
            # Avvia una sincronizzazione NORMALE (non full_sync) senza chiedere conferma
            self.run_synchronization(full_sync=False)
        except Exception as e:
            # Qualsiasi errore qui non deve bloccare l'avvio dell'app
            logging.error(f"Errore durante la sincronizzazione automatica all'avvio: {e}", exc_info=True)

    def open_advanced_search(self):
        """
        Apre la finestra di dialogo per la ricerca avanzata.
        """
        QApplication.setOverrideCursor(Qt.WaitCursor)
        dialog = AdvancedSearchDialog(self)
        QApplication.restoreOverrideCursor()
        
        if dialog.exec() == QDialog.Accepted:
            selected_data = dialog.selected_verification_data
            if selected_data:
                # Navigate to the DbManagerDialog and then to the specific verification
                self.open_db_manager(navigate_to={
                    'type': 'verification',
                    'device_id': selected_data['device_id'],
                    'verification_id': selected_data['verification_id']
                })

    def open_advanced_report_dialog(self):
        dialog = AdvancedReportDialog(self)
        if not dialog.exec():
            return
        options = dialog.get_options()
        start_date = options["start_date"]
        end_date = options["end_date"]
        scope = options["scope"]
        customer_id = options["customer_id"]
        destination_id = options["destination_id"]

        all_verifications = []
        if options["include_electrical"]:
            if scope == "all":
                rows = database.get_verifications_by_date_range(start_date, end_date)
            elif scope == "customer":
                rows = database.get_verifications_for_customer_by_date_range(customer_id, start_date, end_date)
            else:
                rows = database.get_verifications_for_destination_by_date_range(destination_id, start_date, end_date)
            electrical_verifs = [dict(r) for r in rows]
            if options["latest_only"]:
                electrical_verifs = self._filter_latest_verifications(electrical_verifs)
            for verif in electrical_verifs:
                verif["verification_type"] = "ELETTRICA"
                all_verifications.append(verif)

        if options["include_functional"]:
            if scope == "all":
                rows = database.get_functional_verifications_by_date_range(start_date, end_date)
            elif scope == "customer":
                rows = database.get_functional_verifications_for_customer_by_date_range(customer_id, start_date, end_date)
            else:
                rows = database.get_functional_verifications_for_destination_by_date_range(destination_id, start_date, end_date)
            functional_verifs = [dict(r) for r in rows]
            if options["latest_only"]:
                functional_verifs = self._filter_latest_verifications(functional_verifs)
            for verif in functional_verifs:
                verif["verification_type"] = "FUNZIONALE"
                all_verifications.append(verif)

        if not all_verifications:
            return QMessageBox.information(self, "NESSUNA VERIFICA", "NESSUNA VERIFICA TROVATA NEL PERIODO SELEZIONATO.")

        output_folder = options["output_folder"]
        naming_format = options["naming_format"]
        report_settings = {"logo_path": self.logo_path}
        needs_cover_info = (
            options.get("merge_into_one")
            or options.get("export_cover_single")
            or options.get("export_table_single")
        )
        cover_info = self._build_advanced_report_cover_info(options, all_verifications, force=needs_cover_info)

        self.advanced_report_progress = QProgressDialog("GENERAZIONE REPORT...", "ANNULLA", 0, 100, self)
        self.advanced_report_progress.setWindowModality(Qt.WindowModal)
        self.advanced_report_thread = QThread()
        self.advanced_report_worker = BulkReportWorker(
            all_verifications,
            output_folder,
            report_settings,
            naming_format,
            merge_into_one=options["merge_into_one"],
            merged_output_path=options["merged_output_path"],
            merged_intro_mode=options.get("merged_intro_mode", "cover_and_table"),
            export_cover_single=options.get("export_cover_single", False),
            export_table_single=options.get("export_table_single", False),
            keep_individual_reports=options.get("keep_individual_reports", True),
            cover_info=cover_info,
        )
        self.advanced_report_worker.moveToThread(self.advanced_report_thread)
        self.advanced_report_progress.canceled.connect(self.advanced_report_worker.cancel)
        self.advanced_report_worker.progress_updated.connect(self._on_advanced_report_progress)
        self.advanced_report_worker.finished.connect(self._on_advanced_report_finished)
        self.advanced_report_worker.finished.connect(self.advanced_report_thread.quit)
        self.advanced_report_worker.finished.connect(self.advanced_report_worker.deleteLater)
        self.advanced_report_thread.finished.connect(self.advanced_report_thread.deleteLater)
        self.advanced_report_thread.finished.connect(self.advanced_report_progress.close)
        self.advanced_report_thread.started.connect(self.advanced_report_worker.run)
        self.advanced_report_progress.show()
        self.advanced_report_thread.start()

    def _filter_latest_verifications(self, verifications: list) -> list:
        latest_by_device = {}
        for verif in verifications:
            device_id = verif.get("device_id")
            if not device_id:
                continue
            if device_id not in latest_by_device:
                latest_by_device[device_id] = verif
                continue
            current_date = latest_by_device[device_id].get("verification_date", "")
            new_date = verif.get("verification_date", "")
            if new_date > current_date:
                latest_by_device[device_id] = verif
        return list(latest_by_device.values())

    def _build_advanced_report_cover_info(self, options: dict, verifications: list, force: bool = False) -> dict:
        if not options.get("merge_into_one") and not force:
            return {}

        customer_name = "TUTTI I CLIENTI"
        destination_name = "TUTTE LE DESTINAZIONI"

        scope = options.get("scope")
        customer_id = options.get("customer_id")
        destination_id = options.get("destination_id")

        try:
            if scope == "customer" and customer_id:
                cust = database.get_customer_by_id(customer_id)
                if cust:
                    customer_name = str(cust["name"]).upper()
                destination_name = "TUTTE LE DESTINAZIONI"
            elif scope == "destination" and destination_id:
                dest = database.get_destination_by_id(destination_id)
                if dest:
                    destination_name = str(dest["name"]).upper()
                    cust = database.get_customer_by_id(dest["customer_id"])
                    if cust:
                        customer_name = str(cust["name"]).upper()
        except Exception as e:
            logging.warning(f"Impossibile determinare cliente/destinazione per il frontespizio: {e}")

        electrical_count = sum(1 for v in verifications if v.get("verification_type") == "ELETTRICA")
        functional_count = sum(1 for v in verifications if v.get("verification_type") == "FUNZIONALE")

        def _normalize_status(value: str) -> str:
            return str(value or "").strip().upper()
        
        # Conteggio dispositivi unici (apparecchi controllati)
        unique_devices = set(v.get("device_id") for v in verifications if v.get("device_id"))
        devices_count = len(unique_devices)
        
        # Conteggio verifiche conformi e non conformi
        conformi_count = sum(
            1 for v in verifications
            if _normalize_status(v.get("overall_status")) in ("PASSATO", "CONFORME")
        )
        conformi_con_annotazione_count = sum(
            1 for v in verifications
            if _normalize_status(v.get("overall_status")) == "CONFORME CON ANNOTAZIONE"
        )
        non_conformi_count = sum(
            1 for v in verifications
            if _normalize_status(v.get("overall_status")) in ("FALLITO", "NON CONFORME")
        )

        return {
            "customer_name": customer_name,
            "destination_name": destination_name,
            "destination_address": dict(database.get_destination_by_id(destination_id) or {}).get("address", "") if destination_id else "",
            "start_date": options.get("start_date"),
            "end_date": options.get("end_date"),
            "total_count": len(verifications),  # Totale verifiche
            "devices_count": devices_count,      # Apparecchi unici controllati
            "electrical_count": electrical_count,
            "functional_count": functional_count,
            "conformi_count": conformi_count,
            "conformi_con_annotazione_count": conformi_con_annotazione_count,
            "non_conformi_count": non_conformi_count,
            "logo_path": self.logo_path,
            "created_by": self.current_technician_name or "",
        }

    def _on_advanced_report_progress(self, percent, message):
        if hasattr(self, "advanced_report_progress"):
            self.advanced_report_progress.setValue(percent)
            self.advanced_report_progress.setLabelText(message)

    def _on_advanced_report_finished(self, success_count, failed_reports):
        summary = f"GENERAZIONE COMPLETATA.\n- REPORT CREATI: {success_count}"
        if failed_reports:
            summary += f"\n- ERRORI: {len(failed_reports)}"
        msg_box = QMessageBox(QMessageBox.Information, "OPERAZIONE TERMINATA", summary, parent=self)
        if failed_reports:
            msg_box.setDetailedText("Dettaglio errori:\n" + "\n".join(failed_reports))
        msg_box.exec()
    
    def export_customer_inventory(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        dialog = ExportCustomerSelectionDialog(self)
        if dialog.exec():
            customer_id = dialog.get_selected_customer()
            customer = database.get_customer_by_id(customer_id)
            
            # Create worker and thread
            self.export_thread = QThread()
            self.export_worker = InventoryExportWorker(customer_id, customer['name'])
            self.export_worker.moveToThread(self.export_thread)
            
            # Connect signals - Fixed method name to match definition
            self.export_thread.started.connect(self.export_worker.run)
            self.export_worker.finished.connect(self.on_export_finished)  # Changed from handle_export_finished
            self.export_worker.error.connect(self.on_export_error)  # Make sure this matches too
            self.export_worker.get_save_path.connect(self.get_inventory_save_path)
            self.export_worker.finished.connect(self.export_thread.quit)
            self.export_worker.finished.connect(self.export_worker.deleteLater)
            self.export_thread.finished.connect(self.export_thread.deleteLater)
            
            # Start export
            self.export_thread.start()
        QApplication.restoreOverrideCursor()

    def get_inventory_save_path(self, suggested_name):
        """Handle save path selection for inventory export."""
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salva Inventario",
            os.path.join(os.path.expanduser("~"), "Desktop", suggested_name),
            "Excel Files (*.xlsx)"
        )
        
        if save_path:
            # Ensure .xlsx extension
            if not save_path.endswith('.xlsx'):
                save_path += '.xlsx'
                
        # Send path back to worker
        self.export_worker.save_path = save_path
        self.export_worker.save_path_received.emit(save_path)

    def on_export_finished(self, filepath):
        """Handle successful export."""
        QMessageBox.information(
            self,
            "Esportazione Completata",
            f"L'inventario è stato esportato in:\n{filepath}"
        )

    def on_export_error(self, error_msg):
        """Handle export error."""
        QMessageBox.critical(
            self,
            "Errore Esportazione",
            f"Si è verificato un errore durante l'esportazione:\n{error_msg}"
        )
    
    def export_log_file(self):
        """
        Esporta il file di log del giorno corrente in una posizione scelta dall'utente.
        """
        try:
            # --- INIZIO LOGICA DINAMICA ---
            # 1. Ottieni la data corrente in formato YYYY-MM-DD
            current_date = datetime.now().strftime("%Y-%m-%d")
            
            # 2. Costruisci il nome del file di log atteso per oggi
            log_filename = f"app_{current_date}.log"
            
            # 3. Combina la cartella dei log con il nome del file per ottenere il percorso completo
            log_file_path = os.path.join(LOG_DIR, log_filename)
            # --- FINE LOGICA DINAMICA ---

            # Controlla se il file di log di oggi esiste
            if not os.path.exists(log_file_path):
                QMessageBox.warning(self, "File non Trovato", f"Il file di log per oggi non è stato trovato.\nPercorso cercato: {log_file_path}")
                return

            # Apre la finestra di dialogo "Salva con nome"
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "Salva File Log",
                log_filename, # Propone il nome del file di oggi come default
                "Log Files (*.log);;All Files (*)"
            )

            # Se l'utente annulla, esce
            if not save_path:
                return

            # Copia il file nella destinazione scelta
            shutil.copy(log_file_path, save_path)
            QMessageBox.information(self, "Esportazione Riuscita", f"Il file di log è stato salvato con successo in:\n{save_path}")

        except Exception as e:
            QMessageBox.critical(self, "Errore di Esportazione", f"Impossibile esportare il file di log.\nErrore: {e}")

    def check_for_updates(self):
        """Controlla la presenza di aggiornamenti e gestisce il processo."""
        if not config.UPDATE_URL:
            QMessageBox.information(self, "Aggiornamenti", "La funzione di aggiornamento non è configurata.")
            return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            checker = UpdateChecker(config.UPDATE_URL)
            update_info = checker.check_for_updates()
            QApplication.restoreOverrideCursor()

            if update_info:
                reply = QMessageBox.question(
                    self,
                    "Aggiornamento Disponibile",
                    f"È disponibile una nuova versione: <b>{update_info['latest_version']}</b>.<br>"
                    f"Versione installata: {config.VERSIONE}.<br><br>"
                    "Vuoi scaricarla e installarla ora?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    self.download_and_install_update(checker, update_info)
            else:
                QMessageBox.information(self, "Nessun Aggiornamento", "Il software è già aggiornato all'ultima versione.")

        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Errore Aggiornamento", str(e))

    def download_and_install_update(self, checker, update_info):
        dialog = UpdateDialog(checker, update_info, self)
        if dialog.exec() == QDialog.Accepted:
            UpdateChecker.run_updater_and_exit(dialog.updater_path)

    def create_left_panel(self):
        """Crea il pannello sinistro con statistiche e sessione."""
        left_panel_widget = QWidget()
        left_panel_widget.setMaximumWidth(400)
        left_layout = QVBoxLayout(left_panel_widget)
        left_layout.setSpacing(15)
        
        # Ricerca globale rapida in alto
        search_group = self._create_global_search_group()
        left_layout.addWidget(search_group)
        
        #sessione di verifica
        session_group = self._create_session_group()
        left_layout.addWidget(session_group)
        
        # Statistiche moderne (cards)
        stats_header = self._create_stats_cards()
        left_layout.addWidget(stats_header)
        
        # Pulsanti azioni con icone grandi
        actions_group = QGroupBox("⚡ Azioni Rapide")
        actions_layout = QVBoxLayout()
        
        self.manage_button = QPushButton(qta.icon('fa5s.database', scale_factor=1.2), " Gestione Anagrafiche")
        self.manage_button.setObjectName("secondaryButton")
        self.manage_button.setMinimumHeight(40)
        self.manage_button.clicked.connect(self.open_db_manager)
        
        self.sync_button = QPushButton(qta.icon('fa5s.sync-alt', scale_factor=1.2), " Sincronizza")
        self.sync_button.setObjectName("editButton")
        self.sync_button.setMinimumHeight(40)
        self.sync_button.clicked.connect(self.run_synchronization)
        
        actions_layout.addWidget(self.manage_button)
        actions_layout.addWidget(self.sync_button)
        actions_group.setLayout(actions_layout)
        left_layout.addWidget(actions_group)
        
        left_layout.addStretch()
        
        self.main_layout.addWidget(left_panel_widget, 1)
        
        # Aggiorna subito le statistiche
        self.update_dashboard()
    
    def _create_stats_cards(self):
        """Crea le cards moderne per le statistiche."""
        group = QGroupBox("📊 Panoramica")
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        # Container per le cards
        self.stats_layout = QVBoxLayout()
        
        # Crea placeholders per le cards
        self.total_card = QLabel()
        self.conformi_card = QLabel()
        self.non_conformi_card = QLabel()
        
        self.stats_layout.addWidget(self.total_card)
        self.stats_layout.addWidget(self.conformi_card)
        self.stats_layout.addWidget(self.non_conformi_card)
        
        layout.addLayout(self.stats_layout)
        group.setLayout(layout)
        
        return group

    def create_right_panel(self):
        """Crea il nuovo pannello centrale a 3 colonne per selezione intuitiva."""
        from PySide6.QtWidgets import QScrollArea, QSizePolicy
        
        # Variabili per tenere traccia delle selezioni
        self.selected_customer_id = None
        self.selected_destination_id = None
        self.selected_device_id = None
        
        # Container principale
        main_container = QWidget()
        self.right_layout = QVBoxLayout(main_container)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(10)
        
        # Contenitore per la selezione dispositivi
        self.selection_container = QWidget()
        selection_layout = QVBoxLayout(self.selection_container)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        selection_layout.setSpacing(10)
        self.selection_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # === SPLITTER A 3 COLONNE ===
        splitter = QSplitter(Qt.Horizontal)
        
        # COLONNA 1: CLIENTI
        self.customer_panel = self._create_customer_panel()
        splitter.addWidget(self.customer_panel)
        
        # COLONNA 2: DESTINAZIONI
        self.destination_panel = self._create_destination_panel()
        splitter.addWidget(self.destination_panel)
        
        # COLONNA 3: DISPOSITIVI
        self.device_panel = self._create_device_panel()
        splitter.addWidget(self.device_panel)
        
        # Imposta proporzioni iniziali
        splitter.setSizes([350, 350, 500])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        
        selection_layout.addWidget(splitter, 1)
        
        # === PANNELLO INFERIORE: DETTAGLI E AZIONI ===
        bottom_panel = self._create_bottom_action_panel()
        selection_layout.addWidget(bottom_panel)
        
        # Area scrollabile per gestire risoluzioni ridotte / ripristino layout
        self.selection_scroll_area = QScrollArea()
        self.selection_scroll_area.setWidgetResizable(True)
        self.selection_scroll_area.setFrameShape(QFrame.NoFrame)
        self.selection_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.selection_scroll_area.setWidget(self.selection_container)
        self.right_layout.addWidget(self.selection_scroll_area, 1)
        
        # Container per test runner (nascosto inizialmente)
        self.test_runner_container = QWidget()
        self.test_runner_layout = QVBoxLayout(self.test_runner_container)
        self.test_runner_container.hide()
        self.right_layout.addWidget(self.test_runner_container, 1)
        
        self.main_layout.addWidget(main_container, 3)
    
    def _create_global_search_group(self):
        """Crea il gruppo di ricerca rapida globale."""
        group = QGroupBox("🔍 Ricerca Rapida Globale")
        group.setObjectName("searchGroupBox")
        # Gli stili sono gestiti dal QSS del tema
        layout = QHBoxLayout(group)
        layout.setSpacing(10)
        
        # Campo di ricerca
        self.global_device_search_edit = QLineEdit()
        self.global_device_search_edit.setPlaceholderText("Ricerca rapida")
        self.global_device_search_edit.setMinimumHeight(45)
        self.global_device_search_edit.returnPressed.connect(self.perform_global_search)
        
        # Pulsante cerca (solo icona)
        search_btn = QPushButton(qta.icon('fa5s.search', scale_factor=1.0), "")
        search_btn.setObjectName("primaryButton")
        search_btn.setFixedSize(38, 38)
        search_btn.setToolTip("Cerca")
        search_btn.setStyleSheet("QPushButton { padding: 0px !important; margin: 0px !important; min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; }")
        search_btn.clicked.connect(self.perform_global_search)
        
        # Pulsante scansione QR da telefono (toggle)
        self.qr_scan_btn = QPushButton(qta.icon('fa5s.qrcode', scale_factor=1.0), "")
        self.qr_scan_btn.setObjectName("editButton")
        self.qr_scan_btn.setFixedSize(38, 38)
        self.qr_scan_btn.setCheckable(True)
        self.qr_scan_btn.setToolTip("📱 Click: Attiva/Disattiva scanner\nDoppio click: Mostra QR code")
        self.qr_scan_btn.setStyleSheet("QPushButton { padding: 0px !important; margin: 0px !important; min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; }")
        self.qr_scan_btn.clicked.connect(self._on_qr_button_clicked)
        
        # Indicatore stato scanner
        self.qr_status_indicator = QLabel("")
        self.qr_status_indicator.setFixedWidth(20)
        self.qr_status_indicator.setToolTip("Stato scanner QR")
        self.qr_status_indicator.setStyleSheet("QLabel { background-color: transparent!important; }") 
        
        layout.addWidget(self.global_device_search_edit, 1)
        layout.addWidget(search_btn)
        layout.addWidget(self.qr_scan_btn)
        layout.addWidget(self.qr_status_indicator)
        
        return group
    
    def _create_customer_panel(self):
        """Crea il pannello clienti (colonna 1)."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)
        
        # Header
        header = QLabel("👥 <b>Clienti</b>")
        header.setObjectName("panelHeader")
        layout.addWidget(header)
        
        # Barra di ricerca clienti
        self.customer_search = QLineEdit()
        self.customer_search.setPlaceholderText("🔍 Cerca cliente...")
        self.customer_search.setMinimumHeight(40)
        self.customer_search.textChanged.connect(self.filter_customers)
        layout.addWidget(self.customer_search)
        
        # Lista clienti
        self.customer_list = QListWidget()
        self.customer_list.setObjectName("panelListWidget")
        # Gli stili sono gestiti dal QSS del tema
        self.customer_list.itemClicked.connect(self.on_customer_selected)
        layout.addWidget(self.customer_list)
        
        # Contatore
        self.customer_count_label = QLabel("<i>0 clienti</i>")
        self.customer_count_label.setObjectName("panelCountLabel")
        layout.addWidget(self.customer_count_label)
        
        return panel
    
    def _create_destination_panel(self):
        """Crea il pannello destinazioni (colonna 2)."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)
        
        # Header
        header = QLabel("🏢 <b>Destinazioni</b>")
        header.setObjectName("panelHeader")
        layout.addWidget(header)
        
        # Barra di ricerca destinazioni
        self.destination_search = QLineEdit()
        self.destination_search.setPlaceholderText("🔍 Cerca destinazione...")
        self.destination_search.setMinimumHeight(40)
        self.destination_search.textChanged.connect(self.filter_destinations)
        layout.addWidget(self.destination_search)
        
        # Lista destinazioni
        self.destination_list = QListWidget()
        self.destination_list.setObjectName("panelListWidget")
        # Gli stili sono gestiti dal QSS del tema
        self.destination_list.itemClicked.connect(self.on_destination_selected_new)
        layout.addWidget(self.destination_list)
        
        # Contatore
        self.destination_count_label = QLabel("<i>Seleziona un cliente</i>")
        self.destination_count_label.setObjectName("panelCountLabel")
        layout.addWidget(self.destination_count_label)
        
        return panel
    
    def _create_device_panel(self):
        """Crea il pannello dispositivi (colonna 3)."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)
        
        # Header
        header = QLabel("🔧 <b>Dispositivi</b>")
        header.setObjectName("panelHeader")
        layout.addWidget(header)
        
        # Barra di ricerca dispositivi con pulsante aggiungi
        search_layout = QHBoxLayout()
        search_layout.setAlignment(Qt.AlignVCenter)
        search_layout.setSpacing(8)
        self.device_search = QLineEdit()
        self.device_search.setPlaceholderText("🔍 Cerca dispositivo, S/N, inv... (es. sn:123 inv:AMS)")
        self.device_search.setFixedHeight(40)  # Altezza fissa per allineamento
        self.device_search.textChanged.connect(self.filter_devices)
        search_layout.addWidget(self.device_search, 1)
        
        # Pulsante aggiungi dispositivo affianco alla ricerca
        add_device_btn = QPushButton(qta.icon('fa5s.plus'), "")
        add_device_btn.setObjectName("addButton")
        add_device_btn.setToolTip("Aggiungi nuovo dispositivo")
        add_device_btn.setFixedSize(40, 40)  # Stessa altezza del campo di ricerca
        add_device_btn.clicked.connect(self.quick_add_device)
        search_layout.addWidget(add_device_btn, 0, Qt.AlignVCenter)
        
        layout.addLayout(search_layout)
        
        # Filtro rapido avanzato
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Filtro:")
        self.device_verification_filter_combo = QComboBox()
        self.device_verification_filter_combo.addItem("🔍 Nessuna verifica eseguita", "UNVERIFIED_60")
        self.device_verification_filter_combo.addItem("🫀 Solo funzionale da eseguire", "ONLY_FUNCTIONAL_60")
        self.device_verification_filter_combo.addItem("⚡ Solo elettrica da eseguire", "ONLY_ELECTRICAL_60")
        self.device_verification_filter_combo.addItem("✅ Elettrica + Funzionale da completare", "BOTH_60")
        self.device_verification_filter_combo.addItem("📋 Tutti i dispositivi", "ALL")
        self.device_verification_filter_combo.setCurrentIndex(0)
        self.device_verification_filter_combo.setToolTip(
            "Filtra i dispositivi in base alle verifiche elettriche/funzionali nel periodo selezionato"
        )
        self.device_verification_filter_combo.currentIndexChanged.connect(self.reload_devices)

        self.device_period_button = QPushButton(qta.icon('fa5s.calendar-alt'), "")
        self.device_period_button.setObjectName("calendarFilterButton")
        self.device_period_button.clicked.connect(self.choose_device_filter_period)
        self._update_device_period_button_tooltip()

        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.device_verification_filter_combo, 1)
        filter_layout.addWidget(self.device_period_button, 0, Qt.AlignVCenter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Lista dispositivi
        self.device_list = QListWidget()
        self.device_list.setObjectName("panelListWidget")
        # Gli stili sono gestiti dal QSS del tema
        self.device_list.itemClicked.connect(self.on_device_selected_new)
        layout.addWidget(self.device_list)
        
        # Contatore
        self.device_count_label = QLabel("<i>Seleziona una destinazione</i>")
        self.device_count_label.setObjectName("panelCountLabel")
        layout.addWidget(self.device_count_label)
        
        return panel
    
    def _create_bottom_action_panel(self):
        """Crea il pannello inferiore con dettagli dispositivo e pulsanti azione."""
        panel = QGroupBox("📋 Riepilogo e Azioni")
        panel.setObjectName("summaryGroupBox")
        # Gli stili sono gestiti dal QSS del tema
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        
        # === RIEPILOGO SELEZIONE ===
        summary_frame = QFrame()
        summary_frame.setObjectName("summaryFrame")
        # Gli stili sono gestiti dal QSS del tema
        summary_layout = QGridLayout(summary_frame)
        summary_layout.setHorizontalSpacing(20)
        summary_layout.setVerticalSpacing(10)
        
        # Riga 1: Dispositivo e Numero di Serie
        summary_layout.addWidget(QLabel("<b>🔧 Dispositivo:</b>"), 0, 0)
        self.summary_device_label = QLabel("<i>Nessuna selezione</i>")
        self.summary_device_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_device_label, 0, 1, 1, 2)
        
        summary_layout.addWidget(QLabel("<b>🔢 S/N:</b>"), 0, 2)
        self.summary_serial_label = QLabel("—")
        self.summary_serial_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_serial_label, 0, 3)
        
        # Riga 2: Costruttore, Modello
        summary_layout.addWidget(QLabel("<b>🏭 Costruttore:</b>"), 1, 0)
        self.summary_manufacturer_label = QLabel("—")
        self.summary_manufacturer_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_manufacturer_label, 1, 1)
        
        summary_layout.addWidget(QLabel("<b>📱 Modello:</b>"), 1, 2)
        self.summary_model_label = QLabel("—")
        self.summary_model_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_model_label, 1, 3)
        
        # Riga 3: Inventario Cliente, Inventario AMS e Reparto
        summary_layout.addWidget(QLabel("<b>📊 Inv. Cliente:</b>"), 2, 0)
        self.summary_customer_inventory_label = QLabel("—")
        self.summary_customer_inventory_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_customer_inventory_label, 2, 1)
        
        summary_layout.addWidget(QLabel("<b>📋 Inv. AMS:</b>"), 2, 2)
        self.summary_ams_inventory_label = QLabel("—")
        self.summary_ams_inventory_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_ams_inventory_label, 2, 3)
        
        # Reparto nella stessa riga
        summary_layout.addWidget(QLabel("<b>🏢 Reparto:</b>"), 3, 0)
        self.summary_department_label = QLabel("—")
        self.summary_department_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_department_label, 3, 1)

        summary_layout.addWidget(QLabel("<b>🏢 Destinazione:</b>"), 3, 2)
        self.summary_destination_label = QLabel("—")
        self.summary_destination_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_destination_label, 3, 3)
        
        # Riga 4: Profilo
        summary_layout.addWidget(QLabel("<b>⚙️ Profilo:</b>"), 4, 0)
        self.profile_selector = QComboBox()
        self.profile_selector.setMinimumHeight(40)
        self.profile_selector.setAutoFillBackground(False)
        # Imposta lo sfondo dinamicamente in base al tema
        self._update_summary_fields_background()
        summary_layout.addWidget(self.profile_selector, 4, 1)

        summary_layout.addWidget(QLabel("<b>🛠️ Profilo Funzionale:</b>"), 4, 2)
        self.functional_profile_selector = QComboBox()
        self.functional_profile_selector.setMinimumHeight(40)
        self.functional_profile_selector.setAutoFillBackground(False)
        summary_layout.addWidget(self.functional_profile_selector, 4, 3)
        
        # Aggiorna lo sfondo dei campi dopo la creazione
        QTimer.singleShot(100, self._update_summary_fields_background)
        
        summary_layout.setColumnStretch(1, 2)
        summary_layout.setColumnStretch(3, 2)
        
        layout.addWidget(summary_frame)
        
        # === PULSANTI AZIONE ===
        action_layout = QHBoxLayout()
        action_layout.setSpacing(15)
        
        # Pulsante Modifica Dispositivo
        self.btn_edit_device = QPushButton(qta.icon('fa5s.edit', scale_factor=1.2), " Modifica Dispositivo")
        self.btn_edit_device.setObjectName("editButton")
        self.btn_edit_device.setMinimumHeight(55)
        self.btn_edit_device.setEnabled(False)
        self.btn_edit_device.clicked.connect(self.on_edit_selected_device_new)
        action_layout.addWidget(self.btn_edit_device)
        
        # Pulsante Verifica Manuale
        self.start_manual_button = QPushButton(qta.icon('fa5s.hand-pointer', scale_factor=1.3), " Verifica Manuale")
        self.start_manual_button.setObjectName("secondaryButton")
        self.start_manual_button.setMinimumHeight(55)
        self.start_manual_button.setEnabled(False)
        self.start_manual_button.setToolTip("Inserisci manualmente i valori misurati")
        self.start_manual_button.clicked.connect(lambda: self.start_verification(manual_mode=True))
        action_layout.addWidget(self.start_manual_button)
        
        # Pulsante Verifica Automatica
        self.start_auto_button = QPushButton(qta.icon('fa5s.robot', scale_factor=1.3), " Verifica Automatica")
        self.start_auto_button.setObjectName("autoButton")
        self.start_auto_button.setMinimumHeight(55)
        self.start_auto_button.setEnabled(False)
        self.start_auto_button.setToolTip("Avvia sequenza automatica di test con lo strumento")
        self.start_auto_button.clicked.connect(lambda: self.start_verification(manual_mode=False))
        action_layout.addWidget(self.start_auto_button)

        # Pulsante Verifica Funzionale
        self.start_functional_button = QPushButton(qta.icon('fa5s.heartbeat', scale_factor=1.3), " Verifica Funzionale Guidata")
        self.start_functional_button.setObjectName("secondaryButton")
        self.start_functional_button.setMinimumHeight(55)
        self.start_functional_button.setEnabled(False)
        self.start_functional_button.setToolTip("Avvia il flusso guidato della verifica funzionale")
        self.start_functional_button.clicked.connect(self.start_functional_verification)
        action_layout.addWidget(self.start_functional_button)
        
        layout.addLayout(action_layout)
        
        return panel
    
    def create_device_details_panel(self):
        from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton, QWidget, QGridLayout, QLabel, QScrollArea
        from PySide6.QtCore import Qt
        
        self.device_details_group = QGroupBox("Dettagli dispositivo", self)
        
        # Imposta altezza massima per il gruppo
        self.device_details_group.setMaximumHeight(250)
        
        box_layout = QVBoxLayout(self.device_details_group)
        
        # Crea un'area scrollabile per i dettagli
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.device_details_widget = QWidget()
        self.device_details_layout = QGridLayout(self.device_details_widget)
        
        # Imposta lo stretch delle colonne per una distribuzione uniforme
        self.device_details_layout.setColumnStretch(0, 0) # Etichetta col 1
        self.device_details_layout.setColumnStretch(1, 1) # Valore col 1
        self.device_details_layout.setColumnStretch(2, 0) # Etichetta col 2
        self.device_details_layout.setColumnStretch(3, 1) # Valore col 2
        
        # Imposta spaziatura più compatta
        self.device_details_layout.setHorizontalSpacing(20)
        self.device_details_layout.setVerticalSpacing(8)
        self.device_details_layout.setContentsMargins(15, 10, 15, 10)
        
        scroll_area.setWidget(self.device_details_widget)
        box_layout.addWidget(scroll_area)
        
        self.btn_edit_device = QPushButton("Modifica Dispositivo Selezionato")
        self.btn_edit_device.setObjectName("editButton")
        self.btn_edit_device.clicked.connect(self.on_edit_selected_device)
        box_layout.addWidget(self.btn_edit_device)
        
        self.on_device_selection_changed(self.device_selector.currentIndex())

    def _create_session_group(self):
        """Crea il gruppo sessione con design moderno."""
        user_info = auth_manager.get_current_user_info()
        self.current_technician_name = user_info.get('full_name')
        
        group = QGroupBox("👤 Sessione di Verifica")
        layout = QVBoxLayout(group)
        layout.setSpacing(12)
        
        # Info tecnico
        tech_layout = QHBoxLayout()
        tech_icon = QLabel()
        tech_icon.setPixmap(qta.icon('fa5s.user', color='#2563eb').pixmap(24, 24))
        tech_layout.addWidget(tech_icon)
        tech_title_label = QLabel("Tecnico:")
        tech_title_label.setStyleSheet("font-weight: 700; background-color: transparent;")
        tech_layout.addWidget(tech_title_label)
        self.current_technician_label = QLabel(self.current_technician_name or "N/D")
        self.current_technician_label.setStyleSheet("color: #2563eb; font-weight: 600; background-color: transparent;")
        tech_layout.addWidget(self.current_technician_label)
        tech_layout.addStretch()
        layout.addLayout(tech_layout)
        
        # Info strumento
        instr_layout = QHBoxLayout()
        instr_icon = QLabel()
        instr_icon.setPixmap(qta.icon('fa5s.tools', color='#16a34a').pixmap(24, 24))
        instr_layout.addWidget(instr_icon)
        instr_title_label = QLabel("Strumento:")
        instr_title_label.setStyleSheet("font-weight: 700; background-color: transparent;")
        instr_layout.addWidget(instr_title_label)
        self.current_instrument_label = QLabel("Nessuno strumento selezionato")
        self.current_instrument_label.setStyleSheet("color: #64748b; font-style: italic; background-color: transparent;")
        instr_layout.addWidget(self.current_instrument_label)
        instr_layout.addStretch()
        layout.addLayout(instr_layout)
        
        # Pulsante cambia sessione
        change_session_btn = QPushButton(qta.icon('fa5s.cog'), " Imposta Sessione")
        change_session_btn.setObjectName("warningButton") 
        change_session_btn.setMinimumHeight(45)
        change_session_btn.clicked.connect(self.setup_session)
        layout.addWidget(change_session_btn)
        
        return group

    def on_device_selection_changed(self, _idx: int):
        dev_id = self.device_selector.currentData()
        if not dev_id or dev_id == -1:
            self._clear_device_details()
            return
        self.update_device_details_view(dev_id)

    def _clear_device_details(self):
        """Pulisce il layout dei dettagli dispositivo."""
        # Rimuovi tutti i widget esistenti
        while self.device_details_layout.count():
            item = self.device_details_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Aggiungi un messaggio solo se non c'è selezione
        empty_label = QLabel("<i style='color: #64748b;'>Nessun dispositivo selezionato.</i>")
        empty_label.setAlignment(Qt.AlignCenter)
        self.device_details_layout.addWidget(empty_label, 0, 0, 1, 4)

    def update_device_details_view(self, dev_id: int):
        """Aggiorna la vista dettagli dispositivo con design moderno."""
        # Pulisce il layout prima di aggiungere nuovi elementi
        self._clear_device_details()

        row = services.database.get_device_by_id(dev_id)
        if not row:
            return

        dev = dict(row)

        # Recupera destinazione e cliente
        dest_name = "—"
        cust_name = "—"
        try:
            dest_row = services.database.get_destination_by_id(dev.get("destination_id"))
            if dest_row:
                dest = dict(dest_row)
                dest_name = dest.get('name', '—')
                cust_row = services.database.get_customer_by_id(dest.get("customer_id"))
                cust_name = dict(cust_row).get("name", "—") if cust_row else "—"
        except Exception:
            pass

        # Recupera profilo
        prof_key = dev.get("default_profile_key")
        prof_label = prof_key or "—"
        try:
            prof_obj = config.PROFILES.get(prof_key)
            if prof_obj:
                prof_label = getattr(prof_obj, "name", prof_key) or prof_key
        except Exception:
            pass

        func_prof_key = dev.get("default_functional_profile_key")
        func_prof_label = func_prof_key or "—"
        try:
            func_obj = config.FUNCTIONAL_PROFILES.get(func_prof_key)
            if func_obj:
                func_prof_label = getattr(func_obj, "name", func_prof_key) or func_prof_key
        except Exception:
            pass

        # Stato dispositivo
        status = dev.get('status', 'active')
        status_badge = ""
        if status == 'decommissioned':
            status_badge = "<span style='background: #fee2e2; color: #dc2626; padding: 4px 8px; border-radius: 4px; font-weight: bold;'>🚫 DISMESSO</span>"
        else:
            status_badge = "<span style='background: #dcfce7; color: #16a34a; padding: 4px 8px; border-radius: 4px; font-weight: bold;'>✓ ATTIVO</span>"

        # Layout con stile moderno
        row_idx = 0
        
        # Riga 1: Descrizione (occupata tutta)
        desc_label = QLabel("<b>📋 Descrizione:</b>")
        desc_value = QLabel(f"<span style='font-size: 14px; font-weight: bold; color: #1e293b;'>{dev.get('description') or '—'}</span>")
        self.device_details_layout.addWidget(desc_label, row_idx, 0)
        self.device_details_layout.addWidget(desc_value, row_idx, 1, 1, 3)
        row_idx += 1
        
        # Riga 2: Cliente e Destinazione
        self.device_details_layout.addWidget(QLabel("<b>🏢 Cliente:</b>"), row_idx, 0)
        self.device_details_layout.addWidget(QLabel(cust_name), row_idx, 1)
        self.device_details_layout.addWidget(QLabel("<b>📍 Destinazione:</b>"), row_idx, 2)
        self.device_details_layout.addWidget(QLabel(dest_name), row_idx, 3)
        row_idx += 1
        
        # Riga 3: Produttore e Modello
        self.device_details_layout.addWidget(QLabel("<b>🏭 Produttore:</b>"), row_idx, 0)
        self.device_details_layout.addWidget(QLabel(dev.get("manufacturer") or "—"), row_idx, 1)
        self.device_details_layout.addWidget(QLabel("<b>📦 Modello:</b>"), row_idx, 2)
        self.device_details_layout.addWidget(QLabel(dev.get("model") or "—"), row_idx, 3)
        row_idx += 1
        
        # Riga 4: S/N e Reparto
        self.device_details_layout.addWidget(QLabel("<b>🔢 S/N:</b>"), row_idx, 0)
        self.device_details_layout.addWidget(QLabel(dev.get("serial_number") or "—"), row_idx, 1)
        self.device_details_layout.addWidget(QLabel("<b>🏥 Reparto:</b>"), row_idx, 2)
        self.device_details_layout.addWidget(QLabel(dev.get("department") or "—"), row_idx, 3)
        row_idx += 1
        
        # Riga 5: Inventari
        self.device_details_layout.addWidget(QLabel("<b>📊 Inv. AMS:</b>"), row_idx, 0)
        self.device_details_layout.addWidget(QLabel(dev.get("ams_inventory") or "—"), row_idx, 1)
        self.device_details_layout.addWidget(QLabel("<b>📋 Inv. Cliente:</b>"), row_idx, 2)
        self.device_details_layout.addWidget(QLabel(dev.get("customer_inventory") or "—"), row_idx, 3)
        row_idx += 1
        
        # Riga 6: Profilo e Intervallo
        self.device_details_layout.addWidget(QLabel("<b>⚙️ Profilo:</b>"), row_idx, 0)
        self.device_details_layout.addWidget(QLabel(prof_label), row_idx, 1)
        interval = dev.get("verification_interval")
        interval_label = f"{interval} mesi" if interval not in (None, "") else "—"
        self.device_details_layout.addWidget(QLabel("<b>📅 Intervallo:</b>"), row_idx, 2)
        self.device_details_layout.addWidget(QLabel(interval_label), row_idx, 3)
        row_idx += 1

        self.device_details_layout.addWidget(QLabel("<b>🛠️ Profilo Funzionale:</b>"), row_idx, 0)
        self.device_details_layout.addWidget(QLabel(func_prof_label), row_idx, 1, 1, 3)
        row_idx += 1
        
        # Riga 7: Stato (badge)
        self.device_details_layout.addWidget(QLabel("<b>📌 Stato:</b>"), row_idx, 0)
        status_label = QLabel(status_badge)
        self.device_details_layout.addWidget(status_label, row_idx, 1, 1, 3)
        row_idx += 1

    def on_edit_selected_device(self):
        dev_id = self.device_selector.currentData()
        if not dev_id or dev_id == -1:
            QMessageBox.warning(self, "Attenzione", "Seleziona un dispositivo da modificare.")
            return

        try:
            from app.ui.dialogs.detail_dialogs import DeviceDialog

            row = services.database.get_device_by_id(dev_id)
            if not row:
                QMessageBox.critical(self, "Errore", "Impossibile caricare i dati del dispositivo.")
                return

            dev = dict(row)
            dest_id = dev.get("destination_id")
            dest_row = services.database.get_destination_by_id(dest_id) if dest_id else None
            customer_id = dict(dest_row).get("customer_id") if dest_row else None

            dlg = DeviceDialog(customer_id=customer_id,
                            destination_id=dest_id,
                            device_data=dev,
                            parent=self)

            if dlg.exec():
                data = dlg.get_data()
                services.update_device(
                    dev_id,
                    data["destination_id"],
                    data["serial"],
                    data["desc"],
                    data["mfg"],
                    data["model"],
                    data.get("department"),
                    data.get("applied_parts", []),
                    data.get("customer_inv"),
                    data.get("ams_inv"),
                    data.get("verification_interval"),
                    data.get("default_profile_key"),
                    data.get("default_functional_profile_key"),
                    reactivate=False,
                )
                # Ricarica la lista dispositivi e mantieni la selezione del dispositivo modificato
                current_destination_id = data.get("destination_id") or dest_id
                # Se la destinazione è cambiata, cambia anche la selezione destinazione
                if current_destination_id and current_destination_id != self.destination_selector.currentData():
                    dest_index = self.destination_selector.findData(current_destination_id)
                    if dest_index != -1:
                        self.destination_selector.setCurrentIndex(dest_index)
                        QApplication.processEvents()

                # Ricarica i dispositivi per la destinazione corrente
                self.on_destination_selected()
                QApplication.processEvents()

                # Prova a riselezionare il dispositivo modificato
                device_index = self.device_selector.findData(dev_id)
                if device_index != -1:
                    self.device_selector.setCurrentIndex(device_index)
                else:
                    # Se non trovato, potrebbe essere filtrato: passa a "Tutti" e riprova
                    if self._get_device_filter_mode() != "ALL":
                        self._set_device_filter_mode("ALL")
                        QApplication.processEvents()
                        device_index = self.device_selector.findData(dev_id)
                        if device_index != -1:
                            self.device_selector.setCurrentIndex(device_index)

                # Aggiorna i dettagli dopo aver forzato la selezione
                self.update_device_details_view(dev_id)
                QMessageBox.information(self, "Salvato", "Dispositivo aggiornato.")

        except Exception as e:
            logging.error("Errore durante la modifica del dispositivo", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Modifica non riuscita:\n{e}")

    def _create_search_group(self):
        """Crea il gruppo ricerca rapida con design moderno."""
        group = QGroupBox("🔍 Ricerca Rapida")
        layout = QVBoxLayout(group)
        
        search_layout = QHBoxLayout()
        self.global_device_search_edit = QLineEdit()
        self.global_device_search_edit.setPlaceholderText("🔎 Cerca cliente, dispositivo, matricola, inventario cliente...")
        self.global_device_search_edit.setMinimumHeight(45)
        self.global_device_search_edit.returnPressed.connect(self.perform_global_search)
        
        search_btn = QPushButton(qta.icon('fa5s.search'), " Cerca")
        search_btn.setObjectName("editButton")
        search_btn.setMinimumHeight(45)
        search_btn.setMinimumWidth(100)
        search_btn.clicked.connect(self.perform_global_search)
        
        search_layout.addWidget(self.global_device_search_edit, 1)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)
        
        return group

    def setup_session(self):
        dialog = InstrumentSelectionDialog(self, instrument_type='electrical')
        dialog.setWindowTitle("Seleziona Strumento per Verifiche Elettriche")
        if dialog.exec() == QDialog.Accepted:
            self.current_mti_info = dialog.getSelectedInstrumentData()
            user_info = auth_manager.get_current_user_info()
            self.current_technician_name = user_info.get('full_name')

            if self.current_mti_info:
                # Prova a rilevare automaticamente la porta COM se non è già impostata
                current_port = self.settings.value("global_com_port", "")
                if not current_port or current_port == "COM1":  # Se è il default, prova a rilevare
                    detected_port = FlukeESA612.detect_fluke_port()
                    if detected_port:
                        self.settings.setValue("global_com_port", detected_port)
                        self.current_mti_info['com_port'] = detected_port
                        logging.info(f"Porta COM rilevata automaticamente: {detected_port}")
                    else:
                        # Usa la porta salvata o quella dal dialog
                        self.current_mti_info['com_port'] = current_port or self.current_mti_info.get('com_port', 'COM1')
                else:
                    self.current_mti_info['com_port'] = current_port
                
                instrument_name = self.current_mti_info.get('instrument', 'N/A')
                serial_number = self.current_mti_info.get('serial', 'N/A')
                self.current_instrument_label.setText(f"{instrument_name} (S/N: {serial_number})")
                self.current_instrument_label.setStyleSheet("color: #16a34a; font-weight: 600; background-color: transparent;")
                self.current_technician_label.setText(self.current_technician_name or "N/D")
                self.current_technician_label.setStyleSheet("color: #2563eb; font-weight: 600; background-color: transparent;")
                logging.info(f"Sessione impostata per tecnico '{self.current_technician_name}' con strumento S/N {serial_number} su porta {self.current_mti_info.get('com_port', 'N/A')}.")
                self.statusBar().showMessage("verifica impostata. Pronto per iniziare.", 5000)
            else:
                QMessageBox.warning(self, "Dati Mancanti", "Selezionare uno strumento valido.")

    def _create_manual_selection_group(self):
        """Crea il gruppo di selezione dispositivi con etichette affiancate (risparmio spazio)."""
        from PySide6.QtWidgets import QSizePolicy
        
        group = QGroupBox("🎯 Selezione Dispositivo")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        # Destinazione
        self.destination_selector = QComboBox()
        self.destination_selector.setEditable(True)
        self.destination_selector.completer().setFilterMode(Qt.MatchContains)
        self.destination_selector.setPlaceholderText("🏢 Digita per cercare cliente o destinazione...")
        self.destination_selector.lineEdit().setPlaceholderText("🏢 Digita per cercare cliente o destinazione...")
        self.destination_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.destination_selector.setMinimumHeight(45)
        self.destination_selector.setMinimumContentsLength(20)
        self.destination_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        form.addRow("Cliente / Destinazione:", self.destination_selector)
        
        # Dispositivo (selector + add button + counter + filtro)
        device_row = QHBoxLayout()
        self.device_selector = QComboBox() 
        self.device_selector.setEditable(True)
        self.device_selector.completer().setFilterMode(Qt.MatchContains)
        self.device_selector.setPlaceholderText("🔧 Seleziona o cerca dispositivo...")
        self.device_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.device_selector.setMinimumHeight(45)
        self.device_selector.setMinimumContentsLength(20)
        self.device_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        
        add_device_btn = QPushButton(qta.icon('fa5s.plus', scale_factor=1), "")
        add_device_btn.setObjectName("autoButton")
        add_device_btn.setToolTip("Aggiungi nuovo dispositivo")
        add_device_btn.setMinimumHeight(45)
        add_device_btn.setMinimumWidth(45)
        add_device_btn.clicked.connect(self.quick_add_device)
        
        self.device_count_label = QLabel("<i style='color: #64748b;'>(0 dispositivi)</i>")
        self.device_verification_filter_combo = QComboBox()
        self.device_verification_filter_combo.addItem("Solo da verificare (60 gg)", "UNVERIFIED_60")
        self.device_verification_filter_combo.addItem("Solo funzionale (60 gg)", "ONLY_FUNCTIONAL_60")
        self.device_verification_filter_combo.addItem("Solo elettrica (60 gg)", "ONLY_ELECTRICAL_60")
        self.device_verification_filter_combo.addItem("Elettrica + Funzionale (60 gg)", "BOTH_60")
        self.device_verification_filter_combo.addItem("Tutti", "ALL")
        self.device_verification_filter_combo.setCurrentIndex(0)
        self.device_verification_filter_combo.setToolTip(
            "Filtra in base alle verifiche elettriche/funzionali degli ultimi 60 giorni"
        )
        
        device_row.addWidget(self.device_selector, 1)
        device_row.addWidget(add_device_btn)
        device_row.addWidget(self.device_count_label)
        device_row.addWidget(self.device_verification_filter_combo)
        form.addRow(f"Dispositivo:", device_row)
        
        # Profilo di verifica
        self.profile_selector = QComboBox()
        self.profile_selector.setMinimumHeight(45)
        form.addRow("Profilo di Verifica:", self.profile_selector)
        
        # Connessioni segnali
        self.destination_selector.currentIndexChanged.connect(self.on_destination_selected)
        self.device_selector.currentIndexChanged.connect(self.on_device_selected)
        self.device_verification_filter_combo.currentIndexChanged.connect(self.on_destination_selected)
        
        return group
    
    # ========== GESTORI EVENTI PER IL NUOVO DESIGN A 3 COLONNE ==========
    
    def reset_selection(self):
        """Reset di tutte le selezioni."""
        self.selected_customer_id = None
        self.selected_destination_id = None
        self.selected_device_id = None
        
        self.customer_list.clearSelection()
        self.destination_list.clear()
        self.device_list.clear()
        
        self.customer_search.clear()
        self.destination_search.clear()
        self.device_search.clear()
        
        self.update_summary_panel()
        self.destination_count_label.setText("<i>Seleziona un cliente</i>")
        self.device_count_label.setText("<i>Seleziona una destinazione</i>")
    
    def on_customer_selected(self, item):
        """Gestisce la selezione di un cliente."""
        self.selected_customer_id = item.data(Qt.UserRole)
        self.selected_destination_id = None
        self.selected_device_id = None
        
        # Ricarica destinazioni per questo cliente
        self.load_destinations_for_customer(self.selected_customer_id)
        self.device_list.clear()
        
        self.update_summary_panel()
    
    def on_destination_selected_new(self, item):
        """Gestisce la selezione di una destinazione."""
        self.selected_destination_id = item.data(Qt.UserRole)
        self.selected_device_id = None
        
        # Ricarica dispositivi per questa destinazione
        self.reload_devices(reset_search=True)
        
        self.update_summary_panel()
    
    def _select_device_by_id(self, device_id):
        """Seleziona un dispositivo per ID sia nella lista che nel selettore."""
        if not device_id:
            return
        
        # Seleziona nella lista (device_list)
        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            if item.data(Qt.UserRole) == device_id:
                self.device_list.setCurrentItem(item)
                self.on_device_selected_new(item)
                # Scrolla alla posizione del dispositivo
                self.device_list.scrollToItem(item)
                break
        
        # Seleziona nel selettore (device_selector)
        device_index = self.device_selector.findData(device_id)
        if device_index != -1:
            self.device_selector.blockSignals(True)
            self.device_selector.setCurrentIndex(device_index)
            self.device_selector.blockSignals(False)
            self.on_device_selected()
            self.on_device_selection_changed(device_index)
    
    def on_device_selected_new(self, item):
        """Gestisce la selezione di un dispositivo."""
        self.selected_device_id = item.data(Qt.UserRole)
        
        # Carica il profilo predefinito se presente
        device_data = services.database.get_device_by_id(self.selected_device_id)
        if device_data:
            dev = dict(device_data)
            default_profile_key = dev.get('default_profile_key')
            if default_profile_key:
                index = self.profile_selector.findData(default_profile_key)
                if index != -1:
                    self.profile_selector.setCurrentIndex(index)

            default_func_key = dev.get('default_functional_profile_key')
            if default_func_key:
                func_index = self.functional_profile_selector.findData(default_func_key)
                if func_index != -1:
                    self.functional_profile_selector.setCurrentIndex(func_index)
        
        self.update_summary_panel()
        
        # Abilita pulsanti azione
        self.btn_edit_device.setEnabled(True)
        self.start_manual_button.setEnabled(True)
        self.start_auto_button.setEnabled(True)
        self.start_functional_button.setEnabled(self.functional_profile_selector.count() > 0)
    
    def filter_customers(self, text):
        """Filtra i clienti in base al testo di ricerca."""
        text = text.lower()
        for i in range(self.customer_list.count()):
            item = self.customer_list.item(i)
            item.setHidden(text not in item.text().lower())
    
    def filter_destinations(self, text):
        """Filtra le destinazioni in base al testo di ricerca."""
        text = text.lower()
        for i in range(self.destination_list.count()):
            item = self.destination_list.item(i)
            item.setHidden(text not in item.text().lower())
    
    def filter_devices(self, text):
        """Filtra i dispositivi in base al testo di ricerca (smart)."""
        self._populate_device_list(self._get_device_cache(), text)
    
    def update_summary_panel(self):
        """Aggiorna il pannello di riepilogo in basso."""
        # Dispositivo e dettagli
        if self.selected_device_id:
            device_data = services.database.get_device_by_id(self.selected_device_id)
            if device_data:
                dev = dict(device_data)
                self.summary_device_label.setText(f"<b>{dev.get('description', 'N/A')}</b>")
                self.summary_device_label.setProperty("state", "device")
                self.summary_device_label.style().unpolish(self.summary_device_label)
                self.summary_device_label.style().polish(self.summary_device_label)
                
                # Numero di Serie
                serial_number = dev.get('serial_number', '—') or '—'
                self.summary_serial_label.setText(f"<b>{serial_number}</b>")
                
                # Costruttore
                manufacturer = dev.get('manufacturer', '—') or '—'
                self.summary_manufacturer_label.setText(f"<b>{manufacturer}</b>")
                
                # Modello
                model = dev.get('model', '—') or '—'
                self.summary_model_label.setText(f"<b>{model}</b>")
                
                # Inventario Cliente
                customer_inventory = dev.get('customer_inventory', '—') or '—'
                self.summary_customer_inventory_label.setText(f"<b>{customer_inventory}</b>")
                
                # Inventario AMS
                ams_inventory = dev.get('ams_inventory', '—') or '—'
                self.summary_ams_inventory_label.setText(f"<b>{ams_inventory}</b>")
                
                # Reparto
                department = dev.get('department', '—') or '—'
                self.summary_department_label.setText(f"<b>{department}</b>")

                # Destinazione
                destination = '—'
                destination_id = dev.get('destination_id')
                if destination_id:
                    dest_row = services.database.get_destination_by_id(destination_id)
                    if dest_row:
                        destination = dict(dest_row).get('name', '—') or '—'
                self.summary_destination_label.setText(f"<b>{destination}</b>")
            else:
                self._clear_summary_device()
        else:
            self._clear_summary_device()
    
    def _clear_summary_device(self):
        """Pulisce i dettagli dispositivo nel summary."""
        self.summary_device_label.setText("<i>Nessuna selezione</i>")
        self.summary_device_label.setProperty("state", "empty")
        self.summary_device_label.style().unpolish(self.summary_device_label)
        self.summary_device_label.style().polish(self.summary_device_label)
        self.summary_serial_label.setText("—")
        self.summary_manufacturer_label.setText("—")
        self.summary_model_label.setText("—")
        self.summary_customer_inventory_label.setText("—")
        self.summary_ams_inventory_label.setText("—")
        self.summary_department_label.setText("—")
        self.summary_destination_label.setText("—")
        self.btn_edit_device.setEnabled(False)
        self.start_manual_button.setEnabled(False)
        self.start_auto_button.setEnabled(False)
        self.start_functional_button.setEnabled(False)
    
    def on_edit_selected_device_new(self):
        """Gestisce la modifica del dispositivo selezionato (nuova versione)."""
        if not self.selected_device_id:
            QMessageBox.warning(self, "Attenzione", "Nessun dispositivo selezionato.")
            return
        
        try:
            from app.ui.dialogs.detail_dialogs import DeviceDialog
            
            row = services.database.get_device_by_id(self.selected_device_id)
            if not row:
                QMessageBox.critical(self, "Errore", "Impossibile caricare i dati del dispositivo.")
                return
            
            dev = dict(row)
            dest_id = dev.get("destination_id")
            dest_row = services.database.get_destination_by_id(dest_id) if dest_id else None
            customer_id = dict(dest_row).get("customer_id") if dest_row else None
            
            dlg = DeviceDialog(customer_id=customer_id,
                            destination_id=dest_id,
                            device_data=dev,
                            parent=self)
            
            if dlg.exec():
                data = dlg.get_data()
                services.update_device(
                    self.selected_device_id,
                    data["destination_id"],
                    data["serial"],
                    data["desc"],
                    data["mfg"],
                    data["model"],
                    data.get("department"),
                    data.get("applied_parts", []),
                    data.get("customer_inv"),
                    data.get("ams_inv"),
                    data.get("verification_interval"),
                    data.get("default_profile_key"),
                    data.get("default_functional_profile_key"),
                    reactivate=False,
                )
                
                # Ricarica la UI mantenendo la selezione
                current_device_id = self.selected_device_id
                self.reload_devices()
                
                # Riseleziona il dispositivo modificato
                for i in range(self.device_list.count()):
                    item = self.device_list.item(i)
                    if item.data(Qt.UserRole) == current_device_id:
                        self.device_list.setCurrentItem(item)
                        break
                
                self.update_summary_panel()
                QMessageBox.information(self, "Salvato", "Dispositivo aggiornato con successo.")
        
        except Exception as e:
            logging.error("Errore durante la modifica del dispositivo", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Modifica non riuscita:\n{e}")
    
    def reload_devices(self, *, reset_search: bool = False):
        """Ricarica la lista dispositivi per la destinazione selezionata."""
        self.device_list.clear()
        if reset_search and getattr(self, "device_search", None) is not None:
            self.device_search.clear()
        
        if not self.selected_destination_id:
            self.device_count_label.setText("<i>Seleziona una destinazione</i>")
            return
        
        devices = self._get_filtered_devices_for_destination(self.selected_destination_id)
        self._set_device_cache(devices)

        search_query = self.device_search.text() if getattr(self, "device_search", None) is not None else ""
        self._populate_device_list(self._get_device_cache(), search_query)

    def _get_device_filter_mode(self) -> str:
        """Restituisce la modalità di filtro dispositivi attiva."""
        combo = getattr(self, "device_verification_filter_combo", None)
        if combo is not None:
            mode = combo.currentData()
            if mode:
                return str(mode)
        return "UNVERIFIED_60"

    def _set_device_filter_mode(self, mode: str):
        """Imposta la modalità filtro dispositivi se disponibile."""
        combo = getattr(self, "device_verification_filter_combo", None)
        if combo is None:
            return
        idx = combo.findData(mode)
        if idx != -1 and combo.currentIndex() != idx:
            combo.setCurrentIndex(idx)

    def _get_device_filter_label(self, mode: str) -> str:
        labels = {
            "UNVERIFIED_60": "nessuna verifica",
            "ONLY_FUNCTIONAL_60": "manca funzionale",
            "ONLY_ELECTRICAL_60": "manca elettrica",
            "BOTH_60": "non complete (elettrica+funzionale)",
            "ALL": "tutti",
        }
        return labels.get(mode, "personalizzato")

    def _get_device_filter_period(self) -> tuple[str, str]:
        """Restituisce il periodo filtro dispositivi come stringhe YYYY-MM-DD."""
        start = self.device_filter_start_date
        end = self.device_filter_end_date
        if start > end:
            start, end = end, start
        return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')

    def _get_device_filter_period_label(self) -> str:
        start = self.device_filter_start_date
        end = self.device_filter_end_date
        if start > end:
            start, end = end, start
        return f"{start.strftime('%d/%m/%Y')} - {end.strftime('%d/%m/%Y')}"

    def _update_device_period_button_tooltip(self):
        btn = getattr(self, "device_period_button", None)
        if btn is None:
            return
        btn.setToolTip(f"Seleziona periodo filtri (attuale: {self._get_device_filter_period_label()})")

    def choose_device_filter_period(self):
        """Apre il calendario standard già usato nel programma."""
        dialog = SingleCalendarRangeDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        start_str, end_str = dialog.get_date_range()
        if not start_str or not end_str:
            return

        start = datetime.strptime(start_str, "%Y-%m-%d").date()
        end = datetime.strptime(end_str, "%Y-%m-%d").date()
        if start > end:
            start, end = end, start

        self.device_filter_start_date = start
        self.device_filter_end_date = end
        self._update_device_period_button_tooltip()
        self.reload_devices()

    def _get_filtered_devices_for_destination(self, destination_id: int):
        """Recupera i dispositivi della destinazione applicando il filtro verifiche."""
        all_devices = services.database.get_devices_for_destination(destination_id)
        mode = self._get_device_filter_mode()

        if mode == "ALL":
            return all_devices

        start_date_str, end_date_str = self._get_device_filter_period()

        electrical_verifs = services.database.get_verifications_for_destination_by_date_range(
            destination_id,
            start_date_str,
            end_date_str,
        )
        functional_verifs = services.database.get_functional_verifications_for_destination_by_date_range(
            destination_id,
            start_date_str,
            end_date_str,
        )

        electrical_ids = {dict(row).get('device_id') for row in electrical_verifs if dict(row).get('device_id') is not None}
        functional_ids = {dict(row).get('device_id') for row in functional_verifs if dict(row).get('device_id') is not None}

        filtered = []
        for dev_row in all_devices:
            dev = dict(dev_row)
            dev_id = dev.get('id')
            has_electrical = dev_id in electrical_ids
            has_functional = dev_id in functional_ids

            include = True
            if mode == "UNVERIFIED_60":
                # Mostra solo dispositivi senza alcuna verifica (elettrica o funzionale) negli ultimi 60 giorni
                include = not has_electrical and not has_functional
            elif mode == "ONLY_FUNCTIONAL_60":
                # Solo funzionale da eseguire: elettrica presente, funzionale assente
                include = has_electrical and not has_functional
            elif mode == "ONLY_ELECTRICAL_60":
                # Solo elettrica da eseguire: funzionale presente, elettrica assente
                include = has_functional and not has_electrical
            elif mode == "BOTH_60":
                # Nasconde i dispositivi con entrambe le verifiche già eseguite nel periodo,
                # mostrando tutti gli altri.
                include = not (has_electrical and has_functional)

            if include:
                filtered.append(dev_row)

        return filtered

    def _get_device_cache(self):
        return getattr(self, "_device_cache", [])

    def _set_device_cache(self, devices):
        self._device_cache = [dict(row) for row in devices]

    def _populate_device_list(self, devices, search_query: str):
        """Popola la lista dispositivi applicando il filtro di ricerca smart."""
        self.device_list.clear()

        if not self.selected_destination_id:
            self.device_count_label.setText("<i>Seleziona una destinazione</i>")
            return

        current_selected_id = self.selected_device_id
        filtered_devices = [dev for dev in devices if self._device_matches_query(dev, search_query)]

        selected_item = None
        for dev in filtered_devices:
            display_text = (
                f"TIPO: {dev.get('description', 'N/A')} | "
                f"MODELLO: {dev.get('model', 'N/A')} | "
                f"S/N: {dev.get('serial_number', 'N/A')} | "
                f"Inv: {dev.get('ams_inventory', 'N/A')}"
            )
            item = QListWidgetItem(display_text)
            dev_id = dev.get('id')
            item.setData(Qt.UserRole, dev_id)
            self.device_list.addItem(item)
            if current_selected_id and dev_id == current_selected_id:
                selected_item = item

        if selected_item is not None:
            self.device_list.setCurrentItem(selected_item)
        elif self.selected_device_id is not None:
            self.selected_device_id = None
            self._clear_summary_device()

        total_count = len(devices)
        visible_count = len(filtered_devices)
        active_filter = self._get_device_filter_label(self._get_device_filter_mode())
        period_label = self._get_device_filter_period_label()
        if search_query.strip():
            count_text = (
                f"<span style='font-weight: bold;'>{visible_count} di {total_count} dispositivi</span> "
                f"<span style='color:#64748b;'>(filtro: {active_filter}, periodo: {period_label})</span>"
            )
        else:
            count_text = (
                f"<span style='font-weight: bold;'>{total_count} dispositivi</span> "
                f"<span style='color:#64748b;'>(filtro: {active_filter}, periodo: {period_label})</span>"
            )
        self.device_count_label.setText(count_text)

    def _device_matches_query(self, dev: dict, query: str) -> bool:
        """Ricerca intelligente su più campi con tag (es. sn:, inv:, mod:)."""
        query = (query or "").strip().lower()
        if not query:
            return True

        def norm(value: str) -> str:
            return (value or "").strip().lower()

        fields = {
            "description": norm(dev.get("description")),
            "model": norm(dev.get("model")),
            "serial": norm(dev.get("serial_number")),
            "ams": norm(dev.get("ams_inventory")),
            "customer": norm(dev.get("customer_inventory")),
            "manufacturer": norm(dev.get("manufacturer")),
            "department": norm(dev.get("department")),
            "status": norm(dev.get("status")),
        }

        any_field_text = " ".join(fields.values())

        def matches(token: str, key: str | None) -> bool:
            if not token:
                return True

            if key in {"sn", "serial"}:
                return token in fields["serial"]
            if key in {"inv", "inventario"}:
                return token in fields["ams"] or token in fields["customer"]
            if key in {"ams"}:
                return token in fields["ams"]
            if key in {"cli", "cust", "cliente"}:
                return token in fields["customer"]
            if key in {"mod", "model"}:
                return token in fields["model"]
            if key in {"mar", "mfg", "prod", "manufacturer"}:
                return token in fields["manufacturer"]
            if key in {"rep", "dept", "department"}:
                return token in fields["department"]
            if key in {"desc", "tipo", "descrizione"}:
                return token in fields["description"]
            if key in {"stato", "status"}:
                return token in fields["status"]
            return token in any_field_text

        tokens = [t for t in query.split() if t]
        for raw_token in tokens:
            negated = raw_token.startswith("-") and len(raw_token) > 1
            token = raw_token[1:] if negated else raw_token
            key = None
            value = token
            if ":" in token:
                key, value = token.split(":", 1)
                key = key.strip().lower()
                value = value.strip().lower()
            else:
                value = value.strip().lower()

            is_match = matches(value, key)
            if negated and is_match:
                return False
            if not negated and not is_match:
                return False

        return True
    
    def load_destinations_for_customer(self, customer_id):
        """Carica le destinazioni per un cliente specifico."""
        self.destination_list.clear()
        self.destination_search.clear()
        
        if not customer_id:
            self.destination_count_label.setText("<i>Seleziona un cliente</i>")
            return
        
        destinations = services.database.get_destinations_for_customer(customer_id)
        
        for dest_row in destinations:
            dest = dict(dest_row)
            item = QListWidgetItem(dest.get('name', 'N/A'))
            item.setData(Qt.UserRole, dest.get('id'))
            self.destination_list.addItem(item)
        
        # Aggiorna contatore
        dest_count = len(destinations)
        self.destination_count_label.setText(f"<span style='font-weight: bold;'>{dest_count} destinazioni</span>")
        
    def load_all_data(self):
        """Carica tutti i dati iniziali."""
        self.load_customers()
        self.load_profiles()
        self.load_functional_profiles()
        self.load_control_panel_data()
    
    def load_customers(self):
        """Carica tutti i clienti nella lista."""
        self.customer_list.clear()
        self.customer_search.clear()
        
        customers = services.database.get_all_customers()
        
        for customer_row in customers:
            customer = dict(customer_row)
            item = QListWidgetItem(customer.get('name', 'N/A'))
            item.setData(Qt.UserRole, customer.get('id'))
            self.customer_list.addItem(item)
        
        # Aggiorna contatore
        customer_count = len(customers)
        self.customer_count_label.setText(f"<span style='font-weight: bold;'>{customer_count} clienti</span>")

    def load_destinations(self):
        """Load destinations into the combo box (OLD - per compatibilità)."""
        self.destination_selector.blockSignals(True)
        self.destination_selector.clear()
        
        # Load actual destinations
        destinations = services.database.get_all_destinations_with_customer()
        for dest in destinations:
            self.destination_selector.addItem(f"{dest['customer_name']} / {dest['name']}", dest['id'])
        
        self.destination_selector.blockSignals(False)

    def load_profiles(self):
        self.profile_selector.clear()
        self.profile_selector.addItem("— Nessun profilo —", None)
        for key, profile in config.PROFILES.items():
            self.profile_selector.addItem(profile.name.upper(), key)

    def load_functional_profiles(self):
        self.functional_profile_selector.clear()
        self.functional_profile_selector.addItem("— Nessun profilo —", None)
        for key, profile in config.FUNCTIONAL_PROFILES.items():
            self.functional_profile_selector.addItem(profile.name.upper(), key)

    def load_control_panel_data(self):
        """Ricarica i dati - ora non fa nulla perché il control panel è stato rimosso."""
        pass

    def on_destination_selected(self):
        """Carica i dispositivi per la destinazione selezionata."""
        self.device_selector.blockSignals(True)
        self.device_selector.clear()
        
        destination_id = self.destination_selector.currentData()
        if not destination_id or destination_id == -1:
            self.device_selector.addItem("Seleziona prima una destinazione...", -1)
            self.device_count_label.setText("<i>(0 dispositivi)</i>")
            self.device_selector.blockSignals(False)
            self.on_device_selected()
            return

        devices = self._get_filtered_devices_for_destination(destination_id)
        
        # Popola il selettore
        for dev_row in devices:
            dev = dict(dev_row)
            display_text = f"{dev.get('description')} (S/N: {dev.get('serial_number')}) - (Inv AMS: {dev.get('ams_inventory')})"
            self.device_selector.addItem(display_text, dev.get('id'))
        
        # Aggiorna contatore
        device_count = len(devices)
        active_filter = self._get_device_filter_label(self._get_device_filter_mode())
        period_label = self._get_device_filter_period_label()
        count_text = f"<span style='font-weight: bold;'>({device_count} dispositivi)</span> <span style='color:#64748b;'>(filtro: {active_filter}, periodo: {period_label})</span>"

        self.device_count_label.setText(count_text)
        
        if self.device_selector.count() > 0:
            self.device_selector.setCurrentIndex(0)

        self.device_selector.blockSignals(False)
        self.on_device_selected()
        self.on_device_selection_changed(self.device_selector.currentIndex())

    def on_device_selected(self):
        device_id = self.device_selector.currentData()
        self.profile_selector.blockSignals(True)
        self.functional_profile_selector.blockSignals(True)
        if not device_id or device_id == -1:
            if self.profile_selector.count() > 0:
                self.profile_selector.setCurrentIndex(0)
            if self.functional_profile_selector.count() > 0:
                self.functional_profile_selector.setCurrentIndex(0)
            self.profile_selector.blockSignals(False)
            self.functional_profile_selector.blockSignals(False)
            return
        
        device_data = services.database.get_device_by_id(device_id)
        if device_data and device_data.get('default_profile_key'):
            index = self.profile_selector.findData(device_data['default_profile_key'])
            if index != -1:
                self.profile_selector.setCurrentIndex(index)
            else:
                self.profile_selector.setCurrentIndex(0)
        elif self.profile_selector.count() > 0:
            self.profile_selector.setCurrentIndex(0)

        if device_data and device_data.get('default_functional_profile_key'):
            default_func_key = device_data['default_functional_profile_key']
            func_index = self.functional_profile_selector.findData(default_func_key)
            if func_index != -1:
                self.functional_profile_selector.setCurrentIndex(func_index)
            else:
                # Il profilo di default non è stato trovato, potrebbe essere stato modificato
                # Verifica se esiste ancora nel dizionario dei profili
                if default_func_key in config.FUNCTIONAL_PROFILES:
                    # Il profilo esiste ma non è nel selector, ricarica i profili
                    self.load_functional_profiles()
                    func_index = self.functional_profile_selector.findData(default_func_key)
                    if func_index != -1:
                        self.functional_profile_selector.setCurrentIndex(func_index)
                    elif self.functional_profile_selector.count() > 0:
                        self.functional_profile_selector.setCurrentIndex(0)
                elif self.functional_profile_selector.count() > 0:
                    # Il profilo non esiste più, seleziona il primo disponibile
                    self.functional_profile_selector.setCurrentIndex(0)
        elif self.functional_profile_selector.count() > 0:
            self.functional_profile_selector.setCurrentIndex(0)

        self.profile_selector.blockSignals(False)
        self.functional_profile_selector.blockSignals(False)
        self.start_functional_button.setEnabled(self.functional_profile_selector.count() > 0)
    
    def start_verification(self, manual_mode: bool):
        """Avvia la verifica con il nuovo sistema di selezione."""
        if not self.current_mti_info or not self.current_technician_name:
            QMessageBox.warning(self, "Sessione non Impostata", "Impostare strumento e tecnico prima di avviare una verifica.")
            return
            
        # Usa le nuove variabili di selezione
        if not self.selected_device_id:
            QMessageBox.warning(self, "Attenzione", "Selezionare un dispositivo valido prima di avviare la verifica.")
            return
            
        device_info_row = services.database.get_device_by_id(self.selected_device_id)
        if not device_info_row:
            QMessageBox.critical(self, "Errore", "Impossibile trovare i dati del dispositivo selezionato."); return
        device_info = dict(device_info_row)

        profile_key = self.profile_selector.currentData()
        if not profile_key:
            QMessageBox.warning(self, "Attenzione", "Selezionare un profilo di verifica."); return
        
        selected_profile = config.PROFILES[profile_key]
        
        if device_info.get('default_profile_key') != profile_key:
            try:
                logging.info(f"Updating default profile for device ID {self.selected_device_id} to '{profile_key}'.")
                
                update_data = {
                    "destination_id": device_info['destination_id'],
                    "default_profile_key": profile_key,
                    "default_functional_profile_key": device_info.get('default_functional_profile_key'),
                    "serial": device_info['serial_number'],
                    "desc": device_info['description'],
                    "mfg": device_info['manufacturer'],
                    "model": device_info['model'],
                    "department": device_info['department'],
                    "customer_inv": device_info['customer_inventory'],
                    "ams_inv": device_info['ams_inventory'],
                    "applied_parts": [AppliedPart(**pa) for pa in device_info.get('applied_parts', [])],
                    "verification_interval": device_info['verification_interval']
                }
                services.update_device(self.selected_device_id, **update_data)
            except Exception as e:
                logging.error(f"Failed to save default profile for device ID {self.selected_device_id}: {e}")
                QMessageBox.warning(self, "Salvataggio Profilo Fallito", 
                                    "Non è stato possibile salvare il profilo scelto come predefinito, ma la verifica può continuare.")

        profile_needs_ap = any(test.is_applied_part_test for test in selected_profile.tests)
        applied_parts = [AppliedPart(**pa) for pa in device_info.get('applied_parts', [])]
        
        if not manual_mode and profile_needs_ap and applied_parts:
            order_dialog = AppliedPartsOrderDialog(applied_parts, self)
            if order_dialog.exec() != QDialog.Accepted:
                self.statusBar().showMessage("Verifica annullata dall'utente.", 3000)
                return

        if profile_needs_ap and not applied_parts:
            msg_box = QMessageBox(QMessageBox.Question, "Parti Applicate Mancanti",
                                f"Il profilo '{selected_profile.name}' richiede test su Parti Applicate, ma il dispositivo non ne ha.",
                                QMessageBox.NoButton, self)
            btn_edit = msg_box.addButton("Modifica Dispositivo", QMessageBox.ActionRole)
            msg_box.addButton("Continua (Salta Test P.A.)", QMessageBox.ActionRole)
            btn_cancel = msg_box.addButton("Annulla Verifica", QMessageBox.RejectRole)
            msg_box.exec()
            
            clicked_btn = msg_box.clickedButton()
            if clicked_btn == btn_edit:
                destination_info = dict(services.database.get_destination_by_id(device_info['destination_id']))
                customer_id = destination_info['customer_id']
                edit_dialog = DeviceDialog(customer_id=customer_id, destination_id=device_info['destination_id'], device_data=device_info, parent=self)
                if edit_dialog.exec():
                    services.update_device(self.selected_device_id, **edit_dialog.get_data())
                    self.reload_devices()  # Usa il nuovo metodo
                return
            elif clicked_btn == btn_cancel:
                return

        inspection_dialog = VisualInspectionDialog(self)
        if inspection_dialog.exec() == QDialog.Accepted:
            visual_inspection_data = inspection_dialog.get_data()
            
            if self.test_runner_widget:
                self.test_runner_widget.deleteLater()

            destination_info = dict(services.database.get_destination_by_id(device_info['destination_id']))
            customer_info = dict(services.database.get_customer_by_id(destination_info['customer_id']))
            report_settings = {"logo_path": self.logo_path}
            current_user = auth_manager.get_current_user_info()
            
            self.test_runner_widget = TestRunnerWidget(
                device_info, customer_info, self.current_mti_info, report_settings,
                profile_key, visual_inspection_data, 
                current_user.get('full_name'), 
                current_user.get('username'),
                manual_mode, self
            )
            self.test_runner_layout.addWidget(self.test_runner_widget)
            
            self.set_selection_enabled(False)
    
    def start_functional_verification(self):
        """Avvia la compilazione della verifica funzionale per il profilo selezionato."""
        if not self.current_technician_name:
            QMessageBox.warning(
                self,
                "Sessione non impostata",
                "Impostare il tecnico prima di avviare una verifica funzionale.",
            )
            return

        if not self.selected_device_id:
            QMessageBox.warning(self, "Attenzione", "Selezionare un dispositivo valido.")
            return

        profile_key = self.functional_profile_selector.currentData()
        if not profile_key:
            QMessageBox.warning(self, "Profilo mancante", "Selezionare un profilo funzionale.")
            return

        profile = config.FUNCTIONAL_PROFILES.get(profile_key)
        if not profile:
            QMessageBox.critical(
                self,
                "Profilo non trovato",
                "Il profilo funzionale selezionato non è disponibile. Ricaricare i profili.",
            )
            return

        device_info_row = services.database.get_device_by_id(self.selected_device_id)
        if not device_info_row:
            QMessageBox.critical(self, "Errore", "Impossibile recuperare i dati del dispositivo.")
            return
        device_info = dict(device_info_row)

        # Salva il profilo selezionato come default per il dispositivo
        if device_info.get('default_functional_profile_key') != profile_key:
            try:
                logging.info(f"Updating default functional profile for device ID {self.selected_device_id} to '{profile_key}'.")
                
                update_data = {
                    "destination_id": device_info['destination_id'],
                    "default_profile_key": device_info.get('default_profile_key'),
                    "default_functional_profile_key": profile_key,
                    "serial": device_info['serial_number'],
                    "desc": device_info['description'],
                    "mfg": device_info['manufacturer'],
                    "model": device_info['model'],
                    "department": device_info['department'],
                    "customer_inv": device_info['customer_inventory'],
                    "ams_inv": device_info['ams_inventory'],
                    "applied_parts": [AppliedPart(**pa) for pa in device_info.get('applied_parts', [])],
                    "verification_interval": device_info['verification_interval']
                }
                services.update_device(self.selected_device_id, **update_data)
                # Aggiorna anche device_info locale per riflettere il cambiamento
                device_info['default_functional_profile_key'] = profile_key
            except Exception as e:
                logging.error(f"Failed to save default functional profile for device ID {self.selected_device_id}: {e}")
                QMessageBox.warning(self, "Salvataggio Profilo Fallito", 
                                    "Non è stato possibile salvare il profilo funzionale scelto come predefinito, ma la verifica può continuare.")

        # Selezione strumenti opzionale (solo se il profilo ha strumenti associati o se ci sono strumenti disponibili)
        from app.ui.dialogs.instrument_selection_dialog import UsedInstrumentsSelectionDialog
        
        used_instruments = []
        mti_info = None

        # Regole strumenti da profilo
        min_required_instruments = int(getattr(profile, "required_min_instruments", 0) or 0)
        allowed_instrument_types = [
            str(t).strip().lower()
            for t in (getattr(profile, "allowed_instrument_types", []) or [])
            if str(t).strip()
        ]
        
        # Normalizza gli ID strumenti del profilo (evita mismatch int/str)
        available_instrument_ids_set = set()
        for raw_id in (profile.instrument_ids or []):
            try:
                available_instrument_ids_set.add(int(raw_id))
            except (TypeError, ValueError):
                continue

        # Fallback su snapshot strumenti del profilo
        for snap in (getattr(profile, "instrument_snapshots", []) or []):
            if not isinstance(snap, dict):
                continue
            snap_id = snap.get("id")
            try:
                available_instrument_ids_set.add(int(snap_id))
            except (TypeError, ValueError):
                continue

        # Mappa strumenti esistenti per validazione/filtri
        all_instruments_rows = services.database.get_all_instruments() or []
        all_instruments_map = {dict(inst).get("id"): dict(inst) for inst in all_instruments_rows}

        # Applica filtro tipi consentiti, se impostato
        if allowed_instrument_types:
            filtered_ids = set()
            for inst_id in available_instrument_ids_set:
                inst = all_instruments_map.get(inst_id)
                inst_type = str((inst or {}).get("instrument_type") or "").strip().lower()
                if inst_type in allowed_instrument_types:
                    filtered_ids.add(inst_id)
            available_instrument_ids_set = filtered_ids

        has_profile_assigned_instruments = bool(available_instrument_ids_set)
        available_instrument_ids = sorted(available_instrument_ids_set)

        if not available_instrument_ids:
            # Se il profilo non ha strumenti associati, mostra tutti gli strumenti funzionali
            all_functional = services.database.get_all_instruments('functional')
            # Fallback legacy: se non ci sono strumenti marcati come functional,
            # mostra comunque tutti gli strumenti disponibili.
            if not all_functional:
                all_functional = services.database.get_all_instruments()
            available_instrument_ids = [dict(inst)['id'] for inst in all_functional]

        # Storico ultimi strumenti usati per questo profilo (solo se il profilo ha strumenti assegnati)
        history_key = f"functional_last_instruments/{profile.profile_key}"
        preselected_ids = []
        if has_profile_assigned_instruments:
            try:
                saved_history = self.settings.value(history_key, "[]")
                if isinstance(saved_history, str):
                    preselected_ids = json.loads(saved_history)
                elif isinstance(saved_history, list):
                    preselected_ids = saved_history
            except Exception:
                preselected_ids = []

            # Se non c'è storico, usa la preselezione del profilo
            if not preselected_ids:
                preselected_ids = available_instrument_ids.copy()
        
        # Se ci sono strumenti disponibili, chiedi all'utente di selezionarli (ma non obbligatorio)
        if available_instrument_ids:
            instruments_dialog = UsedInstrumentsSelectionDialog(
                available_instrument_ids,
                preselected_ids=preselected_ids,
                parent=self,
            )
            dialog_result = instruments_dialog.exec()
            if dialog_result == QDialog.Accepted:
                used_instruments = instruments_dialog.get_selected_instruments()
                # Usa il primo strumento per compatibilità con il codice esistente (per mti_info)
                mti_info = used_instruments[0] if used_instruments else None

                # Salva storico selezione strumenti per profilo
                try:
                    self.settings.setValue(
                        history_key,
                        json.dumps(instruments_dialog.get_selected_instrument_ids()),
                    )
                except Exception:
                    pass

            # Regola minimo strumenti richiesti
            if len(used_instruments) < min_required_instruments:
                QMessageBox.warning(
                    self,
                    "Strumenti insufficienti",
                    (
                        f"Il profilo richiede almeno {min_required_instruments} strumento/i.\n"
                        f"Selezionati: {len(used_instruments)}."
                    ),
                )
                return

            # Warning calibrazione scaduta (solo warning, nessun blocco)
            expired_instruments = []
            for inst in used_instruments:
                cal_raw = str(inst.get("cal_date") or "").strip()
                if not cal_raw:
                    continue
                calibration_date = None
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        calibration_date = datetime.strptime(cal_raw, fmt).date()
                        break
                    except Exception:
                        continue
                if calibration_date:
                    try:
                        expiry_date = calibration_date.replace(year=calibration_date.year + 1)
                    except ValueError:
                        expiry_date = calibration_date.replace(month=2, day=28, year=calibration_date.year + 1)
                else:
                    expiry_date = None
                if expiry_date and expiry_date < date.today():
                    expired_instruments.append(
                        f"- {inst.get('instrument', 'N/D')} (S/N: {inst.get('serial', 'N/D')}) - Calibrazione: {cal_raw}"
                    )

            if expired_instruments:
                QMessageBox.warning(
                    self,
                    "Avviso calibrazione scaduta",
                    "Sono stati selezionati strumenti con calibrazione scaduta:\n\n"
                    + "\n".join(expired_instruments)
                    + "\n\nLa verifica può continuare (solo avviso).",
                )

            # Se non è stato scelto alcuno strumento, chiedi conferma esplicita prima di continuare
            if not used_instruments:
                confirm_box = QMessageBox(self)
                confirm_box.setIcon(QMessageBox.Question)
                confirm_box.setWindowTitle("Nessuno strumento selezionato")
                confirm_box.setText(
                    "Non è stato selezionato alcuno strumento per la verifica funzionale.\n\n"
                    "Vuoi continuare comunque?"
                )
                btn_yes = confirm_box.addButton("Sì, continua", QMessageBox.YesRole)
                btn_no = confirm_box.addButton("No, torna indietro", QMessageBox.NoRole)
                confirm_box.setDefaultButton(btn_no)
                confirm_box.exec()
                if confirm_box.clickedButton() != btn_yes:
                    return
        elif min_required_instruments > 0:
            QMessageBox.warning(
                self,
                "Strumenti non disponibili",
                (
                    f"Il profilo richiede almeno {min_required_instruments} strumento/i, "
                    "ma non ci sono strumenti disponibili o compatibili con le regole del profilo."
                ),
            )
            return

        # Audit selezione strumenti in avvio verifica funzionale
        try:
            services.log_action(
                'SELECT',
                'functional_instruments',
                entity_id=self.selected_device_id,
                entity_description=f"Selezione strumenti per profilo funzionale '{profile.profile_key}'",
                details={
                    'device_id': self.selected_device_id,
                    'profile_key': profile.profile_key,
                    'profile_name': profile.name,
                    'required_min_instruments': min_required_instruments,
                    'allowed_instrument_types': allowed_instrument_types,
                    'selected_count': len(used_instruments),
                    'selected_instruments': used_instruments,
                    'app_version': config.VERSIONE,
                },
            )
        except Exception:
            pass

        current_user = auth_manager.get_current_user_info()

        if self.test_runner_widget:
            self.test_runner_widget.deleteLater()

        self.state_manager.set_state(
            AppState.TESTING,
            f"Verifica funzionale su {device_info.get('description', 'Dispositivo')}",
        )

        report_settings = {"logo_path": self.logo_path}

        self.test_runner_widget = FunctionalTestRunnerWidget(
            device_info=device_info,
            profile=profile,
            technician_name=self.current_technician_name,
            technician_username=current_user.get("username"),
            mti_info=mti_info,
            used_instruments=used_instruments,  # Passa tutti gli strumenti usati
            report_settings=report_settings,
            parent=self,
        )
        self.test_runner_layout.addWidget(self.test_runner_widget)
        self.set_selection_enabled(False)
    
    def reset_main_ui(self):
        QApplication.restoreOverrideCursor()
        self.state_manager.set_state(AppState.IDLE)
        if self.test_runner_widget:
            self.test_runner_widget.deleteLater()
            self.test_runner_widget = None
        
        self.set_selection_enabled(True)
        if hasattr(self, "selection_scroll_area"):
            self.selection_scroll_area.verticalScrollBar().setValue(0)
        self.load_control_panel_data()
        if self.selected_destination_id:
            # Ricarica i dispositivi per riflettere lo stato più recente
            previously_selected_device = self.selected_device_id
            self.reload_devices()

            # Mantieni la selezione del dispositivo se ancora presente
            if previously_selected_device:
                for i in range(self.device_list.count()):
                    item = self.device_list.item(i)
                    if item.data(Qt.UserRole) == previously_selected_device:
                        self.device_list.setCurrentItem(item)
                        self.on_device_selected_new(item)
                        break
            else:
                self.update_summary_panel()
        else:
            self.update_summary_panel()

    def set_selection_enabled(self, enabled):
        if enabled:
            if hasattr(self, "selection_scroll_area"):
                self.selection_scroll_area.show()
                self.selection_scroll_area.verticalScrollBar().setValue(0)
            self.selection_container.show()
            self.test_runner_container.hide()
        else:
            if hasattr(self, "selection_scroll_area"):
                self.selection_scroll_area.hide()
            self.selection_container.hide()
            self.test_runner_container.show()
        self.menuBar().setEnabled(enabled)
    
    def quick_add_device(self):
        destination_id = self.selected_destination_id
        if not destination_id or destination_id == -1:
            destination_id = self.destination_selector.currentData()

        if not destination_id or destination_id == -1:
            QMessageBox.warning(self, "Attenzione", "Selezionare una destinazione prima di aggiungere un dispositivo.")
            return
        
        destination_data = services.database.get_destination_by_id(destination_id)
        if not destination_data: return
        customer_id = destination_data['customer_id']

        dialog = DeviceDialog(customer_id=customer_id, destination_id=destination_id, parent=self)
        if dialog.exec():
            data = dialog.get_data()
            try:
                new_device_id = services.add_device(**data)
                if self.selected_destination_id == destination_id:
                    self.reload_devices()
                    # Seleziona il dispositivo appena creato
                    self._select_device_by_id(new_device_id)
                else:
                    self.on_destination_selected()
                    # Seleziona il dispositivo appena creato
                    self._select_device_by_id(new_device_id)
                self.update_summary_panel()
            except services.DeletedDeviceFoundException as e:
                # Dispositivo eliminato trovato con lo stesso S/N
                from app.ui.dialogs.reactivate_device_dialog import ReactivateDeviceDialog
                reactivate_dialog = ReactivateDeviceDialog(e.deleted_device, parent=self)
                
                if reactivate_dialog.exec():
                    if reactivate_dialog.reactivate_choice:
                        # Utente ha scelto di riattivare
                        try:
                            services.update_device(
                                dev_id=e.deleted_device['id'],
                                destination_id=data['destination_id'],
                                serial=data['serial'],
                                desc=data['desc'],
                                mfg=data['mfg'],
                                model=data['model'],
                                department=data['department'],
                                applied_parts=data['applied_parts'],
                                customer_inv=data['customer_inv'],
                                ams_inv=data['ams_inv'],
                                verification_interval=data['verification_interval'],
                                default_profile_key=data['default_profile_key'],
                                default_functional_profile_key=data['default_functional_profile_key'],
                                reactivate=True
                            )
                            reactivated_device_id = e.deleted_device['id']
                            if self.selected_destination_id == destination_id:
                                self.reload_devices()
                                # Seleziona il dispositivo riattivato
                                self._select_device_by_id(reactivated_device_id)
                            else:
                                self.on_destination_selected()
                                # Seleziona il dispositivo riattivato
                                self._select_device_by_id(reactivated_device_id)
                            self.update_summary_panel()
                            QMessageBox.information(self, "✓ Dispositivo Riattivato", 
                                                  "Il dispositivo è stato riattivato con successo!")
                        except Exception as ex:
                            QMessageBox.critical(self, "Errore", 
                                               f"Impossibile riattivare il dispositivo:\n{str(ex)}")
                    else:
                        # Utente ha scelto di creare un nuovo dispositivo
                        try:
                            new_device_id = services.add_device(**data, force_create=True)
                            if self.selected_destination_id == destination_id:
                                self.reload_devices()
                                # Seleziona il dispositivo appena creato
                                self._select_device_by_id(new_device_id)
                            else:
                                self.on_destination_selected()
                                # Seleziona il dispositivo appena creato
                                self._select_device_by_id(new_device_id)
                            self.update_summary_panel()
                            QMessageBox.information(self, "✓ Dispositivo Creato", 
                                                  "Nuovo dispositivo creato con successo!")
                        except Exception as ex:
                            QMessageBox.critical(self, "Errore", 
                                               f"Impossibile creare il dispositivo:\n{str(ex)}")
            except ValueError as e:
                QMessageBox.warning(self, "Errore", str(e))

    def confirm_and_force_push(self):
        reply = QMessageBox.question(
            self, "Conferma Forza Upload",
            ("Questa azione segna TUTTI i dati locali come da sincronizzare e li invierà al server "
            "alla prossima sincronizzazione.\n\nProcedere?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            stats = services.force_full_push()
            self.run_synchronization(full_sync=False)
            QMessageBox.information(self, "Operazione completata",
                                    "Tutti i dati sono stati marcati come da sincronizzare.\n"
                                    "Ho avviato la sincronizzazione.")
        except Exception as e:
            logging.exception("Errore durante force_full_push")
            QMessageBox.critical(self, "Errore", f"Impossibile preparare il full push:\n{e}")

    def restore_database(self):
        reply = QMessageBox.question(self, 'Conferma Ripristino Database',
                                     "<b>ATTENZIONE:</b> L'operazione è irreversibile.\n\nL'applicazione verrà chiusa al termine. Vuoi continuare?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No: return
        backup_path, _ = QFileDialog.getOpenFileName(self, "Seleziona un file di backup", "backups", "File di Backup (*.bak)")
        if not backup_path: return
        success = restore_from_backup(backup_path)
        if success:
            QMessageBox.information(self, "Ripristino Completato", "Database ripristinato con successo. L'applicazione verrà chiusa.")
        else:
            QMessageBox.critical(self, "Errore di Ripristino", "Errore durante il ripristino. Controllare i log.")
        QApplication.quit()

    def set_company_logo(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Seleziona Logo", "", "Image Files (*.png *.jpg *.jpeg)")
        if filename:
            self.logo_path = filename
            self.settings.setValue("logo_path", filename)
            QMessageBox.information(self, "Impostazioni Salvate", f"Logo impostato su:\n{filename}")

    def open_instrument_manager(self):
        dialog = InstrumentManagerDialog(self)
        dialog.exec()

    def closeEvent(self, event):
        # --- INIZIO MODIFICA: Controllo stato prima di chiudere ---
        if not self.state_manager.is_idle():
            QMessageBox.warning(self, "Operazione in Corso", "Attendi la fine della sincronizzazione o di altre operazioni prima di chiudere.")
            event.ignore()
            return
        # --- FINE MODIFICA ---
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)

    def apply_permissions(self):
        user_role = auth_manager.get_current_role()
        user_info = auth_manager.get_current_user_info()
        self.setWindowTitle(f"Safety Test Manager {config.VERSIONE} - Utente: {user_info['full_name']}")
        is_technician = (user_role == 'technician')
        is_admin = (user_role == 'admin')
        is_quality_manager = user_role in ['admin', 'power_user']
        if hasattr(self, 'manage_profiles_action'):
            self.manage_profiles_action.setVisible(not is_technician)
        if hasattr(self, 'manage_functional_profiles_action'):
            self.manage_functional_profiles_action.setVisible(not is_technician)
        if hasattr(self, 'manage_users_action'):
            self.manage_users_action.setVisible(not is_technician)
        if hasattr (self, 'force_push_action' ):
            self.force_push_action.setVisible(not is_technician)
        if hasattr (self, 'manage_instruments_action' ):
            self.manage_instruments_action.setVisible(not is_technician)
        # Solo ADMIN può vedere "Correggi Descrizioni Dispositivi" e "Controllo Qualità Dati"
        if hasattr(self, 'correction_action'):
            self.correction_action.setVisible(is_admin)
        if hasattr(self, 'data_quality_action'):
            self.data_quality_action.setVisible(is_admin)
        if hasattr(self, 'deleted_data_action'):
            self.deleted_data_action.setVisible(is_admin)
        # Funzioni per responsabili qualità / direzione (admin + power_user)
        if hasattr(self, 'stats_action'):
            self.stats_action.setVisible(is_quality_manager)
        if hasattr(self, 'audit_log_action'):
            self.audit_log_action.setVisible(is_quality_manager)

    def update_device_list(self):
        customer_id = self.customer_selector.currentData()
        self.device_selector.clear()
        if not customer_id or customer_id == -1:
            return
        # Compatibilità: in questo flusso legacy mostriamo tutti i dispositivi cliente.
        devices = services.database.get_devices_for_customer(customer_id)
        for dev_row in devices:
            dev = dict(dev_row)
            display_text = f"{dev.get('description')} (S/N: {dev.get('serial_number')} - (Inv AMS: {dev.get('ams_inventory')})"
            if dev.get('ams_inventory'):
                display_text += f" / Inv. AMS: {dev.get('ams_inventory')}"
            display_text += ")"
            self.device_selector.addItem(display_text, dev.get('id'))

    def open_profile_manager(self):
        """Apre la finestra di dialogo per la gestione dei profili."""
        dialog = ProfileManagerDialog(self)
        dialog.exec()
        
        # Se i profili sono cambiati, ricarica il ComboBox nella UI principale
        if dialog.profiles_changed:
            logging.info("I profili sono stati modificati. Ricaricamento in corso...")
            # --- INIZIO CODICE CORRETTO ---
            config.load_verification_profiles() # Ricarica i profili dalla fonte dati (DB)
            self.load_profiles() # Usa la funzione corretta per popolare il combobox
            self.load_functional_profiles()
            # --- FINE CODICE CORRETTO ---
            QMessageBox.information(self, "Profili Aggiornati", "La lista dei profili è stata aggiornata.")

    def open_functional_profile_manager(self):
        """Apre la gestione dei profili funzionali."""
        dialog = FunctionalProfileManagerDialog(self)
        dialog.exec()

        if dialog.profiles_changed:
            logging.info("Profili funzionali aggiornati. Ricarico dati in memoria...")
            config.load_functional_profiles()
            self.load_functional_profiles()
            QMessageBox.information(
                self,
                "Profili Aggiornati",
                "La lista dei profili funzionali è stata aggiornata.",
            )

    def apply_theme(self, theme: str):
        """
        Applica il tema selezionato all'applicazione.
        
        Args:
            theme: "light" o "dark"
        """
        self.current_theme = theme
        stylesheet = config.get_theme_stylesheet(theme)
        
        # Applica lo stylesheet alla main window
        self.setStyleSheet(stylesheet)
        
        # Aggiorna le icone del menu in base al tema
        self._update_menu_icons(theme)
        
        # Forza un refresh completo di tutti i widget
        QApplication.processEvents()
        
        # Aggiorna tutti i widget figli forzando un repaint
        try:
            for widget in self.findChildren(QWidget):
                try:
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)
                    # Usa repaint() invece di update() per evitare problemi con override
                    widget.repaint()
                except Exception as e:
                    # Ignora errori su singoli widget
                    logging.debug(f"Errore aggiornamento widget durante cambio tema: {e}")
        except Exception as e:
            logging.warning(f"Errore durante aggiornamento widget per cambio tema: {e}")
        
        self.settings.setValue("theme", theme)
        if hasattr(self, 'theme_action'):
            self.update_theme_action_text()
        
        # Aggiorna lo sfondo dei campi nel summaryFrame
        self._update_summary_fields_background()
        
        # Aggiorna anche tutti i dialog aperti che hanno un riferimento alla main window
        try:
            for widget in QApplication.allWidgets():
                if isinstance(widget, QDialog) and widget.parent() == self:
                    if hasattr(widget, 'main_window') and widget.main_window == self:
                        widget.setStyleSheet(stylesheet)
                        try:
                            for child in widget.findChildren(QWidget):
                                child.style().unpolish(child)
                                child.style().polish(child)
                                child.repaint()
                        except Exception as e:
                            logging.debug(f"Errore aggiornamento widget dialog: {e}")
                    elif widget.parent() == self:
                        widget.setStyleSheet(stylesheet)
                        try:
                            for child in widget.findChildren(QWidget):
                                child.style().unpolish(child)
                                child.style().polish(child)
                                child.repaint()
                        except Exception as e:
                            logging.debug(f"Errore aggiornamento widget dialog: {e}")
        except Exception as e:
            logging.warning(f"Errore durante aggiornamento dialog per cambio tema: {e}")
    
    def _update_menu_icons(self, theme: str):
        """Aggiorna le icone del menu in base al tema."""
        icon_color = "#ffffff" if theme == "dark" else "#000000"
        
        # Mappa delle azioni principali alle loro icone qtawesome
        # Usa getattr con None come default per evitare AttributeError se l'attributo non esiste ancora
        icon_updates = [
            ('fa5s.file-excel', getattr(self, 'export_inventory_action', None)),
            ('fa5s.file-alt', getattr(self, 'export_log_action', None)),
            ('fa5s.search', getattr(self, 'advanced_search_action', None)),
            ('fa5s.file-pdf', getattr(self, 'advanced_report_action', None)),
            ('fa5s.sign-out-alt', getattr(self, 'logout_action', None)),
            ('fa5s.server', getattr(self, 'full_sync_action', None)),
            ('fa5s.cloud-upload-alt', getattr(self, 'force_push_action', None)),
            ('fa5s.database', getattr(self, 'ripristina_db_action', None)),
            ('fa5s.magic', getattr(self, 'correction_action', None)),
            ('fa5s.clone', getattr(self, 'duplicates_action', None)),
            ('fa5s.check-circle', getattr(self, 'data_quality_action', None)),
            ('fa5s.chart-bar', getattr(self, 'stats_action', None)),
            ('fa5s.history', getattr(self, 'audit_log_action', None)),
            ('fa5s.plug', getattr(self, 'set_com_port_action', None)),
            ('fa5s.tools', getattr(self, 'manage_instruments_action', None)),
            ('fa5s.image', getattr(self, 'set_logo_action', None)),
            ('fa5s.users-cog', getattr(self, 'manage_users_action', None)),
            ('fa5s.clipboard-list', getattr(self, 'manage_profiles_action', None)),
            ('fa5s.heartbeat', getattr(self, 'manage_functional_profiles_action', None)),
            ('fa5s.file-signature', getattr(self, 'manage_signature_action', None)),
            ('fa5s.palette', getattr(self, 'theme_action', None)),
            ('fa5s.list-alt', getattr(self, 'changelog_action', None)),
            ('fa5s.download', getattr(self, 'update_action', None)),
        ]
        
        # Aggiorna le icone delle azioni salvate come attributi
        for icon_key, action in icon_updates:
            if action:
                try:
                    new_icon = qta.icon(icon_key, color=icon_color)
                    action.setIcon(new_icon)
                except Exception as e:
                    logging.debug(f"Errore aggiornamento icona {icon_key}: {e}")
        
        # Le icone vengono aggiornate solo tramite la lista icon_updates sopra
        # Non serve più il metodo ricorsivo che sovrascriveva tutte le icone
    
    def _update_summary_fields_background(self):
        """Mantiene stile coerente dei campi summary senza sfondi grigi indesiderati."""
        if not hasattr(self, 'profile_selector') or not hasattr(self, 'functional_profile_selector'):
            return
        
        if self.current_theme == "dark":
            border_color = "#334155"
            border_focus = "#60a5fa"
            border_hover = "#475569"
            bg_color = "#1e293b"
            fg_color = "#e2e8f0"
        else:
            border_color = "#e2e8f0"
            border_focus = "#3b82f6"
            border_hover = "#cbd5e1"
            bg_color = "#ffffff"
            fg_color = "#334155"
        
        base_style = f"""
            QComboBox {{
                font-size: 11pt;
                background-color: {bg_color};
                border: 2px solid {border_color};
                border-radius: 10px;
                padding: 11px 16px;
                color: {fg_color};
            }}
            QComboBox::drop-down {{
                background-color: transparent;
                border: none;
            }}
            QComboBox:focus {{
                background-color: {bg_color};
                border: 2px solid {border_focus};
            }}
            QComboBox:hover {{
                background-color: {bg_color};
                border: 2px solid {border_hover};
            }}
        """
        self.profile_selector.setStyleSheet(base_style)
        self.functional_profile_selector.setStyleSheet(base_style)
        
        # Forza il repaint
        self.profile_selector.repaint()
        self.functional_profile_selector.repaint()
    
    def toggle_theme(self):
        """Cambia tra tema chiaro e scuro."""
        if self.current_theme == "light":
            self.apply_theme("dark")
        else:
            self.apply_theme("light")
    
    def update_theme_action_text(self):
        """Aggiorna il testo dell'azione del menu per riflettere il tema corrente."""
        if hasattr(self, 'theme_action'):
            if self.current_theme == "dark":
                self.theme_action.setText("Cambia Tema (Scuro → Chiaro)")
            else:
                self.theme_action.setText("Cambia Tema (Chiaro → Scuro)")

    def open_signature_manager(self):
        dialog = SignatureManagerDialog(self)
        dialog.exec()

    def logout(self):
        reply = QMessageBox.question(self, 'Conferma Logout', 
                                     'Sei sicuro di voler effettuare il logout?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            auth_manager.logout()
            self.relogin_requested = True
            self.close()

    def open_user_manager(self):
        dialog = UserManagerDialog(self)
        dialog.exec()

    def configure_com_port(self):
        current_port = self.settings.value("global_com_port", "COM1")
        try:
            available_ports = FlukeESA612.list_available_ports()
        except:
            available_ports = ["COM1", "COM2", "COM3", "COM4"]
        
        # Prova a rilevare automaticamente la porta COM
        detected_port = None
        reply = QMessageBox.question(
            self,
            "Rilevamento Automatico",
            "Vuoi rilevare automaticamente la porta COM dello strumento Fluke?\n\n"
            "Questo testerà tutte le porte COM disponibili (può richiedere alcuni secondi).",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            # Mostra un messaggio di attesa
            QMessageBox.information(
                self,
                "Rilevamento in Corso",
                "Rilevamento automatico della porta COM in corso...\n\n"
                "Assicurati che lo strumento Fluke sia acceso e collegato."
            )
            
            # Rileva automaticamente la porta
            detected_port = FlukeESA612.detect_fluke_port()
            
            if detected_port:
                QMessageBox.information(
                    self,
                    "Porta COM Rilevata",
                    f"Porta COM rilevata automaticamente: {detected_port}\n\n"
                    "Vuoi utilizzare questa porta?"
                )
                current_port = detected_port
            else:
                QMessageBox.warning(
                    self,
                    "Rilevamento Fallito",
                    "Impossibile rilevare automaticamente la porta COM.\n\n"
                    "Seleziona manualmente la porta COM dall'elenco."
                )
        
        # Se non è stata rilevata o l'utente ha scelto di selezionare manualmente
        if not detected_port:
            port, ok = QInputDialog.getItem(
                self, "Configura Porta COM",
                "Seleziona la porta COM per lo strumento di misura:",
                available_ports,
                available_ports.index(current_port) if current_port in available_ports else 0,
                False
            )
            if ok and port:
                current_port = port
        
        if current_port:
            self.settings.setValue("global_com_port", current_port)
            # Aggiorna anche la porta COM nello strumento corrente se è già stato selezionato
            if self.current_mti_info:
                self.current_mti_info['com_port'] = current_port
                logging.info(f"Porta COM aggiornata nello strumento corrente: {current_port}")
            QMessageBox.information(self, "Impostazioni Salvate", 
                                f"Porta COM impostata su: {current_port}\n\nQuesta verrà utilizzata per tutti gli strumenti.")
    
    def run_synchronization(self, full_sync=False):
        # --- INIZIO MODIFICA: Controllo stato prima di avviare sync ---
        if not self.state_manager.can_sync():
            QMessageBox.warning(self, "Operazione non permessa", "Impossibile avviare la sincronizzazione mentre un'altra operazione è in corso.")
            return
        # --- FINE MODIFICA ---
        if full_sync:
            reply = QMessageBox.question(self, 'Conferma Sincronizzazione Totale',
                                         "<b>ATTENZIONE:</b> Questa operazione eliminerà tutti i dati locali e li riscaricherà dal server. Le modifiche non sincronizzate andranno perse.\n\nSei sicuro di voler continuare?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return

        self.start_sync_thread(full_sync) 

    def start_sync_thread(self, full_sync=False):
        """
        Avvia il processo di sincronizzazione in un thread separato
        e gestisce correttamente tutti i possibili esiti.
        """
        self.set_ui_enabled(False)
        # 1. Imposta lo stato di "sincronizzazione in corso"
        self.state_manager.set_state(AppState.SYNCING, "Sincronizzazione in corso...")

        # 2. Prepara il worker e il thread
        self.sync_thread = QThread()
        self.sync_worker = SyncWorker(full_sync=full_sync)
        self.sync_worker.moveToThread(self.sync_thread)

        # 3. Connetti i segnali del worker agli slot di gestione
        self.sync_thread.started.connect(self.sync_worker.run)
        self.sync_worker.finished.connect(self.on_sync_success)
        self.sync_worker.error.connect(self.on_sync_error)
        self.sync_worker.conflict.connect(self.on_sync_conflict)
        self.sync_worker.success_with_conflicts.connect(self.on_sync_success_with_conflicts)
        # Sessione scaduta / token non valido
        self.sync_worker.auth_error.connect(self.on_sync_auth_error)

        # Assicura che il thread venga chiuso in ogni caso
        self.sync_worker.finished.connect(self.sync_thread.quit)
        self.sync_worker.error.connect(self.sync_thread.quit)
        self.sync_worker.conflict.connect(self.sync_thread.quit)
        self.sync_worker.success_with_conflicts.connect(self.sync_thread.quit)
        self.sync_worker.auth_error.connect(self.sync_thread.quit)

        # Pulisce le risorse
        self.sync_thread.finished.connect(self.sync_thread.deleteLater)
        self.sync_worker.finished.connect(self.sync_worker.deleteLater)
        self.sync_worker.error.connect(self.sync_worker.deleteLater)
        self.sync_worker.conflict.connect(self.sync_worker.deleteLater)
        self.sync_worker.success_with_conflicts.connect(self.sync_worker.deleteLater)
        self.sync_worker.auth_error.connect(self.sync_worker.deleteLater)

        # 4. Avvia il thread
        self.sync_thread.start()

    def on_sync_success(self, message):
        """Gestisce il caso di sincronizzazione completata con successo."""
        QMessageBox.information(self, "Sincronizzazione Completata", message)
        self.on_sync_finished() # Chiama la funzione di pulizia

    def on_sync_success_with_conflicts(self, message):
        """Gestisce il caso di sincronizzazione completata ma con conflitti da risolvere."""
        self.on_sync_finished()  # Prima ripristina lo stato UI
        
        # Mostra messaggio con opzione di risolvere subito
        reply = QMessageBox.warning(
            self,
            "Sincronizzazione Completata con Conflitti",
            f"{message}\n\nVuoi risolvere i conflitti adesso?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            self._open_conflict_resolution_panel()
        
        # Aggiorna l'indicatore dei conflitti nella status bar
        self._update_conflict_indicator()

    def on_sync_finished(self):
        """
        Funzione centralizzata per ripristinare lo stato dell'UI
        al termine della sincronizzazione, indipendentemente dall'esito.
        """
        # Torna in stato IDLE e riabilita l'interfaccia
        self.state_manager.set_state(AppState.IDLE)
        self.set_ui_enabled(True)

        # Dopo la sincronizzazione ricarichiamo i profili dal database
        # così PROFILES e FUNCTIONAL_PROFILES riflettono il nuovo stato sincronizzato.
        try:
            config.load_verification_profiles()
            config.load_functional_profiles()
        except Exception as e:
            logging.error(f"Errore durante il ricaricamento dei profili post-sync: {e}", exc_info=True)

        # Ricarica tutti i dati (clienti, profili, ecc.) nell'interfaccia
        self.load_all_data()
        logging.info("Dati ricaricati dal database dopo la sincronizzazione.")
        
        # Pulizia conflitti già risolti per non accumulare dati obsoleti
        try:
            cleaned = database.delete_resolved_conflicts()
            if cleaned:
                logging.info(f"🧹 Pulizia: {cleaned} conflitti risolti rimossi dal database")
        except Exception as e:
            logging.debug(f"Errore pulizia conflitti risolti: {e}")

        # Aggiorna l'indicatore dei conflitti
        self._update_conflict_indicator()

        # In ogni caso, la sync (automatica o manuale) NON riavvia più il programma.
        # Azzeriamo solo il flag della sync automatica se era impostato.
        if self._auto_sync_started:
            logging.info("Sync automatica completata.")
            self._auto_sync_started = False
            # Mostra avviso strumenti in scadenza dopo sincronizzazione automatica
            self._check_expiring_devices()
    
    def _check_expiring_devices(self):
        """Controlla e mostra gli strumenti di misura in scadenza nei prossimi 30 giorni."""
        try:
            instruments = database.get_instruments_needing_calibration(days_in_future=30)
            
            if instruments:
                # Mostra il dialog con gli strumenti di misura in scadenza
                dialog = ExpiringDevicesDialog(self)
                dialog.exec()
        except Exception as e:
            logging.error(f"Errore durante il controllo strumenti di misura in scadenza: {e}", exc_info=True)
            # Non mostriamo un errore all'utente se il controllo fallisce

    # =========================================================================
    # GESTIONE CONFLITTI DI SINCRONIZZAZIONE
    # =========================================================================

    def _setup_conflict_indicator(self):
        """Crea l'indicatore dei conflitti nella status bar."""
        self.conflict_btn = QPushButton()
        self.conflict_btn.setFlat(True)
        self.conflict_btn.setCursor(Qt.PointingHandCursor)
        self.conflict_btn.clicked.connect(self._open_conflict_resolution_panel)
        self.conflict_btn.setToolTip("Clicca per risolvere i conflitti di sincronizzazione")
        self.conflict_btn.hide()  # Nascosto di default
        self.statusBar().addPermanentWidget(self.conflict_btn)
        
        # Aggiorna all'avvio
        QTimer.singleShot(2000, self._update_conflict_indicator)

    def _update_conflict_indicator(self):
        """Aggiorna l'indicatore dei conflitti nella status bar."""
        try:
            count = database.get_pending_conflicts_count()
            if count > 0:
                self.conflict_btn.setText(f"⚠️ {count} conflitt{'o' if count == 1 else 'i'} da risolvere")
                self.conflict_btn.setStyleSheet(
                    "QPushButton { color: #BF616A; font-weight: bold; padding: 2px 8px; "
                    "border: 1px solid #BF616A; border-radius: 4px; background: transparent; }"
                    "QPushButton:hover { background: rgba(191, 97, 106, 0.15); }"
                )
                self.conflict_btn.show()
            else:
                self.conflict_btn.hide()
        except Exception as e:
            logging.error(f"Errore aggiornamento indicatore conflitti: {e}")

    def _setup_qr_server_statusbar(self):
        """Crea il pulsante toggle server QR nella status bar, visibile da qualsiasi schermata."""
        self.qr_statusbar_btn = QPushButton("📱 Scanner QR")
        self.qr_statusbar_btn.setFlat(True)
        self.qr_statusbar_btn.setCursor(Qt.PointingHandCursor)
        self.qr_statusbar_btn.setToolTip(
            "Click: Attiva/disattiva lo scanner QR\n"
            "Quando attivo, il telefono può inviare scansioni e allegati"
        )
        self.qr_statusbar_btn.setStyleSheet(
            "QPushButton { color: #888; padding: 2px 10px; border: 1px solid #888; "
            "border-radius: 4px; background: transparent; font-size: 9pt; }"
            "QPushButton:hover { background: rgba(136, 136, 136, 0.15); }"
        )
        self.qr_statusbar_btn.clicked.connect(self._on_qr_statusbar_clicked)
        self.statusBar().addPermanentWidget(self.qr_statusbar_btn)

    def _on_qr_statusbar_clicked(self):
        """Gestisce il click sul pulsante QR nella status bar."""
        if hasattr(self, 'qr_scanner_server_running') and self.qr_scanner_server_running:
            # Server attivo: mostra menu con opzioni
            menu = QMenu(self)
            show_qr_action = menu.addAction("📱 Mostra QR Code")
            show_qr_action.triggered.connect(self._show_qr_scanner_dialog)
            menu.addSeparator()
            stop_action = menu.addAction("🔴 Disattiva Scanner")
            stop_action.triggered.connect(self._stop_qr_scanner_server)
            # Mostra il menu sotto il pulsante
            btn_pos = self.qr_statusbar_btn.mapToGlobal(
                self.qr_statusbar_btn.rect().topLeft()
            )
            menu.exec(btn_pos)
        else:
            # Server non attivo: avvia
            self._start_qr_scanner_server()

    def _update_qr_statusbar(self, active: bool):
        """Aggiorna l'aspetto del pulsante QR nella status bar."""
        if not hasattr(self, 'qr_statusbar_btn'):
            return
        if active:
            url = getattr(self, 'qr_scanner_url', '')
            self.qr_statusbar_btn.setText("📱 Scanner QR 🟢")
            self.qr_statusbar_btn.setToolTip(
                f"Scanner ATTIVO: {url}\n"
                f"Click: mostra QR code per il telefono"
            )
            self.qr_statusbar_btn.setStyleSheet(
                "QPushButton { color: #2E7D32; font-weight: bold; padding: 2px 10px; "
                "border: 1px solid #4CAF50; border-radius: 4px; background: rgba(76, 175, 80, 0.1); font-size: 9pt; }"
                "QPushButton:hover { background: rgba(76, 175, 80, 0.25); }"
            )
        else:
            self.qr_statusbar_btn.setText("📱 Scanner QR")
            self.qr_statusbar_btn.setToolTip(
                "Click: Attiva lo scanner QR\n"
                "Quando attivo, il telefono può inviare scansioni e allegati"
            )
            self.qr_statusbar_btn.setStyleSheet(
                "QPushButton { color: #888; padding: 2px 10px; border: 1px solid #888; "
                "border-radius: 4px; background: transparent; font-size: 9pt; }"
                "QPushButton:hover { background: rgba(136, 136, 136, 0.15); }"
            )

    def _open_conflict_resolution_panel(self):
        """Apre il pannello di risoluzione conflitti."""
        try:
            from app.ui.dialogs.sync_conflicts_dialog import SyncConflictsDialog
            dialog = SyncConflictsDialog(self)
            dialog.conflicts_resolved.connect(self._on_conflicts_panel_closed)
            dialog.exec()
            self._update_conflict_indicator()
        except Exception as e:
            logging.error(f"Errore apertura pannello conflitti: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile aprire il pannello conflitti: {e}")

    def _on_conflicts_panel_closed(self):
        """
        Chiamato quando l'utente ha risolto almeno un conflitto nel pannello.
        Propone una nuova sincronizzazione per applicare le risoluzioni.
        """
        self._update_conflict_indicator()
        pending = database.get_pending_conflicts_count()
        if pending == 0:
            reply = QMessageBox.question(
                self,
                "Tutti i Conflitti Risolti",
                "Tutti i conflitti sono stati risolti.\n\n"
                "Vuoi avviare una nuova sincronizzazione per applicare le modifiche?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self.run_synchronization()

    def on_sync_error(self, error_message):
        """Gestisce il caso di errore durante la sincronizzazione."""
        QMessageBox.critical(self, "Errore di Sincronizzazione", error_message)
        self.set_ui_enabled(True)
        self.on_sync_finished() # Chiama la funzione di pulizia

    def on_sync_auth_error(self, message: str):
        """
        Gestisce in modo specifico il caso di token scaduto / sessione non valida.
        Mostra un messaggio chiaro e forza il ri-login dell'utente.
        """
        # Ripristina subito lo stato UI
        self.on_sync_finished()

        # Determina il titolo in base al tipo di errore
        is_token_expired = "scaduto" in message.lower()
        title = "Token di Accesso Scaduto" if is_token_expired else "Sessione Non Valida"

        QMessageBox.warning(
            self,
            title,
            f"{message}\n\nL'applicazione verrà chiusa per permettere un nuovo login."
        )

        # Segnala al ciclo principale che è richiesto un nuovo login
        self.relogin_requested = True
        # Chiude la finestra principale: il main loop intercetterà relogin_requested e
        # riaprirà la finestra di login.
        self.close()

    @staticmethod
    def _normalize_conflict(conflict):
        """
        Normalizza il conflitto in un formato consistente.
        
        Gestisce tre formati:
        1. Classico: {'client_version': {...}, 'server_version': {...}}
        2. Detailed dal server con server_version completo: {'conflicting_fields': [...], 'server_version': {...}, ...}
        3. Detailed dal server senza server_version: {'conflicting_fields': [...], ...} (legacy)
        
        Ritorna: (client_version, server_version) sempre come dict
        """
        # Se è già nel formato classico, usa direttamente
        if 'client_version' in conflict or 'local_version' in conflict:
            client_version = conflict.get('client_version') or conflict.get('local_version', {})
            server_version = conflict.get('server_version', {})
            return client_version, server_version
        
        # Se il server ha inviato il record completo, usalo
        if 'server_version' in conflict:
            client_version = {}
            
            # Estrai i campi in conflitto dal client se disponibili
            for field_conflict in conflict.get('conflicting_fields', []):
                field_name = field_conflict.get('field')
                if field_name:
                    client_version[field_name] = field_conflict.get('client_value')
            
            # Aggiungi uuid ai dati del client per completezza
            if 'uuid' in conflict:
                client_version['uuid'] = conflict['uuid']
            
            # Usa il server_version completo inviato dal server
            server_version = conflict.get('server_version', {})
            return client_version, server_version
        
        # Se è nel formato detailed dal server SENZA server_version completo (legacy), ricostruisci dai conflicting_fields
        if 'conflicting_fields' in conflict:
            client_version = {}
            server_version = {}
            
            for field_conflict in conflict.get('conflicting_fields', []):
                field_name = field_conflict.get('field')
                if field_name:
                    client_version[field_name] = field_conflict.get('client_value')
                    server_version[field_name] = field_conflict.get('server_value')
            
            # Aggiungi uuid per completezza (è sempre presente nei dati del record)
            if 'uuid' in conflict:
                client_version['uuid'] = conflict['uuid']
                server_version['uuid'] = conflict['uuid']
            
            return client_version, server_version
        
        # Fallback: ritorna vuoti
        return {}, {}

    def on_sync_conflict(self, conflicts):
        """
        Gestisce i conflitti PUSH rilevati dal server.
        Li salva nel database locale (come i conflitti PULL) e apre il pannello
        unificato di gestione conflitti, così l'utente può risolverli con
        le stesse modalità (mantieni locale, usa server, merge per-campo).
        """
        # Ripristina lo stato UI
        self.state_manager.set_state(AppState.IDLE)
        self.set_ui_enabled(True)

        # Salva ogni conflitto PUSH nel database locale
        import uuid as uuid_module
        persisted = 0
        for conflict in (conflicts or []):
            try:
                conflict_id = str(uuid_module.uuid4())

                # Normalizza: estrai client/server version
                client_version, server_version = self._normalize_conflict(conflict)

                table_name = conflict.get('table', 'unknown')
                record_uuid = (
                    conflict.get('uuid')
                    or client_version.get('uuid')
                    or server_version.get('uuid')
                )
                conflict_type = conflict.get('reason', 'modification_conflict')
                severity = conflict.get('severity', 'high')
                error_message = conflict.get('message', '')
                if not error_message:
                    # Costruisci un messaggio leggibile
                    error_message = (
                        f"Il server ha rilevato un conflitto di tipo '{conflict_type}' "
                        f"nella tabella '{table_name}' durante il push."
                    )

                database.save_sync_conflict(
                    conflict_id=conflict_id,
                    table_name=table_name,
                    record_uuid=record_uuid,
                    conflict_type=conflict_type,
                    severity=severity,
                    local_data=client_version if client_version else None,
                    server_data=server_version if server_version else None,
                    error_message=error_message
                )
                persisted += 1
            except Exception as e:
                logging.error(f"Errore nel salvataggio del conflitto PUSH: {e}", exc_info=True)

        logging.info(f"📌 {persisted}/{len(conflicts or [])} conflitti PUSH salvati nel database locale")

        # Aggiorna l'indicatore nella status bar
        self._update_conflict_indicator()

        # Apri il pannello unificato di gestione conflitti
        try:
            from app.ui.dialogs.sync_conflicts_dialog import SyncConflictsDialog
            dialog = SyncConflictsDialog(self)
            dialog.conflicts_resolved.connect(self._on_conflicts_panel_closed)
            dialog.exec()
            self._update_conflict_indicator()
        except Exception as e:
            logging.error(f"Errore apertura pannello conflitti: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile aprire il pannello conflitti: {e}")

    # --- INIZIO MODIFICA: Nuovo metodo per gestire i cambi di stato ---
    def handle_state_change(self, new_state: AppState):
        """Mostra o nasconde l'overlay in base allo stato dell'applicazione."""
        is_idle = new_state == AppState.IDLE

        if is_idle:
            self.overlay.hide()
            self.statusBar().clearMessage()
        else:
            # Per qualsiasi stato non-idle, mostra l'overlay
            self.overlay.show()
            self.overlay.raise_() # Assicura che sia sempre in primo piano

    def handle_state_message_change(self, message: str):
        """Aggiorna il testo sull'overlay o sulla status bar."""
        if not self.state_manager.is_idle():
            self.overlay.setText(message)
        elif message:
            self.statusBar().showMessage(message, 5000) # Mostra per 5 secondi se idle
    # --- FINE MODIFICA ---

    def set_ui_enabled(self, enabled):
        self.setEnabled(enabled)
        if enabled:
            self.overlay.hide()
        else:
            self.overlay.show()


    def open_db_manager(self, navigate_to=None):
        current_role = auth_manager.get_current_role()
        dialog = DbManagerDialog(role=current_role, parent=self)
        dialog.setWindowState(Qt.WindowMaximized)
        if navigate_to:
            dialog.navigate_on_load(navigate_to)
        dialog.exec()
        self.load_destinations()
        self.load_control_panel_data()
    
    def resizeEvent(self, event):
        """
        Assicura che l'overlay si ridimensioni sempre con la finestra principale.
        """
        super().resizeEvent(event)
        if hasattr(self, 'overlay'):
            self.overlay.resize(self.size())

    def _on_qr_button_clicked(self, checked: bool):
        """Gestisce click sul pulsante QR."""
        if hasattr(self, 'qr_scanner_server_running') and self.qr_scanner_server_running:
            # Server già attivo - mostra solo il dialog
            if checked:
                self._show_qr_scanner_dialog()
                self.qr_scan_btn.setChecked(True)  # Mantieni checked
            else:
                # L'utente vuole disattivare
                reply = QMessageBox.question(
                    self,
                    "Disattiva Scanner",
                    "Vuoi disattivare lo scanner QR?\n\n"
                    "Il telefono non potrà più inviare scansioni fino a riattivazione.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self._stop_qr_scanner_server()
                else:
                    self.qr_scan_btn.setChecked(True)
        else:
            # Server non attivo - avvia
            if checked:
                self._start_qr_scanner_server()
            
    def _toggle_qr_scanner(self, checked: bool):
        """Attiva/disattiva lo scanner QR in background."""
        if checked:
            self._start_qr_scanner_server()
        else:
            self._stop_qr_scanner_server()
    
    def _start_qr_scanner_server(self):
        """Avvia il server scanner QR in background."""
        from app.ui.dialogs.qr_device_scanner_dialog import QRDeviceScannerDialog, ThreadedQRServer, QRScannerHTTPHandler
        import socket
        import threading
        
        try:
            # Ottieni IP locale
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except:
            local_ip = "127.0.0.1"
        
        port = 8766
        
        # Imposta callback
        QRScannerHTTPHandler.scan_callback = self._on_qr_scan_received_from_server
        
        try:
            # Crea e avvia server
            self.qr_scanner_server = ThreadedQRServer(("0.0.0.0", port), QRScannerHTTPHandler)
            self.qr_scanner_server_running = True
            
            self.qr_scanner_thread = threading.Thread(target=self._qr_server_loop, daemon=True)
            self.qr_scanner_thread.start()
            
            self.qr_scanner_url = f"https://{local_ip}:{port}"
            
            # Aggiorna UI
            self.qr_scan_btn.setChecked(True)
            self.qr_scan_btn.setStyleSheet("""
                QPushButton { 
                    padding: 0px !important; margin: 0px !important; 
                    min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px;
                    background-color: #4CAF50 !important;
                    border: 2px solid #2E7D32 !important;
                }
            """)
            self.qr_status_indicator.setText("🟢")
            self.qr_status_indicator.setToolTip(f"Scanner attivo: {self.qr_scanner_url}")
            
            logging.info(f"[QR Scanner] Server avviato su {self.qr_scanner_url}")
            
            # Aggiorna indicatore nella status bar
            self._update_qr_statusbar(True)
            
            # Mostra dialog con QR code
            self._show_qr_scanner_dialog()
            
        except Exception as e:
            logging.error(f"Errore avvio server QR: {e}")
            QMessageBox.critical(self, "Errore", f"Impossibile avviare lo scanner:\n{str(e)}")
            self.qr_scan_btn.setChecked(False)
    
    def _qr_server_loop(self):
        """Loop del server QR."""
        while hasattr(self, 'qr_scanner_server_running') and self.qr_scanner_server_running:
            try:
                if self.qr_scanner_server:
                    self.qr_scanner_server.handle_request()
            except:
                pass
    
    def _stop_qr_scanner_server(self):
        """Ferma il server scanner QR."""
        self.qr_scanner_server_running = False
        
        if hasattr(self, 'qr_scanner_server') and self.qr_scanner_server:
            try:
                self.qr_scanner_server.socket.close()
            except:
                pass
            self.qr_scanner_server = None
        
        # Aggiorna UI
        self.qr_scan_btn.setChecked(False)
        self.qr_scan_btn.setStyleSheet("QPushButton { padding: 0px !important; margin: 0px !important; min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; }")
        self.qr_status_indicator.setText("")
        self.qr_status_indicator.setToolTip("Scanner QR non attivo")
        
        # Aggiorna indicatore nella status bar
        self._update_qr_statusbar(False)
        
        # Chiudi dialog se aperto
        if hasattr(self, 'qr_scanner_dialog') and self.qr_scanner_dialog:
            self.qr_scanner_dialog.close()
            self.qr_scanner_dialog = None
        
        logging.info("[QR Scanner] Server fermato")
    
    def _show_qr_scanner_dialog(self):
        """Mostra il dialog con QR code (server già attivo in background)."""
        from app.ui.dialogs.qr_device_scanner_dialog import QRDeviceScannerDialog
        
        # Usa la finestra attiva come parent, così il dialog appare sopra
        # anche quando è aperto un dialog modale (es. Gestione Anagrafiche)
        active_window = QApplication.activeWindow() or self
        
        # Crea nuovo dialog se non esiste o è stato chiuso
        if not hasattr(self, 'qr_scanner_dialog') or not self.qr_scanner_dialog or not self.qr_scanner_dialog.isVisible():
            self.qr_scanner_dialog = QRDeviceScannerDialog(active_window, continuous_mode=True, external_server=True)
            self.qr_scanner_dialog.device_scan_requested.connect(self._on_qr_scan_received)
        
        # Imposta URL e mostra QR
        if hasattr(self, 'qr_scanner_url'):
            self.qr_scanner_dialog._show_qr_code(self.qr_scanner_url)
            self.qr_scanner_dialog.status_label.setText(
                f"✅ Scanner ATTIVO in background!\n"
                f"📱 {self.qr_scanner_url}\n\n"
                f"Puoi chiudere questa finestra.\n"
                f"Il server continuerà ad ascoltare."
            )
            self.qr_scanner_dialog.status_label.setStyleSheet("""
                font-size: 10pt; 
                padding: 10px; 
                background: #e8f5e9;
                border-radius: 8px;
                border: 2px solid #4CAF50;
            """)
        
        self.qr_scanner_dialog.show()
        self.qr_scanner_dialog.raise_()
        self.qr_scanner_dialog.activateWindow()
    
    def _on_qr_scan_received_from_server(self, code: str):
        """Callback dal server (thread separato) - usa Signal per thread-safety."""
        logging.info(f"[QR Scanner] _on_qr_scan_received_from_server chiamato con: {code}")
        # Emetti il segnale (thread-safe, verrà ricevuto nel thread principale)
        self._qr_code_received.emit(code)
        logging.info(f"[QR Scanner] Segnale emesso per: {code}")
    
    def _on_qr_scan_received(self, code: str):
        """Gestisce una scansione QR ricevuta in modalità continua."""
        logging.info(f"[QR Scanner] _on_qr_scan_received chiamato con: {code}")
        
        if not code:
            logging.warning("[QR Scanner] Codice vuoto ricevuto, ignoro")
            return
        
        # Intercept: se un dialog (es. DeviceDialog) ha registrato un callback per UDI scan,
        # inoltra il codice a quel callback invece di cercare dispositivi
        if self._phone_scan_callback is not None:
            logging.info(f"[QR Scanner] Intercept attivo, inoltro codice a DeviceDialog: {code}")
            try:
                self._phone_scan_callback(code)
            except Exception as e:
                logging.error(f"[QR Scanner] Errore nel callback intercept: {e}", exc_info=True)
            return
        
        # Mostra notifica nella status bar
        self.statusBar().showMessage(f"🔍 Scansione ricevuta: {code}", 3000)
        logging.info(f"[QR Scanner] Avvio ricerca dispositivo per: {code}")
        
        # Cerca il dispositivo
        device_found, device_info = self._search_device_by_code_silent(code)
        
        # Aggiorna il dialog con il risultato (se visibile)
        if hasattr(self, 'qr_scanner_dialog') and self.qr_scanner_dialog and self.qr_scanner_dialog.isVisible():
            self.qr_scanner_dialog.show_search_result(device_found, device_info)
        
        # Mostra notifica risultato
        if device_found:
            self.statusBar().showMessage(f"✅ Dispositivo trovato: {device_info}", 5000)
            # Flash verde sul pulsante QR
            self._flash_qr_button("#4CAF50")
        else:
            self.statusBar().showMessage(f"❌ Dispositivo non trovato: {code}", 5000)
            # Flash rosso sul pulsante QR
            self._flash_qr_button("#f44336")

        # Salva ultimo risultato per app mobile
        try:
            from app.ui.dialogs.qr_device_scanner_dialog import QRScannerHTTPHandler
            QRScannerHTTPHandler.last_result = {
                "code": code,
                "found": device_found,
                "info": device_info,
            }
        except Exception:
            pass
    
    def _flash_qr_button(self, color: str):
        """Fa lampeggiare il pulsante QR per feedback visivo."""
        original_style = """
            QPushButton { 
                padding: 0px !important; margin: 0px !important; 
                min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px;
                background-color: #4CAF50 !important;
                border: 2px solid #2E7D32 !important;
            }
        """
        flash_style = f"""
            QPushButton {{ 
                padding: 0px !important; margin: 0px !important; 
                min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px;
                background-color: {color} !important;
                border: 3px solid white !important;
            }}
        """
        
        self.qr_scan_btn.setStyleSheet(flash_style)
        QTimer.singleShot(300, lambda: self.qr_scan_btn.setStyleSheet(original_style))
    
    def _extract_serial_from_udi(self, code: str) -> str:
        """
        Estrae il numero di serie da un codice UDI.
        Supporta formati:
        - GS1 Human Readable: (01)GTIN(21)SERIAL
        - GS1 DataMatrix: 01GTIN21SERIAL (senza parentesi)
        """
        import re
        
        # Rimuovi prefissi DataMatrix
        clean_code = re.sub(r'^\]d2|\]C1|\]e0|\]Q3', '', code)
        # Sostituisci GS separator (ASCII 29)
        clean_code = clean_code.replace(chr(29), '|')
        
        # Formato con parentesi: (21)SERIAL
        match = re.search(r'\(21\)([A-Za-z0-9\-]+?)(?:\(|$|\|)', code)
        if match:
            serial = match.group(1).strip()
            logging.info(f"[UDI] Seriale estratto (HR): {serial}")
            return serial
        
        # Formato DataMatrix senza parentesi: 21SERIAL
        # Il seriale termina con | o fine stringa o altro AI (10, 11, 17, 240)
        match = re.search(r'21([A-Za-z0-9\-]+?)(?:[|]|$|(?=10|11|17|240|30|91))', clean_code)
        if match:
            serial = match.group(1).strip()
            logging.info(f"[UDI] Seriale estratto (DM): {serial}")
            return serial
        
        return code  # Ritorna il codice originale se non è UDI
    
    def _search_device_by_code_silent(self, code: str) -> tuple:
        """
        Cerca un dispositivo tramite codice scansionato (versione silenziosa).
        Ritorna (found: bool, info: str)
        """
        logging.info(f"[QR Scanner] _search_device_by_code_silent chiamato con: {code}")
        
        # Pulisci il codice
        code = code.strip()
        original_code = code
        
        # Se sembra un codice UDI (contiene 01 seguito da 14 cifre o ha parentesi), estrai il seriale
        if '(21)' in code or ('01' in code and len(code) > 16):
            code = self._extract_serial_from_udi(code)
            if code != original_code:
                logging.info(f"[QR Scanner] Codice UDI -> Seriale: {code}")
        
        try:
            device = None
            
            # 1. Cerca per numero inventario AMS
            device = database.get_device_by_inventory_number(code)
            
            # 2. Se non trovato, cerca per numero di serie
            if not device:
                device = database.get_device_by_serial_number(code)
            
            # 3. Se non trovato, cerca per inventario cliente
            if not device:
                device = database.get_device_by_customer_inventory(code)
            
            # 4. Ricerca generica
            if not device:
                results = services.search_globally(code)
                if results:
                    device_results = [r for r in results if 'serial_number' in r]
                    if device_results:
                        device = device_results[0]
            
            if device:
                # Converti a dict se necessario
                if hasattr(device, 'keys'):
                    device_dict = dict(device)
                else:
                    device_dict = device
                
                description = device_dict.get('description', 'N/D')
                serial = device_dict.get('serial_number', 'N/D')
                
                logging.info(f"[QR Scanner] Dispositivo trovato: {description}")
                
                # Seleziona il dispositivo
                self.select_device_from_search(device_dict)
                
                return True, f"{description} (S/N: {serial})"
            else:
                return False, code
                
        except Exception as e:
            logging.error(f"Errore ricerca dispositivo: {e}", exc_info=True)
            return False, f"Errore: {str(e)}"
    
    def _search_device_by_code(self, code: str):
        """Cerca un dispositivo tramite codice scansionato (con messaggi UI)."""
        logging.info(f"[QR Scanner] Ricerca dispositivo con codice: {code}")
        
        # Pulisci il codice
        code = code.strip()
        original_code = code
        
        # Se sembra un codice UDI, estrai il seriale
        if '(21)' in code or ('01' in code and len(code) > 16):
            code = self._extract_serial_from_udi(code)
            if code != original_code:
                logging.info(f"[QR Scanner] Codice UDI -> Seriale: {code}")
        
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        try:
            # Cerca in diversi campi
            device = None
            
            # 1. Cerca per numero inventario AMS
            device = database.get_device_by_inventory_number(code)
            
            # 2. Se non trovato, cerca per numero di serie
            if not device:
                device = database.get_device_by_serial_number(code)
            
            # 3. Se non trovato, cerca per inventario cliente
            if not device:
                device = database.get_device_by_customer_inventory(code)
            
            # 4. Ricerca generica
            if not device:
                results = services.search_globally(code)
                if results:
                    # Filtra solo dispositivi
                    device_results = [r for r in results if 'serial_number' in r]
                    if len(device_results) == 1:
                        device = device_results[0]
                    elif len(device_results) > 1:
                        # Mostra dialog di selezione
                        QApplication.restoreOverrideCursor()
                        dialog = GlobalSearchDialog(device_results, self)
                        if dialog.exec():
                            self._handle_global_search_selection(dialog.selected_item)
                        return
            
            QApplication.restoreOverrideCursor()
            
            if device:
                # Converti a dict se necessario
                if hasattr(device, 'keys'):
                    device_dict = dict(device)
                else:
                    device_dict = device
                
                logging.info(f"[QR Scanner] Dispositivo trovato: {device_dict.get('description', 'N/D')}")
                
                # Seleziona il dispositivo
                self.select_device_from_search(device_dict)
                
                QMessageBox.information(
                    self, 
                    "Dispositivo Trovato",
                    f"Dispositivo selezionato:\n\n"
                    f"📋 {device_dict.get('description', 'N/D')}\n"
                    f"🔢 S/N: {device_dict.get('serial_number', 'N/D')}\n"
                    f"📦 Inv. AMS: {device_dict.get('AMS_inventory', 'N/D')}"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Dispositivo Non Trovato",
                    f"Nessun dispositivo trovato con il codice:\n\n{code}\n\n"
                    "Verifica che il codice sia corretto o che il dispositivo\n"
                    "sia presente nel database."
                )
                
        except Exception as e:
            QApplication.restoreOverrideCursor()
            logging.error(f"Errore ricerca dispositivo: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore durante la ricerca:\n{str(e)}")
    
    def perform_global_search(self):
        search_term = self.global_device_search_edit.text().strip()
        if len(search_term) < 3:
            QMessageBox.warning(self, "Ricerca", "Inserisci almeno 3 caratteri.")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            results = services.search_globally(search_term)
        except Exception as e:
            logging.error(f"Errore nella ricerca globale: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Si è verificato un errore durante la ricerca:\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()

            if not results:
                QMessageBox.information(self, "Ricerca", f"Nessun risultato trovato per '{search_term}'.")
                return

        if len(results) == 1:
            self._handle_global_search_selection(results[0])
            return

        dialog = GlobalSearchDialog(results, self)
        if dialog.exec():
            self._handle_global_search_selection(dialog.selected_item)

    def _handle_global_search_selection(self, selected_item: dict | None):
        """Instrada il risultato della ricerca globale al gestore corretto."""
        if not selected_item:
            return

        if 'serial_number' in selected_item:
            self.select_device_from_search(selected_item)
        elif 'customer_id' in selected_item and 'customer_name' in selected_item:
            self.select_destination_from_search(selected_item)
        else:
            self.select_customer_from_search(selected_item)

    def select_customer_from_search(self, customer_data: dict):
        """Seleziona un cliente dalla ricerca globale."""
        customer_id = customer_data.get('id')
        if not customer_id:
            QMessageBox.warning(self, "Dati Incompleti", "Impossibile selezionare il cliente, dati mancanti.")
            return

        for i in range(self.customer_list.count()):
            item = self.customer_list.item(i)
            if item.data(Qt.UserRole) == customer_id:
                self.customer_list.setCurrentItem(item)
                self.on_customer_selected(item)
                QApplication.processEvents()
                break

    def select_destination_from_search(self, destination_data: dict):
        """Seleziona una destinazione dalla ricerca globale usando il nuovo sistema a 3 colonne."""
        destination_id = destination_data.get('id')
        customer_id = destination_data.get('customer_id')

        if not destination_id or not customer_id:
            QMessageBox.warning(self, "Dati Incompleti", "Impossibile selezionare la destinazione, dati mancanti.")
            return

        # Seleziona il cliente
        for i in range(self.customer_list.count()):
            item = self.customer_list.item(i)
            if item.data(Qt.UserRole) == customer_id:
                self.customer_list.setCurrentItem(item)
                self.on_customer_selected(item)
                QApplication.processEvents()
                break

        # Seleziona la destinazione
        for i in range(self.destination_list.count()):
            item = self.destination_list.item(i)
            if item.data(Qt.UserRole) == destination_id:
                self.destination_list.setCurrentItem(item)
                self.on_destination_selected_new(item)
                QApplication.processEvents()
                break

    def select_device_from_search(self, device_data: dict):
        """Seleziona un dispositivo dalla ricerca globale usando il nuovo sistema a 3 colonne."""
        destination_id = device_data.get('destination_id')
        device_id = device_data.get('id')

        if not destination_id or not device_id:
            QMessageBox.warning(self, "Dati Incompleti", "Impossibile selezionare il dispositivo, dati mancanti.")
            return

        dest_info = services.database.get_destination_by_id(destination_id)
        if not dest_info:
            QMessageBox.warning(self, "Errore", "Destinazione non trovata.")
            return

        customer_id = dict(dest_info).get('customer_id')

        # Seleziona il cliente
        for i in range(self.customer_list.count()):
            item = self.customer_list.item(i)
            if item.data(Qt.UserRole) == customer_id:
                self.customer_list.setCurrentItem(item)
                self.on_customer_selected(item)
                QApplication.processEvents()
                break

        # Seleziona la destinazione
        for i in range(self.destination_list.count()):
            item = self.destination_list.item(i)
            if item.data(Qt.UserRole) == destination_id:
                self.destination_list.setCurrentItem(item)
                self.on_destination_selected_new(item)
                QApplication.processEvents()
                break

        # Seleziona il dispositivo
        device_found = False
        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            if item.data(Qt.UserRole) == device_id:
                self.device_list.setCurrentItem(item)
                self.on_device_selected_new(item)
                device_found = True
                break

        if not device_found and self._get_device_filter_mode() != "ALL":
            logging.info("Dispositivo non trovato con filtro attivo, passaggio a 'Tutti' e nuovo tentativo...")
            self._set_device_filter_mode("ALL")
            QApplication.processEvents()

            for i in range(self.device_list.count()):
                item = self.device_list.item(i)
                if item.data(Qt.UserRole) == device_id:
                    self.device_list.setCurrentItem(item)
                    self.on_device_selected_new(item)
                    break

    def setup_verification_session(self):
        dialog = InstrumentSelectionDialog(self, instrument_type='electrical')
        dialog.setWindowTitle("Seleziona Strumento per Verifiche Elettriche")
        if dialog.exec() == QDialog.Accepted:
            self.current_mti_info = dialog.getSelectedInstrumentData()
            user_info = auth_manager.get_current_user_info()
            self.current_technician_name = user_info.get('full_name')

            if self.current_mti_info:
                self.current_instrument_label.setText(
                    f"{self.current_mti_info.get('instrument')} (S/N: {self.current_mti_info.get('serial')})"
                )
                self.current_instrument_label.setStyleSheet("color: #16a34a; font-weight: 600; background-color: transparent;")
                self.current_technician_label.setText(self.current_technician_name or "N/D")
                self.current_technician_label.setStyleSheet("color: #2563eb; font-weight: 600; background-color: transparent;")
                logging.info(f"Sessione impostata per tecnico '{self.current_technician_name}'.")
                self.statusBar().showMessage("Sessione impostata. Pronto per avviare le verifiche.", 5000)
            else:
                QMessageBox.warning(self, "Dati Mancanti", "Selezionare uno strumento valido.")
    
    def open_correction_dialog(self):
        """Opens the correction dialog."""
        try:
            current_role = auth_manager.get_current_role()
            if current_role not in ['admin', 'power_user']:
                QMessageBox.warning(
                    self,
                    "Accesso Negato",
                    "Non hai i permessi necessari per accedere a questa funzione."
                )
                return
                
            dialog = CorrectionDialog(parent=self)
            dialog.exec()
            
        except Exception as e:
            logging.error(f"Errore apertura dialog correzione: {e}")
            QMessageBox.critical(
                self,
                "Errore",
                f"Impossibile aprire il dialog di correzione:\n{str(e)}"
            )

    def update_dashboard(self):
        """Aggiorna le statistiche nella dashboard con cards moderne."""
        try:
            # Ottieni le statistiche
            stats = services.get_verification_stats()
            
            # Verifica che stats sia un dizionario
            if not isinstance(stats, dict):
                logging.error(f"Invalid stats type: {type(stats)}")
                stats = {'totale': 0, 'conformi': 0, 'non_conformi': 0}
            
            logging.debug(f"Updating dashboard with stats: {stats}")
            
            totale = stats.get('totale', 0)
            conformi = stats.get('conformi', 0)
            non_conformi = stats.get('non_conformi', 0)
            
            # Calcola percentuali
            perc_conformi = (conformi / totale * 100) if totale > 0 else 0
            perc_non_conformi = (non_conformi / totale * 100) if totale > 0 else 0
            
            # Stile moderno per le cards - con colore testo esplicito e grassetto
            card_style_total = """
                QLabel {
                    background-color: #dbeafe;
                    border-left: 5px solid #2563eb;
                    border-radius: 8px;
                    padding: 12px;
                    color: #1e40af;
                    font-weight: bold;
                    font-size: 14px;
                }
            """
            
            card_style_conformi = """
                QLabel {
                    background-color: #dcfce7;
                    border-left: 5px solid #16a34a;
                    border-radius: 8px;
                    padding: 12px;
                    color: #15803d;
                    font-weight: bold;
                    font-size: 14px;
                }
            """
            
            card_style_non_conformi = """
                QLabel {
                    background-color: #fee2e2;
                    border-left: 5px solid #dc2626;
                    border-radius: 8px;
                    padding: 12px;
                    color: #b91c1c;
                    font-weight: bold;
                    font-size: 14px;
                }
            """
            
            # Card Totale - testo semplice senza HTML complesso
            self.total_card.setText(f"TOTALE VERIFICHE\n{totale:,}")
            self.total_card.setStyleSheet(card_style_total)
            self.total_card.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            
            # Card Conformi
            self.conformi_card.setText(f"CONFORMI\n{conformi:,} ({perc_conformi:.1f}%)")
            self.conformi_card.setStyleSheet(card_style_conformi)
            self.conformi_card.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            
            # Card Non Conformi
            self.non_conformi_card.setText(f"NON CONFORMI\n{non_conformi:,} ({perc_non_conformi:.1f}%)")
            self.non_conformi_card.setStyleSheet(card_style_non_conformi)
            self.non_conformi_card.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            
        except Exception as e:
            logging.error(f"Dashboard update error: {e}", exc_info=True)
            self.statusBar().showMessage("Errore aggiornamento statistiche", 5000)