# scratch/test_mobile_dossier.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SECRET_KEY"] = "test_secret_key_minimum_32_characters_for_server_run"
os.environ["ALGORITHM"] = "HS256"

import uuid
import tempfile
import json
from datetime import datetime, timezone
from PyPDF2 import PdfReader
from reportlab.pdfgen import canvas
import database
from app.workers.bulk_report_worker import BulkReportWorker

def create_fake_pdf(path, text="Fake PDF Content"):
    c = canvas.Canvas(path)
    c.drawString(100, 750, text)
    c.save()

# Local implementation of collection functions matching real_server.py
def collect_dossier_verifications(
    scope: str,
    customer_id: int | None,
    destination_id: int | None,
    start_date: str,
    end_date: str,
    include_electrical: bool = True,
    include_functional: bool = True,
    include_system: bool = True,
    include_ecografo_cq: bool = True,
    latest_only: bool = True,
) -> list:
    all_verifications = []

    def _dest_ids_for_cust(c_id):
        if not c_id:
            return []
        dests = database.get_destinations_for_customer(c_id)
        return [d["id"] for d in dests]

    if include_electrical:
        if scope == "all":
            rows = database.get_verifications_by_date_range(start_date, end_date)
            el_verifs = [dict(r) for r in rows]
        elif scope == "customer":
            el_verifs = []
            for did in _dest_ids_for_cust(customer_id):
                el_verifs += [dict(r) for r in database.get_verifications_for_destination_by_date_range(did, start_date, end_date)]
        else:
            el_verifs = [dict(r) for r in database.get_verifications_for_destination_by_date_range(destination_id, start_date, end_date)]

        if latest_only:
            el_verifs = filter_latest_dossier(el_verifs)
        for v in el_verifs:
            v["verification_type"] = "ELETTRICA"
            all_verifications.append(v)

    if include_functional:
        if scope == "all":
            rows = database.get_functional_verifications_by_date_range(start_date, end_date)
            fun_verifs = [dict(r) for r in rows]
        elif scope == "customer":
            fun_verifs = []
            for did in _dest_ids_for_cust(customer_id):
                fun_verifs += [dict(r) for r in database.get_functional_verifications_for_destination_by_date_range(did, start_date, end_date)]
        else:
            fun_verifs = [dict(r) for r in database.get_functional_verifications_for_destination_by_date_range(destination_id, start_date, end_date)]

        if latest_only:
            fun_verifs = filter_latest_dossier(fun_verifs)
        for v in fun_verifs:
            v["verification_type"] = "FUNZIONALE"
            all_verifications.append(v)

    if include_system:
        if scope == "all":
            rows = database.get_system_verifications_by_date_range(start_date, end_date)
            sys_verifs = [dict(r) for r in rows]
        elif scope == "customer":
            sys_verifs = []
            for did in _dest_ids_for_cust(customer_id):
                sys_verifs += [dict(r) for r in database.get_system_verifications_for_destination_by_date_range(did, start_date, end_date)]
        else:
            sys_verifs = [dict(r) for r in database.get_system_verifications_for_destination_by_date_range(destination_id, start_date, end_date)]
        for v in sys_verifs:
            v["verification_type"] = "SISTEMA"
            all_verifications.append(v)

    if include_ecografo_cq:
        if scope == "all":
            cq_rows = database.get_ecografo_quality_checks_by_date_range(start_date, end_date)
        elif scope == "customer":
            cq_rows = database.get_ecografo_quality_checks_by_date_range(start_date, end_date, customer_id=customer_id)
        else:
            cq_rows = database.get_ecografo_quality_checks_by_date_range(start_date, end_date, destination_id=destination_id)
        for r in cq_rows:
            r_dict = dict(r)
            all_verifications.append({
                "verification_type": "ECOGRAFO_CQ",
                "id": r_dict.get("id"),
                "device_id": r_dict.get("device_id"),
                "verification_date": r_dict.get("verification_date"),
                "overall_status": r_dict.get("overall_judgment", ""),
                "description": r_dict.get("description"),
                "manufacturer": r_dict.get("manufacturer"),
                "model": r_dict.get("model"),
                "serial_number": r_dict.get("serial_number"),
                "ams_inventory": r_dict.get("ams_inventory"),
                "customer_inventory": r_dict.get("customer_inventory"),
                "department": r_dict.get("department"),
                "destination_name": r_dict.get("destination_name"),
                "technician_name": r_dict.get("technician_name"),
            })

    try:
        if scope == "all":
            unavail_rows = database.get_unavailability_reports_by_date_range(start_date, end_date)
        elif scope == "customer":
            unavail_rows = database.get_unavailability_reports_by_date_range(start_date, end_date, customer_id=customer_id)
        else:
            unavail_rows = database.get_unavailability_reports_by_date_range(start_date, end_date, destination_id=destination_id)
        for r in unavail_rows:
            all_verifications.append({
                "verification_type": "NON_DISPONIBILE",
                "id": None,
                "device_id": r.get("device_id"),
                "verification_date": r.get("period_start"),
                "overall_status": "NON MESSO A DISPOSIZIONE",
                "notes": r.get("reason", ""),
                "description": r.get("description"),
                "manufacturer": r.get("manufacturer"),
                "model": r.get("model"),
                "serial_number": r.get("serial_number"),
                "ams_inventory": r.get("ams_inventory"),
                "customer_inventory": r.get("customer_inventory"),
                "department": r.get("department"),
                "destination_name": r.get("destination_name"),
                "technician_name": r.get("technician_name"),
                "unavail_report_uuid": r.get("uuid"),
            })
    except Exception as _e:
        print(f"Warning unavail: {_e}")

    return all_verifications


