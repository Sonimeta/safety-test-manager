import ast
import ast
import logging
import os
import re
import time
import math
from PySide6.QtCore import Qt, QTimer, QDate, Signal, QSize, QEvent
from PySide6.QtGui import QFont, QColor, QPainter, QMovie, QFocusEvent, QWheelEvent, QMouseEvent, QEnterEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressBar, QPushButton,
                               QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget, QHeaderView, QListWidget,
                               QListWidgetItem, QFileDialog, QStyle, QFormLayout,
                               QComboBox, QTextEdit, QScrollArea, QDoubleSpinBox, QSpinBox,
                               QAbstractScrollArea, QAbstractItemView, QAbstractSpinBox)
from app import auth_manager, config, services
import database
from app.data_models import AppliedPart
from app.functional_models import (
    FunctionalField,
    FunctionalProfile,
    FunctionalRowDefinition,
    FunctionalSection,
)
from app.ui.state_manager import AppState
from app.hardware.fluke_esa612 import FLUKE_ERROR_CODES, FlukeESA612


class NoAutoSelectLineEdit(QLineEdit):
    """QLineEdit che non seleziona automaticamente il testo quando riceve il focus."""
    def focusInEvent(self, event: QFocusEvent):
        # Chiama il metodo della classe base ma non seleziona il testo
        super().focusInEvent(event)
        # Deseleziona il testo dopo che il focus è stato impostato
        self.deselect()


class NoHoverFocusLineEdit(QLineEdit):
    """QLineEdit che non riceve il focus al passaggio del mouse, solo al click."""
    def __init__(self, parent=None):
        super().__init__(parent)
        # Consenti click + TAB (no focus automatico su hover)
        self.setFocusPolicy(Qt.StrongFocus)
        self._mouse_pressed = False
    
    def enterEvent(self, event: QEnterEvent):
        # Non fare nulla quando il mouse entra - non dare il focus
        super().enterEvent(event)
    
    def mousePressEvent(self, event: QMouseEvent):
        # Segna che c'è stato un click del mouse
        self._mouse_pressed = True
        super().mousePressEvent(event)
        # Forza il focus dopo il click
        self.setFocus()
        QTimer.singleShot(200, lambda: setattr(self, '_mouse_pressed', False))
    
    def focusInEvent(self, event: QFocusEvent):
        reason = event.reason() if hasattr(event, "reason") else None
        allowed_reasons = {Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason}
        if not self._mouse_pressed and reason not in allowed_reasons:
            event.ignore()
            return
        # Chiama il metodo della classe base ma non seleziona il testo
        super().focusInEvent(event)
        # Deseleziona il testo dopo che il focus è stato impostato
        self.deselect()


class NoHoverFocusComboBox(QComboBox):
    """QComboBox che non riceve il focus al passaggio del mouse, solo al click."""
    def __init__(self, parent=None):
        super().__init__(parent)
        # Consenti click + TAB (no focus automatico su hover)
        self.setFocusPolicy(Qt.StrongFocus)
        self._mouse_pressed = False
    
    def enterEvent(self, event: QEnterEvent):
        # Non fare nulla quando il mouse entra - non dare il focus
        super().enterEvent(event)
    
    def mousePressEvent(self, event: QMouseEvent):
        # Segna che c'è stato un click del mouse
        self._mouse_pressed = True
        super().mousePressEvent(event)
        # Forza il focus dopo il click
        self.setFocus()
        QTimer.singleShot(200, lambda: setattr(self, '_mouse_pressed', False))

    def wheelEvent(self, event: QWheelEvent):
        # Evita cambi di selezione involontari durante lo scroll della pagina
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

    def focusInEvent(self, event: QFocusEvent):
        reason = event.reason() if hasattr(event, "reason") else None
        allowed_reasons = {Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason}
        if not self._mouse_pressed and reason not in allowed_reasons:
            event.ignore()
            return
        super().focusInEvent(event)


class NoWheelSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox che ignora gli eventi della rotella del mouse quando non ha il focus attivo."""
    def focusInEvent(self, event: QFocusEvent):
        super().focusInEvent(event)
        try:
            le = self.lineEdit()
            if le is not None:
                le.deselect()
        except Exception:
            pass

    def wheelEvent(self, event: QWheelEvent):
        # Ignora la rotella del mouse se il widget non ha il focus attivo
        if not self.hasFocus():
            # Passa l'evento al widget padre per permettere lo scroll
            if self.parent():
                self.parent().wheelEvent(event)
            return
        # Se ha il focus, comportati normalmente
        super().wheelEvent(event)


class NoHoverFocusSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox che non riceve il focus al passaggio del mouse, solo al click."""
    def __init__(self, parent=None):
        super().__init__(parent)
        # Consenti click + TAB (no focus automatico su hover)
        self.setFocusPolicy(Qt.StrongFocus)
        self._mouse_pressed = False
    
    def enterEvent(self, event: QEnterEvent):
        # Non fare nulla quando il mouse entra - non dare il focus
        super().enterEvent(event)
    
    def mousePressEvent(self, event: QMouseEvent):
        # Segna che c'è stato un click del mouse
        self._mouse_pressed = True
        super().mousePressEvent(event)
        # Forza il focus dopo il click
        self.setFocus()
        QTimer.singleShot(200, lambda: setattr(self, '_mouse_pressed', False))
    
    def wheelEvent(self, event: QWheelEvent):
        # Ignora la rotella del mouse se il widget non ha il focus attivo
        if not self.hasFocus():
            # Passa l'evento al widget padre per permettere lo scroll
            if self.parent():
                self.parent().wheelEvent(event)
            return
        # Se ha il focus, comportati normalmente
        super().wheelEvent(event)

    def focusInEvent(self, event: QFocusEvent):
        reason = event.reason() if hasattr(event, "reason") else None
        allowed_reasons = {Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason}
        if not self._mouse_pressed and reason not in allowed_reasons:
            event.ignore()
            return
        super().focusInEvent(event)


class NoWheelIntSpinBox(QSpinBox):
    """QSpinBox che ignora gli eventi della rotella del mouse quando non ha il focus attivo."""
    def focusInEvent(self, event: QFocusEvent):
        super().focusInEvent(event)
        try:
            le = self.lineEdit()
            if le is not None:
                le.deselect()
        except Exception:
            pass

    def wheelEvent(self, event: QWheelEvent):
        # Ignora la rotella del mouse se il widget non ha il focus attivo
        if not self.hasFocus():
            # Passa l'evento al widget padre per permettere lo scroll
            if self.parent():
                self.parent().wheelEvent(event)
            return
        # Se ha il focus, comportati normalmente
        super().wheelEvent(event)


class NoHoverFocusIntSpinBox(QSpinBox):
    """QSpinBox che non riceve il focus al passaggio del mouse, solo al click."""
    def __init__(self, parent=None):
        super().__init__(parent)
        # Consenti click + TAB (no focus automatico su hover)
        self.setFocusPolicy(Qt.StrongFocus)
        self._mouse_pressed = False
    
    def enterEvent(self, event: QEnterEvent):
        # Non fare nulla quando il mouse entra - non dare il focus
        super().enterEvent(event)
    
    def mousePressEvent(self, event: QMouseEvent):
        # Segna che c'è stato un click del mouse
        self._mouse_pressed = True
        super().mousePressEvent(event)
        # Forza il focus dopo il click
        self.setFocus()
        QTimer.singleShot(200, lambda: setattr(self, '_mouse_pressed', False))
    
    def wheelEvent(self, event: QWheelEvent):
        # Ignora la rotella del mouse se il widget non ha il focus attivo
        if not self.hasFocus():
            # Passa l'evento al widget padre per permettere lo scroll
            if self.parent():
                self.parent().wheelEvent(event)
            return
        # Se ha il focus, comportati normalmente
        super().wheelEvent(event)

    def focusInEvent(self, event: QFocusEvent):
        reason = event.reason() if hasattr(event, "reason") else None
        allowed_reasons = {Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason}
        if not self._mouse_pressed and reason not in allowed_reasons:
            event.ignore()
            return
        super().focusInEvent(event)


class NoHoverFocusTextEdit(QTextEdit):
    """QTextEdit che non riceve il focus al passaggio del mouse, solo al click."""
    def __init__(self, parent=None):
        super().__init__(parent)
        # Consenti click + TAB (no focus automatico su hover)
        self.setFocusPolicy(Qt.StrongFocus)
        self._mouse_pressed = False
    
    def enterEvent(self, event: QEnterEvent):
        # Non fare nulla quando il mouse entra - non dare il focus
        super().enterEvent(event)
    
    def mousePressEvent(self, event: QMouseEvent):
        # Segna che c'è stato un click del mouse
        self._mouse_pressed = True
        super().mousePressEvent(event)
        # Forza il focus dopo il click
        self.setFocus()
        QTimer.singleShot(200, lambda: setattr(self, '_mouse_pressed', False))

    def focusInEvent(self, event: QFocusEvent):
        reason = event.reason() if hasattr(event, "reason") else None
        allowed_reasons = {Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason}
        if not self._mouse_pressed and reason not in allowed_reasons:
            event.ignore()
            return
        super().focusInEvent(event)


