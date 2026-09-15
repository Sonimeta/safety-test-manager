# scratch/test_mainwindow_dashboard.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from app import services
from app.ui.main_window import MainWindow

def test_mainwindow_dashboard():
    app = QApplication.instance() or QApplication(sys.argv)
    
    # 1. Test services.get_verification_stats()
    stats = services.get_verification_stats()
    print("services.get_verification_stats():", stats)
    assert stats['totale'] > 0
    assert stats['verifiche_elettriche'] > 0
    assert stats['verifiche_funzionali'] > 0
    assert 'conformi' in stats
    assert 'non_conformi' in stats

    # 2. Test MainWindow dashboard update
    window = MainWindow()
    window.update_dashboard()
    print("Total card text:", window.total_card.text())
    print("Conformi card text:", window.conformi_card.text())
    print("Non conformi card text:", window.non_conformi_card.text())

    assert f"{stats['totale']:,}" in window.total_card.text()
    assert f"{stats['verifiche_elettriche']:,}" in window.conformi_card.text()
    assert f"{stats['verifiche_funzionali']:,}" in window.non_conformi_card.text()

    print("ALL MAIN WINDOW DASHBOARD TESTS PASSED! (100%)")

if __name__ == "__main__":
    test_mainwindow_dashboard()
