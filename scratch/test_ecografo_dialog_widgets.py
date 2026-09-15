# scratch/test_ecografo_dialog_widgets.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from app.ui.widgets import NoHoverFocusLineEdit, NoHoverFocusComboBox
from app.ui.dialogs.ecografo_quality_dialog import (
    EcografoQualityDialog,
    InspectionControlWidget,
    MaxDepthControlWidget,
    VerticalMeasuresWidget,
    HorizontalMeasuresWidget,
    DeadZoneWidget,
    Resolution3cmWidget,
    Resolution11cmWidget,
    MassAnalysisWidget,
    ProbeWidget,
)
from app.ecografo_quality_models import EcografoQualityCheck, EcografoQualityProbe
from app.ecografo_quality_logic import get_default_controls

def test_widgets():
    app = QApplication.instance() or QApplication(sys.argv)

    probe = EcografoQualityProbe(
        probe_order=0,
        probe_type="Convex",
        model="C5-2",
        serial_number="SN123",
        controls=get_default_controls(),
    )

    probe_widget = ProbeWidget(probe, index=0, on_remove=lambda p: None)

    # Check ProbeWidget header fields
    assert isinstance(probe_widget.type_edit, NoHoverFocusLineEdit)
    assert isinstance(probe_widget.model_edit, NoHoverFocusLineEdit)
    assert isinstance(probe_widget.serial_edit, NoHoverFocusLineEdit)
    assert isinstance(probe_widget.stage_combo, NoHoverFocusComboBox)
    assert isinstance(probe_widget.judgment_combo, NoHoverFocusComboBox)

    # Check custom control widgets
    for w in probe_widget.custom_widgets:
        if isinstance(w, InspectionControlWidget):
            assert isinstance(w.combo, NoHoverFocusComboBox)
            assert isinstance(w.notes_edit, NoHoverFocusLineEdit)
        elif isinstance(w, MaxDepthControlWidget):
            assert isinstance(w.val_edit, NoHoverFocusLineEdit)
            assert isinstance(w.notes_edit, NoHoverFocusLineEdit)
        elif isinstance(w, VerticalMeasuresWidget):
            for _, edit, _ in w.rows_edits:
                assert isinstance(edit, NoHoverFocusLineEdit)
        elif isinstance(w, HorizontalMeasuresWidget):
            for _, edit in w.rows_edits:
                assert isinstance(edit, NoHoverFocusLineEdit)
        elif isinstance(w, DeadZoneWidget):
            assert isinstance(w.targets_edit, NoHoverFocusLineEdit)
            assert isinstance(w.dead_zone_edit, NoHoverFocusLineEdit)
        elif isinstance(w, (Resolution3cmWidget, Resolution11cmWidget)):
            assert isinstance(w.axial_combo, NoHoverFocusComboBox)
            assert isinstance(w.lateral_combo, NoHoverFocusComboBox)
        elif isinstance(w, MassAnalysisWidget):
            assert isinstance(w.oriz_edit, NoHoverFocusLineEdit)
            assert isinstance(w.vert_edit, NoHoverFocusLineEdit)

    # Check main dialog fields
    dlg = EcografoQualityDialog(
        device_info={"id": 1, "description": "Ecografo Test", "model": "TestModel"},
        check=EcografoQualityCheck(device_id=1, verification_date="2026-08-27", probes=[probe]),
        technician_name="Mario Rossi",
    )
    assert isinstance(dlg.technician_edit, NoHoverFocusLineEdit)
    assert isinstance(dlg.notes_edit, NoHoverFocusLineEdit)

    print("ALL ECOGRAFO QUALITY DIALOG WIDGETS VERIFIED AS NoHoverFocus! (100%)")

if __name__ == "__main__":
    test_widgets()
