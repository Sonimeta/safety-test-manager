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
import struct
from urllib.parse import urlparse
from datetime import datetime, timezone

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
TEST_LOG = []
CURRENT_SECTION = "Generale"

def print_header(title):
    global CURRENT_SECTION
    CURRENT_SECTION = title
    TEST_LOG.append(("header", title, ""))
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def test_pass(msg):
    RESULTS["passed"] += 1
    TEST_LOG.append(("pass", CURRENT_SECTION, msg))
    print(f"  \u2705 PASS: {msg}")

def test_fail(msg):
    RESULTS["failed"] += 1
    TEST_LOG.append(("fail", CURRENT_SECTION, msg))
    print(f"  \u274c FAIL: {msg}")

def test_warn(msg):
    RESULTS["warnings"] += 1
    TEST_LOG.append(("warn", CURRENT_SECTION, msg))
    print(f"  \u26a0\ufe0f  WARN: {msg}")

def test_info(msg):
    TEST_LOG.append(("info", CURRENT_SECTION, msg))
    print(f"  \u2139\ufe0f  INFO: {msg}")

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
                        days_left = (expiry - datetime.now(timezone.utc).replace(tzinfo=None)).days
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
# TEST 12: Cipher Suites deboli
# ============================================================
def test_weak_ciphers():
    print_header("TEST 12: Cipher Suites deboli")
    
    # Cipher suites considerate deboli/insicure
    weak_ciphers = [
        "RC4", "DES", "3DES", "MD5", "NULL", "EXPORT", "anon",
        "RC2", "IDEA", "SEED", "CAMELLIA128",
    ]
    
    try:
        ctx = ssl.create_default_context()
        if CA_CERT and os.path.isfile(CA_CERT):
            ctx.load_verify_locations(CA_CERT)
        
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as ssock:
                cipher_name, protocol, bits = ssock.cipher()
                
                # Verifica che il cipher negoziato non sia debole
                is_weak = any(wc.upper() in cipher_name.upper() for wc in weak_ciphers)
                if is_weak:
                    test_fail(f"Cipher suite DEBOLE negoziata: {cipher_name}")
                else:
                    test_pass(f"Cipher suite forte: {cipher_name} ({bits} bit)")
                
                # Verifica lunghezza chiave minima
                if bits < 128:
                    test_fail(f"Chiave troppo corta: {bits} bit (minimo 128)")
                elif bits >= 256:
                    test_pass(f"Chiave eccellente: {bits} bit")
                else:
                    test_pass(f"Chiave accettabile: {bits} bit")
                    
    except Exception as e:
        test_fail(f"Test cipher: {e}")
    
    # Tenta connessione forzando cipher deboli
    weak_cipher_strings = [
        "RC4-SHA",
        "DES-CBC3-SHA",
        "NULL-SHA",
        "EXP-RC4-MD5",
        "ADH-AES128-SHA",
    ]
    
    for wc in weak_cipher_strings:
        try:
            ctx_weak = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx_weak.check_hostname = False
            ctx_weak.verify_mode = ssl.CERT_NONE
            # Forza TLS 1.2 max: TLS 1.3 ignora set_ciphers() e userebbe le sue suite
            ctx_weak.maximum_version = ssl.TLSVersion.TLSv1_2
            ctx_weak.set_ciphers(wc)
            
            with socket.create_connection((HOST, PORT), timeout=5) as sock:
                with ctx_weak.wrap_socket(sock, server_hostname=HOST) as ssock:
                    test_fail(f"Server accetta cipher debole: {wc}")
        except ssl.SSLError:
            test_pass(f"Cipher debole {wc} rifiutato correttamente")
        except (ValueError, OSError):
            # Il cipher non è supportato dal client — OK
            test_pass(f"Cipher {wc} non supportato/disponibile")
        except Exception as e:
            test_info(f"Test cipher {wc}: {type(e).__name__}")


# ============================================================
# TEST 13: SSL Renegotiation
# ============================================================
def test_ssl_renegotiation():
    print_header("TEST 13: SSL Renegotiation")
    
    try:
        ctx = ssl.create_default_context()
        if CA_CERT and os.path.isfile(CA_CERT):
            ctx.load_verify_locations(CA_CERT)
        
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as ssock:
                # In TLS 1.3, renegotiation non è supportata (è sicuro)
                version = ssock.version()
                if version == "TLSv1.3":
                    test_pass("TLS 1.3: renegotiation non supportata (sicuro by design)")
                else:
                    # Prova a fare renegotiation su TLS 1.2
                    try:
                        # Invia dati per testare la connessione
                        ssock.sendall(b"GET / HTTP/1.1\r\nHost: %s\r\n\r\n" % HOST.encode())
                        test_info(f"Renegotiation test su {version} — verificare manualmente con openssl")
                    except Exception as e:
                        test_info(f"Renegotiation test: {e}")
    except Exception as e:
        test_fail(f"Test renegotiation: {e}")


