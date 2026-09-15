# scratch/test_mobile_system_verifications.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import json
import tempfile
from datetime import datetime, timezone
import database
import server_report_generator as srg

def run_tests():
    print("Testing Mobile System Verifications & Report Generation...")

    cust_uuid = str(uuid.uuid4())
    dest_uuid = str(uuid.uuid4())
    dev1_uuid = str(uuid.uuid4())
    dev2_uuid = str(uuid.uuid4())
    inst_uuid = str(uuid.uuid4())
    ts_now = datetime.now(timezone.utc).isoformat()

    # 1. Anagrafiche
    database.add_customer(cust_uuid, "OSPEDALE SAN RAFFAELE", "VIA OLGETTINA 60", "", "", ts_now)
    with database.DatabaseConnection() as conn:
        cust_id = conn.execute("SELECT id FROM customers WHERE uuid = ?", (cust_uuid,)).fetchone()["id"]

    database.add_destination(dest_uuid, cust_id, "BLOCCO OPERATORIO SALA 1", "PIANO 2", ts_now)
    with database.DatabaseConnection() as conn:
        dest_id = conn.execute("SELECT id FROM destinations WHERE uuid = ?", (dest_uuid,)).fetchone()["id"]

    database.add_device(
        uuid=dev1_uuid, destination_id=dest_id, serial='SN_LAPARO_01', desc='COLONNA LAPAROSCOPICA',
        mfg='STORZ', model='IMAGE 1', department='CHIRURGIA', applied_parts=[],
        customer_inv='INV_01', ams_inv='AMS_01', verification_interval=12,
        default_profile_key=None, default_functional_profile_key=None, timestamp=ts_now
    )
    database.add_device(
        uuid=dev2_uuid, destination_id=dest_id, serial='SN_INSUF_01', desc='INSUFFLATORE CO2',
        mfg='STORZ', model='THERMOFLATOR', department='CHIRURGIA', applied_parts=[],
        customer_inv='INV_02', ams_inv='AMS_02', verification_interval=12,
        default_profile_key=None, default_functional_profile_key=None, timestamp=ts_now
    )
    with database.DatabaseConnection() as conn:
        dev1_id = conn.execute("SELECT id FROM devices WHERE uuid = ?", (dev1_uuid,)).fetchone()["id"]
        dev2_id = conn.execute("SELECT id FROM devices WHERE uuid = ?", (dev2_uuid,)).fetchone()["id"]

    inst_id = database.add_instrument(
        uuid=inst_uuid, name='RIGEL 288+', serial='SN_RIGEL_99', fw='2.0',
        cal_date='2026-01-15', timestamp=ts_now, instrument_type='electrical'
    )

    print(f"[OK] Setup anagrafica completato. Dispositivi: {dev1_id}, {dev2_id}")

    # 2. Save system verification
    sv_uuid = str(uuid.uuid4())
    results = [
        {"name": "Resistenza conduttore di protezione (PE)", "passed": True, "value": "0.08", "unit": "Ohm", "limit_value": "0.30", "status": "PASS"},
        {"name": "Resistenza di isolamento", "passed": True, "value": "> 50", "unit": "MOhm", "limit_value": "2.00", "status": "PASS"},
        {"name": "Corrente di dispersione sull'involucro", "passed": True, "value": "15", "unit": "uA", "limit_value": "100", "status": "PASS"}
    ]
    visual_inspection = {
        "checklist": [
            {"item": "Involucri e parti meccaniche dei dispositivi integri.", "result": "OK"},
            {"item": "Cavi di alimentazione, spine e multiprese conformi e senza danni.", "result": "OK"},
            {"item": "Cavi di interconnessione e accessori del sistema integri.", "result": "OK"}
        ],
        "notes": "Tutti i cavi sono stati posati e fascettati correttamente sul carrello."
    }
    mti_info = {
        "instrument": "RIGEL 288+",
        "serial": "SN_RIGEL_99",
        "version": "2.0",
        "cal_date": "2026-01-15"
    }

    code, sv_id = database.save_system_verification(
        uuid_val=sv_uuid,
        system_name="Sistema Colonna Laparoscopica Sala 1",
        destination_id=dest_id,
        profile_name="CEI EN 62353 - Sistema",
        results=results,
        overall_status="CONFORME",
        visual_inspection_data=visual_inspection,
        mti_info=mti_info,
        technician_name="MARIO ROSSI",
        technician_username="mrossi",
        device_ids=[dev1_id, dev2_id],
        timestamp=ts_now,
        verification_date="2026-08-25"
    )

    print(f"[OK] Verifica di sistema salvata con ID {sv_id}, Codice {code}")

    # 3. Retrieve system verification & devices
    sv_row = database.get_system_verification_by_id(sv_id)
    assert sv_row is not None, "Verifica di sistema non trovata"
    assert sv_row["system_name"] == "Sistema Colonna Laparoscopica Sala 1"
    assert sv_row["overall_status"] == "CONFORME"

    devices_associated = database.get_system_verification_devices(sv_id)
    assert len(devices_associated) == 2, f"Attesi 2 dispositivi associati, trovati {len(devices_associated)}"
    print(f"[OK] Recuperata verifica di sistema con {len(devices_associated)} dispositivi associati")

    # 4. Generate PDF report using server_report_generator
    temp_dir = tempfile.mkdtemp(prefix="stm_test_sys_")
    pdf_path = os.path.join(temp_dir, "report_sistema_test.pdf")

    devices_info = [dict(d) for d in devices_associated]
    customer_info = {"name": "OSPEDALE SAN RAFFAELE", "address": "VIA OLGETTINA 60"}
    destination_info = {"name": "BLOCCO OPERATORIO SALA 1", "address": "PIANO 2"}
    verification_data = {
        "date": sv_row.get("verification_date", ""),
        "profile_name": sv_row.get("profile_name", ""),
        "overall_status": sv_row.get("overall_status", ""),
        "results": sv_row.get("results_json") if isinstance(sv_row.get("results_json"), list) else results,
        "visual_inspection_data": sv_row.get("visual_inspection_json") if isinstance(sv_row.get("visual_inspection_json"), dict) else visual_inspection,
        "verification_code": code,
        "system_name": sv_row.get("system_name", ""),
    }

    srg.create_system_report(
        filename=pdf_path,
        devices_info=devices_info,
        customer_info=customer_info,
        destination_info=destination_info,
        mti_info=mti_info,
        report_settings={},
        verification_data=verification_data,
        technician_name="MARIO ROSSI",
        signature_data=None
    )

    assert os.path.exists(pdf_path), "Il PDF di sistema deve esistere"
    from PyPDF2 import PdfReader
    reader = PdfReader(pdf_path)
    print(f"[OK] PDF Report di Sistema generato con successo: {len(reader.pages)} pagine")
    assert len(reader.pages) >= 2, "Il report di sistema deve avere almeno 2 pagine"

    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    with database.DatabaseConnection() as conn:
        conn.execute("DELETE FROM system_verification_devices WHERE system_verification_id = ?", (sv_id,))
        conn.execute("DELETE FROM system_verifications WHERE id = ?", (sv_id,))
        conn.execute("DELETE FROM mti_instruments WHERE id = ?", (inst_id,))
        conn.execute("DELETE FROM devices WHERE id IN (?, ?)", (dev1_id, dev2_id))
        conn.execute("DELETE FROM destinations WHERE id = ?", (dest_id,))
        conn.execute("DELETE FROM customers WHERE id = ?", (cust_id,))
        conn.commit()

    print("[OK] Cleanup database completato")
    print("\nTUTTI I TEST DELLE VERIFICHE DI SISTEMA MOBILE SONO PASSATI CON SUCCESSO!")

if __name__ == "__main__":
    run_tests()
