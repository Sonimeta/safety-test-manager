# app/ui/dialogs/profile_manager_dialog.py
import json
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
                               QMessageBox, QDialogButtonBox, QLineEdit, QTableWidget,
                               QHeaderView, QCheckBox, QGroupBox, QRadioButton, QButtonGroup,
                               QStackedWidget, QGridLayout, QScrollArea,
                               QDoubleSpinBox, QComboBox, QLabel, QFormLayout, QListWidgetItem, QWidget, QFileDialog)
from PySide6.QtCore import Qt
from app.data_models import VerificationProfile, Test, Limit
from app.verification_logic import validate_profile_limits
from app.profile_builder import (
    BuilderOptions, MAINS_VOLTAGE_MEASURES, build_tests, class_defaults,
    describe_tests, parse_profile,
)
from app import services, config
import database

# --- NUOVA MAPPA DEI PARAMETRI VALIDI ---
# Le chiavi e i valori DEVONO essere in MAIUSCOLO perché il monkey-patch globale
# in main.py converte automaticamente tutti i testi di QComboBox in uppercase.
VALID_TEST_PARAMETERS = {
    "TENSIONE ALIMENTAZIONE": ["DA FASE A NEUTRO", "DA NEUTRO A TERRA", "DA FASE A TERRA"],
    "CORRENTE DISPERSIONE DIRETTA DISPOSITIVO": ["POLARITÀ NORMALE", "POLARITÀ INVERSA"],
    "CORRENTE DISPERSIONE DIRETTA P.A.": ["POLARITÀ NORMALE", "POLARITÀ INVERSA"]
}

