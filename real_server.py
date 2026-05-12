# real_server.py (Versione Robusta con Validazione, Logging e Transazioni Atomiche)

from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Body, Request, Cookie, Response as FastAPIResponse
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, field_validator
from typing import List, Optional, Dict, Any
import psycopg2
from psycopg2 import errors, sql
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone, date, timedelta
import logging
import base64
import os
import sys
import json
import hashlib
import time
import re
import collections
from dotenv import load_dotenv
# Sicurezza
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash
from jose import JWTError, ExpiredSignatureError, jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.x509 import load_pem_x509_certificate
import base64 as _base64
from cryptography.hazmat.primitives.asymmetric import padding as _padding
from cryptography.hazmat.primitives import hashes as _hashes
import httpx

# --- CARICAMENTO .env ROBUSTO (compatibile con PyInstaller) ---
# Cerca .env in: 1) directory di lavoro corrente, 2) cartella padre dell'exe
# Questo permette di avviare sia da start_server.bat che con doppio clic sull'exe.
def _find_and_load_env():
    """Cerca e carica il file .env in modo compatibile con PyInstaller."""
    search_dirs = [
        os.getcwd(),  # Directory di lavoro corrente (es. C:\SyncAPI)
    ]
    # Se siamo in un exe PyInstaller, aggiungi la cartella padre dell'exe
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        search_dirs.append(exe_dir)
        search_dirs.append(os.path.dirname(exe_dir))  # Cartella padre (es. C:\SyncAPI se exe è in C:\SyncAPI\SyncAPI_Server\)
    
    for d in search_dirs:
        env_path = os.path.join(d, '.env')
        if os.path.isfile(env_path):
            load_dotenv(env_path)
            print(f"[CONFIG] File .env caricato da: {env_path}")
            return
    
    # Fallback: tenta load_dotenv() standard
    load_dotenv()
    print("[CONFIG] ATTENZIONE: .env non trovato nei percorsi attesi, uso variabili d'ambiente di sistema.")

_find_and_load_env()

# --- CONFIGURAZIONE LOGGING MIGLIORATA ---
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)-8s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- COSTANTI CONFIGURAZIONE ---
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 30)) # 30 giorni

# Validazione critica: SECRET_KEY e ALGORITHM devono essere configurati
if not SECRET_KEY or len(SECRET_KEY) < 32:
    logger.critical("⛔ SECRET_KEY non configurata o troppo corta (min 32 caratteri)! Controlla il file .env")
    raise RuntimeError("SECRET_KEY non configurata o troppo corta. Impossibile avviare il server in modo sicuro.")
if not ALGORITHM:
    logger.critical("⛔ ALGORITHM non configurato! Controlla il file .env")
    raise RuntimeError("ALGORITHM non configurato. Impossibile avviare il server in modo sicuro.")

# Sync configuration
SYNC_DATA_VERSION = "1.0"
MAX_PAYLOAD_SIZE = 50 * 1024 * 1024  # 50MB

# --- CLOUDFLARE ZERO TRUST ---
CLOUDFLARE_TUNNEL = os.getenv("CLOUDFLARE_TUNNEL", "false").lower() == "true"
CF_TEAM_DOMAIN = os.getenv("CF_TEAM_DOMAIN", "").rstrip("/")  # es. https://miodominio.cloudflareaccess.com
CF_ACCESS_AUD = os.getenv("CF_ACCESS_AUD", "")  # Application Audience Tag dalla dashboard

if CLOUDFLARE_TUNNEL:
    if not CF_TEAM_DOMAIN or not CF_ACCESS_AUD:
        logger.critical("⛔ CLOUDFLARE_TUNNEL=true ma CF_TEAM_DOMAIN e/o CF_ACCESS_AUD non configurati!")
        raise RuntimeError("CF_TEAM_DOMAIN e CF_ACCESS_AUD sono obbligatori con CLOUDFLARE_TUNNEL=true")
    logger.info(f"☁️  Cloudflare Zero Trust ABILITATO - Team domain: {CF_TEAM_DOMAIN}")

# Cache JWKS Cloudflare (chiavi pubbliche per validare JWT Access)
_cf_jwks_cache: dict = {"keys": [], "fetched_at": 0}
CF_JWKS_CACHE_TTL = 3600  # Ricarica le chiavi ogni ora

async def _get_cf_public_keys() -> list:
    """Recupera e memorizza nella cache le chiavi pubbliche JWKS di Cloudflare Access."""
    global _cf_jwks_cache
    now = time.time()
    if _cf_jwks_cache["keys"] and (now - _cf_jwks_cache["fetched_at"]) < CF_JWKS_CACHE_TTL:
        return _cf_jwks_cache["keys"]
    try:
        certs_url = f"{CF_TEAM_DOMAIN}/cdn-cgi/access/certs"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(certs_url)
            resp.raise_for_status()
            jwks = resp.json()
        raw_keys = jwks.get("keys", [])
        _cf_jwks_cache = {"keys": raw_keys, "fetched_at": now}
        logger.info(f"☁️  Chiavi JWKS Cloudflare aggiornate ({len(raw_keys)} chiavi)")
        return _cf_jwks_cache["keys"]
    except Exception as e:
        logger.error(f"⚠️ Impossibile recuperare JWKS Cloudflare: {e}")
        return _cf_jwks_cache["keys"]

def _jwk_dict_to_pem(jwk_dict: dict) -> str:
    """
    Converte un JWK dict RSA in una stringa PEM della chiave pubblica
    usando la libreria cryptography (già installata come dipendenza di python-jose).
    """
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization
    import base64

    def _b64_to_int(b64: str) -> int:
        # Aggiunge padding se necessario
        padded = b64 + '=' * (4 - len(b64) % 4)
        return int.from_bytes(base64.urlsafe_b64decode(padded), 'big')

    n = _b64_to_int(jwk_dict['n'])
    e = _b64_to_int(jwk_dict['e'])
    pub_numbers = RSAPublicNumbers(e, n)
    pub_key = pub_numbers.public_key(default_backend())
    return pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')


def _get_real_client_ip(request) -> str:
    """Ritorna l'IP reale del client. Con Cloudflare Tunnel usa CF-Connecting-IP."""
    if CLOUDFLARE_TUNNEL:
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip
    return request.client.host if request.client else "unknown"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
ph = PasswordHasher()

DB_PARAMS = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT")
}
TABLES_TO_SYNC = ["customers", "mti_instruments", "signatures", "profiles", "profile_tests", "functional_profiles", "destinations", "devices", "verifications", "functional_verifications", "verification_attachments", "audit_log"]

# --- AVVIO APPLICAZIONE API ---
app = FastAPI(title="Safety Test Sync API", version="1.0.0+STABLE")

# --- RATE LIMITER (protezione brute-force e DDoS) ---
class RateLimiter:
    """
    Rate limiter in-memory per IP.
    - Endpoint generici: max 60 richieste/minuto per IP
    - Endpoint /token (login): max 5 tentativi/minuto per IP (anti brute-force)
    - Blocco temporaneo: IP bloccato per 15 minuti dopo troppi tentativi di login
    """
    def __init__(self):
        # {ip: deque([timestamp, ...])} per richieste generiche
        self.requests = collections.defaultdict(lambda: collections.deque())
        # {ip: deque([timestamp, ...])} per tentativi di login FALLITI
        self.failed_login_attempts = collections.defaultdict(lambda: collections.deque())
        # {ip: timestamp_sblocco} per IP bloccati
        self.blocked_ips = {}
        
        # Limiti configurabili
        self.GENERAL_LIMIT = 60       # richieste/minuto generiche
        self.GENERAL_WINDOW = 60      # finestra in secondi
        self.LOGIN_FAIL_LIMIT = 5     # tentativi FALLITI/minuto
        self.LOGIN_WINDOW = 60        # finestra in secondi (fallimenti login)
        self.BLOCK_DURATION = 900     # blocco 15 minuti (in secondi)
        self.LOGIN_BLOCK_THRESHOLD = 10  # dopo 10 fallimenti recenti -> blocco
    
    def _cleanup(self, deq: collections.deque, window: float):
        """Rimuove i timestamp più vecchi della finestra."""
        now = time.time()
        while deq and deq[0] < now - window:
            deq.popleft()
    
    def is_blocked(self, ip: str) -> bool:
        """Verifica se un IP è temporaneamente bloccato."""
        if ip in self.blocked_ips:
            if time.time() < self.blocked_ips[ip]:
                return True
            else:
                del self.blocked_ips[ip]
        return False

    def is_login_blocked(self, ip: str) -> bool:
        """Alias semantico usato nel login endpoint."""
        return self.is_blocked(ip)
    
    def check_general(self, ip: str) -> bool:
        """Controlla il rate limit generico. Ritorna True se la richiesta è permessa."""
        if self.is_blocked(ip):
            return False
        self._cleanup(self.requests[ip], self.GENERAL_WINDOW)
        if len(self.requests[ip]) >= self.GENERAL_LIMIT:
            return False
        self.requests[ip].append(time.time())
        return True
    
    def record_failed_login(self, ip: str) -> tuple[bool, int]:
        """
        Registra un login fallito.
        Ritorna (is_blocked_now, retry_after_seconds).
        """
        now = time.time()
        self._cleanup(self.failed_login_attempts[ip], self.LOGIN_WINDOW)
        self.failed_login_attempts[ip].append(now)

        # Blocco duro dopo troppi fallimenti nella finestra.
        if len(self.failed_login_attempts[ip]) >= self.LOGIN_BLOCK_THRESHOLD:
            self.blocked_ips[ip] = now + self.BLOCK_DURATION
            logger.warning(f"🚫 IP {ip} BLOCCATO per {self.BLOCK_DURATION}s - troppi login falliti")
            return True, self.get_login_retry_after(ip)

        # Rate limit morbido sui soli fallimenti.
        if len(self.failed_login_attempts[ip]) >= self.LOGIN_FAIL_LIMIT:
            return False, self.get_login_retry_after(ip)

        return False, 0

    def clear_failed_login_attempts(self, ip: str):
        """Pulisce lo storico dei login falliti dopo un login riuscito."""
        self.failed_login_attempts.pop(ip, None)
    
    def get_retry_after(self, ip: str, is_login: bool = False) -> int:
        """Ritorna i secondi da attendere prima di riprovare."""
        if ip in self.blocked_ips:
            return max(1, int(self.blocked_ips[ip] - time.time()))
        return self.LOGIN_WINDOW if is_login else self.GENERAL_WINDOW

    def get_login_retry_after(self, ip: str) -> int:
        """Ritorna retry-after specifico per login falliti o blocco attivo."""
        if ip in self.blocked_ips:
            return max(1, int(self.blocked_ips[ip] - time.time()))
        if ip not in self.failed_login_attempts or not self.failed_login_attempts[ip]:
            return self.LOGIN_WINDOW
        oldest = self.failed_login_attempts[ip][0]
        remaining = int(self.LOGIN_WINDOW - (time.time() - oldest))
        return max(1, remaining)

rate_limiter = RateLimiter()

# --- MIDDLEWARE DI SICUREZZA ---
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request

class CloudflareZeroTrustMiddleware(BaseHTTPMiddleware):
    """
    Middleware Cloudflare Zero Trust.
    Verifica che ogni richiesta provenga da Cloudflare Access tramite il JWT
    nell'header 'Cf-Access-Jwt-Assertion'. Rifiuta tutte le richieste senza
    un token valido, garantendo che nessuno possa raggiunere il server
    bypassando il tunnel.
    Path esclusi: /health (per il monitoring interno di cloudflared).
    """
    EXCLUDED_PATHS = {"/health"}

    async def dispatch(self, request: Request, call_next):
        if not CLOUDFLARE_TUNNEL:
            return await call_next(request)

        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        cf_jwt = request.headers.get("Cf-Access-Jwt-Assertion")
        if not cf_jwt:
            logger.warning(
                f"🚫 Richiesta bloccata (no CF JWT) da IP: "
                f"{request.client.host if request.client else 'unknown'} "
                f"path={request.url.path}"
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "Accesso negato: richiesta non autorizzata da Cloudflare Access."}
            )

        # Valida il JWT con le chiavi pubbliche Cloudflare
        keys = await _get_cf_public_keys()
        if not keys:
            logger.error("⚠️ JWKS Cloudflare non disponibili, blocco la richiesta per sicurezza")
            return JSONResponse(
                status_code=503,
                content={"detail": "Servizio temporaneamente non disponibile (validazione CF)."}
            )

        # Estrai il kid dall'header JWT per selezionare la chiave corretta
        try:
            token_header = jwt.get_unverified_header(cf_jwt)
            token_kid = token_header.get("kid")
        except Exception:
            token_kid = None

        # Filtra per kid se disponibile, altrimenti prova tutte le chiavi
        candidate_keys = keys
        if token_kid:
            matched = [k for k in keys if k.get("kid") == token_kid]
            if matched:
                candidate_keys = matched

        validated = False
        last_error = None
        for key_dict in candidate_keys:
            try:
                # Converti JWK in PEM per una verifica firma affidabile
                pem = _jwk_dict_to_pem(key_dict)
                payload = jwt.decode(
                    cf_jwt,
                    pem,
                    algorithms=["RS256"],
                    options={"verify_aud": False},
                )

                # Verifica manuale audience (stringa o lista)
                token_aud = payload.get("aud", [])
                if isinstance(token_aud, str):
                    token_aud = [token_aud]
                if CF_ACCESS_AUD not in token_aud:
                    last_error = f"AUD mismatch: token={token_aud}, expected={CF_ACCESS_AUD}"
                    logger.debug(f"⚠️ CF JWT AUD non corrisponde: {last_error}")
                    continue

                # Verifica issuer (team domain) - accetta con e senza slash finale
                iss = payload.get("iss", "").rstrip("/")
                expected_iss = CF_TEAM_DOMAIN.rstrip("/")
                if iss != expected_iss:
                    last_error = f"ISS mismatch: token={iss}, expected={expected_iss}"
                    logger.debug(f"⚠️ CF JWT ISS non corrisponde: {last_error}")
                    continue

                validated = True
                request.state.cf_email = payload.get("email", payload.get("sub", "service-token"))
                break
            except ExpiredSignatureError:
                last_error = "Token scaduto"
                continue
            except JWTError as e:
                last_error = str(e)
                continue
            except Exception as e:
                last_error = str(e)
                continue

        if not validated:
            logger.warning(
                f"🚫 CF JWT non valido da IP: "
                f"{request.client.host if request.client else 'unknown'} "
                f"path={request.url.path} | motivo: {last_error}"
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "Accesso negato: token Cloudflare Access non valido o scaduto."}
            )

        return await call_next(request)

class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Middleware che applica:
    1. Rate limiting per IP
    2. Headers di sicurezza su tutte le risposte
    """
    async def dispatch(self, request: Request, call_next):
        # Ottieni IP del client (usa CF-Connecting-IP se siamo dietro Cloudflare Tunnel)
        client_ip = _get_real_client_ip(request)
        path = request.url.path

        # Rate limit generico (escluso /health per monitoring)
        if path != "/health":
            if not rate_limiter.check_general(client_ip):
                retry_after = rate_limiter.get_retry_after(client_ip)
                logger.warning(f"⚠️ Rate limit GENERALE superato per IP {client_ip}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Troppe richieste. Riprova tra {retry_after} secondi."},
                    headers={"Retry-After": str(retry_after)}
                )
        
        # Processa la richiesta
        response = await call_next(request)
        
        # Aggiungi headers di sicurezza
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        # Rimuovi completamente l'header Server per non rivelare alcuna tecnologia
        if "server" in response.headers:
            del response.headers["server"]
        
        return response

# NOTA: i middleware vengono eseguiti in ordine LIFO (ultimo aggiunto = primo eseguito)
# CloudflareZeroTrustMiddleware deve essere eseguito PRIMA di SecurityMiddleware
app.add_middleware(SecurityMiddleware)
app.add_middleware(CloudflareZeroTrustMiddleware)

# --- UTILITY DI SICUREZZA ---
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una password usando Argon2 in modo robusto."""
    try:
        # Il metodo corretto è ph.verify()
        ph.verify(hashed_password, plain_password)
        return True
    except (VerifyMismatchError, InvalidHash):
        # Se la password non corrisponde o l'hash non è valido, l'eccezione viene
        # catturata e la funzione restituisce False, come previsto.
        return False
    except Exception as e:
        logger.error(f"Errore imprevisto durante la verifica della password: {e}")
        return False

def get_password_hash(password: str) -> str:
    return ph.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def _calculate_checksum(data: dict) -> str:
    """Calcola il checksum SHA256 dei dati per validazione integrità."""
    try:
        data_str = json.dumps(data, sort_keys=True, default=str)
        checksum = hashlib.sha256(data_str.encode()).hexdigest()
        # Debug: log preview dei dati
        data_preview = data_str[:100]
        logging.debug(f"Checksum calcolato su: {data_preview}...")
        return checksum
    except Exception as e:
        logger.error(f"Errore nel calcolo del checksum: {e}")
        return ""

def _validate_checksum(data: dict, received_checksum: str) -> bool:
    """Valida il checksum dei dati ricevuti."""
    if not received_checksum:
        logger.warning("⚠ Nessun checksum ricevuto dal client")
        return True  # Passa se il client non supporta checksum
    
    calculated = _calculate_checksum(data)
    if calculated == received_checksum:
        logger.info("✓ Checksum validato")
        return True
    else:
        # DEBUG: Log dettagliato per diagnostic
        table_info = {k: len(v) if isinstance(v, list) else type(v).__name__ for k, v in data.items()}
        logger.error(f"✗ Checksum mismatch: atteso {received_checksum}, calcolato {calculated}")
        logger.error(f"   Struttura dati ricevuta: {table_info}")
        logger.debug(f"   Dati raw (primo 200 char): {json.dumps(data, sort_keys=True, default=str)[:200]}...")
        return False


# ============================================================
# ADVANCED CONFLICT ANALYSIS FOR SERVER-SIDE
# ============================================================

def _analyze_conflict_severity(client_record: dict, server_record: dict, table_name: str) -> str:
    """
    Analizza la gravità di un conflitto.
    
    Returns:
        'low' | 'medium' | 'high' | 'critical'
    """
    # Campi critici per tabella
    critical_fields = {
        'devices': ['serial_number', 'status', 'location'],
        'customers': ['name', 'email'],
        'verifications': ['test_date', 'status'],
        'profiles': ['name', 'code'],
    }
    
    affected_fields = []
    for key in client_record.keys():
        if key in server_record and client_record[key] != server_record[key]:
            affected_fields.append(key)
    
    # Controlla se campi critici sono in conflitto
    critical_table_fields = critical_fields.get(table_name, [])
    critical_conflicts = [f for f in affected_fields if f in critical_table_fields]
    
    if critical_conflicts:
        return 'high'
    elif len(affected_fields) > 5:
        return 'high'
    elif len(affected_fields) > 2:
        return 'medium'
    elif len(affected_fields) > 0:
        return 'low'
    else:
        return 'low'


