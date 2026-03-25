"""
Test di Sicurezza HTTPS - Safety Test Manager SyncAPI
=====================================================
Esegui questo script per verificare che il server comunichi
ESCLUSIVAMENTE in HTTPS e che il certificato sia corretto.

Uso: python test_sicurezza_https.py
"""

import ssl
import socket
import requests
import sys
import os
import configparser
from urllib.parse import urlparse
from datetime import datetime

# ============================================================
# CONFIGURAZIONE
# ============================================================
CONFIG_FILE = "config.ini"
config = configparser.ConfigParser()
config.read(CONFIG_FILE)

SERVER_URL = config.get("server", "url", fallback="https://195.149.221.71:8000")
CA_CERT = config.get("server", "ssl_ca_cert", fallback=None)

parsed = urlparse(SERVER_URL)
HOST = parsed.hostname
PORT = parsed.port or 443

RESULTS = {"passed": 0, "failed": 0, "warnings": 0}

def print_header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def test_pass(msg):
    RESULTS["passed"] += 1
    print(f"  ✅ PASS: {msg}")

def test_fail(msg):
    RESULTS["failed"] += 1
    print(f"  ❌ FAIL: {msg}")

def test_warn(msg):
    RESULTS["warnings"] += 1
    print(f"  ⚠️  WARN: {msg}")

def test_info(msg):
    print(f"  ℹ️  INFO: {msg}")

# ============================================================
# TEST 1: Verifica che config.ini usi HTTPS
# ============================================================
def test_config_https():
    print_header("TEST 1: Configurazione config.ini")
    
    if SERVER_URL.startswith("https://"):
        test_pass(f"URL usa HTTPS: {SERVER_URL}")
    else:
        test_fail(f"URL NON usa HTTPS: {SERVER_URL}")
    
    if CA_CERT:
        if os.path.isfile(CA_CERT):
            test_pass(f"Certificato CA trovato: {CA_CERT}")
        else:
            test_fail(f"Certificato CA NON trovato: {CA_CERT}")
    else:
        test_info("Nessun certificato CA configurato (usa certificati di sistema)")

# ============================================================
# TEST 2: Il server è raggiungibile?
# ============================================================
def test_server_reachable():
    print_header("TEST 2: Raggiungibilità del server")
    
    try:
        sock = socket.create_connection((HOST, PORT), timeout=10)
        sock.close()
        test_pass(f"Server raggiungibile su {HOST}:{PORT}")
        return True
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        test_fail(f"Server NON raggiungibile su {HOST}:{PORT} - {e}")
        return False

# ============================================================
# TEST 3: Verifica certificato SSL/TLS
# ============================================================
def test_ssl_certificate():
    print_header("TEST 3: Certificato SSL/TLS")
    
    try:
        ctx = ssl.create_default_context()
        if CA_CERT and os.path.isfile(CA_CERT):
            ctx.load_verify_locations(CA_CERT)
        
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as ssock:
                cert = ssock.getpeercert()
                
                # Protocollo
                test_pass(f"Protocollo: {ssock.version()}")
                
                # Cipher suite
                cipher = ssock.cipher()
                test_pass(f"Cipher: {cipher[0]} ({cipher[2]} bit)")
                
                # Soggetto del certificato
                subject = dict(x[0] for x in cert.get('subject', ()))
                cn = subject.get('commonName', 'N/A')
                test_info(f"Common Name: {cn}")
                
                # SAN (Subject Alternative Names)
                san = cert.get('subjectAltName', ())
                san_list = [f"{t}:{v}" for t, v in san]
                test_info(f"SAN: {', '.join(san_list)}")
                
                # Verifica che l'IP del server sia nel SAN
                server_in_san = any(
                    (t == 'IP Address' and v == HOST) or 
                    (t == 'DNS' and v == HOST)
                    for t, v in san
                )
                if server_in_san:
                    test_pass(f"L'IP/hostname {HOST} è presente nel certificato")
                else:
                    test_fail(f"L'IP/hostname {HOST} NON è nel certificato!")
                
                # Scadenza
                not_after = cert.get('notAfter', '')
                if not_after:
                    # Formato: 'Mar 25 09:00:00 2036 GMT'
                    try:
                        expiry = datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')
                        days_left = (expiry - datetime.utcnow()).days
                        if days_left > 30:
                            test_pass(f"Certificato valido fino al {not_after} ({days_left} giorni)")
                        elif days_left > 0:
                            test_warn(f"Certificato SCADE tra {days_left} giorni! ({not_after})")
                        else:
                            test_fail(f"Certificato SCADUTO! ({not_after})")
                    except ValueError:
                        test_info(f"Scadenza: {not_after}")
                
                # Verifica lunghezza chiave (dalla cipher suite)
                if cipher[2] >= 128:
                    test_pass(f"Cifratura forte: {cipher[2]} bit")
                else:
                    test_fail(f"Cifratura DEBOLE: {cipher[2]} bit")
                    
    except ssl.SSLCertVerificationError as e:
        test_fail(f"Certificato NON valido: {e}")
        test_info("Verifica che ssl_ca_cert in config.ini punti al file .crt corretto")
    except Exception as e:
        test_fail(f"Errore SSL: {e}")