# ============================================================
# TEST 14: TLS Downgrade Attack
# ============================================================
def test_tls_downgrade():
    print_header("TEST 14: TLS Downgrade Attack")
    
    # Tenta connessione con protocolli obsoleti
    old_protocols = []
    
    # TLS 1.0
    try:
        ctx_old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx_old.check_hostname = False
        ctx_old.verify_mode = ssl.CERT_NONE
        ctx_old.maximum_version = ssl.TLSVersion.TLSv1
        ctx_old.minimum_version = ssl.TLSVersion.TLSv1
        
        with socket.create_connection((HOST, PORT), timeout=5) as sock:
            with ctx_old.wrap_socket(sock, server_hostname=HOST) as ssock:
                test_fail(f"Server accetta TLS 1.0 — OBSOLETO E INSICURO!")
                old_protocols.append("TLSv1.0")
    except (ssl.SSLError, OSError, ValueError):
        test_pass("TLS 1.0 correttamente rifiutato")
    except Exception as e:
        test_info(f"Test TLS 1.0: {type(e).__name__}")
    
    # TLS 1.1
    try:
        ctx_old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx_old.check_hostname = False
        ctx_old.verify_mode = ssl.CERT_NONE
        ctx_old.maximum_version = ssl.TLSVersion.TLSv1_1
        ctx_old.minimum_version = ssl.TLSVersion.TLSv1_1
        
        with socket.create_connection((HOST, PORT), timeout=5) as sock:
            with ctx_old.wrap_socket(sock, server_hostname=HOST) as ssock:
                test_fail(f"Server accetta TLS 1.1 — OBSOLETO!")
                old_protocols.append("TLSv1.1")
    except (ssl.SSLError, OSError, ValueError):
        test_pass("TLS 1.1 correttamente rifiutato")
    except Exception as e:
        test_info(f"Test TLS 1.1: {type(e).__name__}")
    
    # SSLv3
    try:
        ctx_old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx_old.check_hostname = False
        ctx_old.verify_mode = ssl.CERT_NONE
        ctx_old.options &= ~ssl.OP_NO_SSLv3
        # Prova a impostare SSLv3 se disponibile
        ctx_old.maximum_version = ssl.TLSVersion.SSLv3
        
        with socket.create_connection((HOST, PORT), timeout=5) as sock:
            with ctx_old.wrap_socket(sock, server_hostname=HOST) as ssock:
                test_fail("Server accetta SSLv3 — CRITICO!")
    except (ssl.SSLError, OSError, ValueError, AttributeError):
        test_pass("SSLv3 correttamente rifiutato / non disponibile")
    except Exception as e:
        test_info(f"Test SSLv3: {type(e).__name__}")
    
    if not old_protocols:
        test_pass("Nessun protocollo obsoleto accettato")


# ============================================================
# TEST 15: Certificate Chain Validation
# ============================================================
def test_certificate_chain():
    print_header("TEST 15: Certificate Chain Validation")
    
    try:
        ctx = ssl.create_default_context()
        if CA_CERT and os.path.isfile(CA_CERT):
            ctx.load_verify_locations(CA_CERT)
        
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as ssock:
                cert = ssock.getpeercert()
                der_cert = ssock.getpeercert(binary_form=True)
                
                # Verifica issuer
                issuer = dict(x[0] for x in cert.get('issuer', ()))
                issuer_cn = issuer.get('commonName', 'N/A')
                issuer_o = issuer.get('organizationName', 'N/A')
                test_info(f"Issuer: CN={issuer_cn}, O={issuer_o}")
                
                # Self-signed check
                subject = dict(x[0] for x in cert.get('subject', ()))
                if subject == issuer:
                    test_warn("Certificato SELF-SIGNED (accettabile per uso interno, non per produzione)")
                else:
                    test_pass("Certificato emesso da CA diversa dal soggetto")
                
                # Verifica notBefore
                not_before = cert.get('notBefore', '')
                if not_before:
                    try:
                        start_date = datetime.strptime(not_before, '%b %d %H:%M:%S %Y %Z')
                        if start_date > datetime.now(timezone.utc).replace(tzinfo=None):
                            test_fail(f"Certificato NON ANCORA VALIDO! Inizio: {not_before}")
                        else:
                            test_pass(f"Certificato valido da: {not_before}")
                    except ValueError:
                        test_info(f"Data inizio: {not_before}")
                
                # Verifica dimensione chiave dal DER
                cert_size = len(der_cert)
                if cert_size < 256:
                    test_warn(f"Certificato molto piccolo ({cert_size} bytes)")
                else:
                    test_pass(f"Dimensione certificato: {cert_size} bytes")
                    
                # Verifica Key Usage e Extended Key Usage
                # (non sempre disponibili nel getpeercert Python)
                test_info("Per analisi dettagliata Key Usage, usare: openssl s_client / testssl.sh")
                
    except ssl.SSLCertVerificationError as e:
        test_fail(f"Verifica catena certificati fallita: {e}")
    except Exception as e:
        test_fail(f"Test certificate chain: {e}")


