import os
import logging
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox, QGridLayout,
    QVBoxLayout, QGroupBox, QTableWidget, QTableWidgetItem, QHBoxLayout, QComboBox, QPushButton, QApplication, QStyle, QLabel, QCompleter, QFileDialog, QInputDialog, QHeaderView)
from PySide6.QtCore import Qt, QStringListModel
from app.data_models import AppliedPart
from app.config import format_date_it
from app.ui.dialogs.utility_dialogs import DeviceSearchDialog
from app.ui.dialogs.applied_parts_presets_dialog import AppliedPartsPresetsDialog
from app import services
import qtawesome as qta

class CustomerDialog(QDialog):
    def __init__(self, customer_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dettagli Cliente")
        data = customer_data or {}
        layout = QFormLayout(self)
        self.name_edit = QLineEdit(data.get('name', ''))
        self.address_edit = QLineEdit(data.get('address', ''))
        self.phone_edit = QLineEdit(data.get('phone', ''))
        self.email_edit = QLineEdit(data.get('email', ''))
        layout.addRow("Nome:", self.name_edit)
        layout.addRow("Indirizzo:", self.address_edit)
        layout.addRow("Telefono:", self.phone_edit)
        layout.addRow("Email:", self.email_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        return { "name": self.name_edit.text().strip(), "address": self.address_edit.text().strip(),
                 "phone": self.phone_edit.text().strip(), "email": self.email_edit.text().strip() }
    
class DeviceDialog(QDialog):
    def __init__(self, customer_id, destination_id=None, device_data=None, is_copy=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dettagli Dispositivo")
        self.AP_CODE_SEQUENCE = ["RA", "LL", "LA", "RL", "V1", "V2", "V3", "V4", "V5", "V6"]
        
        data = device_data or {}
        self.customer_id = customer_id
        self.destination_id = destination_id
        self.is_new_device = device_data is None or is_copy
        self._functional_profile_user_override = False
        self._suppress_functional_profile_signal = False
        self._profile_user_override = False
        self._suppress_profile_signal = False

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(14, 12, 14, 12)
        
        # Layout orizzontale per i pulsanti di acquisizione rapida
        top_bar_layout = QHBoxLayout()
        top_bar_layout.setSpacing(8)
        
        self.copy_button = QPushButton(qta.icon('fa5s.copy'), " Copia dati da un dispositivo esistente...")
        self.copy_button.clicked.connect(self.open_copy_search)
        top_bar_layout.addWidget(self.copy_button)
        top_bar_layout.addStretch()
        main_layout.addLayout(top_bar_layout)
        
        if device_data and not is_copy:
            self.copy_button.hide()

        # --- SEZIONE UDI ---
        udi_group = QGroupBox("COMPILAZIONE RAPIDA TRAMITE CODICE UDI / BARCODE")
        udi_layout = QHBoxLayout(udi_group)
        udi_layout.setContentsMargins(8, 6, 8, 6)
        udi_layout.setSpacing(6)
        
        self.udi_input = QLineEdit()
        self.udi_input.setPlaceholderText("Scansiona o incolla il codice UDI / barcode qui...")
        self.udi_input.setMinimumHeight(32)
        self.udi_input.returnPressed.connect(self._lookup_udi)
        udi_layout.addWidget(self.udi_input, 1)

        self.udi_lookup_btn = QPushButton(qta.icon('fa5s.search'), " Cerca")
        self.udi_lookup_btn.setMinimumHeight(32)
        self.udi_lookup_btn.setToolTip("Cerca informazioni dispositivo dal codice UDI")
        self.udi_lookup_btn.clicked.connect(self._lookup_udi)
        udi_layout.addWidget(self.udi_lookup_btn)

        # Pulsante scansione da telefono (usa il QR scanner server già attivo)
        self.udi_phone_btn = QPushButton(qta.icon('fa5s.mobile-alt'), " 📱 Scansiona")
        self.udi_phone_btn.setMinimumHeight(32)
        self.udi_phone_btn.setToolTip("Ricevi codice UDI dall'app VScanner sul telefono")
        self.udi_phone_btn.setCheckable(True)
        self.udi_phone_btn.clicked.connect(self._toggle_phone_scan_listener)
        udi_layout.addWidget(self.udi_phone_btn)

        self.udi_status_label = QLabel("")
        udi_layout.addWidget(self.udi_status_label)

        main_layout.addWidget(udi_group)
        self._phone_scan_connected = False
        if device_data and not is_copy:
            udi_group.hide()
        
        if is_copy:
            data['serial_number'] = ''
            data['customer_inventory'] = ''
            data['ams_inventory'] = ''

        self.profile_combo = QComboBox()
        self.functional_profile_combo = QComboBox()

        # Popoliamo i ComboBox con i profili caricati all'avvio
        from app import config
        self.profile_combo.addItem("— Nessun profilo —", None)
        for key, profile in config.PROFILES.items():
            self.profile_combo.addItem(profile.name, key) # Mostra il nome, ma salva la chiave

        self.functional_profile_combo.addItem("— Nessun profilo —", None)
        for key, profile in config.FUNCTIONAL_PROFILES.items():
            self.functional_profile_combo.addItem(profile.name, key)

        # Se siamo in modalità modifica, preselezioniamo il profilo salvato
        if device_data and device_data.get('default_profile_key'):
            profile_key_to_select = device_data['default_profile_key']
            index = self.profile_combo.findData(profile_key_to_select)
            if index != -1:
                # Impostazione programmatica: non deve contare come scelta manuale
                self._suppress_profile_signal = True
                try:
                    self.profile_combo.setCurrentIndex(index)
                finally:
                    self._suppress_profile_signal = False

        if device_data and device_data.get('default_functional_profile_key'):
            func_key_to_select = device_data['default_functional_profile_key']
            index = self.functional_profile_combo.findData(func_key_to_select)
            if index != -1:
                self.functional_profile_combo.setCurrentIndex(index)

        self.destination_combo = QComboBox()
        destinations = services.database.get_destinations_for_customer(self.customer_id)
        for dest in destinations:
            self.destination_combo.addItem(dest['name'], dest['id'])
    
        id_to_select = device_data.get('destination_id') if device_data else destination_id
        if id_to_select is not None:
            index = self.destination_combo.findData(id_to_select)
            if index != -1:
                self.destination_combo.setCurrentIndex(index)
        if device_data and device_data.get('destination_id'):
            destination_id_to_select = device_data['destination_id']
        
            # 1. Trova l'indice dell'elemento che ha il 'destination_id' corretto
            index = self.destination_combo.findData(destination_id_to_select)
        
            # 2. Se l'indice è valido (diverso da -1), impostalo come corrente
            if index != -1:
                self.destination_combo.setCurrentIndex(index)

        # --- LAYOUT A GRIGLIA A DUE COLONNE ---
        grid_layout = QGridLayout()
        grid_layout.setSpacing(8)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        
        self.serial_edit = QLineEdit(data.get('serial_number', ''))
        self.desc_edit = QLineEdit(data.get('description', ''))
        self.setup_description_completer()
        self.mfg_edit = QLineEdit(data.get('manufacturer', '').upper())
        self.model_edit = QLineEdit(data.get('model', '').upper())
        self.department_edit = QLineEdit(data.get('department', ''))
        self.ams_inv_edit = QLineEdit(data.get('ams_inventory', ''))
        self.customer_inv_edit = QLineEdit(data.get('customer_inventory', ''))
        
        self.verification_interval_combo = QComboBox()
        self.verification_interval_combo.addItems(["Nessuno", "6", "12", "24", "36"])
        if data.get('verification_interval') is not None:
            self.verification_interval_combo.setCurrentText(str(data['verification_interval']))

        # Riga 0: Destinazione / Sede
        grid_layout.addWidget(QLabel("DESTINAZIONE / SEDE:"), 0, 0)
        grid_layout.addWidget(self.destination_combo, 0, 1, 1, 3)
        # Riga 1: Descrizione e Costruttore
        grid_layout.addWidget(QLabel("DESCRIZIONE:"), 1, 0); grid_layout.addWidget(self.desc_edit, 1, 1)
        grid_layout.addWidget(QLabel("COSTRUTTORE:"), 1, 2); grid_layout.addWidget(self.mfg_edit, 1, 3)
        # Riga 2: Modello e Seriale
        grid_layout.addWidget(QLabel("MODELLO:"), 2, 0); grid_layout.addWidget(self.model_edit, 2, 1)
        grid_layout.addWidget(QLabel("NUMERO DI SERIE:"), 2, 2); grid_layout.addWidget(self.serial_edit, 2, 3)
        # Riga 3: Reparto e Profilo VE
        grid_layout.addWidget(QLabel("REPARTO (DETTAGLIO):"), 3, 0); grid_layout.addWidget(self.department_edit, 3, 1)
        grid_layout.addWidget(QLabel("PROFILO VE DEFAULT:"), 3, 2); grid_layout.addWidget(self.profile_combo, 3, 3)
        # Riga 4: Inventario AMS e Profilo Funzionale
        grid_layout.addWidget(QLabel("INVENTARIO AMS:"), 4, 0); grid_layout.addWidget(self.ams_inv_edit, 4, 1)
        grid_layout.addWidget(QLabel("PROFILO VF DEFAULT:"), 4, 2); grid_layout.addWidget(self.functional_profile_combo, 4, 3)
        # Riga 5: Intervallo verifica e Inventario Cliente
        grid_layout.addWidget(QLabel("INTERVALLO (MESI):"), 5, 0); grid_layout.addWidget(self.verification_interval_combo, 5, 1)
        grid_layout.addWidget(QLabel("INVENTARIO CLIENTE:"), 5, 2); grid_layout.addWidget(self.customer_inv_edit, 5, 3)

        main_layout.addLayout(grid_layout)
        
        pa_group = QGroupBox("PARTI APPLICATE")
        pa_layout = QVBoxLayout(pa_group)
        pa_layout.setSpacing(6)
        pa_layout.setContentsMargins(10, 8, 10, 8)

        # --- Barra Preset Parti Applicate ---
        preset_bar = QHBoxLayout()
        preset_bar.setSpacing(6)
        preset_bar.addWidget(QLabel("<b>📦 Preset:</b>"))
        
        self.pa_preset_combo = QComboBox()
        self.pa_preset_combo.setMinimumWidth(220)
        preset_bar.addWidget(self.pa_preset_combo, 1)

        self.btn_apply_preset = QPushButton(qta.icon('fa5s.check', color='#16a34a'), " Applica")
        self.btn_apply_preset.setToolTip("Carica le parti applicate del preset selezionato")
        self.btn_apply_preset.clicked.connect(self._apply_selected_preset)
        preset_bar.addWidget(self.btn_apply_preset)

        self.btn_save_as_preset = QPushButton(qta.icon('fa5s.save', color='#2563eb'), " Salva come Preset...")
        self.btn_save_as_preset.setToolTip("Salva le parti applicate attuali come nuovo preset")
        self.btn_save_as_preset.clicked.connect(self._save_as_preset)
        preset_bar.addWidget(self.btn_save_as_preset)

        self.btn_manage_presets = QPushButton(qta.icon('fa5s.cog'), " Gestisci...")
        self.btn_manage_presets.setToolTip("Apri il gestore dei preset delle parti applicate")
        self.btn_manage_presets.clicked.connect(self._open_manage_presets)
        preset_bar.addWidget(self.btn_manage_presets)

        pa_layout.addLayout(preset_bar)

        self.applied_parts = [AppliedPart(**pa_data) for pa_data in data.get('applied_parts', [])]
        self.pa_table = QTableWidget(0, 3)
        self.pa_table.setHorizontalHeaderLabels(["NOME DESCRITTIVO", "TIPO", "CODICE STRUMENTO"])
        self.pa_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.pa_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.pa_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.pa_table.horizontalHeader().setMinimumSectionSize(110)
        self.pa_table.setMinimumHeight(180)
        self.pa_table.setAlternatingRowColors(True)
        self.pa_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.pa_table.setSelectionMode(QTableWidget.SingleSelection)
        pa_layout.addWidget(self.pa_table, 1)
        
        # --- Barra compatta inserimento ed eliminazione P.A. ---
        add_pa_layout = QHBoxLayout()
        add_pa_layout.setSpacing(6)
        
        add_pa_layout.addWidget(QLabel("<b>NOME:</b>"))
        self.pa_name_input = QLineEdit()
        self.pa_name_input.setPlaceholderText("Nome descrittivo (es. ECG Torace, SpO2, Sonda...)")
        self.pa_name_input.returnPressed.connect(self.add_pa)
        add_pa_layout.addWidget(self.pa_name_input, 1)
        
        add_pa_layout.addWidget(QLabel("<b>TIPO:</b>"))
        self.pa_type_selector = QComboBox()
        self.pa_type_selector.addItems(["B", "BF", "CF"])
        self.pa_type_selector.setCurrentText("BF")
        add_pa_layout.addWidget(self.pa_type_selector)
        
        add_pa_btn = QPushButton(qta.icon('fa5s.plus-circle', color='#16a34a'), " Aggiungi P.A.")
        add_pa_btn.clicked.connect(self.add_pa)
        add_pa_layout.addWidget(add_pa_btn)

        delete_pa_btn = QPushButton(qta.icon('fa5s.trash-alt', color='#dc2626'), " Elimina Selezionata")
        delete_pa_btn.clicked.connect(self.delete_pa)
        add_pa_layout.addWidget(delete_pa_btn)
        
        pa_layout.addLayout(add_pa_layout)

        main_layout.addWidget(pa_group, 1)
        self.load_pa_table()
        self._refresh_presets_combo()
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        # Crea e configura i completer
        self.manufacturer_completer = QCompleter(self)
        self.model_completer = QCompleter(self)

        # Imposta le proprietà dei completer
        for completer in [self.manufacturer_completer, self.model_completer]:
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            completer.setCompletionMode(QCompleter.PopupCompletion)

        # Assegna i completer ai campi
        self.mfg_edit.setCompleter(self.manufacturer_completer)
        self.model_edit.setCompleter(self.model_completer)

        # Carica i dati per l'autocompletamento
        self.load_completion_data()

        # Collegamenti dinamici per i suggerimenti profili
        self.desc_edit.textChanged.connect(self._handle_description_changed)
        self.mfg_edit.textChanged.connect(self._handle_profile_suggestion_trigger)
        self.model_edit.textChanged.connect(self._handle_profile_suggestion_trigger)
        self.functional_profile_combo.currentIndexChanged.connect(
            self._on_functional_profile_combo_changed
        )
        self.profile_combo.currentIndexChanged.connect(
            self._on_profile_combo_changed
        )
        self.showMaximized()

    def _validate_required_fields(self):
        """
        Valida i campi obbligatori prima di salvare.
        Su richiesta:
        - DESCRIZIONE e COSTRUTTORE sono obbligatori
        - NUMERO DI SERIE e MODELLO NON sono obbligatori
        """
        desc = (self.desc_edit.text() or "").strip()
        mfg = (self.mfg_edit.text() or "").strip()

        missing = []
        if not desc:
            missing.append("DESCRIZIONE")
        if not mfg:
            missing.append("COSTRUTTORE")

        if missing:
            fields = ", ".join(missing)
            QMessageBox.warning(
                self,
                "DATI MANCANTI",
                f"I seguenti campi sono obbligatori e devono essere compilati:\n\n{fields}"
            )
            return False

        return True

    def load_completion_data(self):
        """Carica i dati per l'autocompletamento."""
        try:
            # Carica i dati per i costruttori
            manufacturers = services.get_unique_manufacturers()
            manufacturer_list = [m['manufacturer'] for m in manufacturers]
            manufacturer_model = QStringListModel(manufacturer_list)
            self.manufacturer_completer.setModel(manufacturer_model)

            # Carica i dati per i modelli
            models = services.get_unique_models()
            model_list = [m['model'] for m in models]
            model_model = QStringListModel(model_list)
            self.model_completer.setModel(model_model)

        except Exception as e:
            logging.error(f"Errore nel caricamento dei dati di completamento: {e}")
            
    def setup_description_completer(self):
        """Imposta l'autocompletamento per il campo descrizione."""
        try:
            descriptions = services.get_all_unique_device_descriptions()
            if not descriptions:
                self.desc_edit.setToolTip("Nessun suggerimento disponibile: non ci sono descrizioni salvate.")
                if not (self.desc_edit.placeholderText() or "").strip():
                    self.desc_edit.setPlaceholderText("Inserisci descrizione (nessun suggerimento disponibile)")
                return

            self.desc_edit.setToolTip("Digita per vedere i suggerimenti esistenti.")
            self.description_completer = QCompleter(descriptions, self)
            self.description_completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.description_completer.setFilterMode(Qt.MatchContains)
            self.description_completer.setCompletionMode(QCompleter.PopupCompletion)
            self.desc_edit.setCompleter(self.description_completer)
        except Exception as e:
            logging.error(f"Impossibile caricare i suggerimenti per la descrizione: {e}")

    def _handle_description_changed(self, text: str):
        """
        Gestisce i cambi di descrizione:
        - prova a suggerire profili in base alla descrizione
        - mantiene anche la vecchia logica che mappa descrizione -> device_type dei profili funzionali
        """
        if not self.is_new_device:
            return
        if self._functional_profile_user_override:
            return

        # 1) Usa la nuova logica di suggerimento profili (DB) anche solo con la descrizione
        self._handle_profile_suggestion_trigger()

        # 2) Mantiene la logica esistente che mappa descrizione su device_type
        normalized_desc = (text or "").strip().upper()
        if not normalized_desc:
            return

        try:
            from app import config

            for key, profile in config.FUNCTIONAL_PROFILES.items():
                device_type = (profile.device_type or "").strip().upper()
                if device_type and device_type == normalized_desc:
                    self._set_functional_profile_by_key(key)
                    break
        except Exception as exc:
            logging.warning(f"Impossibile applicare la selezione automatica del profilo: {exc}")

    def _set_functional_profile_by_key(self, profile_key: str):
        """Imposta in modo sicuro il profilo funzionale nel combo."""
        index = self.functional_profile_combo.findData(profile_key)
        if index == -1:
            return
        self._suppress_functional_profile_signal = True
        try:
            self.functional_profile_combo.setCurrentIndex(index)
        finally:
            self._suppress_functional_profile_signal = False

    def _on_functional_profile_combo_changed(self, index: int):
        """Tiene traccia delle modifiche manuali al profilo funzionale."""
        if self._suppress_functional_profile_signal:
            return
        if index >= 0:
            self._functional_profile_user_override = True

    def _on_profile_combo_changed(self, index: int):
        """Tiene traccia delle modifiche manuali al profilo elettrico."""
        if self._suppress_profile_signal:
            return
        if index >= 0:
            self._profile_user_override = True

    def _handle_profile_suggestion_trigger(self):
        """Prova a suggerire profili quando cambiano costruttore o modello."""
        if not self.is_new_device:
            return
        # Non sovrascrivere scelte manuali dell'utente
        if self._profile_user_override and self._functional_profile_user_override:
            return

        manu = self.mfg_edit.text()
        model = self.model_edit.text()
        desc = self.desc_edit.text()

        if not (manu or model or desc):
            return

        try:
            suggestions = services.get_suggested_profiles_for_device(manu, model, desc)
        except Exception as e:
            logging.warning(f"Errore nel recupero dei profili suggeriti: {e}")
            return

        prof_key = suggestions.get("default_profile_key")
        func_key = suggestions.get("default_functional_profile_key")

        # Applica suggerimento profilo elettrico solo se l'utente non lo ha cambiato a mano
        if prof_key and not self._profile_user_override:
            idx = self.profile_combo.findData(prof_key)
            if idx != -1:
                self._suppress_profile_signal = True
                try:
                    self.profile_combo.setCurrentIndex(idx)
                finally:
                    self._suppress_profile_signal = False

        # Applica suggerimento profilo funzionale solo se l'utente non lo ha cambiato a mano
        if func_key and not self._functional_profile_user_override:
            self._set_functional_profile_by_key(func_key)

    def add_pa(self):
        """Aggiunge una parte applicata assegnando il codice successivo nella sequenza."""
        name = self.pa_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "DATI MANCANTI", "INSERIRE UN NOME DESCRITTIVO PER LA PARTE APPLICATA.")
            return

        next_code_index = len(self.applied_parts)
        if next_code_index >= len(self.AP_CODE_SEQUENCE):
            QMessageBox.critical(self, "LIMITE RAGGIUNTO", f"NON È POSSIBILE AGGIUNGERE PIÙ DI {len(self.AP_CODE_SEQUENCE)} PARTI APPLICATE.")
            return
            
        assigned_code = self.AP_CODE_SEQUENCE[next_code_index]

        self.applied_parts.append(AppliedPart(
            name=name, 
            part_type=self.pa_type_selector.currentText(),
            code=assigned_code
        ))
        self.load_pa_table()
        self.pa_name_input.clear()

    def delete_pa(self):
        """Elimina la parte applicata selezionata dalla tabella."""
        current_row = self.pa_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "SELEZIONE MANCANTE", "SELEZIONARE UNA PARTE APPLICATA DA ELIMINARE.")
            return
        
        part_to_delete = self.applied_parts[current_row]
        reply = QMessageBox.question(self, "CONFERMA ELIMINAZIONE", 
                                     f"SEI SICURO DI VOLER ELIMINARE LA PARTE APPLICATA '{part_to_delete.name.upper()}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.applied_parts.pop(current_row)
            self.load_pa_table()

    def load_pa_table(self):
        """Ricarica la tabella e riassegna i codici sequenziali."""
        # Riassegna i codici per mantenere la sequenza corretta
        for i, part in enumerate(self.applied_parts):
            if i < len(self.AP_CODE_SEQUENCE):
                part.code = self.AP_CODE_SEQUENCE[i]

        self.pa_table.setRowCount(0)
        for pa in self.applied_parts:
            row = self.pa_table.rowCount()
            self.pa_table.insertRow(row)
            
            name_item = QTableWidgetItem(pa.name.upper())
            type_item = QTableWidgetItem(pa.part_type.upper())
            type_item.setTextAlignment(Qt.AlignCenter)
            code_item = QTableWidgetItem(pa.code.upper())
            code_item.setTextAlignment(Qt.AlignCenter)
            
            self.pa_table.setItem(row, 0, name_item)
            self.pa_table.setItem(row, 1, type_item)
            self.pa_table.setItem(row, 2, code_item)

    def _refresh_presets_combo(self, select_preset_id: int | None = None):
        """Aggiorna il menu a tendina dei preset disponibili."""
        self.pa_preset_combo.blockSignals(True)
        self.pa_preset_combo.clear()
        self.pa_preset_combo.addItem("— Seleziona preset... —", None)
        
        presets = services.get_applied_parts_presets()
        target_idx = 0
        for idx, p in enumerate(presets, start=1):
            parts_count = len(p.get('parts', []))
            self.pa_preset_combo.addItem(f"📦 {p['name']} ({parts_count} P.A.)", p)
            if select_preset_id is not None and p.get('id') == select_preset_id:
                target_idx = idx
                
        self.pa_preset_combo.setCurrentIndex(target_idx)
        self.pa_preset_combo.blockSignals(False)

    def _apply_selected_preset(self):
        """Applica le parti applicate del preset selezionato."""
        preset = self.pa_preset_combo.currentData()
        if not preset:
            QMessageBox.information(self, "Nessun Preset", "Seleziona prima un preset dal menu a discesa.")
            return

        parts_to_load = preset.get('parts', [])
        if not parts_to_load:
            QMessageBox.warning(self, "Preset Vuoto", "Il preset selezionato non contiene parti applicate.")
            return

        if self.applied_parts:
            reply = QMessageBox.question(
                self,
                "Sostituire Parti Applicate?",
                f"Il dispositivo contiene già {len(self.applied_parts)} parti applicate.\n"
                f"Vuoi sostituirle con quelle del preset '{preset.get('name')}'?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                return

        self.applied_parts = []
        for i, p in enumerate(parts_to_load):
            code = self.AP_CODE_SEQUENCE[i] if i < len(self.AP_CODE_SEQUENCE) else f"PA{i+1}"
            self.applied_parts.append(AppliedPart(
                name=p.get('name', ''),
                part_type=p.get('part_type', 'BF'),
                code=code
            ))
        self.load_pa_table()

    def _save_as_preset(self):
        """Salva le parti applicate attualmente definite come nuovo preset."""
        if not self.applied_parts:
            QMessageBox.warning(self, "Nessuna Parte Applicata", "Inserisci almeno una parte applicata prima di salvare un preset.")
            return

        suggested_name = f"{self.mfg_edit.text().strip()} {self.model_edit.text().strip()}".strip()
        if not suggested_name:
            suggested_name = self.desc_edit.text().strip()

        preset_name, ok = QInputDialog.getText(
            self,
            "Salva come Preset",
            "Nome descrittivo per il nuovo preset:",
            QLineEdit.Normal,
            suggested_name
        )
        if not ok or not preset_name.strip():
            return

        preset_name = preset_name.strip()
        parts_list = [{'name': p.name, 'part_type': p.part_type} for p in self.applied_parts]

        try:
            new_id = services.save_applied_parts_preset(name=preset_name, parts=parts_list)
            self._refresh_presets_combo(select_preset_id=new_id)
            QMessageBox.information(
                self,
                "Preset Salvato",
                f"Il preset '{preset_name}' è stato salvato con successo ({len(parts_list)} parti applicate)!"
            )
        except Exception as e:
            logging.error(f"Errore salvataggio preset: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile salvare il preset:\n{str(e)}")

    def _open_manage_presets(self):
        """Apre la dialog per gestire tutti i preset."""
        dlg = AppliedPartsPresetsDialog(parent=self)
        dlg.exec()
        self._refresh_presets_combo()

    def open_copy_search(self):
        """Apre la dialog di ricerca e popola i campi con i dati del dispositivo scelto."""
        search_dialog = DeviceSearchDialog(self)
        if search_dialog.exec():
            template_data = search_dialog.selected_device_data
            if template_data:
                self.populate_fields(template_data)

    def populate_fields(self, data):
        """Popola i campi della dialog con i dati forniti."""
        # Popola i campi principali (descrizione, modello, ecc.)
        self.desc_edit.setText(data.get('description', ''))
        self.mfg_edit.setText(data.get('manufacturer', ''))
        self.model_edit.setText(data.get('model', ''))
        
        # Lascia vuoti i campi univoci
        self.serial_edit.clear()
        self.customer_inv_edit.clear()
        self.ams_inv_edit.clear()
        
        # Imposta l'intervallo di verifica
        interval = data.get('verification_interval')
        if interval is not None:
            self.verification_interval_combo.setCurrentText(str(interval))
        else:
            self.verification_interval_combo.setCurrentText("Nessuno")
            
        # Popola le parti applicate
        self.applied_parts = []
        for pa_data in data.get('applied_parts', []):
            self.applied_parts.append(AppliedPart(**pa_data))
        self.load_pa_table()

        # Metti il focus sul primo campo da compilare
        self.serial_edit.setFocus()

    # ── UDI Lookup ──────────────────────────────────────────────────────
    def _lookup_udi(self):
        """Cerca le informazioni del dispositivo tramite codice UDI e compila i campi."""
        raw_code = self.udi_input.text().strip()
        if not raw_code:
            QMessageBox.warning(self, "Codice mancante", "Inserire o scansionare un codice UDI / barcode.")
            return

        self.udi_status_label.setText("⏳ Ricerca in corso...")
        self.udi_status_label.setStyleSheet("color: #5E81AC; font-weight: bold;")
        QApplication.processEvents()

        try:
            from app.utils.udi_lookup import get_device_info_from_udi

            info = get_device_info_from_udi(raw_code)
            if not info:
                self.udi_status_label.setText("❌ Nessun risultato trovato.")
                self.udi_status_label.setStyleSheet("color: #BF616A; font-weight: bold;")
                return

            filled_fields: list[str] = []

            manufacturer = (info.get('manufacturer') or '').strip()
            model = (info.get('model') or '').strip()
            description = (info.get('description') or '').strip()
            serial = (info.get('serial_number') or '').strip()

            if manufacturer:
                self.mfg_edit.setText(manufacturer)
                filled_fields.append("Costruttore")

            if model:
                self.model_edit.setText(model)
                filled_fields.append("Modello")

            if description:
                self.desc_edit.setText(description)
                filled_fields.append("Descrizione")
            elif manufacturer and model:
                # Se non c'è descrizione ma abbiamo marca e modello, usiamo quelli
                self.desc_edit.setText(f"{manufacturer} {model}".strip())
                filled_fields.append("Descrizione (auto)")

            if serial:
                self.serial_edit.setText(serial)
                filled_fields.append("Numero di serie")

            if filled_fields:
                summary = ", ".join(filled_fields)
                self.udi_status_label.setText(f"✅ Compilati: {summary}")
                self.udi_status_label.setStyleSheet("color: #A3BE8C; font-weight: bold;")
                logging.info(f"[UDI] Compilati campi: {summary} da codice: {raw_code[:40]}...")
            else:
                self.udi_status_label.setText("⚠️ Codice riconosciuto ma nessun dato utile trovato.")
                self.udi_status_label.setStyleSheet("color: #EBCB8B; font-weight: bold;")

        except Exception as e:
            logging.error(f"[UDI] Errore lookup: {e}", exc_info=True)
            self.udi_status_label.setText(f"❌ Errore: {e}")
            self.udi_status_label.setStyleSheet("color: #BF616A; font-weight: bold;")

    # ── Phone Scan (VScanner) ───────────────────────────────────────────
    def _find_main_window(self):
        """Risale la gerarchia dei widget per trovare la MainWindow."""
        widget = self.parent()
        while widget is not None:
            if widget.__class__.__name__ == 'MainWindow':
                return widget
            widget = widget.parent() if hasattr(widget, 'parent') else None
        return None

    def _toggle_phone_scan_listener(self, checked: bool):
        """Attiva/disattiva l'ascolto dello scanner telefonico per compilare il campo UDI."""
        if checked:
            self._start_phone_scan()
        else:
            self._stop_phone_scan()

    def _start_phone_scan(self):
        """Avvia l'ascolto dallo scanner del telefono."""
        main_win = self._find_main_window()
        if not main_win:
            QMessageBox.warning(self, "Errore", "Impossibile trovare la finestra principale.")
            self.udi_phone_btn.setChecked(False)
            return

        # Avvia il server QR scanner se non già attivo
        if not getattr(main_win, 'qr_scanner_server_running', False):
            try:
                main_win._start_qr_scanner_server()
            except Exception as e:
                logging.error(f"[PhoneScan] Errore avvio server: {e}", exc_info=True)
                QMessageBox.warning(self, "Errore", f"Impossibile avviare il server scanner:\n{e}")
                self.udi_phone_btn.setChecked(False)
                return

        # Registra il callback intercept sulla MainWindow
        main_win._phone_scan_callback = self._on_phone_code_received
        self._phone_scan_connected = True

        # Aggiorna UI
        self.udi_phone_btn.setText(" 📱 In ascolto...")
        self.udi_phone_btn.setStyleSheet(
            "QPushButton { background-color: #A3BE8C; color: #2E3440; font-weight: bold; border-radius: 4px; }"
            "QPushButton:checked { background-color: #A3BE8C; }"
        )
        self.udi_status_label.setText("📱 In attesa di scansione dal telefono...")
        self.udi_status_label.setStyleSheet("color: #5E81AC; font-weight: bold;")
        logging.info("[PhoneScan] Ascolto attivato per UDI da telefono")

        # Mostra info per connessione
        url = getattr(main_win, 'qr_scanner_url', None)
        if url:
            QMessageBox.information(
                self, "Scanner Telefono Attivo",
                f"Lo scanner è in ascolto.\n\n"
                f"Apri l'app VScanner sul telefono e scansiona il QR code "
                f"nella barra degli strumenti per connetterti.\n\n"
                f"Indirizzo server: {url}\n\n"
                f"Quando scansioni un codice a barre / UDI, il campo verrà compilato automaticamente."
            )

    def _stop_phone_scan(self):
        """Disattiva l'ascolto dallo scanner del telefono."""
        if self._phone_scan_connected:
            main_win = self._find_main_window()
            if main_win and getattr(main_win, '_phone_scan_callback', None) == self._on_phone_code_received:
                main_win._phone_scan_callback = None
            self._phone_scan_connected = False

        # Ripristina UI
        self.udi_phone_btn.setText(" 📱 Scansiona")
        self.udi_phone_btn.setStyleSheet("")
        self.udi_phone_btn.setChecked(False)
        logging.info("[PhoneScan] Ascolto disattivato")

    def _on_phone_code_received(self, code: str):
        """Callback chiamato quando il telefono invia un codice UDI/barcode."""
        logging.info(f"[PhoneScan] Codice ricevuto dal telefono: {code}")

        # Popola il campo UDI e lancia il lookup
        self.udi_input.setText(code)
        self.udi_status_label.setText(f"📱 Codice ricevuto: {code[:50]}...")
        self.udi_status_label.setStyleSheet("color: #A3BE8C; font-weight: bold;")

        # Esegui il lookup automaticamente
        self._lookup_udi()

        # Aggiorna last_result per feedback all'app Android
        try:
            from app.ui.dialogs.qr_device_scanner_dialog import QRScannerHTTPHandler
            udi_status = self.udi_status_label.text()
            found = "✅" in udi_status
            QRScannerHTTPHandler.last_result = {
                "code": code,
                "found": found,
                "info": udi_status if found else f"UDI compilato: {code[:40]}",
            }
        except Exception:
            pass

    def reject(self):
        """Pulizia alla chiusura della dialog."""
        self._stop_phone_scan()
        super().reject()

    def accept(self):
        """Valida i dati e pulisce la scansione telefono alla conferma."""
        if not self._validate_required_fields():
            return
        self._stop_phone_scan()
        super().accept()

    def get_data(self):
        return { 
            "destination_id": self.destination_combo.currentData(),
            "default_profile_key": self.profile_combo.currentData(),
            "default_functional_profile_key": self.functional_profile_combo.currentData(),
            "serial": self.serial_edit.text().strip().upper(), 
            "desc": self.desc_edit.text().strip().upper(),
            "mfg": self.mfg_edit.text().strip().upper(), 
            "model": self.model_edit.text().strip().upper(),
            "department": self.department_edit.text().strip().upper(),
            "customer_inv": self.customer_inv_edit.text().strip().upper(), 
            "ams_inv": self.ams_inv_edit.text().strip().upper(),
            "applied_parts": self.applied_parts, 
            "verification_interval": self.verification_interval_combo.currentText() 
        }
    
class InstrumentDetailDialog(QDialog):
    """Dialog per inserire/modificare i dettagli di un singolo strumento."""
    def __init__(self, instrument_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DETTAGLI STRUMENTO DI MISURA")
        data = instrument_data or {}
        layout = QFormLayout(self)

        # 1. Creazione di tutti i widget
        self.name_edit = QLineEdit(data.get('instrument_name', ''))
        self.serial_edit = QLineEdit(data.get('serial_number', ''))
        self.version_edit = QLineEdit(data.get('fw_version', ''))
        self.cal_date_edit = QLineEdit(format_date_it(data.get('calibration_date', '')))
        self.sede_edit = QLineEdit(data.get('sede', ''))
        
        # Tipo strumento
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Elettrico", "Funzionale"])
        instrument_type = data.get('instrument_type', 'electrical')
        if instrument_type == 'functional':
            self.type_combo.setCurrentIndex(1)
        else:
            self.type_combo.setCurrentIndex(0)
        
        # Certificato PDF opzionale
        self.chosen_pdf_path = None
        self.cert_label = QLabel("Nessun PDF selezionato")
        self.btn_select_pdf = QPushButton("📎 SFOGLIA PDF...")
        self.btn_select_pdf.clicked.connect(self._select_pdf)
        pdf_row = QHBoxLayout()
        pdf_row.addWidget(self.cert_label)
        pdf_row.addWidget(self.btn_select_pdf)
        
        # 2. Aggiunta dei widget al layout
        layout.addRow("NOME STRUMENTO:", self.name_edit)
        layout.addRow("NUMERO DI SERIE:", self.serial_edit)
        layout.addRow("NR CERTIFICATO DI CAL.:", self.version_edit)
        layout.addRow("DATA CALIBRAZIONE:", self.cal_date_edit)
        layout.addRow("SEDE:", self.sede_edit)
        layout.addRow("TIPO STRUMENTO:", self.type_combo)
        layout.addRow("CERTIFICATO CAL.:", pdf_row)
        
        # 4. Aggiunta dei pulsanti finali
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleziona Certificato di Calibrazione (PDF)", "", "Documenti PDF (*.pdf)"
        )
        if file_path:
            self.chosen_pdf_path = file_path
            self.cert_label.setText(os.path.basename(file_path))

    def get_data(self):
        instrument_type = 'functional' if self.type_combo.currentIndex() == 1 else 'electrical'
        return {
            "instrument_name": self.name_edit.text().strip().upper(),
            "serial_number": self.serial_edit.text().strip().upper(),
            "fw_version": self.version_edit.text().strip().upper(),
            "calibration_date": format_date_it(self.cal_date_edit.text().strip()),
            "sede": self.sede_edit.text().strip().upper() or None,
            "instrument_type": instrument_type,
            "pdf_path": self.chosen_pdf_path,
        }