def _build_conflict_response(conflict_dict: dict, analysis_severity: str) -> dict:
    """
    Costruisce un response dettagliato per il conflitto.
    Include suggerimenti e informazioni utili per il client.
    Include TUTTI i campi del record server, non solo quelli in conflitto,
    così che il client possa accettare il record completo se necessario.
    """
    client_data = conflict_dict.get('client_version', {})
    server_data = conflict_dict.get('server_version', {})
    
    # Identifica campi in conflitto
    conflicting_fields = []
    for key in client_data.keys():
        if key in server_data and client_data[key] != server_data[key]:
            conflicting_fields.append({
                'field': key,
                'client_value': client_data.get(key),
                'server_value': server_data.get(key),
                'conflict': True
            })
    
    # Genera suggerimenti di risoluzione
    client_modified = client_data.get('last_modified', '')
    server_modified = server_data.get('last_modified', '')
    more_recent = 'server' if server_modified > client_modified else 'client'
    
    suggestions = [
        {
            'option': 1,
            'strategy': 'server_wins',
            'description': f"Usa versione server ({more_recent} modification)" if more_recent == 'server' else "Usa versione server",
            'confidence': 0.9 if more_recent == 'server' else 0.7
        },
        {
            'option': 2,
            'strategy': 'client_wins',
            'description': f"Usa versione client ({more_recent} modification)" if more_recent == 'client' else "Usa versione client",
            'confidence': 0.9 if more_recent == 'client' else 0.7
        }
    ]
    
    # Se pochi campi, suggerisci merge
    if len(conflicting_fields) <= 2:
        suggestions.append({
            'option': 3,
            'strategy': 'merge',
            'description': "Tenta merge automatico",
            'confidence': 0.75
        })
    
    return {
        'uuid': conflict_dict.get('uuid'),
        'table': conflict_dict.get('table'),
        'type': 'modification_conflict',
        'severity': analysis_severity,
        'conflicting_fields': conflicting_fields,
        'field_count': len(conflicting_fields),
        'suggestions': sorted(suggestions, key=lambda x: x['confidence'], reverse=True),
        'auto_resolvable': analysis_severity in ['low', 'medium'] and len(conflicting_fields) <= 1,
        # IMPORTANTE: Includi il record server COMPLETO così il client può accettare tutti i campi
        'server_version': server_data
    }

BOOL_FIELDS_BY_TABLE = {
    "customers": ["is_deleted", "is_synced"],
    "profiles": ["is_deleted", "is_synced"],
    "functional_profiles": ["is_deleted", "is_synced"],
    "destinations": ["is_deleted", "is_synced"],
    "devices": ["is_deleted", "is_synced"],
    "profile_tests": ["is_deleted", "is_synced", "is_applied_part_test"],
    "verifications": ["is_deleted", "is_synced"],
    "functional_verifications": ["is_deleted", "is_synced"],
    "mti_instruments": ["is_deleted", "is_synced", "is_default"],
    "signatures": ["is_synced"],
    "audit_log": ["is_deleted", "is_synced"],
}

def _to_bool(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "t", "yes", "y"): return True
        if s in ("0", "false", "f", "no", "n", ""): return False
    return bool(v)

def _normalize_booleans(table_name: str, rec: dict) -> None:
    for f in BOOL_FIELDS_BY_TABLE.get(table_name, []):
        if f in rec:
            rec[f] = _to_bool(rec[f])

def _normalize_incoming_value(table_name: str, key: str, value):
    from datetime import datetime, date
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if table_name == "signatures" and key == "signature_data" and isinstance(value, str):
        try:
            return base64.b64decode(value)
        except Exception:
            logging.warning("signature_data non è base64 valido; imposto NULL.")
            return None
    if table_name == "verification_attachments" and key == "file_data" and isinstance(value, str):
        try:
            return base64.b64decode(value)
        except Exception:
            logging.warning("file_data non è base64 valido; imposto NULL.")
            return None
    return value

def get_valid_columns(cursor, table_name: str) -> set:
    """Recupera le colonne valide per una tabella dal database."""
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s
    """, (table_name,))
    rows = cursor.fetchall()
    valid_cols = { (row["column_name"] if isinstance(row, dict) else row[0]) for row in rows }
    logging.debug(f"Colonne valide per {table_name}: {sorted(valid_cols)}")
    return valid_cols

# --- COSTANTI DI VALIDAZIONE ---
ALLOWED_ROLES = {"admin", "moderator", "technician", "seg"}
MAX_USERNAME_LENGTH = 50
MIN_PASSWORD_LENGTH = 8
MAX_SIGNATURE_SIZE = 512 * 1024  # 512 KB
ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
# Magic bytes per i formati immagine più comuni
IMAGE_MAGIC_BYTES = {
    b'\x89PNG': 'image/png',
    b'\xff\xd8\xff': 'image/jpeg',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF': 'image/webp',  # WebP inizia con RIFF....WEBP
}

# --- MODELLI DATI (Pydantic) ---

class User(BaseModel):
    username: str
    role: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        if not v or not v.strip():
            raise ValueError('Username non può essere vuoto')
        if len(v) > MAX_USERNAME_LENGTH:
            raise ValueError(f'Username troppo lungo (max {MAX_USERNAME_LENGTH} caratteri)')
        if not re.match(r'^[a-zA-Z0-9_.-]+$', v):
            raise ValueError('Username può contenere solo lettere, numeri, underscore, punto e trattino')
        return v.strip()

    @field_validator('role')
    @classmethod
    def validate_role(cls, v):
        if v not in ALLOWED_ROLES:
            raise ValueError(f'Ruolo non valido. Ruoli consentiti: {", ".join(sorted(ALLOWED_ROLES))}')
        return v

class UserCreate(User):
    password: str

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f'Password troppo corta (minimo {MIN_PASSWORD_LENGTH} caratteri)')
        return v

class UserUpdate(BaseModel):
    role: Optional[str] = None
    password: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    @field_validator('role')
    @classmethod
    def validate_role(cls, v):
        if v is not None and v not in ALLOWED_ROLES:
            raise ValueError(f'Ruolo non valido. Ruoli consentiti: {", ".join(sorted(ALLOWED_ROLES))}')
        return v

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if v is not None and len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f'Password troppo corta (minimo {MIN_PASSWORD_LENGTH} caratteri)')
        return v

class Token(BaseModel):
    access_token: str
    token_type: str

class SyncRecord(BaseModel):
    model_config = ConfigDict(extra='allow')
    uuid: str
    last_modified: datetime
    is_deleted: Optional[bool] = False # Optional per tabelle come 'signatures'
    is_synced: bool

class InstrumentRecord(SyncRecord):
    is_default: bool

class SyncChanges(BaseModel):
    customers: List[SyncRecord] = []
    devices: List[SyncRecord] = []
    verifications: List[SyncRecord] = []
    functional_verifications: List[SyncRecord] = []
    mti_instruments: List[InstrumentRecord] = []
    signatures: List[SyncRecord] = []
    profiles: List[SyncRecord] = []
    profile_tests: List[SyncRecord] = []
    functional_profiles: List[SyncRecord] = []
    destinations: List[SyncRecord] = []
    verification_attachments: List[SyncRecord] = []
    system_verifications: List[SyncRecord] = []
    system_verification_devices: List[SyncRecord] = []
    audit_log: List[SyncRecord] = []

class SyncPayload(BaseModel):
    last_sync_timestamp: Optional[str]
    changes: SyncChanges
    checksum: Optional[str] = None  # SHA256 checksum dei dati
    sync_version: Optional[str] = "1.0"  # Versione del sync
    conflict_resolutions: Optional[List[dict]] = None  # Risoluzioni serial_conflict dal client


class SyncConflictDetectedError(Exception):
    """Eccezione interna per forzare rollback totale e risposta 409 su conflitti di sync."""

    def __init__(self, conflicts: List[dict]):
        super().__init__("Conflitti di sincronizzazione rilevati")
        self.conflicts = conflicts

# --- DEPENDENCY PER LA SICUREZZA ---
def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        role: Optional[str] = payload.get("role")
        if username is None or role is None:
            raise credentials_exception
        first_name = payload.get("first_name")
        last_name = payload.get("last_name")
        # Retrocompatibilità: token emessi prima della fix contenevano solo full_name.
        if first_name is None and last_name is None:
            full_name: str = payload.get("full_name", "")
            parts = full_name.split(" ", 1)
            first_name = parts[0] if parts else ""
            last_name = parts[1] if len(parts) > 1 else ""
        return User(
            username=username,
            role=role,
            first_name=first_name or None,
            last_name=last_name or None,
        )
    except ExpiredSignatureError:
        logger.warning("Token di accesso scaduto")
        raise HTTPException(
            status_code=401,
            detail="token_expired",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except JWTError:
        raise credentials_exception

# --- ENDPOINT HEALTH CHECK ---
@app.get("/health")
async def health_check():
    """Endpoint di health check per verificare disponibilità del server."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT NOW()")
        cursor.fetchone()
        cursor.close()
        conn.close()
        
        logger.info("✓ Health check completato: DB accessibile")
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": SYNC_DATA_VERSION,
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"✗ Health check fallito: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": SYNC_DATA_VERSION,
                "database": "disconnected",
                "detail": "Database non disponibile"
            }
        )

# --- FUNZIONI DATABASE SERVER ---
def get_db_connection():
    return psycopg2.connect(**DB_PARAMS)

def _ensure_hard_deletes_table():
    """Crea la tabella hard_deletes se non esiste (tombstone per propagazione eliminazioni definitive)."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hard_deletes (
                id SERIAL PRIMARY KEY,
                table_name VARCHAR(100) NOT NULL,
                record_uuid VARCHAR(255) NOT NULL,
                deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                deleted_by VARCHAR(100)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hard_deletes_deleted_at ON hard_deletes(deleted_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hard_deletes_table_uuid ON hard_deletes(table_name, record_uuid)")
        conn.commit()
        logger.info("✓ Tabella hard_deletes verificata/creata con successo")
    except Exception as e:
        logger.error(f"Errore nella creazione tabella hard_deletes: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

# Assicura che la tabella hard_deletes esista all'avvio
try:
    _ensure_hard_deletes_table()
except Exception as e:
    logger.warning(f"Impossibile creare tabella hard_deletes all'avvio: {e}")

# In real_server.py

def process_client_changes(conn_or_cursor, table_name: str, records: list[dict], user_role: str, server_timestamp: datetime):
    try:
        cursor = conn_or_cursor.cursor(cursor_factory=RealDictCursor)
        conn = conn_or_cursor
    except AttributeError:
        cursor = conn_or_cursor
        conn = cursor.connection
    conflicts = []
    uuid_map = {}

    if not records:
        return conflicts, 0, uuid_map

    valid_cols = get_valid_columns(cursor, table_name)
    cleaned_records = []

    for rec in records:
        r = dict(rec)

        # --- MODIFICA #2: Forza l'uso del timestamp del server ---
        # Questo garantisce che tutte le modifiche abbiano un timestamp coerente,
        # risolvendo il problema della sincronizzazione incrementale.
        r['last_modified'] = server_timestamp
        
        if table_name == "destinations":
            cust_uuid = r.pop("customer_uuid", None)
            if cust_uuid:
                cursor.execute("SELECT id FROM customers WHERE uuid=%s AND is_deleted=FALSE", (cust_uuid,))
                row = cursor.fetchone()
                if not row:
                    logging.warning(f"Salto destination: customer {cust_uuid} assente sul server.")
                    continue
                r["customer_id"] = row["id"]

        elif table_name == "devices":
            dest_uuid = r.pop("destination_uuid", None)
            if dest_uuid:
                cursor.execute("SELECT id FROM destinations WHERE uuid=%s AND is_deleted=FALSE", (dest_uuid,))
                row = cursor.fetchone()
                if not row:
                    logging.warning(f"Salto device: destination {dest_uuid} assente sul server.")
                    continue
                r["destination_id"] = row["id"]

            # Normalizza il numero di serie (come lato client)
            raw_serial = (r.get("serial_number") or "").strip()
            if raw_serial == "" or raw_serial.upper() in {"N.P.", "NP", "N/A", "NA", "NON PRESENTE", "-"}:
                r["serial_number"] = None
                normalized_serial = None
            else:
                normalized_serial = raw_serial.upper()
                r["serial_number"] = normalized_serial

            # --- GESTIONE CONFLITTO: numero di serie già esistente ---
            # Se esiste già un dispositivo ATTIVO con lo stesso serial_number ma UUID diverso,
            # non generiamo un errore 500 ma un conflitto esplicito.
            # Skip: non controlliamo i record in fase di eliminazione (is_deleted)
            if normalized_serial and not r.get('is_deleted'):
                cursor.execute(
                    """
                    SELECT * FROM devices
                    WHERE serial_number = %s
                      AND is_deleted = FALSE
                      AND uuid <> %s
                    """,
                    (normalized_serial, r.get("uuid")),
                )
                existing = cursor.fetchone()
                if existing:
                    conflict = {
                        "table": "devices",
                        "uuid": r.get("uuid"),
                        "reason": "serial_conflict",
                        "message": f"Il numero di serie '{normalized_serial}' esiste già su un altro dispositivo sul server.",
                        "client_version": r,
                        "server_version": existing,
                    }
                    logging.warning(f"Conflitto di numero di serie rilevato durante sync: {conflict}")
                    conflicts.append(conflict)
                    # Salta questo record: non verrà upsertato
                    continue

        elif table_name == "profile_tests":
            prof_uuid = r.pop("profile_uuid", None)
            if prof_uuid:
                cursor.execute("SELECT id FROM profiles WHERE uuid=%s AND is_deleted=FALSE", (prof_uuid,))
                row = cursor.fetchone()
                if not row:
                    logging.warning(f"Salto profile_test: profile {prof_uuid} assente sul server.")
                    continue
                r["profile_id"] = row["id"]

        elif table_name == "verifications":
            dev_uuid = r.pop("device_uuid", None)
            if dev_uuid:
                cursor.execute("SELECT id FROM devices WHERE uuid=%s AND is_deleted=FALSE", (dev_uuid,))
                row = cursor.fetchone()
                if not row:
                    logging.warning(f"Salto verification: device {dev_uuid} assente sul server.")
                    continue
                r["device_id"] = row["id"]

        elif table_name == "functional_verifications":
            dev_uuid = r.pop("device_uuid", None)
            if dev_uuid:
                cursor.execute("SELECT id FROM devices WHERE uuid=%s AND is_deleted=FALSE", (dev_uuid,))
                row = cursor.fetchone()
                if not row:
                    logging.warning(f"Salto functional_verification: device {dev_uuid} assente sul server.")
                    continue
                r["device_id"] = row["id"]

        elif table_name == "system_verifications":
            dest_uuid = r.pop("destination_uuid", None)
            if dest_uuid:
                cursor.execute("SELECT id FROM destinations WHERE uuid=%s AND is_deleted=FALSE", (dest_uuid,))
                row = cursor.fetchone()
                if not row:
                    logging.warning(f"Salto system_verification: destination {dest_uuid} assente sul server.")
                    continue
                r["destination_id"] = row["id"]

        elif table_name == "system_verification_devices":
            sv_uuid = r.pop("system_verification_uuid", None)
            if sv_uuid:
                cursor.execute("SELECT id FROM system_verifications WHERE uuid=%s AND is_deleted=FALSE", (sv_uuid,))
                row = cursor.fetchone()
                if not row:
                    logging.warning(f"Salto system_verification_device: system_verification {sv_uuid} assente sul server.")
                    continue
                r["system_verification_id"] = row["id"]
            dev_uuid = r.pop("device_uuid", None)
            if dev_uuid:
                cursor.execute("SELECT id FROM devices WHERE uuid=%s AND is_deleted=FALSE", (dev_uuid,))
                row = cursor.fetchone()
                if not row:
                    logging.warning(f"Salto system_verification_device: device {dev_uuid} assente sul server.")
                    continue
                r["device_id"] = row["id"]

        elif table_name == "verification_attachments":
            # Risolvi verification_id tramite UUID della verifica padre
            ver_uuid = r.pop("verification_uuid", None)
            ver_type = r.get("verification_type", "functional")
            if ver_uuid:
                if ver_type == "functional":
                    cursor.execute("SELECT id FROM functional_verifications WHERE uuid=%s AND is_deleted=FALSE", (ver_uuid,))
                else:
                    cursor.execute("SELECT id FROM verifications WHERE uuid=%s AND is_deleted=FALSE", (ver_uuid,))
                row = cursor.fetchone()
                if not row:
                    logging.warning(f"Salto attachment: verifica {ver_uuid} (tipo={ver_type}) assente sul server.")
                    continue
                r["verification_id"] = row["id"]
            # Decodifica file_data da base64
            if r.get("file_data") and isinstance(r["file_data"], str):
                try:
                    r["file_data"] = base64.b64decode(r["file_data"])
                except Exception:
                    logging.warning(f"file_data non è base64 valido per attachment {r.get('uuid')}; imposto NULL.")
                    r["file_data"] = None
            # Rimuovi file_path (campo locale del client, il server usa file_data BYTEA)
            r.pop("file_path", None)

        for k, v in list(r.items()):
            r[k] = _normalize_incoming_value(table_name, k, v)

        # Filtra solo i campi che esistono effettivamente nella tabella del database
        r_clean = {k: v for k, v in r.items() if k in valid_cols}
        if not r_clean:
            logging.warning(f"Record per {table_name} senza campi validi dopo il filtraggio. Campi originali: {list(r.keys())}, Campi validi: {list(valid_cols)}")
            continue
        cleaned_records.append(r_clean)

    if not cleaned_records:
        return conflicts, 0, uuid_map

    upserted = upsert_records(conn, cursor, table_name, cleaned_records)
    return conflicts, upserted, uuid_map


def _validate_serial_conflict_resolution(cursor, table_name: str, uuid_to_keep: str, uuid_to_delete: str) -> tuple[bool, str | None, str | None]:
    """
    Valida che la risoluzione rappresenti un conflitto serial reale e risolvibile.
    Restituisce: (is_valid, reason_if_invalid, shared_serial_if_valid)
    """
    if table_name != "devices":
        return False, "Solo la tabella 'devices' supporta conflict_resolutions", None
    if not uuid_to_keep or not uuid_to_delete:
        return False, "uuid_to_keep/uuid_to_delete mancanti", None
    if uuid_to_keep == uuid_to_delete:
        return False, "uuid_to_keep e uuid_to_delete non possono coincidere", None

    cursor.execute(
        """
        SELECT uuid, serial_number, is_deleted
        FROM devices
        WHERE uuid IN (%s, %s)
        FOR UPDATE
        """,
        (uuid_to_keep, uuid_to_delete)
    )
    rows = cursor.fetchall()
    by_uuid = {r["uuid"]: r for r in rows}

    keep_row = by_uuid.get(uuid_to_keep)
    delete_row = by_uuid.get(uuid_to_delete)
    if not keep_row or not delete_row:
        return False, "Uno o entrambi i record non esistono", None
    if keep_row.get("is_deleted") or delete_row.get("is_deleted"):
        return False, "Uno o entrambi i record risultano già eliminati", None

    keep_serial = (keep_row.get("serial_number") or "").strip().upper()
    delete_serial = (delete_row.get("serial_number") or "").strip().upper()
    if not keep_serial or keep_serial != delete_serial:
        return False, "I record non condividono lo stesso serial_number (nessun serial_conflict reale)", None

    return True, None, keep_serial

def upsert_records(conn, cursor, table_name: str, records: list[dict]):
    """Esegue un'operazione di 'UPSERT' per una lista di record."""
    if not records:
        return 0

    try:
        if table_name == 'profile_tests':
            # Converti i valori booleani per profile_tests
            for record in records:
                if 'is_applied_part_test' in record:
                    # Converti esplicitamente in booleano
                    record['is_applied_part_test'] = bool(record['is_applied_part_test'])

        cols = list(records[0].keys())
        
        query = sql.SQL("""
            INSERT INTO {table} ({col_names})
            VALUES ({placeholders})
            ON CONFLICT (uuid) 
            DO UPDATE SET {update_clause}
            WHERE {table}.uuid = EXCLUDED.uuid
        """).format(
            table=sql.Identifier(table_name),
            col_names=sql.SQL(", ").join(sql.Identifier(c) for c in cols),
            placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in cols),
            update_clause=sql.SQL(", ").join(
                [sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(col), sql.Identifier(col))
                 for col in cols if col != 'uuid' and col != 'last_modified']
                + [sql.SQL('"last_modified" = CURRENT_TIMESTAMP')]
            )
        )
        
        logging.debug(f"Executing UPSERT query for {table_name} with columns: {list(cols)}")
        data_tuples = [tuple(rec.get(col) for col in cols) for rec in records]
        
        try:
            cursor.executemany(query, data_tuples)
        except psycopg2.errors.UndefinedColumn as e:
            # Se una colonna non esiste, logga l'errore e prova a ricostruire la query senza quella colonna
            error_msg = str(e)
            logging.error(f"Colonna non trovata durante UPSERT per {table_name}: {error_msg}")
            # Estrai il nome della colonna dall'errore
            import re
            match = re.search(r'column "?(\w+)"? does not exist', error_msg, re.IGNORECASE)
            if match:
                missing_col = match.group(1)
                logging.warning(f"Rimuovendo colonna '{missing_col}' dalla sincronizzazione per {table_name}")
                # Ricostruisci i record senza la colonna mancante
                cols_filtered = [c for c in cols if c != missing_col]
                if not cols_filtered:
                    logging.error(f"Nessuna colonna valida rimasta per {table_name} dopo rimozione di {missing_col}")
                    return 0
                query_filtered = sql.SQL("""
                    INSERT INTO {table} ({col_names})
                    VALUES ({placeholders})
                    ON CONFLICT (uuid) 
                    DO UPDATE SET {update_clause}
                    WHERE {table}.uuid = EXCLUDED.uuid
                """).format(
                    table=sql.Identifier(table_name),
                    col_names=sql.SQL(", ").join(sql.Identifier(c) for c in cols_filtered),
                    placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in cols_filtered),
                    update_clause=sql.SQL(", ").join(
                        [sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(col), sql.Identifier(col))
                         for col in cols_filtered if col != 'uuid' and col != 'last_modified']
                        + [sql.SQL('"last_modified" = CURRENT_TIMESTAMP')]
                    )
                )
                data_tuples_filtered = [tuple(rec.get(col) for col in cols_filtered) for rec in records]
                cursor.executemany(query_filtered, data_tuples_filtered)
                return cursor.rowcount if cursor.rowcount is not None else len(records)
            else:
                raise
        
        return cursor.rowcount if cursor.rowcount is not None else len(records)
        
    except Exception as e:
        logging.error(f"Error during UPSERT for table {table_name}: {str(e)}")
        raise