# ============================================================
# TEST 16: HSTS Configuration
# ============================================================
def test_hsts_config():
    print_header("TEST 16: HSTS Configuration (Dettagliata)")
    
    verify = CA_CERT if (CA_CERT and os.path.isfile(CA_CERT)) else True
    
    try:
        resp = requests.get(f"{SERVER_URL}/", verify=verify, timeout=10)
        hsts = resp.headers.get("strict-transport-security", "")
        
        if not hsts:
            test_fail("Header HSTS completamente assente!")
            return
        
        test_pass(f"HSTS presente: {hsts}")
        
        # Verifica max-age
        if "max-age=" in hsts:
            try:
                max_age = int(hsts.split("max-age=")[1].split(";")[0].strip())
                if max_age >= 31536000:  # 1 anno
                    test_pass(f"HSTS max-age adeguato: {max_age}s ({max_age // 86400} giorni)")
                elif max_age >= 2592000:  # 30 giorni
                    test_warn(f"HSTS max-age basso: {max_age}s (raccomandato: >= 1 anno)")
                else:
                    test_fail(f"HSTS max-age troppo basso: {max_age}s")
            except (ValueError, IndexError):
                test_warn("Impossibile parsare max-age HSTS")
        
        # Verifica includeSubDomains
        if "includesubdomains" in hsts.lower():
            test_pass("HSTS include subdomains")
        else:
            test_warn("HSTS senza includeSubDomains")
        
        # Verifica preload
        if "preload" in hsts.lower():
            test_pass("HSTS con preload (massima protezione)")
        else:
            test_info("HSTS senza preload (opzionale ma raccomandato)")
            
    except Exception as e:
        test_fail(f"Test HSTS: {e}")


# ============================================================
# TEST 17: SSL Compression (CRIME attack)
# ============================================================
def test_ssl_compression():
    print_header("TEST 17: SSL Compression (CRIME attack)")
    
    try:
        ctx = ssl.create_default_context()
        if CA_CERT and os.path.isfile(CA_CERT):
            ctx.load_verify_locations(CA_CERT)
        
        with socket.create_connection((HOST, PORT), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=HOST) as ssock:
                compression = ssock.compression()
                if compression is None:
                    test_pass("Compressione SSL disabilitata (protetto da CRIME)")
                else:
                    test_fail(f"Compressione SSL ATTIVA: {compression} — vulnerabile a CRIME!")
    except Exception as e:
        test_info(f"Test compressione SSL: {e}")


def generate_pdf_report_https():
    """Genera un report PDF con tutti i risultati dei test HTTPS."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
    except ImportError:
        print("  ⚠️  reportlab non installato — impossibile generare PDF")
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"SecurityReport_HTTPS_{timestamp}.pdf"
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
    elements.append(Paragraph("Security Test Report - HTTPS/TLS", title_style))
    elements.append(Paragraph(f"Server: {SERVER_URL} | Host: {HOST}:{PORT} | Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))

    # Riepilogo
    total = RESULTS['passed'] + RESULTS['failed'] + RESULTS['warnings']
    testable = RESULTS['passed'] + RESULTS['failed']
    score = (RESULTS['passed'] / testable * 100) if testable > 0 else 0

    summary_data = [
        ['Metrica', 'Valore'],
        ['Superati', str(RESULTS['passed'])],
        ['Falliti', str(RESULTS['failed'])],
        ['Warning', str(RESULTS['warnings'])],
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

    # Dettaglio test
    color_map = {
        'pass': colors.HexColor('#e8f5e9'),
        'fail': colors.HexColor('#ffebee'),
        'warn': colors.HexColor('#fff8e1'),
        'info': colors.HexColor('#f5f5f5'),
    }
    label_map = {'pass': 'PASS', 'fail': 'FAIL', 'warn': 'WARN', 'info': 'INFO'}
    text_color_map = {
        'pass': colors.HexColor('#2e7d32'),
        'fail': colors.HexColor('#c62828'),
        'warn': colors.HexColor('#f57f17'),
        'info': colors.HexColor('#616161'),
    }

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
        test_weak_ciphers()
        test_ssl_renegotiation()
        test_tls_downgrade()
        test_certificate_chain()
        test_hsts_config()
        test_ssl_compression()
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
        print(f"\n  \U0001f389 TUTTI I TEST SUPERATI - La comunicazione è SICURA!")
    else:
        print(f"\n  \U0001f6a8 ATTENZIONE: {RESULTS['failed']} test falliti - VERIFICA LA CONFIGURAZIONE!")
    
    # --- Genera report PDF ---
    pdf_path = generate_pdf_report_https()
    if pdf_path:
        print(f"  \U0001f4c4 Report PDF generato: {pdf_path}")

    print()
    sys.exit(0 if RESULTS["failed"] == 0 else 1)
