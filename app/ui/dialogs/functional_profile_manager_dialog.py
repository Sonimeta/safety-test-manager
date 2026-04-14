from __future__ import annotations

import copy
import json
import re
import unicodedata
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSpinBox,
    QWizard,
    QWizardPage,
    QTextEdit,
)

from app import config, services
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
        has_formula = is_calculated or bool(self.formula_edit.text().strip())
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
        rows_label = QLabel("<b>Righe della Sezione</b>")
        rows_layout.addWidget(rows_label)
        self.rows_list = QListWidget()
        self.rows_list.setAlternatingRowColors(True)
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
        self.row_quick_add_btn.clicked.connect(self.quick_add_row)
        self.row_edit_btn.clicked.connect(self.edit_row)
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
        self.fields_table.setRowCount(0)
        for field in self.section.fields:
            row_idx = self.fields_table.rowCount()
            self.fields_table.insertRow(row_idx)
            self.fields_table.setItem(row_idx, 0, QTableWidgetItem(field.key))
            self.fields_table.setItem(row_idx, 1, QTableWidgetItem(field.label))
            self.fields_table.setItem(row_idx, 2, QTableWidgetItem(field.field_type))
            self.fields_table.setItem(row_idx, 3, QTableWidgetItem("Sì" if field.required else "No"))
            self.fields_table.setItem(row_idx, 4, QTableWidgetItem("Sì" if field.read_only else "No"))
            self.fields_table.setItem(row_idx, 5, QTableWidgetItem(field.formula or ""))

    def _refresh_rows(self):
        self.rows_list.clear()
        for row in self.section.rows:
            label = row.label or row.key
            item = QListWidgetItem(f"{row.key} - {label} ({len(row.fields)} campi)")
            item.setData(Qt.UserRole, row)
            self.rows_list.addItem(item)

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

    def quick_add_row(self):
        """Aggiunge velocemente una riga con campo esito preconfigurato (OK/KO/N.A.)."""
        from PySide6.QtWidgets import QInputDialog
        label, ok = QInputDialog.getText(
            self,
            "Aggiungi Riga Rapida",
            "Nome della verifica (es: Integrità cavo di alimentazione):",
        )
        if not ok or not label.strip():
            return
        label = label.strip()
        # Genera chiave dalla label
        key = self._slugify_key(label)
        if not key:
            key = f"riga_{len(self.section.rows) + 1}"
        # Verifica chiave unica
        if any(r.key == key for r in self.section.rows):
            suffix = 2
            while any(r.key == f"{key}_{suffix}" for r in self.section.rows):
                suffix += 1
            key = f"{key}_{suffix}"

        new_row = FunctionalRowDefinition(
            key=key,
            label=label,
            fields=[
                FunctionalField(
                    key="esito",
                    label="Esito",
                    field_type="pass_fail",
                    required=True,
                    options=["PASS", "FAIL", "N.A."],
                ),
            ],
        )
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
        
        # Header
        header_layout = QHBoxLayout()
        title_label = QLabel(f"<h2>{'Nuovo' if is_new else 'Modifica'} Profilo Funzionale</h2>")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # Layout orizzontale: form a sinistra, anteprima a destra
        content_layout = QHBoxLayout()
        
        # Colonna sinistra: Form
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        form_widget = QGroupBox("Informazioni Base")
        form = QFormLayout(form_widget)
        self.name_edit = QLineEdit(self.profile.name)
        self.name_edit.textChanged.connect(self._update_preview)
        form.addRow("Nome Profilo *:", self.name_edit)

        self.key_edit = QLineEdit(self.profile.profile_key)
        if not self.is_new:
            self.key_edit.setDisabled(True)
        form.addRow("Chiave Profilo:", self.key_edit)

        self.device_type_edit = QLineEdit(self.profile.device_type or "")
        self.device_type_edit.textChanged.connect(self._update_preview)
        form.addRow("Tipo Apparecchio:", self.device_type_edit)

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
        left_layout.addWidget(instruments_group)

        # Sezioni
        sections_group = QGroupBox("Sezioni del Profilo")
        sections_layout = QVBoxLayout(sections_group)
        self.sections_list = QListWidget()
        self.sections_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.sections_list.setAlternatingRowColors(True)
        sections_layout.addWidget(self.sections_list)

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
        left_layout.addWidget(sections_group, 1)
        
        content_layout.addWidget(left_widget, 2)
        
        # Colonna destra: Anteprima
        preview_group = QGroupBox("Anteprima Profilo")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumWidth(350)
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

        self._refresh_sections()
        self._update_preview()

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
    
    def _update_preview(self):
        """Aggiorna l'anteprima del profilo."""
        name = self.name_edit.text().strip() or "Nome Profilo"
        device_type = self.device_type_edit.text().strip()
        
        preview_html = f"<h3>{name}</h3>"
        if device_type:
            preview_html += f"<p><b>Tipo:</b> {device_type}</p>"
        
        preview_html += f"<p><b>Sezioni:</b> {len(self.profile.sections)}</p>"
        preview_html += "<hr>"
        
        for idx, section in enumerate(self.profile.sections):
            preview_html += f"<h4>{idx + 1}. {section.title}</h4>"
            preview_html += f"<p style='color: #64748b;'><i>Tipo: {section.section_type}</i></p>"
            
            if section.section_type == "fields":
                preview_html += "<ul>"
                for field in section.fields:
                    required = " <span style='color: red;'>*</span>" if field.required else ""
                    type_label = FIELD_TYPE_INFO.get(field.field_type, {}).get("label", field.field_type)
                    preview_html += f"<li>{field.label}{required} <span style='color:#94a3b8;'>({type_label})</span></li>"
                preview_html += "</ul>"
            else:
                preview_html += f"<p>Righe: {len(section.rows)}</p>"
                if section.rows:
                    preview_html += "<ul>"
                    for row in section.rows[:5]:
                        preview_html += f"<li>{row.label or row.key}"
                        if row.fields:
                            field_types = ", ".join(
                                FIELD_TYPE_INFO.get(f.field_type, {}).get("label", f.field_type) for f in row.fields
                            )
                            preview_html += f" <span style='color:#94a3b8;'>({field_types})</span>"
                        preview_html += "</li>"
                    if len(section.rows) > 5:
                        preview_html += f"<li>... e altre {len(section.rows) - 5}</li>"
                    preview_html += "</ul>"
            
            preview_html += "<br>"
        
        self.preview_text.setHtml(preview_html)

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


