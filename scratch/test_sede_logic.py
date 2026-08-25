# scratch/test_sede_logic.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone

import database
import app.services as services

def run_tests():
    print("Testing sede field in database...")
    database._ensure_mti_instruments_columns()
    
    # Check pragma
    with database.DatabaseConnection() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(mti_instruments)").fetchall()}
        assert "sede" in cols, f"Colonna sede mancante in mti_instruments: {cols}"
    print("[OK] Colonna sede presente nel database locale SQLite")

    # Add test instruments
    ts = datetime.now(timezone.utc).isoformat()
    u1 = str(uuid.uuid4())
    u2 = str(uuid.uuid4())
    u3 = str(uuid.uuid4())
    
    database.add_instrument(u1, "STRUMENTO_TEST_NORD", "SN001", "1.0", "2026-01-01", ts, instrument_type="electrical", sede="SEDE NORD")
    database.add_instrument(u2, "STRUMENTO_TEST_SUD", "SN002", "1.0", "2026-01-01", ts, instrument_type="electrical", sede="SEDE SUD")
    database.add_instrument(u3, "STRUMENTO_TEST_CONDIVISO", "SN003", "1.0", "2026-01-01", ts, instrument_type="electrical", sede=None)

    # Test filtering by user sede
    insts_nord = database.get_all_instruments(user_sede="SEDE NORD")
    names_nord = [dict(i)["instrument_name"] for i in insts_nord]
    assert "STRUMENTO_TEST_NORD" in names_nord, "STRUMENTO_TEST_NORD dovrebbe essere visibile a SEDE NORD"
    assert "STRUMENTO_TEST_CONDIVISO" in names_nord, "STRUMENTO_TEST_CONDIVISO dovrebbe essere visibile a tutti"
    assert "STRUMENTO_TEST_SUD" not in names_nord, "STRUMENTO_TEST_SUD NON dovrebbe essere visibile a SEDE NORD"
    print("[OK] Filtro sede utente SEDE NORD verificato con successo")

    insts_sud = database.get_all_instruments(user_sede="SEDE SUD")
    names_sud = [dict(i)["instrument_name"] for i in insts_sud]
    assert "STRUMENTO_TEST_SUD" in names_sud, "STRUMENTO_TEST_SUD dovrebbe essere visibile a SEDE SUD"
    assert "STRUMENTO_TEST_NORD" not in names_sud, "STRUMENTO_TEST_NORD NON dovrebbe essere visibile a SEDE SUD"
    print("[OK] Filtro sede utente SEDE SUD verificato con successo")

    insts_all = database.get_all_instruments(user_sede=None)
    names_all = [dict(i)["instrument_name"] for i in insts_all]
    assert "STRUMENTO_TEST_NORD" in names_all and "STRUMENTO_TEST_SUD" in names_all and "STRUMENTO_TEST_CONDIVISO" in names_all
    print("[OK] Visualizzazione admin di tutti gli strumenti verificata con successo")

    # Clean up test records
    with database.DatabaseConnection() as conn:
        conn.execute("DELETE FROM mti_instruments WHERE uuid IN (?, ?, ?)", (u1, u2, u3))
        conn.commit()
    print("[OK] Cleanup record di test completato")

    print("\nTUTTI I TEST SONO PASSATI CON SUCCESSO!")

if __name__ == "__main__":
    run_tests()
