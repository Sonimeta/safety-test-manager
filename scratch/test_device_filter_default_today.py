# scratch/test_device_filter_default_today.py
import sys
import os
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow

def test_device_filter_default_today():
    app = QApplication.instance() or QApplication(sys.argv)
    
    window = MainWindow()
    
    print("device_filter_start_date:", window.device_filter_start_date)
    print("device_filter_end_date:", window.device_filter_end_date)
    print("Today is:", date.today())
    
    assert window.device_filter_start_date == date.today()
    assert window.device_filter_end_date == date.today()
    
    label = window._get_device_filter_period_label()
    print("Filter label:", label)
    assert label == date.today().strftime('%d/%m/%Y')
    
    tooltip = getattr(window, "device_period_button", None).toolTip()
    print("Button tooltip:", tooltip)
    assert date.today().strftime('%d/%m/%Y') in tooltip
    
    print("ALL DEVICE FILTER DEFAULT TODAY TESTS PASSED! (100%)")

if __name__ == "__main__":
    test_device_filter_default_today()