# --- ENDPOINT DI AUTENTICAZIONE ---
@app.post("/token", response_model=Token)
def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    client_ip = request.client.host if request.client else "unknown"

    # Anti brute-force: blocco gestito sui login FALLITI (non su tutte le POST /token).
    if rate_limiter.is_login_blocked(client_ip):
        retry_after = rate_limiter.get_login_retry_after(client_ip)
        logger.warning(f"⚠️ Login rifiutato: IP {client_ip} attualmente bloccato")
        raise HTTPException(
            status_code=429,
            detail=f"Troppi tentativi di login falliti. Riprova tra {retry_after} secondi.",
            headers={"Retry-After": str(retry_after)}
        )

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM users WHERE username = %s", (form_data.username,))
    user = cursor.fetchone()
    conn.close()

    if not user or not verify_password(form_data.password, user['hashed_password']):
        is_blocked_now, retry_after = rate_limiter.record_failed_login(client_ip)
        if is_blocked_now:
            raise HTTPException(
                status_code=429,
                detail=f"Troppi tentativi di login falliti. IP bloccato per {retry_after} secondi.",
                headers={"Retry-After": str(retry_after)}
            )

        if retry_after > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Troppi tentativi di login falliti. Riprova tra {retry_after} secondi.",
                headers={"Retry-After": str(retry_after)}
            )

        raise HTTPException(status_code=401, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})

    # Login riuscito: azzera lo storico fallimenti per questo IP.
    rate_limiter.clear_failed_login_attempts(client_ip)
    
    first_name = user.get('first_name') or ''
    last_name = user.get('last_name') or ''
    full_name = f"{first_name} {last_name}".strip()
    if not full_name: full_name = user['username']

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user['username'],
            "role": user['role'],
            "first_name": first_name,
            "last_name": last_name,
            "full_name": full_name,
        },
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}  # nosec B105 - standard OAuth2 token type

# --- ENDPOINT PROTETTI ---
@app.post("/sync")
def handle_sync(payload_raw: dict = Body(...), current_user: User = Depends(get_current_user)):
    """
    Endpoint di sincronizzazione con validazione checksum su JSON raw.
    
    IMPORTANTE: Riceviamo il payload come dict grezzo (non Pydantic model) per poter
    validare il checksum PRIMA che Pydantic aggiunga i campi default.
    """
    logging.info(f"Sync richiesto dall'utente: {current_user.username}")
    
    try:
        # === STEP 1: Estrai checksum e dati dal payload raw ===
        checksum_received = payload_raw.get("checksum")
        changes_raw = payload_raw.get("changes", {})
        last_sync_timestamp = payload_raw.get("last_sync_timestamp")
        
        logging.info("📥 Dati ricevuti dal client:")
        for table_name, records in changes_raw.items():
            record_count = len(records) if isinstance(records, list) else 0
            if record_count > 0:
                logging.info(f"   - {table_name}: {record_count} record(s)")
        
        # === STEP 2: Valida checksum su JSON raw (PRIMA di Pydantic) ===
        if checksum_received:
            if not _validate_checksum(changes_raw, checksum_received):
                logging.error("✗ Checksum validation failed on raw data")
                raise HTTPException(status_code=400, detail="Checksum validation failed")
            logging.info("✓ Checksum validato correttamente su dati raw")
        else:
            logging.warning("⚠️  Nessun checksum ricevuto - proceedi senza validazione")
        
        # === STEP 3: Ora usa Pydantic per tipo-checking e normalizzazione ===
        payload = SyncPayload(
            last_sync_timestamp=last_sync_timestamp,
            changes=payload_raw.get("changes", {}),
            checksum=checksum_received,
            sync_version=payload_raw.get("sync_version", "1.0"),
            conflict_resolutions=payload_raw.get("conflict_resolutions")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        # Log sintetico: evita di loggare centinaia di righe di errori Pydantic
        error_summary = str(e).split('\n')[0] if '\n' in str(e) else str(e)
        logging.warning(f"Payload sync non valido: {error_summary[:200]}")
        raise HTTPException(status_code=400, detail="Payload non valido. Verifica il formato dei dati inviati.")

    all_conflicts = []
    changes_to_send = {}
    final_uuid_map = {}
    new_sync_timestamp = datetime.now(timezone.utc)

    try:
        # === MIGLIORAMENTO #1: Validazione taglia payload ===
        payload_json = payload.model_dump_json()
        payload_size = len(payload_json.encode('utf-8'))
        if payload_size > MAX_PAYLOAD_SIZE:
            logging.error(f"✗ Payload size exceeded: {payload_size} > {MAX_PAYLOAD_SIZE} bytes")
            raise HTTPException(status_code=413, detail=f"Payload too large: {payload_size} bytes")
        
        # === MIGLIORAMENTO #2: Checksum già validato sopra (su JSON raw) ===
        # La validazione checksum è stata spostata PRIMA di Pydantic per evitare
        # che Pydantic aggiunga campi default che causerebbero mismatch.
        # Se arrivi qui, il checksum è già stato validato.
        
        
        conn = get_db_connection()
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                logging.info("Fase PUSH: Ricezione dati con rilevamento conflitti...")

                # === GESTIONE RISOLUZIONI CONFLITTO SERIAL ===
                # Il client invia le risoluzioni dei serial_conflict già approvate
                # dall'utente. Applichiamo PRIMA di processare i record normali
                # così il serial_number check non rileva più il conflitto.
                if payload.conflict_resolutions:
                    # Sicurezza: le risoluzioni supportano solo serial_conflict su devices.
                    # In caso di payload non valido non applichiamo modifiche e proseguiamo.
                    allowed_roles_for_resolution = {"admin", "moderator", "technician", "seg"}
                    if current_user.role not in allowed_roles_for_resolution:
                        raise HTTPException(status_code=403, detail="Ruolo non autorizzato ad applicare conflict_resolutions")

                    for resolution in payload.conflict_resolutions:
                        res_table = resolution.get('table')
                        uuid_to_keep = resolution.get('uuid_to_keep')
                        uuid_to_delete = resolution.get('uuid_to_delete')
                        if not res_table or not uuid_to_keep or not uuid_to_delete:
                            logging.warning("Risoluzione conflitto ignorata: campi obbligatori mancanti")
                            continue

                        is_valid_resolution, invalid_reason, shared_serial = _validate_serial_conflict_resolution(
                            cursor,
                            res_table,
                            uuid_to_keep,
                            uuid_to_delete
                        )
                        if not is_valid_resolution:
                            logging.warning(
                                f"Risoluzione conflitto rifiutata ({res_table}, delete={uuid_to_delete}): {invalid_reason}"
                            )
                            continue

                        try:
                            cursor.execute(
                                """
                                UPDATE devices
                                SET is_deleted = TRUE, last_modified = %s
                                WHERE uuid = %s
                                  AND is_deleted = FALSE
                                  AND serial_number = %s
                                """,
                                (new_sync_timestamp, uuid_to_delete, shared_serial)
                            )
                            if cursor.rowcount > 0:
                                logging.info(
                                    f"✓ Risoluzione serial_conflict applicata: keep={uuid_to_keep}, delete={uuid_to_delete}, serial={shared_serial}"
                                )
                            else:
                                logging.info(
                                    f"Risoluzione serial_conflict non applicata: {uuid_to_delete} già eliminato/non valido"
                                )
                        except Exception as e:
                            logging.error(f"Errore applicazione risoluzione conflitto: {e}")

                changes_dict = payload.changes.model_dump()
                tables_order = ["customers", "mti_instruments", "profiles", "profile_tests", "functional_profiles",
                                "destinations", "devices", "verifications", "functional_verifications", "verification_attachments",
                                "system_verifications", "system_verification_devices", "signatures", "audit_log"]

                for table in tables_order:
                    records = changes_dict.get(table, [])
                    if not records:
                        continue
                    logging.info(f"Processando {len(records)} record per la tabella '{table}'...")
                    # --- MIGLIORAMENTO #4: SAVEPOINT per recupero parziale ---
                    try:
                        # Crea un SAVEPOINT per questa tabella
                        cursor.execute(f"SAVEPOINT sync_table_{table}")
                        
                        table_conflicts, _, table_uuid_map = process_client_changes(conn, table, records, current_user.role, new_sync_timestamp)
                        if table_conflicts:
                            all_conflicts.extend(table_conflicts)
                            # Rollback al SAVEPOINT se conflitti
                            cursor.execute(f"ROLLBACK TO SAVEPOINT sync_table_{table}")
                            logging.warning(f"⚠ Rollback per {table} a causa di {len(table_conflicts)} conflitti")
                        else:
                            # Rilascia il SAVEPOINT se nessun errore
                            cursor.execute(f"RELEASE SAVEPOINT sync_table_{table}")
                            if table_uuid_map:
                                final_uuid_map.update(table_uuid_map)
                    except Exception as table_error:
                        # Rollback al SAVEPOINT su eccezione
                        try:
                            cursor.execute(f"ROLLBACK TO SAVEPOINT sync_table_{table}")
                        except Exception as sp_err:
                            logging.debug(f"Rollback SAVEPOINT sync_table_{table} fallito (atteso se transazione abortita): {sp_err}")
                        logging.error(f"✗ Errore nel processamento della tabella '{table}': {table_error}", exc_info=True)
                        raise

                if all_conflicts:
                    logging.warning(f"Rilevati {len(all_conflicts)} conflitti. PUSH annullato.")
                    
                    # === MIGLIORAMENTO: Analizza e costruisci response dettagliato ===
                    detailed_conflicts = []
                    for conflict in all_conflicts:
                        # Analizza gravità
                        severity = _analyze_conflict_severity(
                            conflict.get('client_version', {}),
                            conflict.get('server_version', {}),
                            conflict.get('table', '')
                        )
                        
                        # Costruisci response dettagliato
                        detailed_response = _build_conflict_response(conflict, severity)
                        detailed_conflicts.append(detailed_response)
                        
                        logging.info(f"Conflitto in {conflict['table']} (UUID: {conflict['uuid']}) - Severity: {severity}")

                    # Importante: siamo in `with conn:`. Solleviamo eccezione per forzare
                    # rollback completo della transazione, evitando commit parziali.
                    raise SyncConflictDetectedError(detailed_conflicts)

                logging.info("Fase PUSH completata con successo.")
                logging.info("Fase PULL: Invio aggiornamenti al client...")

                simple_tables = ["customers", "mti_instruments", "profiles", "profile_tests", "functional_profiles", "destinations"]
                is_first_sync = payload.last_sync_timestamp is None

                cursor.execute("SELECT * FROM signatures")
                changes_to_send["signatures"] = cursor.fetchall()
                
                # Audit log - invia sempre tutti i record (tabella speciale, solo inserimenti)
                if is_first_sync:
                    cursor.execute("SELECT * FROM audit_log WHERE is_deleted = FALSE")
                else:
                    try:
                        last_sync_dt = datetime.fromisoformat(payload.last_sync_timestamp)
                    except (ValueError, TypeError):
                        raise HTTPException(status_code=400, detail="Formato last_sync_timestamp non valido. Usare formato ISO 8601.")
                    cursor.execute(
                        "SELECT * FROM audit_log WHERE last_modified > %s AND last_modified <= %s",
                        (last_sync_dt, new_sync_timestamp)
                    )
                changes_to_send["audit_log"] = cursor.fetchall()

                if is_first_sync:
                    logging.info("Prima sincronizzazione per questo client: invio di tutti i dati.")
                    for table in simple_tables:
                        if table == 'destinations':
                            cursor.execute("""
                                SELECT d.*, c.uuid AS customer_uuid
                                FROM destinations d
                                INNER JOIN customers c ON d.customer_id = c.id
                                WHERE d.is_deleted = FALSE
                            """)
                            changes_to_send[table] = cursor.fetchall()
                        elif table == 'profile_tests':
                            cursor.execute("""
                                SELECT pt.*, p.uuid AS profile_uuid
                                FROM profile_tests pt
                                INNER JOIN profiles p ON pt.profile_id = p.id
                                WHERE pt.is_deleted = FALSE
                            """)
                            changes_to_send[table] = cursor.fetchall()
                        else:
                            cursor.execute(sql.SQL("SELECT * FROM {} WHERE is_deleted = FALSE").format(
                                sql.Identifier(table)
                            ))
                            changes_to_send[table] = cursor.fetchall()

                    cursor.execute("""
                        SELECT d.*, dest.uuid as destination_uuid
                        FROM devices d
                        INNER JOIN destinations dest ON d.destination_id = dest.id
                        WHERE d.is_deleted = FALSE
                    """)
                    changes_to_send["devices"] = cursor.fetchall()

                    cursor.execute("""
                        SELECT v.*, d.uuid as device_uuid
                        FROM verifications v
                        INNER JOIN devices d ON v.device_id = d.id
                        WHERE v.is_deleted = FALSE
                    """)
                    changes_to_send["verifications"] = cursor.fetchall()

                    cursor.execute("""
                        SELECT fv.*, d.uuid as device_uuid
                        FROM functional_verifications fv
                        INNER JOIN devices d ON fv.device_id = d.id
                        WHERE fv.is_deleted = FALSE
                    """)
                    changes_to_send["functional_verifications"] = cursor.fetchall()

                    # Verification attachments: join con verifica padre per ottenere UUID
                    cursor.execute("""
                        SELECT va.*,
                               COALESCE(fv.uuid, v.uuid) as verification_uuid
                        FROM verification_attachments va
                        LEFT JOIN functional_verifications fv 
                            ON va.verification_id = fv.id AND va.verification_type = 'functional'
                        LEFT JOIN verifications v 
                            ON va.verification_id = v.id AND va.verification_type = 'electrical'
                        WHERE va.is_deleted = FALSE
                    """)
                    changes_to_send["verification_attachments"] = cursor.fetchall()

                    # System verifications
                    cursor.execute("""
                        SELECT sv.*, dest.uuid as destination_uuid
                        FROM system_verifications sv
                        INNER JOIN destinations dest ON sv.destination_id = dest.id
                        WHERE sv.is_deleted = FALSE
                    """)
                    changes_to_send["system_verifications"] = cursor.fetchall()

                    cursor.execute("""
                        SELECT svd.*, sv.uuid as system_verification_uuid, d.uuid as device_uuid
                        FROM system_verification_devices svd
                        INNER JOIN system_verifications sv ON svd.system_verification_id = sv.id
                        INNER JOIN devices d ON svd.device_id = d.id
                        WHERE svd.is_deleted = FALSE
                    """)
                    changes_to_send["system_verification_devices"] = cursor.fetchall()
                else:
                    last_sync_ts = payload.last_sync_timestamp
                    if last_sync_ts is None:
                        raise HTTPException(status_code=400, detail="last_sync_timestamp must not be None for incremental sync.")
                    try:
                        last_sync_dt = datetime.fromisoformat(last_sync_ts)
                    except (ValueError, TypeError):
                        raise HTTPException(status_code=400, detail="Formato last_sync_timestamp non valido. Usare formato ISO 8601.")

                    for table in simple_tables:
                        if table == 'destinations':
                            cursor.execute("""
                                SELECT d.*, c.uuid AS customer_uuid
                                FROM destinations d
                                INNER JOIN customers c ON d.customer_id = c.id
                                WHERE d.last_modified > %s AND d.last_modified <= %s
                            """, (last_sync_dt, new_sync_timestamp))
                            changes_to_send[table] = cursor.fetchall()
                        elif table == 'profile_tests':
                            cursor.execute("""
                                SELECT pt.*, p.uuid AS profile_uuid
                                FROM profile_tests pt
                                INNER JOIN profiles p ON pt.profile_id = p.id
                                WHERE pt.last_modified > %s AND pt.last_modified <= %s
                            """, (last_sync_dt, new_sync_timestamp))
                            changes_to_send[table] = cursor.fetchall()
                        else:
                            cursor.execute(
                                sql.SQL("SELECT * FROM {} WHERE last_modified > %s AND last_modified <= %s").format(
                                    sql.Identifier(table)
                                ),
                                (last_sync_dt, new_sync_timestamp)
                            )
                            changes_to_send[table] = cursor.fetchall()

                    cursor.execute("""
                        SELECT d.*, dest.uuid as destination_uuid
                        FROM devices d
                        INNER JOIN destinations dest ON d.destination_id = dest.id
                        WHERE d.last_modified > %s AND d.last_modified <= %s
                    """, (last_sync_dt, new_sync_timestamp))
                    changes_to_send["devices"] = cursor.fetchall()

                    cursor.execute("""
                        SELECT v.*, d.uuid as device_uuid
                        FROM verifications v
                        INNER JOIN devices d ON v.device_id = d.id
                        WHERE v.last_modified > %s AND v.last_modified <= %s
                    """, (last_sync_dt, new_sync_timestamp))
                    changes_to_send["verifications"] = cursor.fetchall()

                    cursor.execute("""
                        SELECT fv.*, d.uuid as device_uuid
                        FROM functional_verifications fv
                        INNER JOIN devices d ON fv.device_id = d.id
                        WHERE fv.last_modified > %s AND fv.last_modified <= %s
                    """, (last_sync_dt, new_sync_timestamp))
                    changes_to_send["functional_verifications"] = cursor.fetchall()

                    # Verification attachments: join con verifica padre per ottenere UUID
                    cursor.execute("""
                        SELECT va.*,
                               COALESCE(fv.uuid, v.uuid) as verification_uuid
                        FROM verification_attachments va
                        LEFT JOIN functional_verifications fv 
                            ON va.verification_id = fv.id AND va.verification_type = 'functional'
                        LEFT JOIN verifications v 
                            ON va.verification_id = v.id AND va.verification_type = 'electrical'
                        WHERE va.last_modified > %s AND va.last_modified <= %s
                    """, (last_sync_dt, new_sync_timestamp))
                    changes_to_send["verification_attachments"] = cursor.fetchall()

                    # System verifications (incremental)
                    cursor.execute("""
                        SELECT sv.*, dest.uuid as destination_uuid
                        FROM system_verifications sv
                        INNER JOIN destinations dest ON sv.destination_id = dest.id
                        WHERE sv.last_modified > %s AND sv.last_modified <= %s
                    """, (last_sync_dt, new_sync_timestamp))
                    changes_to_send["system_verifications"] = cursor.fetchall()

                    cursor.execute("""
                        SELECT svd.*, sv.uuid as system_verification_uuid, d.uuid as device_uuid
                        FROM system_verification_devices svd
                        INNER JOIN system_verifications sv ON svd.system_verification_id = sv.id
                        INNER JOIN devices d ON svd.device_id = d.id
                        WHERE svd.last_modified > %s AND svd.last_modified <= %s
                    """, (last_sync_dt, new_sync_timestamp))
                    changes_to_send["system_verification_devices"] = cursor.fetchall()

                if "signatures" in changes_to_send:
                    for signature_record in changes_to_send["signatures"]:
                        if signature_record.get("signature_data"):
                            signature_record["signature_data"] = base64.b64encode(signature_record["signature_data"]).decode('utf-8')

                # Base64 encode file_data degli allegati per il trasferimento JSON
                if "verification_attachments" in changes_to_send:
                    for att_record in changes_to_send["verification_attachments"]:
                        if att_record.get("file_data"):
                            att_record["file_data"] = base64.b64encode(att_record["file_data"]).decode('utf-8')

                for _, rows in changes_to_send.items():
                    for row in rows:
                        for key, value in list(row.items()):
                            if isinstance(value, (datetime, date)):
                                row[key] = value.isoformat()

                # === HARD DELETES: Recupera tombstone per propagazione ===
                hard_deletes_to_send = {}
                if is_first_sync:
                    # Prima sync: invia TUTTI i tombstone (il client potrebbe avere dati vecchi)
                    cursor.execute("SELECT table_name, record_uuid FROM hard_deletes")
                else:
                    # Sync incrementale: solo tombstone dopo l'ultimo sync
                    cursor.execute(
                        "SELECT table_name, record_uuid FROM hard_deletes WHERE deleted_at > %s AND deleted_at <= %s",
                        (last_sync_dt, new_sync_timestamp)
                    )
                tombstone_rows = cursor.fetchall()
                for row in tombstone_rows:
                    tbl = row['table_name']
                    if tbl not in hard_deletes_to_send:
                        hard_deletes_to_send[tbl] = []
                    hard_deletes_to_send[tbl].append(row['record_uuid'])
                
                if hard_deletes_to_send:
                    total_tombstones = sum(len(v) for v in hard_deletes_to_send.values())
                    logging.info(f"🗑️ Invio {total_tombstones} tombstone di eliminazione definitiva al client")

                # === MIGLIORAMENTO #3: Calcolo checksum della risposta ===
                response_checksum = _calculate_checksum(changes_to_send)
                logging.info(f"✓ Checksum risposta calcolato: {response_checksum[:16]}...")

        return {
            "status": "success",
            "new_sync_timestamp": new_sync_timestamp.isoformat(),
            "changes": changes_to_send,
            "hard_deletes": hard_deletes_to_send,
            "uuid_map": final_uuid_map,
            "response_checksum": response_checksum,  # Per validazione client
            "sync_version": SYNC_DATA_VERSION
        }
    except SyncConflictDetectedError as sync_conflict:
        return JSONResponse(
            status_code=409,
            content={
                "status": "conflict",
                "conflict_count": len(sync_conflict.conflicts),
                "conflicts": sync_conflict.conflicts,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Errore grave durante la sincronizzazione: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Errore interno del server durante la sincronizzazione.")

@app.get("/users", response_model=List[User])
def read_users(current_user: User = Depends(get_current_user)):
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Operazione non autorizzata")
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT username, role, first_name, last_name FROM users ORDER BY username")
        users = cursor.fetchall()
        return users
    except Exception:
        raise HTTPException(status_code=500, detail="Errore interno del server.")
    finally:
        if conn: conn.close()

@app.post("/users", response_model=User)
def create_user(user: UserCreate, current_user: User = Depends(get_current_user)):
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Operazione non autorizzata")
    hashed_password = get_password_hash(user.password)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "INSERT INTO users (username, hashed_password, role, first_name, last_name) VALUES (%s, %s, %s, %s, %s) RETURNING username, role, first_name, last_name",
            (user.username, hashed_password, user.role, user.first_name, user.last_name)
        )
        new_user = cursor.fetchone()
        conn.commit()
        return new_user
    except errors.UniqueViolation:
        raise HTTPException(status_code=400, detail="Un utente con questo nome esiste già.")
    except errors.CheckViolation:
        if conn: conn.rollback()
        raise HTTPException(status_code=400, detail="Dati utente non validi. Verificare username e ruolo.")
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Errore creazione utente: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Errore interno del server durante la creazione utente.")
    finally:
        if conn: conn.close()

@app.put("/users/{username}", response_model=User)
def update_user(username: str, user_update: UserUpdate, current_user: User = Depends(get_current_user)):
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Operazione non autorizzata")
    fields_to_update = []
    params = {}
    if user_update.password:
        fields_to_update.append("hashed_password = %(hashed_password)s")
        params["hashed_password"] = get_password_hash(user_update.password)
    if user_update.role:
        fields_to_update.append("role = %(role)s")
        params["role"] = user_update.role
    if user_update.first_name is not None:
        fields_to_update.append("first_name = %(first_name)s")
        params["first_name"] = user_update.first_name
    if user_update.last_name is not None:
        fields_to_update.append("last_name = %(last_name)s")
        params["last_name"] = user_update.last_name
    if not fields_to_update:
        raise HTTPException(status_code=400, detail="Nessun dato da aggiornare fornito.")
    params["username"] = username
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Costruzione sicura: i nomi dei campi sono hardcoded sopra (non input utente)
        query = f"UPDATE users SET {', '.join(fields_to_update)} WHERE username = %(username)s RETURNING username, role, first_name, last_name"  # nosec B608 - field names are hardcoded, not user input
        cursor.execute(query, params)
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Utente non trovato.")
        updated_user = cursor.fetchone()
        conn.commit()
        return updated_user
    except HTTPException:
        raise
    except errors.CheckViolation:
        if conn: conn.rollback()
        raise HTTPException(status_code=400, detail="Dati non validi. Verificare il ruolo e i campi forniti.")
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Errore aggiornamento utente '{username}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Errore interno del server durante l'aggiornamento utente.")
    finally:
        if conn: conn.close()

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v):
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f'Password troppo corta (minimo {MIN_PASSWORD_LENGTH} caratteri)')
        return v

