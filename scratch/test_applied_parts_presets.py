# scratch/test_applied_parts_presets.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMessageBox
from unittest.mock import patch
import database
from app import services
from app.ui.dialogs.detail_dialogs import DeviceDialog
from app.ui.dialogs.applied_parts_presets_dialog import AppliedPartsPresetsDialog

def test_applied_parts_presets():
    app = QApplication.instance() or QApplication(sys.argv)
    
    # Mock message boxes to avoid modal dialog blocking during tests
    QMessageBox.information = lambda *args, **kwargs: QMessageBox.Ok
    QMessageBox.warning = lambda *args, **kwargs: QMessageBox.Ok
    QMessageBox.critical = lambda *args, **kwargs: QMessageBox.Ok
    QMessageBox.question = lambda *args, **kwargs: QMessageBox.Yes
    
    # 1. Run migrations
    database.migrate_database()
    
    # 2. Check initial presets count (or existing count)
    presets_initial = services.get_applied_parts_presets()
    print(f"Existing presets count: {len(presets_initial)}")

    # 3. Create a test preset via services
    preset_name = "Test Elettrobisturi Standard"
    preset_parts = [
        {"name": "MANIPOLO MONOPOLARE", "part_type": "BF"},
        {"name": "PINZA BIPOLARE", "part_type": "BF"},
        {"name": "ELETTRODO NEUTRO", "part_type": "BF"}
    ]
    preset_id = services.save_applied_parts_preset(
        name=preset_name,
        parts=preset_parts,
        description="Preset di test per elettrobisturi"
    )
    print(f"Created preset with ID: {preset_id}")
    assert preset_id > 0

    # 4. Verify retrieval
    retrieved = services.get_applied_parts_preset_by_id(preset_id)
    assert retrieved is not None
    assert retrieved['name'] == preset_name
    assert len(retrieved['parts']) == 3
    assert retrieved['parts'][0]['name'] == "MANIPOLO MONOPOLARE"
    assert retrieved['parts'][0]['part_type'] == "BF"

    # 5. Test DeviceDialog integration
    dev_dialog = DeviceDialog(customer_id=1, destination_id=1)
    
    # Verify combo contains the test preset
    found_in_combo = False
    for i in range(dev_dialog.pa_preset_combo.count()):
        data = dev_dialog.pa_preset_combo.itemData(i)
        if data and data.get('id') == preset_id:
            dev_dialog.pa_preset_combo.setCurrentIndex(i)
            found_in_combo = True
            break
    assert found_in_combo, "Preset not found in DeviceDialog combo"

    # Apply preset
    dev_dialog._apply_selected_preset()
    assert len(dev_dialog.applied_parts) == 3
    assert dev_dialog.applied_parts[0].name == "MANIPOLO MONOPOLARE"
    assert dev_dialog.applied_parts[0].code == "RA"
    assert dev_dialog.applied_parts[1].code == "LL"
    assert dev_dialog.applied_parts[2].code == "LA"
    assert dev_dialog.pa_table.rowCount() == 3
    print("DeviceDialog successfully loaded preset and populated PA table with codes RA, LL, LA!")

    # 6. Test AppliedPartsPresetsDialog
    manager_dlg = AppliedPartsPresetsDialog(select_preset_id=preset_id)
    assert manager_dlg.name_edit.text() == preset_name
    assert manager_dlg.parts_table.rowCount() == 3
    
    # Add a part in manager dialog and save
    manager_dlg.new_pa_name.setText("PEDALE DOPPIO")
    manager_dlg.new_pa_type.setCurrentText("B")
    manager_dlg._add_part_row()
    assert manager_dlg.parts_table.rowCount() == 4
    
    manager_dlg._save_current_preset()
    updated = services.get_applied_parts_preset_by_id(preset_id)
    assert len(updated['parts']) == 4
    print("AppliedPartsPresetsDialog successfully updated preset to 4 parts!")

    # 7. Clean up test preset
    services.delete_applied_parts_preset(preset_id)
    assert services.get_applied_parts_preset_by_id(preset_id) is None
    print("Preset successfully deleted!")

    print("ALL APPLIED PARTS PRESETS TESTS PASSED! (100%)")

if __name__ == "__main__":
    test_applied_parts_presets()
