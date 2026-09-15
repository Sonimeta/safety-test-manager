# scratch/test_mobile_ecografo_cq.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import tempfile
from datetime import datetime, timezone
import database
from app.ecografo_quality_models import (
    EcografoQualityCheck,
    EcografoQualityProbe,
    EcografoQualityControl
)
import report_generator

def run_tests():
    print("Testing Mobile Ultrasound Probe Quality Checks (CQ Sonde)...")

    cust_uuid = str(uuid.uuid4())
    dest_uuid = str(uuid.uuid4())
    dev_uuid = str(uuid.uuid4())
    ts_now = datetime.now(timezone.utc).isoformat()

    # 1. Anagrafiche
    database.add_customer(cust_uuid, "CLINICA CITTA DI TRENTO", "VIA GIOVANELLI 5", "", "", ts_now)
    with database.DatabaseConnection() as conn:
        cust_id = conn.execute("SELECT id FROM customers WHERE uuid = ?", (cust_uuid,)).fetchone()["id"]

    database.add_destination(dest_uuid, cust_id, "SERVIZIO RADIOLOGIA", "PIANO -1", ts_now)
    with database.DatabaseConnection() as conn:
        dest_id = conn.execute("SELECT id FROM destinations WHERE uuid = ?", (dest_uuid,)).fetchone()["id"]

    database.add_device(
        uuid=dev_uuid, destination_id=dest_id, serial='SN_ECO_ESAOTE_88', desc='ECOGRAFO MYLAB X8',
        mfg='ESAOTE', model='MYLAB X8', department='RADIOLOGIA', applied_parts=[],
        customer_inv='INV_RAD_01', ams_inv='AMS_RAD_01', verification_interval=12,
        default_profile_key=None, default_functional_profile_key=None, timestamp=ts_now
    )
    with database.DatabaseConnection() as conn:
        dev_id = conn.execute("SELECT id FROM devices WHERE uuid = ?", (dev_uuid,)).fetchone()["id"]

    print(f"[OK] Setup ecografo completato. ID: {dev_id}")

    # 2. Build CQ Sonde object with 2 probes
    check = EcografoQualityCheck(
        uuid=str(uuid.uuid4()),
        device_id=dev_id,
        verification_date="2026-08-25",
        technician_name="MARIO ROSSI",
        technician_username="mrossi",
        overall_status="CONFORME",
        notes="Controllo qualità periodico sonde eseguito su fantoccio multimodale."
    )

    probe1 = EcografoQualityProbe(
        uuid=str(uuid.uuid4()),
        probe_order=0,
        model="CA631",
        serial_number="SN_PROBE_C1",
        probe_type="Convex",
        manufacturer="ESAOTE",
        inventory="INV_SONDA_1",
        control_stage="Controllo Periodico",
        preset="Addome Standard",
        gain="52 dB",
        power="100%",
        overall_judgment="CONFORME",
        notes="Sonda in ottime condizioni."
    )
    probe1.controls = [
        EcografoQualityControl(control_key="ispezione_visiva", control_label="Ispezione visiva", value="BUONO", passed=True),
        EcografoQualityControl(control_key="uniformita", control_label="Uniformità", value="BUONO", passed=True),
        EcografoQualityControl(control_key="profondita_max", control_label="Profondità max", value="16.5", unit="cm", passed=True),
        EcografoQualityControl(control_key="misure_verticali", control_label="Misure verticali", value="0.8", unit="mm", passed=True),
        EcografoQualityControl(control_key="misure_orizzontali", control_label="Misure orizzontali", value="1.1", unit="mm", passed=True),
        EcografoQualityControl(control_key="zona_morta", control_label="Zona morta", value="2.0", unit="mm", passed=True),
        EcografoQualityControl(control_key="risoluzione_3cm", control_label="Risoluzione 3 cm", value="1.0", unit="mm", passed=True),
        EcografoQualityControl(control_key="risoluzione_11cm", control_label="Risoluzione 11 cm", value="2.0", unit="mm", passed=True),
        EcografoQualityControl(control_key="massa_anecoica", control_label="Massa anecoica", value="PASS", passed=True),
        EcografoQualityControl(control_key="massa_iperecogena", control_label="Massa iperecogena", value="PASS", passed=True),
    ]

    probe2 = EcografoQualityProbe(
        uuid=str(uuid.uuid4()),
        probe_order=1,
        model="L12-4",
        serial_number="SN_PROBE_L2",
        probe_type="Lineare",
        manufacturer="ESAOTE",
        inventory="INV_SONDA_2",
        control_stage="Controllo Periodico",
        preset="Tiroide / Vasi",
        gain="48 dB",
        power="100%",
        overall_judgment="CONFORME",
        notes="Nessun dropout rilevato."
    )
    probe2.controls = [
        EcografoQualityControl(control_key="ispezione_visiva", control_label="Ispezione visiva", value="BUONO", passed=True),
        EcografoQualityControl(control_key="uniformita", control_label="Uniformità", value="BUONO", passed=True),
        EcografoQualityControl(control_key="profondita_max", control_label="Profondità max", value="8.0", unit="cm", passed=True),
        EcografoQualityControl(control_key="misure_verticali", control_label="Misure verticali", value="0.4", unit="mm", passed=True),
        EcografoQualityControl(control_key="misure_orizzontali", control_label="Misure orizzontali", value="0.6", unit="mm", passed=True),
        EcografoQualityControl(control_key="zona_morta", control_label="Zona morta", value="1.0", unit="mm", passed=True),
        EcografoQualityControl(control_key="risoluzione_3cm", control_label="Risoluzione 3 cm", value="0.8", unit="mm", passed=True),
        EcografoQualityControl(control_key="risoluzione_11cm", control_label="Risoluzione 11 cm", value="1.5", unit="mm", passed=True),
        EcografoQualityControl(control_key="massa_anecoica", control_label="Massa anecoica", value="PASS", passed=True),
        EcografoQualityControl(control_key="massa_iperecogena", control_label="Massa iperecogena", value="PASS", passed=True),
    ]

    check.probes = [probe1, probe2]

    # Save to database
    code, check_id = database.save_ecografo_quality_check(check, timestamp=ts_now)
    print(f"[OK] Salvato CQ Sonde ID: {check_id}, Codice: {code}")

    # 3. Retrieve and assert
    cq_saved = database.get_ecografo_quality_check(check_id)
    assert cq_saved is not None, "CQ check non trovato"
    assert len(cq_saved.probes) == 2, f"Attese 2 sonde, trovate {len(cq_saved.probes)}"
    assert cq_saved.overall_status == "CONFORME"
    print(f"[OK] Recuperato CQ con {len(cq_saved.probes)} sonde e relativi controlli")

    # 4. Generate PDF Report
    temp_dir = tempfile.mkdtemp(prefix="stm_test_cq_")
    pdf_path = os.path.join(temp_dir, "report_cq_test.pdf")

    device_info = {
        "description": "ECOGRAFO MYLAB X8",
        "model": "MYLAB X8",
        "serial_number": "SN_ECO_ESAOTE_88",
        "manufacturer": "ESAOTE",
        "ams_inventory": "AMS_RAD_01",
        "customer_inventory": "INV_RAD_01",
        "department": "RADIOLOGIA",
    }
    customer_info = {"name": "CLINICA CITTA DI TRENTO", "address": "VIA GIOVANELLI 5"}
    destination_info = {"name": "SERVIZIO RADIOLOGIA", "address": "PIANO -1"}

    report_generator.create_ecografo_quality_report(
        filename=pdf_path,
        device_info=device_info,
        customer_info=customer_info,
        destination_info=destination_info,
        check=cq_saved,
        technician_name="MARIO ROSSI",
        signature_data=None,
        report_settings={}
    )

    assert os.path.exists(pdf_path), "Il file PDF deve esistere"
    from PyPDF2 import PdfReader
    reader = PdfReader(pdf_path)
    print(f"[OK] PDF Report CQ Sonde generato con successo: {len(reader.pages)} pagine")
    assert len(reader.pages) >= 2, "Il report CQ sonde deve avere più pagine (copertina + sonde)"

    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    with database.DatabaseConnection() as conn:
        conn.execute("DELETE FROM ecografo_quality_controls WHERE probe_id IN (SELECT id FROM ecografo_quality_probes WHERE check_id = ?)", (check_id,))
        conn.execute("DELETE FROM ecografo_quality_probes WHERE check_id = ?", (check_id,))
        conn.execute("DELETE FROM ecografo_quality_checks WHERE id = ?", (check_id,))
        conn.execute("DELETE FROM devices WHERE id = ?", (dev_id,))
        conn.execute("DELETE FROM destinations WHERE id = ?", (dest_id,))
        conn.execute("DELETE FROM customers WHERE id = ?", (cust_id,))
        conn.commit()

    print("[OK] Cleanup database completato")
    print("\nTUTTI I TEST DEL CONTROLLO QUALITA SONDE MOBILE SONO PASSATI CON SUCCESSO!")

if __name__ == "__main__":
    run_tests()
