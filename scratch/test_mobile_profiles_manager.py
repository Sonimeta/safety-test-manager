import os
import sys
import json
import uuid
import sqlite3

# Ensure root directory is in python path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ["SECRET_KEY"] = "test_secret_key_minimum_32_characters_for_server_run"
os.environ["ALGORITHM"] = "HS256"

# Create a local test SQLite DB simulating Postgres tables for real_server tests
test_db_path = os.path.join(BASE_DIR, "scratch", "test_profiles.db")
if os.path.exists(test_db_path):
    os.remove(test_db_path)

conn_init = sqlite3.connect(test_db_path)
conn_init.row_factory = sqlite3.Row
conn_init.executescript("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT,
    username TEXT UNIQUE,
    password_hash TEXT,
    role TEXT,
    first_name TEXT,
    last_name TEXT,
    sede TEXT,
    token TEXT,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE,
    profile_key TEXT,
    name TEXT,
    norma TEXT,
    last_modified TEXT,
    is_synced BOOLEAN DEFAULT 1,
    is_deleted BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS profile_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE,
    profile_id INTEGER,
    name TEXT,
    parameter TEXT,
    limits_json TEXT,
    is_applied_part_test BOOLEAN DEFAULT 0,
    last_modified TEXT,
    is_synced BOOLEAN DEFAULT 1,
    is_deleted BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS functional_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE,
    profile_key TEXT,
    name TEXT,
    device_type TEXT,
    instrument_ids TEXT,
    schema_json TEXT,
    last_modified TEXT,
    is_synced BOOLEAN DEFAULT 1,
    is_deleted BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS verification_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE,
    technician_username TEXT,
    assigned_by TEXT,
    title TEXT,
    assignment_type TEXT,
    customer_id INTEGER,
    destination_id INTEGER,
    device_id INTEGER,
    notes TEXT,
    priority TEXT,
    status TEXT,
    due_date TEXT,
    assigned_at TEXT,
    completed_at TEXT,
    last_modified TEXT,
    is_synced BOOLEAN DEFAULT 1,
    is_deleted BOOLEAN DEFAULT 0
);

