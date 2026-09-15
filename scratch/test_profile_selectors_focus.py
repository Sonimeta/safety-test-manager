# scratch/test_profile_selectors_focus.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QWheelEvent
from app.ui.main_window import MainWindow

def test_profile_selectors_focus():
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()

    # Check focus policy
    assert window.profile_selector.focusPolicy() == Qt.NoFocus
    assert window.functional_profile_selector.focusPolicy() == Qt.NoFocus
    print("Focus policy is Qt.NoFocus for both profile selectors!")

    # Populate items to test wheel event
    window.profile_selector.addItem("Profile A", "A")
    window.profile_selector.addItem("Profile B", "B")
    window.profile_selector.setCurrentIndex(0)

    # Simulate wheel event
    wheel_ev = QWheelEvent(
        QPoint(10, 10),
        QPoint(10, 10),
        QPoint(0, 120),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False
    )
    window.profile_selector.wheelEvent(wheel_ev)
    assert not wheel_ev.isAccepted()
    assert window.profile_selector.currentIndex() == 0

    print("Wheel event correctly ignored on profile_selector!")

    window.functional_profile_selector.addItem("Func A", "FA")
    window.functional_profile_selector.addItem("Func B", "FB")
    window.functional_profile_selector.setCurrentIndex(0)

    wheel_ev2 = QWheelEvent(
        QPoint(10, 10),
        QPoint(10, 10),
        QPoint(0, 120),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False
    )
    window.functional_profile_selector.wheelEvent(wheel_ev2)
    assert not wheel_ev2.isAccepted()
    assert window.functional_profile_selector.currentIndex() == 0

    print("Wheel event correctly ignored on functional_profile_selector!")
    print("ALL PROFILE SELECTORS AUTOFOCUS & WHEEL TESTS PASSED! (100%)")

if __name__ == "__main__":
    test_profile_selectors_focus()