@app.post("/me/change-password")
def change_own_password(req: ChangePasswordRequest, current_user: User = Depends(get_current_user)):
    """Permette a qualsiasi utente autenticato di cambiare la propria password."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT hashed_password FROM users WHERE username = %s", (current_user.username,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Utente non trovato.")
        if not verify_password(req.current_password, row['hashed_password']):
            raise HTTPException(status_code=401, detail="La password attuale non è corretta.")
        new_hash = get_password_hash(req.new_password)
        cursor.execute("UPDATE users SET hashed_password = %s WHERE username = %s", (new_hash, current_user.username))
        conn.commit()
        logger.info(f"Utente '{current_user.username}' ha cambiato la propria password.")
        return {"detail": "Password cambiata con successo."}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Errore cambio password per '{current_user.username}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Errore interno del server durante il cambio password.")
    finally:
        if conn: conn.close()

@app.delete("/users/{username}", status_code=204)
def delete_user(username: str, current_user: User = Depends(get_current_user)):
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Operazione non autorizzata")
    if current_user.username == username:
        raise HTTPException(status_code=400, detail="Un admin non può eliminare se stesso.")
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE username = %s", (username,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Utente non trovato.")
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Errore eliminazione utente '{username}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Errore interno del server durante l'eliminazione utente.")
    finally:
        if conn: conn.close()

@app.post("/signatures/{username}")
def upload_signature(username: str, file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    if current_user.role != 'admin' and current_user.username != username:
        raise HTTPException(status_code=403, detail="Non autorizzato a modificare la firma di un altro utente.")

    # Validazione MIME type dichiarato
    if file.content_type and file.content_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(status_code=400, detail="Tipo file non consentito. Formati accettati: PNG, JPEG, GIF, WebP.")

    # Leggi il file con limite di dimensione
    signature_data = file.file.read(MAX_SIGNATURE_SIZE + 1)
    if len(signature_data) > MAX_SIGNATURE_SIZE:
        raise HTTPException(status_code=413, detail=f"File troppo grande. Dimensione massima: {MAX_SIGNATURE_SIZE // 1024} KB.")

    # Validazione magic bytes (contenuto reale del file)
    is_valid_image = False
    for magic, mime in IMAGE_MAGIC_BYTES.items():
        if signature_data[:len(magic)] == magic:
            is_valid_image = True
            break
    if not is_valid_image:
        raise HTTPException(status_code=400, detail="Il file non è un'immagine valida. Formati accettati: PNG, JPEG, GIF, WebP.")

    timestamp = datetime.now(timezone.utc)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO signatures (username, signature_data, last_modified)
            VALUES (%s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                signature_data = EXCLUDED.signature_data,
                last_modified = EXCLUDED.last_modified;
            """,
            (username, signature_data, timestamp)
        )
        conn.commit()
        return {"status": "success", "username": username}
    except Exception:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail="Errore del server durante il salvataggio della firma.")
    finally:
        if conn: conn.close()

