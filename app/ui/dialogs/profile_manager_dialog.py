# app/ui/dialogs/profile_manager_dialog.py
import json
import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, 
                               QMessageBox, QDialogButtonBox, QLineEdit, QTableWidget,
                               QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox,
                               QDoubleSpinBox, QComboBox, QLabel, QFormLayout, QListWidgetItem, QWidget, QFileDialog)
from PySide6.QtCore import Qt
from app.data_models import VerificationProfile, Test, Limit
from app import services, config
import database
from app.ui.dialogs.utility_dialogs import TemplateSelectionDialog
from app.profile_templates import PROFILE_TEMPLATES

# --- NUOVA MAPPA DEI PARAMETRI VALIDI ---
# Le chiavi e i valori DEVONO essere in MAIUSCOLO perché il monkey-patch globale
# in main.py converte automaticamente tutti i testi di QComboBox in uppercase.
VALID_TEST_PARAMETERS = {
    "TENSIONE ALIMENTAZIONE": ["DA FASE A NEUTRO", "DA NEUTRO A TERRA", "DA FASE A TERRA"],
    "CORRENTE DISPERSIONE DIRETTA DISPOSITIVO": ["POLARITÀ NORMALE", "POLARITÀ INVERSA"],
    "CORRENTE DISPERSIONE DIRETTA P.A.": ["POLARITÀ NORMALE", "POLARITÀ INVERSA"]
}

class ProfileDetailDialog(QDialog):
    """Dialog per creare o modificare un singolo profilo di verifica."""
    def __init__(self, profile: VerificationProfile = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DETTAGLI PROFILO DI VERIFICA" if profile and profile.name else "NUOVO PROFILO DI VERIFICA")
        self.setMinimumSize(900, 600)

        self.profile = profile or VerificationProfile(name="", tests=[])
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.profile_name_edit = QLineEdit(self.profile.name)
        form_layout.addRow("NOME PROFILO:", self.profile_name_edit)

        self.norma_edit = QLineEdit(self.profile.norma)
        self.norma_edit.setPlaceholderText("es. CEI EN 62353")
        form_layout.addRow("NORMA DI RIFERIMENTO:", self.norma_edit)
        layout.addLayout(form_layout)

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
        
        dialog_buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(dialog_buttons)

        add_test_btn.clicked.connect(self.add_test_row)
        remove_test_btn.clicked.connect(self.remove_test_row)
        dialog_buttons.accepted.connect(self.accept_changes)
        dialog_buttons.rejected.connect(self.reject)

        self.populate_table()

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
        if test_data: name_combo.setCurrentText(test_data.name)
        self.tests_table.setCellWidget(row, 0, name_combo)
        
        # Inizializza con un widget temporaneo, verrà sostituito da _update_parameter_widget
        self.tests_table.setCellWidget(row, 1, QLineEdit(test_data.parameter if test_data else ""))
        
        limit_spinbox = QDoubleSpinBox(); limit_spinbox.setDecimals(3); limit_spinbox.setRange(0, 99999.999)
        if test_data and test_data.limits:
            first_limit_key = next(iter(test_data.limits), None)
            if first_limit_key:
                limit_value = test_data.limits[first_limit_key].high_value or 0.0
                limit_spinbox.setValue(limit_value)
        self.tests_table.setCellWidget(row, 2, limit_spinbox)
        
        checkbox_container = QWidget(); checkbox_layout = QHBoxLayout(checkbox_container)
        is_ap_checkbox = QCheckBox(); is_ap_checkbox.setChecked(test_data.is_applied_part_test if test_data else False)
        checkbox_layout.addWidget(is_ap_checkbox); checkbox_layout.setAlignment(Qt.AlignCenter); checkbox_layout.setContentsMargins(0,0,0,0)
        self.tests_table.setCellWidget(row, 3, checkbox_container)
        
        ap_type_combo = QComboBox(); ap_type_combo.addItems(["ST", "B", "BF", "CF"])
        if test_data and test_data.limits:
            first_limit_key = next(iter(test_data.limits), None)
            if first_limit_key:
                ap_type_str = first_limit_key.strip(": ")
                ap_type_combo.setCurrentText(ap_type_str)
        self.tests_table.setCellWidget(row, 4, ap_type_combo)

        # Connetti il segnale e aggiorna subito il widget del parametro
        name_combo.currentIndexChanged.connect(lambda: self._update_parameter_widget(row))
        self._update_parameter_widget(row)
        self.tests_table.resizeRowsToContents()
        self.tests_table.resizeColumnsToContents()



    def remove_test_row(self):
        current_row = self.tests_table.currentRow()
        if current_row > -1: self.tests_table.removeRow(current_row)

    def accept_changes(self):
        if not self.profile_name_edit.text().strip():
            QMessageBox.warning(self, "NOME MANCANTE", "IL NOME DEL PROFILO NON PUÒ ESSERE VUOTO.")
            return

        self.profile.name = self.profile_name_edit.text().strip().upper()
        self.profile.norma = self.norma_edit.text().strip()
        self.profile.tests = []
        for row in range(self.tests_table.rowCount()):
            name = self.tests_table.cellWidget(row, 0).currentText()
            
            param_widget = self.tests_table.cellWidget(row, 1)
            param = ""
            if isinstance(param_widget, QComboBox):
                param = param_widget.currentText()
            elif isinstance(param_widget, QLineEdit):
                param = param_widget.text()
            
            if "PAUSA MANUALE" in name:
                self.profile.tests.append(Test(name=name, parameter=param, limits={}, is_applied_part_test=False))
                continue
            
            limit_val = self.tests_table.cellWidget(row, 2).value()
            checkbox_container = self.tests_table.cellWidget(row, 3)
            is_ap_checkbox = checkbox_container.findChild(QCheckBox)
            is_ap = is_ap_checkbox.isChecked() if is_ap_checkbox else False
            ap_type = self.tests_table.cellWidget(row, 4).currentText()
            unit = "uA" if "CORRENTE" in name.upper() else ("Ohm" if "RESISTENZA" in name.upper() else "V")
            limits = {f"::{ap_type}": Limit(unit=unit, high_value=limit_val if limit_val > 0 else None)}
            self.profile.tests.append(Test(name=name, parameter=param, limits=limits, is_applied_part_test=is_ap))
        
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
        template_dialog = TemplateSelectionDialog(PROFILE_TEMPLATES, self)
        if not template_dialog.exec():
            return

        selected_key = template_dialog.selected_template_key
        template_tests = PROFILE_TEMPLATES.get(selected_key, [])

        temp_profile = VerificationProfile(name="", tests=[Test(**t) if isinstance(t, dict) else t for t in template_tests])
        
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

        for profile_key, payload in entries:
            try:
                if profile_key in config.PROFILES:
                    skipped += 1
                    continue

                profile = self._profile_from_dict(profile_key, payload)
                if not profile.name or not profile.tests:
                    skipped += 1
                    continue

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

        msg = QMessageBox(QMessageBox.Information, "IMPORTAZIONE COMPLETATA", summary, parent=self)
        if errors:
            msg.setDetailedText("Dettaglio errori:\n" + "\n".join(errors))
        msg.exec()