def filter_latest_dossier(verifications: list) -> list:
    latest_by_device = {}
    for verif in verifications:
        device_id = verif.get("device_id")
        if not device_id:
            continue
        if device_id not in latest_by_device:
            latest_by_device[device_id] = verif
            continue
        current_date = latest_by_device[device_id].get("verification_date", "")
        new_date = verif.get("verification_date", "")
        if new_date > current_date:
            latest_by_device[device_id] = verif
    return list(latest_by_device.values())


def build_dossier_cover_info(scope: str, customer_id: int | None, destination_id: int | None,
                             start_date: str, end_date: str, verifications: list,
                             technician_name: str = "") -> dict:
    customer_name = "TUTTI I CLIENTI"
    destination_name = "TUTTE LE DESTINAZIONI"
    dest_address = ""

    try:
        if scope == "customer" and customer_id:
            cust = database.get_customer_by_id(customer_id)
            if cust:
                customer_name = str(cust["name"]).upper()
            destination_name = "TUTTE LE DESTINAZIONI"
        elif scope == "destination" and destination_id:
            dest = database.get_destination_by_id(destination_id)
            if dest:
                destination_name = str(dest["name"]).upper()
                dest_address = dict(dest).get("address", "") or ""
                cust = database.get_customer_by_id(dest["customer_id"])
                if cust:
                    customer_name = str(cust["name"]).upper()
    except Exception as e:
        print(f"Warning cover: {e}")

    electrical_count = sum(1 for v in verifications if v.get("verification_type") == "ELETTRICA")
    functional_count = sum(1 for v in verifications if v.get("verification_type") == "FUNZIONALE")
    system_count = sum(1 for v in verifications if v.get("verification_type") == "SISTEMA")
    ecografo_cq_count = sum(1 for v in verifications if v.get("verification_type") == "ECOGRAFO_CQ")
    non_disponibili_count = sum(1 for v in verifications if v.get("verification_type") == "NON_DISPONIBILE")

    unique_devices = set(
        v.get("device_id")
        for v in verifications
        if v.get("device_id") and v.get("verification_type") not in ("SISTEMA", "NON_DISPONIBILE")
    )

    def _norm(val):
        return str(val or "").strip().upper()

    conformi_count = sum(1 for v in verifications if _norm(v.get("overall_status")) in ("PASSATO", "CONFORME", "IDONEO"))
    cca_count = sum(1 for v in verifications if _norm(v.get("overall_status")) == "CONFORME CON ANNOTAZIONE")
    non_conformi_count = sum(1 for v in verifications if _norm(v.get("overall_status")) in ("FALLITO", "NON CONFORME", "NON IDONEO"))

    el_verifs  = [v for v in verifications if v.get("verification_type") == "ELETTRICA"]
    fun_verifs = [v for v in verifications if v.get("verification_type") == "FUNZIONALE"]
    sys_verifs = [v for v in verifications if v.get("verification_type") == "SISTEMA"]

    el_conformi_count  = sum(1 for v in el_verifs if _norm(v.get("overall_status")) in ("PASSATO", "CONFORME"))
    el_cca_count       = sum(1 for v in el_verifs if _norm(v.get("overall_status")) == "CONFORME CON ANNOTAZIONE")
    el_nc_count        = sum(1 for v in el_verifs if _norm(v.get("overall_status")) in ("FALLITO", "NON CONFORME"))
    fun_conformi_count = sum(1 for v in fun_verifs if _norm(v.get("overall_status")) in ("PASSATO", "CONFORME"))
    fun_cca_count      = sum(1 for v in fun_verifs if _norm(v.get("overall_status")) == "CONFORME CON ANNOTAZIONE")
    fun_nc_count       = sum(1 for v in fun_verifs if _norm(v.get("overall_status")) in ("FALLITO", "NON CONFORME"))
    sys_conformi_count = sum(1 for v in sys_verifs if _norm(v.get("overall_status")) in ("PASSATO", "CONFORME"))
    sys_cca_count      = sum(1 for v in sys_verifs if _norm(v.get("overall_status")) == "CONFORME CON ANNOTAZIONE")
    sys_nc_count       = sum(1 for v in sys_verifs if _norm(v.get("overall_status")) in ("FALLITO", "NON CONFORME"))

    return {
        "customer_name": customer_name,
        "destination_name": destination_name,
        "destination_address": dest_address,
        "start_date": start_date,
        "end_date": end_date,
        "total_count": len(verifications),
        "devices_count": len(unique_devices),
        "electrical_count": electrical_count,
        "functional_count": functional_count,
        "system_count": system_count,
        "ecografo_cq_count": ecografo_cq_count,
        "conformi_count": conformi_count,
        "conformi_con_annotazione_count": cca_count,
        "non_conformi_count": non_conformi_count,
        "non_disponibili_count": non_disponibili_count,
        "el_conformi_count": el_conformi_count,
        "el_cca_count": el_cca_count,
        "el_nc_count": el_nc_count,
        "fun_conformi_count": fun_conformi_count,
        "fun_cca_count": fun_cca_count,
        "fun_nc_count": fun_nc_count,
        "sys_conformi_count": sys_conformi_count,
        "sys_cca_count": sys_cca_count,
        "sys_nc_count": sys_nc_count,
        "logo_path": None,
        "created_by": technician_name or "",
    }


