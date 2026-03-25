# real_server.py (Versione Robusta con Validazione, Logging e Transazioni Atomiche)

from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
import psycopg2
from psycopg2 import errors
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone, date, timedelta
import logging
import base64
import os
import sys
import json
import hashlib
import time
import collections
from dotenv import load_dotenv
# Sicurezza
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash
from jose import JWTError, ExpiredSignatureError, jwt

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
SECRET_KEY = os.getenv("SECRET_KEY") # IN PRODUZIONE, QUESTA CHIAVE DOVREBBE ESSERE GESTITA IN MODO SICURO
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 30)) # 30 giorni

# Sync configuration
SYNC_DATA_VERSION = "1.0"
MAX_PAYLOAD_SIZE = 50 * 1024 * 1024  # 50MB

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
ph = PasswordHasher()

DB_PARAMS = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT")
}
TABLES_TO_SYNC = ["customers", "mti_instruments", "signatures", "profiles", "profile_tests", "functional_profiles", "destinations", "devices", "verifications", "functional_verifications", "audit_log"]

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
        # {ip: deque([timestamp, ...])} per tentativi di login
        self.login_attempts = collections.defaultdict(lambda: collections.deque())
        # {ip: timestamp_sblocco} per IP bloccati
        self.blocked_ips = {}
        
        # Limiti configurabili
        self.GENERAL_LIMIT = 60       # richieste/minuto generiche
        self.GENERAL_WINDOW = 60      # finestra in secondi
        self.LOGIN_LIMIT = 5          # tentativi login/minuto
        self.LOGIN_WINDOW = 60        # finestra in secondi
        self.BLOCK_DURATION = 900     # blocco 15 minuti (in secondi)
        self.LOGIN_BLOCK_THRESHOLD = 10  # dopo 10 tentativi falliti → blocco
    
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
    
    def check_general(self, ip: str) -> bool:
        """Controlla il rate limit generico. Ritorna True se la richiesta è permessa."""
        if self.is_blocked(ip):
            return False
        self._cleanup(self.requests[ip], self.GENERAL_WINDOW)
        if len(self.requests[ip]) >= self.GENERAL_LIMIT:
            return False
        self.requests[ip].append(time.time())
        return True
    
    def check_login(self, ip: str) -> bool:
        """Controlla il rate limit per login. Ritorna True se il tentativo è permesso."""
        if self.is_blocked(ip):
            return False
        self._cleanup(self.login_attempts[ip], self.LOGIN_WINDOW)
        if len(self.login_attempts[ip]) >= self.LOGIN_LIMIT:
            # Se supera la soglia di blocco, blocca l'IP
            if len(self.login_attempts[ip]) >= self.LOGIN_BLOCK_THRESHOLD:
                self.blocked_ips[ip] = time.time() + self.BLOCK_DURATION
                logger.warning(f"🚫 IP {ip} BLOCCATO per {self.BLOCK_DURATION}s - troppi tentativi di login")
            return False
        self.login_attempts[ip].append(time.time())
        return True
    
    def get_retry_after(self, ip: str, is_login: bool = False) -> int:
        """Ritorna i secondi da attendere prima di riprovare."""
        if ip in self.blocked_ips:
            return max(1, int(self.blocked_ips[ip] - time.time()))
        return self.LOGIN_WINDOW if is_login else self.GENERAL_WINDOW

rate_limiter = RateLimiter()

# --- MIDDLEWARE DI SICUREZZA ---
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request