class ControlPanelWidget(QWidget):
    """
    Il widget che funge da pannello di controllo / dashboard principale.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Colonna Sinistra: Statistiche
        stats_group = QGroupBox("Dashboard")
        stats_layout = QFormLayout(stats_group)
        stats_layout.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.customers_stat_label = QLabel("...")
        self.devices_stat_label = QLabel("...")
        stats_layout.addRow("Numero Clienti:", self.customers_stat_label)
        stats_layout.addRow("Numero Dispositivi:", self.devices_stat_label)
        
        # Colonna Destra: Scadenze
        scadenze_group = QGroupBox("Verifiche Scadute o in Scadenza (30 gg)")
        scadenze_layout = QVBoxLayout(scadenze_group)
        self.scadenze_list = QListWidget()
        scadenze_layout.addWidget(self.scadenze_list)
        
        layout.addWidget(stats_group, 1)
        layout.addWidget(scadenze_group, 2)
        
        self.load_data()

    def load_data(self):
        """Carica e aggiorna i dati visualizzati nel pannello di controllo."""
        logging.info("Caricamento dati per il pannello di controllo...")
        try:
            stats = services.get_stats()
            self.customers_stat_label.setText(f"<b>{stats.get('customers', 0)}</b>")
            self.devices_stat_label.setText(f"<b>{stats.get('devices', 0)}</b>")
            
            self.scadenze_list.clear()
            devices_to_check = services.get_devices_needing_verification()
            if not devices_to_check:
                self.scadenze_list.addItem("Nessuna verifica in scadenza.")
            else:
                today = QDate.currentDate()
                for device_row in devices_to_check:
                    device = dict(device_row)
                    next_date_str = device.get('next_verification_date')
                    if not next_date_str: continue
                    
                    next_date = QDate.fromString(next_date_str, "yyyy-MM-dd")
                    item_text = f"<b>{device.get('description')}</b> (S/N: {device.get('serial_number')})<br><small><i>{device.get('customer_name')}</i> - Scadenza: {next_date.toString('dd/MM/yyyy')}</small>"
                    
                    list_item = QListWidgetItem()
                    label = QLabel(item_text)
                    
                    if next_date < today:
                        label.setStyleSheet("color: #BF616A; font-weight: bold;") # Rosso
                        list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_MessageBoxCritical))
                    else:
                        label.setStyleSheet("color: #EBCB8B;") # Giallo/Ambra
                        list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_MessageBoxWarning))

                    self.scadenze_list.addItem(list_item)
                    self.scadenze_list.setItemWidget(list_item, label)
        except Exception as e:
            logging.error(f"Impossibile caricare i dati della dashboard: {e}", exc_info=True)
            self.customers_stat_label.setText("<b style='color:red;'>Errore</b>")
            self.devices_stat_label.setText("<b style='color:red;'>Errore</b>")

class TestRunnerWidget(QWidget):
    """
    Widget che guida l'utente attraverso l'esecuzione di una verifica (versione completa e corretta).
    """
    verification_completed = Signal()
    def __init__(self, device_info, customer_info, mti_info, report_settings, profile_name, visual_inspection_data, technician_name, technician_username, manual_mode: bool, parent=None):
        super().__init__(parent)
        self.device_info = device_info
        self.customer_info = customer_info
        self.mti_info = mti_info
        self.report_settings = report_settings
        self.profile_name = profile_name
        self.visual_inspection_data = visual_inspection_data
        self.technician_name = technician_name
        self.technician_username = technician_username
        self.manual_mode = manual_mode
        self.parent_window = parent
        
        self.current_profile = config.PROFILES.get(profile_name)
        # --- INIZIO MODIFICA: Accesso allo state manager ---
        self.state_manager = self.parent_window.state_manager
        # --- FINE MODIFICA ---
        self.applied_parts = [AppliedPart(**pa) for pa in device_info.get('applied_parts', [])]
        
        self.results = []
        self.is_running_auto = False
        self.saved_verification_id = None
        self.fluke_connection = None

        self.test_plan = self._build_test_plan()
        self.current_step_index = -1
        
        self.setup_ui()

        # --- INIZIO MODIFICA: Imposta lo stato di test ---
        self.state_manager.set_state(AppState.TESTING, f"Verifica in corso su {self.device_info.get('description')}")
        # --- FINE MODIFICA ---
        # --- MODIFICA #1: Imposta il cursore di attesa solo una volta per la modalità automatica ---
        if not self.manual_mode:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
        self.next_step()

    def _build_test_plan(self):
        plan = []
        standard_tests = [t for t in self.current_profile.tests if not t.is_applied_part_test]
        for test in standard_tests:
            plan.append({'test': test, 'applied_part': None})

        # Test sulle parti applicate:
        # prima eseguiamo tutte le prove (es. polarità diretta) su TUTTE le parti applicate,
        # poi le prove successive (es. polarità inversa) sempre su TUTTE le parti applicate,
        # rispettando l'ordine definito nel profilo.
        pa_test_definitions = [t for t in self.current_profile.tests if t.is_applied_part_test]
        for test_def in pa_test_definitions:
            for pa_on_device in self.applied_parts:
                key_to_find = f"::{pa_on_device.part_type}"
                if key_to_find in test_def.limits:
                    plan.append({'test': test_def, 'applied_part': pa_on_device})
        return plan

    def setup_ui(self):
        layout = QVBoxLayout(self)
        test_group = QGroupBox(f"Verifica su: {self.device_info.get('description')} (S/N: {self.device_info.get('serial_number')})")
        test_layout = QVBoxLayout(test_group)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(self.test_plan)); self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True); self.progress_bar.setFormat("Passo %v di %m")
        self.test_name_label = QLabel("Inizio verifica..."); self.test_name_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.test_name_label.setTextFormat(Qt.RichText)
        self.limit_label = QLabel("Limite:")
        self.stacked_widget = QStackedWidget()
        self.manual_page = QWidget()
        manual_layout = QHBoxLayout(self.manual_page)
        self.value_input = QLineEdit(); self.value_input.setPlaceholderText("Inserisci il valore manualmente...")
        self.read_instrument_btn = QPushButton("Leggi da Strumento")
        self.read_instrument_btn.setIcon(QApplication.style().standardIcon(QStyle.SP_DialogYesButton))
        self.read_instrument_btn.clicked.connect(self.read_value_from_instrument)
        manual_layout.addWidget(self.value_input); manual_layout.addWidget(self.read_instrument_btn)
        self.auto_page = QWidget()
        auto_layout = QVBoxLayout(self.auto_page)
        auto_status_label = QLabel("Esecuzione della sequenza automatica in corso...")
        auto_status_label.setAlignment(Qt.AlignCenter)
        auto_layout.addWidget(auto_status_label)
        self.stacked_widget.addWidget(self.manual_page); self.stacked_widget.addWidget(self.auto_page)
        self.final_buttons_layout = QHBoxLayout()
        self.back_button = QPushButton("Indietro"); self.back_button.clicked.connect(self.previous_step)
        self.back_button.setIcon(QApplication.style().standardIcon(QStyle.SP_ArrowBack))
        self.action_button = QPushButton("Avanti"); self.action_button.clicked.connect(self.next_step)
        self.save_db_button = QPushButton("Salva Verifica"); self.save_db_button.clicked.connect(self.save_verification_to_db)
        self.generate_pdf_button = QPushButton("Genera Report PDF"); self.generate_pdf_button.clicked.connect(self.generate_pdf_report_from_summary)
        self.print_pdf_button = QPushButton("Stampa Report"); self.print_pdf_button.clicked.connect(self.print_pdf_report_from_summary)
        self.finish_button = QPushButton("Fine"); self.finish_button.clicked.connect(self._handle_finish_clicked)
        self.final_buttons_layout.addWidget(self.back_button); self.final_buttons_layout.addWidget(self.action_button); self.final_buttons_layout.addWidget(self.save_db_button); self.final_buttons_layout.addWidget(self.generate_pdf_button); self.final_buttons_layout.addWidget(self.print_pdf_button); self.final_buttons_layout.addStretch(); self.final_buttons_layout.addWidget(self.finish_button)
        self.save_db_button.hide(); self.generate_pdf_button.hide(); self.print_pdf_button.hide(); self.finish_button.hide()
        # Il pulsante Indietro è visibile solo in modalità manuale e quando si può tornare indietro
        self.back_button.setVisible(self.manual_mode and self.current_step_index > 0)
        self.value_input.returnPressed.connect(self.action_button.click)
        self.results_table = QTableWidget(0, 4); self.results_table.setHorizontalHeaderLabels(["Test / P.A.", "Limite", "Valore", "Esito"]); self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        test_layout.addWidget(self.progress_bar); test_layout.addWidget(self.test_name_label); test_layout.addWidget(self.limit_label); test_layout.addWidget(self.stacked_widget); test_layout.addWidget(self.results_table); test_layout.addLayout(self.final_buttons_layout)
        layout.addWidget(test_group)
        self.setLayout(layout)

    def _handle_finish_clicked(self):
        self.state_manager.set_state(AppState.IDLE)
        if not self.saved_verification_id:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Verifica non salvata")
            msg_box.setText("La verifica non è stata salvata. Cosa vuoi fare?")
            msg_box.setIcon(QMessageBox.Question)
            
            btn_save_exit = msg_box.addButton("Salva ed Esci", QMessageBox.AcceptRole)
            btn_exit = msg_box.addButton("Esci senza Salvare", QMessageBox.DestructiveRole)
            btn_cancel = msg_box.addButton("Annulla", QMessageBox.RejectRole)
            
            msg_box.exec()
            
            clicked_button = msg_box.clickedButton()
            
            if clicked_button == btn_save_exit:
                if self.save_verification_to_db():
                    self.state_manager.set_state(AppState.IDLE) # Stato IDLE dopo salvataggio
                    # Controlla se proporre verifica funzionale
                    functional_started = self._check_and_prompt_functional_verification()
                    # Resetta l'UI solo se non è stata avviata la verifica funzionale
                    if not functional_started:
                        self.parent_window.reset_main_ui()
            elif clicked_button == btn_exit:
                self.state_manager.set_state(AppState.IDLE) # Stato IDLE se esce
                self.parent_window.reset_main_ui()
            else:
                return
        else:
            self.state_manager.set_state(AppState.IDLE) # Stato IDLE se già salvato
            # Controlla se proporre verifica funzionale
            functional_started = self._check_and_prompt_functional_verification()
            # Resetta l'UI solo se non è stata avviata la verifica funzionale
            if not functional_started:
                self.parent_window.reset_main_ui()
    
    def _check_and_prompt_functional_verification(self):
        """
        Controlla se il dispositivo ha un profilo funzionale e se in quel giorno
        non è stata ancora eseguita una verifica funzionale. Se sì, propone all'utente
        di eseguire anche una verifica funzionale.
        
        Returns:
            True se l'utente ha scelto di avviare la verifica funzionale, False altrimenti
        """
        try:
            # Controlla se il dispositivo ha un profilo funzionale predefinito
            default_functional_profile_key = self.device_info.get('default_functional_profile_key')
            if not default_functional_profile_key:
                return False  # Nessun profilo funzionale, esci senza fare nulla
            
            # Verifica che il profilo esista
            if default_functional_profile_key not in config.FUNCTIONAL_PROFILES:
                logging.warning(f"Profilo funzionale '{default_functional_profile_key}' non trovato per dispositivo {self.device_info.get('id')}")
                return False
            
            # Ottieni la data di oggi
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Controlla se esiste già una verifica funzionale per questo dispositivo oggi
            device_id = self.device_info.get('id')
            if database.has_functional_verification_today(device_id, today):
                return False  # Già eseguita una verifica funzionale oggi, esci senza fare nulla
            
            # Proponi all'utente di eseguire anche una verifica funzionale
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Verifica Funzionale")
            msg_box.setText(
                f"Il dispositivo '{self.device_info.get('description', 'Dispositivo')}' "
                f"ha un profilo di verifica funzionale associato.\n\n"
                f"Vuoi eseguire anche una verifica funzionale?"
            )
            msg_box.setIcon(QMessageBox.Question)
            
            btn_yes = msg_box.addButton("Sì", QMessageBox.YesRole)
            btn_no = msg_box.addButton("No", QMessageBox.NoRole)
            
            msg_box.exec()
            
            clicked_button = msg_box.clickedButton()
            
            if clicked_button == btn_yes:
                # Assicurati che il dispositivo sia ancora selezionato nella main window
                self.parent_window.selected_device_id = self.device_info.get('id')
                
                # Avvia la verifica funzionale
                # Imposta il profilo funzionale selezionato nella main window
                func_index = self.parent_window.functional_profile_selector.findData(default_functional_profile_key)
                if func_index != -1:
                    self.parent_window.functional_profile_selector.setCurrentIndex(func_index)
                
                # Avvia la verifica funzionale
                self.parent_window.start_functional_verification()
                return True  # Verifica funzionale avviata
            else:
                return False  # Utente ha scelto di non avviare la verifica funzionale
        except Exception as e:
            logging.error(f"Errore durante il controllo per verifica funzionale: {e}", exc_info=True)
            # In caso di errore, continua comunque senza bloccare il flusso
            return False

    def _handle_instrument_error(self, error_code):
        error_message = FLUKE_ERROR_CODES.get(error_code, "Errore sconosciuto dello strumento.")
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle("Avviso dallo Strumento")
        msg_box.setText(f"Lo strumento ha riportato un avviso:\n\n{error_message}")
        msg_box.setInformativeText("Vuoi riprovare la misura o annullare l'intera verifica?")
        retry_button = msg_box.addButton("Riprova", QMessageBox.AcceptRole)
        cancel_button = msg_box.addButton("Annulla Verifica", QMessageBox.RejectRole)
        msg_box.exec()
        return "retry" if msg_box.clickedButton() == retry_button else "cancel"

    def read_value_from_instrument(self):
        current_step = self.test_plan[self.current_step_index]
        current_test = current_step['test']
        current_pa = current_step['applied_part']
        while True:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.read_instrument_btn.setEnabled(False)
            self.parent_window.statusBar().showMessage("Comunicazione con lo strumento in corso...")
            try:
                test_function_map = {
                    "tensione alimentazione": "esegui_test_tensione_rete",
                    "resistenza conduttore di terra": "esegui_test_resistenza_terra",
                    "corrente dispersione diretta dispositivo": "esegui_test_dispersione_diretta",
                    "corrente dispersione diretta p.a.": "esegui_test_dispersione_parti_applicate",
                }
                method_name = test_function_map.get(current_test.name.lower())
                if not method_name:
                    raise NotImplementedError(f"Funzione di test non implementata per '{current_test.name}'.")
                with FlukeESA612(self.mti_info.get('com_port')) as fluke:
                    target_function = getattr(fluke, method_name)
                    kwargs = {}
                    if current_test.parameter:
                        kwargs['parametro_test'] = current_test.parameter
                    if current_pa:
                        kwargs['pa_code'] = current_pa.code
                    result = target_function(**kwargs)
            
                if result and result.startswith('!'):
                    QApplication.restoreOverrideCursor()
                    choice = self._handle_instrument_error(result)
                    if choice == "retry":
                        continue
                    else:
                        self.parent_window.reset_main_ui()
                        return
                else:
                    self.value_input.setText(str(result))
                    self.parent_window.statusBar().showMessage("Lettura completata.", 3000)
                    break
            except (ValueError, ConnectionError, IOError, NotImplementedError) as e:
                QMessageBox.critical(self, "Errore di Comunicazione o Configurazione", f"Si è verificato un errore:\n{e}")
                self.parent_window.statusBar().showMessage("Errore di comunicazione.", 5000)
                break
            finally:
                self.read_instrument_btn.setEnabled(True)
                QApplication.restoreOverrideCursor()

    def execute_single_auto_test(self):
        step_data = self.test_plan[self.current_step_index]
        test, applied_part = step_data['test'], step_data['applied_part']
        
        self.parent_window.statusBar().showMessage(f"Esecuzione: {test.name}...")
        try:
            if not self.fluke_connection:
                self.fluke_connection = FlukeESA612(self.mti_info.get('com_port'))
                self.fluke_connection.connect()
            
            test_function_map = {"tensione alimentazione": "esegui_test_tensione_rete", "resistenza conduttore di terra": "esegui_test_resistenza_terra", "corrente dispersione diretta dispositivo": "esegui_test_dispersione_diretta", "corrente dispersione diretta p.a.": "esegui_test_dispersione_parti_applicate"}
            method_name = test_function_map.get(test.name.lower())
            if not method_name: raise NotImplementedError(f"Test non implementato: '{test.name}'.")
            
            target_function = getattr(self.fluke_connection, method_name)
            kwargs = {'parametro_test': test.parameter} if test.parameter else {}
            if applied_part: kwargs['pa_code'] = applied_part.code
            result = target_function(**kwargs)
            
            if result and result.startswith('!'):
                QApplication.restoreOverrideCursor()
                choice = self._handle_instrument_error(result)
                if choice == "retry":
                    QTimer.singleShot(100, self.execute_single_auto_test)
                else:
                    self.parent_window.reset_main_ui()
                return
            else:
                self.value_input.setText(str(result))
                QTimer.singleShot(100, self.next_step)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Errore Sequenza Automatica", f"Sequenza interrotta:\n{e}")
            self.parent_window.reset_main_ui()
            self.state_manager.set_state(AppState.IDLE)
            
    def previous_step(self):
        """Torna al test precedente (solo in modalità manuale)."""
        if not self.manual_mode or self.current_step_index <= 0:
            return
        
        # Rimuovi l'ultimo risultato solo se il test corrente non è una pausa manuale
        current_step = self.test_plan[self.current_step_index]
        if "PAUSA MANUALE" not in current_step['test'].name:
            if self.results:
                self.results.pop()
                # Rimuovi anche l'ultima riga dalla tabella
                if self.results_table.rowCount() > 0:
                    self.results_table.removeRow(self.results_table.rowCount() - 1)
        
        # Torna al test precedente
        self.current_step_index -= 1
        self.progress_bar.setValue(self.current_step_index + 1)
        prev_step_data = self.test_plan[self.current_step_index]
        self.display_test(prev_step_data['test'], prev_step_data['applied_part'])

    def next_step(self):
        if self.current_step_index > -1:
            current_step = self.test_plan[self.current_step_index]
            if "PAUSA MANUALE" not in current_step['test'].name:
                if not self.record_result():
                    return
        self.current_step_index += 1
        if self.current_step_index >= len(self.test_plan):
            self.show_summary()
            return
        self.progress_bar.setValue(self.current_step_index + 1)
        next_step_data = self.test_plan[self.current_step_index]
        self.display_test(next_step_data['test'], next_step_data['applied_part'])
        if not self.manual_mode and "PAUSA MANUALE" not in next_step_data['test'].name:
            QTimer.singleShot(200, self.execute_single_auto_test)
        

    def record_result(self):
        current_step = self.test_plan[self.current_step_index]
        test = current_step['test']
        applied_part = current_step['applied_part']
        value_str = self.value_input.text().strip().replace(',', '.')
        if not value_str:
            if self.manual_mode:
                QMessageBox.warning(self, "Valore Mancante", "Inserire un valore.")
                self.value_input.setStyleSheet("border: 1px solid red;")
                return False
            else:
                raise InterruptedError("Lettura dello strumento fallita (valore vuoto).")
        try:
            cleaned_value_str = re.sub(r'[^\d.-]', '', value_str)
            value_float = float(cleaned_value_str)
        except (ValueError, TypeError):
            if self.manual_mode:
                QMessageBox.warning(self, "Valore Non Valido", "Inserire un valore numerico.")
                self.value_input.setStyleSheet("border: 1px solid red;")
                return False
            else:
                raise ValueError(f"Risposta non valida dallo strumento: '{value_str}'")
        self.value_input.setStyleSheet("")
        result_name = f"{test.name} ({test.parameter})" if test.parameter else test.name
        limit_key = "::ST"
        polarity = None  # <-- AGGIUNTO
        
        if applied_part:
            result_name = f"{test.name} - {applied_part.name} - {applied_part.part_type}"
            limit_key = f"::{applied_part.part_type}"
            # <-- AGGIUNTO: Estrai la polarità dal parametro del test
            if test.parameter:
                polarity = test.parameter
                
        limit_obj = test.limits.get(limit_key)
        is_passed = True
        limit_value = None
        unit = limit_obj.unit if limit_obj else ""
        if limit_obj and limit_obj.high_value is not None:
            is_passed = (value_float <= limit_obj.high_value)
            limit_value = limit_obj.high_value
        
        result_data = {
            "name": result_name, 
            "value": value_str, 
            "limit_value": limit_value, 
            "unit": unit, 
            "passed": is_passed,
            "polarity": polarity  # <-- AGGIUNTO
        }
        
        self.results.append(result_data)
        self.update_results_table(result_data)
        return True
        
    def display_test(self, test, applied_part=None):
        is_pause = "PAUSA MANUALE" in test.name
        self.stacked_widget.setCurrentIndex(0 if self.manual_mode or is_pause else 1)
        self.test_name_label.setText("Pausa Manuale" if is_pause else f"{test.name} {test.parameter or ''}".strip())
        
        # Mostra/nascondi il pulsante Indietro solo in modalità manuale
        if self.manual_mode:
            self.back_button.setVisible(self.current_step_index > 0)
        else:
            self.back_button.setVisible(False)
        
        if is_pause:
            pause_message = test.parameter.strip() if test.parameter.strip() else "Preparare l'apparecchio per il prossimo test."
            self.limit_label.setText(f"<b>{pause_message}</b><br>Premere 'Continua...' per proseguire.")
            self.value_input.hide()
            self.read_instrument_btn.hide()
            self.action_button.setText("Continua...")
        else:
            self.value_input.show()
            self.read_instrument_btn.show()
            self.action_button.setText("Avanti")
            self.value_input.clear()
            self.value_input.setFocus()
            limit_key = "::ST"
            test_title = f"{test.name} {test.parameter if test.parameter else ''}".strip()
            if applied_part:
                test_title += f"\n<i style='color:#AAA;'>Parte Applicata: {applied_part.name} (Tipo {applied_part.part_type})</i>"
                limit_key = f"::{applied_part.part_type}"
            self.test_name_label.setText(test_title)
            limit_obj = test.limits.get(limit_key)
            limit_text = "<b>Limite:</b> Non specificato"
            if limit_obj:
                if limit_obj.high_value is not None:
                    limit_text = f"<b>Limite:</b> ≤ {limit_obj.high_value} {limit_obj.unit}"
                else:
                    limit_text = f"<b>Limite:</b> N/A (misura in {limit_obj.unit})"
            self.limit_label.setText(limit_text)
            self.state_manager.set_state(AppState.IDLE)

    def update_results_table(self, last_result):
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        limit_text = "N/A"
        if last_result['limit_value'] is not None:
            limit_text = f"≤ {last_result['limit_value']} {last_result['unit']}"
        self.results_table.setItem(row, 0, QTableWidgetItem(last_result['name']))
        self.results_table.setItem(row, 1, QTableWidgetItem(limit_text))
        self.results_table.setItem(row, 2, QTableWidgetItem(f"{last_result['value']} {last_result['unit']}".strip()))
        passed_item = QTableWidgetItem("PASSATO" if last_result['passed'] else "FALLITO")
        passed_item.setBackground(QColor('#A3BE8C') if last_result['passed'] else QColor('#BF616A'))
        self.results_table.setItem(row, 3, passed_item)
        self.results_table.scrollToBottom()
        self.state_manager.set_state(AppState.IDLE)

    def show_summary(self):
        # --- MODIFICA #2: Ripristina il cursore qui, alla fine di tutto ---
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

        if self.fluke_connection: 
            self.fluke_connection.disconnect()
            self.fluke_connection = None
        
        self.progress_bar.setFormat("Completato!")
        self.test_name_label.setText("Verifica Completata")
        self.limit_label.setText("Salvare i dati per poter generare il report, oppure terminare.")
        self.stacked_widget.hide()
        self.action_button.hide()
        self.back_button.hide()
        self.save_db_button.show()
        self.generate_pdf_button.show()
        self.print_pdf_button.show()
        self.finish_button.show()
        self.generate_pdf_button.setEnabled(False)
        self.print_pdf_button.setEnabled(False)
        self.finish_button.setEnabled(True)
        self.save_db_button.setEnabled(True)
        self.state_manager.set_state(AppState.IDLE)

    def print_pdf_report_from_summary(self):
        if not self.saved_verification_id:
            QMessageBox.warning(self, "Attenzione", "È necessario prima salvare la verifica nel database.")
            return
        
        try:
            report_settings = {"logo_path": self.report_settings.get("logo_path")}
            services.print_pdf_report(
                verification_id=self.saved_verification_id, 
                device_id=self.device_info['id'], 
                report_settings=report_settings,
                parent_widget=self
            )
        except Exception as e:
            logging.error(f"Errore durante la stampa del report per verifica ID {self.saved_verification_id}", exc_info=True)
            QMessageBox.critical(self, "Errore di Stampa", f"Impossibile stampare il report:\n{e}")

    def save_verification_to_db(self):
        self.parent_window.statusBar().showMessage("Salvataggio verifica in corso...")
        try:
            verification_code, new_id = services.finalizza_e_salva_verifica(
                device_id=self.device_info['id'], profile_name=self.profile_name,
                results=self.results, visual_inspection_data=self.visual_inspection_data,
                mti_info=self.mti_info, technician_name=self.technician_name,
                technician_username=self.technician_username,
                device_info=self.device_info
            )
            self.saved_verification_id = new_id
            self.save_db_button.setEnabled(False)
            self.save_db_button.setText("Verifica Salvata!")
            self.generate_pdf_button.setEnabled(True)
            self.print_pdf_button.setEnabled(True)
            self.finish_button.setEnabled(True)
            self.parent_window.statusBar().showMessage(
                f"Verifica ID {new_id} salvata con successo (Codice: {verification_code}).",
                5000,
            )
            return True
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile salvare la verifica: {e}")
            self.parent_window.statusBar().showMessage("Salvataggio fallito.", 5000)
            return False
            
    def generate_pdf_report_from_summary(self):
        if not self.saved_verification_id:
            QMessageBox.warning(self, "Attenzione", "È necessario prima salvare la verifica nel database.")
            return
            
        if not self.device_info:
            QMessageBox.critical(self, "Errore Dati", "Informazioni sul dispositivo non disponibili. Impossibile generare il report.")
            return

        ams_inv = (self.device_info.get('ams_inventory') or '').strip()
        serial_num = (self.device_info.get('serial_number') or '').strip()
        base_name = ams_inv if ams_inv else serial_num
        if not base_name:
            base_name = f"Report_Verifica_{self.saved_verification_id}"
        safe_base_name = re.sub(r'[\\/*?:"<>|]', '_', base_name)
        default_filename = os.path.join(os.getcwd(), f"{safe_base_name} VE.pdf")
        filename, _ = QFileDialog.getSaveFileName(self, "Salva Report PDF", default_filename, "PDF Files (*.pdf)")
        if not filename:
            return
        try:
            services.generate_pdf_report(
                filename,
                verification_id=self.saved_verification_id,
                device_id=self.device_info['id'],
                report_settings=self.report_settings,
            )
            QMessageBox.information(self, "Successo", f"Report generato con successo:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile generare il report: {e}")


class FunctionalTestRunnerWidget(QWidget):
    """
    Widget per la compilazione delle verifiche funzionali basate su profili dinamici.
    """

    verification_completed = Signal()

    FORMULA_ALLOWED_FUNCTIONS = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
    }

    def __init__(
        self,
        device_info: dict,
        profile: FunctionalProfile,
        technician_name: str,
        technician_username: str,
        mti_info: dict | None,
        used_instruments: list | None = None,
        report_settings: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.device_info = device_info
        self.profile = profile
        self.technician_name = technician_name
        self.technician_username = technician_username
        self.mti_info = mti_info or {}
        self.used_instruments = used_instruments or []  # Lista di tutti gli strumenti usati
        self.parent_window = parent
        self.saved_verification_id: int | None = None
        self.saved_verification_code: str | None = None
        self.report_settings = report_settings or {}

        self.section_controls: dict[str, dict] = {}
        self.formula_bindings: list[dict] = []
        self._formula_signal_wrappers: list = []
        self._tables: list[QTableWidget] = []  # Lista delle tabelle per gestire il filtro eventi
        self._allow_next_table_focus_until: float = 0.0
        self._overall_status_user_locked = False
        self._status_update_in_progress = False
        self._table_view_mode = os.getenv("STM_FUNCTIONAL_TABLE_MODE", "cards").strip().lower()
        
        # Nuove variabili per la navigazione migliorata
        self.current_section_index = 0
        self.section_widgets: list[QWidget] = []
        self.section_list_items: list[QListWidgetItem] = []
        self.stacked_widget: QStackedWidget | None = None
        self.section_list: QListWidget | None = None
        self.section_step_label: QLabel | None = None
        self.section_hint_label: QLabel | None = None
        self.jump_to_incomplete_button: QPushButton | None = None
        self._shortcuts: list[QShortcut] = []

        self._build_ui()
        if self.parent_window:
            try:
                self.parent_window.state_manager.set_state(AppState.IDLE)
            except Exception:
                pass
    
    def eventFilter(self, obj, event):
        """Filtro eventi lasciato neutro: gestione focus demandata ai widget Qt standard."""
        return super().eventFilter(obj, event)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        header_label = QLabel(
            f"<b>Verifica Funzionale: {self.profile.name}</b><br>"
            f"<span style='color:#64748b;'>Dispositivo: {self.device_info.get('description', 'N/D')} "
            f"(S/N: {self.device_info.get('serial_number', 'N/A')})</span>"
        )
        header_label.setTextFormat(Qt.RichText)
        main_layout.addWidget(header_label)

        # Barra guida rapida per rendere il flusso più intuitivo
        guidance_group = QGroupBox("Guida rapida")
        guidance_layout = QHBoxLayout(guidance_group)
        guidance_layout.setContentsMargins(10, 8, 10, 8)
        guidance_layout.setSpacing(12)

        self.section_step_label = QLabel("Sezione 1/1")
        self.section_step_label.setStyleSheet("font-weight: 600;")
        guidance_layout.addWidget(self.section_step_label)

        self.section_hint_label = QLabel("Compila i campi obbligatori per procedere.")
        self.section_hint_label.setStyleSheet("color: #64748b;")
        self.section_hint_label.setWordWrap(True)
        guidance_layout.addWidget(self.section_hint_label, stretch=1)

        self.jump_to_incomplete_button = QPushButton("Vai al primo incompleto")
        self.jump_to_incomplete_button.setObjectName("secondaryButton")
        self.jump_to_incomplete_button.clicked.connect(self._go_to_first_incomplete_section)
        guidance_layout.addWidget(self.jump_to_incomplete_button)

        main_layout.addWidget(guidance_group)

        # Layout principale orizzontale: lista sezioni + contenuto
        content_layout = QHBoxLayout()
        
        # Pannello laterale con lista sezioni e progresso
        sidebar = QWidget()
        sidebar.setFixedWidth(250)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(5, 5, 5, 5)
        
        progress_label = QLabel("<b>Progresso Sezioni</b>")
        progress_label.setTextFormat(Qt.RichText)
        sidebar_layout.addWidget(progress_label)
        
        self.section_list = QListWidget()
        self.section_list.setMaximumWidth(240)
        self.section_list.itemClicked.connect(self._on_section_selected)
        sidebar_layout.addWidget(self.section_list)
        
        # Indicatore di progresso generale
        self.overall_progress = QProgressBar()
        self.overall_progress.setMaximum(100)
        self.overall_progress.setFormat("%p% completato")
        sidebar_layout.addWidget(self.overall_progress)
        
        content_layout.addWidget(sidebar)
        
        # Stacked widget per mostrare una sezione alla volta
        self.stacked_widget = QStackedWidget()
        
        # Crea i widget per ogni sezione
        for section in self.profile.sections:
            section_widget = self._create_section_widget(section)

            section_scroll = QScrollArea()
            section_scroll.setWidgetResizable(True)
            section_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            section_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            section_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
            section_scroll.setWidget(section_widget)

            self.section_widgets.append(section_scroll)
            self.stacked_widget.addWidget(section_scroll)
            
            # Aggiungi alla lista laterale
            section_title = section.title or section.key.title()
            list_item = QListWidgetItem(f"📋 {section_title}")
            list_item.setData(Qt.UserRole, len(self.section_widgets) - 1)
            self.section_list_items.append(list_item)
            self.section_list.addItem(list_item)
        
        content_layout.addWidget(self.stacked_widget, stretch=1)
        main_layout.addLayout(content_layout)
        
        # Inizializza la formula bindings dopo aver creato tutti i widget
        self._initialize_formula_bindings()
        
        # Pulsanti di navigazione
        nav_layout = QHBoxLayout()
        self.prev_button = QPushButton("◀ Precedente")
        self.prev_button.setObjectName("secondaryButton")
        self.prev_button.clicked.connect(self._previous_section)
        self.prev_button.setEnabled(False)
        
        self.next_button = QPushButton("Successivo ▶")
        self.next_button.setObjectName("autoButton")
        self.next_button.clicked.connect(self._next_section)
        if len(self.profile.sections) <= 1:
            self.next_button.setEnabled(False)
        
        nav_layout.addWidget(self.prev_button)
        nav_layout.addStretch()
        nav_layout.addWidget(self.next_button)
        main_layout.addLayout(nav_layout)
        
        # Mostra la prima sezione (dopo aver creato i pulsanti)
        self._show_section(0)

        # Strumento utilizzato - NASCOSTO (non viene più mostrato nella schermata)
        # I dati dello strumento vengono comunque salvati nel database e nel report
        
        # Stato finale e note
        footer_group = QGroupBox("Esito e Note")
        footer_layout = QFormLayout(footer_group)
        self.status_combo = QComboBox()
        self.status_combo.addItems(["PASSATO", "FALLITO", "CONFORME CON ANNOTAZIONE"])
        self.status_combo.currentTextChanged.connect(self._on_status_combo_changed)

        status_row = QWidget()
        status_row_layout = QHBoxLayout(status_row)
        status_row_layout.setContentsMargins(0, 0, 0, 0)
        status_row_layout.setSpacing(8)
        status_row_layout.addWidget(self.status_combo)

        self.auto_status_button = QPushButton("Suggerisci")
        self.auto_status_button.setObjectName("secondaryButton")
        self.auto_status_button.clicked.connect(lambda: self._update_overall_status_suggestion(force=True))
        status_row_layout.addWidget(self.auto_status_button)
        status_row_layout.addStretch()

        footer_layout.addRow("Esito complessivo:", status_row)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Note aggiuntive sulla verifica funzionale...")
        self.notes_edit.setFixedHeight(80)
        self.notes_edit.textChanged.connect(lambda: self._update_overall_status_suggestion())
        footer_layout.addRow("Note:", self.notes_edit)
        main_layout.addWidget(footer_group)

        # Pulsanti azione
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Salva Verifica")
        self.save_button.setObjectName("autoButton")
        self.save_button.clicked.connect(self.save_verification)

        self.generate_pdf_button = QPushButton("Genera Report PDF")
        self.generate_pdf_button.setObjectName("autoButton")
        self.generate_pdf_button.setEnabled(False)
        self.generate_pdf_button.clicked.connect(self.generate_pdf_report_from_summary)

        self.print_pdf_button = QPushButton("Stampa Report")
        self.print_pdf_button.setObjectName("secondaryButton")
        self.print_pdf_button.setEnabled(False)
        self.print_pdf_button.clicked.connect(self.print_pdf_report_from_summary)

        self.finish_button = QPushButton("Fine")
        self.finish_button.setObjectName("secondaryButton")
        self.finish_button.clicked.connect(self._handle_finish)

        
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.generate_pdf_button)
        button_layout.addWidget(self.print_pdf_button)
        button_layout.addStretch()
        button_layout.addWidget(self.finish_button)
        main_layout.addLayout(button_layout)
        
        # Connetti i segnali per la validazione in tempo reale
        QTimer.singleShot(100, self._update_all_progress)
        QTimer.singleShot(150, self._update_overall_status_suggestion)
        self._setup_keyboard_shortcuts()

    def _create_section_widget(self, section: FunctionalSection) -> QWidget:
        """Crea il widget per una singola sezione."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(18)
        
        controls: dict = {"type": section.section_type, "fields": {}, "rows": {}}
        
        if section.description:
            description_label = QLabel(section.description)
            description_label.setWordWrap(True)
            description_label.setStyleSheet("color: #64748b; padding: 5px;")
            layout.addWidget(description_label)

        if section.section_type in {"fields", "form"} and section.fields:
            form_layout = QFormLayout()
            for field in section.fields:
                widget = self._create_widget_for_field(field)
                self._register_widget_metadata(widget, section.key, field)
                # Connetti il segnale per validazione in tempo reale
                self._connect_validation_signal(widget, section.key, field)
                form_layout.addRow(self._build_field_label(field), widget)
                controls["fields"][field.key] = widget
            layout.addLayout(form_layout)

        elif section.section_type in {"checklist", "rows"} and section.rows:
            form_layout = QFormLayout()
            for row in section.rows:
                row_controls = {}
                if row.fields:
                    field = row.fields[0]
                    widget = self._create_widget_for_field(field)
                    self._register_widget_metadata(widget, section.key, field, row.key)
                    self._connect_validation_signal(widget, section.key, field)
                    row_controls[field.key] = widget
                    form_layout.addRow(f"{row.label or row.key}:", widget)
                    for extra_field in row.fields[1:]:
                        extra_widget = self._create_widget_for_field(extra_field)
                        self._register_widget_metadata(extra_widget, section.key, extra_field, row.key)
                        self._connect_validation_signal(extra_widget, section.key, extra_field)
                        row_controls[extra_field.key] = extra_widget
                        form_layout.addRow(
                            f"{row.label or row.key} - {extra_field.label}", extra_widget
                        )
                controls["rows"][row.key] = row_controls
            layout.addLayout(form_layout)

        elif section.section_type == "table" and section.rows:
            if self._table_view_mode == "grid":
                table_meta = self._create_table_for_section(section, layout)
            else:
                table_meta = self._create_table_cards_for_section(section, layout)
            controls.update(table_meta)
            # Connetti validazione per i widget nella tabella
            if "table_cells" in controls:
                for cell_widget in controls["table_cells"].values():
                    if isinstance(cell_widget, QWidget):
                        # Trova il campo corrispondente
                        section_obj = next((s for s in self.profile.sections if s.key == section.key), None)
                        if section_obj:
                            for row in section_obj.rows:
                                for field in row.fields:
                                    if hasattr(cell_widget, 'property') and cell_widget.property("field_key") == field.key:
                                        self._connect_validation_signal(cell_widget, section.key, field)
                                        break

        else:
            form_layout = QFormLayout()
            for field in section.fields:
                widget = self._create_widget_for_field(field)
                self._register_widget_metadata(widget, section.key, field)
                self._connect_validation_signal(widget, section.key, field)
                form_layout.addRow(self._build_field_label(field), widget)
                controls["fields"][field.key] = widget
            layout.addLayout(form_layout)

        layout.addStretch()
        self.section_controls[section.key] = controls
        return container

    def _connect_validation_signal(self, widget, section_key: str, field: FunctionalField):
        """Connette i segnali per la validazione in tempo reale."""
        def on_change(*_):
            QTimer.singleShot(100, lambda: self._update_section_progress(section_key))
            QTimer.singleShot(110, self._update_overall_status_suggestion)
        
        if isinstance(widget, QDoubleSpinBox):
            widget.valueChanged.connect(on_change)
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(on_change)
        elif isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(on_change)
        elif isinstance(widget, QTextEdit):
            widget.textChanged.connect(on_change)
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(on_change)

    def _show_section(self, index: int):
        """Mostra la sezione all'indice specificato."""
        if 0 <= index < len(self.section_widgets):
            self.current_section_index = index
            self.stacked_widget.setCurrentIndex(index)
            
            # Aggiorna la selezione nella lista
            if self.section_list:
                self.section_list.setCurrentRow(index)
            
            # Aggiorna i pulsanti di navigazione
            self.prev_button.setEnabled(index > 0)
            self.next_button.setEnabled(index < len(self.section_widgets) - 1)
            
            # Aggiorna il progresso
            self._update_all_progress()

            if self.section_step_label:
                total = len(self.section_widgets) or 1
                self.section_step_label.setText(f"Sezione {index + 1}/{total}")

    def _on_section_selected(self, item: QListWidgetItem):
        """Gestisce la selezione di una sezione dalla lista."""
        index = item.data(Qt.UserRole)
        if index is not None:
            self._show_section(index)

    def _previous_section(self):
        """Vai alla sezione precedente."""
        if self.current_section_index > 0:
            # Indietro sempre consentito: migliora la libertà di navigazione.
            self._show_section(self.current_section_index - 1)

    def _next_section(self):
        """Vai alla sezione successiva."""
        if self.current_section_index < len(self.section_widgets) - 1:
            # Valida la sezione corrente prima di procedere
            if self._validate_current_section():
                self._show_section(self.current_section_index + 1)
            else:
                missing_label = self._get_first_missing_label_in_section(self.current_section_index)
                message = "Completa i campi obbligatori prima di procedere."
                if missing_label:
                    message = f"Completa il campo obbligatorio: {missing_label}"
                QMessageBox.warning(
                    self,
                    "Campi Obbligatori",
                    message
                )

    def _setup_keyboard_shortcuts(self):
        """Scorciatoie tastiera per velocizzare l'inserimento dati."""
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self.save_verification)

        next_shortcut = QShortcut(QKeySequence("Alt+Right"), self)
        next_shortcut.activated.connect(self._next_section)

        prev_shortcut = QShortcut(QKeySequence("Alt+Left"), self)
        prev_shortcut.activated.connect(self._previous_section)

        incomplete_shortcut = QShortcut(QKeySequence("Ctrl+J"), self)
        incomplete_shortcut.activated.connect(self._go_to_first_incomplete_section)

        self._shortcuts = [save_shortcut, next_shortcut, prev_shortcut, incomplete_shortcut]

    def _collect_missing_fields_for_section(self, section_index: int) -> list[tuple[str, object]]:
        """Restituisce i campi obbligatori mancanti di una sezione."""
        if section_index < 0 or section_index >= len(self.profile.sections):
            return []

        section = self.profile.sections[section_index]
        controls = self.section_controls.get(section.key, {})
        missing: list[tuple[str, object]] = []

        if section.section_type in {"fields", "form"}:
            for field in section.fields:
                if not field.required:
                    continue
                widget = controls.get("fields", {}).get(field.key)
                has_value = bool(widget and self._has_value(widget))
                if not has_value:
                    label = field.label or field.key.replace("_", " ").title()
                    missing.append((label, widget))

        elif section.section_type in {"checklist", "rows"}:
            for row in section.rows:
                row_controls = controls.get("rows", {}).get(row.key, {})
                row_label = row.label or row.key.replace("_", " ").title()
                for field in row.fields:
                    if not field.required:
                        continue
                    widget = row_controls.get(field.key)
                    has_value = bool(widget and self._has_value(widget))
                    if not has_value:
                        field_label = field.label or field.key.replace("_", " ").title()
                        missing.append((f"{row_label} → {field_label}", widget))

        elif section.section_type == "table":
            table_cells = controls.get("table_cells", {})
            for row in section.rows:
                row_label = row.label or row.key.replace("_", " ").title()
                for field in row.fields:
                    if not field.required:
                        continue
                    source = table_cells.get((row.key, field.key))
                    has_value = False
                    if isinstance(source, QTableWidgetItem):
                        has_value = bool(source.text().strip())
                    elif source is not None:
                        has_value = self._has_value(source)

                    if not has_value:
                        field_label = field.label or field.key.replace("_", " ").title()
                        missing.append((f"{row_label} → {field_label}", source))

        return missing

    def _focus_missing_widget(self, widget):
        if widget is None:
            return
        if isinstance(widget, QTableWidgetItem):
            return
        try:
            widget.setFocus()
        except Exception:
            return

    def _get_first_missing_label_in_section(self, section_index: int) -> str:
        missing = self._collect_missing_fields_for_section(section_index)
        return missing[0][0] if missing else ""

    def _go_to_first_incomplete_section(self):
        for idx in range(len(self.profile.sections)):
            missing = self._collect_missing_fields_for_section(idx)
            if missing:
                self._show_section(idx)
                first_missing_widget = missing[0][1]
                if first_missing_widget and not isinstance(first_missing_widget, QTableWidgetItem):
                    self._highlight_field(first_missing_widget, True)
                    self._focus_missing_widget(first_missing_widget)
                return
        QMessageBox.information(self, "Completato", "Tutte le sezioni obbligatorie risultano compilate.")

    def _validate_current_section(self) -> bool:
        """Valida la sezione corrente. Restituisce True se valida."""
        if self.current_section_index >= len(self.profile.sections):
            return True

        missing = self._collect_missing_fields_for_section(self.current_section_index)
        if not missing:
            # Rimuove eventuale evidenziazione residua nella sezione corrente
            section = self.profile.sections[self.current_section_index]
            controls = self.section_controls.get(section.key, {})
            for widget in controls.get("fields", {}).values():
                self._highlight_field(widget, False)
            for row_controls in controls.get("rows", {}).values():
                for widget in row_controls.values():
                    self._highlight_field(widget, False)
            for source in controls.get("table_cells", {}).values():
                if source is not None and not isinstance(source, QTableWidgetItem):
                    self._highlight_field(source, False)
            return True

        first_missing_widget = missing[0][1]
        if first_missing_widget is not None and not isinstance(first_missing_widget, QTableWidgetItem):
            self._highlight_field(first_missing_widget, True)
            self._focus_missing_widget(first_missing_widget)
        return False

    def _on_status_combo_changed(self, _text: str):
        if self._status_update_in_progress:
            return
        self._overall_status_user_locked = True

    def _normalize_outcome_value(self, value) -> str:
        raw = str(value or "").strip().upper()
        if raw in {"N.A", "N/A", "NA"}:
            return "N.A."
        return raw

    def _collect_outcome_counters(self) -> dict[str, int]:
        total = 0
        ko_count = 0
        na_count = 0

        def consume(value):
            nonlocal total, ko_count, na_count
            normalized = self._normalize_outcome_value(value)
            if not normalized:
                return
            total += 1
            if normalized in {"KO", "FALLITO", "FAIL", "NON CONFORME"}:
                ko_count += 1
            elif normalized == "N.A.":
                na_count += 1

        for section in self.profile.sections:
            controls = self.section_controls.get(section.key, {})

            if section.section_type in {"fields", "form"}:
                for field in section.fields:
                    if (field.field_type or "").lower() in {"choice", "enum", "bool"}:
                        widget = controls.get("fields", {}).get(field.key)
                        if widget is not None:
                            consume(self._extract_widget_value(widget))

            elif section.section_type in {"checklist", "rows"}:
                for row in section.rows:
                    row_controls = controls.get("rows", {}).get(row.key, {})
                    for field in row.fields:
                        if (field.field_type or "").lower() in {"choice", "enum", "bool"}:
                            widget = row_controls.get(field.key)
                            if widget is not None:
                                consume(self._extract_widget_value(widget))

            elif section.section_type == "table":
                table_cells = controls.get("table_cells", {})
                for row in section.rows:
                    for field in row.fields:
                        if (field.field_type or "").lower() not in {"choice", "enum", "bool"}:
                            continue
                        source = table_cells.get((row.key, field.key))
                        if isinstance(source, QTableWidgetItem):
                            consume(source.text().strip())
                        elif source is not None:
                            consume(self._extract_widget_value(source))

        return {
            "total": total,
            "ko_count": ko_count,
            "na_count": na_count,
        }

    def _get_suggested_overall_status(self) -> str:
        counters = self._collect_outcome_counters()
        if counters["ko_count"] > 0:
            return "FALLITO"

        if counters["na_count"] > 0:
            return "CONFORME CON ANNOTAZIONE"

        if self.notes_edit.toPlainText().strip():
            return "CONFORME CON ANNOTAZIONE"

        return "PASSATO"

    def _set_status_combo_value(self, value: str):
        if self.status_combo.currentText() == value:
            return
        self._status_update_in_progress = True
        self.status_combo.setCurrentText(value)
        self._status_update_in_progress = False

    def _update_overall_status_suggestion(self, force: bool = False):
        if force:
            self._overall_status_user_locked = False

        if self._overall_status_user_locked:
            return

        self._set_status_combo_value(self._get_suggested_overall_status())

    def _confirm_status_consistency_before_save(self) -> bool:
        counters = self._collect_outcome_counters()
        selected_status = self.status_combo.currentText()

        if counters["ko_count"] > 0 and selected_status == "PASSATO":
            answer = QMessageBox.question(
                self,
                "Esito potenzialmente incoerente",
                (
                    f"Sono presenti {counters['ko_count']} esiti KO ma l'esito complessivo è PASSATO.\n\n"
                    "Vuoi salvare comunque?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return answer == QMessageBox.Yes

        return True

    def _has_value(self, widget) -> bool:
        """Verifica se un widget ha un valore."""
        if isinstance(widget, QComboBox):
            return bool(widget.currentText() and widget.currentText() != "")
        elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
            return True  # I numeri hanno sempre un valore
        elif isinstance(widget, QTextEdit):
            return bool(widget.toPlainText().strip())
        elif isinstance(widget, QLineEdit):
            return bool(widget.text().strip())
        return False

    def _highlight_field(self, widget, highlight: bool):
        """Evidenzia un campo per indicare che è obbligatorio o ha un errore."""
        if highlight:
            widget.setStyleSheet("border: 2px solid #ef4444; background-color: #fef2f2;")
        else:
            widget.setStyleSheet("")

    def _validate_all_sections(self) -> tuple[bool, str]:
        """
        Valida TUTTE le sezioni e i loro campi obbligatori.
        Restituisce (is_valid: bool, error_message: str)
        """
        missing_fields = []
        
        for section_idx, section in enumerate(self.profile.sections):
            controls = self.section_controls.get(section.key, {})
            
            # Valida i campi della sezione se è di tipo "fields" o "form"
            if section.section_type in {"fields", "form"}:
                for field in section.fields:
                    if field.required:
                        widget = controls.get("fields", {}).get(field.key)
                        if not widget or not self._has_value(widget):
                            field_label = field.label or field.key.replace("_", " ").title()
                            section_title = section.title or section.key.replace("_", " ").title()
                            missing_fields.append(f"• {section_title} → {field_label}")
                            # Evidenzia il campo in rosso
                            if widget:
                                self._highlight_field(widget, True)
                        else:
                            # Rimuovi l'evidenziazione se il campo ora ha un valore
                            if widget:
                                self._highlight_field(widget, False)
            
            # Valida le righe della checklist/tabella
            elif section.section_type == "checklist":
                rows_data = controls.get("rows", {})
                for row_def in section.rows:
                    row_widgets = rows_data.get(row_def.key, {})
                    for field in row_def.fields:
                        if field.required:
                            widget = row_widgets.get(field.key)
                            if not widget or not self._has_value(widget):
                                field_label = field.label or field.key.replace("_", " ").title()
                                row_label = row_def.label or row_def.key.replace("_", " ").title()
                                section_title = section.title or section.key.replace("_", " ").title()
                                missing_fields.append(f"• {section_title} → {row_label} → {field_label}")
                                if widget:
                                    self._highlight_field(widget, True)
                            else:
                                if widget:
                                    self._highlight_field(widget, False)
            
            # Valida le righe delle tabelle
            elif section.section_type == "table":
                table_widget = controls.get("table")
                table_cells = controls.get("table_cells", {})
                column_fields = controls.get("column_fields", [])
                column_index_by_key = {f.key: idx for idx, f in enumerate(column_fields)}

                for row_idx, row_def in enumerate(section.rows):
                    for field in row_def.fields:
                        if not field.required:
                            continue

                        value_ok = False
                        source = table_cells.get((row_def.key, field.key))

                        if isinstance(source, QTableWidgetItem):
                            value_ok = bool(source.text().strip())
                        elif source is not None:
                            value_ok = self._has_value(source)
                            self._highlight_field(source, not value_ok)
                        elif table_widget is not None:
                            # Fallback robusto per modalità griglia se la mappa table_cells manca
                            col_idx = column_index_by_key.get(field.key, -1)
                            if col_idx >= 0:
                                cell_widget = table_widget.cellWidget(row_idx, col_idx)
                                if cell_widget is not None:
                                    value_ok = self._has_value(cell_widget)
                                    self._highlight_field(cell_widget, not value_ok)
                                else:
                                    item = table_widget.item(row_idx, col_idx)
                                    value_ok = bool(item and item.text().strip())

                        if not value_ok:
                            field_label = field.label or field.key.replace("_", " ").title()
                            row_label = row_def.label or row_def.key.replace("_", " ").title()
                            section_title = section.title or section.key.replace("_", " ").title()
                            missing_fields.append(
                                f"• {section_title} → {row_label} (riga {row_idx + 1}) → {field_label}"
                            )
        
        if missing_fields:
            error_msg = "I seguenti campi obbligatori non sono compilati:\n\n" + "\n".join(missing_fields)
            return False, error_msg
        
        return True, ""

    def _update_section_progress(self, section_key: str):
        """Aggiorna l'indicatore di progresso per una sezione."""
        section = next((s for s in self.profile.sections if s.key == section_key), None)
        if not section:
            return
        
        controls = self.section_controls.get(section_key, {})
        total_fields = 0
        completed_fields = 0
        
        # Conta i campi completati
        if section.section_type in {"fields", "form"}:
            for field in section.fields:
                total_fields += 1
                widget = controls.get("fields", {}).get(field.key)
                if widget and self._has_value(widget):
                    completed_fields += 1
        elif section.section_type in {"checklist", "rows"}:
            for row in section.rows:
                row_controls = controls.get("rows", {}).get(row.key, {})
                for field in row.fields:
                    total_fields += 1
                    widget = row_controls.get(field.key)
                    if widget and self._has_value(widget):
                        completed_fields += 1
        elif section.section_type == "table":
            table_cells = controls.get("table_cells", {})
            for row in section.rows:
                for field in row.fields:
                    total_fields += 1
                    source = table_cells.get((row.key, field.key))
                    if isinstance(source, QTableWidgetItem):
                        if source.text().strip():
                            completed_fields += 1
                    elif source is not None and self._has_value(source):
                        completed_fields += 1
        
        # Aggiorna l'icona nella lista
        section_index = next((i for i, s in enumerate(self.profile.sections) if s.key == section_key), -1)
        if section_index >= 0 and section_index < len(self.section_list_items):
            item = self.section_list_items[section_index]
            section_title = section.title or section.key.title()
            if total_fields > 0:
                progress_pct = int((completed_fields / total_fields) * 100)
                if progress_pct == 100:
                    item.setText(f"✅ {section_title}")
                    item.setForeground(QColor("#10b981"))
                elif progress_pct > 0:
                    item.setText(f"🔄 {section_title} ({progress_pct}%)")
                    item.setForeground(QColor("#f59e0b"))
                else:
                    item.setText(f"📋 {section_title}")
                    item.setForeground(QColor("#64748b"))
            else:
                item.setText(f"📋 {section_title}")

    def _update_all_progress(self):
        """Aggiorna il progresso di tutte le sezioni e l'indicatore generale."""
        total_sections = len(self.profile.sections)
        completed_sections = 0
        total_fields_all = 0
        completed_fields_all = 0
        
        for section in self.profile.sections:
            self._update_section_progress(section.key)
            controls = self.section_controls.get(section.key, {})
            
            if section.section_type in {"fields", "form"}:
                for field in section.fields:
                    total_fields_all += 1
                    widget = controls.get("fields", {}).get(field.key)
                    if widget and self._has_value(widget):
                        completed_fields_all += 1
                
                # Considera una sezione completata se tutti i campi obbligatori sono compilati
                all_required_filled = True
                for field in section.fields:
                    if field.required:
                        widget = controls.get("fields", {}).get(field.key)
                        if not widget or not self._has_value(widget):
                            all_required_filled = False
                            break
                if all_required_filled and section.fields:
                    completed_sections += 1
            elif section.section_type in {"checklist", "rows"}:
                all_required_filled = True
                has_any_field = False
                for row in section.rows:
                    row_controls = controls.get("rows", {}).get(row.key, {})
                    for field in row.fields:
                        has_any_field = True
                        total_fields_all += 1
                        widget = row_controls.get(field.key)
                        if widget and self._has_value(widget):
                            completed_fields_all += 1
                        if field.required and (not widget or not self._has_value(widget)):
                            all_required_filled = False
                if all_required_filled and has_any_field:
                    completed_sections += 1
            elif section.section_type == "table":
                all_required_filled = True
                has_any_field = False
                table_cells = controls.get("table_cells", {})
                for row in section.rows:
                    for field in row.fields:
                        has_any_field = True
                        total_fields_all += 1
                        source = table_cells.get((row.key, field.key))
                        has_value = False
                        if isinstance(source, QTableWidgetItem):
                            has_value = bool(source.text().strip())
                        elif source is not None:
                            has_value = self._has_value(source)

                        if has_value:
                            completed_fields_all += 1
                        if field.required and not has_value:
                            all_required_filled = False
                if all_required_filled and has_any_field:
                    completed_sections += 1
        
        # Aggiorna la barra di progresso generale
        if total_fields_all > 0:
            overall_pct = int((completed_fields_all / total_fields_all) * 100)
            self.overall_progress.setValue(overall_pct)
            self.overall_progress.setFormat(
                f"{overall_pct}% completato ({completed_sections}/{total_sections} sezioni)"
            )

        if self.section_hint_label:
            if completed_sections >= total_sections and total_sections > 0:
                self.section_hint_label.setText("Ottimo: tutte le sezioni obbligatorie sono complete. Puoi salvare.")
            else:
                first_incomplete = None
                for idx in range(total_sections):
                    if self._collect_missing_fields_for_section(idx):
                        first_incomplete = idx
                        break

                if first_incomplete is not None:
                    section_title = self.profile.sections[first_incomplete].title or self.profile.sections[first_incomplete].key.title()
                    self.section_hint_label.setText(
                        f"Prossima sezione da completare: {section_title}"
                    )
                else:
                    self.section_hint_label.setText("Compila i campi obbligatori per procedere.")

    def _build_field_label(self, field: FunctionalField) -> str:
        label = field.label or field.key.replace("_", " ").title()
        if field.unit:
            label = f"{label} [{field.unit}]"
        return label

    def _create_widget_for_field(self, field: FunctionalField, in_table: bool = False):
        field_type = (field.field_type or "text").lower()
        default_value = field.default
        is_formula = bool(field.formula)

        if is_formula:
            # Per le formule, usa sempre NoAutoSelectLineEdit (non serve NoHoverFocus perché è read-only)
            widget = NoAutoSelectLineEdit()
            widget.setReadOnly(True)
            widget.setAlignment(Qt.AlignRight)
            widget.setPlaceholderText("Calcolato automaticamente")
        elif field_type in {"choice", "enum", "bool"}:
            # In tabella evita focus involontario da hover
            widget = NoHoverFocusComboBox() if in_table else QComboBox()
            options = field.options or ["OK", "KO", "N.A."]
            # Se non c'è un default value, aggiungi un'opzione vuota all'inizio
            if default_value is None or default_value == "":
                widget.addItem("")
            widget.addItems(options)
            if in_table:
                widget.setMinimumWidth(130)
            if default_value in options:
                widget.setCurrentText(str(default_value))
        elif field_type in {"number", "numeric", "float"}:
            # In tabella blocca focus involontario da hover
            widget = NoHoverFocusSpinBox() if in_table else NoWheelSpinBox()
            widget.setDecimals(field.precision if field.precision is not None else 3)
            widget.setRange(-999999.0, 999999.0)
            if in_table:
                widget.setMinimumWidth(120)
            if default_value not in (None, ""):
                try:
                    widget.setValue(float(default_value))
                except (TypeError, ValueError):
                    pass
        elif field_type in {"integer", "int"}:
            # In tabella blocca focus involontario da hover
            widget = NoHoverFocusIntSpinBox() if in_table else NoWheelIntSpinBox()
            widget.setRange(-1000000, 1000000)
            if in_table:
                widget.setMinimumWidth(110)
            if default_value not in (None, ""):
                try:
                    widget.setValue(int(default_value))
                except (TypeError, ValueError):
                    pass
        elif field_type in {"multiline", "text_area"}:
            widget = NoHoverFocusTextEdit() if in_table else QTextEdit()
            widget.setFixedHeight(60)
            if in_table:
                widget.setMinimumWidth(200)
            if default_value:
                widget.setPlainText(str(default_value))
        else:
            widget = NoHoverFocusLineEdit() if in_table else NoAutoSelectLineEdit()
            if in_table:
                widget.setMinimumWidth(140)
            if default_value not in (None, ""):
                widget.setText(str(default_value))

        if is_formula:
            widget.setProperty("is_formula", True)
            if field.unit:
                widget.setToolTip(f"Calcolato automaticamente ({field.unit})")
        else:
            if field.read_only:
                if isinstance(widget, (QLineEdit, QTextEdit)):
                    widget.setReadOnly(True)
                elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                    widget.setReadOnly(True)
                    widget.setButtonSymbols(QAbstractSpinBox.NoButtons)
                else:
                    widget.setDisabled(True)

        if isinstance(widget, (QDoubleSpinBox, QSpinBox)) and field.unit:
            widget.setSuffix(f" {field.unit}")
        elif hasattr(widget, "setPlaceholderText") and not is_formula and field.help_text:
            widget.setPlaceholderText(field.help_text)

        # Migliora leggibilità: evita controlli schiacciati nelle sezioni con molti campi.
        if not in_table and isinstance(widget, (QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox)):
            widget.setMinimumHeight(34)

        return widget

    def _create_table_for_section(self, section: FunctionalSection, layout: QVBoxLayout):
        row_definitions = section.rows

        # Determina le colonne in base ai campi unici
        column_fields: list[FunctionalField] = []
        seen_keys: set[str] = set()
        for row in row_definitions:
            for field in row.fields:
                if field.key not in seen_keys:
                    seen_keys.add(field.key)
                    column_fields.append(field)

        table = QTableWidget(len(row_definitions), len(column_fields))
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setMouseTracking(False)
        table.viewport().setMouseTracking(False)
        table.setAlternatingRowColors(True)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        table.verticalHeader().setVisible(True)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        # Lo stile per le tabelle è ora nel file components.qss
        # table.setStyleSheet("QTableWidget::item { padding: 6px 8px; }")

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)

        headers = []
        for col_idx, field in enumerate(column_fields):
            label = self._build_field_label(field)
            headers.append(label)
        table.setHorizontalHeaderLabels(headers)
        table.setVerticalHeaderLabels(
            [row.label or row.key.title() for row in row_definitions]
        )

        cell_widgets: dict[tuple[str, str], object] = {}

        for row_idx, row in enumerate(row_definitions):
            row_field_map = {f.key: f for f in row.fields}
            for col_idx, column_field in enumerate(column_fields):
                field = row_field_map.get(column_field.key, column_field)
                widget = None
                item = None

                if field.field_type in {"choice", "enum", "bool", "number", "numeric", "float", "integer", "int"} or field.formula:
                    widget = self._create_widget_for_field(field, in_table=True)
                    self._register_widget_metadata(widget, section.key, field, row.key)
                    if isinstance(widget, QTextEdit):
                        text_item = QTableWidgetItem(widget.toPlainText())
                        text_item.setFlags(Qt.ItemIsEnabled)
                        table.setItem(row_idx, col_idx, text_item)
                        item = text_item
                    else:
                        table.setCellWidget(row_idx, col_idx, widget)
                elif field.read_only:
                    item = QTableWidgetItem(str(field.default or ""))
                    item.setFlags(Qt.ItemIsEnabled)
                    table.setItem(row_idx, col_idx, item)
                else:
                    widget = self._create_widget_for_field(field, in_table=True)
                    self._register_widget_metadata(widget, section.key, field, row.key)
                    if isinstance(widget, QTextEdit):
                        text_item = QTableWidgetItem(widget.toPlainText())
                        text_item.setFlags(Qt.ItemIsEnabled)
                        table.setItem(row_idx, col_idx, text_item)
                        item = text_item
                    else:
                        table.setCellWidget(row_idx, col_idx, widget)

                if widget is not None:
                    cell_widgets[(row.key, field.key)] = widget
                elif item is not None:
                    cell_widgets[(row.key, field.key)] = item

            self._apply_table_column_widths(table, column_fields)

        layout.addWidget(table)
        return {
            "type": "table",
            "table_mode": "grid",
            "table": table,
            "column_fields": column_fields,
            "row_definitions": row_definitions,
            "table_cells": cell_widgets,
        }

    def _create_table_cards_for_section(self, section: FunctionalSection, layout: QVBoxLayout):
        """Alternativa user-friendly alla griglia: una card per ogni riga."""
        row_definitions = section.rows

        column_fields: list[FunctionalField] = []
        seen_keys: set[str] = set()
        for row in row_definitions:
            for field in row.fields:
                if field.key not in seen_keys:
                    seen_keys.add(field.key)
                    column_fields.append(field)

        cell_widgets: dict[tuple[str, str], object] = {}

        for row_idx, row in enumerate(row_definitions):
            row_title = row.label or row.key.title()
            group = QGroupBox(f"Riga {row_idx + 1}: {row_title}")
            group_layout = QFormLayout(group)
            group_layout.setHorizontalSpacing(12)
            group_layout.setVerticalSpacing(8)

            row_field_map = {f.key: f for f in row.fields}
            for column_field in column_fields:
                field = row_field_map.get(column_field.key, column_field)
                widget = self._create_widget_for_field(field, in_table=False)
                self._register_widget_metadata(widget, section.key, field, row.key)
                group_layout.addRow(self._build_field_label(field), widget)
                cell_widgets[(row.key, field.key)] = widget

            layout.addWidget(group)

        return {
            "type": "table",
            "table_mode": "cards",
            "column_fields": column_fields,
            "row_definitions": row_definitions,
            "table_cells": cell_widgets,
        }

    def _apply_table_column_widths(self, table: QTableWidget, column_fields: list[FunctionalField]):
        """Bilancia le larghezze colonne per evitare campi schiacciati o eccessivamente larghi."""
        header = table.horizontalHeader()

        for col_idx, field in enumerate(column_fields):
            field_type = (field.field_type or "text").lower()
            base_label = self._build_field_label(field)
            # Stima semplice della larghezza in base all'etichetta per evitare colonne enormi
            label_based_width = min(max(110, len(base_label) * 8), 260)

            if field.formula:
                target_width = max(130, label_based_width)
                resize_mode = QHeaderView.Interactive
            elif field_type in {"choice", "enum", "bool"}:
                target_width = max(140, label_based_width)
                resize_mode = QHeaderView.Interactive
            elif field_type in {"number", "numeric", "float", "integer", "int"}:
                target_width = max(120, min(label_based_width, 180))
                resize_mode = QHeaderView.Interactive
            elif field_type in {"multiline", "text_area"}:
                target_width = max(220, label_based_width)
                resize_mode = QHeaderView.Stretch
            else:
                target_width = max(170, label_based_width)
                resize_mode = QHeaderView.Stretch

            header.setSectionResizeMode(col_idx, resize_mode)
            table.setColumnWidth(col_idx, target_width)

    def _register_widget_metadata(
        self,
        widget,
        section_key: str,
        field: FunctionalField,
        row_key: str | None = None,
    ):
        if widget is None:
            return

        try:
            widget.setProperty("section_key", section_key)
            widget.setProperty("field_key", field.key)
            widget.setProperty("is_formula", bool(field.formula))
            if row_key is not None:
                widget.setProperty("row_key", row_key)
        except Exception:
            pass

        default_value = field.default
        has_value = False
        if field.formula:
            has_value = False
        elif default_value not in (None, ""):
            has_value = True
        elif field.read_only:
            has_value = True
        elif isinstance(widget, QComboBox):
            has_value = bool(widget.currentText())
        elif isinstance(widget, (QDoubleSpinBox, QSpinBox)):
            try:
                has_value = bool(widget.value() != 0 or default_value not in (None, ""))
            except Exception:
                has_value = False
        elif isinstance(widget, QTextEdit):
            has_value = bool(widget.toPlainText().strip())
        elif isinstance(widget, QLineEdit):
            has_value = bool(widget.text().strip())

        widget.setProperty("has_user_value", has_value)

        if field.help_text:
            widget.setToolTip(field.help_text)

    def _initialize_formula_bindings(self):
        self.formula_bindings.clear()
        self._formula_signal_wrappers.clear()

        for section in self.profile.sections:
            controls = self.section_controls.get(section.key, {})
            if not controls:
                continue

            if section.section_type in {"fields", "form"}:
                for field in section.fields:
                    if field.formula:
                        widget = controls.get("fields", {}).get(field.key)
                        if widget:
                            self._register_formula_binding(
                                section_key=section.key,
                                field=field,
                                widget=widget,
                                context={"type": "fields"},
                            )

            elif section.section_type in {"checklist", "rows"}:
                for row in section.rows:
                    row_controls = controls.get("rows", {}).get(row.key, {})
                    for field in row.fields:
                        if field.formula:
                            widget = row_controls.get(field.key)
                            if widget:
                                self._register_formula_binding(
                                    section_key=section.key,
                                    field=field,
                                    widget=widget,
                                    context={"type": "row", "row_key": row.key},
                                )

            elif section.section_type == "table":
                table_cells = controls.get("table_cells", {})
                for row in section.rows:
                    for field in row.fields:
                        if field.formula:
                            widget = table_cells.get((row.key, field.key))
                            if widget is None or isinstance(widget, QTableWidgetItem):
                                continue
                            self._register_formula_binding(
                                section_key=section.key,
                                field=field,
                                widget=widget,
                                context={"type": "table", "row_key": row.key},
                            )
            else:
                for field in section.fields:
                    if field.formula:
                        widget = controls.get("fields", {}).get(field.key)
                        if widget:
                            self._register_formula_binding(
                                section_key=section.key,
                                field=field,
                                widget=widget,
                                context={"type": "fields"},
                            )

    def _register_formula_binding(self, section_key: str, field: FunctionalField, widget, context: dict):
        formula = field.formula or ""
        dependencies = [
            name
            for name in self._extract_formula_dependencies(formula)
            if name not in self.FORMULA_ALLOWED_FUNCTIONS
            and name not in {"True", "False", "None"}
        ]

        binding = {
            "section_key": section_key,
            "field": field,
            "widget": widget,
            "context": context,
            "formula": formula,
            "dependencies": dependencies,
        }
        self.formula_bindings.append(binding)

        for dep in dependencies:
            source_widget, _ = self._locate_dependency_source(section_key, dep, context)
            if source_widget is not None:
                self._connect_change_signal(
                    source_widget,
                    lambda b=binding: self._recalculate_formula(b),
                )

        self._recalculate_formula(binding)

    def _extract_formula_dependencies(self, formula: str) -> list[str]:
        try:
            tree = ast.parse(formula, mode="eval")
        except SyntaxError:
            logging.warning("Formula non valida: %s", formula)
            return []

        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
        return sorted(names)

    def _locate_dependency_source(self, section_key: str, field_key: str, context: dict):
        # Prima cerca nella sezione corrente
        controls = self.section_controls.get(section_key, {})
        row_key = context.get("row_key")

        if context.get("type") == "fields":
            widget = controls.get("fields", {}).get(field_key)
            if widget is not None:
                return widget, None

        if context.get("type") == "row":
            row_controls = controls.get("rows", {}).get(row_key, {})
            widget = row_controls.get(field_key) if row_controls else None
            if widget is not None:
                return widget, None

        if context.get("type") == "table":
            cell = controls.get("table_cells", {}).get((row_key, field_key))
            if isinstance(cell, QTableWidgetItem):
                return None, cell
            if cell is not None:
                return cell, None

        # Se non trovato nella sezione corrente, cerca in tutte le altre sezioni
        # Questo abilita cross-section formula references (es: "esito_ecg" in "verifiche_effettuate")
        for section_controls in self.section_controls.values():
            # Cerca nei campi
            widget = section_controls.get("fields", {}).get(field_key)
            if widget is not None:
                return widget, None
            
            # Cerca nelle righe (checklist/rows)
            rows_dict = section_controls.get("rows", {})
            for row_dict in rows_dict.values():
                widget = row_dict.get(field_key)
                if widget is not None:
                    return widget, None
            
            # Cerca nella tabella
            table_cells = section_controls.get("table_cells", {})
            for cell in table_cells.values():
                if isinstance(cell, QTableWidgetItem):
                    continue
                # Cerca per corrispondenza parziale (row_key, field_key)
                if cell is not None and hasattr(cell, 'data') and cell.data(0) == field_key:
                    return cell, None

        return None, None

    def _connect_change_signal(self, widget, callback):
        def trigger(*_):
            try:
                widget.setProperty("has_user_value", True)
            except Exception:
                pass
            callback()

        self._formula_signal_wrappers.append(trigger)

        if isinstance(widget, QDoubleSpinBox):
            widget.valueChanged.connect(trigger)
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(trigger)
        elif isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(trigger)
        elif isinstance(widget, QTextEdit):
            widget.textChanged.connect(trigger)
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(trigger)

    def _recalculate_formula(self, binding: dict):
        dependencies: list[str] = binding.get("dependencies", [])
        if not dependencies:
            try:
                result = self._evaluate_formula(binding["formula"], {})
            except Exception as exc:
                logging.debug("Errore valutando formula '%s': %s", binding["formula"], exc)
                self._apply_formula_result(binding, None)
            else:
                self._apply_formula_result(binding, result)
            return

        values: dict[str, float | str] = {}
        missing_value = False

        for dep in dependencies:
            widget, item = self._locate_dependency_source(binding["section_key"], dep, binding["context"])
            if widget is None and item is None:
                logging.debug("Formula: impossibile trovare il campo dipendente '%s'.", dep)
                missing_value = True
                continue

            raw_value = self._get_value_from_source(widget, item)
            converted_value = self._convert_to_number(raw_value)
            if converted_value is None:
                if (
                    isinstance(raw_value, str)
                    and raw_value.strip()
                    and len(dependencies) == 1
                    and binding.get("formula", "").strip() == dep
                ):
                    values[dep] = raw_value.strip()
                else:
                    missing_value = True
            else:
                values[dep] = converted_value

        if missing_value:
            self._apply_formula_result(binding, None)
            return

        try:
            result = self._evaluate_formula(binding["formula"], values)
        except Exception as exc:
            logging.debug("Errore valutando formula '%s': %s", binding["formula"], exc)
            self._apply_formula_result(binding, None)
            return

        self._apply_formula_result(binding, result)

    def _evaluate_formula(self, formula: str, values: dict[str, float]):
        local_context: dict[str, float | int | callable] = dict(self.FORMULA_ALLOWED_FUNCTIONS)
        local_context.update(values)
        tree = ast.parse(formula, mode="eval")
        compiled = compile(tree, "<formula>", "eval")
        return eval(compiled, {"__builtins__": {}}, local_context)

    def _format_formula_result(self, field: FunctionalField, value) -> str:
        if value is None:
            return ""

        if isinstance(value, (int, float)):
            if math.isnan(float(value)) or math.isinf(float(value)):
                return ""
            precision = field.precision if field.precision is not None else 3
            formatted = f"{float(value):.{precision}f}"
            if precision > 0:
                formatted = formatted.rstrip("0").rstrip(".")
            return formatted

        return str(value)

    def _apply_formula_result(self, binding: dict, value):
        widget = binding.get("widget")
        field: FunctionalField = binding.get("field")
        if widget is None:
            return

        text_value = self._format_formula_result(field, value)
        has_value = bool(text_value.strip())

        if isinstance(widget, QLineEdit):
            widget.blockSignals(True)
            widget.setText(text_value)
            widget.blockSignals(False)
        elif isinstance(widget, QTextEdit):
            widget.blockSignals(True)
            widget.setPlainText(text_value)
            widget.blockSignals(False)
        elif hasattr(widget, "setText"):
            widget.blockSignals(True)
            widget.setText(text_value)
            widget.blockSignals(False)
        elif hasattr(widget, "setValue"):
            numeric_value = self._convert_to_number(value)
            widget.blockSignals(True)
            if numeric_value is not None:
                widget.setValue(numeric_value)
            widget.blockSignals(False)

        widget.setProperty("has_user_value", has_value)

    def _get_value_from_source(self, widget, item):
        if widget is not None:
            if widget.property("is_formula") and widget.property("has_user_value") is False:
                return None
            if widget.property("has_user_value") is False:
                return None
            return self._extract_widget_value(widget)
        if item is not None:
            return item.text().strip()
        return None

    def _convert_to_number(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.strip().replace(",", ".")
            if not cleaned:
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _extract_widget_value(self, widget):
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QTextEdit):
            return widget.toPlainText().strip()
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        return None

    def collect_results(self) -> dict:
        results: dict = {}
        for section in self.profile.sections:
            controls = self.section_controls.get(section.key, {})
            section_result: dict = {}

            if controls.get("type") == "table":
                rows_data = []
                column_fields: list[FunctionalField] = controls["column_fields"]
                table_cells = controls.get("table_cells", {})
                table = controls.get("table")
                for row_idx, row_def in enumerate(controls["row_definitions"]):
                    row_data = {"key": row_def.key, "label": row_def.label, "values": {}}
                    for col_idx, field in enumerate(column_fields):
                        source = table_cells.get((row_def.key, field.key))
                        if source is not None:
                            if isinstance(source, QTableWidgetItem):
                                row_data["values"][field.key] = source.text().strip()
                            else:
                                row_data["values"][field.key] = self._extract_widget_value(source)
                        elif table is not None:
                            cell_widget = table.cellWidget(row_idx, col_idx)
                            if cell_widget is not None:
                                row_data["values"][field.key] = self._extract_widget_value(
                                    cell_widget
                                )
                            else:
                                item = table.item(row_idx, col_idx)
                                row_data["values"][field.key] = (
                                    item.text().strip() if item else None
                                )
                        else:
                            row_data["values"][field.key] = None
                    rows_data.append(row_data)
                section_result["rows"] = rows_data
            else:
                field_values = {}
                for field_key, widget in controls.get("fields", {}).items():
                    field_values[field_key] = self._extract_widget_value(widget)
                section_result["fields"] = field_values

                row_values = {}
                for row_key, row_fields in controls.get("rows", {}).items():
                    row_entry = {}
                    for field_key, widget in row_fields.items():
                        row_entry[field_key] = self._extract_widget_value(widget)
                    row_values[row_key] = row_entry
                if row_values:
                    section_result["rows"] = row_values

            results[section.key] = section_result
        return results

    def collect_results_with_metadata(self) -> dict:
        collected = self.collect_results()
        structured: dict[str, dict] = {}

        for idx, section in enumerate(self.profile.sections):
            section_data: dict = {
                "title": section.title or section.key,
                "section_type": section.section_type,
                "show_in_summary": section.show_in_summary,
                "order": idx,
            }
            raw_section = collected.get(section.key, {})

            if section.section_type == "fields":
                field_entries = []
                raw_fields = raw_section.get("fields", {})
                for field in section.fields:
                    value = raw_fields.get(field.key, "")
                    field_entries.append(
                        {
                            "key": field.key,
                            "label": field.label or field.key.replace("_", " ").title(),
                            "value": value,
                        }
                    )
                section_data["fields"] = field_entries

            else:
                row_entries = []
                row_def_map = {row.key: row for row in section.rows}

                raw_rows = raw_section.get("rows", [])
                if isinstance(raw_rows, dict):
                    raw_rows = [
                        {"key": key, "values": values, "label": key}
                        for key, values in raw_rows.items()
                    ]

                for raw_row in raw_rows:
                    row_key = raw_row.get("key")
                    row_def = row_def_map.get(row_key)
                    values_map = raw_row.get("values", {}) if isinstance(raw_row.get("values", {}), dict) else {}
                    value_entries = []

                    if row_def and row_def.fields:
                        for field in row_def.fields:
                            value_entries.append(
                                {
                                    "key": field.key,
                                    "label": field.label or field.key.replace("_", " ").title(),
                                    "value": values_map.get(field.key, ""),
                                }
                            )
                    else:
                        for key, value in values_map.items():
                            value_entries.append(
                                {
                                    "key": key,
                                    "label": key.replace("_", " ").title(),
                                    "value": value,
                                }
                            )

                    row_entries.append(
                        {
                            "key": row_key,
                            "label": (row_def.label if row_def else raw_row.get("label")) or row_key,
                            "values": value_entries,
                        }
                    )

                section_data["rows"] = row_entries

            structured[section.key] = section_data

        return structured

    def save_verification(self):
        try:
            incomplete_idx = None
            for idx in range(len(self.profile.sections)):
                if self._collect_missing_fields_for_section(idx):
                    incomplete_idx = idx
                    break

            if incomplete_idx is not None:
                self._show_section(incomplete_idx)

            # Valida TUTTI i campi obbligatori prima di salvare
            is_valid, error_message = self._validate_all_sections()
            if not is_valid:
                QMessageBox.warning(
                    self,
                    "Campi Obbligatori Mancanti",
                    error_message,
                )
                return

            if not self._confirm_status_consistency_before_save():
                return
            
            results = self.collect_results()
            structured_results = self.collect_results_with_metadata()
            status = self.status_combo.currentText()
            notes = self.notes_edit.toPlainText().strip()

            verification_code, new_id = services.finalizza_e_salva_verifica_funzionale(
                device_id=self.device_info["id"],
                profile_key=self.profile.profile_key,
                results=results,
                structured_results=structured_results,
                overall_status=status,
                notes=notes,
                mti_info=self.mti_info,
                technician_name=self.technician_name,
                technician_username=self.technician_username,
                device_info=self.device_info,
                used_instruments=self.used_instruments,  # Passa gli strumenti usati
            )
            self.saved_verification_id = new_id
            self.saved_verification_code = verification_code
            self.save_button.setEnabled(False)
            self.save_button.setText("Verifica Salvata!")
            self.generate_pdf_button.setEnabled(True)
            self.print_pdf_button.setEnabled(True)
            if self.parent_window:
                self.parent_window.statusBar().showMessage(
                    f"Verifica funzionale ID {new_id} salvata con successo (Codice: {verification_code}).",
                    5000,
                )
            else:
                QMessageBox.information(
                    self,
                    "Successo",
                    f"Verifica salvata con successo.\nCodice: {verification_code}",
                )
        except Exception as e:
            logging.error("Errore salvataggio verifica funzionale", exc_info=True)
            QMessageBox.critical(
                self,
                "Errore Salvataggio",
                f"Impossibile salvare la verifica funzionale:\n{e}",
            )

    def generate_pdf_report_from_summary(self):
        if not self.saved_verification_id:
            QMessageBox.warning(self, "Attenzione", "È necessario prima salvare la verifica nel database.")
            return

        if not self.device_info:
            QMessageBox.critical(self, "Errore Dati", "Informazioni sul dispositivo non disponibili. Impossibile generare il report.")
            return

        ams_inv = (self.device_info.get('ams_inventory') or '').strip()
        serial_num = (self.device_info.get('serial_number') or '').strip()
        base_name = ams_inv if ams_inv else serial_num
        if not base_name:
            base_name = f"Report_Verifica_{self.saved_verification_id}"
        safe_base_name = re.sub(r'[\\/*?:"<>|]', '_', base_name)
        default_filename = os.path.join(os.getcwd(), f"{safe_base_name} VF.pdf")
        filename, _ = QFileDialog.getSaveFileName(self, "Salva Report PDF", default_filename, "PDF Files (*.pdf)")
        if not filename:
            return
        try:
            services.generate_functional_pdf_report(
                filename,
                verification_id=self.saved_verification_id,
                device_id=self.device_info['id'],
                report_settings=self.report_settings,
            )
            QMessageBox.information(self, "Successo", f"Report generato con successo:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile generare il report funzionale:\n{e}")

    def print_pdf_report_from_summary(self):
        if not self.saved_verification_id:
            QMessageBox.warning(self, "Attenzione", "È necessario prima salvare la verifica nel database.")
            return
        try:
            services.print_functional_pdf_report(
                verification_id=self.saved_verification_id,
                device_id=self.device_info['id'],
                report_settings=self.report_settings,
                parent_widget=self
            )
        except Exception as e:
            logging.error("Errore durante la stampa del report funzionale", exc_info=True)
            QMessageBox.critical(self, "Errore di Stampa", f"Impossibile stampare il report:\n{e}")

    def _handle_finish(self):
        """Gestisce il click sul pulsante Fine, con avviso se la verifica non è salvata."""
        if not self.saved_verification_id:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Verifica non salvata")
            msg_box.setText("La verifica funzionale non è stata salvata. Cosa vuoi fare?")
            msg_box.setIcon(QMessageBox.Question)
            
            btn_save_exit = msg_box.addButton("Salva ed Esci", QMessageBox.AcceptRole)
            btn_exit = msg_box.addButton("Esci senza Salvare", QMessageBox.DestructiveRole)
            btn_cancel = msg_box.addButton("Annulla", QMessageBox.RejectRole)
            
            msg_box.exec()
            
            clicked_button = msg_box.clickedButton()
            
            if clicked_button == btn_save_exit:
                # Prova a salvare la verifica
                try:
                    self.save_verification()
                    if self.saved_verification_id:
                        # Salvataggio riuscito, esci
                        if self.parent_window:
                            self.parent_window.reset_main_ui()
                        else:
                            self.close()
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "Errore di Salvataggio",
                        f"Impossibile salvare la verifica:\n{e}\n\nVuoi comunque uscire senza salvare?",
                    )
                    # Se l'utente vuole comunque uscire, non fare nulla qui
            elif clicked_button == btn_exit:
                # Esci senza salvare
                if self.parent_window:
                    self.parent_window.reset_main_ui()
                else:
                    self.close()
            else:
                # Annulla - non fare nulla
                return
        else:
            # Verifica già salvata, esci normalmente
            if self.parent_window:
                self.parent_window.reset_main_ui()
            else:
                self.close()