def run_tests():
    print("Testing Mobile Unified Dossier / Fascicolo PDF generation...")

    cust_uuid = str(uuid.uuid4())
    dest_uuid = str(uuid.uuid4())
    dev1_uuid = str(uuid.uuid4())
    dev2_uuid = str(uuid.uuid4())
    dev3_uuid = str(uuid.uuid4())
    dev4_uuid = str(uuid.uuid4())
    inst_uuid = str(uuid.uuid4())
    ts_now = datetime.now(timezone.utc).isoformat()

    # 1. Anagrafiche
    database.add_customer(cust_uuid, "POLICLINICO UNIVERSITARIO", "VIA ROMA 100", "", "", ts_now)
    with database.DatabaseConnection() as conn:
        cust_id = conn.execute("SELECT id FROM customers WHERE uuid = ?", (cust_uuid,)).fetchone()["id"]

    database.add_destination(dest_uuid, cust_id, "BLOCCO OPERATORIO", "PIANO 1", ts_now)
    with database.DatabaseConnection() as conn:
        dest_id = conn.execute("SELECT id FROM destinations WHERE uuid = ?", (dest_uuid,)).fetchone()["id"]

    database.add_device(
        uuid=dev1_uuid, destination_id=dest_id, serial='SN_DEFIB_01', desc='DEFIBRILLATORE',
        mfg='ZOLL', model='R SERIES', department='BLOCCO OPERATORIO', applied_parts=[],
        customer_inv='INV_D1', ams_inv='AMS_D1', verification_interval=12,
        default_profile_key='62353_DIR', default_functional_profile_key='DEFIBRILLATORE', timestamp=ts_now
    )
    database.add_device(
        uuid=dev2_uuid, destination_id=dest_id, serial='SN_ELETTRO_02', desc='ELETTROBISTURI',
        mfg='VALLEYLAB', model='FT10', department='BLOCCO OPERATORIO', applied_parts=[],
        customer_inv='INV_D2', ams_inv='AMS_D2', verification_interval=12,
        default_profile_key='62353_DIR', default_functional_profile_key='ELETTROBISTURI', timestamp=ts_now
    )
    database.add_device(
        uuid=dev3_uuid, destination_id=dest_id, serial='SN_ECO_03', desc='ECOGRAFO',
        mfg='ESAOTE', model='MYLAB 9', department='BLOCCO OPERATORIO', applied_parts=[],
        customer_inv='INV_D3', ams_inv='AMS_D3', verification_interval=12,
        default_profile_key=None, default_functional_profile_key=None, timestamp=ts_now
    )
    database.add_device(
        uuid=dev4_uuid, destination_id=dest_id, serial='SN_MONITOR_04', desc='MONITOR PAZIENTE',
        mfg='PHILIPS', model='INTELLIVUE', department='BLOCCO OPERATORIO', applied_parts=[],
        customer_inv='INV_D4', ams_inv='AMS_D4', verification_interval=12,
        default_profile_key=None, default_functional_profile_key=None, timestamp=ts_now
    )
    with database.DatabaseConnection() as conn:
        dev1_id = conn.execute("SELECT id FROM devices WHERE uuid = ?", (dev1_uuid,)).fetchone()["id"]
        dev2_id = conn.execute("SELECT id FROM devices WHERE uuid = ?", (dev2_uuid,)).fetchone()["id"]
        dev3_id = conn.execute("SELECT id FROM devices WHERE uuid = ?", (dev3_uuid,)).fetchone()["id"]
        dev4_id = conn.execute("SELECT id FROM devices WHERE uuid = ?", (dev4_uuid,)).fetchone()["id"]

    # 2. Strumento con certificato allegato
    inst_id = database.add_instrument(
        uuid=inst_uuid, name='RIGEL 288 PLUS DOSSIER', serial='SN_RIGEL_DOSSIER', fw='2.0',
        cal_date='2026-01-15', timestamp=ts_now, instrument_type='electrical'
    )

    temp_dir = tempfile.mkdtemp(prefix="stm_test_dossier_")
    cert_pdf = os.path.join(temp_dir, "cert_calibrazione_rigel.pdf")
    create_fake_pdf(cert_pdf, "CERTIFICATO DI TARATURA STRUMENTO RIGEL 288 DOSSIER")
    with open(cert_pdf, "rb") as f:
        cert_bytes = f.read()

    cert_att_id = database.save_instrument_attachment(
        instrument_id=inst_id,
        filename="cert_calibrazione_rigel.pdf",
        file_data=cert_bytes,
        description="Certificato di calibrazione"
    )

    # 3. Salva Verifiche:
    # A) Verifica Elettrica
    mti_data = {
        "instrument": "RIGEL 288 PLUS DOSSIER",
        "serial": "SN_RIGEL_DOSSIER",
        "version": "2.0",
        "cal_date": "2026-01-15"
    }
    el_code, el_id = database.save_verification(
        uuid=str(uuid.uuid4()),
        device_id=dev1_id,
        profile_name="CEI EN 62353 Diretto",
        results=[{"name": "Resistenza PE", "passed": True, "value": "0.05", "unit": "Ohm", "limit_value": "0.30"}],
        overall_status="CONFORME",
        visual_inspection_data={"checklist": [], "notes": "OK"},
        mti_info=mti_data,
        technician_name="MARIO ROSSI",
        technician_username="mrossi",
        timestamp=ts_now,
        verification_date="2026-08-25"
    )

    # B) Verifica Funzionale
    fn_code, fn_id = database.save_functional_verification(
        uuid=str(uuid.uuid4()),
        device_id=dev2_id,
        profile_key="ELETTROBISTURI",
        results={"potenza_taglio": {"measured": "100", "unit": "W", "passed": True}},
        structured_results={},
        overall_status="CONFORME",
        notes="Funzionale OK",
        mti_info=mti_data,
        technician_name="MARIO ROSSI",
        technician_username="mrossi",
        timestamp=ts_now,
        verification_date="2026-08-25"
    )

    # C) Verifica di Sistema (dev1 + dev2)
    sys_code, sys_id = database.save_system_verification(
        uuid_val=str(uuid.uuid4()),
        system_name="Colonna Elettrochirurgica",
        destination_id=dest_id,
        profile_name="CEI EN 62353 - Sistema",
        results=[{"name": "Resistenza PE Sistema", "passed": True, "value": "0.08", "unit": "Ohm", "limit_value": "0.30"}],
        overall_status="CONFORME",
        visual_inspection_data={"checklist": [], "notes": "Sistema OK"},
        mti_info=mti_data,
        technician_name="MARIO ROSSI",
        technician_username="mrossi",
        device_ids=[dev1_id, dev2_id],
        timestamp=ts_now,
        verification_date="2026-08-25"
    )

    # D) Segnalazione Non Messo a Disposizione per dev4
    database.save_unavailability_report(
        device_id=dev4_id,
        destination_id=dest_id,
        period_start="2026-08-01",
        period_end="2026-08-25",
        reason="Apparecchio in uso in emergenza",
        technician_name="MARIO ROSSI",
        technician_username="mrossi"
    )

    print(f"[OK] Dati di test creati: VE {el_id}, VF {fn_id}, VS {sys_id}")

    # 4. Raccogli verifiche tramite server helper
    all_verifs = collect_dossier_verifications(
        scope="destination",
        customer_id=cust_id,
        destination_id=dest_id,
        start_date="2026-01-01",
        end_date="2026-12-31",
        include_electrical=True,
        include_functional=True,
        include_system=True,
        include_ecografo_cq=True,
        latest_only=True
    )
    print(f"[OK] Verifiche raccolte per il fascicolo: {len(all_verifs)}")
    assert len(all_verifs) >= 3, f"Attese almeno 3 verifiche nel fascicolo, trovate {len(all_verifs)}"

    # 5. Costruisci cover info
    cover_info = build_dossier_cover_info(
        scope="destination",
        customer_id=cust_id,
        destination_id=dest_id,
        start_date="2026-01-01",
        end_date="2026-12-31",
        verifications=all_verifs,
        technician_name="MARIO ROSSI"
    )
    assert cover_info["customer_name"] == "POLICLINICO UNIVERSITARIO"
    assert cover_info["destination_name"] == "BLOCCO OPERATORIO"
    assert cover_info["total_count"] == len(all_verifs)
    print(f"[OK] Cover info costruita: {cover_info['total_count']} verifiche totali, {cover_info['devices_count']} apparecchi")

    # 6. Esegui generazione Fascicolo con certificati
    dossier_output_pdf = os.path.join(temp_dir, "Fascicolo_Verifiche_Test.pdf")
    worker = BulkReportWorker(
        verifications_to_process=all_verifs,
        output_folder=None,
        report_settings={},
        naming_format="ams_inventory",
        merge_into_one=True,
        merged_output_path=dossier_output_pdf,
        merged_intro_mode="cover_and_table",
        export_cover_single=False,
        export_table_single=False,
        keep_individual_reports=False,
        cover_info=cover_info,
        include_calibration_certs=True
    )
    worker.run()

    assert os.path.exists(dossier_output_pdf), "Il file PDF del fascicolo unificato deve esistere"
    reader = PdfReader(dossier_output_pdf)
    print(f"[OK] Fascicolo PDF generato con successo: {len(reader.pages)} pagine totali")
    assert len(reader.pages) >= 4, f"Il fascicolo deve contenere copertina, tabella, report e certificato. Pagine trovate: {len(reader.pages)}"

    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    with database.DatabaseConnection() as conn:
        conn.execute("DELETE FROM device_unavailability_reports WHERE device_id = ?", (dev4_id,))
        conn.execute("DELETE FROM system_verification_devices WHERE system_verification_id = ?", (sys_id,))
        conn.execute("DELETE FROM system_verifications WHERE id = ?", (sys_id,))
        conn.execute("DELETE FROM functional_verifications WHERE id = ?", (fn_id,))
        conn.execute("DELETE FROM verifications WHERE id = ?", (el_id,))
        conn.execute("DELETE FROM verification_attachments WHERE verification_id = ? AND verification_type = 'instrument'", (inst_id,))
        conn.execute("DELETE FROM mti_instruments WHERE id = ?", (inst_id,))
        conn.execute("DELETE FROM devices WHERE id IN (?, ?, ?, ?)", (dev1_id, dev2_id, dev3_id, dev4_id))
        conn.execute("DELETE FROM destinations WHERE id = ?", (dest_id,))
        conn.execute("DELETE FROM customers WHERE id = ?", (cust_id,))
        conn.commit()

    print("[OK] Cleanup completato con successo")
    print("\nTUTTI I TEST DI GENERAZIONE FASCICOLO PDF MOBILE SONO PASSATI AL 100%!")

if __name__ == "__main__":
    run_tests()
