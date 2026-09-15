# scratch/test_destination_excel_export.py
import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from app import services
from app.workers.table_export_worker import TableExportWorker
import pandas as pd

def test_destination_excel_export():
    # 1. Get destination ID from database to test with real data
    with database.DatabaseConnection() as conn:
        dest = conn.execute("SELECT id, name FROM destinations WHERE is_deleted = 0 LIMIT 1").fetchone()
        if not dest:
            print("No destination found, skipping real db query test")
            return
        dest_id = dest['id']
        dest_name = dest['name']
        print(f"Testing with destination: ID={dest_id}, Name='{dest_name}'")

    # 2. Test database query get_devices_with_last_verification_for_destination
    rows = database.get_devices_with_last_verification_for_destination(dest_id)
    print(f"Retrieved {len(rows)} devices for destination {dest_id}")
    if rows:
        r0 = dict(rows[0])
        print("Sample row fields:", list(r0.keys()))
        print("Sample row:", r0)
        assert 'ESITO' in r0
        assert 'ESITO VERIFICHE FUNZIONALI' in r0
        assert 'NOTE' in r0
        assert 'DESTINAZIONE' in r0

    # 3. Test get_devices_with_verifications_for_destination_by_date_range
    rows_range = database.get_devices_with_verifications_for_destination_by_date_range(dest_id, "2020-01-01", "2030-12-31")
    print(f"Retrieved {len(rows_range)} devices for date range query")
    if rows_range:
        r_range0 = dict(rows_range[0])
        assert 'ESITO' in r_range0
        assert 'ESITO VERIFICHE FUNZIONALI' in r_range0
        assert 'NOTE' in r_range0
        assert 'DESTINAZIONE' in r_range0

    # 4. Test TableExportWorker running and producing valid excel file
    temp_dir = tempfile.mkdtemp()
    excel_path = os.path.join(temp_dir, "test_export.xlsx")
    
    worker = TableExportWorker(dest_id, excel_path, "2020-01-01", "2030-12-31")
    worker.run()
    
    assert os.path.exists(excel_path)
    print("Excel file generated successfully at:", excel_path)
    
    # Read back generated excel
    df_read = pd.read_excel(excel_path, sheet_name='Verifiche')
    print("Exported excel columns:", df_read.columns.tolist())
    print("Exported excel shape:", df_read.shape)
    
    assert "ESITO" in df_read.columns
    assert "ESITO VERIFICHE FUNZIONALI" in df_read.columns
    assert "NOTE" in df_read.columns

    print("ALL DESTINATION EXCEL EXPORT TESTS PASSED! (100%)")

if __name__ == "__main__":
    test_destination_excel_export()