INSERT INTO users (uuid, username, role, first_name, last_name, token, is_active)
VALUES ('admin-uuid-123', 'admin', 'admin', 'Mario', 'Rossi', 'test_token_admin', 1);
""")
conn_init.commit()
conn_init.close()

# Sqlite connection adapter that translates %s and RETURNING for SQLite
class SqliteAdapterCursor:
    def __init__(self, cur):
        self.cur = cur

    def execute(self, sql, params=None):
        sql = sql.replace("%s", "?")
        sql = sql.replace("TRUE", "1").replace("FALSE", "0")
        if "RETURNING id" in sql:
            clean_sql = sql.replace("RETURNING id", "")
            if params:
                self.cur.execute(clean_sql, params)
            else:
                self.cur.execute(clean_sql)
            self._lastrowid = self.cur.lastrowid
            self._returning_id = True
        else:
            self._returning_id = False
            if params:
                self.cur.execute(sql, params)
            else:
                self.cur.execute(sql)
        return self

    def fetchone(self):
        if getattr(self, '_returning_id', False):
            self._returning_id = False
            return {"id": self._lastrowid}
        row = self.cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        rows = self.cur.fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.cur.close()

class SqliteAdapterConn:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    def cursor(self, cursor_factory=None):
        return SqliteAdapterCursor(self.conn.cursor())

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

import real_server
real_server.CLOUDFLARE_TUNNEL = False
# Override real_server get_db_connection to use our local test DB
real_server.get_db_connection = lambda: SqliteAdapterConn(test_db_path)

from fastapi.testclient import TestClient
from real_server import app

client = TestClient(app)

def run_tests():
    print("=== TESTING MOBILE PROFILES MANAGEMENT HUB (v2.0) ===")

    # 1. Setup session with valid JWT token
    from jose import jwt
    token = jwt.encode({
        "sub": "admin",
        "role": "admin",
        "first_name": "Mario",
        "last_name": "Rossi",
        "sede": "SEDE NORD"
    }, real_server.SECRET_KEY, algorithm=real_server.ALGORITHM)
    client.cookies.set("mobile_session", token)

    # 2. Test GET /mobile/profiles
    res = client.get("/mobile/profiles", follow_redirects=False)
    assert res.status_code == 200, f"GET /mobile/profiles failed: {res.status_code}"
    assert "Profili di Verifica" in res.text
    print("[OK] GET /mobile/profiles OK")

    # 3. Test Create Electrical Profile
    test_key = f"test_pe_{uuid.uuid4().hex[:6]}"
    tests_payload = [
        {
            "name": "Resistenza PE di Prova",
            "parameter": "pe_res",
            "is_applied_part_test": False,
            "operator": "<=",
            "limit_value": "0.20",
            "unit": "Ohm"
        },
        {
            "name": "Dispersione Paziente Prova AP",
            "parameter": "patient_leakage",
            "is_applied_part_test": True,
            "limit_b": "100",
            "limit_bf": "50",
            "limit_cf": "10"
        }
    ]

    res = client.post("/mobile/profiles/electrical/new", data={
        "name": "Profilo Elettrico Unit Test",
        "profile_key": test_key,
        "norma": "CEI EN 62353",
        "tests_json": json.dumps(tests_payload)
    }, follow_redirects=False)
    assert res.status_code == 303, f"POST /mobile/profiles/electrical/new failed: {res.status_code}"
    print("[OK] POST /mobile/profiles/electrical/new OK")

    # Verify in DB
    conn = real_server.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM profiles WHERE profile_key = %s AND is_deleted = FALSE", (test_key,))
    prof_row = cur.fetchone()
    assert prof_row is not None, "Created electrical profile not found in DB"
    prof_uuid = prof_row["uuid"]
    prof_id = prof_row["id"]

    cur.execute("SELECT * FROM profile_tests WHERE profile_id = %s AND is_deleted = FALSE", (prof_id,))
    pt_rows = cur.fetchall()
    assert len(pt_rows) == 2, f"Expected 2 tests, got {len(pt_rows)}"
    conn.close()
    print("[OK] Electrical profile & tests verified in DB")

    # 4. Test Edit Electrical Profile
    res = client.get(f"/mobile/profiles/electrical/{prof_uuid}/edit")
    assert res.status_code == 200, f"GET edit electrical failed: {res.status_code}"
    assert "Profilo Elettrico Unit Test" in res.text

    tests_payload[0]["limit_value"] = "0.15"
    res = client.post(f"/mobile/profiles/electrical/{prof_uuid}/edit", data={
        "name": "Profilo Elettrico Modificato",
        "profile_key": test_key,
        "norma": "CEI EN 62353:2020",
        "tests_json": json.dumps(tests_payload)
    }, follow_redirects=False)
    assert res.status_code == 303, f"POST edit electrical failed: {res.status_code}"
    print("[OK] POST /mobile/profiles/electrical/{uuid}/edit OK")

    # 5. Test Duplicate Electrical Profile
    res = client.post(f"/mobile/profiles/electrical/{prof_uuid}/duplicate", follow_redirects=False)
    assert res.status_code == 303, f"POST duplicate electrical failed: {res.status_code}"
    print("[OK] POST /mobile/profiles/electrical/{uuid}/duplicate OK")

    # 6. Test Delete Electrical Profile
    res = client.post(f"/mobile/profiles/electrical/{prof_uuid}/delete", follow_redirects=False)
    assert res.status_code == 303, f"POST delete electrical failed: {res.status_code}"
    print("[OK] POST /mobile/profiles/electrical/{uuid}/delete OK")

    # 7. Test Create Functional Profile
    func_key = f"TEST_FUNC_{uuid.uuid4().hex[:6].upper()}"
    sections_payload = [
        {
            "key": "sec_1",
            "title": "Verifiche Visive",
            "section_type": "fields",
            "fields": [
                {
                    "key": "fld_integrita",
                    "label": "Integrità Strutturale",
                    "field_type": "esito_pass_fail"
                }
            ]
        },
        {
            "key": "sec_2",
            "title": "Misure di Prestazione",
            "section_type": "fields",
            "fields": [
                {
                    "key": "fld_output_power",
                    "label": "Potenza Erogata",
                    "field_type": "misura_numerica",
                    "min_value": "90",
                    "max_value": "110",
                    "unit": "W"
                },
                {
                    "key": "fld_condizione",
                    "label": "Stato di Usura",
                    "field_type": "menu_a_tendina",
                    "options": ["Nuovo", "Normale", "Usurato"]
                }
            ]
        }
    ]

    res = client.post("/mobile/profiles/functional/new", data={
        "name": "Elettromedicale Custom Test",
        "profile_key": func_key,
        "device_type": "Elettromedicale",
        "schema_json": json.dumps(sections_payload)
    }, follow_redirects=False)
    assert res.status_code == 303, f"POST /mobile/profiles/functional/new failed: {res.status_code}"
    print("[OK] POST /mobile/profiles/functional/new OK")

    # Verify in DB
    conn = real_server.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM functional_profiles WHERE profile_key = %s AND is_deleted = FALSE", (func_key,))
    fp_row = cur.fetchone()
    assert fp_row is not None, "Created functional profile not found in DB"
    fp_uuid = fp_row["uuid"]
    conn.close()
    print("[OK] Functional profile verified in DB")

    # 8. Test Edit Functional Profile
    res = client.get(f"/mobile/profiles/functional/{fp_uuid}/edit")
    assert res.status_code == 200, f"GET edit functional failed: {res.status_code}"
    assert "Elettromedicale Custom Test" in res.text

    sections_payload[1]["fields"][0]["min_value"] = "95"
    res = client.post(f"/mobile/profiles/functional/{fp_uuid}/edit", data={
        "name": "Elettromedicale Custom Modificato",
        "profile_key": func_key,
        "device_type": "Elettromedicale Avanzato",
        "schema_json": json.dumps(sections_payload)
    }, follow_redirects=False)
    assert res.status_code == 303, f"POST edit functional failed: {res.status_code}"
    print("[OK] POST /mobile/profiles/functional/{uuid}/edit OK")

    # 9. Test Duplicate Functional Profile
    res = client.post(f"/mobile/profiles/functional/{fp_uuid}/duplicate", follow_redirects=False)
    assert res.status_code == 303, f"POST duplicate functional failed: {res.status_code}"
    print("[OK] POST /mobile/profiles/functional/{uuid}/duplicate OK")

    # 10. Test Delete Functional Profile
    res = client.post(f"/mobile/profiles/functional/{fp_uuid}/delete", follow_redirects=False)
    assert res.status_code == 303, f"POST delete functional failed: {res.status_code}"
    print("[OK] POST /mobile/profiles/functional/{uuid}/delete OK")

    print("\nALL MOBILE PROFILES TESTS PASSED SUCCESSFULLY! (100%)")

if __name__ == "__main__":
    run_tests()
