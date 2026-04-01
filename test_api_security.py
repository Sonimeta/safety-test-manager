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
from datetime import datetime, timedelta
from urllib.parse import urlparse

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
VERBOSE = False

def print_header(title):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")

def test_pass(msg):
    RESULTS["passed"] += 1
    print(f"  ✅ PASS: {msg}")

def test_fail(msg):
    RESULTS["failed"] += 1
    print(f"  ❌ FAIL: {msg}")

def test_warn(msg):
    RESULTS["warnings"] += 1
    print(f"  ⚠️  WARN: {msg}")

def test_skip(msg):
    RESULTS["skipped"] += 1
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
    print_header("TEST 4: SQL Injection")

    sqli_payloads = [
        "' OR '1'='1",
        "admin'--",
        "'; DROP TABLE users; --",
        "' UNION SELECT username, hashed_password FROM users --",
        "admin'; WAITFOR DELAY '0:0:5' --",
        "1; SELECT pg_sleep(5);--",
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
        huge_data = {"customers": [{"uuid": f"fake-{i}", "name": "X" * 1000} for i in range(100)]}
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
def test_rate_limiting():
    print_header("TEST 9: Rate Limiting (anti brute-force)")

    # 9.1 Login rate limiting (limite: 5/minuto)
    test_info("Test rate limiting login: invio 7 tentativi rapidi...")
    got_429 = False
    for i in range(7):
        try:
            resp = requests.post(
                f"{SERVER_URL}/token",
                data={"username": f"ratelimit_test_{i}_{time.time()}", "password": "wrong"},
                verify=SSL_VERIFY, timeout=TIMEOUT
            )
            if resp.status_code == 429:
                got_429 = True
                # Verifica header Retry-After
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    test_pass(f"Rate limit login attivato al tentativo #{i+1} con Retry-After: {retry_after}s")
                else:
                    test_warn(f"Rate limit login attivato al tentativo #{i+1} ma senza header Retry-After")
                break
        except Exception:
            pass

    if not got_429:
        test_warn("Rate limiting login non rilevato dopo 7 tentativi (limite potrebbe essere più alto)")

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
    print_header("TEST 12: XSS e Header Injection")

    # 12.1 XSS nel campo username
    xss_payloads = [
        "<script>alert('XSS')</script>",
        "admin<img src=x onerror=alert(1)>",
        "admin\"><svg/onload=alert(1)>",
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

    # 12.2 Header injection (CRLF)
    try:
        resp = requests.post(
            f"{SERVER_URL}/token",
            data={"username": "admin\r\nX-Injected: true", "password": "test"},
            verify=SSL_VERIFY, timeout=TIMEOUT
        )
        if "x-injected" not in resp.headers:
            test_pass("CRLF header injection bloccata")
        else:
            test_fail("CRLF header injection POSSIBILE!")
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
        test_rate_limiting()
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

    print()
    sys.exit(0 if RESULTS["failed"] == 0 else 1)
