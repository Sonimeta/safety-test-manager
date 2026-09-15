# scratch/test_fascicolo_certs.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import tempfile
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import database
import app.services as services
from app.workers.bulk_report_worker import BulkReportWorker

def create_sample_pdf(path, text):
    c = canvas.Canvas(path, pagesize=A4)
    c.drawString(100, 700, text)
    c.showPage()
    c.save()

def run_tests():
    print("Testing Fascicolo Calibration Certificates Merging Logic...")

    temp_dir = tempfile.mkdtemp(prefix="stm_test_merge_")
    
    # 1. Create a dummy instrument with calibration certificate
    sn = f"SN_MERGE_{uuid.uuid4().hex[:6]}"
    inst_name = "RIGEL 288 PLUS TEST"
    inst_id = database.add_instrument(
        str(uuid.uuid4()), inst_name, sn, "1.0", "2026-01-01", 
        datetime.now(timezone.utc).isoformat(), "electrical", "SEDE NORD"
    )

    cert_pdf_path = os.path.join(temp_dir, "cert_sample.pdf")
    create_sample_pdf(cert_pdf_path, f"CERTIFICATO DI CALIBRAZIONE STRUMENTO {inst_name} S/N: {sn}")
    with open(cert_pdf_path, "rb") as f:
        cert_data = f.read()

    att_id = services.save_instrument_attachment(inst_id, "certificato_rigel.pdf", cert_data)
    print(f"[OK] Strumento creato con ID {inst_id} e certificato allegato ID {att_id}")

    # 2. Prepare mock verifications
    verifications = [
        {
            "id": 1,
            "verification_type": "ELETTRICA",
            "mti_serial": sn,
            "mti_instrument": inst_name,
            "serial_number": "DEV_123",
            "ams_inventory": "AMS_001",
        },
        {
            "id": 2,
            "verification_type": "FUNZIONALE",
            "mti_serial": sn,
            "mti_instrument": inst_name,
            "serial_number": "DEV_456",
            "ams_inventory": "AMS_002",
        }
    ]

    worker = BulkReportWorker(
        verifications_to_process=verifications,
        output_folder=temp_dir,
        report_settings={},
        merge_into_one=True,
        include_calibration_certs=True,
    )

    # 3. Test _collect_used_instruments_certificates
    cert_items, temp_files = worker._collect_used_instruments_certificates()
    assert len(cert_items) == 1, f"Atteso 1 certificato raccolto, trovati {len(cert_items)}"
    cert_file, bookmark_title = cert_items[0]
    print(f"[OK] Certificato raccolto con successo: {cert_file}, Segnalibro: '{bookmark_title}'")
    assert sn in bookmark_title, "Il seriale deve essere nel titolo segnalibro"

    # 4. Test full merge
    rep1_path = os.path.join(temp_dir, "report1.pdf")
    rep2_path = os.path.join(temp_dir, "report2.pdf")
    create_sample_pdf(rep1_path, "REPORT VERIFICA ELETTRICA APPARECCHIO 1")
    create_sample_pdf(rep2_path, "REPORT VERIFICA FUNZIONALE APPARECCHIO 2")

    merged_output = os.path.join(temp_dir, "Fascicolo_Test.pdf")
    merge_list = [rep1_path, rep2_path] + cert_items
    worker._merge_pdfs(merge_list, merged_output)

    assert os.path.exists(merged_output), "Il PDF unico fascicolato deve esistere"
    
    from PyPDF2 import PdfReader
    reader = PdfReader(merged_output)
    print(f"[OK] PDF fascicolato creato con successo: {len(reader.pages)} pagine totali")
    assert len(reader.pages) == 3, f"Attese 3 pagine (2 report + 1 certificato), trovate {len(reader.pages)}"

    # Cleanup DB
    with database.DatabaseConnection() as conn:
        conn.execute("DELETE FROM mti_instruments WHERE id = ?", (inst_id,))
        conn.execute("DELETE FROM verification_attachments WHERE id = ?", (att_id,))
        conn.commit()

    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    print("[OK] Cleanup completato")
    print("\nTUTTI I TEST DI FASCICOLAZIONE CON CERTIFICATI DI CALIBRAZIONE SONO PASSATI CON SUCCESSO!")

if __name__ == "__main__":
    run_tests()
