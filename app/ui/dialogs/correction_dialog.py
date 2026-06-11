from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QDialogButtonBox, QMessageBox,
    QLabel, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QSplitter, QWidget, QComboBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QBrush
from app import services
import logging


class CorrectionDialog(QDialog):
    """
    Finestra per la correzione in blocco delle descrizioni dei dispositivi.
    - Tabella con tutte le descrizioni + conteggio dispositivi
    - Doppio click per modificare inline
    - Selezione multipla + rinomina in batch
    - Filtro rapido per cercare
    - Anteprima dispositivi per la descrizione selezionata
    """

    # campo attivo: "description" | "manufacturer" | "model"
    _FIELD_LABELS = {
        "description":  ("Descrizione", "Descrizione attuale", "Nuova descrizione"),
        "manufacturer": ("Marca",        "Marca attuale",       "Nuova marca"),
        "model":        ("Modello",      "Modello attuale",     "Nuovo modello"),
    }

    def __init__(self, parent=None, field: str = "description"):
        super().__init__(parent)
        self._field = field
        self.setWindowTitle("Correggi Dati Dispositivi")

        # {valore_originale: nuovo_valore} — modifiche pendenti
        self._pending: dict[str, str] = {}

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ── SELETTORE CAMPO ──────────────────────────────────────────────
        field_bar = QHBoxLayout()
        field_bar.setSpacing(6)
        field_bar.addWidget(QLabel("Campo da correggere:"))
        self.field_combo = QComboBox()
        self.field_combo.addItem("Descrizione", "description")
        self.field_combo.addItem("Marca", "manufacturer")
        self.field_combo.addItem("Modello", "model")
        idx = self.field_combo.findData(field)
        if idx >= 0:
            self.field_combo.setCurrentIndex(idx)
        self.field_combo.currentIndexChanged.connect(self._on_field_changed)
        field_bar.addWidget(self.field_combo)
        field_bar.addStretch()
        main_layout.addLayout(field_bar)

        # ── BARRA STRUMENTI ──────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍  Filtra...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)

        self.btn_batch = QPushButton("✏️  Rinomina selezionati…")
        self.btn_batch.setToolTip("Assegna lo stesso nuovo valore a tutte le righe selezionate")
        self.btn_batch.clicked.connect(self._batch_rename)
        self.btn_batch.setEnabled(False)

        self.btn_reset = QPushButton("↩  Annulla modifiche")
        self.btn_reset.setToolTip("Rimuove tutte le modifiche pendenti non ancora salvate")
        self.btn_reset.clicked.connect(self._reset_pending)
        self.btn_reset.setEnabled(False)

        self.pending_label = QLabel("")
        self.pending_label.setStyleSheet("color: #d97706; font-weight: 600;")

        toolbar.addWidget(self.search_edit, 1)
        toolbar.addWidget(self.btn_batch)
        toolbar.addWidget(self.btn_reset)
        toolbar.addWidget(self.pending_label)
        main_layout.addLayout(toolbar)

        # ── SPLITTER: tabella | anteprima ────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # --- Tabella valori ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(4)

        self._table_label = QLabel("")
        self._table_label.setStyleSheet("font-weight:600; font-size:11px;")
        left_layout.addWidget(self._table_label)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.table)

        splitter.addWidget(left)

        # --- Pannello anteprima ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(4)

        self._preview_label = QLabel("")
        self._preview_label.setStyleSheet("font-weight:600; font-size:11px;")
        right_layout.addWidget(self._preview_label)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(4)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setAlternatingRowColors(True)
        right_layout.addWidget(self.preview_table)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter, 1)

        # ── PULSANTI ─────────────────────────────────────────────────────
        self.buttons = QDialogButtonBox()
        self.execute_button = self.buttons.addButton("✅  Salva tutte le correzioni", QDialogButtonBox.AcceptRole)
        self.execute_button.setEnabled(False)
        self.buttons.addButton(QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._execute_all)
        self.buttons.rejected.connect(self.reject)
        main_layout.addWidget(self.buttons)

        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self._loading = False
        self._update_labels()
        self._load_table()

    def _on_field_changed(self):
        self._field = self.field_combo.currentData()
        self._pending.clear()
        self.search_edit.clear()
        self._update_labels()
        self._load_table()

    def _update_labels(self):
        fl, col0, col1 = self._FIELD_LABELS[self._field]
        self._table_label.setText(
            f"{fl} (doppio clic per modificare, Ctrl+clic per selezione multipla)"
        )
        self._preview_label.setText(f"Dispositivi con questo valore")
        self.table.setHorizontalHeaderLabels([col0, col1, "N°"])
        # Preview headers variano per campo
        if self._field == "description":
            self.preview_table.setHorizontalHeaderLabels(["Inv. AMS", "S/N", "Modello", "Destinazione"])
        elif self._field == "manufacturer":
            self.preview_table.setHorizontalHeaderLabels(["Inv. AMS", "S/N", "Modello", "Destinazione"])
        else:  # model
            self.preview_table.setHorizontalHeaderLabels(["Inv. AMS", "S/N", "Marca", "Destinazione"])


    # ── CARICAMENTO ──────────────────────────────────────────────────────

    def _load_table(self):
        self._loading = True
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        try:
            if self._field == "description":
                data = services.get_all_unique_device_descriptions_with_count()
            elif self._field == "manufacturer":
                data = services.get_all_unique_manufacturers_with_count()
            else:  # model
                data = services.get_all_unique_models_with_count()
        except Exception as e:
            logging.error(f"Errore caricamento {self._field}: {e}")
            data = []

        self.table.setRowCount(len(data))
        for row, (desc, count) in enumerate(data):
            item_orig = QTableWidgetItem(str(desc))
            item_orig.setFlags(item_orig.flags() & ~Qt.ItemIsEditable)
            item_orig.setData(Qt.UserRole, str(desc))
            self.table.setItem(row, 0, item_orig)

            pending_val = self._pending.get(str(desc), "")
            item_new = QTableWidgetItem(pending_val)
            item_new.setData(Qt.UserRole, str(desc))
            self.table.setItem(row, 1, item_new)

            item_count = QTableWidgetItem(str(count))
            item_count.setFlags(item_count.flags() & ~Qt.ItemIsEditable)
            item_count.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, item_count)

            self._color_row(row)

        self.table.setSortingEnabled(True)
        self._loading = False
        self._refresh_pending_ui()
        self._apply_filter(self.search_edit.text())

    def _color_row(self, row: int):
        item0 = self.table.item(row, 0)
        item1 = self.table.item(row, 1)
        if not item0 or not item1:
            return
        orig = item0.data(Qt.UserRole)
        new_val = item1.text().strip()
        has_change = bool(new_val) and new_val.upper() != orig.upper()
        color = QColor("#fef9c3") if has_change else QColor(0, 0, 0, 0)
        for col in range(3):
            it = self.table.item(row, col)
            if it:
                it.setBackground(QBrush(color))

    # ── EVENTI TABELLA ───────────────────────────────────────────────────

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._loading or item.column() != 1:
            return
        orig = item.data(Qt.UserRole) or ""
        new_val = item.text().strip()
        if new_val and new_val.upper() != orig.upper():
            self._pending[orig] = new_val
        else:
            self._pending.pop(orig, None)
            self._loading = True
            item.setText("")
            self._loading = False
        self._color_row(item.row())
        self._refresh_pending_ui()

    def _on_selection_changed(self):
        rows = {i.row() for i in self.table.selectedItems()}
        self.btn_batch.setEnabled(len(rows) > 1)
        self._preview_timer.start(150)

    # ── FILTRO ───────────────────────────────────────────────────────────

    def _apply_filter(self, text: str):
        text = text.strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            hide = bool(text and item and text not in item.text().lower())
            self.table.setRowHidden(row, hide)

    # ── BATCH RENAME ─────────────────────────────────────────────────────

    def _batch_rename(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if not rows:
            return
        from PySide6.QtWidgets import QInputDialog
        fl = self._FIELD_LABELS[self._field][0]
        new_val, ok = QInputDialog.getText(
            self,
            "Rinomina selezionati",
            f"Nuovo valore ({fl}) per {len(rows)} voci selezionate:",
        )
        if not ok or not new_val.strip():
            return
        self._loading = True
        for row in rows:
            orig = self.table.item(row, 0).data(Qt.UserRole) if self.table.item(row, 0) else ""
            nv = new_val.strip()
            item_new = self.table.item(row, 1)
            if item_new:
                item_new.setText(nv)
            if nv.upper() != orig.upper():
                self._pending[orig] = nv
            else:
                self._pending.pop(orig, None)
            self._color_row(row)
        self._loading = False
        self._refresh_pending_ui()

    # ── RESET ────────────────────────────────────────────────────────────

    def _reset_pending(self):
        if not self._pending:
            return
        reply = QMessageBox.question(
            self, "Annulla modifiche",
            f"Annullare tutte le {len(self._pending)} modifiche pendenti?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._pending.clear()
        self._load_table()

    # ── ANTEPRIMA ────────────────────────────────────────────────────────

    def _refresh_preview(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        self.preview_table.clearContents()
        self.preview_table.setRowCount(0)
        if not rows:
            return
        if len(rows) == 1:
            orig = self.table.item(rows[0], 0).data(Qt.UserRole) if self.table.item(rows[0], 0) else ""
            try:
                if self._field == "description":
                    devices = [dict(r) for r in services.get_devices_by_description(orig)]
                    col2_key = "model"
                elif self._field == "manufacturer":
                    devices = [dict(r) for r in services.get_devices_by_manufacturer(orig)]
                    col2_key = "model"
                else:  # model
                    devices = [dict(r) for r in services.get_devices_by_model(orig)]
                    col2_key = "manufacturer"
            except Exception:
                devices = []
                col2_key = "model"
            self.preview_table.setRowCount(len(devices))
            for r, dev in enumerate(devices):
                self.preview_table.setItem(r, 0, QTableWidgetItem(str(dev.get("ams_inventory") or "")))
                self.preview_table.setItem(r, 1, QTableWidgetItem(str(dev.get("serial_number") or "")))
                self.preview_table.setItem(r, 2, QTableWidgetItem(str(dev.get(col2_key) or "")))
                self.preview_table.setItem(r, 3, QTableWidgetItem(str(dev.get("destination_name") or "")))
        else:
            self.preview_table.setRowCount(len(rows))
            for idx, row in enumerate(rows):
                orig = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
                count = self.table.item(row, 2).text() if self.table.item(row, 2) else "?"
                new_val = self._pending.get(orig, "")
                self.preview_table.setItem(idx, 0, QTableWidgetItem(orig))
                arrow = f"→  {new_val}" if new_val else "(invariata)"
                self.preview_table.setItem(idx, 1, QTableWidgetItem(arrow))
                self.preview_table.setItem(idx, 2, QTableWidgetItem(f"{count} dispositivi"))
                self.preview_table.setItem(idx, 3, QTableWidgetItem(""))

    # ── PENDING UI ───────────────────────────────────────────────────────

    def _refresh_pending_ui(self):
        n = len(self._pending)
        self.execute_button.setEnabled(n > 0)
        self.btn_reset.setEnabled(n > 0)
        self.pending_label.setText(
            f"{n} modifica{'e' if n > 1 else ''} pendente{'i' if n > 1 else ''}" if n else ""
        )

    # ── SALVATAGGIO ──────────────────────────────────────────────────────

    def _execute_all(self):
        if not self._pending:
            return
        n = len(self._pending)
        reply = QMessageBox.question(
            self, "Conferma salvataggio",
            f"Applicare {n} correzione{'i' if n > 1 else ''} a tutti i dispositivi coinvolti?\nL'operazione non è reversibile.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        errors = []
        total_affected = 0
        for old_val, new_val in self._pending.items():
            try:
                if self._field == "description":
                    total_affected += services.correct_device_description(old_val, new_val.upper())
                elif self._field == "manufacturer":
                    total_affected += services.correct_device_manufacturer(old_val, new_val.upper())
                else:  # model
                    total_affected += services.correct_device_model(old_val, new_val.upper())
            except Exception as e:
                errors.append(f"'{old_val}': {e}")
        if errors:
            QMessageBox.warning(self, "Completato con errori",
                f"Aggiornati {total_affected} dispositivi.\nErrori:\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "Successo",
                f"Completato. Aggiornati {total_affected} dispositivi in {n} categoria{'e' if n > 1 else ''}.")
        self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)