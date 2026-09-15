# scratch/test_mainwindow_device_verifications.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow

def test_mainwindow_device_verifications():
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    assert hasattr(window, 'btn_view_verifications'), "MainWindow missing btn_view_verifications"
    assert hasattr(window, 'show_selected_device_verifications'), "MainWindow missing show_selected_device_verifications"
    assert hasattr(window, 'show_device_verifications'), "MainWindow missing show_device_verifications"

    # Initially disabled
    assert not window.btn_view_verifications.isEnabled(), "btn_view_verifications should be disabled initially"

    print("MainWindow verification button and methods verified successfully!")
    print("ALL MAIN WINDOW INTEGRATION TESTS PASSED! (100%)")

if __name__ == "__main__":
    test_mainwindow_device_verifications()
