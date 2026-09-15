# scratch/test_device_table_color.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app.ui.dialogs.manager_dialogs import DbManagerDialog

def test_device_table_coloring():
    app = QApplication.instance() or QApplication(sys.argv)
    
    dialog = DbManagerDialog(role='admin')
    import database
    mock_data = [
        {
            'id': 101,
            'destination_id': 1,
            'description': 'Device Conforme',
            'department': 'Cardiologia',
            'serial_number': 'SN001',
            'manufacturer': 'Brand A',
            'model': 'Model A',
            'customer_inventory': 'INV1',
            'ams_inventory': 'AMS1',
            'verification_interval': 12,
            'status': 'active',
            'last_verification_date': '2026-01-10',
            'last_verification_outcome': 'CONFORME'
        },
        {
            'id': 102,
            'destination_id': 1,
            'description': 'Device Conforme Con Annotazione',
            'department': 'Radiologia',
            'serial_number': 'SN002',
            'manufacturer': 'Brand B',
            'model': 'Model B',
            'customer_inventory': 'INV2',
            'ams_inventory': 'AMS2',
            'verification_interval': 12,
            'status': 'active',
            'last_verification_date': '2026-01-15',
            'last_verification_outcome': 'CONFORME CON ANNOTAZIONE'
        },
        {
            'id': 103,
            'destination_id': 1,
            'description': 'Device Non Conforme',
            'department': 'Chirurgia',
            'serial_number': 'SN003',
            'manufacturer': 'Brand C',
            'model': 'Model C',
            'customer_inventory': 'INV3',
            'ams_inventory': 'AMS3',
            'verification_interval': 12,
            'status': 'active',
            'last_verification_date': '2026-01-20',
            'last_verification_outcome': 'NON CONFORME'
        }
    ]
    database.get_devices_with_last_verification = lambda: mock_data
    
    dialog.load_devices_table(1)
    
    # Search table rows by Device ID in column 0
    row_map = {}
    for r in range(dialog.device_table.rowCount()):
        dev_id = int(dialog.device_table.item(r, 0).text())
        color = dialog.device_table.item(r, 1).data(Qt.UserRole + 1)
        row_map[dev_id] = color

    print("Resulting row colors by dev_id:", row_map)
    assert row_map[101].lower() == "#0b5f1e"  # CONFORME -> Green
    assert row_map[102].lower() == "#d97706"  # CONFORME CON ANNOTAZIONE -> Orange
    assert row_map[103].lower() == "#fc0217"  # NON CONFORME -> Red
    
    print("ALL DEVICE TABLE COLORING TESTS PASSED! (100%)")

if __name__ == "__main__":
    test_device_table_coloring()
