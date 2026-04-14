# app/ui/dialogs/advanced_search_dialog.py

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QGridLayout, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QHeaderView, QAbstractItemView, QDateEdit,
                               QMessageBox, QTableWidgetItem, QComboBox, QCheckBox, QHBoxLayout,
                               QDialogButtonBox, QCompleter, QGroupBox, QFileDialog, QApplication, QProgressBar,
                               QFrame, QSplitter, QSizePolicy, QSpacerItem)
from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtGui import QColor, QBrush
from app import services, config
from app.ui.dialogs.utility_dialogs import SingleCalendarRangeDialog
import qtawesome as qta
import logging
import pandas as pd
import os

class AdvancedSearchDialog(QDialog):
    """
    Finestra di dialogo migliorata per la ricerca avanzata di dispositivi e verifiche.

    Funzionalità:
    - Ricerca su verifiche elettriche, funzionali o entrambe
    - Filtri per reparto, inventario AMS/Cliente, codice verifica, strumento, profilo, intervallo
    - Autocompletamento intelligente
    - Filtri rapidi predefiniti
    - Ordinamento colonne
    - Esportazione risultati in Excel
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ricerca Avanzata")
        self.setWindowState(Qt.WindowMaximized)
        self.setStyleSheet(config.get_current_stylesheet())

        # Variabili di stato
        self.selected_verification_data = None
        self.current_results = []
        self.table_headers = []

        # Layout principale
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # Header con titolo, filtri rapidi e pulsanti azione
        header_layout = self._create_header()
        main_layout.addLayout(header_layout)

        # Criteri di ricerca
        search_group = self._create_search_criteria_group()
        main_layout.addWidget(search_group)

        # Progress bar per ricerche lunghe
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Risultati
        results_group = self._create_results_group()
        main_layout.addWidget(results_group)

        # Pulsanti finestra
        button_layout = self._create_button_box()
        main_layout.addLayout(button_layout)

        # Inizializza autocompletamento
        self._setup_autocompletion()

        # Collegamento segnali
        self._connect_signals()

    def _create_header(self):
        """Crea l'header con titolo, filtri rapidi e pulsanti azione."""
        main_layout = QVBoxLayout()

        # Prima riga: Titolo e pulsanti azione
        top_row = QHBoxLayout()

        title_label = QLabel("<h2>🔍 Ricerca Avanzata</h2>")
        top_row.addWidget(title_label)

        top_row.addStretch()

        # Pulsante esporta
        self.export_button = QPushButton(qta.icon('fa5s.file-excel'), " Esporta")
        self.export_button.setObjectName("editButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_results)
        self.export_button.setToolTip("Esporta i risultati in Excel")
        top_row.addWidget(self.export_button)

        # Pulsante reset
        reset_button = QPushButton(qta.icon('fa5s.eraser'), " Reset")
        reset_button.setObjectName("warningButton")
        reset_button.clicked.connect(self._reset_filters)
        reset_button.setToolTip("Resetta tutti i filtri")
        top_row.addWidget(reset_button)

        main_layout.addLayout(top_row)

        # Seconda riga: Filtri rapidi
        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("<b>Filtri Rapidi:</b>"))

        btn_expired = QPushButton(qta.icon('fa5s.exclamation-triangle'), " Scadute")
        btn_expired.setObjectName("warningButton")
        btn_expired.setToolTip("Dispositivi con verifica scaduta")
        btn_expired.clicked.connect(lambda: self._apply_quick_filter("scadute"))

        btn_expiring = QPushButton(qta.icon('fa5s.clock'), " In Scadenza")
        btn_expiring.setObjectName("secondaryButton")
        btn_expiring.setToolTip("Dispositivi con verifica in scadenza nei prossimi 30 giorni")
        btn_expiring.clicked.connect(lambda: self._apply_quick_filter("in_scadenza"))

        btn_non_conforme = QPushButton(qta.icon('fa5s.times-circle'), " Non Conformi")
        btn_non_conforme.setObjectName("deleteButton")
        btn_non_conforme.setToolTip("Dispositivi con ultima verifica non conforme")
        btn_non_conforme.clicked.connect(lambda: self._apply_quick_filter("non_conforme"))

        btn_annotazione = QPushButton(qta.icon('fa5s.exclamation'), " Con Annotazione")
        btn_annotazione.setObjectName("warningButton")
        btn_annotazione.setToolTip("Verifiche con esito 'Conforme con annotazione'")
        btn_annotazione.clicked.connect(lambda: self._apply_quick_filter("con_annotazione"))

        btn_mai_verificati = QPushButton(qta.icon('fa5s.question-circle'), " Mai Verificati")
        btn_mai_verificati.setObjectName("secondaryButton")
        btn_mai_verificati.setToolTip("Dispositivi mai verificati")
        btn_mai_verificati.clicked.connect(lambda: self._apply_quick_filter("mai_verificati"))

        btn_last_30_days = QPushButton(qta.icon('fa5s.calendar-check'), " Ultimi 30gg")
        btn_last_30_days.setToolTip("Verifiche degli ultimi 30 giorni")
        btn_last_30_days.clicked.connect(lambda: self._apply_quick_filter("ultimi_30"))

        btn_dismessi = QPushButton(qta.icon('fa5s.ban'), " Dismessi")
        btn_dismessi.setObjectName("secondaryButton")
        btn_dismessi.setToolTip("Solo dispositivi dismessi")
        btn_dismessi.clicked.connect(lambda: self._apply_quick_filter("dismessi"))

        btn_oggi = QPushButton(qta.icon('fa5s.calendar-day'), " Oggi")
        btn_oggi.setToolTip("Verifiche eseguite oggi")
        btn_oggi.clicked.connect(lambda: self._apply_quick_filter("oggi"))

        filters_row.addWidget(btn_expired)
        filters_row.addWidget(btn_expiring)
        filters_row.addWidget(btn_non_conforme)
        filters_row.addWidget(btn_annotazione)
        filters_row.addWidget(btn_mai_verificati)
        filters_row.addWidget(btn_last_30_days)
        filters_row.addWidget(btn_dismessi)
        filters_row.addWidget(btn_oggi)
        filters_row.addStretch()

        main_layout.addLayout(filters_row)

        return main_layout

    def _create_search_criteria_group(self):
        """Crea il gruppo con i criteri di ricerca organizzati su 6 colonne."""
        group = QGroupBox("Criteri di Ricerca")
        grid_layout = QGridLayout()
        grid_layout.setSpacing(8)
        grid_layout.setContentsMargins(10, 10, 10, 10)

        # --- Campi di input ---
        self.customer_input = QLineEdit()
        self.customer_input.setPlaceholderText("Nome cliente...")

        self.destination_input = QLineEdit()
        self.destination_input.setPlaceholderText("Nome destinazione...")

        self.department_input = QLineEdit()
        self.department_input.setPlaceholderText("Reparto...")

        self.device_desc_input = QLineEdit()
        self.device_desc_input.setPlaceholderText("Descrizione apparecchio...")

        self.serial_number_input = QLineEdit()
        self.serial_number_input.setPlaceholderText("Numero di serie...")

        self.manufacturer_input = QLineEdit()
        self.manufacturer_input.setPlaceholderText("Marca/Costruttore...")

        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("Modello...")

        self.ams_inventory_input = QLineEdit()
        self.ams_inventory_input.setPlaceholderText("Inventario AMS...")

        self.customer_inventory_input = QLineEdit()
        self.customer_inventory_input.setPlaceholderText("Inventario cliente...")

        self.technician_input = QLineEdit()
        self.technician_input.setPlaceholderText("Nome tecnico...")

        self.verification_code_input = QLineEdit()
        self.verification_code_input.setPlaceholderText("Codice verifica (es. XX-260408-0001-VE)...")

        self.instrument_input = QLineEdit()
        self.instrument_input.setPlaceholderText("Strumento di misura...")

        # --- ComboBox ---
        self.outcome_combo = QComboBox()
        self.outcome_combo.addItems(["QUALSIASI", "CONFORME", "NON CONFORME", "CONFORME CON ANNOTAZIONE", "NON VERIFICATO"])

        self.device_status_combo = QComboBox()
        self.device_status_combo.addItems(["QUALSIASI", "ATTIVO", "DISMESSO"])

        self.verification_type_combo = QComboBox()
        self.verification_type_combo.addItems(["QUALSIASI", "ELETTRICA", "FUNZIONALE"])
        self.verification_type_combo.currentTextChanged.connect(self._on_verification_type_changed)

        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self.profile_combo.setInsertPolicy(QComboBox.NoInsert)
        self._populate_profile_combo()

        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["QUALSIASI", "6", "12", "24", "36", "48", "60"])

        # --- Data range ---
        self.date_range_button = QPushButton(qta.icon('fa5s.calendar-alt'), " Seleziona Periodo")
        self.date_range_button.setObjectName("secondaryButton")
        self.date_range_button.clicked.connect(self._select_date_range)
        self.date_range_label = QLabel("<i>Nessun periodo selezionato</i>")
        self.start_date = None
        self.end_date = None

        # === Layout griglia 6 colonne (label, input) x 3 ===
        row = 0
        # Riga 0: Cliente | Destinazione | Reparto
        grid_layout.addWidget(QLabel("<b>Cliente:</b>"), row, 0)
        grid_layout.addWidget(self.customer_input, row, 1)
        grid_layout.addWidget(QLabel("<b>Destinazione:</b>"), row, 2)
        grid_layout.addWidget(self.destination_input, row, 3)
        grid_layout.addWidget(QLabel("<b>Reparto:</b>"), row, 4)
        grid_layout.addWidget(self.department_input, row, 5)

        row += 1
        # Riga 1: Apparecchio | Matricola | Marca
        grid_layout.addWidget(QLabel("<b>Apparecchio:</b>"), row, 0)
        grid_layout.addWidget(self.device_desc_input, row, 1)
        grid_layout.addWidget(QLabel("<b>Matricola:</b>"), row, 2)
        grid_layout.addWidget(self.serial_number_input, row, 3)
        grid_layout.addWidget(QLabel("<b>Marca:</b>"), row, 4)
        grid_layout.addWidget(self.manufacturer_input, row, 5)

        row += 1
        # Riga 2: Modello | Inv. AMS | Inv. Cliente
        grid_layout.addWidget(QLabel("<b>Modello:</b>"), row, 0)
        grid_layout.addWidget(self.model_input, row, 1)
        grid_layout.addWidget(QLabel("<b>Inv. AMS:</b>"), row, 2)
        grid_layout.addWidget(self.ams_inventory_input, row, 3)
        grid_layout.addWidget(QLabel("<b>Inv. Cliente:</b>"), row, 4)
        grid_layout.addWidget(self.customer_inventory_input, row, 5)

        row += 1
        # Riga 3: Tecnico | Codice Verifica | Strumento
        grid_layout.addWidget(QLabel("<b>Tecnico:</b>"), row, 0)
        grid_layout.addWidget(self.technician_input, row, 1)
        grid_layout.addWidget(QLabel("<b>Codice Verifica:</b>"), row, 2)
        grid_layout.addWidget(self.verification_code_input, row, 3)
        grid_layout.addWidget(QLabel("<b>Strumento:</b>"), row, 4)
        grid_layout.addWidget(self.instrument_input, row, 5)

        row += 1
        # Riga 4: Esito | Tipo Verifica | Profilo
        grid_layout.addWidget(QLabel("<b>Esito:</b>"), row, 0)
        grid_layout.addWidget(self.outcome_combo, row, 1)
        grid_layout.addWidget(QLabel("<b>Tipo Verifica:</b>"), row, 2)
        grid_layout.addWidget(self.verification_type_combo, row, 3)
        grid_layout.addWidget(QLabel("<b>Profilo:</b>"), row, 4)
        grid_layout.addWidget(self.profile_combo, row, 5)

        row += 1
        # Riga 5: Stato Dispositivo | Int. Verifica | Periodo
        grid_layout.addWidget(QLabel("<b>Stato Disp.:</b>"), row, 0)
        grid_layout.addWidget(self.device_status_combo, row, 1)
        grid_layout.addWidget(QLabel("<b>Int. Verifica (mesi):</b>"), row, 2)
        grid_layout.addWidget(self.interval_combo, row, 3)

        date_layout = QHBoxLayout()
        date_layout.addWidget(self.date_range_button)
        date_layout.addWidget(self.date_range_label)
        date_layout.addStretch()
        grid_layout.addWidget(QLabel("<b>Periodo:</b>"), row, 4)
        grid_layout.addLayout(date_layout, row, 5)

        # Imposta colonne con stretch uniforme per le colonne input
        grid_layout.setColumnStretch(1, 1)
        grid_layout.setColumnStretch(3, 1)
        grid_layout.setColumnStretch(5, 1)

        group.setLayout(grid_layout)
        return group

    def _populate_profile_combo(self, filter_type=None):
        """Popola il combobox profili con tutti i profili elettrici e funzionali."""
        self.profile_combo.clear()
        self.profile_combo.addItem("QUALSIASI", "QUALSIASI")

        # Profili elettrici
        if filter_type in (None, "QUALSIASI", "ELETTRICA"):
            electrical_profiles = config.PROFILES
            if electrical_profiles:
                self.profile_combo.addItem("── Profili Elettrici ──", None)
                idx = self.profile_combo.count() - 1
                self.profile_combo.model().item(idx).setEnabled(False)
                for key, profile in sorted(electrical_profiles.items(), key=lambda x: x[1].name):
                    self.profile_combo.addItem(f"  ⚡ {profile.name}", key)

        # Profili funzionali
        if filter_type in (None, "QUALSIASI", "FUNZIONALE"):
            functional_profiles = config.FUNCTIONAL_PROFILES
            if functional_profiles:
                self.profile_combo.addItem("── Profili Funzionali ──", None)
                idx = self.profile_combo.count() - 1
                self.profile_combo.model().item(idx).setEnabled(False)
                for key, profile in sorted(functional_profiles.items(), key=lambda x: x[1].name):
                    self.profile_combo.addItem(f"  🔧 {profile.name}", key)

        # Imposta completer
        if self.profile_combo.completer():
            self.profile_combo.completer().setFilterMode(Qt.MatchContains)
            self.profile_combo.completer().setCaseSensitivity(Qt.CaseInsensitive)

    def _on_verification_type_changed(self, text):
        """Aggiorna il combobox profili quando cambia il tipo di verifica."""
        self._populate_profile_combo(filter_type=text)

    def _create_results_group(self):
        """Crea il gruppo con la tabella dei risultati."""
        group = QGroupBox("Risultati")
        layout = QVBoxLayout()

        # Info bar
        info_layout = QHBoxLayout()
        self.results_count_label = QLabel("<i>Nessuna ricerca effettuata</i>")
        info_layout.addWidget(self.results_count_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)

        # Tabella
        self.results_table = QTableWidget()
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.itemDoubleClicked.connect(self.accept_selection)
        layout.addWidget(self.results_table)

        group.setLayout(layout)
        return group

    def _create_button_box(self):
        """Crea i pulsanti Cerca, OK e Annulla."""
        layout = QHBoxLayout()

        self.search_button = QPushButton(qta.icon('fa5s.search'), " Cerca")
        self.search_button.setObjectName("autoButton")
        self.search_button.clicked.connect(self._perform_search)
        self.search_button.setMinimumHeight(40)

        layout.addWidget(self.search_button)
        layout.addStretch()

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.button(QDialogButtonBox.Ok).setText("Apri Selezionato")
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
        self.button_box.button(QDialogButtonBox.Cancel).setText("Chiudi")

        layout.addWidget(self.button_box)

        return layout

    def _connect_signals(self):
        """Collega tutti i segnali."""
        self.button_box.accepted.connect(self.accept_selection)
        self.button_box.rejected.connect(self.reject)
        self.results_table.itemSelectionChanged.connect(self._on_selection_changed)

        # Enter nei campi di ricerca attiva la ricerca
        for input_field in [self.customer_input, self.destination_input, self.department_input,
                            self.device_desc_input, self.serial_number_input,
                            self.manufacturer_input, self.model_input,
                            self.ams_inventory_input, self.customer_inventory_input,
                            self.technician_input, self.verification_code_input,
                            self.instrument_input]:
            input_field.returnPressed.connect(self._perform_search)

    def _setup_autocompletion(self):
        """Configura l'autocompletamento per i campi di input."""
        try:
            def _value(row, key):
                if row is None:
                    return None
                if isinstance(row, dict):
                    return row.get(key)
                try:
                    return row[key]
                except Exception:
                    return None

            def _apply_completer(widget, items):
                if items:
                    completer = QCompleter(items, self)
                    completer.setCaseSensitivity(Qt.CaseInsensitive)
                    completer.setFilterMode(Qt.MatchContains)
                    widget.setCompleter(completer)

            # Clienti
            customers = services.get_all_customers()
            customer_names = [name for name in (_value(c, 'name') for c in customers) if name]
            _apply_completer(self.customer_input, customer_names)

            # Costruttori
            manufacturers = services.get_unique_manufacturers()
            manufacturer_names = [name for name in (_value(m, 'manufacturer') for m in manufacturers) if name]
            _apply_completer(self.manufacturer_input, manufacturer_names)

            # Modelli
            models = services.get_unique_models()
            model_names = [name for name in (_value(m, 'model') for m in models) if name]
            _apply_completer(self.model_input, model_names)

            # Reparti
            departments = services.get_unique_departments()
            department_names = [name for name in (_value(d, 'department') for d in departments) if name]
            _apply_completer(self.department_input, department_names)

            # Tecnici
            technicians = services.get_unique_technicians()
            technician_names = [name for name in (_value(t, 'technician_name') for t in technicians) if name]
            _apply_completer(self.technician_input, technician_names)

        except Exception as e:
            logging.warning(f"Impossibile configurare l'autocompletamento: {e}")

    def _select_date_range(self):
        """Apre il dialogo per selezionare l'intervallo di date."""
        dialog = SingleCalendarRangeDialog(self)
        if dialog.exec():
            self.start_date, self.end_date = dialog.get_date_range()
            if self.start_date and self.end_date:
                start = QDate.fromString(self.start_date, "yyyy-MM-dd").toString("dd/MM/yyyy")
                end = QDate.fromString(self.end_date, "yyyy-MM-dd").toString("dd/MM/yyyy")
                self.date_range_label.setText(f"<b>Dal {start} al {end}</b>")

    def _apply_quick_filter(self, filter_type):
        """Applica un filtro rapido predefinito."""
        from datetime import date, timedelta

        self._reset_filters()

        if filter_type == "scadute":
            self.end_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
            self.start_date = "2000-01-01"
            self.date_range_label.setText("<b>Verifiche scadute (fino a ieri)</b>")
            self._perform_search()

        elif filter_type == "in_scadenza":
            today = date.today()
            self.start_date = today.strftime("%Y-%m-%d")
            self.end_date = (today + timedelta(days=30)).strftime("%Y-%m-%d")
            start = today.strftime("%d/%m/%Y")
            end = (today + timedelta(days=30)).strftime("%d/%m/%Y")
            self.date_range_label.setText(f"<b>Dal {start} al {end}</b>")
            self._perform_search()

        elif filter_type == "non_conforme":
            self.outcome_combo.setCurrentText("NON CONFORME")
            self._perform_search()

        elif filter_type == "con_annotazione":
            self.outcome_combo.setCurrentText("CONFORME CON ANNOTAZIONE")
            self._perform_search()

        elif filter_type == "mai_verificati":
            self.outcome_combo.setCurrentText("NON VERIFICATO")
            self._perform_search()

        elif filter_type == "ultimi_30":
            today = date.today()
            self.start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
            self.end_date = today.strftime("%Y-%m-%d")
            start = (today - timedelta(days=30)).strftime("%d/%m/%Y")
            end = today.strftime("%d/%m/%Y")
            self.date_range_label.setText(f"<b>Dal {start} al {end}</b>")
            self._perform_search()

        elif filter_type == "dismessi":
            self.device_status_combo.setCurrentText("DISMESSO")
            self._perform_search()

        elif filter_type == "oggi":
            today = date.today()
            self.start_date = today.strftime("%Y-%m-%d")
            self.end_date = today.strftime("%Y-%m-%d")
            self.date_range_label.setText(f"<b>Oggi ({today.strftime('%d/%m/%Y')})</b>")
            self._perform_search()

    def _reset_filters(self):
        """Resetta tutti i filtri di ricerca."""
        self.customer_input.clear()
        self.destination_input.clear()
        self.department_input.clear()
        self.device_desc_input.clear()
        self.serial_number_input.clear()
        self.manufacturer_input.clear()
        self.model_input.clear()
        self.ams_inventory_input.clear()
        self.customer_inventory_input.clear()
        self.technician_input.clear()
        self.verification_code_input.clear()
        self.instrument_input.clear()
        self.outcome_combo.setCurrentIndex(0)
        self.device_status_combo.setCurrentIndex(0)
        self.verification_type_combo.setCurrentIndex(0)
        self.profile_combo.setCurrentIndex(0)
        self.interval_combo.setCurrentIndex(0)
        self.start_date = None
        self.end_date = None
        self.date_range_label.setText("<i>Nessun periodo selezionato</i>")
        self.results_table.setRowCount(0)
        self.results_count_label.setText("<i>Nessuna ricerca effettuata</i>")
        self.export_button.setEnabled(False)

    def _perform_search(self):
        """Esegue la ricerca in base ai criteri inseriti."""
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        QApplication.setOverrideCursor(Qt.WaitCursor)

        # Recupera il profile_key dal combobox
        profile_key = self.profile_combo.currentData()
        if profile_key is None:
            profile_key = "QUALSIASI"

        criteria = {
            "customer_name": self.customer_input.text().strip(),
            "destination_name": self.destination_input.text().strip(),
            "department": self.department_input.text().strip(),
            "device_description": self.device_desc_input.text().strip(),
            "serial_number": self.serial_number_input.text().strip(),
            "manufacturer": self.manufacturer_input.text().strip(),
            "model": self.model_input.text().strip(),
            "ams_inventory": self.ams_inventory_input.text().strip(),
            "customer_inventory": self.customer_inventory_input.text().strip(),
            "technician_name": self.technician_input.text().strip(),
            "verification_code": self.verification_code_input.text().strip(),
            "instrument": self.instrument_input.text().strip(),
            "outcome": self.outcome_combo.currentText(),
            "device_status": self.device_status_combo.currentText(),
            "verification_type": self.verification_type_combo.currentText(),
            "profile_key": profile_key,
            "verification_interval": self.interval_combo.currentText(),
            "start_date": self.start_date,
            "end_date": self.end_date,
        }

        try:
            results = services.advanced_search(criteria)
            self.current_results = results
            self._populate_table(results)

        except Exception as e:
            logging.error(f"Errore durante la ricerca avanzata: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Si è verificato un errore durante la ricerca:\n{str(e)}")

        finally:
            QApplication.restoreOverrideCursor()
            self.progress_bar.setVisible(False)

    def _populate_table(self, data):
        """Popola la tabella dei risultati con i dati forniti."""
        self.results_table.setSortingEnabled(False)

        if not data:
            self.results_table.setRowCount(0)
            self.results_table.setColumnCount(0)
            self.results_count_label.setText("<b>Nessun risultato trovato</b>")
            self.export_button.setEnabled(False)
            QMessageBox.information(self, "Nessun Risultato", "La ricerca non ha prodotto risultati.")
            return

        headers = list(data[0].keys())
        self.table_headers = headers

        self.results_table.setColumnCount(len(headers))
        self.results_table.setHorizontalHeaderLabels([h.replace("_", " ").title() for h in headers])
        self.results_table.setRowCount(len(data))

        # Colori per esiti
        color_conforme = QColor("#A3BE8C")
        color_non_conforme = QColor("#BF616A")
        color_annotazione = QColor("#EBCB8B")
        color_non_verificato = QColor("#D8DEE9")
        color_elettrica = QColor("#88C0D0")
        color_funzionale = QColor("#B48EAD")

        for row_idx, row_data in enumerate(data):
            for col_idx, key in enumerate(headers):
                value = row_data[key] if row_data[key] is not None else ""
                item = QTableWidgetItem(str(value))

                # Colora gli esiti
                if key == "Esito":
                    if value == "CONFORME":
                        item.setBackground(color_conforme)
                    elif value == "NON CONFORME":
                        item.setBackground(color_non_conforme)
                    elif value == "CONFORME CON ANNOTAZIONE":
                        item.setBackground(color_annotazione)
                    elif value == "NON VERIFICATO":
                        item.setBackground(color_non_verificato)

                # Colora il tipo verifica
                if key == "Tipo":
                    if value == "ELETTRICA":
                        item.setBackground(color_elettrica)
                    elif value == "FUNZIONALE":
                        item.setBackground(color_funzionale)

                # Colora lo stato dispositivo
                if key == "Stato":
                    if value == "DISMESSO":
                        item.setForeground(QBrush(QColor("blue")))

                self.results_table.setItem(row_idx, col_idx, item)

        # Nascondi colonne ID
        for col_name in ['device_id', 'verification_id']:
            try:
                col_idx = self.table_headers.index(col_name)
                self.results_table.hideColumn(col_idx)
            except ValueError:
                pass

        # Ridimensiona colonne
        self.results_table.resizeColumnsToContents()
        self.results_table.setSortingEnabled(True)

        # Aggiorna info
        self.results_count_label.setText(f"<b>Trovati {len(data)} risultati</b>")
        self.export_button.setEnabled(True)
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)

    def _on_selection_changed(self):
        """Gestisce il cambio di selezione nella tabella."""
        has_selection = len(self.results_table.selectionModel().selectedRows()) > 0
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(has_selection)

    def _export_results(self):
        """Esporta i risultati della ricerca in Excel."""
        if not self.current_results:
            QMessageBox.warning(self, "Nessun Risultato", "Non ci sono risultati da esportare.")
            return

        default_filename = f"Ricerca_Avanzata_{QDate.currentDate().toString('yyyyMMdd')}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Esporta Risultati Ricerca",
            os.path.join(os.path.expanduser("~"), "Desktop", default_filename),
            "Excel Files (*.xlsx)"
        )

        if not file_path:
            return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)

            df = pd.DataFrame(self.current_results)

            # Rimuovi colonne ID
            columns_to_drop = [col for col in ['device_id', 'verification_id'] if col in df.columns]
            if columns_to_drop:
                df = df.drop(columns=columns_to_drop)

            # Rinomina colonne
            df.columns = [col.replace("_", " ").title() for col in df.columns]

            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Risultati')

                worksheet = writer.sheets['Risultati']
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width

            QApplication.restoreOverrideCursor()
            QMessageBox.information(
                self,
                "Esportazione Completata",
                f"Risultati esportati con successo in:\n{file_path}\n\n{len(self.current_results)} record esportati."
            )

        except Exception as e:
            QApplication.restoreOverrideCursor()
            logging.error(f"Errore durante l'esportazione: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore Esportazione", f"Impossibile esportare i risultati:\n{str(e)}")

    def accept_selection(self):
        """Accetta la selezione corrente e chiude il dialogo."""
        selected_rows = self.results_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Selezione Mancante", "Seleziona una riga dalla tabella dei risultati.")
            return

        selected_row_index = selected_rows[0].row()

        try:
            device_id_col = self.table_headers.index('device_id')
            verification_id_col = self.table_headers.index('verification_id')

            device_id = int(self.results_table.item(selected_row_index, device_id_col).text())
            verification_id_text = self.results_table.item(selected_row_index, verification_id_col).text()

            verification_id = int(verification_id_text) if verification_id_text and verification_id_text.strip() else None

            # Determina il tipo di verifica selezionata
            verification_type = None
            try:
                type_col = self.table_headers.index('Tipo')
                type_text = self.results_table.item(selected_row_index, type_col).text()
                verification_type = type_text.strip().upper() if type_text else None
            except (ValueError, AttributeError):
                pass

            self.selected_verification_data = {
                'device_id': device_id,
                'verification_id': verification_id,
                'verification_type': verification_type
            }
            self.accept()

        except Exception as e:
            logging.error(f"Errore durante la selezione: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile aprire la selezione:\n{str(e)}")
