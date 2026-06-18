from __future__ import annotations

import copy
import json
import re
import unicodedata
from typing import Optional

from PySide6.QtCore import Qt, Signal, QMimeData, QByteArray
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSpinBox,
    QTextEdit,
    QPlainTextEdit,
)

from app import config, services
from app.functional_builder import (
    OutlineView,
    SimpleFunctionalOptions,
    build_sections,
    default_new_profile_blocks,
    options_from_outline_view,
    outline_view_from_options,
    parse_profile_sections,
)
from app.functional_models import (
    FunctionalField,
    FunctionalProfile,
    FunctionalRowDefinition,
    FunctionalSection,
    functional_profile_from_dict,
    functional_profile_to_dict,
    sanitize_profile_key,
    validate_functional_profile,
)
import database
import qtawesome as qta


FIELD_TYPES = [
    "text",
    "multiline",
    "number",
    "integer",
    "choice",
    "bool",
    "date",
    "time",
    "percentage",
    "rating",
    "pass_fail",
    "header",
    "calculated",
]

# Informazioni descrittive per ogni tipo di campo
FIELD_TYPE_INFO: dict[str, dict] = {
    "text":       {"label": "Testo",               "icon": "fa5s.font",            "color": "#2563eb", "category": "Base",        "desc": "Campo di testo breve (una riga)"},
    "multiline":  {"label": "Testo Multilinea",     "icon": "fa5s.align-left",      "color": "#16a34a", "category": "Base",        "desc": "Campo di testo lungo (più righe)"},
    "number":     {"label": "Numero Decimale",      "icon": "fa5s.hashtag",         "color": "#f59e0b", "category": "Numerico",    "desc": "Numero con decimali (es: 3.14)"},
    "integer":    {"label": "Numero Intero",        "icon": "fa5s.sort-numeric-up", "color": "#8b5cf6", "category": "Numerico",    "desc": "Numero senza decimali (es: 42)"},
    "percentage": {"label": "Percentuale",          "icon": "fa5s.percentage",      "color": "#0891b2", "category": "Numerico",    "desc": "Valore percentuale da 0% a 100%"},
    "choice":     {"label": "Scelta Multipla",      "icon": "fa5s.list",            "color": "#ec4899", "category": "Selezione",   "desc": "Menù a tendina con opzioni personalizzate"},
    "bool":       {"label": "Booleano (Sì/No)",     "icon": "fa5s.check-square",    "color": "#10b981", "category": "Selezione",   "desc": "Scelta tra due opzioni (es: OK/KO)"},
    "pass_fail":  {"label": "Esito (Pass/Fail)",    "icon": "fa5s.clipboard-check", "color": "#059669", "category": "Selezione",   "desc": "Esito rapido: PASS, FAIL, N.A."},
    "rating":     {"label": "Valutazione (Rating)",  "icon": "fa5s.star",            "color": "#eab308", "category": "Selezione",   "desc": "Scala numerica (es: da 1 a 5 stelle)"},
    "date":       {"label": "Data",                 "icon": "fa5s.calendar-alt",    "color": "#6366f1", "category": "Data/Ora",    "desc": "Selettore di data (GG/MM/AAAA)"},
    "time":       {"label": "Ora",                  "icon": "fa5s.clock",           "color": "#7c3aed", "category": "Data/Ora",    "desc": "Selettore di orario (HH:MM)"},
    "header":     {"label": "Intestazione/Separatore", "icon": "fa5s.heading",      "color": "#64748b", "category": "Layout",      "desc": "Testo statico di intestazione (non compilabile)"},
    "calculated": {"label": "Campo Calcolato",      "icon": "fa5s.calculator",      "color": "#0d9488", "category": "Avanzato",    "desc": "Valore calcolato da formula (sola lettura)"},
}

# Ordine delle categorie per il selettore visivo
FIELD_TYPE_CATEGORIES = ["Base", "Numerico", "Selezione", "Data/Ora", "Layout", "Avanzato"]

# ─── Drag & drop ─────────────────────────────────────────────────────────────
SECTION_PRESET_MIME = "application/x-stm-section-preset"

# Blocchi trascinabili dalla palette nel profilo (chiave, etichetta, icona, colore)
SECTION_PRESETS = [
    ("checklist", "Checklist", "fa5s.check-square", "#16a34a"),
    ("normative", "Riferimenti normativi", "fa5s.book", "#2563eb"),
    ("fields", "Campi liberi", "fa5s.list", "#7c3aed"),
    ("notes", "Note", "fa5s.sticky-note", "#f59e0b"),
]


