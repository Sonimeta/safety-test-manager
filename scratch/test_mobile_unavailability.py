# scratch/test_mobile_unavailability.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
import database

def run_tests():
    print("Testing Mobile Unavailability Reports logic...")

    # 1. Setup mock customer & destination & device
    cust_uuid = str(uuid.uuid4())
    dest_uuid = str(uuid.uuid4())
    dev_uuid = str(uuid.uuid4())
    ts_now = datetime.now(timezone.utc).isoformat()

    database.add_customer(cust_uuid, "CLIENTE TEST UNAVAIL", "VIA TEST 1", "", "", ts_now)
    with database.DatabaseConnection() as conn:
        cust_row = conn.execute("SELECT id FROM customers WHERE uuid = ?", (cust_uuid,)).fetchone()
        cust_id = cust_row["id"]

    database.add_destination(dest_uuid, cust_id, "REPARTO CARDIOLOGIA", "PIANO 1", ts_now)
    with database.DatabaseConnection() as conn:
        dest_row = conn.execute("SELECT id FROM destinations WHERE uuid = ?", (dest_uuid,)).fetchone()
        dest_id = dest_row["id"]

    database.add_device(
        uuid=dev_uuid, destination_id=dest_id, serial='SN_DEF_999', desc='DEFIBRILLATORE TEST',
        mfg='PHILIPS', model='HEARTSTART', department='TERAPIA INTENSIVA', applied_parts=[],
        customer_inv='INV_999', ams_inv='AMS_999', verification_interval=12,
        default_profile_key=None, default_functional_profile_key=None, timestamp=ts_now
    )
    with database.DatabaseConnection() as conn:
        dev_row = conn.execute("SELECT id FROM devices WHERE uuid = ?", (dev_uuid,)).fetchone()
        dev_id = dev_row["id"]

    print(f"[OK] Dispositivo creato con ID {dev_id}, UUID {dev_uuid}")

    # 2. Create unavailability report
    rep_uuid = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    with database.DatabaseConnection() as conn:
        conn.execute("""
            INSERT INTO device_unavailability_reports
                (uuid, device_id, destination_id, period_start, period_end, report_date, reason, technician_name, technician_username, created_at, last_modified, is_synced, is_deleted)
            VALUES (?, ?, ?, '2026-08-25', '2026-08-25', '2026-08-25', 'Apparecchio in uso / non disponibile (Paziente collegato)', 'TECNICO ROSSI', 'rossi', ?, ?, 1, 0)
        """, (rep_uuid, dev_id, dest_id, ts, ts))
        conn.commit()

    print(f"[OK] Segnalazione creata con UUID {rep_uuid}")

    # 3. Verify query for device detail
    with database.DatabaseConnection() as conn:
        row = conn.execute("""
            SELECT * FROM device_unavailability_reports WHERE device_id = ? AND is_deleted = 0
        """, (dev_id,)).fetchone()
        assert row is not None, "Segnalazione attiva attesa"
        assert "Apparecchio in uso" in row["reason"]
        print(f"[OK] Segnalazione recuperata correttamente: {dict(row)}")

    # 4. Soft-delete unavailability report
    with database.DatabaseConnection() as conn:
        conn.execute("UPDATE device_unavailability_reports SET is_deleted = 1 WHERE uuid = ?", (rep_uuid,))
        conn.commit()

    with database.DatabaseConnection() as conn:
        row_after = conn.execute("SELECT * FROM device_unavailability_reports WHERE device_id = ? AND is_deleted = 0", (dev_id,)).fetchone()
        assert row_after is None, "Nessuna segnalazione attiva attesa dopo delete"
        print("[OK] Soft delete verificato con successo")

    # Cleanup
    with database.DatabaseConnection() as conn:
        conn.execute("DELETE FROM device_unavailability_reports WHERE uuid = ?", (rep_uuid,))
        conn.execute("DELETE FROM devices WHERE id = ?", (dev_id,))
        conn.execute("DELETE FROM destinations WHERE id = ?", (dest_id,))
        conn.execute("DELETE FROM customers WHERE id = ?", (cust_id,))
        conn.commit()

    print("[OK] Cleanup database completato")
    print("\nTUTTI I TEST DELLA SEGNALAZIONE NON DISPONIBILE MOBILE SONO PASSATI CON SUCCESSO!")

if __name__ == "__main__":
    run_tests()
