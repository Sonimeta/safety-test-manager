import shutil
import re
import qtawesome as qta
from datetime import date, timedelta, datetime
from app.utils.iconify_helper import get_icon, get_pixmap
import logging
import json
import sys
import os   
import socket
import platform
import ctypes
from urllib.parse import urlparse
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QComboBox, QGroupBox, QMessageBox, QFileDialog,
    QStatusBar, QGridLayout, QListWidget, QListWidgetItem, QLineEdit, QDialog, QMenu, QInputDialog,
    QScrollArea, QFrame, QProgressDialog, QDialogButtonBox,
    QStackedWidget, QStackedLayout, QSizePolicy)
from PySide6.QtGui import QAction, QIcon, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QSettings, QThread, Signal, QTimer, QSize
from app.data_models import AppliedPart
from app.ui.dialogs.user_manager_dialog import UserManagerDialog
from app.ui.dialogs.correction_dialog import CorrectionDialog
from app.ui.dialogs.stats_dashboard_dialog import StatsDashboardDialog
from app.ui.dialogs.advanced_search_dialog import AdvancedSearchDialog

# La main_window importa solo i moduli necessari per la UI e i servizi
from app import auth_manager, config, services
from app.config import SYNC_INTERVAL_MINUTES, UPDATE_CHECK_INTERVAL_MINUTES
from app.ui.dialogs.utility_dialogs import (
    AppliedPartsOrderDialog,
    GlobalSearchDialog,
    DuplicateDevicesDialog,
    DeviceDataQualityDialog,
    AdvancedReportDialog,
)
from app.ui.state_manager import AppState, StateManager
from app.updater import UpdateChecker, UpdateCheckWorker
from app.ui.dialogs.update_dialog import UpdateDialog
from app.ui.dialogs.changelog_dialog import ChangelogDialog
from app.ui.dialogs.utility_dialogs import ExportCustomerSelectionDialog, SingleCalendarRangeDialog
from app.ui.overlay_widget import OverlayWidget
from app.ui.widgets import FunctionalTestRunnerWidget, TestRunnerWidget
from app.backup_manager import restore_from_backup, _rotate_old_backups
from app.ui.dialogs import (DbManagerDialog, VisualInspectionDialog, DeviceDialog, 
                            InstrumentManagerDialog, InstrumentSelectionDialog)