class FunctionalProfileWizard(QWizard):
    """Wizard guidato per creare un nuovo profilo funzionale."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wizard Creazione Profilo Funzionale")
        self.setMinimumSize(700, 500)
        # Applica il tema corrente
        self.setStyleSheet(config.get_current_stylesheet())
        
        # Pagina 1: Scelta metodo di creazione
        self.page1 = QWizardPage()
        self.page1.setTitle("Metodo di Creazione")
        self.page1.setSubTitle("Scegli come vuoi creare il nuovo profilo")
        page1_layout = QVBoxLayout(self.page1)
        
        self.create_method_combo = QComboBox()
        self.create_method_combo.addItem("Vuoto - Crea da zero", "empty")
        self.create_method_combo.addItem("Da Template Predefinito", "template")
        self.create_method_combo.addItem("Copia da Profilo Esistente", "copy")
        page1_layout.addWidget(QLabel("Come vuoi creare il profilo?"))
        page1_layout.addWidget(self.create_method_combo)
        page1_layout.addStretch()
        
        # Pagina 2: Template
        self.page2 = QWizardPage()
        self.page2.setTitle("Selezione Template")
        self.page2.setSubTitle("Scegli un template predefinito")
        page2_layout = QVBoxLayout(self.page2)
        
        self.template_list = QListWidget()
        self.template_list.addItem("ECG - Monitor ECG")
        self.template_list.addItem("SpO2 - Monitor SpO2")
        self.template_list.addItem("Defibrillatore")
        self.template_list.addItem("Ventilatore")
        self.template_list.addItem("Pompa Infusione")
        page2_layout.addWidget(self.template_list)
        page2_layout.addWidget(QLabel("💡 I template includono sezioni comuni per il tipo di dispositivo selezionato"))
        
        # Pagina 3: Copia da profilo
        self.page3 = QWizardPage()
        self.page3.setTitle("Copia da Profilo Esistente")
        self.page3.setSubTitle("Seleziona il profilo da copiare")
        page3_layout = QVBoxLayout(self.page3)
        
        self.copy_profile_list = QListWidget()
        page3_layout.addWidget(self.copy_profile_list)
        
        # Pagina 4: Informazioni base
        self.page4 = QWizardPage()
        self.page4.setTitle("Informazioni Base")
        self.page4.setSubTitle("Inserisci le informazioni principali del profilo")
        page4_layout = QFormLayout(self.page4)
        
        self.wizard_name_edit = QLineEdit()
        self.wizard_key_edit = QLineEdit()
        self.wizard_device_type_edit = QLineEdit()
        self.wizard_key_edit.setPlaceholderText("Generato automaticamente dal nome")
        
        page4_layout.addRow("Nome Profilo *:", self.wizard_name_edit)
        page4_layout.addRow("Chiave Profilo:", self.wizard_key_edit)
        page4_layout.addRow("Tipo Apparecchio:", self.wizard_device_type_edit)
        
        self.wizard_name_edit.textChanged.connect(self._on_name_changed)
        
        self.addPage(self.page1)
        self.addPage(self.page2)
        self.addPage(self.page3)
        self.addPage(self.page4)
        
        # Carica profili esistenti per la copia
        self._load_existing_profiles()
        
        # Connessioni
        self.create_method_combo.currentIndexChanged.connect(self._on_method_changed)
        self._on_method_changed(0)
    
    def _on_method_changed(self, index):
        """Mostra/nascondi pagine in base al metodo selezionato."""
        method = self.create_method_combo.currentData()
        if method == "template":
            self.setPage(1, self.page2)
            self.setPage(2, self.page4)
            self.removePage(3)
        elif method == "copy":
            self.setPage(1, self.page3)
            self.setPage(2, self.page4)
            self.removePage(3)
        else:  # empty
            self.setPage(1, self.page4)
            self.removePage(2)
            self.removePage(3)
    
    def _on_name_changed(self, text):
        """Genera automaticamente la chiave dal nome."""
        if text and not self.wizard_key_edit.isModified():
            key = sanitize_profile_key(text)
            self.wizard_key_edit.setText(key)
    
    def _load_existing_profiles(self):
        """Carica i profili esistenti per la copia."""
        self.copy_profile_list.clear()
        with database.DatabaseConnection() as conn:
            rows = conn.execute(
                "SELECT id, profile_key, name FROM functional_profiles WHERE is_deleted = 0 ORDER BY name"
            ).fetchall()
        for row in rows:
            item = QListWidgetItem(row["name"])
            item.setData(Qt.UserRole, {"id": row["id"], "key": row["profile_key"]})
            self.copy_profile_list.addItem(item)
    
    def get_profile(self) -> Optional[FunctionalProfile]:
        """Restituisce il profilo creato dal wizard."""
        method = self.create_method_combo.currentData()
        name = self.wizard_name_edit.text().strip()
        key = self.wizard_key_edit.text().strip() or sanitize_profile_key(name)
        device_type = self.wizard_device_type_edit.text().strip() or None
        
        if not name:
            return None
        
        if method == "template":
            # Crea profilo da template
            template_name = self.template_list.currentItem().text() if self.template_list.currentItem() else ""
            profile = self._create_from_template(template_name, name, key, device_type)
        elif method == "copy":
            # Copia da profilo esistente
            item = self.copy_profile_list.currentItem()
            if not item:
                return None
            data = item.data(Qt.UserRole)
            profile_key = data["key"]
            source_profile = config.FUNCTIONAL_PROFILES.get(profile_key)
            if source_profile:
                profile = copy.deepcopy(source_profile)
                profile.name = name
                profile.profile_key = key
                profile.device_type = device_type or profile.device_type
            else:
                return None
        else:  # empty
            # Profilo vuoto
            profile = FunctionalProfile(
                profile_key=key,
                name=name,
                device_type=device_type,
                sections=[],
            )
        
        return profile
    
    def _create_from_template(self, template_name: str, name: str, key: str, device_type: Optional[str]) -> FunctionalProfile:
        """Crea un profilo da un template predefinito."""
        # Template base con sezioni comuni
        sections = []
        
        if "ECG" in template_name:
            sections = [
                FunctionalSection(
                    key="normative_references",
                    title="Riferimenti Normativi-Procedure",
                    section_type="fields",
                    description="",
                    fields=[
                        FunctionalField(
                            key="norme_procedure",
                            label="Norme/Procedure",
                            field_type="text",
                            required=False,
                            default="CEI 62-26/AMS-MOD-PROVECG1",
                        )
                    ],
                    rows=[],
                ),
                FunctionalSection(
                    key="visual_functional_control",
                    title="Controllo Visivo/Funzionale",
                    section_type="checklist",
                    description="",
                    fields=[],
                    rows=[
                        FunctionalRowDefinition(
                            key="serigrafie_etichette",
                            label="Leggibilità delle serigrafie/etichette",
                            fields=[
                                FunctionalField(
                                    key="esito",
                                    label="Esito",
                                    field_type="choice",
                                    required=True,
                                    options=["OK", "KO", "N.A."],
                                )
                            ],
                        ),
                    ],
                ),
            ]
        elif "SpO2" in template_name:
            sections = [
                FunctionalSection(
                    key="normative_references",
                    title="Riferimenti Normativi-Procedure",
                    section_type="fields",
                    description="",
                    fields=[
                        FunctionalField(
                            key="norme_procedure",
                            label="Norme/Procedure",
                            field_type="text",
                            required=False,
                        )
                    ],
                    rows=[],
                ),
                FunctionalSection(
                    key="visual_functional_control",
                    title="Controllo Visivo/Funzionale",
                    section_type="checklist",
                    description="",
                    fields=[],
                    rows=[
                        FunctionalRowDefinition(
                            key="serigrafie_etichette",
                            label="Leggibilità delle serigrafie/etichette",
                            fields=[
                                FunctionalField(
                                    key="esito",
                                    label="Esito",
                                    field_type="choice",
                                    required=True,
                                    options=["OK", "KO", "N.A."],
                                )
                            ],
                        ),
                    ],
                ),
            ]
        else:
            # Template generico
            sections = [
                FunctionalSection(
                    key="general_info",
                    title="Informazioni Generali",
                    section_type="fields",
                    description="",
                    fields=[
                        FunctionalField(
                            key="note",
                            label="Note",
                            field_type="multiline",
                            required=False,
                        )
                    ],
                    rows=[],
                ),
            ]
        
        return FunctionalProfile(
            profile_key=key,
            name=name,
            device_type=device_type,
            sections=sections,
        )


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
        """Apre il wizard per creare un nuovo profilo."""
        wizard = FunctionalProfileWizard(parent=self)
        if wizard.exec() == QDialog.Accepted:
            profile = wizard.get_profile()
            if not profile:
                QMessageBox.warning(self, "Dati mancanti", "Inserire almeno il nome del profilo.")
                return
            
            if profile.profile_key in config.FUNCTIONAL_PROFILES:
                QMessageBox.warning(
                    self,
                    "Chiave duplicata",
                    f"Esiste già un profilo con la chiave '{profile.profile_key}'.",
                )
                return
            
            try:
                services.add_functional_profile(profile.profile_key, profile)
                self.profiles_changed = True
                config.load_functional_profiles()
                self.load_profiles_from_db()
                
                # Apri l'editor per completare la configurazione
                reply = QMessageBox.question(
                    self,
                    "Profilo Creato",
                    f"Il profilo '{profile.name}' è stato creato.\n\nVuoi modificarlo ora per aggiungere sezioni e campi?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    self.edit_profile_by_key(profile.profile_key)
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