class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Middleware che applica:
    1. Rate limiting per IP
    2. Rate limiting aggressivo su /token (anti brute-force)
    3. Headers di sicurezza su tutte le risposte
    """
    async def dispatch(self, request: Request, call_next):
        # Ottieni IP del client
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path
        
        # Rate limit specifico per /token (login)
        if path == "/token" and request.method == "POST":
            if not rate_limiter.check_login(client_ip):
                retry_after = rate_limiter.get_retry_after(client_ip, is_login=True)
                logger.warning(f"⚠️ Rate limit LOGIN superato per IP {client_ip}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Troppi tentativi di login. Riprova tra {retry_after} secondi."},
                    headers={"Retry-After": str(retry_after)}
                )
        
        # Rate limit generico (escluso /health per monitoring)
        elif path != "/health":
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
        response.headers["Cache-Control"] = "no-store"
        # Nascondi informazioni sul server
        response.headers["Server"] = "SyncAPI"
        
        return response

app.add_middleware(SecurityMiddleware)

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

# --- MODELLI DATI (Pydantic) ---
class User(BaseModel):
    username: str
    role: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

class UserCreate(User):
    password: str

class UserUpdate(BaseModel):
    role: Optional[str] = None
    password: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

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
    audit_log: List[SyncRecord] = []

class SyncPayload(BaseModel):
    last_sync_timestamp: Optional[str]
    changes: SyncChanges
    checksum: Optional[str] = None  # SHA256 checksum dei dati
    sync_version: Optional[str] = "1.0"  # Versione del sync
    conflict_resolutions: Optional[List[dict]] = None  # Risoluzioni serial_conflict dal client

# --- DEPENDENCY PER LA SICUREZZA ---
def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        role: Optional[str] = payload.get("role")
        if username is None or role is None:
            raise credentials_exception
        return User(
            username=username, 
            role=role, 
            first_name=payload.get("first_name"), 
            last_name=payload.get("last_name")
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
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": SYNC_DATA_VERSION,
            "database": "disconnected",
            "error": str(e)
        }

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

        cols = records[0].keys()
        col_names = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join(["%s"] * len(cols))
        
        # Remove last_modified from update columns
        update_cols = [f'"{col}" = EXCLUDED."{col}"' 
                      for col in cols 
                      if col != 'uuid' and col != 'last_modified']
        
        # Add last_modified update
        update_clause = ", ".join(update_cols + ['"last_modified" = CURRENT_TIMESTAMP'])
        
        query = f"""
            INSERT INTO "{table_name}" ({col_names})
            VALUES ({placeholders})
            ON CONFLICT (uuid) 
            DO UPDATE SET {update_clause}
            WHERE "{table_name}".uuid = EXCLUDED.uuid
        """
        
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
                col_names_filtered = ", ".join(f'"{c}"' for c in cols_filtered)
                placeholders_filtered = ", ".join(["%s"] * len(cols_filtered))
                update_cols_filtered = [f'"{col}" = EXCLUDED."{col}"' 
                                      for col in cols_filtered 
                                      if col != 'uuid' and col != 'last_modified']
                update_clause_filtered = ", ".join(update_cols_filtered + ['"last_modified" = CURRENT_TIMESTAMP'])
                query_filtered = f"""
                    INSERT INTO "{table_name}" ({col_names_filtered})
                    VALUES ({placeholders_filtered})
                    ON CONFLICT (uuid) 
                    DO UPDATE SET {update_clause_filtered}
                    WHERE "{table_name}".uuid = EXCLUDED.uuid
                """
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
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM users WHERE username = %s", (form_data.username,))
    user = cursor.fetchone()
    conn.close()
    if not user or not verify_password(form_data.password, user['hashed_password']):
        raise HTTPException(status_code=401, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
    
    first_name = user.get('first_name') or ''
    last_name = user.get('last_name') or ''
    full_name = f"{first_name} {last_name}".strip()
    if not full_name: full_name = user['username']
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user['username'], "role": user['role'], "full_name": full_name}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}

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
        
        logging.info(f"📥 Dati ricevuti dal client:")
        for table_name, records in changes_raw.items():
            record_count = len(records) if isinstance(records, list) else 0
            if record_count > 0:
                logging.info(f"   - {table_name}: {record_count} record(s)")
        
        # === STEP 2: Valida checksum su JSON raw (PRIMA di Pydantic) ===
        if checksum_received:
            if not _validate_checksum(changes_raw, checksum_received):
                logging.error(f"✗ Checksum validation failed on raw data")
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
        
    except Exception as e:
        logging.error(f"Errore nella preparazione del payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")

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
                    tables_valid = {"customers", "mti_instruments", "profiles", "profile_tests",
                                    "functional_profiles", "destinations", "devices",
                                    "verifications", "functional_verifications", "signatures", "audit_log"}
                    for resolution in payload.conflict_resolutions:
                        res_table = resolution.get('table')
                        uuid_to_delete = resolution.get('uuid_to_delete')
                        if not res_table or not uuid_to_delete:
                            continue
                        if res_table not in tables_valid:
                            logging.warning(f"Tabella non valida nella risoluzione conflitto: {res_table}")
                            continue
                        try:
                            cursor.execute(
                                f"UPDATE {res_table} SET is_deleted = TRUE, last_modified = %s "
                                f"WHERE uuid = %s AND is_deleted = FALSE",
                                (new_sync_timestamp, uuid_to_delete)
                            )
                            if cursor.rowcount > 0:
                                logging.info(
                                    f"✓ Risoluzione conflitto applicata: soft-delete {uuid_to_delete} in {res_table}"
                                )
                            else:
                                logging.info(
                                    f"Risoluzione conflitto: {uuid_to_delete} in {res_table} già eliminato o non trovato"
                                )
                        except Exception as e:
                            logging.error(f"Errore applicazione risoluzione conflitto: {e}")

                changes_dict = payload.changes.model_dump()
                tables_order = ["customers", "mti_instruments", "profiles", "profile_tests", "functional_profiles",
                                "destinations", "devices", "verifications", "functional_verifications", "signatures", "audit_log"]

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
                        except Exception:
                            pass
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
                    
                    return {
                        "status": "conflict",
                        "conflict_count": len(detailed_conflicts),
                        "conflicts": detailed_conflicts
                    }

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
                    last_sync_dt = datetime.fromisoformat(payload.last_sync_timestamp)
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
                            cursor.execute(f"SELECT * FROM {table} WHERE is_deleted = FALSE")
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
                else:
                    last_sync_ts = payload.last_sync_timestamp
                    if last_sync_ts is None:
                        raise HTTPException(status_code=400, detail="last_sync_timestamp must not be None for incremental sync.")
                    last_sync_dt = datetime.fromisoformat(last_sync_ts)

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
                                f"SELECT * FROM {table} WHERE last_modified > %s AND last_modified <= %s",
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

                if "signatures" in changes_to_send:
                    for signature_record in changes_to_send["signatures"]:
                        if signature_record.get("signature_data"):
                            signature_record["signature_data"] = base64.b64encode(signature_record["signature_data"]).decode('utf-8')

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
    except Exception as e:
        logging.error(f"Errore grave durante la sincronizzazione: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

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
    except Exception as e:
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
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=f"Errore del server: {e}")
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
        query = f"UPDATE users SET {', '.join(fields_to_update)} WHERE username = %(username)s RETURNING username, role, first_name, last_name"
        cursor.execute(query, params)
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Utente non trovato.")
        updated_user = cursor.fetchone()
        conn.commit()
        return updated_user
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=f"Errore del server: {e}")
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
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=f"Errore del server: {e}")
    finally:
        if conn: conn.close()

@app.post("/signatures/{username}")
def upload_signature(username: str, file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    if current_user.role != 'admin' and current_user.username != username:
        raise HTTPException(status_code=403, detail="Non autorizzato a modificare la firma di un altro utente.")
    signature_data = file.file.read()
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
    except Exception as e:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore del server: {e}")
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
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=f"Errore del server: {e}")
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

    except Exception as e:
        logger.error(f"Errore nel recupero dati eliminati: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Errore del server: {e}")
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
            f'SELECT uuid FROM "{table_name}" WHERE id = %s AND is_deleted = TRUE',
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
            f'DELETE FROM "{table_name}" WHERE id = %s AND is_deleted = TRUE',
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
        raise HTTPException(status_code=500, detail=f"Errore del server: {e}")
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
            f'SELECT uuid FROM "{table_name}" WHERE is_deleted = TRUE'
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
            f'DELETE FROM "{table_name}" WHERE is_deleted = TRUE'
        )
        count = cursor.rowcount
        conn.commit()
        
        logger.warning(f"Admin {current_user.username}: hard delete ALL ({count}) da {table_name} - {len(uuids)} tombstone registrati")
        return {"status": "success", "deleted_count": count}
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Errore hard delete massivo: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Errore del server: {e}")
    finally:
        if conn: conn.close()

# --- ENDPOINT ROOT ---
@app.get("/")
def root():
    return {"message": "Safety Test Sync API è in esecuzione."}

# Blocco per l'esecuzione diretta
if __name__ == "__main__":
    import uvicorn
    import asyncio
    import platform
    
    # Fix per Windows: evita "Exception in callback _ProactorBasePipeTransport._call_connection_lost()"
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", 8000))
    
    # --- CONFIGURAZIONE SSL/HTTPS ---
    ssl_certfile = os.getenv("SSL_CERTFILE")
    ssl_keyfile = os.getenv("SSL_KEYFILE")
    
    uvicorn_kwargs = {
        "host": host,
        "port": port,
        "log_level": "info",
    }
    
    if ssl_certfile and ssl_keyfile:
        if os.path.isfile(ssl_certfile) and os.path.isfile(ssl_keyfile):
            uvicorn_kwargs["ssl_certfile"] = ssl_certfile
            uvicorn_kwargs["ssl_keyfile"] = ssl_keyfile
            logger.info(f"🔒 HTTPS abilitato con certificato: {ssl_certfile}")
        else:
            logger.error(f"✗ File SSL non trovati: cert={ssl_certfile}, key={ssl_keyfile}")
            logger.error("  Il server partirà in HTTP (NON SICURO)!")
    else:
        logger.warning("⚠ SSL non configurato - il server partirà in HTTP (NON SICURO per IP pubblico!)")
    
    protocol = "https" if "ssl_certfile" in uvicorn_kwargs else "http"
    logger.info(f"🚀 Avvio server su {protocol}://{host}:{port}")
    
    uvicorn.run(app, **uvicorn_kwargs)