from app.ui.dialogs.expiring_devices_dialog import ExpiringDevicesDialog
from app.workers.sync_worker import SyncWorker
from app.workers.bulk_report_worker import BulkReportWorker
from app.ui.dialogs.signature_manager_dialog import SignatureManagerDialog
from app.hardware.fluke_esa612 import FlukeESA612
from app.ui.dialogs.profile_manager_dialog import ProfileManagerDialog
from app.ui.dialogs.functional_profile_manager_dialog import FunctionalProfileManagerDialog
from app.ui.dialogs.qr_device_scanner_dialog import QRDeviceScannerDialog
from app.ui.dialogs.system_verification_dialogs import SystemDeviceSelectionDialog
from app.ui.dialogs.assignments_dialog import BulkAssignDialog, AssignmentsManagerDialog
from app.config import LOG_DIR
import database
from app.workers.table_export_worker import InventoryExportWorker


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
        self._restoring_persisted_state = False
        
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
        self.inline_feedback_timer = QTimer(self)
        self.inline_feedback_timer.setSingleShot(True)
        self.inline_feedback_timer.timeout.connect(self.clear_inline_feedback)
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

        # Indicatore aggiornamento disponibile (permanente nella status bar)
        self._update_check_worker = None
        self._pending_update_info = None
        self._update_notification_btn = QPushButton("")
        self._update_notification_btn.setObjectName("updateNotificationBtn")
        self._update_notification_btn.setStyleSheet(
            "QPushButton#updateNotificationBtn {"
            "  background-color: #2563eb; color: white; font-weight: bold;"
            "  border: none; border-radius: 4px; padding: 4px 14px;"
            "  font-size: 12px;"
            "}"
            "QPushButton#updateNotificationBtn:hover {"
            "  background-color: #1d4ed8;"
            "}"
        )
        self._update_notification_btn.setCursor(Qt.PointingHandCursor)
        self._update_notification_btn.clicked.connect(self._on_update_notification_clicked)
        self.statusBar().addPermanentWidget(self._update_notification_btn)
        self._update_notification_btn.hide()
        
        # Indicatore conflitti nella status bar
        self._setup_conflict_indicator()

        # Indicatore/toggle server QR nella status bar (visibile da qualsiasi schermata)
        self._setup_qr_server_statusbar()

        main_widget = QWidget()
        self.main_layout = QHBoxLayout(main_widget)
        self.main_layout.setContentsMargins(18, 18, 18, 18)
        self.main_layout.setSpacing(18)

        # QStackedWidget per navigazione a finestra singola
        self._stacked_widget = QStackedWidget()
        self._stacked_widget.addWidget(main_widget)  # Pagina 0 = vista principale

        # Barra navigazione embedded - design professionale
        self._back_bar = QWidget()
        self._back_bar.setFixedHeight(52)
        self._back_bar.setStyleSheet(
            "QWidget#backBar {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "    stop:0 #0f172a, stop:0.4 #1e293b, stop:1 #0f172a);"
            "  border-bottom: 2px solid #3b82f6;"
            "}"
        )
        self._back_bar.setObjectName("backBar")
        self._back_bar.setVisible(False)
        back_bar_layout = QHBoxLayout(self._back_bar)
        back_bar_layout.setContentsMargins(12, 0, 20, 0)
        back_bar_layout.setSpacing(0)
        self._back_btn = None  # creato in _show_embedded_dialog

        # Label breadcrumb sinistra ("⌂  Home  ›")
        utente = auth_manager.get_current_user_info()
        self._back_bar_breadcrumb = QLabel("")
        self._back_bar_breadcrumb.setStyleSheet(
            "color:#64748b; font-size:11px; font-weight:500; letter-spacing:.5px;"
        )
        back_bar_layout.addWidget(self._back_bar_breadcrumb)

        back_bar_layout.addStretch(1)

        # Titolo sezione centrato
        self._back_bar_label = QLabel("")
        self._back_bar_label.setStyleSheet(
            "color:#f1f5f9; font-size:13px; font-weight:700; letter-spacing:1.5px;"
        )
        self._back_bar_label.setAlignment(Qt.AlignCenter)
        back_bar_layout.addWidget(self._back_bar_label)

        back_bar_layout.addStretch(1)

        # Label app name destra
        ruolo = auth_manager.get_current_role()
        _app_label = QLabel(f"Safety Test Manager - {ruolo}")
        _app_label.setStyleSheet(
            "color:#f1f5f9; font-size:10px; font-weight:700; letter-spacing:.5px;"
        )
        back_bar_layout.addWidget(_app_label)

        # Container principale: back_bar + stacked
        _central_container = QWidget()
        _central_vbox = QVBoxLayout(_central_container)
        _central_vbox.setContentsMargins(0, 0, 0, 0)
        _central_vbox.setSpacing(0)
        _central_vbox.addWidget(self._back_bar)
        _central_vbox.addWidget(self._stacked_widget)
        self.setCentralWidget(_central_container)

        self._embedded_dialog = None
        self._embedded_on_close = None

        self.create_left_panel()
        self.create_right_panel()
        self._restore_window_layout_settings()
        self._setup_keyboard_shortcuts()
        self._setup_accessibility()

        self.apply_permissions()
        self.load_all_data()
        QTimer.singleShot(0, self._restore_main_view_state)
        
        # Controlla e mostra il changelog se necessario
        QTimer.singleShot(1000, self._check_and_show_changelog)
        QTimer.singleShot(4500, self._check_expiring_devices_on_startup)
        
        # Avvia una sincronizzazione automatica all'avvio se è disponibile la rete
        QTimer.singleShot(3000, self._auto_sync_on_startup)
        
        # --- INIZIO AGGIUNTA: Timer per sincronizzazione periodica in background ---
        self._setup_periodic_sync_timer()

        # --- Timer per controllo aggiornamenti automatico in background ---
        self._setup_auto_update_check_timer()

        # --- Pulizia backup vecchi all'avvio ---
        QTimer.singleShot(5000, self._cleanup_old_backups)
    
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

        self.export_inventory_action = QAction(get_icon("export", theme=self.current_theme), "Esporta Inventario Cliente...", self)
        self.export_inventory_action.triggered.connect(self.export_customer_inventory)
        file_menu.addAction(self.export_inventory_action)

        self.export_log_action = QAction(get_icon("report", theme=self.current_theme), "Esporta File Log...", self)
        self.export_log_action.triggered.connect(self.export_log_file)
        file_menu.addAction(self.export_log_action)

        file_menu.addSeparator()

        self.logout_action = QAction(get_icon("logout", theme=self.current_theme), "Esci", self)
        self.logout_action.triggered.connect(self.logout)
        file_menu.addAction(self.logout_action)

        # ===================== MENU LAVORI =====================
        jobs_menu = menubar.addMenu("&Lavori")

        self.advanced_search_action = QAction(get_icon("search", theme=self.current_theme), "Ricerca Avanzata...", self)
        self.advanced_search_action.triggered.connect(self.open_advanced_search)
        jobs_menu.addAction(self.advanced_search_action)

        jobs_menu.addSeparator()

        self.new_assignment_action = QAction(get_icon("audit", theme=self.current_theme), "Nuova Assegnazione...", self)
        self.new_assignment_action.triggered.connect(self._open_bulk_assign_dialog)
        jobs_menu.addAction(self.new_assignment_action)

        self.assignments_action = QAction(get_icon("clipboard", theme=self.current_theme), "Gestione Lavori Assegnati...", self)
        self.assignments_action.triggered.connect(self.open_assignments_manager)
        jobs_menu.addAction(self.assignments_action)

        # ===================== MENU REPORT / ANALISI =====================
        report_menu = menubar.addMenu("&Report / Analisi")

        self.advanced_report_action = QAction(get_icon("report", theme=self.current_theme), "Genera Report...", self)
        self.advanced_report_action.triggered.connect(self.open_advanced_report_dialog)
        report_menu.addAction(self.advanced_report_action)

        self.stats_action = QAction(get_icon("chart", theme=self.current_theme), "Dashboard Statistiche...", self)
        self.stats_action.triggered.connect(self.open_stats_dashboard)
        report_menu.addAction(self.stats_action)

        self.audit_log_action = QAction(get_icon("audit", theme=self.current_theme), "Log Attività (Chi ha fatto cosa)...", self)
        self.audit_log_action.triggered.connect(self.open_audit_log)
        report_menu.addAction(self.audit_log_action)

        report_menu.addSeparator()

        self.correction_action = QAction(get_icon("magic", theme=self.current_theme), "Correggi Descrizioni Dispositivi...", self)
        self.correction_action.triggered.connect(self.open_correction_dialog)
        report_menu.addAction(self.correction_action)

        self.duplicates_action = QAction(get_icon("duplicate", theme=self.current_theme), "Trova Dispositivi Duplicati...", self)
        self.duplicates_action.triggered.connect(self.open_duplicate_devices_dialog)
        report_menu.addAction(self.duplicates_action)

        self.data_quality_action = QAction(get_icon("quality", theme=self.current_theme), "Controllo Qualità Dati Dispositivi...", self)
        self.data_quality_action.triggered.connect(self.open_device_data_quality_dialog)
        report_menu.addAction(self.data_quality_action)

        # ===================== MENU SINCRONIZZAZIONE =====================
        sync_menu = menubar.addMenu("&Sincronizzazione")

        self.full_sync_action = QAction(get_icon("sync", theme=self.current_theme), "Sincronizza Tutto (Reset Locale)...", self)
        self.full_sync_action.triggered.connect(lambda: self.run_synchronization(full_sync=True))
        sync_menu.addAction(self.full_sync_action)

        self.force_push_action = QAction(get_icon("import", theme=self.current_theme), "Forza Upload (tutti i dati)...", self)
        self.force_push_action.triggered.connect(self.confirm_and_force_push)
        sync_menu.addAction(self.force_push_action)

        self.view_conflicts_action = QAction(get_icon("conflict", theme=self.current_theme), "Gestisci Conflitti...", self)
        self.view_conflicts_action.triggered.connect(self._open_conflict_resolution_panel)
        sync_menu.addAction(self.view_conflicts_action)

        sync_menu.addSeparator()

        self.disable_auto_sync_action = QAction(get_icon("pending", theme=self.current_theme), "Disattiva Sincronizzazione Automatica", self)
        self.disable_auto_sync_action.setCheckable(True)
        self.disable_auto_sync_action.setChecked(False)
        self.disable_auto_sync_action.toggled.connect(self._toggle_auto_sync)
        sync_menu.addAction(self.disable_auto_sync_action)

        sync_menu.addSeparator()

        self.ripristina_db_action = QAction(get_icon("restore", theme=self.current_theme), "Ripristina Database...", self)
        self.ripristina_db_action.triggered.connect(self.restore_database)
        sync_menu.addAction(self.ripristina_db_action)

        # ===================== MENU IMPOSTAZIONI =====================
        settings_menu = menubar.addMenu("&Impostazioni")

        # — Hardware —
        self.set_com_port_action = QAction(get_icon("com_port", theme=self.current_theme), "Imposta Porta COM...", self)
        self.set_com_port_action.triggered.connect(self.configure_com_port)
        settings_menu.addAction(self.set_com_port_action)

        self.manage_instruments_action = QAction(get_icon("instrument", theme=self.current_theme), "Gestisci Strumenti di Misura...", self)
        self.manage_instruments_action.triggered.connect(self.open_instrument_manager)
        settings_menu.addAction(self.manage_instruments_action)

        settings_menu.addSeparator()

        # — Branding e profili —
        self.set_logo_action = QAction(get_icon("logo", theme=self.current_theme), "Imposta Logo Azienda...", self)
        self.set_logo_action.triggered.connect(self.set_company_logo)
        settings_menu.addAction(self.set_logo_action)

        self.manage_signature_action = QAction(get_icon("edit", theme=self.current_theme), "Gestisci Firma...", self)
        self.manage_signature_action.triggered.connect(self.open_signature_manager)
        settings_menu.addAction(self.manage_signature_action)

        self.manage_profiles_action = QAction(get_icon("report", theme=self.current_theme), "Gestisci Profili Elettrici...", self)
        self.manage_profiles_action.triggered.connect(self.open_profile_manager)
        settings_menu.addAction(self.manage_profiles_action)

        self.manage_functional_profiles_action = QAction(get_icon("functional_verify", theme=self.current_theme), "Gestisci Profili Funzionali...", self)
        self.manage_functional_profiles_action.triggered.connect(self.open_functional_profile_manager)
        settings_menu.addAction(self.manage_functional_profiles_action)

        settings_menu.addSeparator()

        # — Utenti e accesso —
        self.manage_users_action = QAction(get_icon("users", theme=self.current_theme), "Gestisci Utenti...", self)
        self.manage_users_action.triggered.connect(self.open_user_manager)
        settings_menu.addAction(self.manage_users_action)

        self.change_password_action = QAction(get_icon("password", theme=self.current_theme), "Cambia Password...", self)
        self.change_password_action.triggered.connect(self.open_change_password_dialog)
        settings_menu.addAction(self.change_password_action)

        settings_menu.addSeparator()

        # — Dati e manutenzione —
        self.deleted_data_action = QAction(get_icon("trash", theme=self.current_theme), "Gestione Dati Eliminati...", self)
        self.deleted_data_action.triggered.connect(self.open_deleted_data_manager)
        settings_menu.addAction(self.deleted_data_action)

        self.attachments_storage_action = QAction(get_icon("report", theme=self.current_theme), "Gestione Spazio Allegati...", self)
        self.attachments_storage_action.triggered.connect(self.open_attachments_storage_dialog)
        settings_menu.addAction(self.attachments_storage_action)

        settings_menu.addSeparator()

        # — Interfaccia —
        self.theme_action = QAction(get_icon("theme", theme=self.current_theme), "Cambia Tema", self)
        self.theme_action.triggered.connect(self.toggle_theme)
        settings_menu.addAction(self.theme_action)
        self.update_theme_action_text()

        # ===================== MENU AIUTO =====================
        help_menu = menubar.addMenu("&Aiuto")

        self.changelog_action = QAction(get_icon("changelog", theme=self.current_theme), "Visualizza Changelog...", self)
        self.changelog_action.triggered.connect(self.show_changelog)
        help_menu.addAction(self.changelog_action)

        self.shortcuts_help_action = QAction(get_icon("shortcuts", theme=self.current_theme), "Scorciatoie da Tastiera...", self)
        self.shortcuts_help_action.triggered.connect(self._show_shortcuts_dialog)
        help_menu.addAction(self.shortcuts_help_action)

        help_menu.addSeparator()

        self.update_action = QAction(get_icon("update", theme=self.current_theme), "Controlla Aggiornamenti...", self)
        self.update_action.triggered.connect(self.check_for_updates)
        help_menu.addAction(self.update_action)

        help_menu.addSeparator()

        self.about_action = QAction(get_icon("about", theme=self.current_theme), "Informazioni su Safety Test Manager...", self)
        self.about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(self.about_action)

    def open_assignments_manager(self):
        """Apre la finestra di gestione dei lavori assegnati."""
        dialog = AssignmentsManagerDialog(self)
        dialog.exec()
        # Navigazione automatica se il tecnico ha avviato un'attività
        if dialog.started_assignment:
            QTimer.singleShot(200, lambda: self._navigate_to_assignment(dialog.started_assignment))

    def _navigate_to_assignment(self, assignment: dict):
        """Naviga alla sede/dispositivo dell'assegnazione avviata."""
        from app import services
        device_id = assignment.get("device_id")
        dest_id   = assignment.get("destination_id")

        dev_name  = assignment.get("description") or assignment.get("model") or ""
        dest_name = assignment.get("destination_name") or ""

        if device_id:
            # Navigazione verso il dispositivo specifico
            device_data = services.database.get_device_by_id(device_id)
            if device_data:
                dev = dict(device_data)
                ok = self.select_device_from_search(dev, notify=False)
                if ok:
                    self.show_inline_feedback(
                        f"▶  Attività avviata: {dev_name or dev.get('description', 'Dispositivo')}"
                        f"  —  puoi ora avviare le verifiche.",
                        level="success")
                    return
        elif dest_id:
            # Navigazione verso la sede intera
            dest_data = services.database.get_destination_by_id(dest_id)
            if dest_data:
                d = dict(dest_data)
                ok = self.select_destination_from_search(d, notify=False)
                if ok:
                    self.show_inline_feedback(
                        f"▶  Attività avviata: Sede {dest_name or d.get('name', '')}"
                        f"  —  seleziona il dispositivo e avvia le verifiche.",
                        level="success")
                    return

        self.show_inline_feedback(
            "Attività avviata. Naviga manualmente al dispositivo/sede.",
            level="info")

    def _show_device_context_menu(self, pos):
        """Menu contestuale sulla lista dispositivi con 'Assegna Verifica'."""
        item = self.device_list.itemAt(pos)
        if not item:
            return
        device_id = item.data(Qt.UserRole)
        if not device_id:
            return
        menu = QMenu(self)
        assign_action = menu.addAction("📋  Assegna Verifica...")
        role = auth_manager.get_current_role()
        assign_action.setEnabled(role in ("admin", "moderator"))
        action = menu.exec(self.device_list.viewport().mapToGlobal(pos))
        if action == assign_action:
            self._assign_verification_from_device(device_id)

    def _open_bulk_assign_dialog(self):
        """Apre il dialog di assegnazione multipla con contesto corrente."""
        from app import auth_manager as _am
        if _am.get_current_role() not in ('admin', 'moderator'):
            return
        dialog = BulkAssignDialog(
            parent=self,
            preselect_device_id=getattr(self, 'selected_device_id', None),
            preselect_destination_id=getattr(self, 'selected_destination_id', None),
            preselect_customer_id=getattr(self, 'selected_customer_id', None),
        )
        dialog.exec()

    def _assign_verification_from_device(self, device_id: int):
        """Apre il dialog di assegnazione per il dispositivo selezionato."""
        dialog = BulkAssignDialog(parent=self, preselect_device_id=device_id)
        dialog.exec()

    def mark_device_unavailable(self, device_id: int):
        """Apre un dialog per segnare il dispositivo come 'non messo a disposizione'."""
        from app.ui.dialogs.utility_dialogs import UnavailabilityReportDialog
        device = services.get_device_by_id(device_id)
        if not device:
            QMessageBox.warning(self, "ERRORE", "Dispositivo non trovato.")
            return
        device = dict(device)
        dest_id = device.get('destination_id') or self.selected_destination_id
        start_str, end_str = self._get_device_filter_period()
        dialog = UnavailabilityReportDialog(
            device=device,
            destination_id=dest_id,
            default_start=start_str,
            default_end=end_str,
            parent=self,
        )
        if dialog.exec():
            period_start, period_end, reason = dialog.get_data()
            try:
                from app import auth_manager as _am
                user = _am.get_current_user_info()
                services.save_unavailability_report(
                    device_id=device_id,
                    destination_id=dest_id,
                    period_start=period_start,
                    period_end=period_end,
                    reason=reason,
                    technician_name=user.get('full_name') if user else None,
                    technician_username=user.get('username') if user else None,
                )
                self.show_inline_feedback(
                    f"{str(device.get('description') or '').upper()} segnato come non messo a disposizione.",
                    level='warning'
                )
            except Exception as e:
                QMessageBox.critical(self, "ERRORE", f"Impossibile salvare la segnalazione:\n{e}")

    def open_duplicate_devices_dialog(self):
        """Apre la finestra per la gestione dei dispositivi duplicati."""
        dialog = DuplicateDevicesDialog(self)
        self._show_embedded_dialog(dialog, "DISPOSITIVI DUPLICATI")

    def open_device_data_quality_dialog(self):
        """Apre la finestra per il controllo qualità dei dati dispositivi."""
        dialog = DeviceDataQualityDialog(self)
        self._show_embedded_dialog(dialog, "CONTROLLO QUALITÀ DATI")
    
    def open_stats_dashboard(self):
        """Apre la finestra di dialogo con le statistiche."""
        dialog = StatsDashboardDialog(self)
        self._show_embedded_dialog(dialog, "DASHBOARD STATISTICHE")
    
    def open_audit_log(self):
        """Apre la finestra di dialogo con il log delle attività."""
        from app.ui.dialogs.audit_log_dialog import AuditLogDialog
        dialog = AuditLogDialog(self)
        self._show_embedded_dialog(dialog, "LOG ATTIVITÀ")

    def open_deleted_data_manager(self):
        """Apre la finestra di gestione dati eliminati (solo admin)."""
        from app.ui.dialogs.deleted_data_dialog import DeletedDataDialog
        dialog = DeletedDataDialog(self)
        self._show_embedded_dialog(dialog, "GESTIONE DATI ELIMINATI")

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

    def _show_shortcuts_dialog(self):
        """Mostra l'elenco delle scorciatoie principali disponibili nell'app."""
        shortcuts_html = (
            "<h3>Schermata Principale</h3>"
            "<ul>"
            "<li><b>Ctrl+F</b> - Focus su Ricerca rapida</li>"
            "<li><b>Ctrl+Shift+F</b> - Apre la ricerca avanzata</li>"
            "<li><b>Ctrl+N</b> - Aggiunge un nuovo dispositivo</li>"
            "<li><b>Ctrl+S</b> - Avvia la sincronizzazione</li>"
            "<li><b>F6</b> - Imposta o modifica la sessione di verifica</li>"
            "<li><b>Alt+1</b> - Vai a Clienti e cerca</li>"
            "<li><b>Alt+2</b> - Vai a Destinazioni e cerca</li>"
            "<li><b>Alt+3</b> - Vai a Dispositivi e cerca</li>"
            "</ul>"
            "<h3>Verifica Funzionale</h3>"
            "<ul>"
            "<li><b>Ctrl+S</b> - Salva la verifica</li>"
            "<li><b>Alt+Right</b> - Sezione successiva</li>"
            "<li><b>Alt+Left</b> - Sezione precedente</li>"
            "<li><b>Ctrl+Tab</b> - Sezione successiva</li>"
            "<li><b>Ctrl+Shift+Tab</b> - Sezione precedente</li>"
            "<li><b>Ctrl+J</b> - Vai al primo incompleto</li>"
            "<li><b>Alt+1 ... Alt+9</b> - Salto diretto alle sezioni</li>"
            "</ul>"
        )
        QMessageBox.information(
            self,
            "Scorciatoie da Tastiera",
            shortcuts_html,
        )

    def _show_about_dialog(self):
        """Mostra la finestra Informazioni con versione, autore e licenze terze parti."""
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

    def _check_expiring_devices_on_startup(self):
        """Mostra l'avviso strumenti in scadenza una sola volta per avvio programma."""
        app = QApplication.instance()
        if app and app.property("_stm_expiring_devices_checked_on_startup"):
            return

        if self.state_manager.is_syncing() or QApplication.activeModalWidget() is not None:
            QTimer.singleShot(1000, self._check_expiring_devices_on_startup)
            return

        if app:
            app.setProperty("_stm_expiring_devices_checked_on_startup", True)
        self._check_expiring_devices()

    # === CONTROLLO AGGIORNAMENTI AUTOMATICO IN BACKGROUND ===

    def _cleanup_old_backups(self):
        """Esegue la pulizia dei backup vecchi all'avvio dell'applicazione."""
        try:
            _rotate_old_backups()
            logging.info("✓ Pulizia backup completata all'avvio.")
        except Exception as e:
            logging.warning(f"Errore durante la pulizia dei backup all'avvio: {e}")

    def open_attachments_storage_dialog(self):
        """Mostra dialogo per la gestione dello spazio allegati locali."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QDialogButtonBox
        usage = services.get_attachments_disk_usage()

        def _fmt(b):
            if b < 1024: return f"{b} B"
            if b < 1024**2: return f"{b//1024} KB"
            return f"{b/(1024**2):.1f} MB"

        dlg = QDialog(self)
        dlg.setWindowTitle("Gestione Spazio Allegati")
        dlg.setMinimumWidth(440)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)

        layout.addWidget(QLabel(
            f"<b>Spazio totale allegati locali:</b> {_fmt(usage['total_bytes'])} "
            f"({usage['total_files']} file)"
        ))
        layout.addWidget(QLabel(
            f"<b>Di cui già sincronizzati con il server:</b> "
            f"{_fmt(usage['synced_bytes'])} ({usage['synced_files']} file)"
        ))
        note = QLabel(
            "<small>I file già sincronizzati possono essere rimossi dal disco locale. "
            "I metadati rimangono nel database e i file restano accessibili sul server.</small>"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        def do_purge():
            if usage['synced_files'] == 0:
                QMessageBox.information(dlg, "Nessun file da rimuovere",
                    "Non ci sono allegati sincronizzati da rimuovere.")
                return
            reply = QMessageBox.question(
                dlg, "Conferma pulizia",
                f"Verranno rimossi {usage['synced_files']} file locali "
                f"({_fmt(usage['synced_bytes'])}) già presenti sul server.\n"
                "Continuare?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            result = services.purge_synced_attachments()
            msg = (f"Liberati {_fmt(result['freed_bytes'])} "
                   f"({result['deleted_files']} file rimossi).")
            if result['errors']:
                msg += f"\n{result['errors']} file non rimovibili (vedi log)."
            QMessageBox.information(dlg, "Pulizia completata", msg)
            dlg.accept()

        btn_purge = QPushButton(
            f"🗑  Rimuovi file già sincronizzati  "
            f"({usage['synced_files']} file — {_fmt(usage['synced_bytes'])})"
        )
        btn_purge.clicked.connect(do_purge)
        btn_purge.setEnabled(usage['synced_files'] > 0)
        layout.addWidget(btn_purge)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec()

    # === NAVIGAZIONE EMBEDDED (finestra singola) ===

    def _show_embedded_dialog(self, dialog, title, on_close=None):
        """
        Mostra un QDialog embedded nella finestra principale invece di aprirlo
        come finestra separata. Sostituisce dialog.exec().
        """
        # Se c'è già una vista embedded aperta, chiudila prima (senza callback)
        if self._stacked_widget.count() > 1:
            old = self._stacked_widget.widget(1)
            self._stacked_widget.setCurrentIndex(0)
            self._stacked_widget.removeWidget(old)
            old.deleteLater()
            self._embedded_dialog = None
            self._embedded_on_close = None

        self._embedded_dialog = dialog
        self._embedded_on_close = on_close

        # Converti il QDialog in widget embedded (rimuove i flag di finestra)
        dialog.setWindowFlags(Qt.Widget)
        dialog.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        def _embedded_done(result):
            dialog.setResult(result)
            self._close_embedded_view()

        dialog.done = _embedded_done


        # Pulsante "indietro" nel back_bar fisso (mai nella status bar)
        # Rimuovi eventuale pulsante precedente
        if hasattr(self, '_back_btn') and self._back_btn:
            self._back_btn.deleteLater()
            self._back_btn = None

        self._back_btn = QPushButton(qta.icon('fa5s.arrow-left', color='#93c5fd', scale_factor=0.75), "  Indietro")
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.setFixedHeight(32)
        self._back_btn.setFixedWidth(110)
        self._back_btn.setToolTip("Torna alla Home (Esc)")
        self._back_btn.setStyleSheet(
            "QPushButton {"
            "  background: rgba(59,130,246,0.15);"
            "  border: 1px solid rgba(59,130,246,0.4);"
            "  border-radius: 7px;"
            "  padding: 0 12px;"
            "  color: #93c5fd;"
            "  font-weight: 700;"
            "  font-size: 12px;"
            "  letter-spacing: .3px;"
            "}"
            "QPushButton:hover {"
            "  background: rgba(59,130,246,0.30);"
            "  border-color: #3b82f6;"
            "  color: #bfdbfe;"
            "}"
            "QPushButton:pressed { background: rgba(59,130,246,0.45); }"
        )
        self._back_btn.clicked.connect(lambda: dialog.done(QDialog.Rejected))
        # Inserisci il pulsante all'inizio del layout del back_bar
        self._back_bar.layout().insertWidget(0, self._back_btn)
        self._back_bar_label.setText(f"  {title}  ")
        self._back_bar.setVisible(True)

        # Aggiorna titolo finestra per mostrare la sezione corrente
        self._original_window_title = self.windowTitle()
        self.setWindowTitle(f"{title}  —  {self._original_window_title}")

        # Converti in widget e aggiungi allo stacked widget
        self._stacked_widget.addWidget(dialog)
        self._stacked_widget.setCurrentWidget(dialog)
        dialog.show()

        # Nascondi il menu (visibile solo nella home)
        self.menuBar().setVisible(False)

    def _close_embedded_view(self):
        """Torna alla vista principale e pulisce la vista embedded."""
        if self._stacked_widget.count() <= 1:
            return

        current = self._stacked_widget.currentWidget()
        self._stacked_widget.setCurrentIndex(0)

        # Ripristina il menu
        self.menuBar().setVisible(True)

        # Ripristina titolo e nascondi back_bar
        if hasattr(self, '_original_window_title') and self._original_window_title:
            self.setWindowTitle(self._original_window_title)
            self._original_window_title = None
        if hasattr(self, '_back_btn') and self._back_btn:
            self._back_btn.deleteLater()
            self._back_btn = None
        if hasattr(self, '_back_bar'):
            self._back_bar.setVisible(False)
            self._back_bar_label.setText("")
            if hasattr(self, '_back_bar_breadcrumb'):
                self._back_bar_breadcrumb.setText("")
        # Salva riferimenti prima della pulizia
        on_close = self._embedded_on_close
        self._embedded_on_close = None
        self._embedded_dialog = None

        # Esegui callback PRIMA di distruggere il widget (i dati del dialog sono ancora accessibili)
        if on_close:
            try:
                on_close()
            except Exception as e:
                logging.error(f"Errore nel callback post-chiusura vista embedded: {e}")

        # Rimuovi e distruggi il container
        if current and current != self._stacked_widget.widget(0):
            self._stacked_widget.removeWidget(current)
            current.deleteLater()

    def _setup_auto_update_check_timer(self):
        """
        Configura il timer per il controllo periodico degli aggiornamenti.
        Primo check dopo 15 secondi dall'avvio, poi ogni N minuti da config.
        """
        self._update_check_timer = QTimer(self)
        self._update_check_timer.timeout.connect(self._run_background_update_check)

        if not config.UPDATE_URL:
            self.show_info_feedback("Controllo aggiornamenti non configurato.")
            return

        if UPDATE_CHECK_INTERVAL_MINUTES <= 0:
            logging.info("Controllo aggiornamenti automatico disabilitato (check_interval_minutes = 0).")
            return

        # Primo check dopo 15 secondi dall'avvio
        QTimer.singleShot(15000, self._run_background_update_check)

        # Poi periodicamente
        interval_ms = UPDATE_CHECK_INTERVAL_MINUTES * 60 * 1000
        self._update_check_timer.start(interval_ms)
        logging.info(f"Timer controllo aggiornamenti avviato: ogni {UPDATE_CHECK_INTERVAL_MINUTES} minuti.")

    def _run_background_update_check(self):
        """Avvia un worker in background per controllare la presenza di aggiornamenti."""
        # Se c'è già un check in corso o un aggiornamento già notificato, non fare nulla
        if self._update_check_worker is not None and self._update_check_worker.isRunning():
            return
        if self._pending_update_info is not None:
            return
        if not config.UPDATE_URL:
            return

        logging.debug("Avvio controllo aggiornamenti in background...")
        self._update_check_worker = UpdateCheckWorker(config.UPDATE_URL, self)
        self._update_check_worker.update_available.connect(self._on_background_update_found)
        self._update_check_worker.no_update.connect(self._on_background_no_update)
        self._update_check_worker.check_error.connect(self._on_background_update_error)
        self._update_check_worker.finished.connect(self._on_update_check_worker_finished)
        self._update_check_worker.start()

    def _on_background_update_found(self, update_info: dict):
        """Chiamato dal worker quando un aggiornamento è disponibile. Mostra una notifica non invasiva."""
        latest_version = update_info.get('latest_version', '?')
        logging.info(f"Aggiornamento disponibile rilevato in background: v{latest_version}")
        self._pending_update_info = update_info
        self._update_notification_btn.setText(f"⬆ Aggiornamento v{latest_version} disponibile — Clicca per aggiornare")
        self._update_notification_btn.show()
        self.statusBar().showMessage(f"Nuova versione disponibile: {latest_version}", 10000)

    def _on_background_no_update(self):
        """Chiamato dal worker se non ci sono aggiornamenti."""
        logging.debug("Nessun aggiornamento disponibile (check automatico).")

    def _on_background_update_error(self, error_msg: str):
        """Chiamato dal worker in caso di errore — silenzioso, solo log."""
        logging.debug(f"Errore check aggiornamenti in background: {error_msg}")

    def _on_update_check_worker_finished(self):
        """Pulizia del worker dopo il completamento."""
        if self._update_check_worker is not None:
            self._update_check_worker.deleteLater()
            self._update_check_worker = None

    def _on_update_notification_clicked(self):
        """L'utente clicca sulla notifica di aggiornamento nella status bar."""
        update_info = self._pending_update_info
        if not update_info:
            return

        latest_version = update_info.get('latest_version', '?')
        changelog = update_info.get('changelog', '')

        # Componi messaggio con changelog se disponibile
        msg = (f"È disponibile la versione <b>{latest_version}</b>.<br>"
               f"Versione installata: <b>{config.VERSIONE}</b>.<br><br>")
        if changelog:
            msg += f"<b>Novità:</b><br>{changelog}<br><br>"
        msg += "Vuoi scaricarla e installarla ora?"

        reply = QMessageBox.question(
            self,
            "Aggiornamento Disponibile",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            try:
                checker = UpdateChecker(config.UPDATE_URL)
                # Riusa le info già recuperate
                checker.update_info = update_info
                self.download_and_install_update(checker, update_info)
            except Exception as e:
                QMessageBox.critical(self, "Errore Aggiornamento", str(e))
        else:
            # L'utente ha detto no — nascondi la notifica ma non re-notificare
            # finche l'utente non avvia manualmente un nuovo controllo.
            self._pending_update_info = None
            self._update_notification_btn.hide()

    def open_advanced_search(self):
        """
        Apre la finestra di dialogo per la ricerca avanzata.
        """
        QApplication.setOverrideCursor(Qt.WaitCursor)
        dialog = AdvancedSearchDialog(self)
        QApplication.restoreOverrideCursor()

        def on_close():
            if dialog.result() == QDialog.Accepted:
                selected_data = dialog.selected_verification_data
                if selected_data:
                    self.open_db_manager(navigate_to={
                        'type': 'verification',
                        'device_id': selected_data['device_id'],
                        'verification_id': selected_data['verification_id']
                    })

        self._show_embedded_dialog(dialog, "RICERCA AVANZATA", on_close)

    def open_advanced_report_dialog(self):
        dialog = AdvancedReportDialog(self)

        def on_close():
            if dialog.result() != QDialog.Accepted:
                return
            options = dialog.get_options()
            self._run_advanced_report(options)

        self._show_embedded_dialog(dialog, "GENERA REPORT AVANZATO", on_close)

    def _run_advanced_report(self, options: dict):
        start_date = options["start_date"]
        end_date = options["end_date"]
        scope = options["scope"]
        customer_id = options["customer_id"]
        destination_id = options["destination_id"]

        # destination_ids: lista di dest selezionate (solo per scope=customer); vuota = tutte
        destination_ids = options.get("destination_ids") or []

        def _dest_ids_for_customer(cid):
            """Restituisce la lista di destination_id da usare per scope=customer."""
            if destination_ids:
                return destination_ids
            dests = database.get_destinations_for_customer(cid)
            return [dict(d).get('id') for d in dests if dict(d).get('id')]

        all_verifications = []
        if options["include_electrical"]:
            if scope == "all":
                rows = database.get_verifications_by_date_range(start_date, end_date)
                electrical_verifs = [dict(r) for r in rows]
            elif scope == "customer":
                electrical_verifs = []
                for did in _dest_ids_for_customer(customer_id):
                    electrical_verifs += [dict(r) for r in database.get_verifications_for_destination_by_date_range(did, start_date, end_date)]
            else:
                electrical_verifs = [dict(r) for r in database.get_verifications_for_destination_by_date_range(destination_id, start_date, end_date)]
            if options["latest_only"]:
                electrical_verifs = self._filter_latest_verifications(electrical_verifs)
            for verif in electrical_verifs:
                verif["verification_type"] = "ELETTRICA"
                all_verifications.append(verif)

        if options["include_functional"]:
            if scope == "all":
                rows = database.get_functional_verifications_by_date_range(start_date, end_date)
                functional_verifs = [dict(r) for r in rows]
            elif scope == "customer":
                functional_verifs = []
                for did in _dest_ids_for_customer(customer_id):
                    functional_verifs += [dict(r) for r in database.get_functional_verifications_for_destination_by_date_range(did, start_date, end_date)]
            else:
                functional_verifs = [dict(r) for r in database.get_functional_verifications_for_destination_by_date_range(destination_id, start_date, end_date)]
            if options["latest_only"]:
                functional_verifs = self._filter_latest_verifications(functional_verifs)
            for verif in functional_verifs:
                verif["verification_type"] = "FUNZIONALE"
                all_verifications.append(verif)

        if options.get("include_system"):
            if scope == "all":
                rows = database.get_system_verifications_by_date_range(start_date, end_date)
                system_verifs = [dict(r) for r in rows]
            elif scope == "customer":
                system_verifs = []
                for did in _dest_ids_for_customer(customer_id):
                    system_verifs += [dict(r) for r in database.get_system_verifications_for_destination_by_date_range(did, start_date, end_date)]
            else:
                system_verifs = [dict(r) for r in database.get_system_verifications_for_destination_by_date_range(destination_id, start_date, end_date)]
            for verif in system_verifs:
                verif["verification_type"] = "SISTEMA"
                all_verifications.append(verif)

        # Aggiungi segnalazioni "non messo a disposizione" come righe sintetiche
        try:
            if scope == "all":
                unavail_rows = database.get_unavailability_reports_by_date_range(start_date, end_date)
            elif scope == "customer" and customer_id:
                unavail_rows = database.get_unavailability_reports_by_date_range(
                    start_date, end_date, customer_id=customer_id)
                if destination_ids:
                    unavail_rows = [r for r in unavail_rows if r.get('destination_id') in destination_ids]
            else:
                unavail_rows = database.get_unavailability_reports_by_date_range(
                    start_date, end_date, destination_id=destination_id)
            for r in unavail_rows:
                all_verifications.append({
                    "verification_type": "NON_DISPONIBILE",
                    "id": None,
                    "device_id": r.get("device_id"),
                    "verification_date": r.get("period_start"),
                    "overall_status": "NON MESSO A DISPOSIZIONE",
                    "notes": r.get("reason", ""),
                    "description": r.get("description"),
                    "manufacturer": r.get("manufacturer"),
                    "model": r.get("model"),
                    "serial_number": r.get("serial_number"),
                    "ams_inventory": r.get("ams_inventory"),
                    "customer_inventory": r.get("customer_inventory"),
                    "department": r.get("department"),
                    "destination_name": r.get("destination_name"),
                    "technician_name": r.get("technician_name"),
                    "unavail_report_uuid": r.get("uuid"),
                })
        except Exception as _e:
            logging.warning(f"Impossibile recuperare segnalazioni non disponibili: {_e}")

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

        destination_ids = options.get("destination_ids") or []
        try:
            if scope == "customer" and customer_id:
                cust = database.get_customer_by_id(customer_id)
                if cust:
                    customer_name = str(cust["name"]).upper()
                if destination_ids:
                    # Costruisce stringa con i nomi delle destinazioni selezionate
                    dest_names = []
                    for did in destination_ids:
                        d = database.get_destination_by_id(did)
                        if d:
                            dest_names.append(str(d["name"]).upper())
                    destination_name = ", ".join(dest_names) if dest_names else "DESTINAZIONI SELEZIONATE"
                else:
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
        system_count = sum(1 for v in verifications if v.get("verification_type") == "SISTEMA")

        def _normalize_status(value: str) -> str:
            return str(value or "").strip().upper()
        
        # Conteggio dispositivi unici (apparecchi controllati)
        # Le verifiche di sistema e le segnalazioni non disponibili non rappresentano
        # un singolo dispositivo verificato.
        unique_devices = set(
            v.get("device_id")
            for v in verifications
            if v.get("device_id") and v.get("verification_type") not in ("SISTEMA", "NON_DISPONIBILE")
        )
        devices_count = len(unique_devices)

        non_disponibili_count = sum(
            1 for v in verifications if v.get("verification_type") == "NON_DISPONIBILE"
        )
        
        # Conteggio verifiche conformi e non conformi (totale)
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

        # Conteggi separati per tipo di verifica (frontespizio)
        el_verifs  = [v for v in verifications if v.get("verification_type") == "ELETTRICA"]
        fun_verifs = [v for v in verifications if v.get("verification_type") == "FUNZIONALE"]
        el_conformi_count  = sum(1 for v in el_verifs if _normalize_status(v.get("overall_status")) in ("PASSATO", "CONFORME"))
        el_cca_count       = sum(1 for v in el_verifs if _normalize_status(v.get("overall_status")) == "CONFORME CON ANNOTAZIONE")
        el_nc_count        = sum(1 for v in el_verifs if _normalize_status(v.get("overall_status")) in ("FALLITO", "NON CONFORME"))
        fun_conformi_count = sum(1 for v in fun_verifs if _normalize_status(v.get("overall_status")) in ("PASSATO", "CONFORME"))
        fun_cca_count      = sum(1 for v in fun_verifs if _normalize_status(v.get("overall_status")) == "CONFORME CON ANNOTAZIONE")
        fun_nc_count       = sum(1 for v in fun_verifs if _normalize_status(v.get("overall_status")) in ("FALLITO", "NON CONFORME"))

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
            "system_count": system_count,
            "conformi_count": conformi_count,
            "conformi_con_annotazione_count": conformi_con_annotazione_count,
            "non_conformi_count": non_conformi_count,
            "non_disponibili_count": non_disponibili_count,
            "el_conformi_count": el_conformi_count,
            "el_cca_count": el_cca_count,
            "el_nc_count": el_nc_count,
            "fun_conformi_count": fun_conformi_count,
            "fun_cca_count": fun_cca_count,
            "fun_nc_count": fun_nc_count,
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
        self.show_success_feedback(f"Inventario esportato in: {filepath}", timeout_ms=7000)

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
                self.show_warning_feedback(
                    f"File di log di oggi non trovato. Percorso cercato: {log_file_path}",
                    timeout_ms=7000,
                )
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
            self.show_success_feedback(f"File di log esportato in: {save_path}", timeout_ms=7000)

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
        self.left_panel_widget = QWidget()
        self.left_panel_widget.setObjectName("homeSidebar")
        self.left_panel_widget.setMaximumWidth(300)
        self.left_panel_widget.setMinimumWidth(220)
        left_layout = QVBoxLayout(self.left_panel_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(14)
        
        # Ricerca globale rapida in alto
        search_group = self._create_global_search_group()
        left_layout.addWidget(search_group)

        self.inline_feedback_banner = self._create_inline_feedback_banner()
        left_layout.addWidget(self.inline_feedback_banner)
        
        #sessione di verifica
        session_group = self._create_session_group()
        left_layout.addWidget(session_group)
        
        # Statistiche moderne (cards)
        stats_header = self._create_stats_cards()
        left_layout.addWidget(stats_header)
        
        # Pulsanti azioni con icone grandi
        actions_group = QGroupBox("Azioni Principali")
        actions_group.setObjectName("homeActionsGroup")
        actions_layout = QVBoxLayout()
        
        self.manage_button = QPushButton(get_icon("archive", theme=self.current_theme), " Archivio Clienti e Dispositivi")
        self.manage_button.setObjectName("secondaryButton")
        self.manage_button.setMinimumHeight(40)
        self.manage_button.setToolTip("Apri l'archivio completo di clienti, destinazioni e dispositivi")
        self.manage_button.clicked.connect(self.open_db_manager)
        
        self.sync_button = QPushButton(get_icon("sync", theme=self.current_theme), " Sincronizza Dati")
        self.sync_button.setObjectName("editButton")
        self.sync_button.setMinimumHeight(40)
        self.sync_button.setToolTip("Invia e ricevi gli aggiornamenti dal server")
        self.sync_button.clicked.connect(self.run_synchronization)
        
        actions_layout.addWidget(self.manage_button)
        actions_layout.addWidget(self.sync_button)
        actions_group.setLayout(actions_layout)
        left_layout.addWidget(actions_group)
        
        left_layout.addStretch()
        
        self.main_layout.addWidget(self.left_panel_widget, 1)
        
        # Aggiorna subito le statistiche
        self.update_dashboard()
    
    def _create_stats_cards(self):
        """Crea le cards moderne per le statistiche."""
        group = QGroupBox("📊 Panoramica")
        group.setObjectName("statsGroupBox")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        self.stats_layout = QGridLayout()
        self.stats_layout.setHorizontalSpacing(8)
        self.stats_layout.setVerticalSpacing(8)
        
        # Crea placeholders per le cards
        self.total_card = QLabel()
        self.total_card.setObjectName("statsCardPrimary")
        self.total_card.setTextFormat(Qt.RichText)
        self.total_card.setWordWrap(True)
        self.total_card.setMinimumHeight(88)
        self.total_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.total_card.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.conformi_card = QLabel()
        self.conformi_card.setObjectName("statsCardSuccess")
        self.conformi_card.setTextFormat(Qt.RichText)
        self.conformi_card.setWordWrap(True)
        self.conformi_card.setMinimumHeight(82)
        self.conformi_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.conformi_card.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.non_conformi_card = QLabel()
        self.non_conformi_card.setObjectName("statsCardDanger")
        self.non_conformi_card.setTextFormat(Qt.RichText)
        self.non_conformi_card.setWordWrap(True)
        self.non_conformi_card.setMinimumHeight(82)
        self.non_conformi_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.non_conformi_card.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        self.stats_layout.addWidget(self.total_card, 0, 0, 1, 2)
        self.stats_layout.addWidget(self.conformi_card, 1, 0)
        self.stats_layout.addWidget(self.non_conformi_card, 1, 1)

        self.stats_timestamp_label = QLabel("Aggiornamento in corso...")
        self.stats_timestamp_label.setObjectName("statsTimestampLabel")
        self.stats_timestamp_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addLayout(self.stats_layout)
        layout.addWidget(self.stats_timestamp_label)
        group.setLayout(layout)
        
        return group

    def create_right_panel(self):
        """Crea il pannello principale con layout Drill-Down."""
        self.selected_customer_id = None
        self.selected_destination_id = None
        self.selected_device_id = None
        self._drill_device_name = None
        self._drill_step = 0   # 0=clienti, 1=destinazioni, 2=dispositivi

        main_container = QWidget()
        main_container.setObjectName("homeWorkspace")
        self.right_layout = QVBoxLayout(main_container)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(0)

        # === BREADCRUMB BAR ===
        self.drill_breadcrumb_bar = self._create_drill_breadcrumb()
        self.right_layout.addWidget(self.drill_breadcrumb_bar)

        # === STACK: ogni step è un widget, uno visibile alla volta ===
        self.drill_stack = QWidget()
        self.drill_stack.setObjectName("drillStack")
        self._drill_stack_layout = QStackedLayout(self.drill_stack)
        self._drill_stack_layout.setContentsMargins(0, 0, 0, 0)

        self._drill_stack_layout.addWidget(self._create_drill_customer_page())   # idx 0
        self._drill_stack_layout.addWidget(self._create_drill_destination_page()) # idx 1
        self._drill_stack_layout.addWidget(self._create_drill_device_page())      # idx 2

        self.right_layout.addWidget(self.drill_stack, 1)

        # === STICKY ACTION BAR ===
        self.bottom_action_panel = self._create_bottom_action_panel()
        self.right_layout.addWidget(self.bottom_action_panel)

        # Container test runner (nascosto)
        self.test_runner_container = QWidget()
        self.test_runner_layout = QVBoxLayout(self.test_runner_container)
        self.test_runner_container.hide()
        self.right_layout.addWidget(self.test_runner_container, 1)

        # Pannelli nascosti per compatibilità con load/filter/restore logic
        self.customer_panel = QWidget()
        self.customer_panel.hide()
        self.destination_panel = QWidget()
        self.destination_panel.hide()
        self.device_panel = QWidget()
        self.device_panel.hide()

        self.main_layout.addWidget(main_container, 4)
        self._drill_goto(0)
        self._update_guided_flow_ui()

    # ── Drill-down layout ───────────────────────────────────────────────────

    def _create_drill_breadcrumb(self):
        """Barra breadcrumb cliccabile per il drill-down."""
        bar = QFrame()
        bar.setObjectName("drillBreadcrumbBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Crumb clienti (sempre cliccabile)
        self.drill_crumb_customer = QPushButton("Clienti")
        self.drill_crumb_customer.setObjectName("drillCrumb")
        self.drill_crumb_customer.setProperty("crumbStep", "0")
        self.drill_crumb_customer.clicked.connect(lambda: self._drill_back_to(0))
        layout.addWidget(self.drill_crumb_customer)

        self._drill_arrow1 = QLabel("›")
        self._drill_arrow1.setObjectName("drillCrumbArrow")
        self._drill_arrow1.hide()
        layout.addWidget(self._drill_arrow1)

        # Crumb destinazioni
        self.drill_crumb_destination = QPushButton("—")
        self.drill_crumb_destination.setObjectName("drillCrumb")
        self.drill_crumb_destination.setProperty("crumbStep", "1")
        self.drill_crumb_destination.clicked.connect(lambda: self._drill_back_to(1))
        self.drill_crumb_destination.hide()
        layout.addWidget(self.drill_crumb_destination)

        self._drill_arrow2 = QLabel("›")
        self._drill_arrow2.setObjectName("drillCrumbArrow")
        self._drill_arrow2.hide()
        layout.addWidget(self._drill_arrow2)

        # Crumb dispositivi (solo testo, step finale - usa QPushButton per QSS affidabile)
        self.drill_crumb_device = QPushButton("Dispositivi")
        self.drill_crumb_device.setObjectName("drillCrumbCurrent")
        self.drill_crumb_device.setEnabled(True)
        self.drill_crumb_device.setFocusPolicy(Qt.NoFocus)
        self.drill_crumb_device.setCursor(Qt.ArrowCursor)
        self.drill_crumb_device.hide()
        layout.addWidget(self.drill_crumb_device)

        layout.addStretch()

        # Contatore risultati (visibile su tutti gli step)
        self.drill_count_label = QLabel("")
        self.drill_count_label.setObjectName("drillCountLabel")
        self.drill_count_label.setAttribute(Qt.WA_StyledBackground, True)
        layout.addWidget(self.drill_count_label)

        return bar

    def _create_drill_customer_page(self):
        """Pagina step 0: lista clienti a tutta altezza."""
        page = QWidget()
        page.setObjectName("drillPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)

        # Search bar
        self.customer_search = QLineEdit()
        self.customer_search.setPlaceholderText("Cerca cliente...")
        self.customer_search.setFixedHeight(38)
        self.customer_search.textChanged.connect(self.filter_customers)
        self.customer_search.textChanged.connect(lambda *_: self._persist_main_view_state())
        lay.addWidget(self.customer_search)

        # Lista clienti
        self.customer_list = QListWidget()
        self.customer_list.setObjectName("drillListWidget")
        self.customer_list.itemClicked.connect(self._on_drill_customer_clicked)
        lay.addWidget(self.customer_list, 1)

        # label contatore (compat)
        self.customer_count_label = QLabel("")
        self.customer_count_label.hide()
        lay.addWidget(self.customer_count_label)

        return page

    def _create_drill_destination_page(self):
        """Pagina step 1: lista destinazioni a tutta altezza."""
        page = QWidget()
        page.setObjectName("drillPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)

        self.destination_search = QLineEdit()
        self.destination_search.setPlaceholderText("Cerca destinazione...")
        self.destination_search.setFixedHeight(38)
        self.destination_search.textChanged.connect(self.filter_destinations)
        self.destination_search.textChanged.connect(lambda *_: self._persist_main_view_state())
        lay.addWidget(self.destination_search)

        self.destination_list = QListWidget()
        self.destination_list.setObjectName("drillListWidget")
        self.destination_list.itemClicked.connect(self._on_drill_destination_clicked)
        lay.addWidget(self.destination_list, 1)

        self.destination_count_label = QLabel("")
        self.destination_count_label.hide()
        lay.addWidget(self.destination_count_label)

        return page

    def _create_drill_device_page(self):
        """Pagina step 2: lista dispositivi con filtri a tutta altezza."""
        page = QWidget()
        page.setObjectName("drillPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)

        # Toolbar ricerca + azioni
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.device_search = QLineEdit()
        self.device_search.setPlaceholderText("Cerca dispositivo, S/N, inventario...")
        self.device_search.setFixedHeight(38)
        self.device_search.textChanged.connect(self.filter_devices)
        self.device_search.textChanged.connect(lambda *_: self._persist_main_view_state())
        toolbar.addWidget(self.device_search, 1)

        self.add_device_button = QPushButton(get_icon("add", theme=self.current_theme), "")
        self.add_device_button.setObjectName("addButton")
        self.add_device_button.setProperty("homeIconButton", True)
        self.add_device_button.setProperty("iconRole", "add")
        self.add_device_button.setToolTip("Aggiungi nuovo dispositivo")
        self._prepare_home_icon_button(self.add_device_button, size=38, icon_size=16)
        self.add_device_button.clicked.connect(self.quick_add_device)
        toolbar.addWidget(self.add_device_button)

        self.device_verification_filter_combo = QComboBox()
        self.device_verification_filter_combo.addItem("🔍 Nessuna verifica eseguita", "UNVERIFIED_60")
        self.device_verification_filter_combo.addItem("🫀 Manca funzionale", "ONLY_FUNCTIONAL_60")
        self.device_verification_filter_combo.addItem("⚡ Manca elettrica", "ONLY_ELECTRICAL_60")
        self.device_verification_filter_combo.addItem("✅ VE O VF MANCANTE", "BOTH_60")
        self.device_verification_filter_combo.addItem("📋 Tutti i dispositivi", "ALL")
        self.device_verification_filter_combo.setCurrentIndex(0)
        self.device_verification_filter_combo.setFixedHeight(38)
        self.device_verification_filter_combo.setToolTip(
            "Filtra i dispositivi in base alle verifiche elettriche/funzionali nel periodo selezionato"
        )
        self.device_verification_filter_combo.currentIndexChanged.connect(self.reload_devices)
        self.device_verification_filter_combo.currentIndexChanged.connect(lambda *_: self._persist_main_view_state())
        toolbar.addWidget(self.device_verification_filter_combo)

        self.device_period_button = QPushButton(get_icon("calendar", theme=self.current_theme), "")
        self.device_period_button.setObjectName("calendarFilterButton")
        self.device_period_button.setProperty("homeIconButton", True)
        self.device_period_button.setProperty("iconRole", "calendar")
        self._prepare_home_icon_button(self.device_period_button, size=38, icon_size=16)
        self.device_period_button.clicked.connect(self.choose_device_filter_period)
        self._update_device_period_button_tooltip()
        toolbar.addWidget(self.device_period_button)

        lay.addLayout(toolbar)

        self.device_list = QListWidget()
        self.device_list.setObjectName("drillListWidget")
        self.device_list.itemClicked.connect(self.on_device_selected_new)
        self.device_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.device_list.customContextMenuRequested.connect(self._show_device_context_menu)
        lay.addWidget(self.device_list, 1)

        self.device_count_label = QLabel("<i>Seleziona una destinazione</i>")
        self.device_count_label.setObjectName("drillCountInline")
        lay.addWidget(self.device_count_label)

        return page

    def _drill_goto(self, step: int):
        """Passa allo step del drill-down e aggiorna il breadcrumb."""
        self._drill_step = step
        if hasattr(self, "_drill_stack_layout"):
            self._drill_stack_layout.setCurrentIndex(step)
        # focus sulla search del passo attivo
        if step == 0 and hasattr(self, "customer_search"):
            self.customer_search.setFocus()
        elif step == 1 and hasattr(self, "destination_search"):
            self.destination_search.setFocus()
        elif step == 2 and hasattr(self, "device_search"):
            self.device_search.setFocus()
        self._update_drill_breadcrumb()

    def _drill_back_to(self, step: int):
        """Torna indietro al passo indicato resettando le selezioni successive."""
        if step == 0:
            self.selected_customer_id = None
            self.selected_destination_id = None
            self.selected_device_id = None
            self._drill_device_name = None
            if hasattr(self, "destination_list"):
                self.destination_list.clear()
            if hasattr(self, "device_list"):
                self.device_list.clear()
        elif step == 1:
            self.selected_destination_id = None
            self.selected_device_id = None
            self._drill_device_name = None
            if hasattr(self, "device_list"):
                self.device_list.clear()
        self._drill_goto(step)
        self.update_summary_panel()
        self._persist_main_view_state()
        self._update_guided_flow_ui()

    def _on_drill_customer_clicked(self, item):
        """Avanza al drill-down step 1 dopo selezione cliente."""
        self.on_customer_selected(item)
        self._drill_goto(1)

    def _on_drill_destination_clicked(self, item):
        """Avanza al drill-down step 2 dopo selezione destinazione."""
        self.on_destination_selected_new(item)
        self._drill_goto(2)

    def _update_drill_breadcrumb(self):
        """Aggiorna testi e visibilità del breadcrumb drill-down."""
        step = getattr(self, "_drill_step", 0)

        # Crumb clienti: sempre visibile, evidenziato se step>0
        if hasattr(self, "drill_crumb_customer"):
            if self.selected_customer_id:
                name = getattr(self, '_drill_customer_name', None) or "Cliente"
                self.drill_crumb_customer.setText(name)
            else:
                self.drill_crumb_customer.setText("Clienti")
            self.drill_crumb_customer.setProperty("crumbActive", "true" if step > 0 else "current")
            self.drill_crumb_customer.style().unpolish(self.drill_crumb_customer)
            self.drill_crumb_customer.style().polish(self.drill_crumb_customer)

        # Freccia + crumb destinazioni
        if hasattr(self, "_drill_arrow1"):
            self._drill_arrow1.setVisible(step >= 1)
        if hasattr(self, "drill_crumb_destination"):
            self.drill_crumb_destination.setVisible(step >= 1)
            if self.selected_destination_id:
                name = getattr(self, '_drill_destination_name', None) or "Destinazione"
                self.drill_crumb_destination.setText(name)
            else:
                self.drill_crumb_destination.setText("Destinazioni")
            self.drill_crumb_destination.setProperty("crumbActive", "true" if step > 1 else "current")
            self.drill_crumb_destination.style().unpolish(self.drill_crumb_destination)
            self.drill_crumb_destination.style().polish(self.drill_crumb_destination)

        # Freccia + label dispositivi
        if hasattr(self, "_drill_arrow2"):
            self._drill_arrow2.setVisible(step >= 2)
        if hasattr(self, "drill_crumb_device"):
            self.drill_crumb_device.setVisible(step >= 2)
            if self.selected_device_id:
                dev_name = getattr(self, '_drill_device_name', None)
                if not dev_name:
                    try:
                        d = services.database.get_device_by_id(self.selected_device_id)
                        if d:
                            dev_name = dict(d).get('description') or None
                    except Exception:
                        pass
                self.drill_crumb_device.setText(dev_name or 'Dispositivo')
                self.drill_crumb_device.setObjectName("drillCrumbSelected")
            else:
                self.drill_crumb_device.setText('Dispositivi')
                self.drill_crumb_device.setObjectName("drillCrumbCurrent")
            self.drill_crumb_device.setStyleSheet("")
            self.drill_crumb_device.style().unpolish(self.drill_crumb_device)
            self.drill_crumb_device.style().polish(self.drill_crumb_device)

        # Contatore
        if hasattr(self, "drill_count_label"):
            if step == 0:
                n = self.customer_list.count() if hasattr(self, "customer_list") else 0
                self.drill_count_label.setText(f"{n} clienti")
            elif step == 1:
                n = self.destination_list.count() if hasattr(self, "destination_list") else 0
                self.drill_count_label.setText(f"{n} destinazioni")
            else:
                n = self.device_list.count() if hasattr(self, "device_list") else 0
                self.drill_count_label.setText(f"{n} dispositivi")

    def _update_guided_flow_ui(self):
        """Mantiene coerente l'abilitazione dei pannelli, breadcrumb e azioni principali."""
        has_customer   = bool(self.selected_customer_id)
        has_destination = bool(self.selected_destination_id)
        has_device     = bool(self.selected_device_id)

        # ── Abilita/disabilita colonne + placeholder ────────────────────────────
        if hasattr(self, "destination_panel"):
            self.destination_panel.setEnabled(has_customer)
            self.destination_panel.setProperty("locked", "" if has_customer else "true")
            self.destination_panel.style().unpolish(self.destination_panel)
            self.destination_panel.style().polish(self.destination_panel)
            if hasattr(self, "destination_placeholder"):
                self.destination_placeholder.setVisible(not has_customer)
                if hasattr(self, "destination_list"):
                    self.destination_list.setVisible(has_customer)
                if hasattr(self, "destination_search"):
                    self.destination_search.setVisible(has_customer)
        if hasattr(self, "device_panel"):
            self.device_panel.setEnabled(has_destination)
            self.device_panel.setProperty("locked", "" if has_destination else "true")
            self.device_panel.style().unpolish(self.device_panel)
            self.device_panel.style().polish(self.device_panel)
            if hasattr(self, "device_placeholder"):
                self.device_placeholder.setVisible(not has_destination)
                if hasattr(self, "device_list"):
                    self.device_list.setVisible(has_destination)
                if hasattr(self, "device_search"):
                    self.device_search.setVisible(has_destination)
                if hasattr(self, "device_verification_filter_combo"):
                    self.device_verification_filter_combo.setVisible(has_destination)
                if hasattr(self, "add_device_button"):
                    self.add_device_button.setVisible(has_destination)
                if hasattr(self, "device_period_button"):
                    self.device_period_button.setVisible(has_destination)

        # ── Pulsanti azione ─────────────────────────────────────────────────────
        if hasattr(self, "btn_edit_device"):
            self.btn_edit_device.setEnabled(has_device)
        if hasattr(self, "start_electrical_button"):
            self.start_electrical_button.setEnabled(has_device)
        if hasattr(self, "start_functional_button"):
            self.start_functional_button.setEnabled(
                has_device and self.functional_profile_selector.count() > 0
            )

        # ── Breadcrumb step labels ───────────────────────────────────────────────
        if hasattr(self, "bc_customer_label"):
            customer_name = getattr(self, '_drill_customer_name', None) if has_customer else None
            if customer_name:
                self.bc_customer_label.setText(f"① {customer_name}")
                self.bc_customer_label.setProperty("state", "active")
            else:
                self.bc_customer_label.setText("① Cliente")
                self.bc_customer_label.setProperty("state", "pending")
            self.bc_customer_label.style().unpolish(self.bc_customer_label)
            self.bc_customer_label.style().polish(self.bc_customer_label)

        if hasattr(self, "bc_dest_label"):
            dest_name = getattr(self, '_drill_destination_name', None) if has_destination else None
            if dest_name:
                self.bc_dest_label.setText(f"② {dest_name}")
                self.bc_dest_label.setProperty("state", "active")
            else:
                self.bc_dest_label.setText("② Destinazione")
                self.bc_dest_label.setProperty("state", "pending" if has_customer else "locked")
            self.bc_dest_label.style().unpolish(self.bc_dest_label)
            self.bc_dest_label.style().polish(self.bc_dest_label)

        if hasattr(self, "bc_device_label"):
            device_name = getattr(self, '_drill_device_name', None) if has_device else None
            if device_name:
                self.bc_device_label.setText(f"③ {device_name}")
                self.bc_device_label.setProperty("state", "active")
            else:
                self.bc_device_label.setText("③ Dispositivo")
                self.bc_device_label.setProperty("state", "pending" if has_destination else "locked")
            self.bc_device_label.style().unpolish(self.bc_device_label)
            self.bc_device_label.style().polish(self.bc_device_label)

        # ── Badge sessione ───────────────────────────────────────────────────────
        if hasattr(self, "session_status_label"):
            if self.current_mti_info:
                sn = self.current_mti_info.get("serial_number") or self.current_mti_info.get("com_port", "?")
                self.session_status_label.setText(f"🔧 Strumento: {sn}")
                self.session_status_label.setProperty("state", "ready")
            else:
                self.session_status_label.setText("⚠ Sessione non impostata")
                self.session_status_label.setProperty("state", "warning")
            self.session_status_label.style().unpolish(self.session_status_label)
            self.session_status_label.style().polish(self.session_status_label)

        # ── Testo pulsante sessione sidebar ─────────────────────────────────────
        if hasattr(self, "change_session_btn"):
            if has_device and not self.current_mti_info:
                self.change_session_btn.setText(" Imposta Sessione per Verifica")
            else:
                self.change_session_btn.setText(" Imposta Sessione")

        # ── Breadcrumb drill-down ────────────────────────────────────────────────
        self._update_drill_breadcrumb()

    def _setup_keyboard_shortcuts(self):
        """Registra scorciatoie utili per il flusso principale."""
        self._window_shortcuts = []
        shortcuts = [
            ("Ctrl+F", self._focus_global_search),
            ("Ctrl+Shift+F", self.open_advanced_search),
            ("Ctrl+N", self._shortcut_quick_add_device),
            ("Ctrl+S", self._shortcut_sync),
            ("F6", self.setup_session),
            ("Alt+1", lambda: (self._drill_goto(0), self._focus_widget(self.customer_search))),
            ("Alt+2", lambda: (self._drill_goto(1), self._focus_widget(self.destination_search))),
            ("Alt+3", lambda: (self._drill_goto(2), self._focus_widget(self.device_search))),
        ]

        for key_sequence, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(key_sequence), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(callback)
            self._window_shortcuts.append(shortcut)

    def _setup_accessibility(self):
        """Aggiunge nomi accessibili e un tab order più prevedibile."""
        widget_metadata = [
            (
                self.global_device_search_edit,
                "Ricerca rapida globale",
                "Cerca clienti, destinazioni o dispositivi dalla schermata principale.",
            ),
            (
                self.qr_scan_btn,
                "Scanner QR",
                "Attiva o disattiva la scansione QR da telefono per cercare un dispositivo.",
            ),
            (
                self.change_session_btn,
                "Imposta sessione",
                "Seleziona lo strumento e prepara la sessione tecnica per le verifiche.",
            ),
            (
                self.customer_search,
                "Ricerca clienti",
                "Filtra l'elenco clienti.",
            ),
            (
                self.customer_list,
                "Elenco clienti",
                "Mostra i clienti disponibili.",
            ),
            (
                self.destination_search,
                "Ricerca destinazioni",
                "Filtra l'elenco destinazioni del cliente selezionato.",
            ),
            (
                self.destination_list,
                "Elenco destinazioni",
                "Mostra le destinazioni del cliente selezionato.",
            ),
            (
                self.device_search,
                "Ricerca dispositivi",
                "Filtra l'elenco dispositivi della destinazione selezionata.",
            ),
            (
                self.device_list,
                "Elenco dispositivi",
                "Mostra i dispositivi disponibili per la destinazione selezionata.",
            ),
            (
                self.profile_selector,
                "Profilo elettrico",
                "Seleziona il profilo di verifica elettrica del dispositivo.",
            ),
            (
                self.functional_profile_selector,
                "Profilo funzionale",
                "Seleziona il profilo di verifica funzionale del dispositivo.",
            ),
            (
                self.btn_edit_device,
                "Modifica dispositivo",
                "Apre la modifica del dispositivo selezionato.",
            ),
            (
                self.start_electrical_button,
                "Avvia verifica elettrica",
                "Avvia la verifica elettrica del dispositivo selezionato.",
            ),
            (
                self.start_functional_button,
                "Avvia verifica funzionale",
                "Avvia la verifica funzionale guidata del dispositivo selezionato.",
            ),
        ]

        for widget, accessible_name, accessible_description in widget_metadata:
            widget.setAccessibleName(accessible_name)
            widget.setAccessibleDescription(accessible_description)

        QWidget.setTabOrder(self.global_device_search_edit, self.change_session_btn)
        QWidget.setTabOrder(self.change_session_btn, self.customer_search)
        QWidget.setTabOrder(self.customer_search, self.customer_list)
        QWidget.setTabOrder(self.customer_list, self.destination_search)
        QWidget.setTabOrder(self.destination_search, self.destination_list)
        QWidget.setTabOrder(self.destination_list, self.device_search)
        QWidget.setTabOrder(self.device_search, self.device_list)
        QWidget.setTabOrder(self.device_list, self.profile_selector)
        QWidget.setTabOrder(self.profile_selector, self.functional_profile_selector)
        QWidget.setTabOrder(self.functional_profile_selector, self.btn_edit_device)
        QWidget.setTabOrder(self.btn_edit_device, self.start_electrical_button)
        QWidget.setTabOrder(self.start_electrical_button, self.start_functional_button)

    def _can_use_home_shortcuts(self) -> bool:
        """Ritorna True se la home principale è visibile."""
        return getattr(self, "_stacked_widget", None) is not None and self._stacked_widget.currentIndex() == 0

    def _focus_widget(self, widget):
        """Porta il focus su un widget se la home è attiva."""
        if not self._can_use_home_shortcuts() or widget is None:
            return
        widget.setFocus()
        if isinstance(widget, QLineEdit):
            widget.selectAll()

    def _focus_global_search(self):
        """Focus veloce sulla ricerca rapida globale."""
        self._focus_widget(self.global_device_search_edit)

    def _shortcut_quick_add_device(self):
        """Scorciatoia per inserimento rapido dispositivo."""
        if not self._can_use_home_shortcuts():
            return
        if not self.selected_destination_id:
            self.show_inline_feedback(
                "Seleziona prima una destinazione per aggiungere un dispositivo.",
                level="warning",
            )
            self._focus_widget(self.destination_search)
            return
        self.quick_add_device()

    def _shortcut_sync(self):
        """Scorciatoia per sincronizzazione manuale."""
        if not self._can_use_home_shortcuts():
            return
        self.run_synchronization()

    def _prepare_home_icon_button(self, button: QPushButton, size: int = 40, icon_size: int = 18):
        """Blocca dimensioni e resa dei pulsanti icon-only della home."""
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setFixedSize(size, size)
        button.setIconSize(QSize(icon_size, icon_size))
        button.setAutoDefault(False)
        button.setDefault(False)
        button.style().unpolish(button)
        button.style().polish(button)
        button.updateGeometry()
        button.update()
    
    def _create_global_search_group(self):
        """Crea il gruppo di ricerca rapida globale."""
        group = QGroupBox("🔍 Ricerca rapida")
        group.setObjectName("searchGroupBox")
        # Gli stili sono gestiti dal QSS del tema
        layout = QHBoxLayout(group)
        layout.setSpacing(10)
        
        # Campo di ricerca
        self.global_device_search_edit = QLineEdit()
        self.global_device_search_edit.setPlaceholderText("Cerca cliente, destinazione o dispositivo")
        self.global_device_search_edit.setMinimumHeight(45)
        self.global_device_search_edit.setCompleter(None)  # Disabilita memoria/autocomplete
        self.global_device_search_edit.returnPressed.connect(self.perform_global_search)
        self.global_device_search_edit.textChanged.connect(lambda *_: self._persist_main_view_state())
        
        # Pulsante cerca (solo icona)
        self.global_search_button = QPushButton(get_icon("search", theme=self.current_theme), "")
        self.global_search_button.setObjectName("primaryButton")
        self.global_search_button.setProperty("homeIconButton", True)
        self.global_search_button.setProperty("iconRole", "search")
        self._prepare_home_icon_button(self.global_search_button, size=38, icon_size=18)
        self.global_search_button.setToolTip("Cerca")
        self.global_search_button.clicked.connect(self.perform_global_search)
        
        # Indicatore stato scanner (usato da altri metodi, mantenuto ma non visibile qui)
        self.qr_scan_btn = QPushButton()  # placeholder per compatibilità con metodi esistenti
        self.qr_scan_btn.hide()
        self.qr_status_indicator = QLabel("")
        self.qr_status_indicator.hide()

        layout.addWidget(self.global_device_search_edit, 1)
        layout.addWidget(self.global_search_button)
        
        return group

    def _create_inline_feedback_banner(self):
        """Crea un banner inline non bloccante per messaggi rapidi nella home."""
        banner = QFrame()
        banner.setObjectName("inlineFeedbackBanner")
        banner.hide()

        layout = QHBoxLayout(banner)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        self.inline_feedback_title = QLabel("Info")
        self.inline_feedback_title.setStyleSheet("font-weight: 700; background: transparent;")
        self.inline_feedback_title.hide()
        layout.addWidget(self.inline_feedback_title, 0)

        self.inline_feedback_label = QLabel("")
        self.inline_feedback_label.setWordWrap(True)
        self.inline_feedback_label.setTextFormat(Qt.RichText)
        self.inline_feedback_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.inline_feedback_label.setMinimumWidth(0)
        self.inline_feedback_label.setStyleSheet("background: transparent;")
        layout.addWidget(self.inline_feedback_label, 1)

        return banner

    def show_inline_feedback(self, message: str, level: str = "info", timeout_ms: int = 5000):
        """Mostra un messaggio inline non bloccante e lo replica nella status bar."""
        if not message:
            return

        styles = {
            "info": {
                "title": "Info",
                "bg": "#e0f2fe",
                "border": "#38bdf8",
                "text": "#0f172a",
            },
            "success": {
                "title": "Completato",
                "bg": "#dcfce7",
                "border": "#22c55e",
                "text": "#14532d",
            },
            "warning": {
                "title": "Attenzione",
                "bg": "#fef3c7",
                "border": "#f59e0b",
                "text": "#78350f",
            },
            "error": {
                "title": "Errore",
                "bg": "#fee2e2",
                "border": "#ef4444",
                "text": "#7f1d1d",
            },
        }
        style = styles.get(level, styles["info"])

        if hasattr(self, "inline_feedback_title") and hasattr(self, "inline_feedback_label"):
            self.inline_feedback_title.setText(style["title"])
            self.inline_feedback_label.setText(f"<b>{style['title']}:</b> {message}")
            self.inline_feedback_banner.setStyleSheet(
                "QFrame#inlineFeedbackBanner {"
                f"background-color: {style['bg']};"
                f"border: 1px solid {style['border']};"
                "border-radius: 10px;"
                "}"
                f"QLabel {{ color: {style['text']}; }}"
            )
            self.inline_feedback_banner.show()

        if timeout_ms and timeout_ms > 0:
            self.inline_feedback_timer.start(timeout_ms)
            self.statusBar().showMessage(message, timeout_ms)
        else:
            self.inline_feedback_timer.stop()
            self.statusBar().showMessage(message)

    def clear_inline_feedback(self):
        """Nasconde il banner inline attivo."""
        self.inline_feedback_timer.stop()
        if hasattr(self, "inline_feedback_label"):
            self.inline_feedback_label.clear()
        if hasattr(self, "inline_feedback_banner"):
            self.inline_feedback_banner.hide()

    def _is_home_view_active(self) -> bool:
        """Ritorna True se la schermata principale e' visibile."""
        return getattr(self, "_stacked_widget", None) is not None and self._stacked_widget.currentIndex() == 0

    def show_soft_feedback(self, message: str, level: str = "info", timeout_ms: int = 5000):
        """Mostra feedback leggero senza interrompere il flusso."""
        if not message:
            return
        if self._is_home_view_active():
            self.show_inline_feedback(message, level=level, timeout_ms=timeout_ms)
            return

        self.inline_feedback_timer.stop()
        self.statusBar().showMessage(message, timeout_ms if timeout_ms and timeout_ms > 0 else 0)

    def show_success_feedback(self, message: str, timeout_ms: int = 5000):
        self.show_soft_feedback(message, level="success", timeout_ms=timeout_ms)

    def show_info_feedback(self, message: str, timeout_ms: int = 5000):
        self.show_soft_feedback(message, level="info", timeout_ms=timeout_ms)

    def show_warning_feedback(self, message: str, timeout_ms: int = 6000):
        self.show_soft_feedback(message, level="warning", timeout_ms=timeout_ms)

    def _settings_int_value(self, key: str):
        """Legge un intero da QSettings restituendo None se non valido."""
        value = self.settings.value(key, "")
        if value in (None, "", "None"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _settings_bool_value(self, key: str, default: bool = False) -> bool:
        """Legge un booleano da QSettings in modo tollerante."""
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        if value in (None, ""):
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _restore_window_layout_settings(self):
        """Ripristina geometria finestra e layout principale persistiti."""
        geometry = self.settings.value("geometry")
        was_maximized = self._settings_bool_value("main_window/is_maximized", True)

        if was_maximized:
            self.setWindowState(Qt.WindowMaximized)
        elif geometry is not None:
            self.setWindowState(Qt.WindowNoState)
            self.restoreGeometry(geometry)

        splitter_state = self.settings.value("main_window/splitter_state")
        if splitter_state is not None and hasattr(self, "main_splitter"):
            self.main_splitter.restoreState(splitter_state)

    def _persist_main_view_state(self):
        """Salva layout e contesto principale della schermata home."""
        if getattr(self, "_restoring_persisted_state", False):
            return

        if hasattr(self, "main_splitter"):
            self.settings.setValue("main_window/splitter_state", self.main_splitter.saveState())

        self.settings.setValue("main_window/device_filter_mode", self._get_device_filter_mode())
        self.settings.setValue("main_window/device_filter_start_date", self.device_filter_start_date.isoformat())
        self.settings.setValue("main_window/device_filter_end_date", self.device_filter_end_date.isoformat())
        self.settings.setValue(
            "main_window/global_search_text",
            self.global_device_search_edit.text() if hasattr(self, "global_device_search_edit") else "",
        )
        self.settings.setValue(
            "main_window/customer_search_text",
            self.customer_search.text() if hasattr(self, "customer_search") else "",
        )
        self.settings.setValue(
            "main_window/destination_search_text",
            self.destination_search.text() if hasattr(self, "destination_search") else "",
        )
        self.settings.setValue(
            "main_window/device_search_text",
            self.device_search.text() if hasattr(self, "device_search") else "",
        )
        self.settings.setValue("main_window/selected_customer_id", self.selected_customer_id or "")
        self.settings.setValue("main_window/selected_destination_id", self.selected_destination_id or "")
        self.settings.setValue("main_window/selected_device_id", self.selected_device_id or "")

    def _restore_main_view_state(self):
        """Ripristina filtri, ricerche e selezioni della schermata home."""
        if getattr(self, "_restoring_persisted_state", False):
            return

        self._restoring_persisted_state = True
        try:
            start_value = self.settings.value("main_window/device_filter_start_date", "")
            end_value = self.settings.value("main_window/device_filter_end_date", "")
            try:
                if start_value:
                    self.device_filter_start_date = date.fromisoformat(str(start_value))
                if end_value:
                    self.device_filter_end_date = date.fromisoformat(str(end_value))
            except ValueError:
                logging.warning("Impossibile ripristinare il periodo filtro dispositivi salvato.")

            self._update_device_period_button_tooltip()

            filter_mode = self.settings.value("main_window/device_filter_mode", "UNVERIFIED_60")
            if filter_mode:
                combo = getattr(self, "device_verification_filter_combo", None)
                if combo is not None:
                    idx = combo.findData(str(filter_mode))
                    if idx != -1:
                        combo.blockSignals(True)
                        combo.setCurrentIndex(idx)
                        combo.blockSignals(False)

            if hasattr(self, "global_device_search_edit"):
                self.global_device_search_edit.setText("")  # Non ripristinare la ricerca rapida all'avvio
            if hasattr(self, "customer_search"):
                self.customer_search.setText(self.settings.value("main_window/customer_search_text", ""))

            saved_customer_id = self._settings_int_value("main_window/selected_customer_id")
            saved_destination_id = self._settings_int_value("main_window/selected_destination_id")
            saved_device_id = self._settings_int_value("main_window/selected_device_id")

            if saved_customer_id is not None:
                self._restore_customer_selection_by_id(saved_customer_id)

            if hasattr(self, "destination_search"):
                self.destination_search.setText(self.settings.value("main_window/destination_search_text", ""))

            if self.selected_customer_id and saved_destination_id is not None:
                self._restore_destination_selection_by_id(saved_destination_id)

            if hasattr(self, "device_search"):
                self.device_search.setText(self.settings.value("main_window/device_search_text", ""))

            if self.selected_destination_id and saved_device_id is not None:
                self._select_device_by_id(saved_device_id)
        finally:
            self._restoring_persisted_state = False

        # Ripristina step drill-down in base alle selezioni recuperate
        if self.selected_device_id:
            self._drill_goto(2)
        elif self.selected_destination_id:
            self._drill_goto(2)
        elif self.selected_customer_id:
            self._drill_goto(1)
        else:
            self._drill_goto(0)

        self._update_guided_flow_ui()
        self._persist_main_view_state()

    def _restore_customer_selection_by_id(self, customer_id: int) -> bool:
        """Ripristina silenziosamente la selezione cliente salvata."""
        for i in range(self.customer_list.count()):
            item = self.customer_list.item(i)
            if item.data(Qt.UserRole) == customer_id:
                self.customer_list.setCurrentItem(item)
                self.on_customer_selected(item)
                return True
        return False

    def _restore_destination_selection_by_id(self, destination_id: int) -> bool:
        """Ripristina silenziosamente la selezione destinazione salvata."""
        for i in range(self.destination_list.count()):
            item = self.destination_list.item(i)
            if item.data(Qt.UserRole) == destination_id:
                self.destination_list.setCurrentItem(item)
                self.on_destination_selected_new(item)
                return True
        return False
    
    def _create_customer_panel(self):
        """Crea il pannello clienti (colonna 1)."""
        panel = QWidget()
        panel.setObjectName("selectionColumnCard")
        panel.setProperty("columnStep", "1")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header compatto
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        step_badge = QLabel("1")
        step_badge.setObjectName("stepBadge")
        step_badge.setProperty("stepColor", "blue")
        step_badge.setFixedSize(24, 24)
        step_badge.setAlignment(Qt.AlignCenter)
        title_lbl = QLabel("CLIENTI")
        title_lbl.setObjectName("panelColumnTitle")
        header_row.addWidget(step_badge)
        header_row.addWidget(title_lbl)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Barra di ricerca clienti
        self.customer_search = QLineEdit()
        self.customer_search.setPlaceholderText("Cerca cliente...")
        self.customer_search.setMinimumHeight(36)
        self.customer_search.textChanged.connect(self.filter_customers)
        self.customer_search.textChanged.connect(lambda *_: self._persist_main_view_state())
        layout.addWidget(self.customer_search)

        # Lista clienti
        self.customer_list = QListWidget()
        self.customer_list.setObjectName("panelListWidget")
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
        panel.setObjectName("selectionColumnCard")
        panel.setProperty("columnStep", "2")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header compatto
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        step_badge = QLabel("2")
        step_badge.setObjectName("stepBadge")
        step_badge.setProperty("stepColor", "orange")
        step_badge.setFixedSize(24, 24)
        step_badge.setAlignment(Qt.AlignCenter)
        title_lbl = QLabel("DESTINAZIONI")
        title_lbl.setObjectName("panelColumnTitle")
        header_row.addWidget(step_badge)
        header_row.addWidget(title_lbl)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Barra di ricerca destinazioni
        self.destination_search = QLineEdit()
        self.destination_search.setPlaceholderText("Cerca destinazione...")
        self.destination_search.setMinimumHeight(36)
        self.destination_search.textChanged.connect(self.filter_destinations)
        self.destination_search.textChanged.connect(lambda *_: self._persist_main_view_state())
        layout.addWidget(self.destination_search)

        # Lista destinazioni
        self.destination_list = QListWidget()
        self.destination_list.setObjectName("panelListWidget")
        self.destination_list.itemClicked.connect(self.on_destination_selected_new)
        layout.addWidget(self.destination_list)

        # Placeholder colonna bloccata
        self.destination_placeholder = QLabel("← Seleziona prima un cliente")
        self.destination_placeholder.setObjectName("columnPlaceholder")
        self.destination_placeholder.setAlignment(Qt.AlignCenter)
        self.destination_placeholder.hide()
        layout.addWidget(self.destination_placeholder)

        # Contatore
        self.destination_count_label = QLabel("<i>Seleziona un cliente</i>")
        self.destination_count_label.setObjectName("panelCountLabel")
        layout.addWidget(self.destination_count_label)

        return panel
    
    def _create_device_panel(self):
        """Crea il pannello dispositivi (colonna 3)."""
        panel = QWidget()
        panel.setObjectName("selectionColumnCard")
        panel.setProperty("columnStep", "3")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header compatto con pulsante aggiungi a destra
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        step_badge = QLabel("3")
        step_badge.setObjectName("stepBadge")
        step_badge.setProperty("stepColor", "green")
        step_badge.setFixedSize(24, 24)
        step_badge.setAlignment(Qt.AlignCenter)
        title_lbl = QLabel("DISPOSITIVI")
        title_lbl.setObjectName("panelColumnTitle")
        header_row.addWidget(step_badge)
        header_row.addWidget(title_lbl)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Placeholder colonna bloccata
        self.device_placeholder = QLabel("← Seleziona prima una destinazione")
        self.device_placeholder.setObjectName("columnPlaceholder")
        self.device_placeholder.setAlignment(Qt.AlignCenter)
        self.device_placeholder.hide()
        layout.addWidget(self.device_placeholder)
        
        # Barra di ricerca dispositivi con pulsante aggiungi
        search_layout = QHBoxLayout()
        search_layout.setAlignment(Qt.AlignVCenter)
        search_layout.setSpacing(6)
        self.device_search = QLineEdit()
        self.device_search.setPlaceholderText("Cerca dispositivo, matricola o inventario")
        self.device_search.setFixedHeight(36)
        self.device_search.textChanged.connect(self.filter_devices)
        self.device_search.textChanged.connect(lambda *_: self._persist_main_view_state())
        search_layout.addWidget(self.device_search, 1)

        # Pulsante aggiungi dispositivo
        self.add_device_button = QPushButton(get_icon("add", theme=self.current_theme), "")
        self.add_device_button.setObjectName("addButton")
        self.add_device_button.setProperty("homeIconButton", True)
        self.add_device_button.setProperty("iconRole", "add")
        self.add_device_button.setToolTip("Aggiungi nuovo dispositivo")
        self._prepare_home_icon_button(self.add_device_button, size=36, icon_size=16)
        self.add_device_button.clicked.connect(self.quick_add_device)
        search_layout.addWidget(self.add_device_button, 0, Qt.AlignVCenter)

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
        self.device_verification_filter_combo.currentIndexChanged.connect(lambda *_: self._persist_main_view_state())

        self.device_period_button = QPushButton(get_icon("calendar", theme=self.current_theme), "")
        self.device_period_button.setObjectName("calendarFilterButton")
        self.device_period_button.setProperty("homeIconButton", True)
        self.device_period_button.setProperty("iconRole", "calendar")
        self._prepare_home_icon_button(self.device_period_button, size=40, icon_size=18)
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
        """
        Barra contestuale sticky: breadcrumb flusso + dettagli dispositivo
        + profili + pulsanti azione sempre visibili.
        Layout:
          ┌─ BREADCRUMB (cliente → destinazione → dispositivo) ─── [🔧 Sessione] ─┐
          │  dettagli dispositivo  │  profili  │  pulsanti azione                  │
          └────────────────────────────────────────────────────────────────────────┘
        """
        panel = QFrame()
        panel.setObjectName("stickyActionBar")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── RIGA 1: BREADCRUMB + INDICATORE SESSIONE ─────────────────────────────
        breadcrumb_bar = QFrame()
        breadcrumb_bar.setObjectName("flowBreadcrumbBar")
        bc_layout = QHBoxLayout(breadcrumb_bar)
        bc_layout.setContentsMargins(14, 8, 14, 8)
        bc_layout.setSpacing(4)

        def _make_step(obj_name: str, text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName(obj_name)
            lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            return lbl

        def _make_arrow() -> QLabel:
            arr = QLabel("›")
            arr.setObjectName("breadcrumbArrow")
            arr.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
            return arr

        self.bc_customer_label  = _make_step("breadcrumbStep", "① Cliente")
        self.bc_dest_label      = _make_step("breadcrumbStep", "② Destinazione")
        self.bc_device_label    = _make_step("breadcrumbStep", "③ Dispositivo")

        bc_layout.addWidget(self.bc_customer_label)
        bc_layout.addWidget(_make_arrow())
        bc_layout.addWidget(self.bc_dest_label)
        bc_layout.addWidget(_make_arrow())
        bc_layout.addWidget(self.bc_device_label)
        bc_layout.addStretch()

        # Indicatore sessione compatto integrato nella barra
        self.session_status_label = QLabel()
        self.session_status_label.setObjectName("sessionStatusBadge")
        self.session_status_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        bc_layout.addWidget(self.session_status_label)

        outer.addWidget(breadcrumb_bar)

        # Separatore
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("sectionDivider")
        outer.addWidget(sep)

        # ── RIGA 2: DETTAGLI + PROFILI + AZIONI ──────────────────────────────────
        summary_frame = QFrame()
        summary_frame.setObjectName("summaryFrame")
        summary_layout = QGridLayout(summary_frame)
        summary_layout.setHorizontalSpacing(12)
        summary_layout.setVerticalSpacing(4)
        summary_layout.setContentsMargins(12, 10, 12, 10)

        def add_caption(text: str, row: int, col: int):
            lbl = QLabel(text)
            lbl.setObjectName("summaryCaptionLabel")
            summary_layout.addWidget(lbl, row, col)

        # Col 0-3: dettagli dispositivo (compatti su 2 righe)
        add_caption("Dispositivo", 0, 0)
        self.summary_device_label = QLabel("<i>Nessuna selezione</i>")
        self.summary_device_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_device_label, 0, 1)

        add_caption("S/N", 0, 2)
        self.summary_serial_label = QLabel("—")
        self.summary_serial_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_serial_label, 0, 3)

        add_caption("Costruttore", 1, 0)
        self.summary_manufacturer_label = QLabel("—")
        self.summary_manufacturer_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_manufacturer_label, 1, 1)

        add_caption("Modello", 1, 2)
        self.summary_model_label = QLabel("—")
        self.summary_model_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_model_label, 1, 3)

        add_caption("Inv. Cliente", 2, 0)
        self.summary_customer_inventory_label = QLabel("—")
        self.summary_customer_inventory_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_customer_inventory_label, 2, 1)

        add_caption("Inv. AMS", 2, 2)
        self.summary_ams_inventory_label = QLabel("—")
        self.summary_ams_inventory_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_ams_inventory_label, 2, 3)

        add_caption("Reparto", 3, 0)
        self.summary_department_label = QLabel("—")
        self.summary_department_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_department_label, 3, 1)

        add_caption("Destinazione", 3, 2)
        self.summary_destination_label = QLabel("—")
        self.summary_destination_label.setObjectName("summaryLabel")
        summary_layout.addWidget(self.summary_destination_label, 3, 3)

        # Separatore verticale tra dettagli e profili+azioni
        v_sep = QFrame()
        v_sep.setFrameShape(QFrame.VLine)
        v_sep.setObjectName("sectionDivider")
        summary_layout.addWidget(v_sep, 0, 4, 5, 1)

        # Col 5-6: profili
        add_caption("Profilo elettrico", 0, 5)
        self.profile_selector = QComboBox()
        self.profile_selector.setMinimumHeight(32)
        self.profile_selector.setAutoFillBackground(False)
        self._update_summary_fields_background()
        summary_layout.addWidget(self.profile_selector, 1, 5, 1, 2)

        add_caption("Profilo funzionale", 2, 5)
        self.functional_profile_selector = QComboBox()
        self.functional_profile_selector.setMinimumHeight(32)
        self.functional_profile_selector.setAutoFillBackground(False)
        summary_layout.addWidget(self.functional_profile_selector, 3, 5, 1, 2)

        QTimer.singleShot(100, self._update_summary_fields_background)

        # Separatore verticale
        v_sep2 = QFrame()
        v_sep2.setFrameShape(QFrame.VLine)
        v_sep2.setObjectName("sectionDivider")
        summary_layout.addWidget(v_sep2, 0, 7, 5, 1)

        # Col 8: pulsanti azione in verticale (sempre visibili, disabilitati se non pronti)
        action_col = QVBoxLayout()
        action_col.setSpacing(6)

        self.btn_edit_device = QPushButton(get_icon("edit", theme=self.current_theme), " Modifica")
        self.btn_edit_device.setObjectName("editButton")
        self.btn_edit_device.setProperty("summaryRole", "neutral")
        self.btn_edit_device.setMinimumHeight(40)
        self.btn_edit_device.setEnabled(False)
        self.btn_edit_device.clicked.connect(self.on_edit_selected_device_new)
        action_col.addWidget(self.btn_edit_device)


        self.start_electrical_button = QPushButton(get_icon("electrical_verify", theme=self.current_theme), " Verifica Elettrica ▼")
        self.start_electrical_button.setObjectName("secondaryButton")
        self.start_electrical_button.setProperty("summaryRole", "electrical")
        self.start_electrical_button.setMinimumHeight(40)
        self.start_electrical_button.setEnabled(False)
        self.start_electrical_button.setToolTip("Avvia una verifica elettrica (manuale, automatica o di sistema)")

        self._electrical_menu = QMenu(self)
        self._electrical_menu.addAction(
            get_icon("edit", theme=self.current_theme), "Verifica Manuale",
            lambda: self.start_verification(manual_mode=True)
        ).setToolTip("Inserisci manualmente i valori misurati")
        self._electrical_menu.addAction(
            get_icon("device", theme=self.current_theme), "Verifica Automatica",
            lambda: self.start_verification(manual_mode=False)
        ).setToolTip("Avvia sequenza automatica di test con lo strumento")
        self._electrical_menu.addSeparator()
        self._electrical_menu.addAction(
            get_icon("instrument", theme=self.current_theme), "Verifica di Sistema",
            self.start_system_verification
        ).setToolTip("Verifica più dispositivi insieme come sistema (CEI 62353)")
        self.start_electrical_button.setMenu(self._electrical_menu)
        action_col.addWidget(self.start_electrical_button)

        self.start_functional_button = QPushButton(get_icon("functional_verify", theme=self.current_theme), " Verifica Funzionale")
        self.start_functional_button.setObjectName("secondaryButton")
        self.start_functional_button.setProperty("summaryRole", "functional")
        self.start_functional_button.setMinimumHeight(40)
        self.start_functional_button.setEnabled(False)
        self.start_functional_button.setToolTip("Avvia il flusso guidato della verifica funzionale")
        self.start_functional_button.clicked.connect(self.start_functional_verification)
        action_col.addWidget(self.start_functional_button)

        summary_layout.addLayout(action_col, 0, 8, 5, 1)

        summary_layout.setColumnStretch(1, 2)
        summary_layout.setColumnStretch(3, 2)
        summary_layout.setColumnStretch(5, 2)
        summary_layout.setColumnStretch(6, 1)
        summary_layout.setColumnStretch(8, 2)

        outer.addWidget(summary_frame)
        return panel
    
    def create_device_details_panel(self):
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
        self.btn_edit_device.clicked.connect(self.on_edit_selected_device_new)
        box_layout.addWidget(self.btn_edit_device)
        
        self.on_device_selection_changed(self.device_selector.currentIndex())

    def _create_session_group(self):
        """Crea il gruppo sessione con design moderno."""
        user_info = auth_manager.get_current_user_info()
        self.current_technician_name = user_info.get('full_name')
        
        group = QGroupBox("👤 Sessione di Verifica")
        layout = QVBoxLayout(group)
        layout.setSpacing(12)
        
        # Label tecnico nascosta (usata internamente, non mostrata)
        self.current_technician_label = QLabel(self.current_technician_name or "N/D")
        self.current_technician_label.hide()

        # Info strumento
        instr_layout = QHBoxLayout()
        instr_icon = QLabel()
        instr_icon.setPixmap(get_pixmap("instrument", color="#16a34a", size=24))
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
        self.change_session_btn = QPushButton(get_icon("settings", theme=self.current_theme), " Imposta Sessione")
        self.change_session_btn.setObjectName("warningButton") 
        self.change_session_btn.setMinimumHeight(45)
        self.change_session_btn.clicked.connect(self.setup_session)
        layout.addWidget(self.change_session_btn)
        
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
                self._update_guided_flow_ui()
            else:
                QMessageBox.warning(self, "Dati Mancanti", "Selezionare uno strumento valido.")

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
        self.device_count_label.setText("<i>Seleziona una destinazione</i>")

        # Torna allo step clienti nel drill-down
        self._drill_goto(0)
        self._update_guided_flow_ui()
    
    def on_customer_selected(self, item):
        """Gestisce la selezione di un cliente."""
        self.selected_customer_id = item.data(Qt.UserRole)
        self._drill_customer_name = item.data(Qt.UserRole + 2) or item.data(Qt.UserRole + 1) or None
        self.selected_destination_id = None
        self._drill_destination_name = None
        self.selected_device_id = None
        self._drill_device_name = None
        
        # Ricarica destinazioni per questo cliente
        self.load_destinations_for_customer(self.selected_customer_id)
        self.device_list.clear()
        
        self.update_summary_panel()
        self._persist_main_view_state()
        self._update_guided_flow_ui()
    
    def on_destination_selected_new(self, item):
        """Gestisce la selezione di una destinazione."""
        self.selected_destination_id = item.data(Qt.UserRole)
        self._drill_destination_name = item.data(Qt.UserRole + 2) or item.data(Qt.UserRole + 1) or None
        self.selected_device_id = None
        self._drill_device_name = None
        
        # Ricarica dispositivi per questa destinazione
        self.reload_devices(reset_search=True)
        
        self.update_summary_panel()
        self._persist_main_view_state()
        self._update_guided_flow_ui()
    
    def _select_device_by_id(self, device_id):
        """Seleziona un dispositivo per ID nella lista."""
        if not device_id:
            return
        
        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            if item.data(Qt.UserRole) == device_id:
                self.device_list.setCurrentItem(item)
                self.on_device_selected_new(item)
                self.device_list.scrollToItem(item)
                break
    
    def on_device_selected_new(self, item):
        """Gestisce la selezione di un dispositivo."""
        self.selected_device_id = item.data(Qt.UserRole)
        
        # Salva subito il nome per il breadcrumb (prima di qualsiasi segnale che possa resettare)
        self._drill_device_name = None
        device_data = services.database.get_device_by_id(self.selected_device_id)
        if device_data:
            dev = dict(device_data)
            self._drill_device_name = dev.get('description') or None
            default_profile_key = dev.get('default_profile_key')
            if default_profile_key:
                index = self.profile_selector.findData(default_profile_key)
                if index != -1:
                    self.profile_selector.setCurrentIndex(index)
                else:
                    self.profile_selector.setCurrentIndex(0)
            else:
                self.profile_selector.setCurrentIndex(0)

            default_func_key = dev.get('default_functional_profile_key')
            if default_func_key:
                func_index = self.functional_profile_selector.findData(default_func_key)
                if func_index != -1:
                    self.functional_profile_selector.setCurrentIndex(func_index)
                else:
                    self.functional_profile_selector.setCurrentIndex(0)
            else:
                self.functional_profile_selector.setCurrentIndex(0)
        
        self.update_summary_panel()
        
        # Abilita pulsanti azione
        self.btn_edit_device.setEnabled(True)
        self.start_electrical_button.setEnabled(True)
        self.start_functional_button.setEnabled(self.functional_profile_selector.count() > 0)
        self._persist_main_view_state()
        self._update_guided_flow_ui()
        QTimer.singleShot(0, self._update_drill_breadcrumb)
        QTimer.singleShot(0, self._update_drill_breadcrumb)
    
    def filter_customers(self, text):
        """Filtra i clienti in base al testo di ricerca."""
        text = text.lower()
        for i in range(self.customer_list.count()):
            item = self.customer_list.item(i)
            search_text = item.data(Qt.UserRole + 1) or item.text().lower()
            item.setHidden(text not in search_text)
    
    def filter_destinations(self, text):
        """Filtra le destinazioni in base al testo di ricerca."""
        text = text.lower()
        for i in range(self.destination_list.count()):
            item = self.destination_list.item(i)
            search_text = item.data(Qt.UserRole + 1) or item.text().lower()
            item.setHidden(text not in search_text)
    
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
        self.start_electrical_button.setEnabled(False)
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
                try:
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
                except services.DuplicateActiveSerialException as e:
                    existing = e.existing_device
                    dest_info = services.database.get_destination_by_id(existing.get('destination_id')) if existing.get('destination_id') else None
                    dest_name = dict(dest_info).get('name', 'N/D') if dest_info else 'N/D'
                    msg = (
                        f"Il numero di serie <b>{e.serial_number}</b> è già presente nel database:\n\n"
                        f"• Dispositivo: {existing.get('description', 'N/D')}\n"
                        f"• Costruttore: {existing.get('manufacturer', 'N/D')}\n"
                        f"• Modello: {existing.get('model', 'N/D')}\n"
                        f"• Destinazione: {dest_name}\n\n"
                        f"Vuoi salvare comunque le modifiche mantenendo questo numero di serie duplicato?"
                    )
                    reply = QMessageBox.question(self, "Numero di Serie Duplicato", msg,
                                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if reply != QMessageBox.Yes:
                        return
                    try:
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
                            force_duplicate_serial=True,
                        )
                    except Exception as ex:
                        QMessageBox.critical(self, "Errore", f"Modifica non riuscita:\n{ex}")
                        return
                
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
                self.show_success_feedback("Dispositivo aggiornato con successo.")
        
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
        self._persist_main_view_state()

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

        # Dispositivi segnati come "non messo a disposizione" nel periodo:
        # vengono esclusi da tutti i filtri (trattati come già gestiti).
        try:
            unavail_reports = services.get_unavailability_reports_for_period(
                destination_id, start_date_str, end_date_str
            )
            unavail_ids = {r.get('device_id') for r in unavail_reports if r.get('device_id') is not None}
        except Exception:
            unavail_ids = set()

        filtered = []
        for dev_row in all_devices:
            dev = dict(dev_row)
            dev_id = dev.get('id')

            # Dispositivi non disponibili: escludi sempre dai filtri "da verificare"
            if dev_id in unavail_ids:
                continue

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
        """Popola la lista dispositivi con item ricchi a più righe."""
        self.device_list.clear()

        if not self.selected_destination_id:
            self.device_count_label.setText("<i>Seleziona una destinazione</i>")
            return

        current_selected_id = self.selected_device_id
        filtered_devices = [dev for dev in devices if self._device_matches_query(dev, search_query)]

        selected_item = None
        for dev in filtered_devices:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, dev.get('id'))
            item.setSizeHint(QSize(0, 96))
            self.device_list.addItem(item)
            widget = self._make_device_row_widget(dev, item)
            self.device_list.setItemWidget(item, widget)
            if current_selected_id and dev.get('id') == current_selected_id:
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
        # Aggiorna contatore breadcrumb
        if hasattr(self, "drill_count_label") and getattr(self, "_drill_step", 0) == 2:
            self.drill_count_label.setText(f"{visible_count} dispositivi")

    def _make_device_row_widget(self, dev: dict, list_item=None) -> QWidget:
        """Crea un widget ricco a 3 righe per un item della lista dispositivi."""
        container = QWidget()
        container.setObjectName("deviceRowWidget")
        # Non usiamo WA_TransparentForMouseEvents sul container così i pulsanti
        # interni possono ricevere i click; forwardiamo manualmente i click
        # sul container (non su un pulsante) alla selezione dell'item.
        if list_item is not None:
            def _container_press(ev, _item=list_item):
                from PySide6.QtCore import QEvent
                # Forwardare il click alla lista solo se non intercettato da un figlio
                # (i figli con un proprio handler lo consumano prima)
                self.device_list.setCurrentItem(_item)
                self.on_device_selected_new(_item)
            container.mousePressEvent = _container_press

        lay = QVBoxLayout(container)
        lay.setContentsMargins(14, 10, 6, 10)
        lay.setSpacing(4)

        description = (dev.get('description') or 'Dispositivo senza nome').upper()
        manufacturer = dev.get('manufacturer') or '—'
        model = dev.get('model') or '—'
        serial = dev.get('serial_number') or '—'
        ams_inv = dev.get('ams_inventory') or '—'
        cust_inv = dev.get('customer_inventory') or '—'
        department = dev.get('department') or ''
        status = dev.get('status', 'active')

        # ── Riga 1: Descrizione + badge stato + pulsante non disponibile ─────
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        desc_lbl = QLabel(description)
        desc_lbl.setObjectName("deviceRowTitle")
        desc_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row1.addWidget(desc_lbl, 1)

        if status == 'inactive':
            badge = QLabel("DISMESSO")
            badge.setObjectName("deviceStatusBadge")
            badge.setProperty("badgeType", "inactive")
            badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            row1.addWidget(badge)

        if department:
            dept_badge = QLabel(department)
            dept_badge.setObjectName("deviceDeptBadge")
            dept_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            row1.addWidget(dept_badge)

        # Pulsante "Non messo a disposizione"
        unavail_btn = QPushButton("🚫")
        unavail_btn.setToolTip("Segna come non messo a disposizione")
        unavail_btn.setFixedSize(26, 26)
        unavail_btn.setStyleSheet(
            "QPushButton { background: #ede9fe; color: #7c3aed; border: 1px solid #c4b5fd;"
            " border-radius: 5px; font-size: 12px; padding: 0; }"
            " QPushButton:hover { background: #ddd6fe; }"
        )
        device_id = dev.get('id')
        unavail_btn.clicked.connect(lambda _checked=False, did=device_id: self.mark_device_unavailable(did))
        row1.addWidget(unavail_btn)

        lay.addLayout(row1)

        # ── Riga 2: Marca / Modello / S/N ────────────────────────────────────
        row2_parts = []
        if manufacturer and manufacturer != '—':
            row2_parts.append(f"<b>{manufacturer}</b>")
        if model and model != '—':
            row2_parts.append(model)
        if serial and serial != '—':
            row2_parts.append(f"S/N&nbsp;<b>{serial}</b>")

        if row2_parts:
            row2_lbl = QLabel("  ·  ".join(row2_parts))
            row2_lbl.setObjectName("deviceRowSub")
            row2_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lay.addWidget(row2_lbl)

        # ── Riga 3: Inventari come badge colorati ────────────────────────────
        row3 = QHBoxLayout()
        row3.setSpacing(6)
        row3.setContentsMargins(0, 0, 0, 0)
        has_inv = False

        if ams_inv and ams_inv != '—':
            ams_badge = QLabel(f"AMS · {ams_inv}")
            ams_badge.setObjectName("deviceInvBadge")
            ams_badge.setProperty("invType", "ams")
            ams_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            row3.addWidget(ams_badge)
            has_inv = True

        if cust_inv and cust_inv != '—':
            cust_badge = QLabel(f"Cliente · {cust_inv}")
            cust_badge.setObjectName("deviceInvBadge")
            cust_badge.setProperty("invType", "customer")
            cust_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            row3.addWidget(cust_badge)
            has_inv = True

        if has_inv:
            row3.addStretch()
            lay.addLayout(row3)
        elif not row2_parts:
            lay.addStretch()

        return container

    def _make_customer_row_widget(self, cust: dict) -> QWidget:
        """Crea un widget ricco a 2 righe per un item della lista clienti."""
        container = QWidget()
        container.setObjectName("customerRowWidget")
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)
        name = (cust.get('name') or 'Cliente senza nome').upper()
        address = cust.get('address') or ''
        phone = cust.get('phone') or ''
        dest_count = cust.get('destination_count', 0) or 0
        dev_count = cust.get('device_count', 0) or 0

        # Riga 1: Nome + badge destinazioni
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("customerRowTitle")
        name_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row1.addWidget(name_lbl, 1)

        dest_badge = QLabel(f"📍 {dest_count} dest.")
        dest_badge.setObjectName("customerCountBadge")
        dest_badge.setProperty("badgeType", "dest")
        dest_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row1.addWidget(dest_badge)

        dev_badge = QLabel(f"🔧 {dev_count} dis.")
        dev_badge.setObjectName("customerCountBadge")
        dev_badge.setProperty("badgeType", "dev")
        dev_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row1.addWidget(dev_badge)
        lay.addLayout(row1)

        # Riga 2: Indirizzo / Telefono
        sub_parts = []
        if address:
            sub_parts.append(address)
        if phone:
            sub_parts.append(f"☎ {phone}")
        if sub_parts:
            sub_lbl = QLabel("  ·  ".join(sub_parts))
            sub_lbl.setObjectName("customerRowSub")
            sub_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lay.addWidget(sub_lbl)
        else:
            lay.addStretch()

        return container

    def _make_destination_row_widget(self, dest: dict) -> QWidget:
        """Crea un widget ricco a 2 righe per un item della lista destinazioni."""
        container = QWidget()
        container.setObjectName("destinationRowWidget")
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)
        name = (dest.get('name') or 'Destinazione senza nome').upper()
        address = dest.get('address') or ''
        dev_count = dest.get('device_count', 0) or 0

        # Riga 1: Nome + badge dispositivi
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("destinationRowTitle")
        name_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row1.addWidget(name_lbl, 1)

        dev_badge = QLabel(f"🔧 {dev_count} dispositivi")
        dev_badge.setObjectName("destinationCountBadge")
        dev_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row1.addWidget(dev_badge)
        lay.addLayout(row1)

        # Riga 2: Indirizzo
        if address:
            sub_lbl = QLabel(address)
            sub_lbl.setObjectName("destinationRowSub")
            sub_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lay.addWidget(sub_lbl)
        else:
            lay.addStretch()

        return container

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
        """Carica le destinazioni per un cliente specifico con widget ricchi."""
        self.destination_list.clear()
        self.destination_search.clear()

        if not customer_id:
            self.destination_count_label.setText("<i>Seleziona un cliente</i>")
            return

        destinations = services.get_destinations_with_device_count_for_customer(customer_id)

        for dest_row in destinations:
            dest = dict(dest_row)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, dest.get('id'))
            item.setData(Qt.UserRole + 1, (dest.get('name') or '').lower())
            item.setData(Qt.UserRole + 2, dest.get('name') or '')
            has_sub = bool(dest.get('address'))
            item.setSizeHint(QSize(0, 74 if has_sub else 54))
            self.destination_list.addItem(item)
            widget = self._make_destination_row_widget(dest)
            self.destination_list.setItemWidget(item, widget)

        dest_count = len(destinations)
        self.destination_count_label.setText(f"<span style='font-weight: bold;'>{dest_count} destinazioni</span>")
        
    def load_all_data(self):
        """Carica tutti i dati iniziali."""
        self.load_customers()
        self.load_profiles()
        self.load_functional_profiles()
        self.load_control_panel_data()
    
    def load_customers(self):
        """Carica tutti i clienti nella lista con widget ricchi."""
        self.customer_list.clear()
        self.customer_search.clear()

        customers = services.get_all_customers_with_counts()

        for customer_row in customers:
            cust = dict(customer_row)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, cust.get('id'))
            # Testo per la ricerca (non visibile ma usato da filter_customers)
            item.setData(Qt.UserRole + 1, (cust.get('name') or '').lower())
            item.setData(Qt.UserRole + 2, cust.get('name') or '')
            has_sub = bool(cust.get('address') or cust.get('phone'))
            item.setSizeHint(QSize(0, 76 if has_sub else 54))
            self.customer_list.addItem(item)
            widget = self._make_customer_row_widget(cust)
            self.customer_list.setItemWidget(item, widget)

        customer_count = len(customers)
        self.customer_count_label.setText(f"<span style='font-weight: bold;'>{customer_count} clienti</span>")

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
        """Ricarica i dati - il control panel è stato rimosso, metodo mantenuto per compatibilità."""
        pass

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

    # ========== VERIFICHE DI SISTEMA (CEI 62353) ==========

    def start_system_verification(self):
        """
        Avvia il flusso per una verifica di sistema.
        1. Selezione dispositivi
        2. Ispezione visiva
        3. Test runner (come verifica singola, ma il report mostra tutti i dispositivi)
        4. Salvataggio come verifica di sistema
        """
        if not self.current_mti_info or not self.current_technician_name:
            QMessageBox.warning(
                self, "Sessione non Impostata",
                "Impostare strumento e tecnico prima di avviare una verifica di sistema."
            )
            return

        if not self.selected_destination_id:
            QMessageBox.warning(
                self, "Attenzione",
                "Selezionare una destinazione prima di avviare una verifica di sistema."
            )
            return

        # Recupera il nome della destinazione
        dest_row = services.database.get_destination_by_id(self.selected_destination_id)
        dest_name = dict(dest_row).get('name', '') if dest_row else ''

        # 1. Dialog di selezione dispositivi
        selection_dialog = SystemDeviceSelectionDialog(
            self.selected_destination_id,
            dest_name,
            preselected_device_id=self.selected_device_id,
            parent=self,
        )
        if selection_dialog.exec() != QDialog.Accepted:
            return

        device_ids = selection_dialog.get_selected_device_ids()
        devices_info = selection_dialog.get_selected_devices_info()
        system_name = selection_dialog.get_system_name()
        profile_key = selection_dialog.get_selected_profile_key()

        if len(device_ids) < 2:
            QMessageBox.warning(self, "Attenzione", "Selezionare almeno 2 dispositivi.")
            return

        # Verifica profilo selezionato
        if not profile_key:
            QMessageBox.warning(self, "Attenzione", "Selezionare un profilo di verifica.")
            return

        selected_profile = config.PROFILES.get(profile_key)
        if not selected_profile:
            QMessageBox.warning(self, "Attenzione", "Profilo di verifica non trovato.")
            return

        # 3. Ispezione visiva del sistema
        from app.ui.dialogs import VisualInspectionDialog
        inspection_dialog = VisualInspectionDialog(self)
        inspection_dialog.setWindowTitle("Ispezione Visiva del Sistema")
        if inspection_dialog.exec() != QDialog.Accepted:
            return
        visual_inspection_data = inspection_dialog.get_data()

        # 4. Avvia il test runner in modalità sistema
        if self.test_runner_widget:
            self.test_runner_widget.deleteLater()

        destination_info = dict(services.database.get_destination_by_id(self.selected_destination_id))
        customer_info = dict(services.database.get_customer_by_id(destination_info['customer_id']))
        report_settings = {"logo_path": self.logo_path}
        current_user = auth_manager.get_current_user_info()

        # Combiniamo tutte le applied parts dei dispositivi del sistema
        all_applied_parts = []
        for dev in devices_info:
            parts = dev.get('applied_parts', [])
            if isinstance(parts, str):
                try:
                    parts = json.loads(parts)
                except Exception:
                    parts = []
            all_applied_parts.extend(parts)

        # Creiamo un device_info "sistema" che combina le info
        system_device_info = {
            'id': None,  # Non è un singolo dispositivo
            'description': system_name or "Sistema",
            'serial_number': f"{len(device_ids)} dispositivi",
            'manufacturer': '',
            'model': '',
            'department': '',
            'customer_inventory': '',
            'ams_inventory': '',
            'applied_parts': all_applied_parts,
            'destination_id': self.selected_destination_id,
        }

        # Creiamo il TestRunnerWidget in modalità manuale per il sistema
        self.test_runner_widget = TestRunnerWidget(
            system_device_info, customer_info, self.current_mti_info, report_settings,
            profile_key, visual_inspection_data,
            current_user.get('full_name'),
            current_user.get('username'),
            True,  # manual_mode
            self,
        )

        def save_system_verification():
            self.statusBar().showMessage("Salvataggio verifica di sistema in corso...")
            try:
                verification_code, new_id = services.finalizza_e_salva_verifica_sistema(
                    system_name=system_name,
                    destination_id=self.selected_destination_id,
                    profile_name=profile_key,
                    results=self.test_runner_widget.results,
                    visual_inspection_data=visual_inspection_data,
                    mti_info=self.current_mti_info,
                    technician_name=current_user.get('full_name'),
                    technician_username=current_user.get('username'),
                    device_ids=device_ids,
                    device_infos=devices_info,
                )
                self.test_runner_widget.saved_verification_id = new_id
                self.test_runner_widget.save_db_button.setEnabled(False)
                self.test_runner_widget.save_db_button.setText("Verifica di Sistema Salvata!")
                self.test_runner_widget.generate_pdf_button.setEnabled(True)
                self.test_runner_widget.print_pdf_button.setEnabled(True)
                self.test_runner_widget.finish_button.setEnabled(True)

                # Override generate PDF e stampa per usare il report di sistema
                self.test_runner_widget.generate_pdf_report_from_summary = \
                    lambda: self._generate_system_pdf_from_runner(new_id, system_name)
                self.test_runner_widget.print_pdf_report_from_summary = \
                    lambda: self._print_system_pdf_from_runner(new_id)

                self.statusBar().showMessage(
                    f"Verifica di sistema ID {new_id} salvata (Codice: {verification_code}).",
                    5000,
                )
                return True
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile salvare la verifica di sistema: {e}")
                logging.error(f"Errore salvataggio verifica di sistema: {e}", exc_info=True)
                self.statusBar().showMessage("Salvataggio fallito.", 5000)
                return False

        self.test_runner_widget.save_verification_to_db = save_system_verification

        self.test_runner_layout.addWidget(self.test_runner_widget)
        self.set_selection_enabled(False)

    def _generate_system_pdf_from_runner(self, sv_id, system_name):
        """Genera il PDF dal test runner per una verifica di sistema."""
        safe_name = re.sub(r'[\\/*?:"<>|]', '_', system_name or 'Sistema')
        default_filename = os.path.join(os.getcwd(), f"{safe_name}_VS.pdf")
        filename, _ = QFileDialog.getSaveFileName(
            self, "Salva Report Verifica di Sistema", default_filename, "PDF Files (*.pdf)"
        )
        if not filename:
            return
        try:
            report_settings = {"logo_path": self.logo_path}
            services.generate_system_pdf_report(filename, sv_id, report_settings)
            QMessageBox.information(self, "Successo", f"Report generato con successo:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile generare il report:\n{e}")
            logging.error(f"Errore generazione report di sistema: {e}", exc_info=True)

    def _print_system_pdf_from_runner(self, sv_id):
        """Stampa il report di una verifica di sistema dal test runner."""
        try:
            report_settings = {"logo_path": self.logo_path}
            services.print_system_pdf_report(sv_id, report_settings, parent_widget=self)
        except Exception as e:
            QMessageBox.critical(self, "Errore di Stampa", f"Impossibile stampare il report:\n{e}")
            logging.error(f"Errore stampa report di sistema: {e}", exc_info=True)

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
            if hasattr(self, "left_panel_widget"):
                self.left_panel_widget.show()
            if hasattr(self, "selection_scroll_area"):
                self.selection_scroll_area.show()
                self.selection_scroll_area.verticalScrollBar().setValue(0)
            if hasattr(self, "drill_stack"):
                self.drill_stack.show()
            if hasattr(self, "drill_breadcrumb_bar"):
                self.drill_breadcrumb_bar.show()
            if hasattr(self, "bottom_action_panel"):
                self.bottom_action_panel.show()
            self.test_runner_container.hide()
        else:
            if hasattr(self, "left_panel_widget"):
                self.left_panel_widget.hide()
            if hasattr(self, "selection_scroll_area"):
                self.selection_scroll_area.hide()
            if hasattr(self, "drill_stack"):
                self.drill_stack.hide()
            if hasattr(self, "drill_breadcrumb_bar"):
                self.drill_breadcrumb_bar.hide()
            if hasattr(self, "bottom_action_panel"):
                self.bottom_action_panel.hide()
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
                    self.reload_devices()
                    # Seleziona il dispositivo appena creato
                    self._select_device_by_id(new_device_id)
                self.update_summary_panel()
            except services.DuplicateActiveSerialException as e:
                # Numero di serie già usato da un dispositivo ATTIVO
                existing = e.existing_device
                dest_info = services.database.get_destination_by_id(existing.get('destination_id')) if existing.get('destination_id') else None
                dest_name = dict(dest_info).get('name', 'N/D') if dest_info else 'N/D'
                msg = (
                    f"Il numero di serie <b>{e.serial_number}</b> è già presente nel database:\n\n"
                    f"• Dispositivo: {existing.get('description', 'N/D')}\n"
                    f"• Costruttore: {existing.get('manufacturer', 'N/D')}\n"
                    f"• Modello: {existing.get('model', 'N/D')}\n"
                    f"• Destinazione: {dest_name}\n\n"
                    f"Vuoi inserire comunque il nuovo dispositivo con lo stesso numero di serie?"
                )
                reply = QMessageBox.question(self, "Numero di Serie Duplicato", msg,
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply == QMessageBox.Yes:
                    try:
                        new_device_id = services.add_device(**data, force_duplicate_serial=True)
                        self.reload_devices()
                        self._select_device_by_id(new_device_id)
                        self.update_summary_panel()
                    except Exception as ex:
                        QMessageBox.critical(self, "Errore", f"Impossibile creare il dispositivo:\n{ex}")
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
                                self.reload_devices()
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
                                self.reload_devices()
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
            services.force_full_push()
            self.run_synchronization(full_sync=False)
            self.show_success_feedback(
                "Tutti i dati locali sono stati marcati per la sincronizzazione. Sync avviata.",
                timeout_ms=7000,
            )
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
            self.show_success_feedback(f"Logo aziendale aggiornato: {filename}", timeout_ms=7000)

    def open_instrument_manager(self):
        dialog = InstrumentManagerDialog(self)
        self._show_embedded_dialog(dialog, "GESTIONE STRUMENTI DI MISURA")

    def closeEvent(self, event):
        # --- INIZIO MODIFICA: Controllo stato prima di chiudere ---
        if not self.state_manager.is_idle():
            QMessageBox.warning(self, "Operazione in Corso", "Attendi la fine della sincronizzazione o di altre operazioni prima di chiudere.")
            event.ignore()
            return
        # --- FINE MODIFICA ---
        self.settings.setValue("main_window/is_maximized", self.isMaximized())
        self.settings.setValue("geometry", self.saveGeometry())
        self._persist_main_view_state()
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
        if hasattr(self, 'new_assignment_action'):
            self.new_assignment_action.setVisible(not is_technician)

    def open_profile_manager(self):
        """Apre la finestra di dialogo per la gestione dei profili."""
        dialog = ProfileManagerDialog(self)

        def on_close():
            if dialog.profiles_changed:
                logging.info("I profili sono stati modificati. Ricaricamento in corso...")
                config.load_verification_profiles()
                self.load_profiles()
                self.load_functional_profiles()
                self.show_success_feedback("Profili elettrici aggiornati.")

        self._show_embedded_dialog(dialog, "GESTIONE PROFILI", on_close)

    def open_functional_profile_manager(self):
        """Apre la gestione dei profili funzionali."""
        dialog = FunctionalProfileManagerDialog(self)

        def on_close():
            if dialog.profiles_changed:
                logging.info("Profili funzionali aggiornati. Ricarico dati in memoria...")
                config.load_functional_profiles()
                self.load_functional_profiles()
                self.show_success_feedback("Profili funzionali aggiornati.")

        self._show_embedded_dialog(dialog, "GESTIONE PROFILI FUNZIONALI", on_close)

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
        self._update_button_icons(theme)
        
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
        """Aggiorna le icone del menu in base al tema (usa iconify con fallback a qtawesome)."""
        # Mappa azione → chiave simbolica di iconify_helper
        icon_updates = [
            ("export",            getattr(self, 'export_inventory_action', None)),
            ("report",            getattr(self, 'export_log_action', None)),
            ("search",            getattr(self, 'advanced_search_action', None)),
            ("report",            getattr(self, 'advanced_report_action', None)),
            ("logout",            getattr(self, 'logout_action', None)),
            ("sync",              getattr(self, 'full_sync_action', None)),
            ("import",            getattr(self, 'force_push_action', None)),
            ("restore",           getattr(self, 'ripristina_db_action', None)),
            ("magic",             getattr(self, 'correction_action', None)),
            ("duplicate",         getattr(self, 'duplicates_action', None)),
            ("quality",           getattr(self, 'data_quality_action', None)),
            ("chart",             getattr(self, 'stats_action', None)),
            ("history",           getattr(self, 'audit_log_action', None)),
            ("com_port",          getattr(self, 'set_com_port_action', None)),
            ("instrument",        getattr(self, 'manage_instruments_action', None)),
            ("logo",              getattr(self, 'set_logo_action', None)),
            ("users",             getattr(self, 'manage_users_action', None)),
            ("report",            getattr(self, 'manage_profiles_action', None)),
            ("functional_verify", getattr(self, 'manage_functional_profiles_action', None)),
            ("edit",              getattr(self, 'manage_signature_action', None)),
            ("theme",             getattr(self, 'theme_action', None)),
            ("changelog",         getattr(self, 'changelog_action', None)),
            ("update",            getattr(self, 'update_action', None)),
            ("conflict",          getattr(self, 'view_conflicts_action', None)),
            ("password",          getattr(self, 'change_password_action', None)),
            ("trash",             getattr(self, 'deleted_data_action', None)),
            ("about",             getattr(self, 'about_action', None)),
            ("shortcuts",         getattr(self, 'shortcuts_help_action', None)),
        ]

        for icon_key, action in icon_updates:
            if action:
                try:
                    action.setIcon(get_icon(icon_key, theme=theme))
                except Exception as e:
                    logging.debug(f"Errore aggiornamento icona {icon_key}: {e}")

    def _update_button_icons(self, theme: str):
        """Aggiorna le icone dei pulsanti principali in base al tema corrente."""
        button_updates = [
            ("archive", getattr(self, "manage_button", None)),
            ("sync", getattr(self, "sync_button", None)),
            ("search", getattr(self, "global_search_button", None)),
            ("qr", getattr(self, "qr_scan_btn", None)),
            ("add", getattr(self, "add_device_button", None)),
            ("calendar", getattr(self, "device_period_button", None)),
            ("edit", getattr(self, "btn_edit_device", None)),
            ("electrical_verify", getattr(self, "start_electrical_button", None)),
            ("functional_verify", getattr(self, "start_functional_button", None)),
            ("settings", getattr(self, "change_session_btn", None)),
        ]

        for icon_key, button in button_updates:
            if button:
                try:
                    button.setIcon(get_icon(icon_key, theme=theme))
                except Exception as e:
                    logging.debug(f"Errore aggiornamento icona pulsante {icon_key}: {e}")

        if hasattr(self, "_electrical_menu"):
            actions = self._electrical_menu.actions()
            electrical_menu_icons = [
                ("edit", 0),
                ("device", 1),
                ("instrument", 3),
            ]
            for icon_key, index in electrical_menu_icons:
                if 0 <= index < len(actions):
                    try:
                        actions[index].setIcon(get_icon(icon_key, theme=theme))
                    except Exception as e:
                        logging.debug(f"Errore aggiornamento icona menu verifica elettrica {icon_key}: {e}")
    
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
        self._show_embedded_dialog(dialog, "GESTIONE FIRMA")

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
        self._show_embedded_dialog(dialog, "GESTIONE UTENTI")

    def open_change_password_dialog(self):
        from app.ui.dialogs.change_password_dialog import ChangePasswordDialog
        dialog = ChangePasswordDialog(self)
        if dialog.exec() == ChangePasswordDialog.Accepted:
            # Dopo il cambio password, esegui il logout automatico
            QMessageBox.information(self, "LOGOUT", "LA PASSWORD È STATA CAMBIATA.\nVERRAI DISCONNESSO PER EFFETTUARE IL LOGIN CON LA NUOVA PASSWORD.")
            auth_manager.logout()
            self.relogin_requested = True
            self.close()

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
        self.show_success_feedback(message, timeout_ms=7000)
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

            def on_close():
                self._update_conflict_indicator()

            self._show_embedded_dialog(dialog, "RISOLUZIONE CONFLITTI", on_close)
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
        # Ignora i serial_conflict: i duplicati di numero di serie sono ora permessi
        conflicts = [c for c in (conflicts or []) if c.get('reason') not in ('serial_conflict', 'duplicate_serial_number')]
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
        if navigate_to:
            dialog.navigate_on_load(navigate_to)

        def on_close():
            self.load_customers()
            self.load_control_panel_data()

        self._show_embedded_dialog(dialog, "GESTIONE ANAGRAFICHE", on_close)
    
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
        from app.ui.dialogs.qr_device_scanner_dialog import ThreadedQRServer, QRScannerHTTPHandler
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
        self.qr_scan_btn.setStyleSheet("")
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
                
                # Seleziona il dispositivo senza banner aggiuntivi:
                # il feedback viene gestito dal chiamante.
                self.select_device_from_search(device_dict, notify=False)
                
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
                
                # Seleziona il dispositivo e mostra un feedback non bloccante.
                self.select_device_from_search(device_dict, notify=False)
                self.show_inline_feedback(
                    "Dispositivo selezionato: "
                    f"{device_dict.get('description', 'N/D')} "
                    f"(S/N: {device_dict.get('serial_number', 'N/D')})",
                    level="success",
                )
                return
            else:
                self.show_inline_feedback(
                    f"Nessun dispositivo trovato per il codice '{code}'.",
                    level="warning",
                    timeout_ms=7000,
                )
                return
                
        except Exception as e:
            QApplication.restoreOverrideCursor()
            logging.error(f"Errore ricerca dispositivo: {e}", exc_info=True)
            self.show_inline_feedback(
                f"Errore durante la ricerca del dispositivo: {e}",
                level="error",
                timeout_ms=7000,
            )
    
    def perform_global_search(self):
        search_term = self.global_device_search_edit.text().strip()
        if len(search_term) < 3:
            self.show_inline_feedback(
                "Inserisci almeno 3 caratteri per avviare la ricerca.",
                level="warning",
            )
            self.global_device_search_edit.setFocus()
            return

        results = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            results = services.search_globally(search_term)
        except Exception as e:
            logging.error(f"Errore nella ricerca globale: {e}", exc_info=True)
            self.show_inline_feedback(
                f"Ricerca non riuscita: {e}",
                level="error",
                timeout_ms=7000,
            )
            return
        finally:
            QApplication.restoreOverrideCursor()

        if not results:
            self.show_inline_feedback(
                f"Nessun risultato trovato per '{search_term}'.",
                level="info",
            )
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

    def select_customer_from_search(self, customer_data: dict, notify: bool = True):
        """Seleziona un cliente dalla ricerca globale."""
        customer_id = customer_data.get('id')
        if not customer_id:
            self.show_inline_feedback(
                "Impossibile selezionare il cliente: dati mancanti.",
                level="warning",
                timeout_ms=7000,
            )
            return False

        customer_found = False
        for i in range(self.customer_list.count()):
            item = self.customer_list.item(i)
            if item.data(Qt.UserRole) == customer_id:
                self.customer_list.setCurrentItem(item)
                self.on_customer_selected(item)
                QApplication.processEvents()
                customer_found = True
                break

        if not customer_found:
            self.show_inline_feedback(
                "Cliente non presente nella lista corrente.",
                level="warning",
                timeout_ms=7000,
            )
            return False

        if notify:
            self.show_inline_feedback(
                f"Cliente selezionato: {customer_data.get('name', 'N/D')}",
                level="success",
            )
        return True

    def select_destination_from_search(self, destination_data: dict, notify: bool = True):
        """Seleziona una destinazione dalla ricerca globale usando il nuovo sistema a 3 colonne."""
        destination_id = destination_data.get('id')
        customer_id = destination_data.get('customer_id')

        if not destination_id or not customer_id:
            self.show_inline_feedback(
                "Impossibile selezionare la destinazione: dati mancanti.",
                level="warning",
                timeout_ms=7000,
            )
            return False

        # Seleziona il cliente
        customer_found = False
        for i in range(self.customer_list.count()):
            item = self.customer_list.item(i)
            if item.data(Qt.UserRole) == customer_id:
                self.customer_list.setCurrentItem(item)
                self.on_customer_selected(item)
                QApplication.processEvents()
                customer_found = True
                break

        if not customer_found:
            self.show_inline_feedback(
                "Cliente associato alla destinazione non presente nella lista corrente.",
                level="warning",
                timeout_ms=7000,
            )
            return False

        # Seleziona la destinazione
        destination_found = False
        for i in range(self.destination_list.count()):
            item = self.destination_list.item(i)
            if item.data(Qt.UserRole) == destination_id:
                self.destination_list.setCurrentItem(item)
                self.on_destination_selected_new(item)
                QApplication.processEvents()
                destination_found = True
                break

        if not destination_found:
            self.show_inline_feedback(
                "Destinazione non presente nella lista corrente.",
                level="warning",
                timeout_ms=7000,
            )
            return False

        if notify:
            self.show_inline_feedback(
                f"Destinazione selezionata: {destination_data.get('name', 'N/D')}",
                level="success",
            )
        return True

    def select_device_from_search(self, device_data: dict, notify: bool = True):
        """Seleziona un dispositivo dalla ricerca globale usando il nuovo sistema a 3 colonne."""
        destination_id = device_data.get('destination_id')
        device_id = device_data.get('id')

        if not destination_id or not device_id:
            self.show_inline_feedback(
                "Impossibile selezionare il dispositivo: dati mancanti.",
                level="warning",
                timeout_ms=7000,
            )
            return False

        dest_info = services.database.get_destination_by_id(destination_id)
        if not dest_info:
            self.show_inline_feedback(
                "Destinazione del dispositivo non trovata.",
                level="error",
                timeout_ms=7000,
            )
            return False

        customer_id = dict(dest_info).get('customer_id')

        # Seleziona il cliente
        customer_found = False
        for i in range(self.customer_list.count()):
            item = self.customer_list.item(i)
            if item.data(Qt.UserRole) == customer_id:
                self.customer_list.setCurrentItem(item)
                self.on_customer_selected(item)
                QApplication.processEvents()
                customer_found = True
                break

        if not customer_found:
            self.show_inline_feedback(
                "Cliente associato al dispositivo non presente nella lista corrente.",
                level="warning",
                timeout_ms=7000,
            )
            return False

        # Seleziona la destinazione
        destination_found = False
        for i in range(self.destination_list.count()):
            item = self.destination_list.item(i)
            if item.data(Qt.UserRole) == destination_id:
                self.destination_list.setCurrentItem(item)
                self.on_destination_selected_new(item)
                QApplication.processEvents()
                destination_found = True
                break

        if not destination_found:
            self.show_inline_feedback(
                "Destinazione non presente nella lista corrente.",
                level="warning",
                timeout_ms=7000,
            )
            return False

        # Seleziona il dispositivo
        device_found = False
        filter_was_reset = False
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
            filter_was_reset = True

            for i in range(self.device_list.count()):
                item = self.device_list.item(i)
                if item.data(Qt.UserRole) == device_id:
                    self.device_list.setCurrentItem(item)
                    self.on_device_selected_new(item)
                    device_found = True
                    break

        if not device_found:
            self.show_inline_feedback(
                "Dispositivo non presente nella lista corrente.",
                level="warning",
                timeout_ms=7000,
            )
            return False

        # Naviga il drill-down allo step 2 (lista dispositivi) e aggiorna il breadcrumb
        self._drill_goto(2)

        # Scrolla gli item selezionati nelle rispettive liste
        for lst, sel_id in (
            (self.customer_list, customer_id),
            (self.destination_list, destination_id),
            (self.device_list, device_id),
        ):
            for i in range(lst.count()):
                it = lst.item(i)
                if it and it.data(Qt.UserRole) == sel_id:
                    lst.scrollToItem(it)
                    break

        if notify:
            message = (
                f"Dispositivo selezionato: {device_data.get('description', 'N/D')} "
                f"(S/N: {device_data.get('serial_number', 'N/D')})"
            )
            if filter_was_reset:
                message += ". Filtro dispositivi impostato su 'Tutti'."
            self.show_inline_feedback(message, level="success")
        return True

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
                self._update_guided_flow_ui()
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
            self._show_embedded_dialog(dialog, "CORREGGI DESCRIZIONI DISPOSITIVI")
            
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
            stats = services.get_verification_stats()

            if not isinstance(stats, dict):
                logging.error(f"Invalid stats type: {type(stats)}")
                stats = {'totale': 0, 'verifiche_elettriche': 0, 'verifiche_funzionali': 0}

            logging.debug(f"Updating dashboard with stats: {stats}")

            totale = stats.get('totale', 0)
            verifiche_elettriche = stats.get('verifiche_elettriche', 0)
            verifiche_funzionali = stats.get('verifiche_funzionali', 0)

            perc_elettriche = (verifiche_elettriche / totale * 100) if totale > 0 else 0
            perc_funzionali = (verifiche_funzionali / totale * 100) if totale > 0 else 0

            self.total_card.setText(
                "<div>"
                "<span style='font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;'>Totale verifiche</span><br>"
                f"<span style='font-size:24px; font-weight:800;'>{totale:,}</span><br>"
                f"<span style='font-size:10px; opacity:0.85;'>{verifiche_elettriche:,} elettriche / {verifiche_funzionali:,} funzionali</span>"
                "</div>"
            )

            self.conformi_card.setText(
                "<div>"
                "<span style='font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;'>Elettriche</span><br>"
                f"<span style='font-size:22px; font-weight:800;'>{verifiche_elettriche:,}</span><br>"
                f"<span style='font-size:10px; opacity:0.85;'>{perc_elettriche:.1f}% del totale</span>"
                "</div>"
            )

            self.non_conformi_card.setText(
                "<div>"
                "<span style='font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;'>Funzionali</span><br>"
                f"<span style='font-size:22px; font-weight:800;'>{verifiche_funzionali:,}</span><br>"
                f"<span style='font-size:10px; opacity:0.85;'>{perc_funzionali:.1f}% del totale</span>"
                "</div>"
            )

            if hasattr(self, "stats_timestamp_label"):
                self.stats_timestamp_label.setText(
                    f"Aggiornato {datetime.now().strftime('%d/%m/%Y alle %H:%M')}"
                )

        except Exception as e:
            logging.error(f"Dashboard update error: {e}", exc_info=True)
            self.statusBar().showMessage("Errore aggiornamento statistiche", 5000)