class SectionPalette(QListWidget):
    """Palette di blocchi trascinabili: si trascina una voce nel profilo per
    aggiungere quel tipo di sezione."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        for key, label, icon, color in SECTION_PRESETS:
            item = QListWidgetItem(qta.icon(icon, color=color), label)
            item.setData(Qt.UserRole, key)
            item.setToolTip("Trascina nel profilo per aggiungere questa sezione")
            self.addItem(item)

    def mimeData(self, items):
        md = QMimeData()
        if items:
            preset = str(items[0].data(Qt.UserRole) or "")
            md.setData(SECTION_PRESET_MIME, QByteArray(preset.encode()))
        return md


class DragDropList(QListWidget):
    """Lista che supporta il riordino per trascinamento e (opzionale) il drop
    dei blocchi dalla palette. Non sposta gli item da sola: emette segnali e
    lascia che sia il dialog a riordinare/creare i dati e a ridisegnare."""
    reorder_requested = Signal(int, int)   # riga origine, riga destinazione
    preset_dropped = Signal(str, int)      # chiave preset, riga destinazione

    def __init__(self, accept_presets: bool = False, parent=None):
        super().__init__(parent)
        self._accept_presets = accept_presets
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.viewport().setAcceptDrops(True)

    def _accepts(self, event) -> bool:
        if self._accept_presets and event.mimeData().hasFormat(SECTION_PRESET_MIME):
            return True
        return event.source() is self

    def dragEnterEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _drop_row(self, event) -> int:
        row = self.indexAt(event.position().toPoint()).row()
        return row

    def dropEvent(self, event):
        if self._accept_presets and event.mimeData().hasFormat(SECTION_PRESET_MIME):
            preset = bytes(event.mimeData().data(SECTION_PRESET_MIME)).decode()
            row = self._drop_row(event)
            if row < 0:
                row = self.count()
            event.setDropAction(Qt.IgnoreAction)
            event.accept()
            self.preset_dropped.emit(preset, row)
            return
        if event.source() is self:
            src = self.currentRow()
            dst = self._drop_row(event)
            if dst < 0:
                dst = self.count() - 1
            event.setDropAction(Qt.IgnoreAction)
            event.accept()
            if src >= 0 and src != dst:
                self.reorder_requested.emit(src, dst)
            return
        event.ignore()


def move_in_list(items: list, src: int, dst: int):
    """Sposta items[src] in posizione dst (semantica 'rilascia sulla riga dst')."""
    if src < 0 or src >= len(items) or src == dst:
        return
    element = items.pop(src)
    if src < dst:
        dst -= 1
    dst = max(0, min(dst, len(items)))
    items.insert(dst, element)


class FieldEditorDialog(QDialog):
    def __init__(self, field: Optional[FunctionalField] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editor Campo")
        self.setMinimumSize(650, 480)
        # Applica il tema corrente
        self.setStyleSheet(config.get_current_stylesheet())
        self.field = field or FunctionalField(key="", label="", field_type="text")
        # Flag per capire se l'utente ha modificato manualmente la chiave:
        # - nuovo campo (key vuota) → generazione automatica dalla label
        # - campo esistente (key già valorizzata) → NON toccare la chiave
        self._key_user_edited = bool(self.field.key)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # --- Scroll Area per rendere il contenuto scorrevole ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        main_layout = QVBoxLayout(scroll_content)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(6)
        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll)
        
        form_widget = QGroupBox("Informazioni Base")
        form = QFormLayout(form_widget)
        form.setSpacing(4)

        self.label_edit = QLineEdit(self.field.label)
        self.label_edit.setPlaceholderText("Etichetta visualizzata all'utente")
        form.addRow("Etichetta *:", self.label_edit)

        self.key_edit = QLineEdit(self.field.key)
        self.key_edit.setPlaceholderText("Generata automaticamente dall'etichetta")
        form.addRow("Chiave *:", self.key_edit)

        # --- Selettore tipo campo visivo (compatto, 4 colonne) ---
        type_group = QGroupBox("Tipo Campo *")
        type_group_layout = QVBoxLayout(type_group)
        type_group_layout.setSpacing(2)
        type_group_layout.setContentsMargins(6, 6, 6, 6)
        self.type_grid = QGridLayout()
        self.type_grid.setSpacing(3)
        self.type_grid.setContentsMargins(0, 0, 0, 0)
        self._type_buttons: dict[str, QPushButton] = {}
        col = 0
        row_idx = 0
        max_cols = 4

        for category in FIELD_TYPE_CATEGORIES:
            # Se non siamo alla prima categoria, aggiungi un piccolo separatore
            if row_idx > 0 and col == 0:
                pass  # lo spazio viene già dato dalla riga precedente
            elif col > 0:
                row_idx += 1
                col = 0

            for ft, info in FIELD_TYPE_INFO.items():
                if info["category"] != category:
                    continue
                btn = QPushButton(qta.icon(info["icon"], color=info["color"]), info['label'])
                btn.setCheckable(True)
                btn.setToolTip(f"{info['category']} — {info['desc']}")
                btn.setFixedHeight(26)
                btn.setStyleSheet(
                    "QPushButton { text-align: left; padding: 2px 5px; border: 1px solid #ccc; border-radius: 3px; font-size: 11px; }"
                    "QPushButton:checked { border: 2px solid " + info["color"] + "; background: rgba(37,99,235,0.08); font-weight: bold; }"
                )
                btn.clicked.connect(lambda checked, t=ft: self._select_type(t))
                self.type_grid.addWidget(btn, row_idx, col)
                self._type_buttons[ft] = btn
                col += 1
                if col >= max_cols:
                    col = 0
                    row_idx += 1
            if col > 0:
                row_idx += 1
                col = 0

        type_group_layout.addLayout(self.type_grid)

        self.type_desc_label = QLabel("")
        self.type_desc_label.setWordWrap(True)
        self.type_desc_label.setStyleSheet("color: #64748b; font-style: italic; padding: 2px; font-size: 11px;")
        type_group_layout.addWidget(self.type_desc_label)

        form.addRow(type_group)
        main_layout.addWidget(form_widget)
        
        # --- Pannello opzioni dinamiche ---
        self.options_group = QGroupBox("Opzioni Campo")
        self.options_form = QFormLayout(self.options_group)

        self.required_check = QCheckBox("Campo obbligatorio")
        self.required_check.setChecked(self.field.required)
        self.options_form.addRow(self.required_check)

        self.readonly_check = QCheckBox("Sola lettura (non modificabile)")
        self.readonly_check.setChecked(self.field.read_only)
        self.options_form.addRow(self.readonly_check)

        self.unit_edit = QLineEdit(self.field.unit or "")
        self.unit_edit.setPlaceholderText("es: bpm, mV, V, °C")
        self.unit_row_label = QLabel("Unità di misura:")
        self.options_form.addRow(self.unit_row_label, self.unit_edit)

        self.options_edit = QLineEdit(",".join(self.field.options or []))
        self.options_edit.setPlaceholderText("es: OK,KO,N.A. (separati da virgola)")
        self.options_row_label = QLabel("Opzioni:")
        self.options_form.addRow(self.options_row_label, self.options_edit)

        # Presets rapidi per opzioni
        presets_layout = QHBoxLayout()
        presets_label = QLabel("Presets:")
        presets_label.setStyleSheet("color: #64748b; font-size: 11px;")
        presets_layout.addWidget(presets_label)
        for preset_name, preset_values in [
            ("OK/KO", "OK,KO"),
            ("OK/KO/N.A.", "OK,KO,N.A."),
            ("Sì/No", "Sì,No"),
            ("Conforme/Non Conforme", "Conforme,Non Conforme"),
            ("1-5", "1,2,3,4,5"),
        ]:
            preset_btn = QPushButton(preset_name)
            preset_btn.setMaximumHeight(24)
            preset_btn.setStyleSheet("font-size: 10px; padding: 2px 6px;")
            preset_btn.clicked.connect(lambda _, v=preset_values: self.options_edit.setText(v))
            presets_layout.addWidget(preset_btn)
        presets_layout.addStretch()
        self.presets_widget = QWidget()
        self.presets_widget.setLayout(presets_layout)
        self.options_form.addRow("", self.presets_widget)

        self.default_edit = QLineEdit("" if self.field.default is None else str(self.field.default))
        self.default_edit.setPlaceholderText("Valore predefinito")
        self.default_row_label = QLabel("Valore predefinito:")
        self.options_form.addRow(self.default_row_label, self.default_edit)

        self.help_edit = QLineEdit(self.field.help_text or "")
        self.help_edit.setPlaceholderText("Suggerimento per l'utente")
        self.options_form.addRow("Suggerimento:", self.help_edit)

        self.placeholder_edit = QLineEdit(self.field.placeholder or "")
        self.placeholder_edit.setPlaceholderText("Testo visualizzato nel campo vuoto")
        self.placeholder_row_label = QLabel("Placeholder:")
        self.options_form.addRow(self.placeholder_row_label, self.placeholder_edit)

        # Opzioni numeriche (min, max, step)
        numeric_row = QHBoxLayout()
        self.min_spin = QLineEdit(str(self.field.min_value) if self.field.min_value is not None else "")
        self.min_spin.setPlaceholderText("Min")
        self.max_spin = QLineEdit(str(self.field.max_value) if self.field.max_value is not None else "")
        self.max_spin.setPlaceholderText("Max")
        self.step_spin = QLineEdit(str(self.field.step) if self.field.step is not None else "")
        self.step_spin.setPlaceholderText("Passo")
        numeric_row.addWidget(QLabel("Min:"))
        numeric_row.addWidget(self.min_spin)
        numeric_row.addWidget(QLabel("Max:"))
        numeric_row.addWidget(self.max_spin)
        numeric_row.addWidget(QLabel("Passo:"))
        numeric_row.addWidget(self.step_spin)
        self.numeric_widget = QWidget()
        self.numeric_widget.setLayout(numeric_row)
        self.numeric_row_label = QLabel("Limiti numerici:")
        self.options_form.addRow(self.numeric_row_label, self.numeric_widget)

        # Rating max
        self.rating_max_spin = QSpinBox()
        self.rating_max_spin.setRange(2, 10)
        self.rating_max_spin.setValue(self.field.rating_max or 5)
        self.rating_max_label = QLabel("Scala massima:")
        self.options_form.addRow(self.rating_max_label, self.rating_max_spin)

        # Formula
        self.formula_edit = QLineEdit(self.field.formula or "")
        self.formula_edit.setPlaceholderText("es: field1 + field2")
        self.formula_row_label = QLabel("Formula calcolo:")
        self.options_form.addRow(self.formula_row_label, self.formula_edit)
        
        formula_help = QLabel()
        formula_help.setWordWrap(True)
        formula_help.setTextFormat(Qt.RichText)
        formula_help.setText("<small>Usa i nomi delle chiavi dei campi per riferirti ad altri valori. "
                             "Es: <code>campo_a * campo_b / 100</code></small>")
        self.formula_help_label = formula_help
        self.options_form.addRow("", formula_help)

        # Precisione decimali
        self.precision_spin = QSpinBox()
        self.precision_spin.setRange(-1, 6)
        self.precision_spin.setSpecialValueText("Default (3 decimali)")
        if self.field.precision is not None:
            self.precision_spin.setValue(self.field.precision)
        else:
            self.precision_spin.setValue(-1)
        self.precision_row_label = QLabel("Decimali:")
        self.options_form.addRow(self.precision_row_label, self.precision_spin)
        
        main_layout.addWidget(self.options_group)

        # Collegamenti per generare la chiave automaticamente dalla label,
        # finché l'utente non modifica la chiave a mano.
        self.label_edit.textChanged.connect(self._on_label_changed)
        self.key_edit.textEdited.connect(self._on_key_edited)

        self.formula_edit.textChanged.connect(self._on_formula_changed)
        self._on_formula_changed(self.formula_edit.text())

        # Pulsanti OK/Cancel fuori dalla scroll area (sempre visibili)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer_layout.addWidget(buttons)

        # Seleziona il tipo corrente
        self._select_type(self.field.field_type)

    def _select_type(self, field_type: str):
        """Seleziona un tipo di campo nel selettore visivo e aggiorna le opzioni visibili."""
        # Aggiorna toggle buttons
        for ft, btn in self._type_buttons.items():
            btn.setChecked(ft == field_type)

        # Aggiorna descrizione
        info = FIELD_TYPE_INFO.get(field_type, {})
        self.type_desc_label.setText(info.get("desc", ""))

        # Mostra/nascondi opzioni in base al tipo
        is_numeric = field_type in {"number", "integer", "percentage"}
        is_choice = field_type in {"choice", "bool"}
        is_rating = field_type == "rating"
        is_header = field_type == "header"
        is_calculated = field_type == "calculated"
        is_text_like = field_type in {"text", "multiline"}

        # Visibilità opzioni
        self.unit_row_label.setVisible(is_numeric or field_type in {"text", "number", "integer", "percentage"})
        self.unit_edit.setVisible(is_numeric or field_type in {"text", "number", "integer", "percentage"})

        self.options_row_label.setVisible(is_choice)
        self.options_edit.setVisible(is_choice)
        self.presets_widget.setVisible(is_choice)

        self.numeric_row_label.setVisible(is_numeric)
        self.numeric_widget.setVisible(is_numeric)

        self.rating_max_label.setVisible(is_rating)
        self.rating_max_spin.setVisible(is_rating)

        self.formula_row_label.setVisible(is_calculated or is_numeric)
        self.formula_edit.setVisible(is_calculated or is_numeric)
        self.formula_help_label.setVisible(is_calculated or is_numeric)

        self.precision_row_label.setVisible(is_numeric)
        self.precision_spin.setVisible(is_numeric)

        self.placeholder_row_label.setVisible(is_text_like)
        self.placeholder_edit.setVisible(is_text_like)

        self.required_check.setVisible(not is_header)
        self.readonly_check.setVisible(not is_header and not is_calculated)

        self.default_row_label.setVisible(not is_header)
        self.default_edit.setVisible(not is_header)

        # Auto-imposta opzioni per pass_fail
        if field_type == "pass_fail" and not self.options_edit.text().strip():
            self.options_edit.setText("PASS,FAIL,N.A.")

        # Auto-imposta opzioni per bool
        if field_type == "bool" and not self.options_edit.text().strip():
            self.options_edit.setText("OK,KO")

        # Header è sempre read-only
        if is_header:
            self.readonly_check.setChecked(True)

        # Calculated è sempre read-only
        if is_calculated:
            self.readonly_check.setChecked(True)

    def _slugify_key(self, text: str) -> str:
        """
        Genera una chiave "pulita" a partire dall'etichetta:
        - minuscolo
        - rimozione accenti
        - spazi e caratteri non alfanumerici → underscore
        """
        if not text:
            return ""
        value = text.strip().lower()
        if not value:
            return ""
        # Rimuove accenti/diacritici
        value = unicodedata.normalize("NFKD", value)
        value = "".join(c for c in value if not unicodedata.combining(c))
        # Sostituisce tutto ciò che non è a-z o 0-9 con underscore
        value = re.sub(r"[^a-z0-9]+", "_", value)
        # Rimuove underscore iniziali/finali
        value = value.strip("_")
        return value

    def _on_label_changed(self, text: str):
        """
        Aggiorna automaticamente la chiave quando cambia la label,
        ma solo se l'utente non ha mai modificato manualmente la chiave.
        """
        if self._key_user_edited:
            return
        auto_key = self._slugify_key(text)
        self.key_edit.setText(auto_key)

    def _on_key_edited(self, _text: str):
        """
        Segnala che l'utente ha modificato manualmente la chiave,
        disabilitando la generazione automatica da questo momento in poi.
        """
        self._key_user_edited = True

    def _get_selected_type(self) -> str:
        """Restituisce il tipo di campo attualmente selezionato."""
        for ft, btn in self._type_buttons.items():
            if btn.isChecked():
                return ft
        return "text"

    def _on_formula_changed(self, text: str):
        has_formula = bool(text.strip())
        self.readonly_check.setEnabled(not has_formula)
        if has_formula:
            self.readonly_check.setChecked(True)

    def accept(self):
        key = self.key_edit.text().strip()
        label = self.label_edit.text().strip()

        if not key:
            QMessageBox.warning(self, "Campo invalido", "La chiave del campo è obbligatoria.")
            return
        if not label:
            QMessageBox.warning(self, "Campo invalido", "L'etichetta del campo è obbligatoria.")
            return

        field_type = self._get_selected_type()
        options = [opt.strip() for opt in self.options_edit.text().split(",") if opt.strip()]

        # Per pass_fail, forza le opzioni standard
        if field_type == "pass_fail":
            if not options:
                options = ["PASS", "FAIL", "N.A."]

        default_value = self.default_edit.text().strip()
        if default_value == "":
            default = None
        else:
            try:
                if field_type in {"number", "percentage"}:
                    default = float(default_value)
                elif field_type == "integer":
                    default = int(default_value)
                elif field_type == "bool":
                    default = default_value.lower() in {"true", "si", "sì", "1", "ok"}
                elif field_type == "rating":
                    default = int(default_value)
                else:
                    default = default_value
            except ValueError:
                QMessageBox.warning(self, "Valore non valido", "Il valore predefinito non è compatibile con il tipo.")
                return

        formula_value = self.formula_edit.text().strip() or None
        precision_value = self.precision_spin.value()
        precision = precision_value if precision_value >= 0 else None

        read_only_value = self.readonly_check.isChecked()
        if formula_value or field_type in {"header", "calculated"}:
            read_only_value = True

        # Parse limiti numerici
        min_value = None
        max_value = None
        step_value = None
        if field_type in {"number", "integer", "percentage"}:
            try:
                if self.min_spin.text().strip():
                    min_value = float(self.min_spin.text().strip())
            except ValueError:
                pass
            try:
                if self.max_spin.text().strip():
                    max_value = float(self.max_spin.text().strip())
            except ValueError:
                pass
            try:
                if self.step_spin.text().strip():
                    step_value = float(self.step_spin.text().strip())
            except ValueError:
                pass

        # Per percentage, forza range 0-100 se non specificato
        if field_type == "percentage":
            if min_value is None:
                min_value = 0.0
            if max_value is None:
                max_value = 100.0

        rating_max = None
        if field_type == "rating":
            rating_max = self.rating_max_spin.value()

        placeholder = self.placeholder_edit.text().strip() or None

        self.field = FunctionalField(
            key=key,
            label=label,
            field_type=field_type,
            required=self.required_check.isChecked() if field_type != "header" else False,
            unit=self.unit_edit.text().strip() or None,
            options=options,
            read_only=read_only_value,
            default=default,
            help_text=self.help_edit.text().strip() or None,
            formula=formula_value,
            precision=precision,
            min_value=min_value,
            max_value=max_value,
            step=step_value,
            placeholder=placeholder,
            rating_max=rating_max,
        )
        super().accept()


class RowEditorDialog(QDialog):
    def __init__(self, row: Optional[FunctionalRowDefinition] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editor Riga")
        self.setMinimumSize(700, 600)
        # Applica il tema corrente
        self.setStyleSheet(config.get_current_stylesheet())
        self.row = copy.deepcopy(row) if row else FunctionalRowDefinition(key="", label="", fields=[])

        main_layout = QVBoxLayout(self)
        
        header_label = QLabel("<h3>Configurazione Riga</h3>")
        main_layout.addWidget(header_label)

        form_widget = QGroupBox("Informazioni Base")
        form = QFormLayout(form_widget)
        self.key_edit = QLineEdit(self.row.key)
        self.key_edit.setPlaceholderText("es: freq_row_1")
        form.addRow("Chiave *:", self.key_edit)
        
        self.label_edit = QLineEdit(self.row.label or "")
        self.label_edit.setPlaceholderText("Etichetta visualizzata (es: Livello 1)")
        form.addRow("Etichetta:", self.label_edit)
        main_layout.addWidget(form_widget)

        fields_group = QGroupBox("Campi della Riga")
        fields_layout = QVBoxLayout(fields_group)
        self.fields_table = QTableWidget(0, 6)
        self.fields_table.setHorizontalHeaderLabels(["Chiave", "Etichetta", "Tipo", "Obbl.", "Sola lett.", "Formula"])
        self.fields_table.horizontalHeader().setStretchLastSection(True)
        self.fields_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fields_table.setAlternatingRowColors(True)
        fields_layout.addWidget(self.fields_table)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton(qta.icon('fa5s.plus'), " Aggiungi")
        add_btn.setObjectName("autoButton")
        edit_btn = QPushButton(qta.icon('fa5s.edit'), " Modifica")
        edit_btn.setObjectName("editButton")
        remove_btn = QPushButton(qta.icon('fa5s.trash'), " Rimuovi")
        remove_btn.setObjectName("deleteButton")
        self.field_up_btn = QPushButton(qta.icon('fa5s.arrow-up'), "")
        self.field_up_btn.setToolTip("Sposta su")
        self.field_down_btn = QPushButton(qta.icon('fa5s.arrow-down'), "")
        self.field_down_btn.setToolTip("Sposta giù")
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addWidget(self.field_up_btn)
        btn_layout.addWidget(self.field_down_btn)
        btn_layout.addStretch()
        fields_layout.addLayout(btn_layout)
        main_layout.addWidget(fields_group, 1)

        add_btn.clicked.connect(self.add_field)
        edit_btn.clicked.connect(self.edit_field)
        remove_btn.clicked.connect(self.remove_field)
        self.field_up_btn.clicked.connect(self.move_field_up)
        self.field_down_btn.clicked.connect(self.move_field_down)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self._refresh_fields()

    def _refresh_fields(self):
        self.fields_table.setRowCount(0)
        for field in self.row.fields:
            row_idx = self.fields_table.rowCount()
            self.fields_table.insertRow(row_idx)
            self.fields_table.setItem(row_idx, 0, QTableWidgetItem(field.key))
            self.fields_table.setItem(row_idx, 1, QTableWidgetItem(field.label))
            self.fields_table.setItem(row_idx, 2, QTableWidgetItem(field.field_type))
            self.fields_table.setItem(row_idx, 3, QTableWidgetItem("Sì" if field.required else "No"))
            self.fields_table.setItem(row_idx, 4, QTableWidgetItem("Sì" if field.read_only else "No"))
            self.fields_table.setItem(row_idx, 5, QTableWidgetItem(field.formula or ""))

    def add_field(self):
        dialog = FieldEditorDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            new_field = dialog.field
            if any(f.key == new_field.key for f in self.row.fields):
                QMessageBox.warning(self, "Chiave duplicata", f"Esiste già un campo con chiave '{new_field.key}'.")
                return
            self.row.fields.append(new_field)
            self._refresh_fields()

    def edit_field(self):
        row_idx = self.fields_table.currentRow()
        if row_idx < 0:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona un campo da modificare.")
            return
        dialog = FieldEditorDialog(field=self.row.fields[row_idx], parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.row.fields[row_idx] = dialog.field
            self._refresh_fields()

    def remove_field(self):
        row_idx = self.fields_table.currentRow()
        if row_idx < 0:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona un campo da rimuovere.")
            return
        self.row.fields.pop(row_idx)
        self._refresh_fields()

    def move_field_up(self):
        row_idx = self.fields_table.currentRow()
        if row_idx <= 0:
            return
        self.row.fields[row_idx - 1], self.row.fields[row_idx] = (
            self.row.fields[row_idx],
            self.row.fields[row_idx - 1],
        )
        self._refresh_fields()
        self.fields_table.selectRow(row_idx - 1)

    def move_field_down(self):
        row_idx = self.fields_table.currentRow()
        if row_idx < 0 or row_idx >= len(self.row.fields) - 1:
            return
        self.row.fields[row_idx + 1], self.row.fields[row_idx] = (
            self.row.fields[row_idx],
            self.row.fields[row_idx + 1],
        )
        self._refresh_fields()
        self.fields_table.selectRow(row_idx + 1)

    def accept(self):
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "Chiave mancante", "La chiave della riga è obbligatoria.")
            return
        if not self.row.fields:
            QMessageBox.warning(self, "Campi mancanti", "Aggiungere almeno un campo alla riga.")
            return
        self.row.key = key
        self.row.label = self.label_edit.text().strip() or None
        super().accept()


class SectionEditorDialog(QDialog):
    def __init__(self, section: Optional[FunctionalSection] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editor Sezione")
        self.setMinimumSize(800, 650)
        # Applica il tema corrente
        self.setStyleSheet(config.get_current_stylesheet())
        self.section = copy.deepcopy(section) if section else FunctionalSection(
            key="",
            title="",
            section_type="fields",
            description="",
            fields=[],
            rows=[],
        )
        # Flag per auto-generazione chiave dal titolo
        self._key_user_edited = bool(self.section.key)

        main_layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("<h3>Configurazione Sezione</h3>")
        main_layout.addWidget(header_label)

        form_widget = QGroupBox("Informazioni Base")
        form_layout = QFormLayout(form_widget)

        self.title_edit = QLineEdit(self.section.title)
        self.title_edit.setPlaceholderText("es: Controlli Visivi, Misurazioni, Note")
        form_layout.addRow("Titolo *:", self.title_edit)
        
        self.key_edit = QLineEdit(self.section.key)
        self.key_edit.setPlaceholderText("Generata automaticamente dal titolo")
        form_layout.addRow("Chiave *:", self.key_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem(qta.icon('fa5s.list', color='#2563eb'), "Campi (Fields)", "fields")
        self.type_combo.addItem(qta.icon('fa5s.check-square', color='#16a34a'), "Checklist", "checklist")
        self.type_combo.addItem(qta.icon('fa5s.table', color='#f59e0b'), "Tabella (Table)", "table")
        
        if self.section.section_type in {"fields", "checklist", "table"}:
            for i in range(self.type_combo.count()):
                if self.type_combo.itemData(i) == self.section.section_type:
                    self.type_combo.setCurrentIndex(i)
                    break
        
        form_layout.addRow("Tipo Sezione *:", self.type_combo)
        
        help_label = QLabel()
        help_label.setWordWrap(True)
        help_label.setTextFormat(Qt.RichText)
        help_label.setText(
            "<small>"
            "<b>Campi:</b> Form con campi singoli (testo, numeri, scelte...)<br>"
            "<b>Checklist:</b> Lista di elementi da verificare con esito<br>"
            "<b>Tabella:</b> Tabella con righe e colonne personalizzabili"
            "</small>"
        )
        form_layout.addRow("", help_label)

        self.description_edit = QLineEdit(self.section.description or "")
        self.description_edit.setPlaceholderText("Descrizione opzionale della sezione")
        form_layout.addRow("Descrizione:", self.description_edit)

        self.show_in_summary_checkbox = QCheckBox("Mostra in prima pagina report")
        self.show_in_summary_checkbox.setChecked(self.section.show_in_summary)
        form_layout.addRow("", self.show_in_summary_checkbox)

        main_layout.addWidget(form_widget)

        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack, 1)

        # Pannello per i campi (fields)
        self.fields_table = QTableWidget(0, 6)
        self.fields_table.setHorizontalHeaderLabels(["Chiave", "Etichetta", "Tipo", "Obbl.", "Sola lett.", "Formula"])
        self.fields_table.horizontalHeader().setStretchLastSection(True)
        self.fields_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fields_table.setAlternatingRowColors(True)

        fields_widget = QWidget()
        fields_layout = QVBoxLayout(fields_widget)
        fields_label = QLabel("<b>Campi della Sezione</b>")
        fields_layout.addWidget(fields_label)
        # Aggiunta rapida inline: scrivi l'etichetta e premi Invio (campo testo;
        # tipo e dettagli si cambiano poi col doppio clic / Modifica)
        self.field_quick_edit = QLineEdit()
        self.field_quick_edit.setPlaceholderText("➕  Scrivi un campo e premi Invio per aggiungerlo…")
        self.field_quick_edit.returnPressed.connect(self._inline_add_field)
        fields_layout.addWidget(self.field_quick_edit)
        fields_layout.addWidget(self.fields_table)
        fields_btn_layout = QHBoxLayout()
        self.field_add_btn = QPushButton(qta.icon('fa5s.plus'), " Aggiungi")
        self.field_add_btn.setObjectName("autoButton")
        self.field_edit_btn = QPushButton(qta.icon('fa5s.edit'), " Modifica")
        self.field_edit_btn.setObjectName("editButton")
        self.field_dup_btn = QPushButton(qta.icon('fa5s.copy'), " Duplica")
        self.field_dup_btn.setToolTip("Duplica il campo selezionato")
        self.field_remove_btn = QPushButton(qta.icon('fa5s.trash'), " Rimuovi")
        self.field_remove_btn.setObjectName("deleteButton")
        self.field_up_btn = QPushButton(qta.icon('fa5s.arrow-up'), "")
        self.field_up_btn.setToolTip("Sposta su")
        self.field_down_btn = QPushButton(qta.icon('fa5s.arrow-down'), "")
        self.field_down_btn.setToolTip("Sposta giù")
        fields_btn_layout.addWidget(self.field_add_btn)
        fields_btn_layout.addWidget(self.field_edit_btn)
        fields_btn_layout.addWidget(self.field_dup_btn)
        fields_btn_layout.addWidget(self.field_remove_btn)
        fields_btn_layout.addWidget(self.field_up_btn)
        fields_btn_layout.addWidget(self.field_down_btn)
        fields_btn_layout.addStretch()
        fields_layout.addLayout(fields_btn_layout)
        self.stack.addWidget(fields_widget)

        # Pannello per le righe (checklist/table)
        rows_widget = QWidget()
        rows_layout = QVBoxLayout(rows_widget)
        rows_label = QLabel("<b>Verifiche della Sezione</b>  <span style='color:#64748b;'>(doppio clic per rinominare)</span>")
        rows_label.setTextFormat(Qt.RichText)
        rows_layout.addWidget(rows_label)
        # Aggiunta rapida inline: scrivi la verifica e premi Invio (esito OK/KO/N.A.
        # automatico). Niente più finestre annidate per il caso comune
        self.row_quick_edit = QLineEdit()
        self.row_quick_edit.setPlaceholderText("➕  Scrivi una verifica e premi Invio per aggiungerla…")
        self.row_quick_edit.returnPressed.connect(self._inline_add_row)
        rows_layout.addWidget(self.row_quick_edit)
        self.rows_list = DragDropList()
        self.rows_list.setAlternatingRowColors(True)
        self.rows_list.reorder_requested.connect(self._reorder_rows)
        rows_layout.addWidget(self.rows_list)
        rows_btn_layout = QHBoxLayout()
        self.row_add_btn = QPushButton(qta.icon('fa5s.plus'), " Aggiungi")
        self.row_add_btn.setObjectName("autoButton")
        self.row_quick_add_btn = QPushButton(qta.icon('fa5s.bolt'), " Aggiungi Rapido")
        self.row_quick_add_btn.setToolTip("Aggiungi velocemente una riga con campo esito preconfigurato")
        self.row_quick_add_btn.setObjectName("autoButton")
        self.row_edit_btn = QPushButton(qta.icon('fa5s.edit'), " Modifica")
        self.row_edit_btn.setObjectName("editButton")
        self.row_dup_btn = QPushButton(qta.icon('fa5s.copy'), " Duplica")
        self.row_dup_btn.setToolTip("Duplica la riga selezionata")
        self.row_remove_btn = QPushButton(qta.icon('fa5s.trash'), " Rimuovi")
        self.row_remove_btn.setObjectName("deleteButton")
        self.row_up_btn = QPushButton(qta.icon('fa5s.arrow-up'), "")
        self.row_up_btn.setToolTip("Sposta su")
        self.row_down_btn = QPushButton(qta.icon('fa5s.arrow-down'), "")
        self.row_down_btn.setToolTip("Sposta giù")
        rows_btn_layout.addWidget(self.row_add_btn)
        rows_btn_layout.addWidget(self.row_quick_add_btn)
        rows_btn_layout.addWidget(self.row_edit_btn)
        rows_btn_layout.addWidget(self.row_dup_btn)
        rows_btn_layout.addWidget(self.row_remove_btn)
        rows_btn_layout.addWidget(self.row_up_btn)
        rows_btn_layout.addWidget(self.row_down_btn)
        rows_btn_layout.addStretch()
        rows_layout.addLayout(rows_btn_layout)
        self.stack.addWidget(rows_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self.field_add_btn.clicked.connect(self.add_field)
        self.field_edit_btn.clicked.connect(self.edit_field)
        self.field_dup_btn.clicked.connect(self.duplicate_field)
        self.field_remove_btn.clicked.connect(self.remove_field)
        self.field_up_btn.clicked.connect(self.move_field_up)
        self.field_down_btn.clicked.connect(self.move_field_down)
        self.row_add_btn.clicked.connect(self.add_row)
        self.row_quick_add_btn.clicked.connect(lambda: self.row_quick_edit.setFocus())
        self.row_edit_btn.clicked.connect(self.edit_row)
        # Rinomina inline delle verifiche e dei campi (doppio clic sull'elemento)
        self.rows_list.itemChanged.connect(self._on_row_label_edited)
        self.fields_table.itemChanged.connect(self._on_field_cell_changed)
        self.row_dup_btn.clicked.connect(self.duplicate_row)
        self.row_remove_btn.clicked.connect(self.remove_row)
        self.row_up_btn.clicked.connect(self.move_row_up)
        self.row_down_btn.clicked.connect(self.move_row_down)
        # Auto-genera chiave dal titolo
        self.title_edit.textChanged.connect(self._on_title_changed)
        self.key_edit.textEdited.connect(self._on_key_edited)
        # Usa l'indice per gestire correttamente i valori interni ("fields", "checklist", "table")
        self.type_combo.currentIndexChanged.connect(self._update_stack)

        self._update_stack(self.type_combo.currentIndex())
        self._refresh_fields()
        self._refresh_rows()

    def _update_stack(self, index: int):
        """
        Mostra il pannello corretto in base al tipo di sezione selezionato.
        Usa i dati interni del combo ("fields", "checklist", "table"), non il testo visualizzato.
        """
        if index < 0 or index >= self.type_combo.count():
            return
        section_type = self.type_combo.itemData(index)
        if section_type == "fields":
            self.stack.setCurrentIndex(0)
        else:
            self.stack.setCurrentIndex(1)

    def _slugify_key(self, text: str) -> str:
        if not text:
            return ""
        value = text.strip().lower()
        if not value:
            return ""
        value = unicodedata.normalize("NFKD", value)
        value = "".join(c for c in value if not unicodedata.combining(c))
        value = re.sub(r"[^a-z0-9]+", "_", value)
        value = value.strip("_")
        return value

    def _on_title_changed(self, text: str):
        """Auto-genera chiave dal titolo se non modificata manualmente."""
        if self._key_user_edited:
            return
        self.key_edit.setText(self._slugify_key(text))

    def _on_key_edited(self, _text: str):
        self._key_user_edited = True

    def _refresh_fields(self):
        self.fields_table.blockSignals(True)
        self.fields_table.setRowCount(0)
        for field in self.section.fields:
            row_idx = self.fields_table.rowCount()
            self.fields_table.insertRow(row_idx)
            type_label = FIELD_TYPE_INFO.get(field.field_type, {}).get("label", field.field_type)
            cells = [
                (field.key, False),
                (field.label, True),   # solo l'etichetta è modificabile inline
                (type_label, False),
                ("Sì" if field.required else "No", False),
                ("Sì" if field.read_only else "No", False),
                (field.formula or "", False),
            ]
            for col, (text, editable) in enumerate(cells):
                item = QTableWidgetItem(text)
                if editable:
                    item.setToolTip("Doppio clic per rinominare")
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.fields_table.setItem(row_idx, col, item)
        self.fields_table.blockSignals(False)

    def _on_field_cell_changed(self, item):
        """Rinomina inline dell'etichetta di un campo (colonna 1)."""
        if item.column() != 1:
            return
        idx = item.row()
        if 0 <= idx < len(self.section.fields):
            new_label = item.text().strip()
            if new_label:
                self.section.fields[idx].label = new_label
            else:
                self.fields_table.blockSignals(True)
                item.setText(self.section.fields[idx].label)
                self.fields_table.blockSignals(False)

    def _inline_add_field(self):
        """Aggiunge un campo testo dalla riga di inserimento rapido."""
        label = self.field_quick_edit.text().strip()
        if not label:
            return
        key = self._slugify_key(label) or f"campo_{len(self.section.fields) + 1}"
        if any(f.key == key for f in self.section.fields):
            suffix = 2
            while any(f.key == f"{key}_{suffix}" for f in self.section.fields):
                suffix += 1
            key = f"{key}_{suffix}"
        self.section.fields.append(FunctionalField(key=key, label=label, field_type="text"))
        self.field_quick_edit.clear()
        self._refresh_fields()
        self.field_quick_edit.setFocus()

    def _refresh_rows(self):
        self.rows_list.blockSignals(True)
        self.rows_list.clear()
        for row in self.section.rows:
            label = row.label or row.key
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setData(Qt.UserRole, row)
            extra = ", ".join(f.label for f in row.fields if f.key != "esito")
            tip = f"Chiave: {row.key} · {len(row.fields)} campo/i"
            if extra:
                tip += f" · {extra}"
            item.setToolTip(tip)
            self.rows_list.addItem(item)
        self.rows_list.blockSignals(False)

    def _on_row_label_edited(self, item):
        """Rinomina inline di una verifica (doppio clic sull'elemento)."""
        row = item.data(Qt.UserRole)
        if row is None:
            return
        new_label = item.text().strip()
        if new_label:
            row.label = new_label
        else:
            self.rows_list.blockSignals(True)
            item.setText(row.label or row.key)
            self.rows_list.blockSignals(False)

    def _reorder_rows(self, src, dst):
        """Riordino delle verifiche per trascinamento."""
        move_in_list(self.section.rows, src, dst)
        self._refresh_rows()

    def _inline_add_row(self):
        """Aggiunge una verifica con esito OK/KO/N.A. dalla riga rapida."""
        label = self.row_quick_edit.text().strip()
        if not label:
            return
        key = self._slugify_key(label) or f"riga_{len(self.section.rows) + 1}"
        if any(r.key == key for r in self.section.rows):
            suffix = 2
            while any(r.key == f"{key}_{suffix}" for r in self.section.rows):
                suffix += 1
            key = f"{key}_{suffix}"
        self.section.rows.append(FunctionalRowDefinition(
            key=key, label=label,
            fields=[FunctionalField(key="esito", label="Esito", field_type="choice",
                                    required=True, options=["OK", "KO", "N.A."])]))
        self.row_quick_edit.clear()
        self._refresh_rows()
        self.row_quick_edit.setFocus()

    def add_field(self):
        dialog = FieldEditorDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            new_field = dialog.field
            if any(f.key == new_field.key for f in self.section.fields):
                QMessageBox.warning(self, "Chiave duplicata", f"Esiste già un campo con chiave '{new_field.key}'.")
                return
            self.section.fields.append(new_field)
            self._refresh_fields()

    def edit_field(self):
        row_idx = self.fields_table.currentRow()
        if row_idx < 0:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona un campo da modificare.")
            return
        dialog = FieldEditorDialog(field=self.section.fields[row_idx], parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.section.fields[row_idx] = dialog.field
            self._refresh_fields()

    def remove_field(self):
        row_idx = self.fields_table.currentRow()
        if row_idx < 0:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona un campo da rimuovere.")
            return
        self.section.fields.pop(row_idx)
        self._refresh_fields()

    def duplicate_field(self):
        """Duplica il campo selezionato con una nuova chiave."""
        row_idx = self.fields_table.currentRow()
        if row_idx < 0:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona un campo da duplicare.")
            return
        original = self.section.fields[row_idx]
        new_field = copy.deepcopy(original)
        # Genera chiave unica
        base_key = original.key
        suffix = 2
        while any(f.key == f"{base_key}_{suffix}" for f in self.section.fields):
            suffix += 1
        new_field.key = f"{base_key}_{suffix}"
        new_field.label = f"{original.label} (copia)"
        self.section.fields.insert(row_idx + 1, new_field)
        self._refresh_fields()
        self.fields_table.selectRow(row_idx + 1)

    def move_field_up(self):
        row_idx = self.fields_table.currentRow()
        if row_idx <= 0:
            return
        self.section.fields[row_idx - 1], self.section.fields[row_idx] = (
            self.section.fields[row_idx],
            self.section.fields[row_idx - 1],
        )
        self._refresh_fields()
        self.fields_table.selectRow(row_idx - 1)

    def move_field_down(self):
        row_idx = self.fields_table.currentRow()
        if row_idx < 0 or row_idx >= len(self.section.fields) - 1:
            return
        self.section.fields[row_idx + 1], self.section.fields[row_idx] = (
            self.section.fields[row_idx],
            self.section.fields[row_idx + 1],
        )
        self._refresh_fields()
        self.fields_table.selectRow(row_idx + 1)

    def add_row(self):
        dialog = RowEditorDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            new_row = dialog.row
            if any(r.key == new_row.key for r in self.section.rows):
                QMessageBox.warning(self, "Chiave duplicata", f"Esiste già una riga con chiave '{new_row.key}'.")
                return
            self.section.rows.append(new_row)
            self._refresh_rows()

    def duplicate_row(self):
        """Duplica la riga selezionata con una nuova chiave."""
        item = self.rows_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona una riga da duplicare.")
            return
        idx = self.rows_list.row(item)
        original = self.section.rows[idx]
        new_row = copy.deepcopy(original)
        # Genera chiave unica
        base_key = original.key
        suffix = 2
        while any(r.key == f"{base_key}_{suffix}" for r in self.section.rows):
            suffix += 1
        new_row.key = f"{base_key}_{suffix}"
        new_row.label = f"{original.label or original.key} (copia)"
        self.section.rows.insert(idx + 1, new_row)
        self._refresh_rows()
        self.rows_list.setCurrentRow(idx + 1)

    def edit_row(self):
        item = self.rows_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona una riga da modificare.")
            return
        selected_row = item.data(Qt.UserRole)
        dialog = RowEditorDialog(row=selected_row, parent=self)
        if dialog.exec() == QDialog.Accepted:
            row = dialog.row
            idx = self.rows_list.row(item)
            self.section.rows[idx] = row
            self._refresh_rows()

    def remove_row(self):
        row = self.rows_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona una riga da rimuovere.")
            return
        self.section.rows.pop(row)
        self._refresh_rows()

    def move_row_up(self):
        row = self.rows_list.currentRow()
        if row <= 0:
            return
        self.section.rows[row - 1], self.section.rows[row] = (
            self.section.rows[row],
            self.section.rows[row - 1],
        )
        self._refresh_rows()
        self.rows_list.setCurrentRow(row - 1)

    def move_row_down(self):
        row = self.rows_list.currentRow()
        if row < 0 or row >= len(self.section.rows) - 1:
            return
        self.section.rows[row + 1], self.section.rows[row] = (
            self.section.rows[row],
            self.section.rows[row + 1],
        )
        self._refresh_rows()
        self.rows_list.setCurrentRow(row + 1)

    def accept(self):
        key = self.key_edit.text().strip()
        title = self.title_edit.text().strip()
        # Salviamo il valore "logico" della sezione: fields / checklist / table
        section_type = self.type_combo.currentData()

        if not key:
            QMessageBox.warning(self, "Chiave mancante", "La chiave della sezione è obbligatoria.")
            return
        if not title:
            QMessageBox.warning(self, "Titolo mancante", "Il titolo della sezione è obbligatorio.")
            return

        if section_type == "fields":
            if not self.section.fields:
                QMessageBox.warning(self, "Campi mancanti", "Aggiungere almeno un campo alla sezione.")
                return
            self.section.rows = []
        else:
            if not self.section.rows:
                QMessageBox.warning(self, "Righe mancanti", "Aggiungere almeno una riga alla sezione.")
                return
            self.section.fields = []

        self.section.key = key
        self.section.title = title
        self.section.section_type = section_type
        self.section.description = self.description_edit.text().strip() or ""
        self.section.show_in_summary = self.show_in_summary_checkbox.isChecked()
        super().accept()


class FunctionalProfileEditorDialog(QDialog):
    def __init__(self, profile: Optional[FunctionalProfile] = None, is_new: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editor Profilo Funzionale")
        self.setMinimumSize(1000, 700)
        self.resize(1180, 780)
        # Applica il tema corrente
        self.setStyleSheet(config.get_current_stylesheet())
        self.is_new = is_new
        self.profile = copy.deepcopy(profile) if profile else FunctionalProfile(
            profile_key="",
            name="",
            device_type="",
            sections=[],
        )

        main_layout = QVBoxLayout(self)

        # Barra in alto sempre visibile: nome e tipo apparecchio, i dati che
        # servono subito (prima erano in un wizard separato / nascosti in scheda)
        header_box = QGroupBox(f"{'Nuovo' if is_new else 'Modifica'} Profilo Funzionale")
        header_layout = QHBoxLayout(header_box)
        header_layout.addWidget(QLabel("Nome *:"))
        self.name_edit = QLineEdit(self.profile.name)
        self.name_edit.setPlaceholderText("es. Monitor multiparametrico")
        self.name_edit.textChanged.connect(self._update_preview)
        header_layout.addWidget(self.name_edit, 3)
        header_layout.addWidget(QLabel("Tipo apparecchio:"))
        self.device_type_edit = QLineEdit(self.profile.device_type or "")
        self.device_type_edit.setPlaceholderText("es. MONITOR")
        self.device_type_edit.textChanged.connect(self._update_preview)
        header_layout.addWidget(self.device_type_edit, 2)
        main_layout.addWidget(header_box)

        # Layout orizzontale: form a sinistra, anteprima a destra
        content_layout = QHBoxLayout()

        # Colonna sinistra a SCHEDE: separa il lavoro sul contenuto dalle
        # informazioni/strumenti, così ogni parte ha tutto lo spazio in altezza
        # (prima erano impilati e l'area di editing restava schiacciata in fondo)
        self.editor_tabs = QTabWidget()

        # Scheda "Informazioni e strumenti"
        info_tab = QWidget()
        left_layout = QVBoxLayout(info_tab)

        form_widget = QGroupBox("Informazioni Base")
        form = QFormLayout(form_widget)

        self.key_edit = QLineEdit(self.profile.profile_key)
        self.key_edit.setPlaceholderText("Generata automaticamente dal nome")
        if not self.is_new:
            self.key_edit.setDisabled(True)
        form.addRow("Chiave Profilo:", self.key_edit)

        # Regole strumenti per il profilo
        self.min_instruments_spin = QSpinBox()
        self.min_instruments_spin.setRange(0, 20)
        self.min_instruments_spin.setValue(int(getattr(self.profile, "required_min_instruments", 0) or 0))
        self.min_instruments_spin.setToolTip("Numero minimo di strumenti da selezionare all'avvio verifica")
        form.addRow("Minimo strumenti richiesti:", self.min_instruments_spin)

        allowed_types = set(getattr(self.profile, "allowed_instrument_types", []) or [])
        type_row = QWidget()
        type_row_layout = QHBoxLayout(type_row)
        type_row_layout.setContentsMargins(0, 0, 0, 0)
        self.allowed_type_functional = QCheckBox("Funzionali")
        self.allowed_type_electrical = QCheckBox("Elettrici")
        self.allowed_type_functional.setChecked((not allowed_types) or ("functional" in allowed_types))
        self.allowed_type_electrical.setChecked("electrical" in allowed_types)
        type_row_layout.addWidget(self.allowed_type_functional)
        type_row_layout.addWidget(self.allowed_type_electrical)
        type_row_layout.addStretch()
        form.addRow("Tipi strumenti consentiti:", type_row)
        left_layout.addWidget(form_widget)

        # Selezione multipla strumenti
        instruments_group = QGroupBox("Strumenti Disponibili")
        instruments_layout = QVBoxLayout(instruments_group)

        filters_row = QHBoxLayout()
        self.instruments_search_edit = QLineEdit()
        self.instruments_search_edit.setPlaceholderText("Cerca per nome o matricola...")
        self.instruments_sort_combo = QComboBox()
        self.instruments_sort_combo.addItem("Ordina: Nome", "name")
        self.instruments_sort_combo.addItem("Ordina: Matricola", "serial")
        self.instruments_sort_combo.addItem("Ordina: Scadenza calibrazione", "calibration")
        filters_row.addWidget(self.instruments_search_edit, 1)
        filters_row.addWidget(self.instruments_sort_combo)
        instruments_layout.addLayout(filters_row)

        self.instruments_list = QListWidget()
        self.instruments_list.setSelectionMode(QAbstractItemView.MultiSelection)
        # Carica solo strumenti funzionali
        functional_instruments = services.database.get_all_instruments('functional')
        self.all_instruments = {}  # Dizionario per mappare ID -> dati strumento
        # Normalizza gli ID già associati al profilo (int + fallback stringa)
        selected_ids_raw = self.profile.instrument_ids or []
        selected_ids_int: set[int] = set()
        selected_ids_str: set[str] = set()
        for raw_id in selected_ids_raw:
            if raw_id is None:
                continue
            selected_ids_str.add(str(raw_id))
            try:
                selected_ids_int.add(int(raw_id))
            except (TypeError, ValueError):
                pass

        for inst_row in (functional_instruments or []):
            instrument = dict(inst_row)
            inst_id = instrument.get('id')
            self.all_instruments[inst_id] = instrument
        if not self.all_instruments:
            # Fallback: se non esiste distinzione per tipo, usa tutti gli strumenti
            for inst_row in (services.database.get_all_instruments() or []):
                instrument = dict(inst_row)
                inst_id = instrument.get('id')
                self.all_instruments[inst_id] = instrument

        # Include eventuali strumenti in snapshot non più presenti
        for snap in (getattr(self.profile, "instrument_snapshots", []) or []):
            if not isinstance(snap, dict):
                continue
            snap_id = snap.get("id")
            if snap_id is None:
                continue
            try:
                snap_id_int = int(snap_id)
            except (TypeError, ValueError):
                continue
            if snap_id_int not in self.all_instruments:
                self.all_instruments[snap_id_int] = {
                    "id": snap_id_int,
                    "instrument_name": snap.get("instrument", "Strumento non trovato"),
                    "serial_number": snap.get("serial", "N/D"),
                    "calibration_date": snap.get("cal_date"),
                    "instrument_type": snap.get("instrument_type", "unknown"),
                    "_missing": True,
                }

        self._selected_instrument_ids = set(selected_ids_int)
        self._refresh_instruments_list()
        self.instruments_search_edit.textChanged.connect(self._refresh_instruments_list)
        self.instruments_sort_combo.currentIndexChanged.connect(self._refresh_instruments_list)
        self.instruments_list.itemSelectionChanged.connect(self._capture_instrument_selection)
        instruments_layout.addWidget(self.instruments_list)
        left_layout.addWidget(instruments_group, 1)

        # Sezioni
        sections_group = QGroupBox("Sezioni del Profilo")
        sections_layout = QVBoxLayout(sections_group)

        # Palette di blocchi + canvas con drag & drop: si trascina un blocco
        # dalla palette nell'elenco per aggiungerlo, e si riordinano le sezioni
        # trascinandole
        dnd_row = QHBoxLayout()
        palette_col = QVBoxLayout()
        palette_col.setSpacing(2)
        palette_col.addWidget(QLabel("<small><b>Trascina nel profilo →</b></small>"))
        self.section_palette = SectionPalette()
        self.section_palette.setFixedWidth(215)
        self.section_palette.setMaximumHeight(160)
        palette_col.addWidget(self.section_palette)
        palette_col.addStretch()
        dnd_row.addLayout(palette_col)

        canvas_col = QVBoxLayout()
        canvas_col.setSpacing(2)
        canvas_col.addWidget(QLabel("<small>Sezioni del profilo "
                                    "<span style='color:#64748b;'>(trascina per riordinare)</span></small>"))
        self.sections_list = DragDropList(accept_presets=True)
        self.sections_list.setAlternatingRowColors(True)
        self.sections_list.preset_dropped.connect(self._drop_section_preset)
        self.sections_list.reorder_requested.connect(self._reorder_sections)
        canvas_col.addWidget(self.sections_list)
        dnd_row.addLayout(canvas_col, 1)
        sections_layout.addLayout(dnd_row)

        btn_row = QHBoxLayout()
        self.section_add_btn = QPushButton(qta.icon('fa5s.plus'), " Aggiungi")
        self.section_add_btn.setObjectName("autoButton")
        self.section_quick_btn = QPushButton(qta.icon('fa5s.bolt'), " Aggiungi Preset")
        self.section_quick_btn.setToolTip("Aggiungi una sezione da modello predefinito")
        self.section_quick_btn.setObjectName("autoButton")
        self.section_edit_btn = QPushButton(qta.icon('fa5s.edit'), " Modifica")
        self.section_edit_btn.setObjectName("editButton")
        self.section_dup_btn = QPushButton(qta.icon('fa5s.copy'), " Duplica")
        self.section_dup_btn.setToolTip("Duplica la sezione selezionata")
        self.section_remove_btn = QPushButton(qta.icon('fa5s.trash'), " Rimuovi")
        self.section_remove_btn.setObjectName("deleteButton")
        self.section_up_btn = QPushButton(qta.icon('fa5s.arrow-up'), "")
        self.section_up_btn.setToolTip("Sposta su")
        self.section_down_btn = QPushButton(qta.icon('fa5s.arrow-down'), "")
        self.section_down_btn.setToolTip("Sposta giù")
        
        for btn in (self.section_add_btn, self.section_quick_btn, self.section_edit_btn,
                     self.section_dup_btn, self.section_remove_btn,
                     self.section_up_btn, self.section_down_btn):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        sections_layout.addLayout(btn_row)
        # Scheda "Contenuto del profilo": selettore modalità + sezioni,
        # a tutta altezza — è qui che si lavora di più
        content_tab = QWidget()
        content_tab_layout = QVBoxLayout(content_tab)

        mode_row = QHBoxLayout()
        self.sections_mode_label = QLabel("")
        self.sections_mode_label.setStyleSheet("font-weight: bold;")
        self.sections_mode_btn = QPushButton("")
        self.sections_mode_btn.clicked.connect(self._toggle_sections_mode)
        mode_row.addWidget(self.sections_mode_label)
        mode_row.addStretch()
        mode_row.addWidget(self.sections_mode_btn)
        content_tab_layout.addLayout(mode_row)

        self.sections_stack = QStackedWidget()
        self.sections_stack.addWidget(self._build_simple_sections_page())  # 0 = guidata
        self.sections_stack.addWidget(sections_group)                      # 1 = completo
        content_tab_layout.addWidget(self.sections_stack, 1)

        # Contenuto come prima scheda (attiva di default), info come seconda
        self.editor_tabs.addTab(content_tab, qta.icon('fa5s.list-ul'), "  Contenuto del profilo")
        self.editor_tabs.addTab(info_tab, qta.icon('fa5s.info-circle'), "  Informazioni e strumenti")
        content_layout.addWidget(self.editor_tabs, 2)

        # Colonna destra: Anteprima (sempre visibile, accanto alle schede)
        preview_group = QGroupBox("Anteprima Profilo")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumWidth(300)
        preview_layout.addWidget(self.preview_text)
        content_layout.addWidget(preview_group, 1)

        main_layout.addLayout(content_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self.section_add_btn.clicked.connect(self.add_section)
        self.section_quick_btn.clicked.connect(self.quick_add_section)
        self.section_edit_btn.clicked.connect(self.edit_section)
        self.section_dup_btn.clicked.connect(self.duplicate_section)
        self.section_remove_btn.clicked.connect(self.remove_section)
        self.section_up_btn.clicked.connect(self.move_section_up)
        self.section_down_btn.clicked.connect(self.move_section_down)
        self.sections_list.itemDoubleClicked.connect(lambda _: self.edit_section())
        self.sections_list.currentRowChanged.connect(self._update_preview)

        # Nuovo profilo: parte già con una struttura tipica pronta da editare
        # (riferimenti normativi + checklist visiva standard + note), così
        # l'editor strutturato non si apre vuoto
        if self.is_new and not self.profile.sections:
            self.profile.sections = build_sections(
                SimpleFunctionalOptions(blocks=default_new_profile_blocks()))
        self._refresh_sections()

        # Prepara anche la vista "documento" come modalità alternativa (pulsante)
        parsed = parse_profile_sections(self.profile)
        view = outline_view_from_options(parsed) if parsed is not None else None
        if view is not None:
            self._load_outline_view(view)

        # Default: editor strutturato avanzato (quello che l'utente preferisce)
        self._set_sections_mode(simple=False)
        self._update_preview()

    # ─── Modalità documento: profilo scritto come testo ──────────────────

    def _build_simple_sections_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)

        # Riferimenti normativi: riga singola opzionale
        norm_row = QHBoxLayout()
        self.doc_normative_chk = QCheckBox("Riferimenti normativi:")
        self.doc_normative_chk.setChecked(True)
        self.doc_normative_edit = QLineEdit()
        self.doc_normative_edit.setPlaceholderText("es. CEI 62353 / AMS-MOD-…")
        norm_row.addWidget(self.doc_normative_chk)
        norm_row.addWidget(self.doc_normative_edit, 1)
        v.addLayout(norm_row)

        v.addWidget(QLabel("Verifiche del profilo:"))
        self.doc_text = QPlainTextEdit()
        self.doc_text.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 13px;")
        self.doc_text.setPlaceholderText(
            "# Controllo Visivo/Funzionale\n"
            "Integrità involucro\n"
            "Leggibilità etichette\n"
            "Lettura SpO2 [%]\n"
            "\n"
            "# Controllo Funzionale\n"
            "Allarmi acustici e visivi"
        )
        v.addWidget(self.doc_text, 1)

        self.doc_notes_chk = QCheckBox("Aggiungi spazio note a fine verifica")
        self.doc_notes_chk.setChecked(True)
        v.addWidget(self.doc_notes_chk)

        hint = QLabel("💡  «#» apre una sezione · una verifica per riga (esito OK/KO/N.A. "
                      "automatico) · «[unità]» per registrare anche un valore, es: Lettura SpO2 [%]")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 11px;")
        v.addWidget(hint)

        self.doc_normative_chk.toggled.connect(self.doc_normative_edit.setEnabled)
        self.doc_normative_chk.toggled.connect(self._on_simple_changed)
        self.doc_normative_edit.textChanged.connect(self._on_simple_changed)
        self.doc_text.textChanged.connect(self._on_simple_changed)
        self.doc_notes_chk.toggled.connect(self._on_simple_changed)

        # OutlineView caricata: conserva sorgenti e chiavi da preservare
        self._doc_view = None
        return page

    def _collect_simple_options(self) -> SimpleFunctionalOptions:
        meta = getattr(self, "_doc_view", None)
        normative = self.doc_normative_edit.text() if self.doc_normative_chk.isChecked() else None
        view = OutlineView(
            normative=normative,
            outline=self.doc_text.toPlainText(),
            has_notes=self.doc_notes_chk.isChecked(),
            sources=meta.sources if meta else [],
            normative_key=meta.normative_key if meta else None,
            normative_field_key=meta.normative_field_key if meta else None,
            notes_key=meta.notes_key if meta else None,
            notes_field_key=meta.notes_field_key if meta else None,
        )
        return options_from_outline_view(view)

    def _load_outline_view(self, view: OutlineView):
        self._doc_view = view
        widgets = (self.doc_normative_chk, self.doc_normative_edit,
                   self.doc_text, self.doc_notes_chk)
        for w in widgets:
            w.blockSignals(True)
        self.doc_normative_chk.setChecked(view.normative is not None)
        self.doc_normative_edit.setText(view.normative or "")
        self.doc_normative_edit.setEnabled(view.normative is not None)
        self.doc_text.setPlainText(view.outline)
        self.doc_notes_chk.setChecked(view.has_notes)
        for w in widgets:
            w.blockSignals(False)
        self._on_simple_changed()

    def _on_simple_changed(self, *args):
        if hasattr(self, "preview_text"):
            self._update_preview()

    def _current_sections(self):
        """Sezioni correnti: costruite dalla guidata oppure quelle del profilo."""
        if getattr(self, "_sections_simple_mode", False):
            try:
                return build_sections(self._collect_simple_options())
            except Exception:
                return self.profile.sections
        return self.profile.sections

    def _set_sections_mode(self, simple: bool):
        self._sections_simple_mode = simple
        self.sections_stack.setCurrentIndex(0 if simple else 1)
        if simple:
            self.sections_mode_label.setText("✦ MODALITÀ DOCUMENTO — scrivi il profilo come testo")
            self.sections_mode_btn.setText("EDITOR AVANZATO…")
        else:
            self.sections_mode_label.setText("🛠 EDITOR AVANZATO — sezioni, tabelle e formule")
            self.sections_mode_btn.setText("TORNA AL DOCUMENTO…")
        if hasattr(self, "preview_text"):
            self._update_preview()

    def _toggle_sections_mode(self):
        if self._sections_simple_mode:
            # Guidata → completo: travasa le sezioni costruite
            self.profile.sections = build_sections(self._collect_simple_options())
            self._refresh_sections()
            self._set_sections_mode(simple=False)
        else:
            temp = FunctionalProfile(profile_key="x", name="x",
                                     sections=self.profile.sections)
            parsed = parse_profile_sections(temp)
            view = outline_view_from_options(parsed) if parsed is not None else None
            if view is None:
                QMessageBox.information(
                    self, "Modalità documento non disponibile",
                    "Il profilo contiene tabelle, formule o moduli di campi\n"
                    "che la modalità documento non può rappresentare.\n\n"
                    "Continua nell'editor avanzato.",
                )
                return
            self._load_outline_view(view)
            self._set_sections_mode(simple=True)

    def _refresh_sections(self):
        """Aggiorna la lista delle sezioni con icone e colori."""
        self.sections_list.clear()
        for idx, section in enumerate(self.profile.sections):
            section_type_icon = {
                "fields": qta.icon('fa5s.list', color='#2563eb'),
                "checklist": qta.icon('fa5s.check-square', color='#16a34a'),
                "table": qta.icon('fa5s.table', color='#f59e0b'),
            }
            icon = section_type_icon.get(section.section_type, qta.icon('fa5s.cog', color='#64748b'))
            
            # Conta elementi
            if section.section_type == "fields":
                count = len(section.fields)
                count_text = f"{count} campo{'i' if count != 1 else ''}"
            else:
                count = len(section.rows)
                count_text = f"{count} riga{'he' if count != 1 else ''}"
            
            item = QListWidgetItem(icon, f"{idx + 1}. {section.title}")
            item.setToolTip(f"Tipo: {section.section_type}\n{count_text}\nChiave: {section.key}")
            item.setData(Qt.UserRole, section)
            self.sections_list.addItem(item)
        self._update_preview()
    
    def _field_control_preview(self, field) -> str:
        """Descrizione HTML del controllo come apparirà al tecnico in verifica."""
        import html as _html
        ft = field.field_type
        if ft == "header":
            return ""  # intestazione: già resa come titolo
        if ft in ("choice", "pass_fail"):
            opts = field.options or (["PASS", "FAIL", "N.A."] if ft == "pass_fail" else [])
            if opts:
                chips = " ".join(
                    f"<span style='background:#eef2ff;color:#4338ca;border-radius:8px;"
                    f"padding:1px 6px;'>{_html.escape(str(o))}</span>" for o in opts
                )
                return chips
            return "<span style='color:#94a3b8;'>(nessuna opzione)</span>"
        if ft == "bool":
            return "<span style='color:#94a3b8;'>☐ Sì / No</span>"
        if ft == "rating":
            n = field.rating_max or 5
            return f"<span style='color:#eab308;'>{'★' * min(n, 10)}</span> <span style='color:#94a3b8;'>(1–{n})</span>"
        if ft == "calculated":
            return (f"<span style='color:#0d9488;'>∑ calcolato: "
                    f"<code>{_html.escape(field.formula or '')}</code></span>")
        # input testuale/numerico/data/ora: mostra una casella con eventuale unità/default
        placeholder = ""
        if field.default not in (None, ""):
            placeholder = _html.escape(str(field.default))
        box = (f"<span style='border:1px solid #cbd5e1;border-radius:4px;"
               f"padding:1px 18px 1px 6px;color:#64748b;'>{placeholder or '&nbsp;'}</span>")
        if field.unit:
            box += f" <span style='color:#64748b;'>{_html.escape(field.unit)}</span>"
        return box

    def _update_preview(self):
        """Anteprima fedele: mostra il profilo come apparirà in verifica."""
        import html as _html
        name = self.name_edit.text().strip() or "Nome Profilo"
        device_type = self.device_type_edit.text().strip()
        sections = self._current_sections()

        html_parts = [f"<h3 style='margin-bottom:2px;'>{_html.escape(name)}</h3>"]
        if device_type:
            html_parts.append(f"<p style='color:#64748b;margin-top:0;'>{_html.escape(device_type)}</p>")
        if not sections:
            html_parts.append("<p style='color:#94a3b8;'><i>Nessuna sezione: aggiungi una "
                              "checklist o un modulo campi.</i></p>")

        for idx, section in enumerate(sections):
            html_parts.append(
                f"<div style='margin-top:10px;'><span style='font-weight:700;color:#1e293b;'>"
                f"{idx + 1}. {_html.escape(section.title)}</span></div>")
            if section.description:
                html_parts.append(
                    f"<div style='color:#64748b;font-size:11px;'>{_html.escape(section.description)}</div>")

            if section.section_type in ("fields", "form"):
                html_parts.append("<table cellpadding='3' style='margin-left:6px;'>")
                for field in section.fields:
                    if field.field_type == "header":
                        html_parts.append(
                            f"<tr><td colspan='2' style='font-weight:600;color:#475569;'>"
                            f"— {_html.escape(field.label)} —</td></tr>")
                        continue
                    req = " <span style='color:#dc2626;'>*</span>" if field.required else ""
                    html_parts.append(
                        f"<tr><td style='color:#334155;vertical-align:top;'>{_html.escape(field.label)}{req}</td>"
                        f"<td>{self._field_control_preview(field)}</td></tr>")
                html_parts.append("</table>")
            else:
                # checklist / table: una riga per voce
                html_parts.append("<table cellpadding='3' style='margin-left:6px;'>")
                for row in section.rows[:8]:
                    controls = " &nbsp; ".join(
                        self._field_control_preview(f) for f in row.fields
                        if self._field_control_preview(f)
                    )
                    html_parts.append(
                        f"<tr><td style='color:#334155;vertical-align:top;'>"
                        f"{_html.escape(row.label or row.key)}</td><td>{controls}</td></tr>")
                if len(section.rows) > 8:
                    html_parts.append(
                        f"<tr><td colspan='2' style='color:#94a3b8;'>… e altre "
                        f"{len(section.rows) - 8} voci</td></tr>")
                html_parts.append("</table>")

        self.preview_text.setHtml("".join(html_parts))

    def _capture_instrument_selection(self):
        self._selected_instrument_ids = {
            item.data(Qt.UserRole)
            for item in self.instruments_list.selectedItems()
            if item.data(Qt.UserRole) is not None
        }

    def _parse_calibration_date(self, value: str | None):
        if not value:
            return None
        value = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                from datetime import datetime
                return datetime.strptime(value, fmt).date()
            except Exception:
                continue
        return None

    def _build_instrument_item_text(self, instrument: dict) -> str:
        name = instrument.get('instrument_name', 'N/A')
        serial = instrument.get('serial_number', 'N/A')
        cal_date_raw = instrument.get('calibration_date')
        cal_date = self._parse_calibration_date(cal_date_raw)
        cal_txt = str(cal_date_raw or 'N/D')
        type_txt = str(instrument.get('instrument_type') or 'N/D').upper()

        status_txt = ""
        if cal_date:
            from datetime import date
            try:
                expiry_date = cal_date.replace(year=cal_date.year + 1)
            except ValueError:
                expiry_date = cal_date.replace(month=2, day=28, year=cal_date.year + 1)
            if expiry_date < date.today():
                status_txt = " [CALIBRAZIONE SCADUTA]"

        missing_txt = " [MANCANTE]" if instrument.get("_missing") else ""
        return f"{name} (S/N: {serial}) - Tipo: {type_txt} - Cal: {cal_txt}{status_txt}{missing_txt}"

    def _refresh_instruments_list(self):
        search = self.instruments_search_edit.text().strip().lower() if hasattr(self, "instruments_search_edit") else ""
        sort_mode = self.instruments_sort_combo.currentData() if hasattr(self, "instruments_sort_combo") else "name"

        instruments = list(self.all_instruments.values())

        def sort_key(inst: dict):
            if sort_mode == "serial":
                return str(inst.get("serial_number") or "").lower()
            if sort_mode == "calibration":
                cal_date = self._parse_calibration_date(inst.get("calibration_date"))
                return (cal_date is None, cal_date)
            return str(inst.get("instrument_name") or "").lower()

        instruments.sort(key=sort_key)

        self.instruments_list.clear()
        for instrument in instruments:
            text = self._build_instrument_item_text(instrument)
            if search and search not in text.lower():
                continue

            inst_id = instrument.get("id")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, inst_id)

            if instrument.get("_missing"):
                item.setForeground(Qt.darkRed)

            self.instruments_list.addItem(item)
            if inst_id in self._selected_instrument_ids:
                item.setSelected(True)

    def add_section(self):
        dialog = SectionEditorDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            new_section = dialog.section
            if any(sec.key == new_section.key for sec in self.profile.sections):
                QMessageBox.warning(self, "Chiave duplicata", f"Esiste già una sezione con chiave '{new_section.key}'.")
                return
            self.profile.sections.append(new_section)
            self._refresh_sections()

    def quick_add_section(self):
        """Aggiunge una sezione da un modello predefinito."""
        presets = {
            "Riferimenti Normativi": FunctionalSection(
                key="riferimenti_normativi",
                title="Riferimenti Normativi-Procedure",
                section_type="fields",
                fields=[
                    FunctionalField(key="norme_procedure", label="Norme/Procedure", field_type="text"),
                ],
            ),
            "Controlli Visivi (Checklist)": FunctionalSection(
                key="controlli_visivi",
                title="Controllo Visivo/Funzionale",
                section_type="checklist",
                rows=[
                    FunctionalRowDefinition(key="integrita_generale", label="Integrità generale apparecchiatura", fields=[
                        FunctionalField(key="esito", label="Esito", field_type="pass_fail", required=True, options=["PASS", "FAIL", "N.A."]),
                    ]),
                    FunctionalRowDefinition(key="serigrafie_etichette", label="Leggibilità serigrafie/etichette", fields=[
                        FunctionalField(key="esito", label="Esito", field_type="pass_fail", required=True, options=["PASS", "FAIL", "N.A."]),
                    ]),
                    FunctionalRowDefinition(key="cavo_alimentazione", label="Integrità cavo di alimentazione", fields=[
                        FunctionalField(key="esito", label="Esito", field_type="pass_fail", required=True, options=["PASS", "FAIL", "N.A."]),
                    ]),
                ],
            ),
            "Misurazioni (Tabella)": FunctionalSection(
                key="misurazioni",
                title="Misurazioni",
                section_type="table",
                rows=[
                    FunctionalRowDefinition(key="misura_1", label="Misura 1", fields=[
                        FunctionalField(key="valore_atteso", label="Valore Atteso", field_type="number", unit=""),
                        FunctionalField(key="valore_misurato", label="Valore Misurato", field_type="number", unit=""),
                        FunctionalField(key="tolleranza", label="Tolleranza (%)", field_type="percentage"),
                        FunctionalField(key="esito", label="Esito", field_type="pass_fail", required=True, options=["PASS", "FAIL", "N.A."]),
                    ]),
                ],
            ),
            "Note e Osservazioni": FunctionalSection(
                key="note_osservazioni",
                title="Note e Osservazioni",
                section_type="fields",
                fields=[
                    FunctionalField(key="note", label="Note", field_type="multiline"),
                    FunctionalField(key="data_verifica", label="Data Verifica", field_type="date"),
                ],
            ),
            "Consumabili (Checklist)": FunctionalSection(
                key="consumabili",
                title="Consumabili e Accessori",
                section_type="checklist",
                rows=[
                    FunctionalRowDefinition(key="accessori_presenti", label="Accessori presenti e funzionanti", fields=[
                        FunctionalField(key="esito", label="Esito", field_type="pass_fail", required=True, options=["PASS", "FAIL", "N.A."]),
                    ]),
                ],
            ),
        }

        items = list(presets.keys())
        from PySide6.QtWidgets import QInputDialog
        chosen, ok = QInputDialog.getItem(
            self,
            "Aggiungi Sezione Predefinita",
            "Seleziona un modello di sezione:",
            items,
            0,
            False,
        )
        if not ok or not chosen:
            return

        preset_section = copy.deepcopy(presets[chosen])
        # Assicura chiave unica
        base_key = preset_section.key
        if any(s.key == base_key for s in self.profile.sections):
            suffix = 2
            while any(s.key == f"{base_key}_{suffix}" for s in self.profile.sections):
                suffix += 1
            preset_section.key = f"{base_key}_{suffix}"
            preset_section.title = f"{preset_section.title} ({suffix})"

        self.profile.sections.append(preset_section)
        self._refresh_sections()

    def duplicate_section(self):
        """Duplica la sezione selezionata."""
        item = self.sections_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona una sezione da duplicare.")
            return
        idx = self.sections_list.row(item)
        original = self.profile.sections[idx]
        new_section = copy.deepcopy(original)
        # Genera chiave unica
        base_key = original.key
        suffix = 2
        while any(s.key == f"{base_key}_{suffix}" for s in self.profile.sections):
            suffix += 1
        new_section.key = f"{base_key}_{suffix}"
        new_section.title = f"{original.title} (copia)"
        self.profile.sections.insert(idx + 1, new_section)
        self._refresh_sections()
        self.sections_list.setCurrentRow(idx + 1)

    def edit_section(self):
        item = self.sections_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona una sezione da modificare.")
            return
        section = item.data(Qt.UserRole)
        dialog = SectionEditorDialog(section=section, parent=self)
        if dialog.exec() == QDialog.Accepted:
            idx = self.sections_list.row(item)
            self.profile.sections[idx] = dialog.section
            self._refresh_sections()
            self.sections_list.setCurrentRow(idx)

    def remove_section(self):
        row = self.sections_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona una sezione da rimuovere.")
            return
        self.profile.sections.pop(row)
        self._refresh_sections()

    def _unique_section_key(self, base: str) -> str:
        base = base or "sezione"
        existing = {s.key for s in self.profile.sections}
        if base not in existing:
            return base
        n = 2
        while f"{base}_{n}" in existing:
            n += 1
        return f"{base}_{n}"

    def _drop_section_preset(self, preset: str, row: int):
        """Crea una sezione dal blocco trascinato dalla palette e la inserisce
        nel punto del rilascio."""
        from app.functional_templates import (
            build_normative_section, build_notes_section,
        )
        if preset == "normative":
            section = build_normative_section()
        elif preset == "notes":
            section = build_notes_section()
        elif preset == "checklist":
            section = FunctionalSection(key="", title="Nuova checklist",
                                        section_type="checklist", rows=[])
        else:  # fields
            section = FunctionalSection(key="", title="Nuova sezione",
                                        section_type="fields", fields=[])
        section.key = self._unique_section_key(
            section.key or sanitize_profile_key(section.title) or "sezione")
        row = max(0, min(row, len(self.profile.sections)))
        self.profile.sections.insert(row, section)
        self._refresh_sections()
        self.sections_list.setCurrentRow(row)
        self._update_preview()

    def _reorder_sections(self, src: int, dst: int):
        """Riordino delle sezioni per trascinamento."""
        move_in_list(self.profile.sections, src, dst)
        self._refresh_sections()
        self._update_preview()

    def move_section_up(self):
        row = self.sections_list.currentRow()
        if row > 0:
            self.profile.sections[row - 1], self.profile.sections[row] = (
                self.profile.sections[row],
                self.profile.sections[row - 1],
            )
            self._refresh_sections()
            self.sections_list.setCurrentRow(row - 1)

    def move_section_down(self):
        row = self.sections_list.currentRow()
        if 0 <= row < len(self.profile.sections) - 1:
            self.profile.sections[row + 1], self.profile.sections[row] = (
                self.profile.sections[row],
                self.profile.sections[row + 1],
            )
            self._refresh_sections()
            self.sections_list.setCurrentRow(row + 1)

    def accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Nome mancante", "Il nome del profilo è obbligatorio.")
            return

        # In modalità guidata le sezioni vengono costruite dalle checklist
        if getattr(self, "_sections_simple_mode", False):
            self.profile.sections = build_sections(self._collect_simple_options())

        if self.is_new:
            key = sanitize_profile_key(self.key_edit.text() or name)
            if not key:
                QMessageBox.warning(self, "Chiave invalida", "La chiave del profilo non può essere vuota.")
                return
            self.profile.profile_key = key
        else:
            # nei profili esistenti la chiave è bloccata
            key = self.profile.profile_key

        self.profile.name = name
        self.profile.device_type = self.device_type_edit.text().strip() or None
        # Raccogli gli ID degli strumenti selezionati
        selected_instrument_ids = []
        selected_instrument_snapshots = []
        for i in range(self.instruments_list.count()):
            item = self.instruments_list.item(i)
            if item.isSelected():
                inst_id = item.data(Qt.UserRole)
                if inst_id is not None:
                    selected_instrument_ids.append(inst_id)
                    inst = self.all_instruments.get(inst_id, {})
                    selected_instrument_snapshots.append(
                        {
                            "id": inst_id,
                            "instrument": inst.get("instrument_name"),
                            "serial": inst.get("serial_number"),
                            "version": inst.get("fw_version"),
                            "cal_date": inst.get("calibration_date"),
                            "instrument_type": inst.get("instrument_type"),
                        }
                    )
        self.profile.instrument_ids = selected_instrument_ids
        self.profile.instrument_snapshots = selected_instrument_snapshots
        self.profile.required_min_instruments = self.min_instruments_spin.value()

        allowed_types = []
        if self.allowed_type_functional.isChecked():
            allowed_types.append("functional")
        if self.allowed_type_electrical.isChecked():
            allowed_types.append("electrical")
        self.profile.allowed_instrument_types = allowed_types

        errors = validate_functional_profile(self.profile)
        if errors:
            QMessageBox.warning(self, "Profilo non valido", "\n".join(errors))
            return

        super().accept()


class FunctionalProfileManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestione Profili Funzionali")
        self.setMinimumSize(800, 600)
        # Applica il tema corrente
        self.setStyleSheet(config.get_current_stylesheet())
        self.profiles_changed = False

        layout = QVBoxLayout(self)
        
        # Header con titolo
        header_layout = QHBoxLayout()
        title_label = QLabel("<h2>📋 Profili Funzionali</h2>")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Lista profili migliorata
        self.profile_list = QListWidget()
        self.profile_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.profile_list.setAlternatingRowColors(True)
        layout.addWidget(self.profile_list)

        # Pulsanti migliorati con icone
        btn_layout = QHBoxLayout()
        
        self.add_btn = QPushButton(qta.icon('fa5s.plus-circle'), " Nuovo")
        self.add_btn.setObjectName("autoButton")
        self.add_btn.setToolTip("Crea un nuovo profilo (Wizard guidato)")
        
        self.edit_btn = QPushButton(qta.icon('fa5s.edit'), " Modifica")
        self.edit_btn.setObjectName("editButton")
        
        self.copy_btn = QPushButton(qta.icon('fa5s.copy'), " Copia")
        self.copy_btn.setObjectName("copyButton")
        self.copy_btn.setToolTip("Crea una copia del profilo selezionato")
        
        self.delete_btn = QPushButton(qta.icon('fa5s.trash'), " Elimina")
        self.delete_btn.setObjectName("deleteButton")
        
        self.import_btn = QPushButton(qta.icon('fa5s.file-import'), " Importa")
        self.import_btn.setObjectName("importButton")
        
        self.export_btn = QPushButton(qta.icon('fa5s.file-export'), " Esporta")
        self.export_btn.setObjectName("exportButton")
        
        for btn in (self.add_btn, self.edit_btn, self.copy_btn, self.delete_btn, self.import_btn, self.export_btn):
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        close_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_buttons.rejected.connect(self.reject)
        layout.addWidget(close_buttons)

        self.add_btn.clicked.connect(self.add_profile)
        self.edit_btn.clicked.connect(self.edit_profile)
        self.copy_btn.clicked.connect(self.copy_profile)
        self.delete_btn.clicked.connect(self.delete_profile)
        self.import_btn.clicked.connect(self.import_profiles)
        self.export_btn.clicked.connect(self.export_profile)
        self.profile_list.itemDoubleClicked.connect(lambda _: self.edit_profile())

        self.load_profiles_from_db()

    def load_profiles_from_db(self):
        """Carica i profili dal database con visualizzazione migliorata."""
        self.profile_list.clear()
        with database.DatabaseConnection() as conn:
            rows = conn.execute(
                "SELECT id, profile_key, name, device_type FROM functional_profiles WHERE is_deleted = 0 ORDER BY name"
            ).fetchall()
        for row in rows:
            name = row["name"]
            device_type = row["device_type"] if row["device_type"] else ""
            profile_key = row["profile_key"]
            
            # Crea item con informazioni aggiuntive
            display_text = name
            if device_type:
                display_text += f" ({device_type})"
            
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, {"id": row["id"], "key": profile_key})
            
            # Aggiungi icona in base al tipo
            if "ECG" in name.upper() or "ECG" in device_type.upper():
                item.setIcon(qta.icon('fa5s.heartbeat', color='#dc2626'))
            elif "SPO2" in name.upper() or "SPO2" in device_type.upper():
                item.setIcon(qta.icon('fa5s.lungs', color='#2563eb'))
            elif "DEFIB" in name.upper() or "DEFIB" in device_type.upper():
                item.setIcon(qta.icon('fa5s.bolt', color='#f59e0b'))
            else:
                item.setIcon(qta.icon('fa5s.cog', color='#64748b'))
            
            self.profile_list.addItem(item)

    def _get_selected(self):
        item = self.profile_list.currentItem()
        return item, item.data(Qt.UserRole) if item else (None, None)

    def add_profile(self):
        """Crea un nuovo profilo aprendo direttamente l'editor a documento.

        Niente più wizard: nome, tipo e contenuto si impostano tutti
        nell'unica schermata dell'editor.
        """
        editor = FunctionalProfileEditorDialog(profile=None, is_new=True, parent=self)
        if editor.exec() != QDialog.Accepted:
            return

        profile = editor.profile
        # Chiave univoca: se quella generata dal nome esiste già, aggiunge un
        # suffisso invece di buttare via il lavoro appena fatto
        base = profile.profile_key
        if base in config.FUNCTIONAL_PROFILES:
            n = 2
            while f"{base}_{n}" in config.FUNCTIONAL_PROFILES:
                n += 1
            profile.profile_key = f"{base}_{n}"

        try:
            services.add_functional_profile(profile.profile_key, profile)
            self.profiles_changed = True
            config.load_functional_profiles()
            self.load_profiles_from_db()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile creare il profilo:\n{e}")
    
    def copy_profile(self):
        """Crea una copia del profilo selezionato."""
        item, data = self._get_selected()
        if not item:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona un profilo da copiare.")
            return
        
        profile_key = data["key"]
        source_profile = config.FUNCTIONAL_PROFILES.get(profile_key)
        if not source_profile:
            QMessageBox.critical(self, "Errore", "Impossibile trovare il profilo selezionato.")
            return
        
        # Chiedi il nuovo nome
        new_name, ok = QMessageBox.getText(
            self,
            "Copia Profilo",
            f"Inserisci il nome per la copia di '{source_profile.name}':",
        )
        if not ok or not new_name.strip():
            return
        
        new_key = sanitize_profile_key(new_name)
        if new_key in config.FUNCTIONAL_PROFILES:
            QMessageBox.warning(
                self,
                "Chiave duplicata",
                f"Esiste già un profilo con la chiave '{new_key}'.",
            )
            return
        
        # Crea copia
        copied_profile = copy.deepcopy(source_profile)
        copied_profile.name = new_name.strip()
        copied_profile.profile_key = new_key
        
        try:
            services.add_functional_profile(copied_profile.profile_key, copied_profile)
            self.profiles_changed = True
            config.load_functional_profiles()
            self.load_profiles_from_db()
            QMessageBox.information(self, "Copia Completata", f"Profilo '{new_name}' creato con successo.")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile copiare il profilo:\n{e}")
    
    def edit_profile_by_key(self, profile_key: str):
        """Modifica un profilo dato il suo profile_key."""
        profile = config.FUNCTIONAL_PROFILES.get(profile_key)
        if not profile:
            return
        
        # Trova l'ID nel database
        with database.DatabaseConnection() as conn:
            row = conn.execute(
                "SELECT id FROM functional_profiles WHERE profile_key = ? AND is_deleted = 0",
                (profile_key,)
            ).fetchone()
        
        if not row:
            return
        
        editor = FunctionalProfileEditorDialog(profile=profile, is_new=False, parent=self)
        if editor.exec() == QDialog.Accepted:
            try:
                services.update_functional_profile(row["id"], editor.profile)
                self.profiles_changed = True
                config.load_functional_profiles()
                self.load_profiles_from_db()
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile salvare il profilo:\n{e}")

    def edit_profile(self):
        item, data = self._get_selected()
        if not item:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona un profilo da modificare.")
            return
        profile_key = data["key"]
        profile = config.FUNCTIONAL_PROFILES.get(profile_key)
        if not profile:
            QMessageBox.critical(self, "Errore", "Impossibile trovare il profilo selezionato.")
            return
        editor = FunctionalProfileEditorDialog(profile=profile, is_new=False, parent=self)
        if editor.exec() == QDialog.Accepted:
            try:
                services.update_functional_profile(data["id"], editor.profile)
                self.profiles_changed = True
                config.load_functional_profiles()
                self.load_profiles_from_db()
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile salvare il profilo:\n{e}")

    def delete_profile(self):
        item, data = self._get_selected()
        if not item:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona un profilo da eliminare.")
            return
        reply = QMessageBox.question(
            self,
            "Conferma eliminazione",
            f"Eliminare il profilo '{item.text()}'? L'operazione non può essere annullata.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                services.delete_functional_profile(data["id"])
                self.profiles_changed = True
                config.load_functional_profiles()
                self.load_profiles_from_db()
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile eliminare il profilo:\n{e}")

    def import_profiles(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Importa profilo funzionale",
            "",
            "File JSON (*.json);;Tutti i file (*.*)",
        )
        if not filename:
            return
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Errore lettura", f"Impossibile aprire il file:\n{e}")
            return

        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            QMessageBox.warning(self, "Formato non valido", "Il file selezionato non contiene un profilo valido.")
            return
        if data and all(isinstance(item, list) for item in data):
            QMessageBox.warning(
                self,
                "Formato non valido",
                "Il file selezionato contiene dati tabellari, non un profilo.\n"
                "Seleziona un file *_fun.json.",
            )
            return
        if any(not isinstance(item, dict) for item in data):
            QMessageBox.warning(
                self,
                "Formato non valido",
                "Il file selezionato contiene elementi non validi.\n"
                "Seleziona un file *_fun.json.",
            )
            return

        imported = 0
        for entry in data:
            try:
                profile = functional_profile_from_dict(entry)
                if not profile.profile_key:
                    profile.profile_key = sanitize_profile_key(profile.name)
                errors = validate_functional_profile(profile)
                if errors:
                    QMessageBox.warning(
                        self,
                        "Profilo non valido",
                        f"Profilo '{profile.name}' non importato:\n" + "\n".join(errors),
                    )
                    continue
                if profile.profile_key in config.FUNCTIONAL_PROFILES:
                    QMessageBox.warning(
                        self,
                        "Chiave duplicata",
                        f"Profilo '{profile.name}' non importato: chiave '{profile.profile_key}' già presente.",
                    )
                    continue
                services.add_functional_profile(profile.profile_key, profile)
                imported += 1
            except Exception as e:
                QMessageBox.warning(self, "Importazione fallita", f"Errore durante l'importazione:\n{e}")

        if imported:
            self.profiles_changed = True
            config.load_functional_profiles()
            self.load_profiles_from_db()
            QMessageBox.information(self, "Importazione completata", f"Importati {imported} profili.")

    def export_profile(self):
        item, data = self._get_selected()
        if not item:
            QMessageBox.warning(self, "Selezione mancante", "Seleziona un profilo da esportare.")
            return
        profile_key = data["key"]
        profile = config.FUNCTIONAL_PROFILES.get(profile_key)
        if not profile:
            QMessageBox.critical(self, "Errore", "Impossibile trovare il profilo selezionato.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Esporta profilo funzionale",
            f"{profile_key}.json",
            "File JSON (*.json)",
        )
        if not filename:
            return
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(functional_profile_to_dict(profile), f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "Esportazione completata", f"Profilo esportato in:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile esportare il profilo:\n{e}")