@app.get("/signatures/{username}", responses={200: {"content": {"image/png": {}}}})
def get_signature(username: str, current_user: User = Depends(get_current_user)):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT signature_data FROM signatures WHERE username = %s", (username,))
        record = cursor.fetchone()
        if not record or not record['signature_data']:
            raise HTTPException(status_code=404, detail="Firma non trovata.")
        from fastapi.responses import Response
        return Response(content=record['signature_data'], media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Errore recupero firma '{username}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Errore interno del server durante il recupero della firma.")
    finally:
        if conn: conn.close()

@app.delete("/signatures/{username}", status_code=204)
def delete_signature(username: str, current_user: User = Depends(get_current_user)):
    if current_user.role != 'admin' and current_user.username != username:
        raise HTTPException(status_code=403, detail="Non autorizzato a eliminare la firma di un altro utente.")
    timestamp = datetime.now(timezone.utc)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE signatures SET signature_data = NULL, last_modified = %s WHERE username = %s",
            (timestamp, username)
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Errore eliminazione firma '{username}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Errore interno del server durante l'eliminazione della firma.")
    finally:
        if conn: conn.close()

# ============================================================
# ENDPOINT GESTIONE DATI ELIMINATI (ADMIN)
# ============================================================

@app.get("/admin/deleted-data")
def get_all_deleted_data(current_user: User = Depends(get_current_user)):
    """
    Restituisce tutti i record soft-deleted da tutte le tabelle del database online.
    Solo gli utenti admin possono accedere a questo endpoint.
    """
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Operazione non autorizzata. Solo gli admin possono accedere.")
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        result = {}

        # Clienti eliminati
        cursor.execute("""
            SELECT id, uuid, name, address, phone, email, 
                   last_modified::text as last_modified
            FROM customers WHERE is_deleted = TRUE
            ORDER BY last_modified DESC
        """)
        result['customers'] = cursor.fetchall()

        # Destinazioni eliminate
        cursor.execute("""
            SELECT d.id, d.uuid, d.name, d.address, 
                   d.last_modified::text as last_modified,
                   COALESCE(c.name, '(Cliente eliminato)') as customer_name
            FROM destinations d
            LEFT JOIN customers c ON d.customer_id = c.id
            WHERE d.is_deleted = TRUE
            ORDER BY d.last_modified DESC
        """)
        result['destinations'] = cursor.fetchall()

        # Dispositivi eliminati
        cursor.execute("""
            SELECT dev.id, dev.uuid, dev.serial_number, dev.description,
                   dev.manufacturer, dev.model, 
                   dev.last_modified::text as last_modified,
                   COALESCE(dest.name, '(Dest. eliminata)') as destination_name,
                   COALESCE(c.name, '(Cliente eliminato)') as customer_name
            FROM devices dev
            LEFT JOIN destinations dest ON dev.destination_id = dest.id
            LEFT JOIN customers c ON dest.customer_id = c.id
            WHERE dev.is_deleted = TRUE
            ORDER BY dev.last_modified DESC
        """)
        result['devices'] = cursor.fetchall()

        # Verifiche elettriche eliminate
        cursor.execute("""
            SELECT v.id, v.uuid, v.verification_date::text as verification_date, 
                   v.profile_name, v.overall_status, v.technician_name, 
                   v.verification_code,
                   v.last_modified::text as last_modified,
                   COALESCE(d.serial_number, 'N/A') as device_serial,
                   COALESCE(d.description, 'N/A') as device_description
            FROM verifications v
            LEFT JOIN devices d ON v.device_id = d.id
            WHERE v.is_deleted = TRUE
            ORDER BY v.last_modified DESC
        """)
        result['verifications'] = cursor.fetchall()

        # Verifiche funzionali eliminate
        cursor.execute("""
            SELECT fv.id, fv.uuid, fv.verification_date::text as verification_date, 
                   fv.profile_key, fv.overall_status, fv.technician_name, 
                   fv.verification_code,
                   fv.last_modified::text as last_modified,
                   COALESCE(d.serial_number, 'N/A') as device_serial,
                   COALESCE(d.description, 'N/A') as device_description
            FROM functional_verifications fv
            LEFT JOIN devices d ON fv.device_id = d.id
            WHERE fv.is_deleted = TRUE
            ORDER BY fv.last_modified DESC
        """)
        result['functional_verifications'] = cursor.fetchall()

        # Profili elettrici eliminati
        cursor.execute("""
            SELECT id, uuid, profile_key, name, 
                   last_modified::text as last_modified
            FROM profiles WHERE is_deleted = TRUE
            ORDER BY last_modified DESC
        """)
        result['profiles'] = cursor.fetchall()

        # Profili funzionali eliminati
        cursor.execute("""
            SELECT id, uuid, profile_key, name, device_type, 
                   last_modified::text as last_modified
            FROM functional_profiles WHERE is_deleted = TRUE
            ORDER BY last_modified DESC
        """)
        result['functional_profiles'] = cursor.fetchall()

        # Strumenti eliminati
        cursor.execute("""
            SELECT id, uuid, instrument_name, serial_number, fw_version, 
                   calibration_date, instrument_type,
                   last_modified::text as last_modified
            FROM mti_instruments WHERE is_deleted = TRUE
            ORDER BY last_modified DESC
        """)
        result['mti_instruments'] = cursor.fetchall()

        # Conteggi
        counts = {}
        for table_name in result:
            counts[table_name] = len(result[table_name])
        result['counts'] = counts

        logger.info(f"Admin {current_user.username} ha richiesto i dati eliminati. Conteggi: {counts}")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Errore nel recupero dati eliminati: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Errore interno del server durante il recupero dei dati eliminati.")
    finally:
        if conn: conn.close()

@app.delete("/admin/deleted-data/{table_name}/{record_id}")
def hard_delete_single_record(table_name: str, record_id: int, current_user: User = Depends(get_current_user)):
    """
    Elimina definitivamente un singolo record soft-deleted dal database online.
    Solo admin.
    """
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Operazione non autorizzata.")
    
    allowed_tables = {
        'customers', 'destinations', 'devices', 'verifications',
        'functional_verifications', 'profiles', 'functional_profiles',
        'mti_instruments'
    }
    if table_name not in allowed_tables:
        raise HTTPException(status_code=400, detail=f"Tabella '{table_name}' non consentita.")
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Recupera UUID del record prima di eliminarlo (per tombstone)
        cursor.execute(
            sql.SQL('SELECT uuid FROM {} WHERE id = %s AND is_deleted = TRUE').format(
                sql.Identifier(table_name)
            ),
            (record_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Record non trovato o non eliminato.")
        
        record_uuid = row['uuid']
        
        # Registra tombstone per propagazione hard delete ai client
        cursor.execute(
            "INSERT INTO hard_deletes (table_name, record_uuid, deleted_at, deleted_by) VALUES (%s, %s, NOW(), %s)",
            (table_name, record_uuid, current_user.username)
        )
        
        # Elimina definitivamente il record
        cursor.execute(
            sql.SQL('DELETE FROM {} WHERE id = %s AND is_deleted = TRUE').format(
                sql.Identifier(table_name)
            ),
            (record_id,)
        )
        conn.commit()
        
        logger.warning(f"Admin {current_user.username}: hard delete record ID {record_id} (UUID: {record_uuid}) da {table_name} - tombstone registrato")
        return {"status": "success", "deleted": True, "uuid": record_uuid}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Errore hard delete: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Errore interno del server durante l'eliminazione.")
    finally:
        if conn: conn.close()

@app.delete("/admin/deleted-data/{table_name}")
def hard_delete_all_records(table_name: str, current_user: User = Depends(get_current_user)):
    """
    Elimina definitivamente TUTTI i record soft-deleted di una tabella dal database online.
    Solo admin.
    """
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Operazione non autorizzata.")
    
    allowed_tables = {
        'customers', 'destinations', 'devices', 'verifications',
        'functional_verifications', 'profiles', 'functional_profiles',
        'mti_instruments'
    }
    if table_name not in allowed_tables:
        raise HTTPException(status_code=400, detail=f"Tabella '{table_name}' non consentita.")
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Recupera tutti gli UUID dei record da eliminare (per tombstone)
        cursor.execute(
            sql.SQL('SELECT uuid FROM {} WHERE is_deleted = TRUE').format(
                sql.Identifier(table_name)
            )
        )
        rows = cursor.fetchall()
        uuids = [r['uuid'] for r in rows if r.get('uuid')]
        
        # Registra tombstone per ogni UUID
        if uuids:
            from psycopg2.extras import execute_values
            tombstone_data = [(table_name, uuid_val, current_user.username) for uuid_val in uuids]
            execute_values(
                cursor,
                "INSERT INTO hard_deletes (table_name, record_uuid, deleted_at, deleted_by) VALUES %s",
                tombstone_data,
                template="(%s, %s, NOW(), %s)"
            )
        
        # Elimina definitivamente tutti i record soft-deleted
        cursor.execute(
            sql.SQL('DELETE FROM {} WHERE is_deleted = TRUE').format(
                sql.Identifier(table_name)
            )
        )
        count = cursor.rowcount
        conn.commit()
        
        logger.warning(f"Admin {current_user.username}: hard delete ALL ({count}) da {table_name} - {len(uuids)} tombstone registrati")
        return {"status": "success", "deleted_count": count}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Errore hard delete massivo: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Errore interno del server durante l'eliminazione massiva.")
    finally:
        if conn: conn.close()

# --- ENDPOINT ROOT ---
@app.get("/")
def root():
    return {"message": "Safety Test Sync API è in esecuzione."}


# ════════════════════════════════════════════════════════════════════════════════
# MOBILE PWA — Routes, Templates, Static Files
# ════════════════════════════════════════════════════════════════════════════════

_THIS_DIR = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_MOBILE_TEMPLATES = os.path.join(_THIS_DIR, "mobile", "templates")
_MOBILE_STATIC    = os.path.join(_THIS_DIR, "mobile", "static")

mobile_templates = Jinja2Templates(directory=_MOBILE_TEMPLATES)

if os.path.isdir(_MOBILE_STATIC):
    app.mount("/mobile/static", StaticFiles(directory=_MOBILE_STATIC), name="mobile_static")

# ─── Auth helpers ────────────────────────────────────────────────────────────

def _mobile_user_from_cookie(mobile_session: Optional[str] = Cookie(None)) -> Optional[User]:
    """Decode User from the mobile_session cookie (JWT). Returns None if invalid."""
    if not mobile_session:
        return None
    try:
        payload = jwt.decode(mobile_session, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        role     = payload.get("role")
        if not username or not role:
            return None
        return User(
            username=username,
            role=role,
            first_name=payload.get("first_name"),
            last_name=payload.get("last_name"),
        )
    except Exception:
        return None


def _mobile_redirect_login():
    return RedirectResponse(url="/mobile/", status_code=302)


def _set_mobile_cookie(response: RedirectResponse, token: str):
    response.set_cookie(
        key="mobile_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=int(ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        secure=False,  # Set True if served over HTTPS
    )


# ─── Login / Logout ──────────────────────────────────────────────────────────

@app.get("/mobile/", response_class=HTMLResponse)
def mobile_index(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if user:
        return RedirectResponse(url="/mobile/dashboard", status_code=302)
    return mobile_templates.TemplateResponse("login.html", {"request": request})


@app.post("/mobile/auth/login")
def mobile_login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    client_ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_login_blocked(client_ip):
        retry = rate_limiter.get_login_retry_after(client_ip)
        return mobile_templates.TemplateResponse(
            "login.html", {"request": request, "error": f"Troppi tentativi. Riprova tra {retry} secondi."})

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM users WHERE username = %s", (form_data.username,))
    user_row = cursor.fetchone()
    conn.close()

    if not user_row or not verify_password(form_data.password, user_row["hashed_password"]):
        rate_limiter.record_failed_login(client_ip)
        return mobile_templates.TemplateResponse(
            "login.html", {"request": request, "error": "Username o password errati."})

    rate_limiter.clear_failed_login_attempts(client_ip)
    first_name = user_row.get("first_name") or ""
    last_name  = user_row.get("last_name")  or ""
    token = create_access_token(
        data={"sub": user_row["username"], "role": user_row["role"],
              "first_name": first_name, "last_name": last_name,
              "full_name": f"{first_name} {last_name}".strip() or user_row["username"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    resp = RedirectResponse(url="/mobile/dashboard", status_code=302)
    _set_mobile_cookie(resp, token)
    return resp


@app.get("/mobile/auth/logout")
def mobile_logout():
    resp = RedirectResponse(url="/mobile/", status_code=302)
    resp.delete_cookie("mobile_session")
    return resp


# ─── Dashboard ───────────────────────────────────────────────────────────────

@app.get("/mobile/dashboard", response_class=HTMLResponse)
def mobile_dashboard(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    today = date.today().isoformat()
    threshold = (date.today() + timedelta(days=30)).isoformat()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT COUNT(*) as cnt FROM customers WHERE is_deleted = FALSE")
        total_customers = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM devices WHERE is_deleted = FALSE AND status = 'active'")
        total_devices = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT COUNT(*) as cnt FROM verifications WHERE is_deleted = FALSE
            AND EXTRACT(MONTH FROM verification_date) = EXTRACT(MONTH FROM CURRENT_DATE)
            AND EXTRACT(YEAR  FROM verification_date) = EXTRACT(YEAR  FROM CURRENT_DATE)
        """)
        verifications_this_month = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT COUNT(*) as cnt FROM devices
            WHERE is_deleted = FALSE AND status = 'active'
            AND next_verification_date IS NOT NULL
            AND next_verification_date < CURRENT_DATE
        """)
        overdue = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT COUNT(*) as cnt FROM devices
            WHERE is_deleted = FALSE AND status = 'active'
            AND next_verification_date IS NOT NULL
            AND next_verification_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
        """)
        expiring_soon = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE overall_status IN ('PASSATO','PASS','OK'))  AS pass_count,
                COUNT(*) FILTER (WHERE overall_status IN ('NON PASSATO','FAIL','FALLITO')) AS fail_count
            FROM verifications WHERE is_deleted = FALSE
            AND EXTRACT(MONTH FROM verification_date) = EXTRACT(MONTH FROM CURRENT_DATE)
            AND EXTRACT(YEAR  FROM verification_date) = EXTRACT(YEAR  FROM CURRENT_DATE)
        """)
        pf = cur.fetchone()
        pass_count = pf["pass_count"] if pf else 0
        fail_count = pf["fail_count"] if pf else 0

        cur.execute("""
            SELECT v.uuid, v.verification_date, v.profile_name, v.overall_status,
                   d.description, d.manufacturer, d.model, d.serial_number
            FROM verifications v
            JOIN devices d ON d.id = v.device_id
            WHERE v.is_deleted = FALSE
            ORDER BY v.verification_date DESC, v.last_modified DESC
            LIMIT 5
        """)
        recent_verifications = cur.fetchall()

        cur.execute("""
            SELECT fv.uuid, fv.verification_date, fv.profile_key, fv.overall_status,
                   d.description, d.manufacturer, d.model
            FROM functional_verifications fv
            JOIN devices d ON d.id = fv.device_id
            WHERE fv.is_deleted = FALSE
            ORDER BY fv.verification_date DESC, fv.last_modified DESC
            LIMIT 5
        """)
        recent_func_verifications = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"[mobile] dashboard error: {e}", exc_info=True)
        total_customers = total_devices = verifications_this_month = overdue = expiring_soon = 0
        pass_count = fail_count = 0
        recent_verifications = []
        recent_func_verifications = []

    return mobile_templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "active_nav": "dashboard",
        "total_customers": total_customers, "total_devices": total_devices,
        "verifications_this_month": verifications_this_month,
        "pass_count": pass_count, "fail_count": fail_count,
        "overdue": overdue, "expiring_soon": expiring_soon,
        "recent_verifications": recent_verifications,
        "recent_func_verifications": recent_func_verifications,
    })


# ─── Customers ───────────────────────────────────────────────────────────────

@app.get("/mobile/customers", response_class=HTMLResponse)
def mobile_customers(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT COUNT(*) as cnt FROM customers WHERE is_deleted = FALSE")
        total = cur.fetchone()["cnt"]
        cur.execute("""
            SELECT uuid, name, address, phone, email
            FROM customers WHERE is_deleted = FALSE ORDER BY name
        """)
        customers = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"[mobile] customers error: {e}", exc_info=True)
        total = 0; customers = []

    return mobile_templates.TemplateResponse("customers.html", {
        "request": request, "user": user, "active_nav": "customers",
        "customers": customers, "total": total, "back_url": "/mobile/dashboard",
    })


@app.get("/mobile/customers/new", response_class=HTMLResponse)
def mobile_customer_new_form(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()
    return mobile_templates.TemplateResponse("customer_form.html", {
        "request": request,
        "user": user,
        "active_nav": "customers",
        "mode": "create",
        "customer": {},
        "form_action": "/mobile/customers/new",
        "back_url": "/mobile/customers",
    })


@app.post("/mobile/customers/new", response_class=HTMLResponse)
async def mobile_customer_create(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()
    name = form.get("name", "").strip()
    address = form.get("address", "").strip() or None
    phone = form.get("phone", "").strip() or None
    email = form.get("email", "").strip() or None

    if not name:
        return mobile_templates.TemplateResponse("customer_form.html", {
            "request": request, "user": user, "active_nav": "customers",
            "mode": "create", "customer": {"name": name, "address": address, "phone": phone, "email": email},
            "form_action": "/mobile/customers/new", "back_url": "/mobile/customers",
            "error": "Il nome del cliente è obbligatorio.",
        })

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO customers (uuid, name, address, phone, email, last_modified, is_deleted, is_synced)
            VALUES (%s, %s, %s, %s, %s, %s, FALSE, TRUE)
            """,
            (str(__import__("uuid").uuid4()), name, address, phone, email, datetime.now(timezone.utc)),
        )
        conn.commit()
        conn.close()
        return RedirectResponse(url="/mobile/customers", status_code=302)
    except Exception as e:
        logger.error(f"[mobile] customer create error: {e}", exc_info=True)
        return mobile_templates.TemplateResponse("customer_form.html", {
            "request": request, "user": user, "active_nav": "customers",
            "mode": "create", "customer": {"name": name, "address": address, "phone": phone, "email": email},
            "form_action": "/mobile/customers/new", "back_url": "/mobile/customers",
            "error": f"Errore durante il salvataggio: {e}",
        })


@app.get("/mobile/customers/{uuid}/edit", response_class=HTMLResponse)
def mobile_customer_edit_form(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM customers WHERE uuid = %s AND is_deleted = FALSE", (uuid,))
        customer = cur.fetchone()
        conn.close()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente non trovato")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] customer edit form error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return mobile_templates.TemplateResponse("customer_form.html", {
        "request": request,
        "user": user,
        "active_nav": "customers",
        "mode": "edit",
        "customer": customer,
        "form_action": f"/mobile/customers/{uuid}/edit",
        "back_url": f"/mobile/customers/{uuid}",
    })


@app.post("/mobile/customers/{uuid}/edit", response_class=HTMLResponse)
async def mobile_customer_update(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()
    name = form.get("name", "").strip()
    address = form.get("address", "").strip() or None
    phone = form.get("phone", "").strip() or None
    email = form.get("email", "").strip() or None

    if not name:
        return mobile_templates.TemplateResponse("customer_form.html", {
            "request": request, "user": user, "active_nav": "customers",
            "mode": "edit", "customer": {"uuid": uuid, "name": name, "address": address, "phone": phone, "email": email},
            "form_action": f"/mobile/customers/{uuid}/edit", "back_url": f"/mobile/customers/{uuid}",
            "error": "Il nome del cliente è obbligatorio.",
        })

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE customers
            SET name = %s, address = %s, phone = %s, email = %s, last_modified = %s
            WHERE uuid = %s AND is_deleted = FALSE
            """,
            (name, address, phone, email, datetime.now(timezone.utc), uuid),
        )
        conn.commit()
        conn.close()
        return RedirectResponse(url=f"/mobile/customers/{uuid}", status_code=302)
    except Exception as e:
        logger.error(f"[mobile] customer update error: {e}", exc_info=True)
        return mobile_templates.TemplateResponse("customer_form.html", {
            "request": request, "user": user, "active_nav": "customers",
            "mode": "edit", "customer": {"uuid": uuid, "name": name, "address": address, "phone": phone, "email": email},
            "form_action": f"/mobile/customers/{uuid}/edit", "back_url": f"/mobile/customers/{uuid}",
            "error": f"Errore durante l'aggiornamento: {e}",
        })


@app.post("/mobile/customers/{uuid}/delete")
def mobile_customer_delete(uuid: str, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE customers SET is_deleted = TRUE, last_modified = %s WHERE uuid = %s AND is_deleted = FALSE", (datetime.now(timezone.utc), uuid))
        conn.commit()
        conn.close()
        return RedirectResponse(url="/mobile/customers", status_code=302)
    except Exception as e:
        logger.error(f"[mobile] customer delete error: {e}", exc_info=True)
        raise HTTPException(status_code=500)


@app.get("/mobile/partials/customers", response_class=HTMLResponse)
def mobile_customers_partial(request: Request, q: str = "", mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return HTMLResponse(status_code=401)

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        if q:
            cur.execute("""
                SELECT uuid, name, address, phone FROM customers
                WHERE is_deleted = FALSE AND (name ILIKE %s OR address ILIKE %s)
                ORDER BY name LIMIT 50
            """, (f"%{q}%", f"%{q}%"))
        else:
            cur.execute("""
                SELECT uuid, name, address, phone FROM customers
                WHERE is_deleted = FALSE ORDER BY name LIMIT 100
            """)
        customers = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"[mobile] customers partial error: {e}", exc_info=True)
        customers = []

    return mobile_templates.TemplateResponse("partials/customers_list.html", {
        "request": request, "customers": customers,
    })


@app.get("/mobile/customers/{uuid}", response_class=HTMLResponse)
def mobile_customer_detail(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM customers WHERE uuid = %s AND is_deleted = FALSE", (uuid,))
        customer = cur.fetchone()
        if not customer:
            conn.close()
            raise HTTPException(status_code=404, detail="Cliente non trovato")

        cur.execute("""
            SELECT uuid, name, address FROM destinations
            WHERE customer_id = %s AND is_deleted = FALSE ORDER BY name
        """, (customer["id"],))
        destinations = cur.fetchall()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] customer detail error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return mobile_templates.TemplateResponse("customer_detail.html", {
        "request": request, "user": user, "active_nav": "customers",
        "customer": customer, "destinations": destinations,
        "back_url": "/mobile/customers",
    })


@app.get("/mobile/customers/{customer_uuid}/destinations/new", response_class=HTMLResponse)
def mobile_destination_new_form(customer_uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT uuid, name FROM customers WHERE uuid = %s AND is_deleted = FALSE", (customer_uuid,))
        customer = cur.fetchone()
        conn.close()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente non trovato")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] destination new form error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return mobile_templates.TemplateResponse("destination_form.html", {
        "request": request, "user": user, "active_nav": "customers",
        "mode": "create", "customer": customer, "destination": {},
        "form_action": f"/mobile/customers/{customer_uuid}/destinations/new",
        "back_url": f"/mobile/customers/{customer_uuid}",
    })


@app.post("/mobile/customers/{customer_uuid}/destinations/new", response_class=HTMLResponse)
async def mobile_destination_create(customer_uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()
    name = form.get("name", "").strip()
    address = form.get("address", "").strip() or None

    if not name:
        return mobile_templates.TemplateResponse("destination_form.html", {
            "request": request, "user": user, "active_nav": "customers",
            "mode": "create", "customer": {"uuid": customer_uuid},
            "destination": {"name": name, "address": address},
            "form_action": f"/mobile/customers/{customer_uuid}/destinations/new",
            "back_url": f"/mobile/customers/{customer_uuid}",
            "error": "Il nome della sede è obbligatorio.",
        })

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM customers WHERE uuid = %s AND is_deleted = FALSE", (customer_uuid,))
        customer_row = cur.fetchone()
        if not customer_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Cliente non trovato")
        cur.execute(
            """
            INSERT INTO destinations (uuid, customer_id, name, address, last_modified, is_deleted, is_synced)
            VALUES (%s, %s, %s, %s, %s, FALSE, TRUE)
            """,
            (str(__import__("uuid").uuid4()), customer_row[0], name, address, datetime.now(timezone.utc)),
        )
        conn.commit()
        conn.close()
        return RedirectResponse(url=f"/mobile/customers/{customer_uuid}", status_code=302)
    except Exception as e:
        logger.error(f"[mobile] destination create error: {e}", exc_info=True)
        return mobile_templates.TemplateResponse("destination_form.html", {
            "request": request, "user": user, "active_nav": "customers",
            "mode": "create", "customer": {"uuid": customer_uuid},
            "destination": {"name": name, "address": address},
            "form_action": f"/mobile/customers/{customer_uuid}/destinations/new",
            "back_url": f"/mobile/customers/{customer_uuid}",
            "error": f"Errore durante il salvataggio: {e}",
        })


@app.get("/mobile/destinations/{uuid}/edit", response_class=HTMLResponse)
def mobile_destination_edit_form(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT d.uuid, d.name, d.address, c.uuid AS customer_uuid, c.name AS customer_name
            FROM destinations d
            JOIN customers c ON c.id = d.customer_id
            WHERE d.uuid = %s AND d.is_deleted = FALSE
        """, (uuid,))
        destination = cur.fetchone()
        conn.close()
        if not destination:
            raise HTTPException(status_code=404, detail="Destinazione non trovata")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] destination edit form error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return mobile_templates.TemplateResponse("destination_form.html", {
        "request": request, "user": user, "active_nav": "customers",
        "mode": "edit", "customer": {"uuid": destination["customer_uuid"], "name": destination["customer_name"]},
        "destination": destination, "form_action": f"/mobile/destinations/{uuid}/edit",
        "back_url": f"/mobile/destinations/{uuid}",
    })


@app.post("/mobile/destinations/{uuid}/edit", response_class=HTMLResponse)
async def mobile_destination_update(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()
    name = form.get("name", "").strip()
    address = form.get("address", "").strip() or None

    if not name:
        return mobile_templates.TemplateResponse("destination_form.html", {
            "request": request, "user": user, "active_nav": "customers",
            "mode": "edit", "customer": {"uuid": form.get("customer_uuid")},
            "destination": {"uuid": uuid, "name": name, "address": address},
            "form_action": f"/mobile/destinations/{uuid}/edit",
            "back_url": f"/mobile/destinations/{uuid}",
            "error": "Il nome della sede è obbligatorio.",
        })

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT customer_id FROM destinations WHERE uuid = %s AND is_deleted = FALSE", (uuid,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Destinazione non trovata")
        cur.execute("UPDATE destinations SET name = %s, address = %s, last_modified = %s WHERE uuid = %s AND is_deleted = FALSE", (name, address, datetime.now(timezone.utc), uuid))
        conn.commit()
        cur.execute("SELECT uuid FROM customers WHERE id = %s", (row["customer_id"],))
        customer_row = cur.fetchone()
        conn.close()
        return RedirectResponse(url=f"/mobile/destinations/{uuid}", status_code=302)
    except Exception as e:
        logger.error(f"[mobile] destination update error: {e}", exc_info=True)
        return mobile_templates.TemplateResponse("destination_form.html", {
            "request": request, "user": user, "active_nav": "customers",
            "mode": "edit", "customer": {"uuid": form.get("customer_uuid")},
            "destination": {"uuid": uuid, "name": name, "address": address},
            "form_action": f"/mobile/destinations/{uuid}/edit",
            "back_url": f"/mobile/destinations/{uuid}",
            "error": f"Errore durante l'aggiornamento: {e}",
        })


@app.post("/mobile/destinations/{uuid}/delete")
def mobile_destination_delete(uuid: str, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT c.uuid AS customer_uuid FROM destinations d JOIN customers c ON c.id = d.customer_id WHERE d.uuid = %s", (uuid,))
        row = cur.fetchone()
        cur.execute("UPDATE destinations SET is_deleted = TRUE, last_modified = %s WHERE uuid = %s AND is_deleted = FALSE", (datetime.now(timezone.utc), uuid))
        conn.commit()
        conn.close()
        return RedirectResponse(url=f"/mobile/customers/{row['customer_uuid']}" if row and row.get("customer_uuid") else "/mobile/customers", status_code=302)
    except Exception as e:
        logger.error(f"[mobile] destination delete error: {e}", exc_info=True)
        raise HTTPException(status_code=500)


@app.get("/mobile/destinations/{destination_uuid}/devices/new", response_class=HTMLResponse)
def mobile_device_new_form(destination_uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT d.uuid, d.name, c.uuid AS customer_uuid, c.name AS customer_name
            FROM destinations d
            JOIN customers c ON c.id = d.customer_id
            WHERE d.uuid = %s AND d.is_deleted = FALSE
        """, (destination_uuid,))
        destination = cur.fetchone()
        if not destination:
            conn.close()
            raise HTTPException(status_code=404, detail="Destinazione non trovata")
        cur.execute("SELECT profile_key, name FROM profiles WHERE is_deleted = FALSE ORDER BY name")
        profiles = cur.fetchall()
        cur.execute("SELECT profile_key, name FROM functional_profiles WHERE is_deleted = FALSE ORDER BY name")
        functional_profiles = cur.fetchall()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] device new form error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return mobile_templates.TemplateResponse("device_form.html", {
        "request": request, "user": user, "active_nav": "customers",
        "mode": "create", "destination": destination, "device": {},
        "profiles": profiles, "functional_profiles": functional_profiles,
        "form_action": f"/mobile/destinations/{destination_uuid}/devices/new",
        "back_url": f"/mobile/destinations/{destination_uuid}",
    })


@app.post("/mobile/destinations/{destination_uuid}/devices/new", response_class=HTMLResponse)
async def mobile_device_create(destination_uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()
    serial = form.get("serial_number", "").strip() or None
    description = form.get("description", "").strip() or None
    manufacturer = form.get("manufacturer", "").strip() or None
    model = form.get("model", "").strip() or None
    department = form.get("department", "").strip() or None
    customer_inventory = form.get("customer_inventory", "").strip() or None
    ams_inventory = form.get("ams_inventory", "").strip() or None
    verification_interval = form.get("verification_interval", "").strip() or None
    default_profile_key = form.get("default_profile_key", "").strip() or None
    default_functional_profile_key = form.get("default_functional_profile_key", "").strip() or None
    pa_count = int(form.get("pa_count", 0) or 0)
    applied_parts = []
    for i in range(pa_count):
        pa_name = form.get(f"pa_name_{i}", "").strip()
        pa_type = form.get(f"pa_type_{i}", "B").strip()
        if pa_type:
            applied_parts.append({"name": pa_name, "part_type": pa_type, "code": ""})
    applied_parts_json = json.dumps(applied_parts) if applied_parts else None
    device_status = (form.get("status") or "active").strip()
    if device_status not in ("active", "dismissed", "maintenance"):
        device_status = "active"

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM destinations WHERE uuid = %s AND is_deleted = FALSE", (destination_uuid,))
        destination_row = cur.fetchone()
        if not destination_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Destinazione non trovata")

        cur.execute(
            """
            INSERT INTO devices (
                uuid, destination_id, serial_number, description, manufacturer, model, department,
                customer_inventory, ams_inventory, applied_parts_json,
                verification_interval, default_profile_key, default_functional_profile_key,
                last_modified, is_deleted, is_synced, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, TRUE, %s)
            """,
            (
                str(__import__("uuid").uuid4()), destination_row[0], serial, description, manufacturer, model,
                department, customer_inventory, ams_inventory, applied_parts_json,
                int(verification_interval) if verification_interval else None, default_profile_key,
                default_functional_profile_key, datetime.now(timezone.utc), device_status,
            ),
        )
        conn.commit()
        conn.close()
        return RedirectResponse(url=f"/mobile/destinations/{destination_uuid}", status_code=302)
    except Exception as e:
        logger.error(f"[mobile] device create error: {e}", exc_info=True)
        raise HTTPException(status_code=500)


@app.get("/mobile/devices/{uuid}/edit", response_class=HTMLResponse)
def mobile_device_edit_form(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT d.*, dest.uuid AS destination_uuid, dest.name AS destination_name,
                   c.uuid AS customer_uuid, c.name AS customer_name
            FROM devices d
            JOIN destinations dest ON dest.id = d.destination_id
            JOIN customers c ON c.id = dest.customer_id
            WHERE d.uuid = %s AND d.is_deleted = FALSE
        """, (uuid,))
        device = cur.fetchone()
        if not device:
            conn.close()
            raise HTTPException(status_code=404, detail="Dispositivo non trovato")
        cur.execute("SELECT profile_key, name FROM profiles WHERE is_deleted = FALSE ORDER BY name")
        profiles = cur.fetchall()
        cur.execute("SELECT profile_key, name FROM functional_profiles WHERE is_deleted = FALSE ORDER BY name")
        functional_profiles = cur.fetchall()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] device edit form error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    # Parse applied_parts_json for Alpine
    device_dict = dict(device)
    raw_ap = device_dict.get("applied_parts_json")
    if raw_ap and isinstance(raw_ap, str):
        try:
            device_dict["applied_parts_json"] = json.loads(raw_ap)
        except Exception:
            device_dict["applied_parts_json"] = []
    elif not isinstance(raw_ap, list):
        device_dict["applied_parts_json"] = []

    return mobile_templates.TemplateResponse("device_form.html", {
        "request": request, "user": user, "active_nav": "customers",
        "mode": "edit", "device": device_dict,
        "destination": {"uuid": device["destination_uuid"], "name": device["destination_name"]},
        "profiles": profiles, "functional_profiles": functional_profiles,
        "form_action": f"/mobile/devices/{uuid}/edit",
        "back_url": f"/mobile/devices/{uuid}",
    })


@app.post("/mobile/devices/{uuid}/edit", response_class=HTMLResponse)
async def mobile_device_update(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()
    serial = form.get("serial_number", "").strip() or None
    description = form.get("description", "").strip() or None
    manufacturer = form.get("manufacturer", "").strip() or None
    model = form.get("model", "").strip() or None
    department = form.get("department", "").strip() or None
    customer_inventory = form.get("customer_inventory", "").strip() or None
    ams_inventory = form.get("ams_inventory", "").strip() or None
    verification_interval = form.get("verification_interval", "").strip() or None
    default_profile_key = form.get("default_profile_key", "").strip() or None
    default_functional_profile_key = form.get("default_functional_profile_key", "").strip() or None
    pa_count = int(form.get("pa_count", 0) or 0)
    applied_parts = []
    for i in range(pa_count):
        pa_name = form.get(f"pa_name_{i}", "").strip()
        pa_type = form.get(f"pa_type_{i}", "B").strip()
        if pa_type:
            applied_parts.append({"name": pa_name, "part_type": pa_type, "code": ""})
    applied_parts_json = json.dumps(applied_parts) if applied_parts else None
    upd_status = (form.get("status") or "active").strip()
    if upd_status not in ("active", "dismissed", "maintenance"):
        upd_status = "active"

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE devices
            SET serial_number = %s,
                description = %s,
                manufacturer = %s,
                model = %s,
                department = %s,
                customer_inventory = %s,
                ams_inventory = %s,
                applied_parts_json = %s,
                verification_interval = %s,
                default_profile_key = %s,
                default_functional_profile_key = %s,
                status = %s,
                last_modified = %s
            WHERE uuid = %s AND is_deleted = FALSE
            """,
            (
                serial, description, manufacturer, model, department,
                customer_inventory, ams_inventory, applied_parts_json,
                int(verification_interval) if verification_interval else None,
                default_profile_key, default_functional_profile_key, upd_status,
                datetime.now(timezone.utc), uuid,
            ),
        )
        conn.commit()
        conn.close()
        return RedirectResponse(url=f"/mobile/devices/{uuid}", status_code=302)
    except Exception as e:
        logger.error(f"[mobile] device update error: {e}", exc_info=True)
        raise HTTPException(status_code=500)


@app.post("/mobile/devices/{uuid}/delete")
def mobile_device_delete(uuid: str, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE devices SET is_deleted = TRUE, last_modified = %s WHERE uuid = %s AND is_deleted = FALSE", (datetime.now(timezone.utc), uuid))
        conn.commit()
        conn.close()
        return RedirectResponse(url="/mobile/customers", status_code=302)
    except Exception as e:
        logger.error(f"[mobile] device delete error: {e}", exc_info=True)
        raise HTTPException(status_code=500)


# ─── Destinations ────────────────────────────────────────────────────────────

@app.get("/mobile/destinations/{uuid}", response_class=HTMLResponse)
def mobile_destination_detail(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    today_str     = date.today().isoformat()
    threshold_str = (date.today() + timedelta(days=30)).isoformat()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT d.*, c.name AS customer_name, c.uuid AS customer_uuid
            FROM destinations d
            JOIN customers c ON c.id = d.customer_id
            WHERE d.uuid = %s AND d.is_deleted = FALSE
        """, (uuid,))
        destination = cur.fetchone()
        if not destination:
            conn.close()
            raise HTTPException(status_code=404, detail="Destinazione non trovata")

        cur.execute("""
            SELECT uuid, description, manufacturer, model, serial_number,
                   ams_inventory, department, next_verification_date, status
            FROM devices
            WHERE destination_id = %s AND is_deleted = FALSE ORDER BY description
        """, (destination["id"],))
        raw_devices = cur.fetchall()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] destination detail error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    # Converti next_verification_date (datetime.date) a stringa ISO per Jinja2
    devices = [
        {**dict(d), "next_verification_date": d["next_verification_date"].isoformat() if d["next_verification_date"] else None}
        for d in raw_devices
    ]

    return mobile_templates.TemplateResponse("destination_detail.html", {
        "request": request, "user": user, "active_nav": "customers",
        "destination": destination, "customer_name": destination["customer_name"],
        "devices": devices, "back_url": f"/mobile/customers/{destination['customer_uuid']}",
        "today": today_str, "expiry_threshold": threshold_str,
    })


# ─── Devices ─────────────────────────────────────────────────────────────────

@app.get("/mobile/devices/{uuid}", response_class=HTMLResponse)
def mobile_device_detail(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    today_str     = date.today().isoformat()
    threshold_str = (date.today() + timedelta(days=30)).isoformat()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT d.*, dest.name AS destination_name, dest.uuid AS destination_uuid,
                   c.name AS customer_name, c.uuid AS customer_uuid
            FROM devices d
            JOIN destinations dest ON dest.id = d.destination_id
            JOIN customers c ON c.id = dest.customer_id
            WHERE d.uuid = %s AND d.is_deleted = FALSE
        """, (uuid,))
        device = cur.fetchone()
        if not device:
            conn.close()
            raise HTTPException(status_code=404, detail="Dispositivo non trovato")

        cur.execute("""
            SELECT uuid, verification_date, profile_name, overall_status,
                   technician_name, verification_code
            FROM verifications
            WHERE device_id = %s AND is_deleted = FALSE
            ORDER BY verification_date DESC, last_modified DESC
        """, (device["id"],))
        verifications = cur.fetchall()

        cur.execute("""
            SELECT uuid, verification_date, profile_key, overall_status,
                   technician_name, verification_code
            FROM functional_verifications
            WHERE device_id = %s AND is_deleted = FALSE
            ORDER BY verification_date DESC, last_modified DESC
        """, (device["id"],))
        func_verifications = cur.fetchall()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] device detail error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    # Converti next_verification_date (datetime.date) a stringa ISO per Jinja2
    device_dict = dict(device)
    if device_dict.get("next_verification_date") and not isinstance(device_dict["next_verification_date"], str):
        device_dict["next_verification_date"] = device_dict["next_verification_date"].isoformat()
    # Parse applied_parts_json
    raw_ap = device_dict.get("applied_parts_json")
    if raw_ap and isinstance(raw_ap, str):
        try:
            device_dict["applied_parts_json"] = json.loads(raw_ap)
        except Exception:
            device_dict["applied_parts_json"] = []
    elif not isinstance(raw_ap, list):
        device_dict["applied_parts_json"] = []

    return mobile_templates.TemplateResponse("device_detail.html", {
        "request": request, "user": user,
        "device": device_dict, "verifications": verifications,
        "func_verifications": func_verifications,
        "customer_name": device["customer_name"],
        "destination_name": device["destination_name"],
        "today": today_str, "expiry_threshold": threshold_str,
        "back_url": f"/mobile/destinations/{device['destination_uuid']}",
    })


# ─── Verifications ───────────────────────────────────────────────────────────

@app.get("/mobile/verifications/{uuid}", response_class=HTMLResponse)
def mobile_verification_detail(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT v.*, d.uuid AS device_uuid, d.description, d.manufacturer, d.model
            FROM verifications v
            JOIN devices d ON d.id = v.device_id
            WHERE v.uuid = %s AND v.is_deleted = FALSE
        """, (uuid,))
        verification = cur.fetchone()
        if not verification:
            conn.close()
            raise HTTPException(status_code=404)

        device = {"uuid": verification["device_uuid"],
                  "description": verification["description"],
                  "manufacturer": verification["manufacturer"],
                  "model": verification["model"]}

        results = {}
        try:
            raw_res = json.loads(verification.get("results_json") or "{}")
            if isinstance(raw_res, list):
                # Formato lista: [{"name": "Test", "status": "PASS", "value": ...}, ...]
                results = {
                    item.get("name", f"Test {i}"): {
                        "status": item.get("status", ""),
                        "value":  item.get("value"),
                        "unit":   item.get("unit"),
                        "limit":  item.get("limit"),
                    }
                    for i, item in enumerate(raw_res) if isinstance(item, dict)
                }
            elif isinstance(raw_res, dict):
                results = raw_res
        except Exception:
            pass

        visual_inspection = {}
        try:
            visual_inspection = json.loads(verification.get("visual_inspection_json") or "{}")
        except Exception:
            pass

        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] verification detail error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return mobile_templates.TemplateResponse("verification_detail.html", {
        "request": request, "user": user,
        "verification": verification, "device": device,
        "results": results, "visual_inspection": visual_inspection,
        "back_url": f"/mobile/devices/{device['uuid']}",
    })


@app.get("/mobile/func-verifications/{uuid}", response_class=HTMLResponse)
def mobile_func_verification_detail(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT fv.*, d.uuid AS device_uuid, d.description, d.manufacturer, d.model
            FROM functional_verifications fv
            JOIN devices d ON d.id = fv.device_id
            WHERE fv.uuid = %s AND fv.is_deleted = FALSE
        """, (uuid,))
        fv = cur.fetchone()
        if not fv:
            conn.close()
            raise HTTPException(status_code=404)

        device = {"uuid": fv["device_uuid"], "description": fv["description"],
                  "manufacturer": fv["manufacturer"], "model": fv["model"]}

        # Fetch profile name, section titles and field labels from schema
        profile_name = fv["profile_key"]
        section_titles = {}
        field_labels   = {}  # {section_key: {field_key: label}}
        section_types  = {}  # {section_key: section_type}
        try:
            cur.execute("SELECT name, schema_json FROM functional_profiles WHERE profile_key = %s AND is_deleted = FALSE LIMIT 1", (fv["profile_key"],))
            fp_row = cur.fetchone()
            if fp_row:
                profile_name = fp_row["name"] or fv["profile_key"]
                if fp_row["schema_json"]:
                    raw_schema = json.loads(fp_row["schema_json"])
                    secs = raw_schema if isinstance(raw_schema, list) else raw_schema.get("sections", [])
                    for s in secs:
                        sk = s.get("key", "")
                        section_titles[sk] = s.get("title", sk)
                        section_types[sk]  = s.get("section_type", "fields")
                        lbl_map = {}
                        for field in s.get("fields", []):
                            lbl_map[field.get("key", "")] = field.get("label") or field.get("key", "")
                        for row in s.get("rows", []):
                            for field in row.get("fields", []):
                                lbl_map[field.get("key", "")] = field.get("label") or field.get("key", "")
                        field_labels[sk] = lbl_map
        except Exception:
            pass

        # Parse results_json into sections, resolving field keys to human-readable labels
        sections = []
        try:
            raw_results = json.loads(fv.get("results_json") or "{}")
            for section_key, section_data in raw_results.items():
                if not isinstance(section_data, dict):
                    continue
                lbl_map = field_labels.get(section_key, {})
                sec_type = section_types.get(section_key, "fields")

                # --- detect actual data dict ---
                # Desktop format A: {"fields": [...], "rows": {field_key: {"esito": val}}}
                # Desktop format B: {"fields": [...], "rows": [{"key":...,"values":{...}}]}
                # Mobile format:    {field_key: value_string}
                if "rows" in section_data and isinstance(section_data["rows"], dict):
                    actual_data = section_data["rows"]
                elif "rows" in section_data and isinstance(section_data["rows"], list):
                    # rows as list of objects
                    actual_data = {}
                    for row_obj in section_data["rows"]:
                        if isinstance(row_obj, dict):
                            rk = row_obj.get("key") or row_obj.get("label", "")
                            rv = row_obj.get("value") or row_obj.get("esito") or row_obj.get("result", "")
                            if rk:
                                actual_data[rk] = rv
                elif "fields" in section_data and set(section_data.keys()) <= {"fields", "rows", "section_type"}:
                    # Only metadata keys — try fields list for saved values
                    actual_data = {}
                    for f in section_data.get("fields", []):
                        if isinstance(f, dict):
                            fk2 = f.get("key", "")
                            fv2 = f.get("value") or f.get("esito") or f.get("result")
                            if fk2 and fv2 is not None:
                                actual_data[fk2] = fv2
                else:
                    # Mobile-saved flat dict
                    actual_data = {k: v for k, v in section_data.items()
                                   if k not in ("fields", "rows", "section_type")}

                # Resolve keys → labels, and unwrap nested dicts {"esito": val}
                resolved = {}
                for fk, fv_v in actual_data.items():
                    label = lbl_map.get(fk, fk)
                    if isinstance(fv_v, dict):
                        val = (fv_v.get("esito") or fv_v.get("value") or
                               fv_v.get("result") or fv_v.get("stato") or str(fv_v))
                    else:
                        val = fv_v
                    if val is not None and val != "":
                        resolved[label] = val

                if resolved:
                    sections.append({
                        "title": section_titles.get(section_key, section_key),
                        "section_type": sec_type,
                        "data": resolved,
                    })
        except Exception as ex:
            logger.error(f"[mobile] fv detail parse error: {ex}", exc_info=True)

        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] func verification detail error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return mobile_templates.TemplateResponse("func_verification_detail.html", {
        "request": request, "user": user,
        "fv": fv, "device": device, "sections": sections,
        "profile_name": profile_name,
        "back_url": f"/mobile/devices/{device['uuid']}",
    })


@app.get("/mobile/func-verifications/{uuid}/report", response_class=HTMLResponse)
def mobile_func_verification_report(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT fv.*, d.uuid AS device_uuid, d.description, d.manufacturer, d.model,
                   d.serial_number AS device_serial, d.customer_inventory, d.ams_inventory
            FROM functional_verifications fv
            JOIN devices d ON d.id = fv.device_id
            WHERE fv.uuid = %s AND fv.is_deleted = FALSE
        """, (uuid,))
        fv = cur.fetchone()
        if not fv:
            conn.close()
            raise HTTPException(status_code=404)

        device = {
            "uuid": fv["device_uuid"], "description": fv["description"],
            "manufacturer": fv["manufacturer"], "model": fv["model"],
            "serial_number": fv["device_serial"],
            "customer_inventory": fv["customer_inventory"],
            "ams_inventory": fv["ams_inventory"],
        }

        cur.execute("""
            SELECT dest.name AS dest_name, c.name AS cust_name
            FROM devices d
            JOIN destinations dest ON dest.id = d.destination_id
            JOIN customers c ON c.id = dest.customer_id
            WHERE d.uuid = %s
        """, (device["uuid"],))
        loc_row = cur.fetchone()
        customer    = {"name": loc_row["cust_name"]} if loc_row else None
        destination = {"name": loc_row["dest_name"]} if loc_row else None

        profile_name = fv["profile_key"]
        section_titles = {}
        field_labels_r  = {}
        section_types_r = {}
        try:
            cur.execute("SELECT name, schema_json FROM functional_profiles WHERE profile_key = %s AND is_deleted = FALSE LIMIT 1", (fv["profile_key"],))
            fp_row = cur.fetchone()
            if fp_row:
                profile_name = fp_row["name"] or fv["profile_key"]
                if fp_row["schema_json"]:
                    raw_schema = json.loads(fp_row["schema_json"])
                    secs = raw_schema if isinstance(raw_schema, list) else raw_schema.get("sections", [])
                    for s in secs:
                        sk = s.get("key", "")
                        section_titles[sk]   = s.get("title", sk)
                        section_types_r[sk]  = s.get("section_type", "fields")
                        lbl_map = {}
                        for field in s.get("fields", []):
                            lbl_map[field.get("key", "")] = field.get("label") or field.get("key", "")
                        for row in s.get("rows", []):
                            if isinstance(row, dict):
                                for field in row.get("fields", []):
                                    lbl_map[field.get("key", "")] = field.get("label") or field.get("key", "")
                        field_labels_r[sk] = lbl_map
        except Exception:
            pass

        sections = []
        try:
            raw_results = json.loads(fv.get("results_json") or "{}")
            for section_key, section_data in raw_results.items():
                if not isinstance(section_data, dict):
                    continue
                lbl_map  = field_labels_r.get(section_key, {})
                sec_type = section_types_r.get(section_key, "fields")

                if "rows" in section_data and isinstance(section_data["rows"], dict):
                    actual_data = section_data["rows"]
                elif "rows" in section_data and isinstance(section_data["rows"], list):
                    actual_data = {}
                    for row_obj in section_data["rows"]:
                        if isinstance(row_obj, dict):
                            rk = row_obj.get("key") or row_obj.get("label", "")
                            rv = row_obj.get("value") or row_obj.get("esito") or row_obj.get("result", "")
                            if rk:
                                actual_data[rk] = rv
                elif "fields" in section_data and set(section_data.keys()) <= {"fields", "rows", "section_type"}:
                    actual_data = {}
                    for f in section_data.get("fields", []):
                        if isinstance(f, dict):
                            fk2 = f.get("key", "")
                            fv2 = f.get("value") or f.get("esito") or f.get("result")
                            if fk2 and fv2 is not None:
                                actual_data[fk2] = fv2
                else:
                    actual_data = {k: v for k, v in section_data.items()
                                   if k not in ("fields", "rows", "section_type")}

                resolved = {}
                for fk, fv_v in actual_data.items():
                    label = lbl_map.get(fk, fk)
                    if isinstance(fv_v, dict):
                        val = (fv_v.get("esito") or fv_v.get("value") or
                               fv_v.get("result") or fv_v.get("stato") or str(fv_v))
                    else:
                        val = fv_v
                    if val is not None and val != "":
                        resolved[label] = val

                if resolved:
                    sections.append({
                        "title": section_titles.get(section_key, section_key),
                        "section_type": sec_type,
                        "data": resolved,
                    })
        except Exception:
            pass

        signature_img = None
        try:
            cur.execute("SELECT signature_data FROM signatures WHERE username = %s AND is_deleted = FALSE LIMIT 1",
                        (fv.get("technician_username"),))
            sig_row = cur.fetchone()
            if sig_row and sig_row.get("signature_data"):
                import base64
                sig_bytes = sig_row["signature_data"]
                if isinstance(sig_bytes, (bytes, bytearray)):
                    signature_img = base64.b64encode(sig_bytes).decode()
                elif isinstance(sig_bytes, str):
                    signature_img = sig_bytes
        except Exception:
            pass

        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] func verification report error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return mobile_templates.TemplateResponse("func_verification_report.html", {
        "request": request, "user": user,
        "fv": fv, "device": device, "customer": customer, "destination": destination,
        "profile_name": profile_name, "sections": sections,
        "signature_img": signature_img,
    })


# ─── Instruments ─────────────────────────────────────────────────────────────

@app.get("/mobile/verifications/{uuid}/report", response_class=HTMLResponse)
def mobile_verification_report(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT v.*, d.uuid AS device_uuid, d.description, d.manufacturer, d.model,
                   d.serial_number AS device_serial, d.customer_inventory, d.ams_inventory,
                   d.department, d.applied_parts_json, d.next_verification_date
            FROM verifications v
            JOIN devices d ON d.id = v.device_id
            WHERE v.uuid = %s AND v.is_deleted = FALSE
        """, (uuid,))
        verification = cur.fetchone()
        if not verification:
            conn.close()
            raise HTTPException(status_code=404)

        # Parse applied parts
        raw_ap = verification.get("applied_parts_json")
        applied_parts = []
        if raw_ap:
            try:
                applied_parts = json.loads(raw_ap) if isinstance(raw_ap, str) else raw_ap
            except Exception:
                pass

        nvd = verification.get("next_verification_date")
        device = {
            "uuid": verification["device_uuid"],
            "description": verification["description"],
            "manufacturer": verification["manufacturer"],
            "model": verification["model"],
            "serial_number": verification["device_serial"],
            "customer_inventory": verification.get("customer_inventory"),
            "ams_inventory": verification.get("ams_inventory"),
            "department": verification.get("department"),
            "applied_parts": applied_parts,
            "next_verification_date": nvd.isoformat() if nvd and not isinstance(nvd, str) else nvd,
        }

        # Get destination & customer
        cur.execute("""
            SELECT dest.name AS dest_name, c.name AS cust_name
            FROM devices d
            JOIN destinations dest ON dest.id = d.destination_id
            JOIN customers c ON c.id = dest.customer_id
            WHERE d.uuid = %s
        """, (device["uuid"],))
        loc_row = cur.fetchone()
        customer    = {"name": loc_row["cust_name"]}    if loc_row else None
        destination = {"name": loc_row["dest_name"]}    if loc_row else None

        # Parse results
        results = {}
        try:
            raw_res = json.loads(verification.get("results_json") or "{}")
            if isinstance(raw_res, list):
                results = {item.get("name", f"Test {i}"): {
                    "status": item.get("status",""), "value": item.get("value"),
                    "unit": item.get("unit"), "limit": item.get("limit"),
                } for i, item in enumerate(raw_res) if isinstance(item, dict)}
            elif isinstance(raw_res, dict):
                results = raw_res
        except Exception:
            pass

        # Parse visual inspection
        visual_inspection = {}
        try:
            visual_inspection = json.loads(verification.get("visual_inspection_json") or "{}")
        except Exception:
            pass

        # Try to load signature image (base64)
        signature_img = None
        try:
            cur.execute("SELECT signature_data FROM signatures WHERE username = %s AND is_deleted = FALSE LIMIT 1",
                        (verification.get("technician_username"),))
            sig_row = cur.fetchone()
            if sig_row and sig_row.get("signature_data"):
                import base64
                sig_bytes = sig_row["signature_data"]
                if isinstance(sig_bytes, (bytes, bytearray)):
                    signature_img = base64.b64encode(sig_bytes).decode()
                elif isinstance(sig_bytes, str):
                    signature_img = sig_bytes
        except Exception:
            pass

        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] verification report error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return mobile_templates.TemplateResponse("verification_report.html", {
        "request": request, "user": user,
        "verification": verification, "device": device,
        "customer": customer, "destination": destination,
        "results": results, "visual_inspection": visual_inspection,
        "signature_img": signature_img,
        "now_date": date.today().isoformat(),
    })


@app.get("/mobile/instruments", response_class=HTMLResponse)
def mobile_instruments_list(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT uuid, instrument_name, serial_number, calibration_date,
                   fw_version, instrument_type, is_default
            FROM mti_instruments WHERE is_deleted = FALSE
            ORDER BY is_default DESC, instrument_name ASC
        """)
        instruments = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"[mobile] instruments list error: {e}", exc_info=True)
        instruments = []

    return mobile_templates.TemplateResponse("instruments.html", {
        "request": request, "user": user, "active_nav": "instruments",
        "instruments": instruments,
        "today": date.today().isoformat(),
        "warn_threshold": (date.today() + timedelta(days=60)).isoformat(),
    })


@app.get("/mobile/instruments/new", response_class=HTMLResponse)
def mobile_instrument_new_form(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    return mobile_templates.TemplateResponse("instrument_form.html", {
        "request": request, "user": user, "mode": "create",
        "form": {}, "back_url": "/mobile/instruments",
    })


@app.post("/mobile/instruments/new", response_class=HTMLResponse)
async def mobile_instrument_create(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()
    instrument_name = (form.get("instrument_name") or "").strip()
    serial_number   = (form.get("serial_number") or "").strip() or None
    calibration_date = form.get("calibration_date") or None
    fw_version      = (form.get("fw_version") or "").strip() or None
    instrument_type = (form.get("instrument_type") or "").strip() or None
    is_default      = bool(form.get("is_default"))

    if not instrument_name:
        return mobile_templates.TemplateResponse("instrument_form.html", {
            "request": request, "user": user, "mode": "create",
            "form": dict(form), "error": "Il nome strumento è obbligatorio.",
            "back_url": "/mobile/instruments",
        })

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        new_uuid = str(__import__("uuid").uuid4())
        now_ts   = datetime.now(timezone.utc)
        cur.execute("""
            INSERT INTO mti_instruments
                (uuid, instrument_name, serial_number, calibration_date,
                 fw_version, instrument_type, is_default,
                 is_deleted, is_synced, last_modified)
            VALUES (%s,%s,%s,%s,%s,%s,%s,FALSE,FALSE,%s)
        """, (new_uuid, instrument_name, serial_number, calibration_date or None,
              fw_version, instrument_type, is_default, now_ts))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[mobile] instrument create error: {e}", exc_info=True)
        return mobile_templates.TemplateResponse("instrument_form.html", {
            "request": request, "user": user, "mode": "create",
            "form": dict(form), "error": f"Errore durante la creazione: {e}",
            "back_url": "/mobile/instruments",
        })

    return RedirectResponse(url="/mobile/instruments", status_code=303)


@app.get("/mobile/instruments/{uuid}/edit", response_class=HTMLResponse)
def mobile_instrument_edit_form(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM mti_instruments WHERE uuid = %s AND is_deleted = FALSE", (uuid,))
        instr = cur.fetchone()
        conn.close()
        if not instr:
            raise HTTPException(status_code=404)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] instrument edit form error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    # Convert date to string if needed
    cd = instr.get("calibration_date")
    form_data = dict(instr)
    if cd and not isinstance(cd, str):
        form_data["calibration_date"] = cd.isoformat()

    return mobile_templates.TemplateResponse("instrument_form.html", {
        "request": request, "user": user, "mode": "edit",
        "instrument": instr, "form": form_data,
        "back_url": "/mobile/instruments",
    })


@app.post("/mobile/instruments/{uuid}/edit", response_class=HTMLResponse)
async def mobile_instrument_update(uuid: str, request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()
    instrument_name = (form.get("instrument_name") or "").strip()
    serial_number   = (form.get("serial_number") or "").strip() or None
    calibration_date = form.get("calibration_date") or None
    fw_version      = (form.get("fw_version") or "").strip() or None
    instrument_type = (form.get("instrument_type") or "").strip() or None
    is_default      = bool(form.get("is_default"))

    if not instrument_name:
        try:
            conn = get_db_connection()
            cur  = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM mti_instruments WHERE uuid = %s AND is_deleted = FALSE", (uuid,))
            instr = cur.fetchone()
            conn.close()
        except Exception:
            instr = None
        return mobile_templates.TemplateResponse("instrument_form.html", {
            "request": request, "user": user, "mode": "edit",
            "instrument": instr or {"uuid": uuid}, "form": dict(form),
            "error": "Il nome strumento è obbligatorio.",
            "back_url": "/mobile/instruments",
        })

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        now_ts = datetime.now(timezone.utc)
        cur.execute("""
            UPDATE mti_instruments SET
                instrument_name=%s, serial_number=%s, calibration_date=%s,
                fw_version=%s, instrument_type=%s, is_default=%s,
                is_synced=FALSE, last_modified=%s
            WHERE uuid=%s AND is_deleted=FALSE
        """, (instrument_name, serial_number, calibration_date or None,
              fw_version, instrument_type, is_default, now_ts, uuid))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[mobile] instrument update error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return RedirectResponse(url="/mobile/instruments", status_code=303)


@app.post("/mobile/instruments/{uuid}/delete", response_class=HTMLResponse)
def mobile_instrument_delete(uuid: str, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        now_ts = datetime.now(timezone.utc)
        cur.execute("UPDATE mti_instruments SET is_deleted=TRUE, is_synced=FALSE, last_modified=%s WHERE uuid=%s",
                    (now_ts, uuid))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[mobile] instrument delete error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return RedirectResponse(url="/mobile/instruments", status_code=303)


# ─── Delete Verifications ────────────────────────────────────────────────────

@app.post("/mobile/verifications/{uuid}/delete", response_class=HTMLResponse)
def mobile_verification_delete(uuid: str, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT d.uuid AS device_uuid FROM verifications v JOIN devices d ON d.id = v.device_id WHERE v.uuid = %s AND v.is_deleted = FALSE", (uuid,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404)
        device_uuid = row["device_uuid"]
        now_ts = datetime.now(timezone.utc)
        cur.execute("UPDATE verifications SET is_deleted=TRUE, last_modified=%s WHERE uuid=%s", (now_ts, uuid))
        conn.commit()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] verification delete error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return RedirectResponse(url=f"/mobile/devices/{device_uuid}?tab=ve", status_code=303)


@app.post("/mobile/func-verifications/{uuid}/delete", response_class=HTMLResponse)
def mobile_func_verification_delete(uuid: str, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT d.uuid AS device_uuid FROM functional_verifications fv JOIN devices d ON d.id = fv.device_id WHERE fv.uuid = %s AND fv.is_deleted = FALSE", (uuid,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404)
        device_uuid = row["device_uuid"]
        now_ts = datetime.now(timezone.utc)
        cur.execute("UPDATE functional_verifications SET is_deleted=TRUE, last_modified=%s WHERE uuid=%s", (now_ts, uuid))
        conn.commit()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] func verification delete error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return RedirectResponse(url=f"/mobile/devices/{device_uuid}?tab=vf", status_code=303)


# ─── New Verification (Elettrica) ────────────────────────────────────────────

@app.get("/mobile/devices/{device_uuid}/new-verification", response_class=HTMLResponse)
def mobile_new_verification_form(device_uuid: str, request: Request,
                                  mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM devices WHERE uuid = %s AND is_deleted = FALSE", (device_uuid,))
        device = cur.fetchone()
        if not device:
            conn.close()
            raise HTTPException(status_code=404)

        cur.execute("""
            SELECT DISTINCT ON (p.profile_key) p.profile_key, p.name
            FROM profiles p
            WHERE p.is_deleted = FALSE ORDER BY p.profile_key, p.last_modified DESC
        """)
        profiles = cur.fetchall()
        cur.execute("""
            SELECT uuid, instrument_name, serial_number, calibration_date
            FROM mti_instruments
            WHERE is_deleted = FALSE
              AND (instrument_type IS NULL OR instrument_type = '' OR instrument_type = 'electrical')
            ORDER BY is_default DESC, instrument_name ASC
        """)
        instruments = cur.fetchall()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] new verification form error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    today_str = date.today().isoformat()
    return mobile_templates.TemplateResponse("new_verification.html", {
        "request": request, "user": user,
        "device": device, "profiles": profiles, "instruments": instruments, "today": today_str,
        "selected_profile": device.get("default_profile_key") or "",
        "back_url": f"/mobile/devices/{device_uuid}",
    })


@app.post("/mobile/devices/{device_uuid}/new-verification", response_class=HTMLResponse)
async def mobile_save_verification(device_uuid: str, request: Request,
                                    mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()

    verification_date = form.get("verification_date") or date.today().isoformat()
    profile_key       = form.get("profile_key", "").strip()
    overall_status    = form.get("overall_status", "PASSATO")
    instrument_uuid   = form.get("instrument_uuid", "").strip()
    notes             = form.get("notes", "").strip() or None
    test_count        = int(form.get("test_count", 0) or 0)

    def _load_form_data(conn_):
        cur_ = conn_.cursor(cursor_factory=RealDictCursor)
        cur_.execute("SELECT * FROM devices WHERE uuid = %s AND is_deleted = FALSE", (device_uuid,))
        dev_ = cur_.fetchone()
        cur_.execute("SELECT DISTINCT ON (p.profile_key) p.profile_key, p.name FROM profiles p WHERE p.is_deleted = FALSE ORDER BY p.profile_key, p.last_modified DESC")
        prof_ = cur_.fetchall()
        cur_.execute("SELECT uuid, instrument_name, serial_number, calibration_date FROM mti_instruments WHERE is_deleted = FALSE AND (instrument_type IS NULL OR instrument_type = '' OR instrument_type = 'electrical') ORDER BY is_default DESC, instrument_name ASC")
        inst_ = cur_.fetchall()
        conn_.close()
        return dev_, prof_, inst_

    if not profile_key:
        conn = get_db_connection()
        device, profiles, instruments = _load_form_data(conn)
        return mobile_templates.TemplateResponse("new_verification.html", {
            "request": request, "user": user,
            "device": device, "profiles": profiles, "instruments": instruments,
            "today": verification_date,
            "error": "Seleziona un profilo di verifica.",
            "back_url": f"/mobile/devices/{device_uuid}",
        })

    if not instrument_uuid:
        conn = get_db_connection()
        device, profiles, instruments = _load_form_data(conn)
        return mobile_templates.TemplateResponse("new_verification.html", {
            "request": request, "user": user,
            "device": device, "profiles": profiles, "instruments": instruments,
            "today": verification_date, "selected_profile": profile_key,
            "error": "Seleziona uno strumento di misura.",
            "back_url": f"/mobile/devices/{device_uuid}",
        })

    # Build results dict from form fields
    results: Dict[str, Any] = {}
    for i in range(test_count):
        test_name   = form.get(f"test_name_{i}", "").strip()
        test_status = form.get(f"test_status_{i}", "PASS")
        test_value  = form.get(f"test_value_{i}", "").strip()
        if test_name:
            results[test_name] = {"status": test_status, "value": test_value or None}

    # Build visual inspection JSON
    VI_ITEMS = [
        "Involucro e parti meccaniche integri, senza danni.",
        "Cavo di alimentazione e spina senza danneggiamenti.",
        "Cavi paziente, connettori e accessori integri.",
        "Marcature e targhette di sicurezza leggibili.",
        "Assenza di sporcizia o segni di versamento di liquidi.",
        "Corretta procedura di accensione.",
        "Fusibili (se accessibili) di tipo e valore corretti.",
    ]
    vi_checklist = [{"item": item, "result": form.get(f"vi_{i}", "OK")} for i, item in enumerate(VI_ITEMS)]
    vi_notes = (form.get("vi_notes") or "").strip()
    visual_inspection_json = json.dumps({"checklist": vi_checklist, "notes": vi_notes})

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT id, uuid FROM devices WHERE uuid = %s AND is_deleted = FALSE", (device_uuid,))
        device_row = cur.fetchone()
        if not device_row:
            conn.close()
            raise HTTPException(status_code=404)

        # Get profile name
        cur.execute("SELECT name FROM profiles WHERE profile_key = %s AND is_deleted = FALSE LIMIT 1", (profile_key,))
        profile_row = cur.fetchone()
        profile_name = profile_row["name"] if profile_row else profile_key

        # Get instrument info from DB
        cur.execute("SELECT instrument_name, serial_number, calibration_date FROM mti_instruments WHERE uuid = %s AND is_deleted = FALSE", (instrument_uuid,))
        instr_row = cur.fetchone()
        mti_instrument = instr_row["instrument_name"] if instr_row else None
        mti_serial     = instr_row["serial_number"]   if instr_row else None
        mti_cal_date   = instr_row["calibration_date"] if instr_row else None

        new_uuid  = str(__import__("uuid").uuid4())
        now_ts    = datetime.now(timezone.utc)

        # Generate verification code: INIZIALI-AAMMGG-NNNN-VE
        tech_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username
        def _initials(name):
            parts = name.split()
            if len(parts) >= 2:
                return (parts[0][0] + parts[1][0]).upper()
            return name[:2].upper() if len(name) >= 2 else "XX"
        initials  = _initials(tech_name)
        try:
            date_prefix = datetime.strptime(verification_date, '%Y-%m-%d').strftime('%y%m%d')
        except Exception:
            date_prefix = datetime.now().strftime('%y%m%d')
        full_prefix = f"{initials}-{date_prefix}-"
        cur.execute(
            "SELECT verification_code FROM verifications WHERE verification_code LIKE %s ORDER BY verification_code DESC LIMIT 1",
            (f"{full_prefix}%-VE",)
        )
        last_code_row = cur.fetchone()
        if last_code_row and last_code_row["verification_code"]:
            try:
                core = last_code_row["verification_code"][len(full_prefix):]
                num  = int(core.split("-")[0]) + 1
            except Exception:
                num = 1
        else:
            num = 1
        verification_code = f"{full_prefix}{num:04d}-VE"

        cur.execute("""
            INSERT INTO verifications (
                uuid, device_id, verification_date, profile_name,
                results_json, overall_status, visual_inspection_json,
                mti_instrument, mti_serial, mti_cal_date,
                technician_name, technician_username, verification_code, notes,
                last_modified, is_deleted, is_synced
            ) VALUES (%s,%s,%s,%s, %s,%s,%s, %s,%s,%s, %s,%s,%s,%s, %s,FALSE,TRUE)
        """, (
            new_uuid, device_row["id"], verification_date, profile_name,
            json.dumps(results), overall_status, visual_inspection_json,
            mti_instrument, mti_serial, mti_cal_date,
            tech_name, user.username, verification_code, notes,
            now_ts,
        ))
        conn.commit()

        # Update device next_verification_date if interval is set
        cur.execute("""
            UPDATE devices SET
                last_modified = %s,
                next_verification_date = CASE
                    WHEN verification_interval IS NOT NULL AND verification_interval > 0
                    THEN (%s::date + (verification_interval || ' months')::interval)::date
                    ELSE next_verification_date
                END
            WHERE id = %s
        """, (now_ts, verification_date, device_row["id"]))
        conn.commit()
        conn.close()

        logger.info(f"[mobile] New verification {verification_code} saved by {user.username}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] save verification error: {e}", exc_info=True)
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        device, profiles, instruments = _load_form_data(get_db_connection())
        return mobile_templates.TemplateResponse("new_verification.html", {
            "request": request, "user": user,
            "device": device, "profiles": profiles, "instruments": instruments,
            "today": verification_date,
            "selected_profile": profile_key,
            "error": f"Errore durante il salvataggio: {e}",
            "back_url": f"/mobile/devices/{device_uuid}",
        })

    return RedirectResponse(url=f"/mobile/devices/{device_uuid}?tab=ve", status_code=302)


# ─── New Functional Verification ─────────────────────────────────────────────

@app.get("/mobile/devices/{device_uuid}/new-func-verification", response_class=HTMLResponse)
def mobile_new_func_verification_form(device_uuid: str, request: Request,
                                       mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM devices WHERE uuid = %s AND is_deleted = FALSE", (device_uuid,))
        device = cur.fetchone()
        if not device:
            conn.close()
            raise HTTPException(status_code=404)

        cur.execute("""
            SELECT profile_key, name, device_type
            FROM functional_profiles WHERE is_deleted = FALSE ORDER BY name
        """)
        functional_profiles = cur.fetchall()
        cur.execute("""
            SELECT uuid, instrument_name, serial_number, calibration_date
            FROM mti_instruments
            WHERE is_deleted = FALSE AND instrument_type = 'functional'
            ORDER BY is_default DESC, instrument_name ASC
        """)
        func_instruments = cur.fetchall()
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] new func ver form error: {e}", exc_info=True)
        raise HTTPException(status_code=500)

    return mobile_templates.TemplateResponse("new_func_verification.html", {
        "request": request, "user": user,
        "device": device, "functional_profiles": functional_profiles,
        "instruments": func_instruments,
        "selected_profile": device.get("default_functional_profile_key") or "",
        "today": date.today().isoformat(),
        "back_url": f"/mobile/devices/{device_uuid}",
    })


@app.post("/mobile/devices/{device_uuid}/new-func-verification", response_class=HTMLResponse)
async def mobile_save_func_verification(device_uuid: str, request: Request,
                                         mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()
    verification_date = form.get("verification_date") or date.today().isoformat()
    profile_key       = form.get("profile_key", "").strip()
    overall_status    = form.get("overall_status", "PASSATO")
    notes             = form.get("notes", "").strip() or None
    instrument_uuid   = form.get("instrument_uuid", "").strip()
    results: Dict[str, Any] = {}
    for key, value in form.items():
        if key.startswith("field_") and value:
            parts = key.split("_", 2)  # field_SECTION_FIELD
            if len(parts) == 3:
                _, section_key, field_key = parts
                if section_key not in results:
                    results[section_key] = {}
                results[section_key][field_key] = value

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id FROM devices WHERE uuid = %s AND is_deleted = FALSE", (device_uuid,))
        device_row = cur.fetchone()
        if not device_row:
            conn.close()
            raise HTTPException(status_code=404)

        # Look up instrument
        mti_instrument = None; mti_serial = None; mti_cal_date = None
        if instrument_uuid:
            cur.execute("SELECT instrument_name, serial_number, calibration_date FROM mti_instruments WHERE uuid = %s AND is_deleted = FALSE", (instrument_uuid,))
            instr_row = cur.fetchone()
            mti_instrument = instr_row["instrument_name"] if instr_row else None
            mti_serial     = instr_row["serial_number"]   if instr_row else None
            mti_cal_date   = instr_row["calibration_date"] if instr_row else None

        new_uuid = str(__import__("uuid").uuid4())
        now_ts   = datetime.now(timezone.utc)
        tech_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username

        # Generate verification code: INIZIALI-AAMMGG-NNNN-VF
        def _initials_vf(name):
            parts = name.split()
            if len(parts) >= 2:
                return (parts[0][0] + parts[1][0]).upper()
            return name[:2].upper() if len(name) >= 2 else "XX"
        initials_vf = _initials_vf(tech_name)
        try:
            date_prefix_vf = datetime.strptime(verification_date, '%Y-%m-%d').strftime('%y%m%d')
        except Exception:
            date_prefix_vf = datetime.now().strftime('%y%m%d')
        full_prefix_vf = f"{initials_vf}-{date_prefix_vf}-"
        cur.execute(
            "SELECT verification_code FROM functional_verifications WHERE verification_code LIKE %s ORDER BY verification_code DESC LIMIT 1",
            (f"{full_prefix_vf}%-VF",)
        )
        last_vf_row = cur.fetchone()
        if last_vf_row and last_vf_row["verification_code"]:
            try:
                core_vf = last_vf_row["verification_code"][len(full_prefix_vf):]
                num_vf  = int(core_vf.split("-")[0]) + 1
            except Exception:
                num_vf = 1
        else:
            num_vf = 1
        verification_code_vf = f"{full_prefix_vf}{num_vf:04d}-VF"

        cur.execute("""
            INSERT INTO functional_verifications (
                uuid, device_id, profile_key, verification_date,
                technician_name, technician_username,
                mti_instrument, mti_serial, mti_cal_date,
                results_json, structured_results_json, overall_status, notes,
                verification_code,
                last_modified, is_deleted, is_synced
            ) VALUES (%s,%s,%s,%s, %s,%s, %s,%s,%s, %s,%s,%s,%s, %s, %s,FALSE,TRUE)
        """, (
            new_uuid, device_row["id"], profile_key, verification_date,
            tech_name, user.username,
            mti_instrument, mti_serial, mti_cal_date,
            json.dumps(results), json.dumps(results), overall_status, notes,
            verification_code_vf,
            now_ts,
        ))
        conn.commit()
        conn.close()
        logger.info(f"[mobile] New func verification saved by {user.username}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[mobile] save func verification error: {e}", exc_info=True)
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM devices WHERE uuid = %s", (device_uuid,))
        device = cur.fetchone()
        cur.execute("SELECT profile_key, name, device_type FROM functional_profiles WHERE is_deleted = FALSE ORDER BY name")
        functional_profiles = cur.fetchall()
        cur.execute("SELECT uuid, instrument_name, serial_number, calibration_date FROM mti_instruments WHERE is_deleted = FALSE AND instrument_type = 'functional' ORDER BY is_default DESC, instrument_name ASC")
        func_instruments = cur.fetchall()
        conn.close()
        return mobile_templates.TemplateResponse("new_func_verification.html", {
            "request": request, "user": user,
            "device": device, "functional_profiles": functional_profiles,
            "instruments": func_instruments,
            "selected_profile": profile_key,
            "today": verification_date, "error": f"Errore: {e}",
            "back_url": f"/mobile/devices/{device_uuid}",
        })

    return RedirectResponse(url=f"/mobile/devices/{device_uuid}", status_code=302)


# ─── HTMX Partial: Profile Tests ─────────────────────────────────────────────

@app.get("/mobile/partials/profile-tests", response_class=HTMLResponse)
def mobile_profile_tests_partial(request: Request, profile_key: str = "",
                                  mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return HTMLResponse("")

    tests = []
    if profile_key:
        try:
            conn = get_db_connection()
            cur  = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT pt.name, pt.parameter, pt.limits_json, pt.is_applied_part_test
                FROM profile_tests pt
                JOIN profiles p ON p.id = pt.profile_id
                WHERE p.profile_key = %s AND pt.is_deleted = FALSE AND p.is_deleted = FALSE
                ORDER BY pt.id
            """, (profile_key,))
            raw_tests = cur.fetchall()
            conn.close()
            for t in raw_tests:
                limits = {}
                try:
                    limits = json.loads(t["limits_json"] or "{}")
                except Exception:
                    pass
                tests.append({
                    "name": t["name"],
                    "parameter": t["parameter"],
                    "is_applied_part_test": t["is_applied_part_test"],
                    "limits": limits,  # dict: {"::ST": {"unit": "mA", "high_value": 0.5}, ...}
                })
        except Exception as e:
            logger.error(f"[mobile] profile tests partial error: {e}", exc_info=True)

    return mobile_templates.TemplateResponse("partials/profile_tests.html", {
        "request": request, "tests": tests,
    })


# ─── HTMX Partial: Functional Profile Schema ─────────────────────────────────

@app.get("/mobile/partials/functional-profile-schema", response_class=HTMLResponse)
def mobile_func_profile_schema_partial(request: Request, profile_key: str = "",
                                        mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return HTMLResponse("")

    sections = []
    if profile_key:
        try:
            conn = get_db_connection()
            cur  = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT schema_json FROM functional_profiles
                WHERE profile_key = %s AND is_deleted = FALSE
            """, (profile_key,))
            row = cur.fetchone()
            conn.close()
            if row and row["schema_json"]:
                schema = json.loads(row["schema_json"])
                if isinstance(schema, list):
                    sections = schema
                elif isinstance(schema, dict):
                    sections = schema.get("sections", [])
        except Exception as e:
            logger.error(f"[mobile] func profile schema error: {e}", exc_info=True)

    # Convert to dataclass-like dicts for template
    def _parse_field(f):
        return type("F", (), {
            "key": f.get("key",""), "label": f.get("label",""),
            "field_type": f.get("field_type","text"),
            "required": f.get("required", False),
            "unit": f.get("unit"), "options": f.get("options",[]),
            "placeholder": f.get("placeholder"),
            "help_text": f.get("help_text"),
            "min_value": f.get("min_value"),
            "max_value": f.get("max_value"),
            "step": f.get("step"),
            "rating_max": f.get("rating_max", 5),
        })()

    parsed_sections = []
    for s in sections:
        fields = [_parse_field(f) for f in s.get("fields", [])]
        rows_raw = s.get("rows", [])
        rows = []
        for r in rows_raw:
            rows.append(type("R", (), {
                "key": r.get("key",""), "label": r.get("label"),
                "fields": [_parse_field(f) for f in r.get("fields", [])],
            })())
        parsed_sections.append(type("S", (), {
            "key": s.get("key",""), "title": s.get("title",""),
            "section_type": s.get("section_type","fields"),
            "fields": fields, "rows": rows,
        })())

    return mobile_templates.TemplateResponse("partials/functional_schema.html", {
        "request": request, "sections": parsed_sections,
    })


# ─── Search ──────────────────────────────────────────────────────────────────

@app.get("/mobile/search", response_class=HTMLResponse)
def mobile_search_page(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()
    return mobile_templates.TemplateResponse("search.html", {
        "request": request, "user": user, "active_nav": "search",
    })


@app.get("/mobile/partials/search-results", response_class=HTMLResponse)
def mobile_search_results(request: Request, q: str = "",
                           mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return HTMLResponse(status_code=401)

    customers     = []
    devices       = []
    verifications = []
    if q and len(q) >= 2:
        try:
            conn = get_db_connection()
            cur  = conn.cursor(cursor_factory=RealDictCursor)
            like = f"%{q}%"
            cur.execute("""
                SELECT uuid, name, address FROM customers
                WHERE is_deleted = FALSE AND (name ILIKE %s OR address ILIKE %s)
                ORDER BY name LIMIT 20
            """, (like, like))
            customers = cur.fetchall()

            cur.execute("""
                SELECT d.uuid, d.description, d.manufacturer, d.model,
                       d.serial_number, d.ams_inventory, d.customer_inventory,
                       c.name AS customer_name, dest.name AS destination_name
                FROM devices d
                JOIN destinations dest ON dest.id = d.destination_id
                JOIN customers c ON c.id = dest.customer_id
                WHERE d.is_deleted = FALSE AND (
                    d.description ILIKE %s OR d.serial_number ILIKE %s OR
                    d.ams_inventory ILIKE %s OR d.model ILIKE %s OR
                    d.manufacturer ILIKE %s OR d.customer_inventory ILIKE %s
                )
                ORDER BY d.description LIMIT 30
            """, (like, like, like, like, like, like))
            devices = cur.fetchall()

            cur.execute("""
                SELECT v.uuid, v.verification_date, v.profile_name, v.verification_code, v.overall_status,
                       d.description AS device_description
                FROM verifications v
                JOIN devices d ON d.id = v.device_id
                WHERE v.is_deleted = FALSE AND (
                    v.verification_code ILIKE %s OR v.profile_name ILIKE %s OR
                    v.technician_name ILIKE %s OR d.description ILIKE %s
                )
                ORDER BY v.verification_date DESC LIMIT 15
            """, (like, like, like, like))
            verifications = cur.fetchall()
            conn.close()
        except Exception as e:
            logger.error(f"[mobile] search error: {e}", exc_info=True)

    return mobile_templates.TemplateResponse("partials/search_results.html", {
        "request": request, "customers": customers, "devices": devices,
        "verifications": verifications, "q": q,
    })


# ─── Profile page ────────────────────────────────────────────────────────────

@app.get("/mobile/profile", response_class=HTMLResponse)
def mobile_profile_page(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()
    return mobile_templates.TemplateResponse("profile_page.html", {
        "request": request, "user": user, "active_nav": "profile",
    })


@app.post("/mobile/profile/change-password", response_class=HTMLResponse)
async def mobile_change_password(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    form = await request.form()
    current_pw  = (form.get("current_password") or "").strip()
    new_pw      = (form.get("new_password") or "").strip()
    confirm_pw  = (form.get("confirm_password") or "").strip()

    def _render(error=None, success=None):
        return mobile_templates.TemplateResponse("profile_page.html", {
            "request": request, "user": user, "active_nav": "profile",
            "pw_error": error, "pw_success": success,
        })

    if not current_pw or not new_pw or not confirm_pw:
        return _render(error="Compilare tutti i campi.")
    if new_pw != confirm_pw:
        return _render(error="Le nuove password non coincidono.")
    if len(new_pw) < 6:
        return _render(error="La password deve avere almeno 6 caratteri.")

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT hashed_password FROM users WHERE username = %s AND is_deleted = FALSE", (user.username,))
        row = cur.fetchone()
        if not row or not verify_password(current_pw, row["hashed_password"]):
            conn.close()
            return _render(error="Password attuale non corretta.")
        new_hash = get_password_hash(new_pw)
        cur.execute(
            "UPDATE users SET hashed_password = %s, last_modified = %s WHERE username = %s AND is_deleted = FALSE",
            (new_hash, datetime.now(timezone.utc), user.username),
        )
        conn.commit()
        conn.close()
        return _render(success="Password aggiornata con successo.")
    except Exception as e:
        logger.error(f"[mobile] change password error: {e}", exc_info=True)
        return _render(error=f"Errore durante l'aggiornamento: {e}")


# ─── Expiring devices ────────────────────────────────────────────────────────

@app.get("/mobile/expiring", response_class=HTMLResponse)
def mobile_expiring(request: Request, mobile_session: Optional[str] = Cookie(None)):
    user = _mobile_user_from_cookie(mobile_session)
    if not user:
        return _mobile_redirect_login()

    try:
        conn = get_db_connection()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT d.uuid, d.description, d.model, d.serial_number, d.next_verification_date,
                   c.name AS customer_name, dest.name AS destination_name
            FROM devices d
            JOIN destinations dest ON dest.id = d.destination_id
            JOIN customers c ON c.id = dest.customer_id
            WHERE d.is_deleted = FALSE AND d.status = 'active'
            AND d.next_verification_date IS NOT NULL
            AND d.next_verification_date < CURRENT_DATE
            ORDER BY d.next_verification_date
        """)
        overdue_devices = cur.fetchall()

        cur.execute("""
            SELECT d.uuid, d.description, d.model, d.serial_number, d.next_verification_date,
                   c.name AS customer_name, dest.name AS destination_name
            FROM devices d
            JOIN destinations dest ON dest.id = d.destination_id
            JOIN customers c ON c.id = dest.customer_id
            WHERE d.is_deleted = FALSE AND d.status = 'active'
            AND d.next_verification_date IS NOT NULL
            AND d.next_verification_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
            ORDER BY d.next_verification_date
        """)
        expiring_devices = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"[mobile] expiring error: {e}", exc_info=True)
        overdue_devices = []; expiring_devices = []

    return mobile_templates.TemplateResponse("expiring_devices.html", {
        "request": request, "user": user, "active_nav": "dashboard",
        "overdue_devices": overdue_devices, "expiring_devices": expiring_devices,
        "back_url": "/mobile/dashboard",
    })


# ════════════════════════════════════════════════════════════════════════════════

# Blocco per l'esecuzione diretta
if __name__ == "__main__":
    import uvicorn
    import asyncio
    import platform
    
    # Fix per Windows: evita "Exception in callback _ProactorBasePipeTransport._call_connection_lost()"
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # --- MODALITÀ CLOUDFLARE TUNNEL ---
    # Con CLOUDFLARE_TUNNEL=true il server gira in HTTP su 127.0.0.1 perché
    # cloudflared gestisce TLS e Zero Trust. Non è necessario né consigliato
    # esporre la porta all'esterno o usare un certificato SSL locale.
    if CLOUDFLARE_TUNNEL:
        host = os.getenv("SERVER_HOST", "127.0.0.1")  # Solo localhost, mai 0.0.0.0
        port = int(os.getenv("SERVER_PORT", 8000))
        uvicorn_kwargs = {
            "host": host,
            "port": port,
            "log_level": "info",
            "server_header": False,
        }
        logger.info(f"☁️  Modalità Cloudflare Zero Trust Tunnel attiva")
        logger.info(f"🔒 Il server ascolta SOLO su http://{host}:{port} (TLS gestito da cloudflared)")
        logger.info(f"   Assicurati che cloudflared punti a http://127.0.0.1:{port}")
    else:
        host = os.getenv("SERVER_HOST", "0.0.0.0")
        port = int(os.getenv("SERVER_PORT", 8000))

        # --- CONFIGURAZIONE SSL/HTTPS (solo modalità diretta, senza tunnel) ---
        ssl_certfile = os.getenv("SSL_CERTFILE")
        ssl_keyfile = os.getenv("SSL_KEYFILE")

        uvicorn_kwargs = {
            "host": host,
            "port": port,
            "log_level": "info",
            "server_header": False,
        }

        if ssl_certfile and ssl_keyfile:
            if os.path.isfile(ssl_certfile) and os.path.isfile(ssl_keyfile):
                uvicorn_kwargs["ssl_certfile"] = ssl_certfile
                uvicorn_kwargs["ssl_keyfile"] = ssl_keyfile
                logger.info(f"🔒 HTTPS abilitato con certificato: {ssl_certfile}")
            else:
                logger.error(f"✗ File SSL non trovati: cert={ssl_certfile}, key={ssl_keyfile}")
                raise RuntimeError("File SSL non trovati: impossibile avviare il server senza HTTPS!")
        else:
            logger.error("⚠ SSL non configurato: impossibile avviare il server senza HTTPS!")
            raise RuntimeError("SSL_CERTFILE e/o SSL_KEYFILE non configurati: impossibile avviare il server senza HTTPS!")

    protocol = "https" if "ssl_certfile" in uvicorn_kwargs else "http"
    logger.info(f"🚀 Avvio server su {protocol}://{host}:{port}")
    
    uvicorn.run(app, **uvicorn_kwargs)