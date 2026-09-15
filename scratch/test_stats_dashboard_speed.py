# scratch/test_stats_dashboard_speed.py
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
import database
from app import services
from app.ui.dialogs.stats_dashboard_dialog import StatsDashboardDialog

def test_stats_dashboard_speed():
    app = QApplication.instance() or QApplication(sys.argv)

    # 1. Run migrations
    t0 = time.perf_counter()
    database.migrate_database()
    t_mig = time.perf_counter() - t0
    print(f"Migration completed in {t_mig*1000:.2f}ms")

    # 2. Test consolidated summary stats
    t0 = time.perf_counter()
    summary = database.get_dashboard_summary_stats()
    t_sum = time.perf_counter() - t0
    print(f"Consolidated get_dashboard_summary_stats took {t_sum*1000:.2f}ms: {summary}")
    assert 'customers' in summary
    assert 'devices_active' in summary
    assert 'verifications_electrical' in summary

    # 3. Test electrical and functional stats
    el_stats = database.get_electrical_verification_stats()
    fn_stats = database.get_functional_verification_stats()
    print(f"Electrical stats: {el_stats}")
    print(f"Functional stats: {fn_stats}")
    assert 'totale' in el_stats
    assert 'conformi' in el_stats

    # 4. Test StatsDashboardDialog instantiation & lazy load
    t0 = time.perf_counter()
    dlg = StatsDashboardDialog()
    t_init = time.perf_counter() - t0
    print(f"StatsDashboardDialog instantiated in {t_init*1000:.2f}ms")

    # Trigger initial load
    dlg._initial_load()
    assert 0 in dlg._loaded_tabs
    assert 1 not in dlg._loaded_tabs  # Tab 1 should not be loaded yet!
    assert 2 not in dlg._loaded_tabs  # Tab 2 should not be loaded yet!

    # Switch to Tab 1 (Conformità)
    t0 = time.perf_counter()
    dlg.tabs.setCurrentIndex(1)
    dlg._on_tab_switched(1)
    t_tab1 = time.perf_counter() - t0
    print(f"Tab 1 (Conformità) loaded in {t_tab1*1000:.2f}ms")
    assert 1 in dlg._loaded_tabs

    # Switch to Tab 2 (Andamento Mensile)
    t0 = time.perf_counter()
    dlg.tabs.setCurrentIndex(2)
    dlg._on_tab_switched(2)
    t_tab2 = time.perf_counter() - t0
    print(f"Tab 2 (Andamento Mensile) loaded in {t_tab2*1000:.2f}ms")
    assert 2 in dlg._loaded_tabs

    # Switch to Tab 5 (Classifiche)
    t0 = time.perf_counter()
    dlg.tabs.setCurrentIndex(5)
    dlg._on_tab_switched(5)
    t_tab5 = time.perf_counter() - t0
    print(f"Tab 5 (Classifiche) loaded in {t_tab5*1000:.2f}ms")
    assert 5 in dlg._loaded_tabs

    # Switch to Tab 6 (Dashboard Operativa)
    t0 = time.perf_counter()
    dlg.tabs.setCurrentIndex(6)
    dlg._on_tab_switched(6)
    t_tab6 = time.perf_counter() - t0
    print(f"Tab 6 (Dashboard Operativa) loaded in {t_tab6*1000:.2f}ms")
    assert 6 in dlg._loaded_tabs

    print("ALL STATS DASHBOARD PERFORMANCE TESTS PASSED! (100%)")

if __name__ == "__main__":
    test_stats_dashboard_speed()