class ProfileDetailDialog(QDialog):
    """Dialog per creare o modificare un singolo profilo di verifica.

    Due modalità:
    - GUIDATA (default): si scelgono le prove da eseguire con limiti CEI 62353
      precompilati in base alla classe del dispositivo, con anteprima live
      della sequenza e avvisi normativi immediati.
    - AVANZATA: la tabella libera test-per-test, per profili particolari.
    Un profilo esistente si apre in guidata solo se la sua struttura è
    riconoscibile; altrimenti si apre in avanzata.
    """
    def __init__(self, profile: VerificationProfile = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DETTAGLI PROFILO DI VERIFICA" if profile and profile.name else "NUOVO PROFILO DI VERIFICA")
        self.setMinimumSize(950, 680)

        self.profile = profile or VerificationProfile(name="", tests=[])

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.profile_name_edit = QLineEdit(self.profile.name)
        self.profile_name_edit.setPlaceholderText("es. ELETTROMEDICALE CLASSE I CON P.A.")
        form_layout.addRow("NOME PROFILO:", self.profile_name_edit)

        self.norma_edit = QLineEdit(self.profile.norma or "CEI EN 62353")
        self.norma_edit.setPlaceholderText("es. CEI EN 62353")
        form_layout.addRow("NORMA DI RIFERIMENTO:", self.norma_edit)
        layout.addLayout(form_layout)

        # Selettore modalità
        mode_row = QHBoxLayout()
        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet("font-weight: bold;")
        self.mode_toggle_btn = QPushButton("")
        self.mode_toggle_btn.clicked.connect(self._toggle_mode)
        mode_row.addWidget(self.mode_label)
        mode_row.addStretch()
        mode_row.addWidget(self.mode_toggle_btn)
        layout.addLayout(mode_row)

        # Pagine: 0 = guidata, 1 = avanzata
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_simple_page())
        self.stack.addWidget(self._build_advanced_page())
        layout.addWidget(self.stack, 1)

        dialog_buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(dialog_buttons)
        dialog_buttons.accepted.connect(self.accept_changes)
        dialog_buttons.rejected.connect(self.reject)

        # Modalità iniziale: guidata se il profilo è riconoscibile
        self.populate_table()
        if self.profile.tests:
            parsed = parse_profile(self.profile)
        else:
            parsed = BuilderOptions()  # nuovo profilo: default Classe I
        if parsed is not None:
            self._load_simple(parsed)
            self._set_mode(simple=True)
        else:
            self._set_mode(simple=False)

    # ─── Pagina GUIDATA ──────────────────────────────────────────────────

    def _build_simple_page(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)

        # Colonna sinistra: scelte
        left = QVBoxLayout()

        # Classe del dispositivo
        class_box = QGroupBox("CLASSE DEL DISPOSITIVO")
        class_lay = QHBoxLayout(class_box)
        self.class1_radio = QRadioButton("CLASSE I  (con conduttore di terra)")
        self.class2_radio = QRadioButton("CLASSE II  (doppio isolamento)")
        self.class1_radio.setChecked(True)
        self._class_group = QButtonGroup(self)
        self._class_group.addButton(self.class1_radio)
        self._class_group.addButton(self.class2_radio)
        class_lay.addWidget(self.class1_radio)
        class_lay.addWidget(self.class2_radio)
        left.addWidget(class_box)

        # Prove preliminari
        mains_box = QGroupBox("PROVE PRELIMINARI (informative, senza limite)")
        mains_lay = QVBoxLayout(mains_box)
        self.chk_mains = QCheckBox("Tensione di alimentazione")
        mains_lay.addWidget(self.chk_mains)
        mains_sub = QHBoxLayout()
        mains_sub.addSpacing(24)
        self.chk_mains_measures = []
        for label in MAINS_VOLTAGE_MEASURES:
            cb = QCheckBox(label)
            cb.setChecked(True)
            self.chk_mains_measures.append(cb)
            mains_sub.addWidget(cb)
        mains_sub.addStretch()
        mains_lay.addLayout(mains_sub)
        left.addWidget(mains_box)

        # Prove di sicurezza
        safety_box = QGroupBox("PROVE DI SICUREZZA ELETTRICA")
        safety_lay = QGridLayout(safety_box)
        self.chk_earth = QCheckBox("Resistenza conduttore di terra")
        self.spin_earth = QDoubleSpinBox()
        self.spin_earth.setDecimals(3); self.spin_earth.setRange(0.001, 99.0)
        self.spin_earth.setValue(0.3); self.spin_earth.setSuffix(" Ω")
        safety_lay.addWidget(self.chk_earth, 0, 0)
        safety_lay.addWidget(QLabel("limite ≤"), 0, 1)
        safety_lay.addWidget(self.spin_earth, 0, 2)

        self.chk_leak = QCheckBox("Corrente dispersione apparecchio")
        self.spin_leak = QDoubleSpinBox()
        self.spin_leak.setDecimals(1); self.spin_leak.setRange(0.1, 99999.0)
        self.spin_leak.setValue(500.0); self.spin_leak.setSuffix(" µA")
        safety_lay.addWidget(self.chk_leak, 1, 0)
        safety_lay.addWidget(QLabel("limite ≤"), 1, 1)
        safety_lay.addWidget(self.spin_leak, 1, 2)
        pol_row = QHBoxLayout()
        pol_row.addSpacing(24)
        self.chk_leak_norm = QCheckBox("Polarità normale")
        self.chk_leak_rev = QCheckBox("Polarità inversa")
        self.chk_leak_norm.setChecked(True); self.chk_leak_rev.setChecked(True)
        pol_row.addWidget(self.chk_leak_norm); pol_row.addWidget(self.chk_leak_rev); pol_row.addStretch()
        safety_lay.addLayout(pol_row, 2, 0, 1, 3)
        left.addWidget(safety_box)

        # Parti applicate
        ap_box = QGroupBox("PARTI APPLICATE")
        ap_lay = QVBoxLayout(ap_box)
        self.chk_ap = QCheckBox("Corrente dispersione parti applicate  (eseguita su ogni parte del dispositivo)")
        ap_lay.addWidget(self.chk_ap)

        ap_grid = QGridLayout()
        ap_grid.setColumnStretch(3, 1)
        self.ap_type_widgets = {}
        defaults = {"B": 5000.0, "BF": 5000.0, "CF": 50.0}
        for r, ap_type in enumerate(("B", "BF", "CF")):
            cb = QCheckBox(f"Tipo {ap_type}")
            cb.setChecked(True)
            spin = QDoubleSpinBox()
            spin.setDecimals(1); spin.setRange(0.1, 99999.0)
            spin.setValue(defaults[ap_type]); spin.setSuffix(" µA")
            ap_grid.addWidget(cb, r, 0)
            ap_grid.addWidget(QLabel("limite ≤"), r, 1)
            ap_grid.addWidget(spin, r, 2)
            self.ap_type_widgets[ap_type] = (cb, spin)
        ap_lay.addLayout(ap_grid)

        ap_pol_row = QHBoxLayout()
        self.chk_ap_norm = QCheckBox("Polarità normale")
        self.chk_ap_rev = QCheckBox("Polarità inversa")
        self.chk_ap_norm.setChecked(True); self.chk_ap_rev.setChecked(True)
        ap_pol_row.addWidget(self.chk_ap_norm); ap_pol_row.addWidget(self.chk_ap_rev); ap_pol_row.addStretch()
        ap_lay.addLayout(ap_pol_row)

        pause_row = QHBoxLayout()
        self.chk_pause = QCheckBox("Pausa prima delle prove P.A. con messaggio:")
        self.pause_edit = QLineEdit()
        self.pause_edit.setPlaceholderText("es. Collegare gli elettrodi al dispositivo")
        pause_row.addWidget(self.chk_pause)
        pause_row.addWidget(self.pause_edit, 1)
        ap_lay.addLayout(pause_row)
        left.addWidget(ap_box)
        left.addStretch()

        # Colonna destra: anteprima live
        right = QVBoxLayout()
        preview_box = QGroupBox("ANTEPRIMA SEQUENZA DI VERIFICA")
        preview_lay = QVBoxLayout(preview_box)
        self.preview_list = QListWidget()
        self.preview_list.setSelectionMode(QListWidget.NoSelection)
        self.preview_list.setFocusPolicy(Qt.NoFocus)
        preview_lay.addWidget(self.preview_list, 1)
        self.preview_warnings = QLabel("")
        self.preview_warnings.setWordWrap(True)
        self.preview_warnings.setStyleSheet("color: #b45309; font-weight: bold;")
        preview_lay.addWidget(self.preview_warnings)
        right.addWidget(preview_box, 1)

        left_widget = QWidget(); left_widget.setLayout(left)
        scroll = QScrollArea(); scroll.setWidget(left_widget)
        scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, 3)
        right_widget = QWidget(); right_widget.setLayout(right)
        outer.addWidget(right_widget, 2)

        # Cambi classe → aggiorna i default di norma
        self.class1_radio.toggled.connect(self._apply_class_defaults)
        # Qualunque modifica → aggiorna anteprima e abilitazioni
        for w in ([self.chk_mains, self.chk_earth, self.chk_leak, self.chk_leak_norm,
                   self.chk_leak_rev, self.chk_ap, self.chk_ap_norm, self.chk_ap_rev,
                   self.chk_pause] + self.chk_mains_measures
                  + [cb for cb, _ in self.ap_type_widgets.values()]):
            w.toggled.connect(self._update_preview)
        for s in [self.spin_earth, self.spin_leak] + [sp for _, sp in self.ap_type_widgets.values()]:
            s.valueChanged.connect(self._update_preview)
        self.pause_edit.textChanged.connect(self._update_preview)

        return page

    def _apply_class_defaults(self):
        """Quando si cambia classe, ripropone i valori CEI 62353 di default."""
        defaults = class_defaults("I" if self.class1_radio.isChecked() else "II")
        self.chk_earth.setChecked(defaults["include_earth_resistance"])
        if "earth_limit" in defaults:
            self.spin_earth.setValue(defaults["earth_limit"])
        self.spin_leak.setValue(defaults["equipment_leakage_limit"])
        self._update_preview()

    def _collect_simple(self) -> BuilderOptions:
        return BuilderOptions(
            device_class="I" if self.class1_radio.isChecked() else "II",
            include_mains_voltage=self.chk_mains.isChecked(),
            mains_voltage_measures=[
                m for m, cb in zip(MAINS_VOLTAGE_MEASURES, self.chk_mains_measures)
                if cb.isChecked()
            ],
            include_earth_resistance=self.chk_earth.isChecked(),
            earth_limit=self.spin_earth.value(),
            include_equipment_leakage=self.chk_leak.isChecked(),
            equipment_leakage_limit=self.spin_leak.value(),
            equipment_polarity_normal=self.chk_leak_norm.isChecked(),
            equipment_polarity_reverse=self.chk_leak_rev.isChecked(),
            include_ap_leakage=self.chk_ap.isChecked(),
            ap_limits={
                ap_type: spin.value()
                for ap_type, (cb, spin) in self.ap_type_widgets.items()
                if cb.isChecked()
            },
            ap_polarity_normal=self.chk_ap_norm.isChecked(),
            ap_polarity_reverse=self.chk_ap_rev.isChecked(),
            include_pause_before_ap=self.chk_pause.isChecked(),
            pause_before_ap=self.pause_edit.text(),
        )

    def _load_simple(self, opts: BuilderOptions):
        """Carica le opzioni nei widget senza far scattare i default di classe."""
        self.class1_radio.blockSignals(True)
        self.class1_radio.setChecked(opts.device_class == "I")
        self.class2_radio.setChecked(opts.device_class != "I")
        self.class1_radio.blockSignals(False)

        self.chk_mains.setChecked(opts.include_mains_voltage)
        for m, cb in zip(MAINS_VOLTAGE_MEASURES, self.chk_mains_measures):
            cb.setChecked(m in opts.mains_voltage_measures or not opts.include_mains_voltage)

        self.chk_earth.setChecked(opts.include_earth_resistance)
        if opts.include_earth_resistance:
            self.spin_earth.setValue(opts.earth_limit)
        self.chk_leak.setChecked(opts.include_equipment_leakage)
        if opts.include_equipment_leakage:
            self.spin_leak.setValue(opts.equipment_leakage_limit)
        self.chk_leak_norm.setChecked(opts.equipment_polarity_normal)
        self.chk_leak_rev.setChecked(opts.equipment_polarity_reverse)

        self.chk_ap.setChecked(opts.include_ap_leakage)
        for ap_type, (cb, spin) in self.ap_type_widgets.items():
            if opts.include_ap_leakage:
                cb.setChecked(ap_type in opts.ap_limits)
                if ap_type in opts.ap_limits:
                    spin.setValue(opts.ap_limits[ap_type])
        self.chk_ap_norm.setChecked(opts.ap_polarity_normal or not opts.include_ap_leakage)
        self.chk_ap_rev.setChecked(opts.ap_polarity_reverse or not opts.include_ap_leakage)
        self.chk_pause.setChecked(opts.include_pause_before_ap)
        self.pause_edit.setText(opts.pause_before_ap)

        self._update_preview()

    def _update_preview(self):
        """Rigenera l'anteprima della sequenza e gli avvisi normativi."""
        # Abilitazioni dipendenti
        for cb in self.chk_mains_measures:
            cb.setEnabled(self.chk_mains.isChecked())
        self.spin_earth.setEnabled(self.chk_earth.isChecked())
        leak_on = self.chk_leak.isChecked()
        for w in (self.spin_leak, self.chk_leak_norm, self.chk_leak_rev):
            w.setEnabled(leak_on)
        ap_on = self.chk_ap.isChecked()
        for ap_type, (cb, spin) in self.ap_type_widgets.items():
            cb.setEnabled(ap_on)
            spin.setEnabled(ap_on and cb.isChecked())
        for w in (self.chk_ap_norm, self.chk_ap_rev, self.chk_pause):
            w.setEnabled(ap_on)
        self.pause_edit.setEnabled(ap_on and self.chk_pause.isChecked())

        opts = self._collect_simple()
        tests = build_tests(opts)
        self.preview_list.clear()
        if tests:
            self.preview_list.addItems(describe_tests(tests))
        else:
            self.preview_list.addItem("— Nessuna prova selezionata —")

        temp_profile = VerificationProfile(name="anteprima", tests=tests)
        warnings = validate_profile_limits(temp_profile)
        self.preview_warnings.setText("\n".join(f"⚠ {w}" for w in warnings))

    # ─── Gestione modalità ───────────────────────────────────────────────

    def _set_mode(self, simple: bool):
        self._simple_mode = simple
        self.stack.setCurrentIndex(0 if simple else 1)
        if simple:
            self.mode_label.setText("✦ MODALITÀ GUIDATA — limiti CEI 62353 precompilati")
            self.mode_toggle_btn.setText("PASSA ALLA MODALITÀ AVANZATA…")
        else:
            self.mode_label.setText("🛠 MODALITÀ AVANZATA — controllo completo dei test")
            self.mode_toggle_btn.setText("TORNA ALLA MODALITÀ GUIDATA…")

    def _toggle_mode(self):
        if self._simple_mode:
            # Guidata → avanzata: travasa le prove correnti nella tabella
            tests = build_tests(self._collect_simple())
            self.profile.tests = tests
            self.populate_table()
            self._set_mode(simple=False)
        else:
            # Avanzata → guidata: possibile solo se la struttura è riconoscibile
            tests = self._collect_tests_from_table()
            temp = VerificationProfile(name="x", tests=tests)
            parsed = parse_profile(temp)
            if parsed is None:
                QMessageBox.information(
                    self, "MODALITÀ GUIDATA NON DISPONIBILE",
                    "Il profilo contiene test personalizzati o in un ordine particolare\n"
                    "che la modalità guidata non può rappresentare.\n\n"
                    "Continua nella modalità avanzata.",
                )
                return
            self._load_simple(parsed)
            self._set_mode(simple=True)

    # ─── Pagina AVANZATA (tabella libera) ────────────────────────────────

    def _build_advanced_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("TEST DEL PROFILO:"))
        self.tests_table = QTableWidget()
        self.tests_table.setColumnCount(5)
        self.tests_table.setHorizontalHeaderLabels(["NOME TEST", "PARAMETRO / MESSAGGIO PAUSA", "LIMITE ALTO (ΜA/Ω)", "PARTE APPLICATA?", "TIPO P.A."])
        self.tests_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tests_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        layout.addWidget(self.tests_table)

        buttons_layout = QHBoxLayout()
        add_test_btn = QPushButton("AGGIUNGI TEST")
        remove_test_btn = QPushButton("RIMUOVI TEST SELEZIONATO")
        buttons_layout.addStretch(); buttons_layout.addWidget(add_test_btn); buttons_layout.addWidget(remove_test_btn)
        layout.addLayout(buttons_layout)

        add_test_btn.clicked.connect(self.add_test_row)
        remove_test_btn.clicked.connect(self.remove_test_row)
        return page

    def populate_table(self):
        self.tests_table.setRowCount(0)
        for test in self.profile.tests:
            self.add_test_row(test_data=test)

    def _update_parameter_widget(self, row):
        """
        Sostituisce il widget nella colonna 'Parametro' in base al tipo di test selezionato.
        """
        name_combo = self.tests_table.cellWidget(row, 0)
        selected_test = name_combo.currentText()

        current_parameter_widget = self.tests_table.cellWidget(row, 1)
        # Salva il valore corrente prima di cambiare widget
        current_value = ""
        if isinstance(current_parameter_widget, QComboBox):
            current_value = current_parameter_widget.currentText()
        elif isinstance(current_parameter_widget, QLineEdit):
            current_value = current_parameter_widget.text()

        is_pause = "PAUSA MANUALE" in selected_test
        valid_params = VALID_TEST_PARAMETERS.get(selected_test)

        # Disabilita gli altri campi se è una pausa
        for col in range(2, 5):
            widget = self.tests_table.cellWidget(row, col)
            if widget:
                widget.setEnabled(not is_pause)
        
        if is_pause:
            # Usa un QLineEdit per il messaggio di pausa
            param_widget = QLineEdit(current_value)
            param_widget.setPlaceholderText("MESSAGGIO PER LA PAUSA...")
            self.tests_table.setCellWidget(row, 1, param_widget)
        elif valid_params:
            # Usa un QComboBox per i parametri predefiniti
            param_widget = QComboBox()
            param_widget.addItems(valid_params)
            # Confronto case-insensitive per gestire il monkey-patch uppercase
            upper_val = current_value.upper() if current_value else ""
            upper_params = [p.upper() for p in valid_params]
            if upper_val in upper_params:
                param_widget.setCurrentIndex(upper_params.index(upper_val))
            self.tests_table.setCellWidget(row, 1, param_widget)
        else:
            # Usa un QLineEdit disabilitato per i test senza parametri
            param_widget = QLineEdit()
            param_widget.setPlaceholderText("N/A")
            param_widget.setEnabled(False)
            self.tests_table.setCellWidget(row, 1, param_widget)

    def add_test_row(self, test_data: Test = None):
        row = self.tests_table.rowCount()
        self.tests_table.insertRow(row)

        name_combo = QComboBox()
        test_names = list(VALID_TEST_PARAMETERS.keys()) + ["Resistenza conduttore di terra", "--- PAUSA MANUALE ---"]
        name_combo.addItems(test_names)
        if test_data:
            # Match case-insensitive: i nomi nei profili sono in caso misto
            # (es. "Corrente dispersione diretta dispositivo") mentre le voci
            # del combo sono in maiuscolo; setCurrentText non troverebbe la
            # voce e lascerebbe silenziosamente il primo test della lista
            idx = name_combo.findText(test_data.name, Qt.MatchFixedString)
            if idx >= 0:
                name_combo.setCurrentIndex(idx)
            else:
                name_combo.setCurrentText(test_data.name)
        self.tests_table.setCellWidget(row, 0, name_combo)
        
        # Inizializza con un widget temporaneo, verrà sostituito da _update_parameter_widget
        self.tests_table.setCellWidget(row, 1, QLineEdit(test_data.parameter if test_data else ""))
        
        # Mappa tipo P.A. -> valore limite: un test può avere limiti per più
        # tipi di parte (es. BF 5000 e CF 50); il dialog ne mostra uno alla
        # volta ma li conserva tutti, altrimenti il salvataggio cancellerebbe
        # silenziosamente i limiti dei tipi non visualizzati
        limits_by_type = {}
        if test_data and test_data.limits:
            for lim_key, lim in test_data.limits.items():
                limits_by_type[lim_key.strip(": ").upper()] = lim.high_value or 0.0
        first_type = next(iter(limits_by_type), "ST")

        limit_spinbox = QDoubleSpinBox(); limit_spinbox.setDecimals(3); limit_spinbox.setRange(0, 99999.999)
        limit_spinbox.setValue(limits_by_type.get(first_type, 0.0))
        self.tests_table.setCellWidget(row, 2, limit_spinbox)

        checkbox_container = QWidget(); checkbox_layout = QHBoxLayout(checkbox_container)
        is_ap_checkbox = QCheckBox(); is_ap_checkbox.setChecked(test_data.is_applied_part_test if test_data else False)
        checkbox_layout.addWidget(is_ap_checkbox); checkbox_layout.setAlignment(Qt.AlignCenter); checkbox_layout.setContentsMargins(0,0,0,0)
        self.tests_table.setCellWidget(row, 3, checkbox_container)

        ap_type_combo = QComboBox(); ap_type_combo.addItems(["ST", "B", "BF", "CF"])
        ap_type_combo.setCurrentText(first_type)
        ap_type_combo._limits_by_type = limits_by_type
        ap_type_combo._current_type = ap_type_combo.currentText()
        self.tests_table.setCellWidget(row, 4, ap_type_combo)

        def _on_ap_type_changed(_idx, combo=ap_type_combo, spin=limit_spinbox):
            # Salva il valore del tipo che si sta lasciando e carica quello
            # del tipo selezionato, così ogni tipo conserva il proprio limite
            combo._limits_by_type[combo._current_type] = spin.value()
            combo._current_type = combo.currentText()
            spin.setValue(combo._limits_by_type.get(combo._current_type, 0.0))
        ap_type_combo.currentIndexChanged.connect(_on_ap_type_changed)

        # Connetti il segnale e aggiorna subito il widget del parametro
        name_combo.currentIndexChanged.connect(lambda: self._update_parameter_widget(row))
        self._update_parameter_widget(row)
        self.tests_table.resizeRowsToContents()
        self.tests_table.resizeColumnsToContents()



    def remove_test_row(self):
        current_row = self.tests_table.currentRow()
        if current_row > -1: self.tests_table.removeRow(current_row)

    def _collect_tests_from_table(self):
        """Costruisce la lista di Test dalla tabella della modalità avanzata."""
        tests = []
        for row in range(self.tests_table.rowCount()):
            name = self.tests_table.cellWidget(row, 0).currentText()

            param_widget = self.tests_table.cellWidget(row, 1)
            param = ""
            if isinstance(param_widget, QComboBox):
                param = param_widget.currentText()
            elif isinstance(param_widget, QLineEdit):
                param = param_widget.text()

            if "PAUSA MANUALE" in name:
                tests.append(Test(name=name, parameter=param, limits={}, is_applied_part_test=False))
                continue

            limit_val = self.tests_table.cellWidget(row, 2).value()
            checkbox_container = self.tests_table.cellWidget(row, 3)
            is_ap_checkbox = checkbox_container.findChild(QCheckBox)
            is_ap = is_ap_checkbox.isChecked() if is_ap_checkbox else False
            ap_combo = self.tests_table.cellWidget(row, 4)
            ap_type = ap_combo.currentText()
            unit = "uA" if "CORRENTE" in name.upper() else ("Ohm" if "RESISTENZA" in name.upper() else "V")
            # Per i test su parti applicate ricostruisce TUTTI i limiti con
            # valore impostato (un test può coprire B, BF e CF insieme);
            # per i test standard vale solo il tipo attualmente selezionato
            limits_by_type = {}
            if is_ap:
                stored = getattr(ap_combo, "_limits_by_type", {})
                limits_by_type = {t: v for t, v in stored.items() if t and v > 0}
            limits_by_type[ap_type] = limit_val
            limits = {
                f"::{lim_type}": Limit(unit=unit, high_value=lim_val if lim_val > 0 else None)
                for lim_type, lim_val in limits_by_type.items()
            }
            tests.append(Test(name=name, parameter=param, limits=limits, is_applied_part_test=is_ap))
        return tests

    def accept_changes(self):
        if not self.profile_name_edit.text().strip():
            QMessageBox.warning(self, "NOME MANCANTE", "IL NOME DEL PROFILO NON PUÒ ESSERE VUOTO.")
            return

        if self._simple_mode:
            tests = build_tests(self._collect_simple())
        else:
            tests = self._collect_tests_from_table()

        if not tests:
            QMessageBox.warning(self, "NESSUNA PROVA", "IL PROFILO NON CONTIENE NESSUNA PROVA: SELEZIONARE ALMENO UN TEST.")
            return

        self.profile.name = self.profile_name_edit.text().strip().upper()
        self.profile.norma = self.norma_edit.text().strip()
        self.profile.tests = tests

        # Controllo di plausibilità dei limiti rispetto alla CEI 62353:
        # non blocca, ma chiede conferma esplicita se qualcosa è fuori scala
        limit_warnings = validate_profile_limits(self.profile)
        if limit_warnings:
            warning_text = "\n\n".join(f"• {w}" for w in limit_warnings)
            reply = QMessageBox.warning(
                self,
                "LIMITI FUORI SCALA",
                "ATTENZIONE: alcuni limiti sembrano incoerenti con la CEI 62353:\n\n"
                f"{warning_text}\n\n"
                "Vuoi salvare comunque il profilo?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        self.accept()

class ProfileManagerDialog(QDialog):
    """Dialog per visualizzare e gestire i profili dal database."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GESTIONE PROFILI DI VERIFICA (SINCRONIZZATI)")
        self.setMinimumSize(500, 400)
        self.profiles_changed = False

        layout = QVBoxLayout(self)
        self.profiles_list_widget = QListWidget()
        layout.addWidget(self.profiles_list_widget)

        buttons_layout = QHBoxLayout()
        add_btn = QPushButton("NUOVO...")
        edit_btn = QPushButton("MODIFICA...")
        delete_btn = QPushButton("ELIMINA")
        import_btn = QPushButton("IMPORTA JSON...")
        buttons_layout.addStretch()
        buttons_layout.addWidget(import_btn)
        buttons_layout.addWidget(add_btn)
        buttons_layout.addWidget(edit_btn)
        buttons_layout.addWidget(delete_btn)
        layout.addLayout(buttons_layout)

        close_button = QDialogButtonBox(QDialogButtonBox.Close)
        layout.addWidget(close_button)

        add_btn.clicked.connect(self.add_profile)
        edit_btn.clicked.connect(self.edit_profile)
        delete_btn.clicked.connect(self.delete_profile)
        import_btn.clicked.connect(self.import_profiles)
        self.profiles_list_widget.itemDoubleClicked.connect(self.edit_profile)
        close_button.rejected.connect(self.reject)

        self.load_profiles_from_db()

    def load_profiles_from_db(self):
        self.profiles_list_widget.clear()
        with database.DatabaseConnection() as conn:
            db_profiles = conn.execute("SELECT id, profile_key, name FROM profiles WHERE is_deleted = 0 ORDER BY name").fetchall()
        for profile in db_profiles:
            item = QListWidgetItem(profile['name'].upper())
            item.setData(Qt.UserRole, {'id': profile['id'], 'key': profile['profile_key']})
            self.profiles_list_widget.addItem(item)
    
    def add_profile(self):
        # La modalità guidata del dialog parte già con i valori CEI 62353
        # precompilati: non serve più scegliere un template
        temp_profile = VerificationProfile(name="", tests=[])

        dialog = ProfileDetailDialog(profile=temp_profile, parent=self)
        if dialog.exec():
            new_profile = dialog.profile
            new_key = new_profile.name.replace(" ", "_").lower()
            
            with database.DatabaseConnection() as conn:
                existing = conn.execute("SELECT id FROM profiles WHERE profile_key = ?", (new_key,)).fetchone()
            if existing:
                QMessageBox.critical(self, "ERRORE", "UN PROFILO CON UN NOME SIMILE ESISTE GIÀ.")
                return
            
            services.add_profile_with_tests(new_key, new_profile.name, new_profile.tests, norma=new_profile.norma)
            self.profiles_changed = True
            self.load_profiles_from_db()

    def edit_profile(self):
        selected_item = self.profiles_list_widget.currentItem()
        if not selected_item:
            return
        
        item_data = selected_item.data(Qt.UserRole)
        profile_id = item_data['id']
        profile_key = item_data['key']

        profile_to_edit = config.PROFILES.get(profile_key)
        if not profile_to_edit:
            QMessageBox.critical(self, "ERRORE", "IMPOSSIBILE TROVARE IL PROFILO DA MODIFICARE. PROVA A RIAVVIARE L'APPLICAZIONE.")
            return

        dialog = ProfileDetailDialog(profile=profile_to_edit, parent=self)
        if dialog.exec():
            updated_profile = dialog.profile
            services.update_profile_with_tests(profile_id, updated_profile.name, updated_profile.tests, norma=updated_profile.norma)
            self.profiles_changed = True
            # Ricarica i profili globali e poi la lista
            config.load_verification_profiles()
            self.load_profiles_from_db()

    def delete_profile(self):
        selected_item = self.profiles_list_widget.currentItem()
        if not selected_item:
            return
        
        reply = QMessageBox.question(self, "CONFERMA ELIMINAZIONE",
                                     f"SEI SICURO DI VOLER ELIMINARE IL PROFILO '{selected_item.text().upper()}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            profile_id = selected_item.data(Qt.UserRole)['id']
            services.delete_profile(profile_id)
            self.profiles_changed = True
            config.load_verification_profiles()
            self.load_profiles_from_db()

    def _profile_from_dict(self, profile_key: str, payload: dict) -> VerificationProfile:
        """Converte un dizionario JSON nel datamodel del profilo elettrico."""
        profile_name = str(payload.get("name") or profile_key).strip().upper()
        tests_payload = payload.get("tests") or []
        tests: list[Test] = []

        for t in tests_payload:
            if not isinstance(t, dict):
                continue

            limits_obj = {}
            limits_payload = t.get("limits") or {}
            if isinstance(limits_payload, dict):
                for lim_key, lim_val in limits_payload.items():
                    if isinstance(lim_val, dict):
                        limits_obj[str(lim_key)] = Limit(
                            unit=str(lim_val.get("unit") or ""),
                            high_value=(
                                float(lim_val.get("high_value"))
                                if lim_val.get("high_value") is not None and str(lim_val.get("high_value")) != ""
                                else None
                            ),
                        )

            tests.append(
                Test(
                    name=str(t.get("name") or "").strip(),
                    parameter=str(t.get("parameter") or "").strip(),
                    limits=limits_obj,
                    is_applied_part_test=bool(t.get("is_applied_part_test", False)),
                )
            )

        norma = str(payload.get("norma") or "").strip()
        return VerificationProfile(name=profile_name, tests=tests, norma=norma)

    def import_profiles(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "IMPORTA PROFILI ELETTRICI",
            "",
            "File JSON (*.json);;Tutti i file (*.*)",
        )
        if not filename:
            return

        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "ERRORE LETTURA", f"IMPOSSIBILE APRIRE IL FILE:\n{e}")
            return

        # Formati supportati:
        # 1) { "profile_key": {"name": ..., "tests": [...]}, ... }
        # 2) [ {"profile_key": ..., "name": ..., "tests": [...]}, ... ]
        entries: list[tuple[str, dict]] = []

        if isinstance(data, dict):
            for p_key, p_val in data.items():
                if isinstance(p_val, dict):
                    entries.append((str(p_key).strip(), p_val))
        elif isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                p_key = str(item.get("profile_key") or "").strip()
                if not p_key:
                    p_key = str(item.get("name") or "").strip().replace(" ", "_").lower()
                if p_key:
                    entries.append((p_key, item))

        if not entries:
            QMessageBox.warning(self, "FORMATO NON VALIDO", "IL FILE NON CONTIENE PROFILI ELETTRICI IMPORTABILI.")
            return

        imported = 0
        skipped = 0
        errors = []
        limit_warnings = []

        for profile_key, payload in entries:
            try:
                if profile_key in config.PROFILES:
                    skipped += 1
                    continue

                profile = self._profile_from_dict(profile_key, payload)
                if not profile.name or not profile.tests:
                    skipped += 1
                    continue

                # Plausibilità limiti CEI 62353: importa comunque ma segnala
                for w in validate_profile_limits(profile):
                    limit_warnings.append(f"{profile.name} — {w}")

                services.add_profile_with_tests(profile_key, profile.name, profile.tests)
                imported += 1
            except Exception as e:
                errors.append(f"{profile_key}: {e}")

        if imported:
            self.profiles_changed = True
            config.load_verification_profiles()
            self.load_profiles_from_db()

        summary = f"IMPORTATI: {imported}\nSALTATI: {skipped}"
        if errors:
            summary += f"\nERRORI: {len(errors)}"
        if limit_warnings:
            summary += f"\nAVVISI SUI LIMITI: {len(limit_warnings)} (vedi dettagli)"

        msg = QMessageBox(QMessageBox.Information, "IMPORTAZIONE COMPLETATA", summary, parent=self)
        details = []
        if errors:
            details.append("Dettaglio errori:\n" + "\n".join(errors))
        if limit_warnings:
            details.append("Avvisi limiti CEI 62353:\n" + "\n".join(limit_warnings))
        if details:
            msg.setDetailedText("\n\n".join(details))
        msg.exec()