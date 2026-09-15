"""Dialog per il Controllo Qualità delle sonde ecografiche.

Permette di inserire/modificare una verifica completa con N sonde,
ciascuna con i 10 controlli previsti dal manuale di qualità.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import os
import re
import logging
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import database
from app.ui.widgets import NoHoverFocusLineEdit, NoHoverFocusComboBox, fix_calendar_popup
from app.ecografo_quality_logic import (
    CONTROL_ANECHOIC_MASS,
    CONTROL_DEAD_ZONE,
    CONTROL_HORIZONTAL_MEASURES,
    CONTROL_HYPOERECHOIC_MASS,
    CONTROL_INSPECTION,
    CONTROL_MAX_DEPTH,
    CONTROL_RESOLUTION_11CM_AXIAL,
    CONTROL_RESOLUTION_11CM_LATERAL,
    CONTROL_RESOLUTION_3CM_AXIAL,
    CONTROL_RESOLUTION_3CM_LATERAL,
    CONTROL_UNIFORMITY,
    CONTROL_VERTICAL_MEASURES,
    evaluate_check,
    get_default_controls,
    update_overall_status,
)
from app.ecografo_quality_models import (
    EcografoQualityCheck,
    EcografoQualityControl,
    EcografoQualityProbe,
)


# ─── Widget per i 10 controlli di qualità conforme al PDF ────────────────────

class InspectionControlWidget(QGroupBox):
    """Controllo 1 & 2: Ispezione Visiva / Uniformità con descrizioni PDF."""

    def __init__(self, control: EcografoQualityControl, parent=None):
        super().__init__(f"{control.control_label}", parent)
        self.control = control
        self.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        layout = QVBoxLayout(self)

        self.combo = NoHoverFocusComboBox()
        if control.control_key == CONTROL_INSPECTION:
            self.combo.addItem("BUONO (non vi sono crepe/tagli/altre non conformità né sulla sonda né sulla guaina)", "BUONO")
            self.combo.addItem("SUFFICIENTE (vi sono delle non conformità di lieve entità)", "SUFFICIENTE")
            self.combo.addItem("INSUFFICIENTE (vi sono delle non conformità di entità non lieve)", "INSUFFICIENTE")
        else:
            self.combo.addItem("BUONO (immagine uniforme in tutte le zone lungo tutta la profondità di penetrazione)", "BUONO")
            self.combo.addItem("SUFFICIENTE (vi sono delle zone non uniformi che però non pregiudicano la visione dei pin)", "SUFFICIENTE")
            self.combo.addItem("INSUFFICIENTE (vi sono delle zone non uniformi che pregiudicano la visione dei pin)", "INSUFFICIENTE")

        if control.value:
            idx = self.combo.findData(control.value.upper())
            if idx >= 0:
                self.combo.setCurrentIndex(idx)

        self.combo.currentIndexChanged.connect(self._on_change)
        layout.addWidget(self.combo)

        # Campo Note
        n_layout = QHBoxLayout()
        n_layout.addWidget(QLabel("Note:"))
        self.notes_edit = NoHoverFocusLineEdit(control.notes or "")
        self.notes_edit.setPlaceholderText("Note o osservazioni")
        n_layout.addWidget(self.notes_edit)
        layout.addLayout(n_layout)

    def _on_change(self):
        self.control.value = self.combo.currentData()
        self.control.passed = self.control.value in ("BUONO", "SUFFICIENTE")

    def save_to_model(self):
        self.control.value = self.combo.currentData()
        self.control.passed = self.control.value in ("BUONO", "SUFFICIENTE")
        self.control.notes = self.notes_edit.text().strip() or None

    def refresh_status(self):
        pass


class MaxDepthControlWidget(QGroupBox):
    """Controllo 3: Massima profondità di penetrazione."""

    def __init__(self, control: EcografoQualityControl, parent=None):
        super().__init__("3. MASSIMA PROFONDITA' DI PENETRAZIONE", parent)
        self.control = control
        self.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        layout = QVBoxLayout(self)

        f_layout = QHBoxLayout()
        f_layout.addWidget(QLabel("<b>DISTANZA DELL'ULTIMO BERSAGLIO VISIBILE (cm):</b>"))
        self.val_edit = NoHoverFocusLineEdit(control.value or "")
        self.val_edit.setPlaceholderText("Es. 14.5")
        f_layout.addWidget(self.val_edit)
        layout.addLayout(f_layout)

        ref_lbl = QLabel("<span style='color:#64748b;'>Valori di riferimento: <2.5 MHz &rarr; >16 cm | 2.5-5 MHz &rarr; >13 cm | 5-8 MHz &rarr; >6 cm | 8-12 MHz &rarr; >4 cm</span>")
        ref_lbl.setWordWrap(True)
        layout.addWidget(ref_lbl)

        n_layout = QHBoxLayout()
        n_layout.addWidget(QLabel("Note:"))
        self.notes_edit = NoHoverFocusLineEdit(control.notes or "")
        n_layout.addWidget(self.notes_edit)
        layout.addLayout(n_layout)

    def save_to_model(self):
        self.control.value = self.val_edit.text().strip() or None
        self.control.notes = self.notes_edit.text().strip() or None

    def refresh_status(self):
        pass


class VerticalMeasuresWidget(QGroupBox):
    """Controllo 4: Misure Verticali con tabella di 8 punti 20-160mm."""

    def __init__(self, control: EcografoQualityControl, parent=None):
        super().__init__("4. MISURE VERTICALI", parent)
        self.control = control
        self.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        layout = QVBoxLayout(self)

        self.rows_edits: List[Tuple[float, NoHoverFocusLineEdit, QLabel]] = []
        grid = QFormLayout()
        grid.addRow(QLabel("<b>Effettivo (mm)</b>"), QLabel("<b>Misurato (mm)</b>"))

        # Carica valori precedenti
        prev_vals = {}
        if control.value and ";" in str(control.value):
            parts = str(control.value).split(";")
            effs = [20, 40, 60, 80, 100, 120, 140, 160]
            for e, p in zip(effs, parts):
                prev_vals[e] = p

        for eff in [20, 40, 60, 80, 100, 120, 140, 160]:
            edit = NoHoverFocusLineEdit(prev_vals.get(eff, ""))
            edit.setPlaceholderText(f"Misurato per {eff} mm")
            scarto_lbl = QLabel("Scarto: -")
            edit.textChanged.connect(lambda text, e=eff, l=scarto_lbl: self._calc_scarto(e, text, l))
            grid.addRow(QLabel(f"<b>{eff} mm</b>"), edit)
            self.rows_edits.append((eff, edit, scarto_lbl))

        layout.addLayout(grid)
        ref_lbl = QLabel("<span style='color:#64748b;'>Valori di riferimento: scarto < 1,5 mm fra due misure contigue</span>")
        layout.addWidget(ref_lbl)

    def _calc_scarto(self, eff: int, text: str, label: QLabel):
        try:
            val = float(text.replace(",", "."))
            scarto = abs(val - eff)
            label.setText(f"Scarto: {scarto:.2f} mm")
        except ValueError:
            label.setText("Scarto: -")

    def save_to_model(self):
        vals = [edit.text().strip() for _, edit, _ in self.rows_edits]
        if any(vals):
            self.control.value = ";".join(vals)
        else:
            self.control.value = None

    def refresh_status(self):
        pass


class HorizontalMeasuresWidget(QGroupBox):
    """Controllo 5: Misure Orizontali con tabella e checkbox Test Non Applicabile."""

    def __init__(self, control: EcografoQualityControl, parent=None):
        super().__init__("5. MISURE ORIZZONTALI", parent)
        self.control = control
        self.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        layout = QVBoxLayout(self)

        self.na_checkbox = QCheckBox("TEST NON APPLICABILE A QUESTA SONDA")
        self.na_checkbox.stateChanged.connect(self._on_na_change)
        layout.addWidget(self.na_checkbox)

        self.form_widget = QWidget()
        form_layout = QFormLayout(self.form_widget)
        self.rows_edits: List[Tuple[int, NoHoverFocusLineEdit]] = []

        effs = [-20, -40, -60, -80, 40, 20]
        prev_vals = {}
        if control.value and control.value != "N/A" and ";" in str(control.value):
            parts = str(control.value).split(";")
            for e, p in zip(effs, parts):
                prev_vals[e] = p

        for eff in effs:
            edit = NoHoverFocusLineEdit(prev_vals.get(eff, ""))
            edit.setPlaceholderText(f"Misurato per {eff} mm")
            form_layout.addRow(QLabel(f"<b>{eff} mm</b>"), edit)
            self.rows_edits.append((eff, edit))

        layout.addWidget(self.form_widget)
        ref_lbl = QLabel("<span style='color:#64748b;'>Valori di riferimento: scarto < 2 mm fra due misure contigue</span>")
        layout.addWidget(ref_lbl)

        if control.value == "N/A":
            self.na_checkbox.setChecked(True)
            self.form_widget.setEnabled(False)

    def _on_na_change(self, state):
        self.form_widget.setEnabled(state == 0)

    def save_to_model(self):
        if self.na_checkbox.isChecked():
            self.control.value = "N/A"
        else:
            vals = [edit.text().strip() for _, edit in self.rows_edits]
            self.control.value = ";".join(vals) if any(vals) else None

    def refresh_status(self):
        pass


class DeadZoneWidget(QGroupBox):
    """Controllo 6: Zona Morta."""

    def __init__(self, control: EcografoQualityControl, parent=None):
        super().__init__("6. ZONA MORTA", parent)
        self.control = control
        self.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        layout = QVBoxLayout(self)

        self.na_checkbox = QCheckBox("TEST NON APPLICABILE A QUESTA SONDA")
        self.na_checkbox.stateChanged.connect(lambda s: self.form_widget.setEnabled(s == 0))
        layout.addWidget(self.na_checkbox)

        self.form_widget = QWidget()
        f_layout = QHBoxLayout(self.form_widget)
        f_layout.addWidget(QLabel("NUMERO TOTALE BERSAGLI:"))
        self.targets_edit = NoHoverFocusLineEdit()
        self.targets_edit.setPlaceholderText("Es. 6")
        f_layout.addWidget(self.targets_edit)

        f_layout.addWidget(QLabel("ZONA MORTA (mm):"))
        self.dead_zone_edit = NoHoverFocusLineEdit()
        self.dead_zone_edit.setPlaceholderText("Es. 1")
        f_layout.addWidget(self.dead_zone_edit)

        if control.value and control.value != "N/A" and ";" in str(control.value):
            parts = dict(p.split("=") for p in control.value.split(";") if "=" in p)
            self.targets_edit.setText(parts.get("targets", ""))
            self.dead_zone_edit.setText(parts.get("zona_morta", ""))
        elif control.value == "N/A":
            self.na_checkbox.setChecked(True)
            self.form_widget.setEnabled(False)

        layout.addWidget(self.form_widget)
        ref_lbl = QLabel("<span style='color:#64748b;'>Valori di riferimento: <7 mm (<3 MHz) | <5 mm (3-7 MHz) | <3 mm (>7 MHz)</span>")
        layout.addWidget(ref_lbl)

    def save_to_model(self):
        if self.na_checkbox.isChecked():
            self.control.value = "N/A"
        else:
            t = self.targets_edit.text().strip()
            z = self.dead_zone_edit.text().strip()
            self.control.value = f"targets={t};zona_morta={z}" if (t or z) else None

    def refresh_status(self):
        pass


class Resolution3cmWidget(QGroupBox):
    """Controllo 7: Risoluzione 3 cm (Assiale & Laterale)."""

    def __init__(self, axial_ctrl: EcografoQualityControl, lateral_ctrl: EcografoQualityControl, parent=None):
        super().__init__("7. RISOLUZIONE 3 CM", parent)
        self.axial_ctrl = axial_ctrl
        self.lateral_ctrl = lateral_ctrl
        self.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        layout = QFormLayout(self)

        opts_3cm = ["1a (4 mm)", "2a (3 mm)", "3a (2 mm)", "4a (1 mm)", "5a (.5 mm)", "6a (.25 mm)", "N/A"]

        self.axial_combo = NoHoverFocusComboBox()
        self.axial_combo.addItems(opts_3cm)
        if axial_ctrl.value:
            self.axial_combo.setCurrentText(axial_ctrl.value)

        self.lateral_combo = NoHoverFocusComboBox()
        self.lateral_combo.addItems(opts_3cm)
        if lateral_ctrl.value:
            self.lateral_combo.setCurrentText(lateral_ctrl.value)

        layout.addRow("Ultima coppia Assiale:", self.axial_combo)
        layout.addRow("Ultima coppia Laterale:", self.lateral_combo)
        ref_lbl = QLabel("<span style='color:#64748b;'>Valori di riferimento: non deve superare di 1 mm i valori indicati dal costruttore</span>")
        layout.addRow(ref_lbl)

    def save_to_model(self):
        self.axial_ctrl.value = self.axial_combo.currentText()
        self.lateral_ctrl.value = self.lateral_combo.currentText()

    def refresh_status(self):
        pass


class Resolution11cmWidget(QGroupBox):
    """Controllo 8: Risoluzione 11 cm (Assiale & Laterale)."""

    def __init__(self, axial_ctrl: EcografoQualityControl, lateral_ctrl: EcografoQualityControl, parent=None):
        super().__init__("8. RISOLUZIONE 11 CM", parent)
        self.axial_ctrl = axial_ctrl
        self.lateral_ctrl = lateral_ctrl
        self.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        layout = QFormLayout(self)

        opts_11cm = ["1a (5 mm)", "2a (4 mm)", "3a (3 mm)", "4a (2 mm)", "5a (1 mm)", "Non Applicabile"]

        self.axial_combo = NoHoverFocusComboBox()
        self.axial_combo.addItems(opts_11cm)
        if axial_ctrl.value:
            self.axial_combo.setCurrentText(axial_ctrl.value)

        self.lateral_combo = NoHoverFocusComboBox()
        self.lateral_combo.addItems(opts_11cm)
        if lateral_ctrl.value:
            self.lateral_combo.setCurrentText(lateral_ctrl.value)

        layout.addRow("Ultima coppia Assiale:", self.axial_combo)
        layout.addRow("Ultima coppia Laterale:", self.lateral_combo)
        ref_lbl = QLabel("<span style='color:#64748b;'>Valori di riferimento: non deve superare di 1 mm i valori indicati dal costruttore</span>")
        layout.addRow(ref_lbl)

    def save_to_model(self):
        self.axial_ctrl.value = self.axial_combo.currentText()
        self.lateral_ctrl.value = self.lateral_combo.currentText()

    def refresh_status(self):
        pass


class MassAnalysisWidget(QGroupBox):
    """Controllo 9 & 10: Analisi Masse Anecoiche / Iperecogene."""

    def __init__(self, control: EcografoQualityControl, title: str, parent=None):
        super().__init__(title, parent)
        self.control = control
        self.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        layout = QVBoxLayout(self)

        self.na_checkbox = QCheckBox("TEST NON APPLICABILE A QUESTA SONDA")
        self.na_checkbox.stateChanged.connect(lambda s: self.form_widget.setEnabled(s == 0))
        layout.addWidget(self.na_checkbox)

        self.form_widget = QWidget()
        f_layout = QFormLayout(self.form_widget)

        self.oriz_edit = NoHoverFocusLineEdit()
        self.oriz_edit.setPlaceholderText("Es. 6.9")
        self.vert_edit = NoHoverFocusLineEdit()
        self.vert_edit.setPlaceholderText("Es. 6.8")

        self.rapporto_lbl = QLabel("1.00")
        self.area_lbl = QLabel("0.00 mm²")

        self.oriz_edit.textChanged.connect(self._recalc)
        self.vert_edit.textChanged.connect(self._recalc)

        f_layout.addRow("Diametro orizzontale (mm):", self.oriz_edit)
        f_layout.addRow("Diametro verticale (mm):", self.vert_edit)
        f_layout.addRow("Rapporto diametri:", self.rapporto_lbl)
        f_layout.addRow("Area (mm²):", self.area_lbl)

        if control.value and control.value != "N/A" and ";" in str(control.value):
            parts = dict(p.split("=") for p in control.value.split(";") if "=" in p)
            self.oriz_edit.setText(parts.get("oriz", ""))
            self.vert_edit.setText(parts.get("vert", ""))
            self._recalc()
        elif control.value == "N/A":
            self.na_checkbox.setChecked(True)
            self.form_widget.setEnabled(False)

        layout.addWidget(self.form_widget)
        ref_lbl = QLabel("<span style='color:#64748b;'>Valori di riferimento: non esiste una standardizzazione tale da indicare dei limiti di tolleranza su scala quantitativa</span>")
        layout.addWidget(ref_lbl)

    def _recalc(self):
        try:
            o = float(self.oriz_edit.text().replace(",", "."))
            v = float(self.vert_edit.text().replace(",", "."))
            rapporto = o / v if v != 0 else 0
            import math
            area = math.pi * (o / 2.0) * (v / 2.0)
            self.rapporto_lbl.setText(f"{rapporto:.2f}")
            self.area_lbl.setText(f"{area:.1f} mm²")
        except ValueError:
            self.rapporto_lbl.setText("-")
            self.area_lbl.setText("-")

    def save_to_model(self):
        if self.na_checkbox.isChecked():
            self.control.value = "N/A"
        else:
            o = self.oriz_edit.text().strip()
            v = self.vert_edit.text().strip()
            r = self.rapporto_lbl.text()
            a = self.area_lbl.text().replace(" mm²", "")
            self.control.value = f"oriz={o};vert={v};rapporto={r};area={a}" if (o or v) else None

    def refresh_status(self):
        pass


# ─── Widget per una sonda (Completamente Scrollabile e Flessibile) ───────────

class ProbeWidget(QWidget):
    """Scheda di input per una singola sonda ecografica."""

    def __init__(
        self,
        probe: EcografoQualityProbe,
        index: int,
        on_remove: Any,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.probe = probe
        self.index = index
        self.on_remove = on_remove
        self.control_widgets: Dict[str, ControlRowWidget] = {}
        self._build_ui()

    def _build_ui(self):
        # Utilizzo di un QScrollArea a livello principale per la scheda della sonda
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)

        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(16)

        # Header Sonda
        # Header Sonda
        header_layout = QHBoxLayout()
        title_text = f"Sonda #{self.index + 1}"
        if self.probe.model or self.probe.probe_type:
            title_text += f" — {self.probe.model or self.probe.probe_type}"
        if self.probe.serial_number:
            title_text += f" (S/N: {self.probe.serial_number})"
        self.title_label = QLabel(f"<h3 style='margin:0; color:#1e3a5f;'>{title_text}</h3>")
        header_layout.addWidget(self.title_label)

        header_layout.addSpacing(20)
        self.include_checkbox = QCheckBox("✔ Sonda sottoposta a verifica in questa sessione")
        self.include_checkbox.setCursor(Qt.PointingHandCursor)
        self.include_checkbox.setStyleSheet("QCheckBox { font-size: 13px; font-weight: bold; color: #059669; } QCheckBox::indicator { width: 18px; height: 18px; }")
        self.include_checkbox.setChecked(True)
        self.include_checkbox.toggled.connect(self._on_include_toggled)
        header_layout.addWidget(self.include_checkbox)

        header_layout.addStretch()

        self.remove_btn = QPushButton("Elimina questa sonda")
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setStyleSheet("background-color: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; font-weight: bold; padding: 4px 12px; border-radius: 4px;")
        self.remove_btn.clicked.connect(lambda: self.on_remove(self.probe))
        header_layout.addWidget(self.remove_btn)
        main_layout.addLayout(header_layout)

        # Contenitore abilitabile/disabilitabile
        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        # Sezione 1: Layout affiancato per Dati Sonda e Parametri Test (2 colonne)
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)

        # Card 1: Dati identificativi sonda
        ident_group = QGroupBox("Dati Identificativi Sonda")
        ident_group.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        ident_layout = QFormLayout(ident_group)
        ident_layout.setSpacing(8)

        self.type_edit = NoHoverFocusLineEdit(self.probe.probe_type or "")
        self.type_edit.setPlaceholderText("Es. Convex / Linear / Phased Array")
        self.model_edit = NoHoverFocusLineEdit(self.probe.model or "")
        self.model_edit.setPlaceholderText("Es. C5-2 / L12-4")
        self.serial_edit = NoHoverFocusLineEdit(self.probe.serial_number or "")
        self.serial_edit.setPlaceholderText("Numero di serie")
        self.manufacturer_edit = NoHoverFocusLineEdit(self.probe.manufacturer or "")
        self.inventory_edit = NoHoverFocusLineEdit(self.probe.inventory or "")

        ident_layout.addRow("Tipo Sonda:", self.type_edit)
        ident_layout.addRow("Modello:", self.model_edit)
        ident_layout.addRow("S/N (Matricola):", self.serial_edit)
        ident_layout.addRow("Costruttore:", self.manufacturer_edit)
        ident_layout.addRow("Inventario:", self.inventory_edit)

        cards_layout.addWidget(ident_group, 1)

        # Card 2: Parametri Test e Stadio
        test_group = QGroupBox("Parametri di Test e Stadio")
        test_group.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        test_layout = QFormLayout(test_group)
        test_layout.setSpacing(8)

        self.stage_combo = NoHoverFocusComboBox()
        self.stage_combo.setEditable(True)
        self.stage_combo.addItems(["Baseline", "Controllo 1", "Controllo 2", "Controllo 3", "Controllo 4"])
        if self.probe.control_stage:
            self.stage_combo.setCurrentText(self.probe.control_stage)

        self.test_model_edit = NoHoverFocusLineEdit(self.probe.test_model or "")
        self.test_model_edit.setPlaceholderText("Es. GEN-M / RIS-B")
        self.preset_edit = NoHoverFocusLineEdit(self.probe.preset or "")
        self.preset_edit.setPlaceholderText("Es. ADDOMINALE GENERALE")
        self.gain_edit = NoHoverFocusLineEdit(self.probe.gain or "")
        self.power_edit = NoHoverFocusLineEdit(self.probe.power or "")
        self.baseline_edit = NoHoverFocusLineEdit(self.probe.baseline or "")
        self.baseline_edit.setPlaceholderText("Es. Valori di targa o riferimento iniziale")
        self.baseline_edit.setToolTip("Valore o riferimento iniziale (es. prima calibrazione) usato per confrontare il decadimento delle prestazioni nei controlli successivi.")

        self.judgment_combo = NoHoverFocusComboBox()
        self.judgment_combo.addItems(["BUONO", "SUFFICIENTE", "NON SUFFICIENTE"])
        if self.probe.overall_judgment and self.probe.overall_judgment in ["BUONO", "SUFFICIENTE", "NON SUFFICIENTE"]:
            self.judgment_combo.setCurrentText(self.probe.overall_judgment)
        else:
            self.judgment_combo.setCurrentText("BUONO")

        test_layout.addRow("Stadio Controllo:", self.stage_combo)
        test_layout.addRow("Mod. usata per test:", self.test_model_edit)
        test_layout.addRow("Preset impostato:", self.preset_edit)
        test_layout.addRow("Gain:", self.gain_edit)
        test_layout.addRow("Power:", self.power_edit)
        test_layout.addRow("Baseline:", self.baseline_edit)
        test_layout.addRow("Giudizio complessivo:", self.judgment_combo)

        cards_layout.addWidget(test_group, 1)
        content_layout.addLayout(cards_layout)

        # Sezione 2: Controlli di qualità (i 10 punti del manuale PDF)
        controls_group = QGroupBox("Controlli di Qualità (Manuale Ecografo)")
        controls_group.setStyleSheet("QGroupBox { font-weight: bold; color: #1e3a5f; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 6px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }")
        controls_layout = QVBoxLayout(controls_group)
        controls_layout.setSpacing(12)

        # Assicura che esistano tutti i controlli di default
        existing_keys = {c.control_key for c in self.probe.controls}
        for default in get_default_controls():
            if default.control_key not in existing_keys:
                self.probe.controls.append(default)

        # Mappa dei controlli per chiave
        c_map = {c.control_key: c for c in self.probe.controls}

        self.custom_widgets = []

        # 1. Ispezione visiva
        w1 = InspectionControlWidget(c_map[CONTROL_INSPECTION])
        controls_layout.addWidget(w1)
        self.custom_widgets.append(w1)

        # 2. Uniformità
        w2 = InspectionControlWidget(c_map[CONTROL_UNIFORMITY])
        controls_layout.addWidget(w2)
        self.custom_widgets.append(w2)

        # 3. Massima profondità di penetrazione
        w3 = MaxDepthControlWidget(c_map[CONTROL_MAX_DEPTH])
        controls_layout.addWidget(w3)
        self.custom_widgets.append(w3)

        # 4. Misure verticali
        w4 = VerticalMeasuresWidget(c_map[CONTROL_VERTICAL_MEASURES])
        controls_layout.addWidget(w4)
        self.custom_widgets.append(w4)

        # 5. Misure orizzontali
        w5 = HorizontalMeasuresWidget(c_map[CONTROL_HORIZONTAL_MEASURES])
        controls_layout.addWidget(w5)
        self.custom_widgets.append(w5)

        # 6. Zona morta
        w6 = DeadZoneWidget(c_map[CONTROL_DEAD_ZONE])
        controls_layout.addWidget(w6)
        self.custom_widgets.append(w6)

        # 7. Risoluzione 3 cm
        w7 = Resolution3cmWidget(c_map[CONTROL_RESOLUTION_3CM_AXIAL], c_map[CONTROL_RESOLUTION_3CM_LATERAL])
        controls_layout.addWidget(w7)
        self.custom_widgets.append(w7)

        # 8. Risoluzione 11 cm
        w8 = Resolution11cmWidget(c_map[CONTROL_RESOLUTION_11CM_AXIAL], c_map[CONTROL_RESOLUTION_11CM_LATERAL])
        controls_layout.addWidget(w8)
        self.custom_widgets.append(w8)

        # 9. Analisi masse anecoiche
        w9 = MassAnalysisWidget(c_map[CONTROL_ANECHOIC_MASS], "9. ANALISI DELLE MASSE ANECOICHE")
        controls_layout.addWidget(w9)
        self.custom_widgets.append(w9)

        # 10. Analisi masse iperecogene
        w10 = MassAnalysisWidget(c_map[CONTROL_HYPOERECHOIC_MASS], "10. ANALISI DELLE MASSE IPERECOGENE")
        controls_layout.addWidget(w10)
        self.custom_widgets.append(w10)

        content_layout.addWidget(controls_group)
        main_layout.addWidget(self.content_widget)

        scroll_area.setWidget(container)
        outer_layout.addWidget(scroll_area)

    def _on_include_toggled(self, checked: bool):
        self.content_widget.setEnabled(checked)
        if checked:
            self.include_checkbox.setStyleSheet("QCheckBox { font-size: 13px; font-weight: bold; color: #059669; } QCheckBox::indicator { width: 18px; height: 18px; }")
        else:
            self.include_checkbox.setStyleSheet("QCheckBox { font-size: 13px; font-weight: bold; color: #94a3b8; } QCheckBox::indicator { width: 18px; height: 18px; }")

    def update_index(self, index: int):
        self.index = index
        title_text = f"Sonda #{index + 1}"
        if self.probe.model or self.probe.probe_type:
            title_text += f" — {self.probe.model or self.probe.probe_type}"
        if self.probe.serial_number:
            title_text += f" (S/N: {self.probe.serial_number})"
        self.title_label.setText(f"<h3 style='margin:0; color:#1e3a5f;'>{title_text}</h3>")

    def save_to_model(self):
        self.probe.inventory = self.inventory_edit.text().strip() or None
        self.probe.manufacturer = self.manufacturer_edit.text().strip() or None
        self.probe.probe_type = self.type_edit.text().strip() or None
        self.probe.serial_number = self.serial_edit.text().strip() or None
        self.probe.model = self.model_edit.text().strip() or None
        self.probe.control_stage = self.stage_combo.currentText().strip() or "Baseline"
        self.probe.test_model = self.test_model_edit.text().strip() or None
        self.probe.preset = self.preset_edit.text().strip() or None
        self.probe.gain = self.gain_edit.text().strip() or None
        self.probe.power = self.power_edit.text().strip() or None
        self.probe.baseline = self.baseline_edit.text().strip() or None
        self.probe.overall_judgment = self.judgment_combo.currentText().strip() or "BUONO"
        self.probe.probe_order = self.index

        for w in self.custom_widgets:
            w.save_to_model()

    def refresh_controls(self):
        for w in self.control_widgets.values():
            w.refresh_status()


# ─── Dialog principale Riprogettato ──────────────────────────────────────────

class EcografoQualityDialog(QDialog):
    """Dialog moderno e user-friendly per il Controllo Qualità sonde ecografo."""

    def __init__(
        self,
        device_info: Dict[str, Any],
        check: EcografoQualityCheck | None = None,
        technician_name: str = "",
        technician_username: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.device_info = device_info
        self.technician_name = technician_name
        self.technician_username = technician_username

        if check is None:
            today = datetime.now().strftime("%Y-%m-%d")
            dev_id = device_info.get("id", 0)
            initial_probes = self._prefill_probes_from_last_check(dev_id)
            self.check = EcografoQualityCheck(
                device_id=dev_id,
                verification_date=today,
                technician_name=technician_name or None,
                technician_username=technician_username or None,
                probes=initial_probes,
            )
            self.edit_mode = False
        else:
            self.check = check
            self.edit_mode = True

        self.probe_widgets: List[ProbeWidget] = []
        self.setWindowTitle("Controllo Qualità Sonde Ecografo")
        self.setWindowState(Qt.WindowMaximized)
        self.setMinimumSize(950, 680)
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus()

    def _prefill_probes_from_last_check(self, device_id: int) -> List[EcografoQualityProbe]:
        """Precompila in automatico i dati identificativi e i parametri di test delle sonde dall'ultimo controllo registrato."""
        if not device_id:
            return []
        past_check_rows = database.get_ecografo_quality_checks_for_device(device_id)
        if not past_check_rows:
            return []

        latest_check_id = past_check_rows[0]["id"] if isinstance(past_check_rows[0], dict) else getattr(past_check_rows[0], "id", None)
        if not latest_check_id:
            return []

        latest_check = database.get_ecografo_quality_check(latest_check_id)
        if not latest_check or not getattr(latest_check, "probes", None):
            return []

        history = database.get_probe_history_for_device(device_id)
        from app.ecografo_quality_logic import determine_next_control_stage

        new_probes: List[EcografoQualityProbe] = []
        for old_probe in latest_check.probes:
            key = (old_probe.serial_number or old_probe.inventory or f"probe_order_{old_probe.probe_order}").strip()
            probe_history_count = len(history.get(key, []))
            next_stage = determine_next_control_stage(probe_history_count)

            new_p = EcografoQualityProbe(
                probe_order=old_probe.probe_order,
                probe_type=old_probe.probe_type,
                model=old_probe.model,
                serial_number=old_probe.serial_number,
                manufacturer=old_probe.manufacturer,
                inventory=old_probe.inventory,
                test_model=old_probe.test_model,
                preset=old_probe.preset,
                gain=old_probe.gain,
                power=old_probe.power,
                baseline=old_probe.baseline,
                control_stage=next_stage,
                overall_judgment="BUONO",
                controls=get_default_controls(),
                uuid=str(uuid.uuid4()),
            )
            new_probes.append(new_p)
        return new_probes

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Header compatto con Dati Apparecchio e Dati Verifica (in 2 colonne affiancate)
        header_card = QWidget()
        header_card.setStyleSheet("background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px;")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(24)

        # Colonna Sinistra: Apparecchio + Pulsante Storico
        left_box = QVBoxLayout()
        dev_desc = self.device_info.get("description", "Ecografo")
        dev_sn = self.device_info.get("serial_number", "N/D")
        dev_man = self.device_info.get("manufacturer", "N/D")
        dev_mod = self.device_info.get("model", "N/D")

        dev_info_text = f"<b>Apparecchio:</b> {dev_desc} &nbsp;|&nbsp; <b>S/N:</b> {dev_sn}<br/><span style='color:#64748b;'>Costruttore/Modello: {dev_man} / {dev_mod}</span>"
        dev_label = QLabel(dev_info_text)
        dev_label.setStyleSheet("font-size: 13px;")
        left_box.addWidget(dev_label)

        self.btn_open_history = QPushButton("📊 Storico CQ Sonde (Verifiche Passate)")
        self.btn_open_history.setToolTip("Consulta lo storico delle verifiche per questo dispositivo")
        self.btn_open_history.setMinimumHeight(30)
        self.btn_open_history.setStyleSheet("font-weight: bold; background: #e0f2fe; color: #0369a1; border: 1px solid #7dd3fc; border-radius: 4px; padding: 4px 10px;")
        self.btn_open_history.clicked.connect(self._open_history_dialog)
        left_box.addWidget(self.btn_open_history)

        header_layout.addLayout(left_box, 1)

        # Colonna Destra: General Form (Data, Tecnico, Note)
        gen_form = QFormLayout()
        gen_form.setSpacing(6)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        fix_calendar_popup(self.date_edit)
        self.date_edit.setDate(
            QDate.fromString(self.check.verification_date, "yyyy-MM-dd")
            if self.check.verification_date
            else QDate.currentDate()
        )
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setMinimumHeight(28)

        self.technician_edit = NoHoverFocusLineEdit(self.check.technician_name or self.technician_name or "")
        self.technician_edit.setMinimumHeight(28)

        self.notes_edit = NoHoverFocusLineEdit(self.check.notes or "")
        self.notes_edit.setPlaceholderText("Note generali sulla verifica")
        self.notes_edit.setMinimumHeight(28)

        gen_form.addRow("Data:", self.date_edit)
        gen_form.addRow("Tecnico:", self.technician_edit)
        gen_form.addRow("Note:", self.notes_edit)

        header_layout.addLayout(gen_form, 1)
        main_layout.addWidget(header_card)

        # 2. Barra di azione per le sonde + Schede Tab Sonde
        tabs_header = QHBoxLayout()
        tabs_title = QLabel("<h3 style='margin:0; color:#1e3a5f;'>Sonde sottoposte a verifica</h3>")
        tabs_header.addWidget(tabs_title)
        tabs_header.addStretch()

        self.add_probe_btn = QPushButton("+ Aggiungi Nuova Sonda")
        self.add_probe_btn.setCursor(Qt.PointingHandCursor)
        self.add_probe_btn.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 6px 16px; border-radius: 6px;")
        self.add_probe_btn.clicked.connect(self._add_probe)
        tabs_header.addWidget(self.add_probe_btn)
        main_layout.addLayout(tabs_header)

        self.probes_tabs = QTabWidget()
        self.probes_tabs.setTabsClosable(True)
        self.probes_tabs.setStyleSheet("QTabBar::tab { font-size: 13px; font-weight: bold; padding: 8px 16px; border-top-left-radius: 6px; border-top-right-radius: 6px; } QTabBar::tab:selected { background: #1e3a5f; color: white; }")
        self.probes_tabs.tabCloseRequested.connect(self._on_tab_close)
        self.probes_tabs.currentChanged.connect(lambda _: self.setFocus())
        main_layout.addWidget(self.probes_tabs, 1)

        # 3. Footer Bar (Pulsanti Salva/Annulla)
        footer_card = QWidget()
        footer_card.setStyleSheet("background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px;")
        footer_layout = QHBoxLayout(footer_card)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        footer_layout.addStretch()

        # Action Buttons
        if self.edit_mode and self.check and self.check.id:
            self.delete_btn = QPushButton("🗑️ Elimina Controllo CQ")
            self.delete_btn.setMinimumHeight(36)
            self.delete_btn.setCursor(Qt.PointingHandCursor)
            self.delete_btn.setStyleSheet("background-color: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; font-weight: bold; padding: 6px 16px; border-radius: 6px;")
            self.delete_btn.clicked.connect(self._on_delete_current_check)
            footer_layout.addWidget(self.delete_btn)

        self.cancel_btn = QPushButton("Annulla")
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.setStyleSheet("padding: 6px 18px; font-size: 13px;")
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("Salva Verifica CQ")
        self.save_btn.setMinimumHeight(36)
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setStyleSheet("background-color: #059669; color: white; font-weight: bold; padding: 6px 22px; font-size: 13px; border-radius: 6px;")
        self.save_btn.clicked.connect(self._on_save)

        footer_layout.addWidget(self.cancel_btn)
        footer_layout.addWidget(self.save_btn)

        main_layout.addWidget(footer_card)

        # Carica sonde esistenti o precompilate
        for probe in self.check.probes:
            self._add_probe_widget(probe)

        if not self.check.probes:
            self._add_probe()

    def _on_delete_current_check(self):
        if not self.check or not self.check.id:
            return
        reply = QMessageBox.question(
            self,
            "Conferma Eliminazione",
            "Sei sicuro di voler eliminare questo controllo qualità per sonde ecografo? L'operazione rimuoverà la verifica dal database.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            from app import services
            if services.delete_ecografo_quality_check(self.check.id):
                QMessageBox.information(self, "Eliminato", "Verifica di controllo qualità eliminata con successo.")
                self.accept()
            else:
                QMessageBox.critical(self, "Errore", "Impossibile eliminare la verifica.")

    def _add_probe(self):
        device_id = self.device_info.get("id", 0)
        history = database.get_probe_history_for_device(device_id) if device_id else {}
        past_check_rows = database.get_ecografo_quality_checks_for_device(device_id) if device_id else []
        
        probe_order = len(self.check.probes)

        latest_check = None
        if past_check_rows:
            latest_check_id = past_check_rows[0]["id"] if isinstance(past_check_rows[0], dict) else getattr(past_check_rows[0], "id", None)
            if latest_check_id:
                latest_check = database.get_ecografo_quality_check(latest_check_id)

        ref_probe = None
        if latest_check and getattr(latest_check, "probes", None):
            if probe_order < len(latest_check.probes):
                ref_probe = latest_check.probes[probe_order]

        probe_history_count = 0
        if ref_probe:
            key = (ref_probe.serial_number or ref_probe.inventory or f"probe_order_{ref_probe.probe_order}").strip()
            probe_history_count = len(history.get(key, []))
        elif history:
            probe_history_count = max((len(h) for h in history.values()), default=0)

        from app.ecografo_quality_logic import determine_next_control_stage
        auto_stage = determine_next_control_stage(probe_history_count)

        probe = EcografoQualityProbe(
            probe_order=probe_order,
            probe_type=ref_probe.probe_type if ref_probe else None,
            model=ref_probe.model if ref_probe else None,
            serial_number=ref_probe.serial_number if ref_probe else None,
            manufacturer=ref_probe.manufacturer if ref_probe else None,
            inventory=ref_probe.inventory if ref_probe else None,
            test_model=ref_probe.test_model if ref_probe else None,
            preset=ref_probe.preset if ref_probe else None,
            gain=ref_probe.gain if ref_probe else None,
            power=ref_probe.power if ref_probe else None,
            baseline=ref_probe.baseline if ref_probe else None,
            control_stage=auto_stage,
            overall_judgment="BUONO",
            controls=get_default_controls(),
            uuid=str(uuid.uuid4()),
        )
        self.check.probes.append(probe)
        self._add_probe_widget(probe)

    def _add_probe_widget(self, probe: EcografoQualityProbe):
        index = len(self.probe_widgets)
        widget = ProbeWidget(
            probe=probe,
            index=index,
            on_remove=self._remove_probe,
            parent=self,
        )
        self.probe_widgets.append(widget)

        tab_title = f"Sonda {index + 1}"
        if probe.model or probe.probe_type:
            tab_title = f"Sonda {index + 1} ({probe.model or probe.probe_type})"

        self.probes_tabs.addTab(widget, tab_title)
        self.probes_tabs.setCurrentWidget(widget)

    def _remove_probe(self, probe: EcografoQualityProbe):
        if probe in self.check.probes:
            self.check.probes.remove(probe)
        self._rebuild_tabs()

    def _on_tab_close(self, index: int):
        if len(self.probe_widgets) <= 1:
            QMessageBox.warning(self, "Attenzione", "Devi mantenere almeno una sonda nel controllo.")
            return
        widget = self.probe_widgets[index]
        reply = QMessageBox.question(
            self,
            "Conferma rimozione",
            f"Sei sicuro di voler rimuovere {self.probes_tabs.tabText(index)} da questo controllo?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._remove_probe(widget.probe)

    def _rebuild_tabs(self):
        self.probes_tabs.clear()
        self.probe_widgets.clear()
        for i, probe in enumerate(self.check.probes):
            probe.probe_order = i
            widget = ProbeWidget(
                probe=probe,
                index=i,
                on_remove=self._remove_probe,
                parent=self,
            )
            self.probe_widgets.append(widget)
            tab_title = f"Sonda {i + 1}"
            if probe.model or probe.probe_type:
                tab_title = f"Sonda {i + 1} ({probe.model or probe.probe_type})"
            self.probes_tabs.addTab(widget, tab_title)

    def _collect_data(self) -> bool:
        self.check.verification_date = self.date_edit.date().toString("yyyy-MM-dd")
        self.check.technician_name = self.technician_edit.text().strip() or None
        self.check.notes = self.notes_edit.text().strip() or None

        for widget in self.probe_widgets:
            widget.save_to_model()

        update_overall_status(self.check)
        return True

    def _recalculate_status(self):
        self._collect_data()
        for widget in self.probe_widgets:
            widget.refresh_controls()

    def _on_save(self):
        if not self._collect_data():
            return

        verified_probes = []
        excluded_widgets = []

        for widget in self.probe_widgets:
            if widget.include_checkbox.isChecked():
                widget.save_to_model()
                # Verifica se la sonda ha misurazioni o valori compilati
                has_measurements = any(
                    ctrl.value and ctrl.value.strip() and ctrl.value.strip() != "—"
                    for ctrl in widget.probe.controls
                )
                if has_measurements:
                    verified_probes.append(widget.probe)
                else:
                    excluded_widgets.append(widget)
            else:
                excluded_widgets.append(widget)

        if not verified_probes:
            QMessageBox.warning(
                self,
                "Attenzione",
                "Nessuna sonda risulta verificata. Compila le misurazioni su almeno una sonda prima di salvare.",
            )
            return

        # Avviso informativo sulle sonde non verificate escluse
        if excluded_widgets:
            probe_names = [f"• Sonda #{w.index + 1} ({w.probe.model or w.probe.probe_type or 'N/D'})" for w in excluded_widgets]
            names_str = "\n".join(probe_names)
            QMessageBox.information(
                self,
                "Avviso Sonde Non Verificate",
                f"Le seguenti sonde non sono state verificate in questa sessione e verranno escluse dal report finale:\n\n{names_str}",
                QMessageBox.Ok,
            )

        for i, p in enumerate(verified_probes):
            p.probe_order = i

        self.check.probes = verified_probes
        update_overall_status(self.check)
        self.accept()

    def _open_history_dialog(self):
        dlg = EcografoQualityHistoryDialog(device_info=self.device_info, parent=self)
        dlg.exec()

    def get_check(self) -> EcografoQualityCheck:
        return self.check


# ─── Dialog per lo Storico CQ Sonde per Dispositivo ──────────────────────────

class EcografoQualityHistoryDialog(QDialog):
    """Dialog per la visualizzazione dello storico dei controlli qualità sonde di un ecografo."""

    def __init__(self, device_info: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.device_info = device_info
        self.device_id = device_info.get("id")
        self.setWindowTitle(f"Storico Controlli Qualità Sonde — {device_info.get('description', 'Ecografo')}")
        self.resize(1000, 650)
        self._build_ui()

    def _build_ui(self):
        # Pulisci layout precedente se presente
        if self.layout() is not None:
            QWidget().setLayout(self.layout())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Header info ecografo
        info_group = QGroupBox("Dati Dispositivo Ecografo")
        info_layout = QHBoxLayout(info_group)
        info_layout.addWidget(QLabel(f"<b>Ecografo:</b> {self.device_info.get('description', '—')}"))
        info_layout.addWidget(QLabel(f"<b>Modello:</b> {self.device_info.get('model', '—')}"))
        info_layout.addWidget(QLabel(f"<b>S/N:</b> {self.device_info.get('serial_number', '—')}"))
        info_layout.addWidget(QLabel(f"<b>Inv. AMS:</b> {self.device_info.get('ams_inventory', '—')}"))
        layout.addWidget(info_group)

        tabs = QTabWidget()

        # Tab 1: Elenco Verifiche CQ
        checks_tab = QWidget()
        c_layout = QVBoxLayout(checks_tab)

        self.checks_table = QTableWidget()
        self.checks_table.setColumnCount(5)
        self.checks_table.setHorizontalHeaderLabels([
            "Data Verifica", "Codice", "Tecnico", "N. Sonde", "Azioni"
        ])
        self.checks_table.horizontalHeader().setStretchLastSection(True)
        self.checks_table.setAlternatingRowColors(True)

        checks = database.get_ecografo_quality_checks_for_device(self.device_id) if self.device_id else []
        self.checks_table.setRowCount(len(checks))

        for row_idx, check_dict in enumerate(checks):
            check_id = check_dict.get("id")
            full_check = database.get_ecografo_quality_check(check_id) if check_id else None

            v_date = check_dict.get("verification_date") or "—"
            v_code = check_dict.get("verification_code") or "—"
            tech_name = check_dict.get("technician_name") or "—"
            num_probes = len(full_check.probes) if full_check else 0

            self.checks_table.setItem(row_idx, 0, QTableWidgetItem(v_date))
            self.checks_table.setItem(row_idx, 1, QTableWidgetItem(v_code))
            self.checks_table.setItem(row_idx, 2, QTableWidgetItem(tech_name))
            self.checks_table.setItem(row_idx, 3, QTableWidgetItem(str(num_probes)))

            # Action buttons: Genera PDF ed Elimina
            act_widget = QWidget()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(4, 2, 4, 2)
            act_layout.setSpacing(6)

            btn_pdf = QPushButton("📄 Stampa PDF")
            btn_pdf.setCursor(Qt.PointingHandCursor)
            btn_pdf.setStyleSheet("font-weight: bold; background: #e0f2fe; color: #0369a1; border: 1px solid #7dd3fc; border-radius: 4px; padding: 4px 8px;")
            btn_pdf.clicked.connect(lambda _=False, cid=check_id: self._generate_pdf_for_check(cid))

            btn_del = QPushButton("🗑️ Elimina")
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet("font-weight: bold; background: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; border-radius: 4px; padding: 4px 8px;")
            btn_del.clicked.connect(lambda _=False, cid=check_id, code=v_code, dt=v_date: self._delete_check(cid, code, dt))

            act_layout.addWidget(btn_pdf)
            act_layout.addWidget(btn_del)
            self.checks_table.setCellWidget(row_idx, 4, act_widget)

        c_layout.addWidget(self.checks_table)
        tabs.addTab(checks_tab, "📋 Verifiche CQ Eseguite")

        # Tab 2: Timeline Sonde
        probes_tab = QWidget()
        p_layout = QVBoxLayout(probes_tab)

        probe_history = database.get_probe_history_for_device(self.device_id) if self.device_id else {}
        if not probe_history:
            p_layout.addWidget(QLabel("<i>Nessuna sonda registrata nello storico per questo dispositivo.</i>"))
        else:
            p_tabs = QTabWidget()
            for p_key, p_list in probe_history.items():
                p_widget = QWidget()
                pw_layout = QVBoxLayout(p_widget)

                table = QTableWidget()
                
                # Raccogli tutti gli stadi registrati per questa sonda
                found_stages = set()
                for p in p_list:
                    if p.control_stage:
                        found_stages.add(p.control_stage)
                
                def stage_key(st):
                    if not st:
                        return (3, "")
                    st_lower = st.lower()
                    if st_lower == "baseline":
                        return (0, 0)
                    if st_lower.startswith("controllo"):
                        try:
                            num = int(st.split()[-1])
                            return (1, num)
                        except Exception:
                            pass
                    return (2, st)

                stages_sorted = sorted(list(found_stages), key=stage_key)
                standard_stages = ["Baseline", "Controllo 1", "Controllo 2", "Controllo 3"]
                for s_st in standard_stages:
                    if s_st not in stages_sorted and len(stages_sorted) < 4:
                        stages_sorted.append(s_st)
                stages = sorted(list(set(stages_sorted)), key=stage_key)
                if not stages:
                    stages = ["Baseline"]

                table.setColumnCount(len(stages) + 1)
                table.setHorizontalHeaderLabels(["Parametro / Controllo"] + stages)

                def _get_ctrl_val(probe_obj, key_name):
                    if not probe_obj or not getattr(probe_obj, "controls", None):
                        return "—"
                    for ctrl in probe_obj.controls:
                        if ctrl.control_key == key_name:
                            return ctrl.value or "—"
                    return "—"

                from report_generator import (
                    _get_max_vertical_scarto,
                    _get_max_horizontal_scarto,
                    _get_dead_zone_value,
                    _get_mass_area,
                )

                controls_def = [
                    ("Data", lambda p: getattr(p, "verification_date", None) or "—"),
                    ("Ispezione visiva", lambda p: _get_ctrl_val(p, "ispezione_visiva")),
                    ("Uniformità", lambda p: _get_ctrl_val(p, "uniformita")),
                    ("Profondità max (cm)", lambda p: _get_ctrl_val(p, "profondita_max")),
                    ("Misure verticali (scarto max mm)", lambda p: _get_max_vertical_scarto(_get_ctrl_val(p, "misure_verticali")) or "—"),
                    ("Misure orizzontali (scarto max mm)", lambda p: _get_max_horizontal_scarto(_get_ctrl_val(p, "misure_orizzontali")) or "—"),
                    ("Zona Morta (mm)", lambda p: _get_dead_zone_value(_get_ctrl_val(p, "zona_morta")) or "—"),
                    ("Risoluzione assiale 3 cm (mm)", lambda p: _get_ctrl_val(p, "risoluzione_3cm_assiale")),
                    ("Risoluzione laterale 3 cm (mm)", lambda p: _get_ctrl_val(p, "risoluzione_3cm_laterale")),
                    ("Risoluzione assiale 11 cm (mm)", lambda p: _get_ctrl_val(p, "risoluzione_11cm_assiale")),
                    ("Risoluzione laterale 11 cm (mm)", lambda p: _get_ctrl_val(p, "risoluzione_11cm_laterale")),
                    ("Massa anecoica area (mm²)", lambda p: _get_mass_area(_get_ctrl_val(p, "massa_anecoica")) or "—"),
                    ("Massa iperecogena area (mm²)", lambda p: _get_mass_area(_get_ctrl_val(p, "massa_iperecogena")) or "—"),
                    ("Giudizio complessivo", lambda p: (p.overall_judgment or "—") if p else "—"),
                    ("Tecnico", lambda p: getattr(p, "technician_name", None) or "—"),
                ]
                table.setRowCount(len(controls_def))

                stage_map = {p.control_stage: p for p in p_list}
                for r_idx, (label, getter) in enumerate(controls_def):
                    table.setItem(r_idx, 0, QTableWidgetItem(label))
                    for c_idx, st in enumerate(stages):
                        p_obj = stage_map.get(st)
                        val = getter(p_obj) if p_obj else "—"
                        table.setItem(r_idx, c_idx + 1, QTableWidgetItem(str(val or "—")))

                pw_layout.addWidget(table)
                p_tabs.addTab(p_widget, f"Sonda {p_key}")
            p_layout.addWidget(p_tabs)

        tabs.addTab(probes_tab, "📈 Timeline Sonde Pluriennale")
        layout.addWidget(tabs)

        # Footer Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _generate_pdf_for_check(self, check_id: int):
        from report_generator import create_ecografo_quality_report
        check = database.get_ecografo_quality_check(check_id)
        if not check:
            QMessageBox.critical(self, "Errore", "Impossibile trovare il controllo qualità.")
            return

        ams_inv = (self.device_info.get('ams_inventory') or '').strip()
        serial_num = (self.device_info.get('serial_number') or '').strip()
        base_name = ams_inv if ams_inv else serial_num
        if not base_name:
            base_name = check.verification_code or f"CQ_{check_id}"
        safe_base_name = re.sub(r'[\\/*?:"<>|]', '_', base_name)
        default_filename = os.path.join(os.getcwd(), f"{safe_base_name} CQ.pdf")

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Salva Report Controllo Qualità Sonde Ecografo",
            default_filename,
            "PDF Files (*.pdf)",
        )
        if not filename:
            return

        try:
            check_info = database.get_ecografo_quality_check_with_device_info(check_id)
            dev_info = {
                "description": check_info.get("description", self.device_info.get("description", "N/D")),
                "serial_number": check_info.get("serial_number", self.device_info.get("serial_number", "N/D")),
                "manufacturer": check_info.get("manufacturer", self.device_info.get("manufacturer", "N/D")),
                "model": check_info.get("model", self.device_info.get("model", "N/D")),
                "department": check_info.get("department", self.device_info.get("department", "N/D")),
                "customer_inventory": check_info.get("customer_inventory", self.device_info.get("customer_inventory", "N/D")),
                "ams_inventory": check_info.get("ams_inventory", self.device_info.get("ams_inventory", "N/D")),
            }
            destination_info = {"name": check_info.get("destination_name", "N/D")}
            customer_info = {"name": check_info.get("customer_name", "N/D")}
            signature_data = database.get_signature_by_username(check.technician_username or "")
            parent_logo = getattr(self.parent(), "logo_path", None) if self.parent() else None
            report_settings = {"logo_path": parent_logo} if parent_logo else {}

            create_ecografo_quality_report(
                filename=filename,
                device_info=dev_info,
                customer_info=customer_info,
                destination_info=destination_info,
                check=check,
                technician_name=check.technician_name or "N/D",
                signature_data=signature_data,
                report_settings=report_settings,
            )
            QMessageBox.information(self, "Successo", f"Report generato con successo:\n{filename}")
        except Exception as e:
            logging.error(f"Errore generazione report CQ: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile generare il report:\n{e}")

    def _delete_check(self, check_id: int, v_code: str, v_date: str):
        reply = QMessageBox.question(
            self,
            "Conferma Eliminazione Controllo",
            f"Sei sicuro di voler eliminare la verifica '{v_code}' del {v_date}?\n\n"
            f"L'operazione rimuoverà la verifica dal database e dallo storico.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            from app import services
            success = services.delete_ecografo_quality_check(check_id)
            if success:
                QMessageBox.information(self, "Eliminato", f"Controllo qualità '{v_code}' eliminato con successo.")
                self._build_ui()
            else:
                QMessageBox.critical(self, "Errore", "Impossibile eliminare il controllo qualità.")

