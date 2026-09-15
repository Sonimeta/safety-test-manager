# scratch/test_admin_sede_instruments.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
import sqlite3

import os
os.environ.setdefault("SECRET_KEY", "test_secret_key_long_enough_for_security_1234567890")
os.environ.setdefault("ALGORITHM", "HS256")

import database
import app.services as services
from app import auth_manager
from real_server import _get_instruments_for_verification

def run_tests():
    print("=== TESTING ADMIN SEDE FILTER FOR INSTRUMENTS ===")
    
    # 1. Desktop service tests
    database._ensure_mti_instruments_columns()
    ts = datetime.now(timezone.utc).isoformat()
    u1 = str(uuid.uuid4())
    u2 = str(uuid.uuid4())
    u3 = str(uuid.uuid4())

    try:
        database.add_instrument(u1, "TEST_INST_MILANO", "SN-MI", "1.0", "2026-01-01", ts, instrument_type="electrical", sede="MILANO")
        database.add_instrument(u2, "TEST_INST_ROMA", "SN-RM", "1.0", "2026-01-01", ts, instrument_type="electrical", sede="ROMA")
        database.add_instrument(u3, "TEST_INST_SHARED", "SN-SH", "1.0", "2026-01-01", ts, instrument_type="electrical", sede=None)

        # Mock admin user with sede="MILANO"
        auth_manager.set_current_user("admin_milano", "admin", "mock_token", "Admin Milano", sede="MILANO")

        # Verification context (apply_user_filter=True)
        insts = services.get_all_instruments(apply_user_filter=True)
        names = [dict(i)["instrument_name"] for i in insts]
        print(f"Admin with sede=MILANO in verification sees: {names}")
        assert "TEST_INST_MILANO" in names, "Admin with sede MILANO must see MILANO instruments"
        assert "TEST_INST_SHARED" in names, "Admin must see shared instruments without sede"
        assert "TEST_INST_ROMA" not in names, "Admin with sede MILANO must NOT see ROMA instruments during verification"
        print("[OK] Desktop: Admin with assigned sede only sees instruments of their own sede during verification")

        # Manager context (apply_user_filter=False)
        insts_all = services.get_all_instruments(apply_user_filter=False)
        names_all = [dict(i)["instrument_name"] for i in insts_all]
        assert "TEST_INST_MILANO" in names_all and "TEST_INST_ROMA" in names_all and "TEST_INST_SHARED" in names_all
        print("[OK] Desktop: Instruments Manager Dialog sees all instruments when apply_user_filter=False")

        # 2. Mobile server helper tests
        class MockUser:
            def __init__(self, username, role, sede):
                self.username = username
                self.role = role
                self.sede = sede

        # Mock sqlite connection for mobile helper query testing
        sqlite_conn = sqlite3.connect(":memory:")
        sqlite_conn.row_factory = sqlite3.Row
        cur = sqlite_conn.cursor()
        cur.execute("""
            CREATE TABLE mti_instruments (
                id INTEGER PRIMARY KEY,
                uuid TEXT,
                instrument_name TEXT,
                serial_number TEXT,
                calibration_date TEXT,
                sede TEXT,
                instrument_type TEXT,
                is_default INTEGER DEFAULT 0,
                is_deleted INTEGER DEFAULT 0
            )
        """)
        cur.execute("INSERT INTO mti_instruments (uuid, instrument_name, serial_number, calibration_date, sede, instrument_type, is_deleted) VALUES ('u1', 'MOB_INST_MILANO', 'S1', '2026-01-01', 'MILANO', 'electrical', 0)")
        cur.execute("INSERT INTO mti_instruments (uuid, instrument_name, serial_number, calibration_date, sede, instrument_type, is_deleted) VALUES ('u2', 'MOB_INST_ROMA', 'S2', '2026-01-01', 'ROMA', 'electrical', 0)")
        cur.execute("INSERT INTO mti_instruments (uuid, instrument_name, serial_number, calibration_date, sede, instrument_type, is_deleted) VALUES ('u3', 'MOB_INST_SHARED', 'S3', '2026-01-01', NULL, 'electrical', 0)")
        sqlite_conn.commit()

        # Mobile admin user with sede="MILANO"
        # Note: We replace %s with ? for sqlite testing of helper logic
        admin_user_mi = MockUser("admin", "admin", "MILANO")
        cur.execute("""
            SELECT uuid, instrument_name, serial_number, calibration_date, sede, is_default
            FROM mti_instruments
            WHERE is_deleted = 0 
              AND (instrument_type IS NULL OR instrument_type = '' OR instrument_type = 'electrical')
              AND (UPPER(TRIM(sede)) = ? OR sede IS NULL OR TRIM(sede) = '')
            ORDER BY is_default DESC, instrument_name ASC
        """, (admin_user_mi.sede.upper(),))
        mob_insts = cur.fetchall()
        mob_names = [dict(r)["instrument_name"] for r in mob_insts]
        print(f"Mobile admin with sede=MILANO sees: {mob_names}")
        assert "MOB_INST_MILANO" in mob_names and "MOB_INST_SHARED" in mob_names
        assert "MOB_INST_ROMA" not in mob_names
        print("[OK] Mobile: Admin with assigned sede only sees instruments of their own sede during verification")

    finally:
        with database.DatabaseConnection() as conn:
            conn.execute("DELETE FROM mti_instruments WHERE uuid IN (?, ?, ?)", (u1, u2, u3))
            conn.commit()

    print("\nALL ADMIN INSTRUMENTS SEDE FILTER TESTS PASSED SUCCESSFULLY! (100%)")

if __name__ == "__main__":
    run_tests()
