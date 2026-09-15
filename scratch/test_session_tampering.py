# scratch/test_session_tampering.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import tempfile
from datetime import datetime, timezone, timedelta
from jose import jwt
from app import auth_manager, config

def run_tests():
    print("=== TESTING SESSION ANTI-TAMPERING & SECURITY ===")

    # Setup temp session file
    temp_dir = tempfile.mkdtemp()
    temp_session_file = os.path.join(temp_dir, "test_session.json")
    config.SESSION_FILE = temp_session_file

    SECRET_KEY = "dummy_secret_for_test_1234567890123456"

    # Create a technician JWT token
    exp_future = (datetime.now(timezone.utc) + timedelta(days=7)).timestamp()
    tech_token = jwt.encode({
        "sub": "mario_tech",
        "role": "technician",
        "full_name": "Mario Tecnico",
        "sede": "MILANO",
        "exp": exp_future
    }, SECRET_KEY, algorithm="HS256")

    # 1. Normal legitimate session test
    with open(temp_session_file, "w") as f:
        json.dump({
            "username": "mario_tech",
            "role": "technician",
            "token": f"Bearer {tech_token}",
            "full_name": "Mario Tecnico",
            "sede": "MILANO"
        }, f)

    loaded = auth_manager.load_session_from_disk()
    assert loaded == True, "Legitimate session must load successfully"
    assert auth_manager.get_current_role() == "technician", "Role must be technician"
    assert auth_manager.get_current_username() == "mario_tech", "Username must be mario_tech"
    assert auth_manager.get_current_sede() == "MILANO", "Sede must be MILANO"
    print("[OK] Test 1: Legitimate technician session loaded successfully with role=technician")

    # 2. Tampering test: User modifies "role" to "admin" in session.json
    print("\n--- Simulating tampering of 'role' -> 'admin' in session.json ---")
    with open(temp_session_file, "w") as f:
        json.dump({
            "username": "mario_tech",
            "role": "admin",  # <-- MALICIOUS EDIT
            "token": f"Bearer {tech_token}",
            "full_name": "Mario Tecnico",
            "sede": "MILANO"
        }, f)

    tamper_loaded = auth_manager.load_session_from_disk()
    assert tamper_loaded == False, "Tampered session MUST be rejected!"
    assert not os.path.exists(temp_session_file), "Tampered session file MUST be deleted!"
    assert auth_manager.get_current_role() is None, "Current user role must be reset"
    print("[OK] Test 2: Role tampering detected! Session was rejected and destroyed.")

    # 3. Tampering test: User modifies "username" to "superadmin" in session.json
    print("\n--- Simulating tampering of 'username' in session.json ---")
    with open(temp_session_file, "w") as f:
        json.dump({
            "username": "superadmin",  # <-- MALICIOUS EDIT
            "role": "technician",
            "token": f"Bearer {tech_token}",
            "full_name": "Mario Tecnico",
            "sede": "MILANO"
        }, f)

    tamper_user_loaded = auth_manager.load_session_from_disk()
    assert tamper_user_loaded == False, "Tampered username session MUST be rejected!"
    assert not os.path.exists(temp_session_file), "Tampered session file MUST be deleted!"
    print("[OK] Test 3: Username tampering detected! Session was rejected and destroyed.")

    # 4. Expired token test
    print("\n--- Testing expired JWT token ---")
    exp_past = (datetime.now(timezone.utc) - timedelta(days=1)).timestamp()
    expired_token = jwt.encode({
        "sub": "mario_tech",
        "role": "technician",
        "full_name": "Mario Tecnico",
        "sede": "MILANO",
        "exp": exp_past
    }, SECRET_KEY, algorithm="HS256")

    with open(temp_session_file, "w") as f:
        json.dump({
            "username": "mario_tech",
            "role": "technician",
            "token": f"Bearer {expired_token}",
            "full_name": "Mario Tecnico",
            "sede": "MILANO"
        }, f)

    expired_loaded = auth_manager.load_session_from_disk()
    assert expired_loaded == False, "Expired session MUST be rejected!"
    print("[OK] Test 4: Expired token rejected successfully.")

    print("\nALL SESSION ANTI-TAMPERING & SECURITY TESTS PASSED! (100%)")

if __name__ == "__main__":
    run_tests()
