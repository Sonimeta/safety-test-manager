# scratch/test_device_verifications_dialog.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from app.ui.dialogs.device_verifications_dialog import DeviceVerificationsDialog
import database
from app import services

def test_device_verifications_dialog():
    app = QApplication.instance() or QApplication(sys.argv)

    # Fetch a device
    customers = database.get_all_customers()
    if not customers:
        print("No customers in DB, skipping full load test")
        return
    cust_id = customers[0]['id']
    devices = database.get_devices_for_customer(cust_id)
    if not devices:
        print("No devices in DB, skipping full load test")
        return
    device_id = devices[0]['id']

    dialog = DeviceVerificationsDialog(device_id=device_id)
    assert dialog.device_id == device_id
    assert dialog.tabs.count() == 4
    assert dialog.btn_view is not None
    assert dialog.btn_pdf is not None
    assert dialog.btn_print is not None
    assert dialog.btn_edit is not None
    assert dialog.btn_delete is not None

    print(f"Verified DeviceVerificationsDialog successfully for device_id={device_id}")
    print(f"Tabs count: {dialog.tabs.count()}")
    print(f"Summary badge text: {dialog.summary_badge_label.text().encode('ascii', errors='replace').decode('ascii')}")

    print("ALL DEVICE VERIFICATIONS DIALOG TESTS PASSED! (100%)")

if __name__ == "__main__":
    test_device_verifications_dialog()