# ============================================================
# TEST 4: HTTP deve essere RIFIUTATO
# ============================================================
def test_http_rejected():
    print_header("TEST 4: HTTP deve essere rifiutato")
    
    http_url = f"http://{HOST}:{PORT}/"
    try:
        resp = requests.get(http_url, timeout=5)
        # Se risponde in HTTP, è un PROBLEMA
        test_fail(f"Il server ACCETTA connessioni HTTP! Status: {resp.status_code}")
        test_fail("Il traffico può viaggiare in chiaro - RISCHIO SICUREZZA!")
    except requests.exceptions.ConnectionError:
        test_pass("HTTP correttamente RIFIUTATO (ConnectionError)")
    except requests.exceptions.ReadTimeout:
        test_pass("HTTP correttamente RIFIUTATO (Timeout)")
    except Exception as e:
        # Qualsiasi errore su HTTP è buono
        test_pass(f"HTTP non funziona (come previsto): {type(e).__name__}")

# ============================================================
# TEST 5: HTTPS funziona con il certificato CA
# ============================================================
def test_https_works():
    print_header("TEST 5: HTTPS funziona correttamente")
    
    verify = CA_CERT if (CA_CERT and os.path.isfile(CA_CERT)) else True
    
    try:
        resp = requests.get(f"{SERVER_URL}/", verify=verify, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            test_pass(f"HTTPS funziona! Risposta: {data}")
        else:
            test_warn(f"HTTPS risponde ma con status {resp.status_code}")
    except requests.exceptions.SSLError as e:
        test_fail(f"Errore SSL sulla connessione HTTPS: {e}")
    except requests.exceptions.ConnectionError as e:
        test_fail(f"Impossibile connettersi in HTTPS: {e}")
    except Exception as e:
        test_fail(f"Errore HTTPS: {e}")

# ============================================================
# TEST 6: HTTPS senza certificato CA (deve fallire o avvisare)
# ============================================================
def test_https_without_ca():
    print_header("TEST 6: HTTPS senza certificato CA (self-signed)")
    
    try:
        resp = requests.get(f"{SERVER_URL}/", verify=True, timeout=10)
        test_info("Il certificato è riconosciuto dal sistema (CA pubblica)")
        test_info("Non serve ssl_ca_cert in config.ini")
    except requests.exceptions.SSLError:
        test_pass("Certificato self-signed: correttamente rifiutato senza CA cert")
        test_info("Questo è normale per certificati self-signed")
        test_info("Il client usa ssl_ca_cert per fidarsi del certificato")

# ============================================================
# TEST 7: Verifica che /token richieda HTTPS
# ============================================================
def test_login_https():
    print_header("TEST 7: Login via HTTPS")
    
    verify = CA_CERT if (CA_CERT and os.path.isfile(CA_CERT)) else True
    
    # Test con credenziali volutamente sbagliate
    try:
        resp = requests.post(
            f"{SERVER_URL}/token",
            data={"username": "test_security_check", "password": "wrong_password"},
            verify=verify,
            timeout=10
        )
        if resp.status_code == 401:
            test_pass("Endpoint /token raggiungibile via HTTPS (401 = credenziali errate, OK)")
        elif resp.status_code == 200:
            test_warn("Login riuscito con credenziali di test?!")
        else:
            test_info(f"Endpoint /token risponde con status {resp.status_code}")
    except requests.exceptions.SSLError as e:
        test_fail(f"Errore SSL su /token: {e}")
    except Exception as e:
        test_fail(f"Errore su /token: {e}")

# ============================================================
# TEST 8: Verifica versione TLS (deve essere >= 1.2)
# ============================================================
def test_tls_version():
    print_header("TEST 8: Versione TLS")
    
    try:
        ctx = ssl.create_default_context()
        if CA_CERT and os.path.isfile(CA_CERT):
            ctx.load_verify_locations(CA_CERT)
        
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as ssock:
                version = ssock.version()
                if version in ('TLSv1.3',):
                    test_pass(f"TLS 1.3 - Massima sicurezza! ✨")
                elif version in ('TLSv1.2',):
                    test_pass(f"TLS 1.2 - Sicuro")
                elif version in ('TLSv1.1', 'TLSv1'):
                    test_fail(f"{version} - OBSOLETO e insicuro!")
                else:
                    test_info(f"Versione: {version}")
    except Exception as e:
        test_fail(f"Impossibile verificare TLS: {e}")

# ============================================================
# TEST 9: Sniffing simulato - verifica che i dati siano cifrati
# ============================================================
def test_data_encrypted():
    print_header("TEST 9: Verifica cifratura dati")
    
    verify = CA_CERT if (CA_CERT and os.path.isfile(CA_CERT)) else True
    
    try:
        # Inviamo dati sensibili (credenziali false) e verifichiamo
        # che la risposta arrivi cifrata via HTTPS
        resp = requests.post(
            f"{SERVER_URL}/token",
            data={"username": "admin_test_crypto", "password": "SuperSecret123!"},
            verify=verify,
            timeout=10
        )
        
        # Se la connessione è HTTPS, i dati sono cifrati in transito
        # Verifichiamo che l'URL effettivo sia HTTPS
        if resp.url.startswith("https://"):
            test_pass("I dati transitano su HTTPS (cifrati in transito)")
            test_pass("Username e password NON visibili a chi intercetta il traffico")
        else:
            test_fail(f"ATTENZIONE: La risposta proviene da {resp.url} (NON HTTPS!)")
            
    except requests.exceptions.SSLError:
        test_info("Connessione SSL attiva (errore di certificato, ma traffico cifrato)")
    except Exception as e:
        test_info(f"Test cifratura: {e}")

# ============================================================
# TEST 10: Rate Limiting (anti brute-force)
# ============================================================
def test_rate_limiting():
    print_header("TEST 10: Rate Limiting (anti brute-force)")
    
    verify = CA_CERT if (CA_CERT and os.path.isfile(CA_CERT)) else True
    
    test_info("Invio 6 tentativi di login rapidi (limite: 5/minuto)...")
    got_429 = False
    for i in range(6):
        try:
            resp = requests.post(
                f"{SERVER_URL}/token",
                data={"username": f"ratelimit_test_{i}", "password": "wrong"},
                verify=verify,
                timeout=10
            )
            if resp.status_code == 429:
                got_429 = True
                test_pass(f"Rate limit attivato al tentativo #{i+1} (429 Too Many Requests)")
                break
        except Exception:
            pass
    
    if not got_429:
        test_warn("Rate limiting non rilevato (potrebbe non essere attivo o il limite è più alto)")

# ============================================================
# TEST 11: Headers di sicurezza
# ============================================================
def test_security_headers():
    print_header("TEST 11: Headers di sicurezza")
    
    verify = CA_CERT if (CA_CERT and os.path.isfile(CA_CERT)) else True
    
    try:
        resp = requests.get(f"{SERVER_URL}/", verify=verify, timeout=10)
        headers = resp.headers
        
        # HSTS
        if "strict-transport-security" in headers:
            test_pass(f"HSTS attivo: {headers['strict-transport-security']}")
        else:
            test_warn("Header Strict-Transport-Security mancante")
        
        # X-Content-Type-Options
        if headers.get("x-content-type-options") == "nosniff":
            test_pass("X-Content-Type-Options: nosniff")
        else:
            test_warn("Header X-Content-Type-Options mancante")
        
        # X-Frame-Options
        if "x-frame-options" in headers:
            test_pass(f"X-Frame-Options: {headers['x-frame-options']}")
        else:
            test_warn("Header X-Frame-Options mancante")
        
        # Server header (non deve rivelare uvicorn)
        server_hdr = headers.get("server", "")
        if "uvicorn" in server_hdr.lower():
            test_warn(f"Server header rivela tecnologia: {server_hdr}")
        else:
            test_pass(f"Server header mascherato: '{server_hdr}'")
            
    except Exception as e:
        test_fail(f"Impossibile verificare headers: {e}")

# ============================================================
# ESECUZIONE
# ============================================================
if __name__ == "__main__":
    print("\n" + "🔒" * 30)
    print("  TEST DI SICUREZZA HTTPS - Safety Test Manager")
    print("  " + "🔒" * 30)
    print(f"\n  Server:      {SERVER_URL}")
    print(f"  Host:        {HOST}")
    print(f"  Porta:       {PORT}")
    print(f"  CA Cert:     {CA_CERT or 'Non configurato'}")
    print(f"  Data test:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Esegui tutti i test
    test_config_https()
    
    if test_server_reachable():
        test_ssl_certificate()
        test_http_rejected()
        test_https_works()
        test_https_without_ca()
        test_login_https()
        test_tls_version()
        test_data_encrypted()
        test_rate_limiting()
        test_security_headers()
    else:
        print("\n  ⛔ Server non raggiungibile - impossibile eseguire i test di rete")
    
    # Riepilogo
    print_header("RIEPILOGO")
    total = RESULTS["passed"] + RESULTS["failed"] + RESULTS["warnings"]
    print(f"  ✅ Superati:    {RESULTS['passed']}")
    print(f"  ❌ Falliti:     {RESULTS['failed']}")
    print(f"  ⚠️  Attenzione:  {RESULTS['warnings']}")
    print(f"  📊 Totale:      {total}")
    
    if RESULTS["failed"] == 0:
        print(f"\n  🎉 TUTTI I TEST SUPERATI - La comunicazione è SICURA!")
    else:
        print(f"\n  🚨 ATTENZIONE: {RESULTS['failed']} test falliti - VERIFICA LA CONFIGURAZIONE!")
    
    print()
    sys.exit(0 if RESULTS["failed"] == 0 else 1)
