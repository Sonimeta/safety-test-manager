import requests
import sys

# CONFIGURA QUI L'ENDPOINT DELLE TUE API
API_BASE_URL = "https://195.149.221.71:8000"  # Cambia con l'URL reale

# Percorsi da testare (aggiungi altri endpoint se vuoi)
ENDPOINTS = ["/", "/docs", "/openapi.json"]

# Header di sicurezza attesi
REQUIRED_HEADERS = [
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "X-XSS-Protection",
    "Content-Security-Policy",
]

# Parole chiave da NON trovare nelle risposte (per evitare info sensibili)
SENSITIVE_KEYWORDS = ["traceback", "password", "exception", "error", "stack"]

def test_https_only():
    try:
        r = requests.get(API_BASE_URL.replace("https://", "http://"), timeout=3)
        if r.status_code < 400:
            print("[FAIL] L'API risponde anche su HTTP! Solo HTTPS deve essere abilitato.")
        else:
            print("[OK] L'API non risponde su HTTP.")
    except Exception:
        print("[OK] L'API non risponde su HTTP.")

def test_security_headers():
    for endpoint in ENDPOINTS:
        url = API_BASE_URL + endpoint
        try:
            r = requests.get(url, verify=False, timeout=5)
            missing = [h for h in REQUIRED_HEADERS if h not in r.headers]
            if missing:
                print(f"[WARN] Mancano header di sicurezza su {endpoint}: {missing}")
            else:
                print(f"[OK] Tutti gli header di sicurezza presenti su {endpoint}")
        except Exception as e:
            print(f"[FAIL] Errore su {url}: {e}")

def test_sensitive_info():
    for endpoint in ENDPOINTS:
        url = API_BASE_URL + endpoint
        try:
            r = requests.get(url, verify=False, timeout=5)
            for word in SENSITIVE_KEYWORDS:
                if word in r.text.lower():
                    print(f"[FAIL] '{word}' trovato nella risposta di {endpoint}")
        except Exception as e:
            print(f"[FAIL] Errore su {url}: {e}")

def test_rate_limiting():
    endpoint = ENDPOINTS[0]
    url = API_BASE_URL + endpoint
    print(f"[INFO] Test rate limiting su {endpoint}...")
    success = 0
    too_many = 0
    for i in range(20):
        try:
            r = requests.get(url, verify=False, timeout=3)
            if r.status_code == 429:
                too_many += 1
            elif r.status_code < 400:
                success += 1
        except Exception as e:
            print(f"[WARN] Errore durante il test rate limiting: {e}")
    if too_many > 0:
        print(f"[OK] Rate limiting attivo: {too_many} risposte 429 su 20 richieste.")
    else:
        print(f"[WARN] Nessuna risposta 429: rate limiting non rilevato su {endpoint}.")

def main():
    print("--- TEST SICUREZZA API ---")
    test_https_only()
    test_security_headers()
    test_sensitive_info()
    test_rate_limiting()
    print("--- FINE TEST ---")

if __name__ == "__main__":
    main()
