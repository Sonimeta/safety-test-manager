# app/ui/dialogs/applied_parts_presets_dialog.py
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QListWidget, QListWidgetItem,
    QGroupBox, QMessageBox, QSplitter, QHeaderView, QApplication, QStyle,
    QDialogButtonBox
)
from PySide6.QtCore import Qt, Signal
import qtawesome as qta
from app import services

class AppliedPartsPresetsDialog(QDialog):
    """
    Dialog per la gestione dei preset delle parti applicate.
    Consente di creare, modificare, duplicare ed eliminare preset riutilizzabili.
    """
    presets_changed = Signal()

    def __init__(self, parent=None, select_preset_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("GESTIONE PRESET PARTI APPLICATE")
        self.setMinimumSize(820, 520)
        

        self._current_preset_id: int | None = None
        self._current_parts: list[dict] = []

        self._init_ui()
        self._load_presets_list(select_preset_id)
        self.showMaximized()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # Header con icona e titolo
        header_layout = QHBoxLayout()
        title_label = QLabel("<h2>📦 Preset Parti Applicate</h2>")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # Splitter tra lista preset e dettaglio/editor
        splitter = QSplitter(Qt.Horizontal)

        # === PANNELLO SINISTRO: LISTA PRESET ===
        left_widget = QGroupBox("PRESET ESISTENTI")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(8)

        self.preset_list = QListWidget()
        self.preset_list.currentRowChanged.connect(self._on_preset_selected)
        left_layout.addWidget(self.preset_list)

        left_btn_layout = QHBoxLayout()
        self.btn_new_preset = QPushButton(qta.icon('fa5s.plus', color='#16a34a'), " Nuovo Preset")
        self.btn_new_preset.clicked.connect(self._new_preset)
        left_btn_layout.addWidget(self.btn_new_preset)

        self.btn_delete_preset = QPushButton(qta.icon('fa5s.trash', color='#dc2626'), " Elimina")
        self.btn_delete_preset.clicked.connect(self._delete_preset)
        left_btn_layout.addWidget(self.btn_delete_preset)

        left_layout.addLayout(left_btn_layout)
        splitter.addWidget(left_widget)

        # === PANNELLO DESTRO: EDITOR PRESET ===
        right_widget = QGroupBox("DETTAGLIO E MODIFICA PRESET")
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(10)

        # Campi info preset
        form_layout = QVBoxLayout()
        form_layout.setSpacing(6)

        form_layout.addWidget(QLabel("<b>NOME PRESET:</b>"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Es. Monitor Multiparametrico Standard")
        form_layout.addWidget(self.name_edit)

        form_layout.addWidget(QLabel("<b>DESCRIZIONE / NOTE (OPZIONALE):</b>"))
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Es. Include ECG, SpO2, NIBP e Temp")
        form_layout.addWidget(self.desc_edit)

        right_layout.addLayout(form_layout)

        # Tabella delle parti applicate del preset
        right_layout.addWidget(QLabel("<b>ELENCO PARTI APPLICATE:</b>"))
        self.parts_table = QTableWidget(0, 2)
        self.parts_table.setHorizontalHeaderLabels(["NOME DESCRITTIVO P.A.", "TIPO"])
        self.parts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.parts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.parts_table.verticalHeader().setDefaultSectionSize(45)
        right_layout.addWidget(self.parts_table)

        # Riquadro inserimento rapido P.A.
        add_pa_box = QHBoxLayout()
        add_pa_box.setSpacing(6)
        
        self.new_pa_name = QLineEdit()
        self.new_pa_name.setPlaceholderText("Nome P.A. (es. ECG Torace, SpO2, Sonda...)")
        self.new_pa_name.returnPressed.connect(self._add_part_row)
        add_pa_box.addWidget(self.new_pa_name, 1)

        self.new_pa_type = QComboBox()
        self.new_pa_type.addItems(["B", "BF", "CF"])
        self.new_pa_type.setCurrentText("BF")
        add_pa_box.addWidget(self.new_pa_type)

        btn_add_part = QPushButton(qta.icon('fa5s.plus-circle'), " Inserisci P.A.")
        btn_add_part.clicked.connect(self._add_part_row)
        add_pa_box.addWidget(btn_add_part)

        right_layout.addLayout(add_pa_box)

        # Pulsante rimuovi riga selezionata
        table_actions = QHBoxLayout()
        btn_del_part = QPushButton(qta.icon('fa5s.minus-circle'), " Rimuovi P.A. Selezionata")
        btn_del_part.clicked.connect(self._delete_part_row)
        table_actions.addWidget(btn_del_part)
        table_actions.addStretch()

        self.btn_save_preset = QPushButton(qta.icon('fa5s.save'), " Salva Modifiche Preset")
        self.btn_save_preset.setObjectName("primaryButton")
        self.btn_save_preset.clicked.connect(self._save_current_preset)
        table_actions.addWidget(self.btn_save_preset)

        right_layout.addLayout(table_actions)

        splitter.addWidget(right_widget)
        splitter.setSizes([260, 560])
        main_layout.addWidget(splitter, 1)

        # Pulsanti dialog inferiori
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.accept)
        main_layout.addWidget(button_box)

    def _load_presets_list(self, select_preset_id: int | None = None):
        """Carica tutti i preset disponibili nel list widget."""
        self.preset_list.blockSignals(True)
        self.preset_list.clear()
        
        presets = services.get_applied_parts_presets()
        target_row = -1
        
        for idx, p in enumerate(presets):
            item = QListWidgetItem(f"📦  {p['name']}")
            item.setData(Qt.UserRole, p)
            self.preset_list.addItem(item)
            if select_preset_id is not None and p['id'] == select_preset_id:
                target_row = idx

        self.preset_list.blockSignals(False)

        if target_row >= 0:
            self.preset_list.setCurrentRow(target_row)
        elif self.preset_list.count() > 0:
            self.preset_list.setCurrentRow(0)
        else:
            self._new_preset()

    def _on_preset_selected(self, row: int):
        """Mostra i dettagli del preset selezionato nel pannello di destra."""
        if row < 0:
            return
        item = self.preset_list.item(row)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return

        self._current_preset_id = data.get('id')
        self.name_edit.setText(data.get('name', ''))
        self.desc_edit.setText(data.get('description', ''))
        self._current_parts = [dict(p) for p in data.get('parts', [])]
        self._render_parts_table()

    def _render_parts_table(self):
        """Aggiorna la tabella delle parti applicate correnti."""
        self.parts_table.setRowCount(0)
        for p in self._current_parts:
            row = self.parts_table.rowCount()
            self.parts_table.insertRow(row)
            
            name_item = QTableWidgetItem(str(p.get('name', '')).upper())
            self.parts_table.setItem(row, 0, name_item)
            
            type_combo = QComboBox()
            type_combo.addItems(["B", "BF", "CF"])
            type_combo.setCurrentText(str(p.get('part_type', 'BF')).upper())
            type_combo.currentTextChanged.connect(self._sync_parts_from_table)
            self.parts_table.setCellWidget(row, 1, type_combo)

    def _sync_parts_from_table(self):
        """Sincronizza l'elenco `self._current_parts` dallo stato attuale della tabella."""
        parts = []
        for r in range(self.parts_table.rowCount()):
            name_item = self.parts_table.item(r, 0)
            name = name_item.text().strip() if name_item else ""
            type_widget = self.parts_table.cellWidget(r, 1)
            p_type = type_widget.currentText() if isinstance(type_widget, QComboBox) else "BF"
            if name:
                parts.append({'name': name, 'part_type': p_type})
        self._current_parts = parts

    def _add_part_row(self):
        """Aggiunge una nuova riga di parte applicata."""
        name = self.new_pa_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Nome Mancante", "Inserisci il nome descrittivo della parte applicata.")
            self.new_pa_name.setFocus()
            return
        
        p_type = self.new_pa_type.currentText()
        self._sync_parts_from_table()
        self._current_parts.append({'name': name, 'part_type': p_type})
        self._render_parts_table()
        self.new_pa_name.clear()
        self.new_pa_name.setFocus()

    def _delete_part_row(self):
        """Rimuove la riga selezionata dalla tabella."""
        current_row = self.parts_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Selezione Mancante", "Seleziona la parte applicata da rimuovere.")
            return
        
        self._sync_parts_from_table()
        if 0 <= current_row < len(self._current_parts):
            self._current_parts.pop(current_row)
            self._render_parts_table()

    def _new_preset(self):
        """Pulisce i campi per la creazione di un nuovo preset."""
        self.preset_list.blockSignals(True)
        self.preset_list.clearSelection()
        self.preset_list.blockSignals(False)

        self._current_preset_id = None
        self.name_edit.clear()
        self.desc_edit.clear()
        self._current_parts = []
        self._render_parts_table()
        self.name_edit.setFocus()

    def _save_current_preset(self):
        """Salva o aggiorna il preset corrente nel database."""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Dati Mancanti", "Inserisci un nome per il preset.")
            self.name_edit.setFocus()
            return
        
        self._sync_parts_from_table()
        if not self._current_parts:
            QMessageBox.warning(self, "Dati Mancanti", "Inserisci almeno una parte applicata nel preset.")
            self.new_pa_name.setFocus()
            return

        description = self.desc_edit.text().strip()

        try:
            saved_id = services.save_applied_parts_preset(
                name=name,
                parts=self._current_parts,
                description=description,
                preset_id=self._current_preset_id
            )
            self._current_preset_id = saved_id
            self.presets_changed.emit()
            self._load_presets_list(select_preset_id=saved_id)
            QMessageBox.information(self, "Preset Salvato", f"Il preset '{name}' è stato salvato con successo!")
        except Exception as e:
            logging.error(f"Errore salvataggio preset parti applicate: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile salvare il preset:\n{str(e)}")

    def _delete_preset(self):
        """Elimina il preset selezionato."""
        if not self._current_preset_id:
            QMessageBox.warning(self, "Selezione Mancante", "Seleziona un preset da eliminare.")
            return

        name = self.name_edit.text().strip()
        reply = QMessageBox.question(
            self,
            "Conferma Eliminazione",
            f"Sei sicuro di voler eliminare il preset '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                services.delete_applied_parts_preset(self._current_preset_id)
                self.presets_changed.emit()
                self._load_presets_list()
                QMessageBox.information(self, "Preset Eliminato", f"Il preset '{name}' è stato eliminato.")
            except Exception as e:
                logging.error(f"Errore eliminazione preset: {e}", exc_info=True)
                QMessageBox.critical(self, "Errore", f"Impossibile eliminare il preset:\n{str(e)}")
