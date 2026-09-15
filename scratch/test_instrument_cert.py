# scratch/test_instrument_cert.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
import database
import app.services as services

def run_tests():
    print("Testing Instrument PDF Calibration Certificate Logic...")
    
    # 1. Create a dummy instrument
    u = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    inst_id = database.add_instrument(u, "FLUKE TEST 999", "SN9999", "1.0", "2026-01-01", ts, instrument_type="electrical", sede="SEDE TEST")
    assert inst_id is not None, "add_instrument deve restituire l'ID creato"
    print(f"[OK] Strumento creato con ID: {inst_id}")

    # 2. Save a dummy PDF certificate
    pdf_bytes = b"%PDF-1.4 dummy pdf content for calibration cert test"
    att_id = services.save_instrument_attachment(inst_id, "certificato_calibrazione_fluke.pdf", pdf_bytes, description="Certificato di calibrazione PDF")
    assert att_id is not None, "save_instrument_attachment deve restituire un ID allegato valido"
    print(f"[OK] Certificato PDF salvato con ID: {att_id}")

    # 3. Retrieve attachments for instrument
    atts = services.get_instrument_attachments(inst_id)
    assert len(atts) == 1, f"Atteso 1 allegato, trovati {len(atts)}"
    assert atts[0]["filename"] == "certificato_calibrazione_fluke.pdf"
    assert atts[0]["verification_type"] == "instrument"
    print("[OK] get_instrument_attachments ha restituito il certificato")

    # 4. Check count map
    count_map = services.get_instrument_attachments_count_map()
    assert count_map.get(inst_id) == 1, f"Conteggio atteso 1 per inst_id {inst_id}, ottenuto {count_map.get(inst_id)}"
    print("[OK] get_instrument_attachments_count_map verificata")

    # 5. Check physical file exists on disk
    file_path = database.get_attachment_file_path(att_id)
    assert file_path is not None and os.path.exists(file_path), f"File fisico non trovato: {file_path}"
    print(f"[OK] File fisico presente su disco in: {file_path}")

    # 6. Delete attachment
    deleted = services.delete_instrument_attachment(att_id)
    assert deleted is True, "delete_instrument_attachment deve restituire True"
    atts_after = services.get_instrument_attachments(inst_id)
    assert len(atts_after) == 0, "Nessun certificato attivo atteso dopo delete"
    print("[OK] Eliminazione certificato completata con successo")

    # Cleanup instrument
    with database.DatabaseConnection() as conn:
        conn.execute("DELETE FROM mti_instruments WHERE id = ?", (inst_id,))
        conn.execute("DELETE FROM verification_attachments WHERE id = ?", (att_id,))
        conn.commit()
    print("[OK] Cleanup database completato")

    print("\nTUTTI I TEST DEI CERTIFICATI DI CALIBRAZIONE SONO PASSATI CON SUCCESSO!")

if __name__ == "__main__":
    run_tests()
