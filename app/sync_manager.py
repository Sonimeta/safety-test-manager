# app/sync_manager.py (Versione Robusta con Backup, Transazioni, Retry e Heartbeat)
import requests
import json
import logging
from datetime import datetime, timezone, date
import database
import sqlite3
import base64
import os
import time
import hashlib
from typing import Optional, Tuple, Dict, List
from PySide6.QtWidgets import QMessageBox

from app import auth_manager, config
from app.backup_manager import create_backup, get_latest_backup, restore_from_backup

LOCK_FILE = config.LOCK_FILE_DIR
SYNC_ORDER = ["customers", "mti_instruments", "signatures", "profiles", "profile_tests", "functional_profiles", "destinations", "devices", "verifications", "functional_verifications", "audit_log"]

# Timeout e retry configuration
REQUEST_TIMEOUT = 90  # secondi
MAX_PAYLOAD_SIZE = 50 * 1024 * 1024  # 50MB limite payload

# Retry configuration con backoff esponenziale
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1  # secondi
MAX_RETRY_DELAY = 60  # secondi
RETRY_BACKOFF_FACTOR = 2

# Heartbeat configuration
HEARTBEAT_INTERVAL = 30  # secondi
HEARTBEAT_TIMEOUT = 5  # secondi
LOCK_STALE_HOURS = 6  # oltre questa soglia il lock è considerato stantio

# Sync checksum per verificare integrità
SYNC_DATA_VERSION = "1.0"

def is_sync_locked():
    """Controlla se il file di lock esiste."""
    return os.path.exists(LOCK_FILE)


def _safe_remove_lock_file(reason: str = ""):
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            if reason:
                logging.warning(f"⚠ Lock di sync rimosso automaticamente: {reason}")
            else:
                logging.warning("⚠ Lock di sync rimosso automaticamente")
    except Exception as e:
        logging.error(f"Impossibile rimuovere il lock file {LOCK_FILE}: {e}")


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _read_lock_info() -> dict:
    info = {}
    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            raw = (f.read() or "").strip()
        if not raw:
            return info
        # Nuovo formato: JSON
        if raw.startswith("{"):
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                info = parsed
        else:
            # Formato legacy: solo timestamp stringa
            info["started_at"] = raw
    except Exception:
        pass

    # Fallback robusto sul timestamp da mtime file
    if not info.get("started_at"):
        try:
            mtime = os.path.getmtime(LOCK_FILE)
            info["started_at"] = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
        except Exception:
            pass
    return info


def _parse_datetime(value: str | None):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class RetryManager:
    """Gestisce retry automatici con backoff esponenziale."""
    
    def __init__(self, max_retries=MAX_RETRIES, initial_delay=INITIAL_RETRY_DELAY, 
                 max_delay=MAX_RETRY_DELAY, backoff_factor=RETRY_BACKOFF_FACTOR):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.attempt = 0
        self.last_error = None
    
    def get_delay(self) -> float:
        """Calcola il delay per il prossimo retry con backoff esponenziale."""
        delay = min(self.initial_delay * (self.backoff_factor ** self.attempt), self.max_delay)
        # Aggiungi jitter per evitare thundering herd
        jitter = time.time() % 0.1  # Piccolo jitter casuale
        return delay + jitter
    
    def should_retry(self) -> bool:
        """Determina se dovrebbe fare retry."""
        return self.attempt < self.max_retries
    
    def wait_before_retry(self) -> float:
        """Attende prima di fare il retry e ritorna il delay usato."""
        if not self.should_retry():
            return 0
        
        delay = self.get_delay()
        logging.warning(f"⏳ Tentativo {self.attempt + 1}/{self.max_retries} dopo {delay:.1f}s (Errore: {self.last_error})")
        time.sleep(delay)
        self.attempt += 1
        return delay


def _check_server_health() -> bool:
    """Esegue un health check del server usando heartbeat."""
    try:
        headers = auth_manager.get_auth_headers()
        health_url = f"{config.SERVER_URL}/health"
        
        response = requests.get(
            health_url,
            timeout=HEARTBEAT_TIMEOUT,
            headers=headers
        )
        
        if response.status_code == 200:
            logging.info("✓ Server health check OK")
            return True
        else:
            logging.warning(f"⚠ Server health check fallito: HTTP {response.status_code}")
            return False
            
    except requests.Timeout:
        logging.warning("⚠ Server health check timeout")
        return False
    except requests.ConnectionError as e:
        logging.warning(f"⚠ Server health check errore di connessione: {e}")
        return False
    except Exception as e:
        logging.warning(f"⚠ Server health check errore imprevisto: {e}")
        return False


def _calculate_checksum(data: dict) -> str:
    """Calcola il checksum SHA256 dei dati di sincronizzazione per verificare integrità."""
    try:
        data_str = json.dumps(data, sort_keys=True, default=str)
        checksum = hashlib.sha256(data_str.encode()).hexdigest()
        # Debug: log primo hash di dati per diagnostic
        data_preview = json.dumps(data, sort_keys=True, default=str)[:100]
        logging.debug(f"Checksum calcolato su: {data_preview}...")
        return checksum
    except Exception as e:
        logging.error(f"Errore nel calcolo del checksum: {e}")
        return ""


def _validate_checksum(data: dict, received_checksum: str) -> bool:
    """Valida il checksum dei dati ricevuti."""
    if not received_checksum:
        logging.warning("⚠ Nessun checksum ricevuto dal server")
        return True  # Passa se il server non supporta checksum
    
    calculated = _calculate_checksum(data)
    if calculated == received_checksum:
        logging.info("✓ Checksum validato correttamente")
        return True
    else:
        logging.error(f"✗ Checksum mismatch: atteso {received_checksum}, calcolato {calculated}")
        # DEBUG: Log delle tabelle ricevute
        table_info = {k: len(v) if isinstance(v, list) else type(v).__name__ for k, v in data.items()}
        logging.debug(f"  Struttura dati ricevuta: {table_info}")
        return False


# ============================================================
# ADVANCED CONFLICT RESOLUTION SYSTEM
# ============================================================

class ConflictAnalyzer:
    """
    Analizza conflitti di sincronizzazione per comprendere natura e gravità.
    """
    
    CONFLICT_TYPES = {
        'modification_conflict': 'Stessi record modificati diversamente',
        'deletion_conflict': 'Record eliminato da una parte, modificato dall\'altra',
        'duplication_conflict': 'Record duplicato (es. stesso serial_number)',
        'schema_conflict': 'Struttura dati divergente',
        'foreign_key_conflict': 'Chiave esterna non trovata',
        'constraint_conflict': 'Vincolo di integrità violato',
    }
    
    SEVERITY_LEVELS = {
        'low': 1,
        'medium': 2,
        'high': 3,
        'critical': 4
    }
    
    def __init__(self):
        self.analysis_cache = {}
    
    def analyze_modification_conflict(self, local_rec: dict, server_rec: dict, table: str) -> dict:
        """Analizza un conflitto di modifica."""
        affected_fields = []
        non_conflicting_fields = []
        
        # Identifica campi divergenti
        for field in local_rec.keys():
            if field in server_rec:
                if local_rec[field] != server_rec[field]:
                    affected_fields.append(field)
                else:
                    non_conflicting_fields.append(field)
        
        # Calcola severità basato su numero di campi conflittuali
        severity = self._calculate_severity(
            len(affected_fields),
            len(non_conflicting_fields),
            table
        )
        
        # Determina se è auto-risolvibile
        local_modified = local_rec.get('last_modified', '')
        server_modified = server_rec.get('last_modified', '')
        auto_resolvable = len(affected_fields) <= 1 and severity in ['low', 'medium']
        
        return {
            'type': 'modification_conflict',
            'severity': severity,
            'affected_fields': affected_fields,
            'non_conflicting_fields': non_conflicting_fields,
            'field_count': len(affected_fields),
            'auto_resolvable': auto_resolvable,
            'local_modified': local_modified,
            'server_modified': server_modified,
            'more_recent': 'server' if server_modified > local_modified else 'client'
        }
    
    def analyze_duplication_conflict(self, record: dict, existing: dict, duplicate_field: str) -> dict:
        """Analizza un conflitto di duplicazione."""
        return {
            'type': 'duplication_conflict',
            'severity': 'high',
            'auto_resolvable': False,
            'duplicate_field': duplicate_field,
            'duplicate_value': record.get(duplicate_field),
            'message': f"Record con {duplicate_field}='{record.get(duplicate_field)}' esiste già",
            'suggestions': [
                'Rinominare il campo nel client',
                'Eliminare il record duplicato',
                'Unire i record'
            ]
        }
    
    def _calculate_severity(self, conflict_count: int, safe_count: int, table: str) -> str:
        """Calcola gravità del conflitto."""
        if conflict_count == 0:
            return 'low'
        
        ratio = conflict_count / max(safe_count, 1)
        
        # Campi critici hanno maggiore impatto
        critical_fields = self._get_critical_fields(table)
        conflicting_critical = sum(1 for f in critical_fields if f in conflict_count)
        
        if conflicting_critical > 0:
            return 'high'
        elif ratio > 0.5:
            return 'high'
        elif ratio > 0.25:
            return 'medium'
        else:
            return 'low'
    
    def _get_critical_fields(self, table: str) -> List[str]:
        """Ritorna i campi critici per una tabella."""
        critical_by_table = {
            'devices': ['serial_number', 'status', 'location'],
            'customers': ['name', 'email'],
            'verifications': ['test_date', 'status'],
        }
        return critical_by_table.get(table, [])


class ConflictResolver:
    """
    Risolve conflitti di sincronizzazione usando strategie intelligenti.
    """
    
    RESOLUTION_STRATEGIES = {
        'server_wins': 'Il server ha la priorità',
        'client_wins': 'Il client ha la priorità',
        'manual': 'Richiede intervento manuale',
        'merge': 'Tenta merge intelligente',
        'timestamp': 'Vince quello più recente',
        'user_preference': 'Usa preferenze utente'
    }
    
    def __init__(self, default_strategy: str = 'timestamp'):
        self.strategy = default_strategy
        self.resolution_history = []
        self.user_preferences = {}
    
    def resolve(self, conflict: dict, analysis: dict = None, user_choice: str = None) -> dict:
        """
        Risolve un conflitto secondo la strategia specificata.
        
        Args:
            conflict: Dati del conflitto
            analysis: Analisi del conflitto (da ConflictAnalyzer)
            user_choice: Scelta dell'utente (se manuale)
        
        Returns:
            dict: Risultato della risoluzione
        """
        uuid = conflict.get('uuid')
        table = conflict.get('table')
        conflict_type = conflict.get('type', 'modification_conflict')
        
        # Scegli strategia
        if user_choice:
            strategy_used = 'user_choice'
            resolution = user_choice
            confidence = 1.0
        elif conflict_type == 'modification_conflict' and analysis and analysis.get('auto_resolvable'):
            strategy_used = self.strategy
            resolution, confidence = self._resolve_modification(conflict, analysis)
        elif conflict_type == 'duplication_conflict':
            strategy_used = 'manual'
            resolution = None
            confidence = 0.0
        else:
            strategy_used = 'manual'
            resolution = None
            confidence = 0.0
        
        result = {
            'uuid': uuid,
            'table': table,
            'type': conflict_type,
            'strategy_used': strategy_used,
            'resolution': resolution,
            'confidence': confidence,
            'auto_resolved': confidence >= 0.8,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        self.resolution_history.append(result)
        self._save_preference(table, strategy_used)
        
        return result
    
    def _resolve_modification(self, conflict: dict, analysis: dict) -> Tuple[dict, float]:
        """Risolve conflitto di modifica."""
        local_data = conflict.get('local_version', {})
        server_data = conflict.get('server_version', {})
        
        if self.strategy == 'timestamp':
            more_recent = analysis.get('more_recent', 'server')
            if more_recent == 'server':
                return {'winner': 'server', 'data': server_data}, 0.9
            else:
                return {'winner': 'client', 'data': local_data}, 0.9
        
        elif self.strategy == 'server_wins':
            return {'winner': 'server', 'data': server_data}, 0.85
        
        elif self.strategy == 'client_wins':
            return {'winner': 'client', 'data': local_data}, 0.85
        
        elif self.strategy == 'merge':
            merged = self._merge_records(local_data, server_data, analysis)
            return {'winner': 'merged', 'data': merged}, 0.75
        
        return None, 0.0
    
    def _merge_records(self, local: dict, server: dict, analysis: dict) -> dict:
        """Tenta merge intelligente dei record."""
        result = server.copy()
        non_conflicting = analysis.get('non_conflicting_fields', [])
        
        # Usa i campi non-conflittuali dal client se più recenti
        local_modified = local.get('last_modified', '')
        server_modified = server.get('last_modified', '')
        
        if local_modified > server_modified:
            for field in non_conflicting:
                if field in local:
                    result[field] = local[field]
        
        return result
    
    def _save_preference(self, table: str, strategy: str):
        """Salva preferenza utente per apprendimento futuro."""
        key = f"{table}:{strategy}"
        self.user_preferences[key] = self.user_preferences.get(key, 0) + 1


def is_sync_locked():
    """
    Controlla se il lock è attivo.
    Se trova un lock stantio (processo non più attivo o lock troppo vecchio),
    lo rimuove automaticamente.
    """
    if not os.path.exists(LOCK_FILE):
        return False

    info = _read_lock_info()
    pid_raw = info.get("pid")
    started_at = _parse_datetime(info.get("started_at"))

    # Se c'è PID e il processo non esiste più, lock stantio
    try:
        pid = int(pid_raw) if pid_raw is not None else None
    except (TypeError, ValueError):
        pid = None

    if pid is not None and not _is_process_running(pid):
        _safe_remove_lock_file(reason=f"processo PID {pid} non attivo")
        return False

    # Se il lock è troppo vecchio, consideralo stantio
    if started_at is not None:
        age_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
        if age_seconds > (LOCK_STALE_HOURS * 3600):
            _safe_remove_lock_file(reason=f"lock più vecchio di {LOCK_STALE_HOURS} ore")
            return False

    return True

def lock_sync():
    """Crea il file di lock per indicare che la sincronizzazione è in corso."""
    try:
        payload = {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload))
        logging.info("Sincronizzazione bloccata (lock acquisito).")
    except IOError as e:
        logging.error(f"Impossibile creare il file di lock: {e}")
        raise


def _make_sync_request_with_retry(payload: dict, headers: dict, sync_url: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    Esegue la richiesta di sincronizzazione con retry automatico e backoff esponenziale.
    
    Args:
        payload: Dati da inviare al server
        headers: Headers HTTP con autenticazione
        sync_url: URL del server per la sincronizzazione
    
    Returns:
        tuple: (response_data, error_message) - uno dei due sarà None
    """
    retry_manager = RetryManager()
    last_error = None
    
    while True:
        try:
            # Health check prima di ogni tentativo
            if retry_manager.attempt > 0:  # Salta al primo tentativo
                if not _check_server_health():
                    raise ConnectionError("Server non disponibile al health check")
            
            logging.info(f"🌐 Tentativo sincronizzazione {retry_manager.attempt + 1}/{retry_manager.max_retries + 1}")
            
            response = requests.post(
                sync_url,
                json=payload,
                timeout=REQUEST_TIMEOUT,
                headers=headers
            )
            
            response.raise_for_status()
            server_response = response.json()
            
            logging.info(f"✓ Risposta ricevuta dal server (status: {server_response.get('status')})")
            return server_response, None
            
        except requests.Timeout as e:
            last_error = f"Timeout ({REQUEST_TIMEOUT}s)"
            retry_manager.last_error = last_error
            logging.warning(f"⚠ {last_error} - tentativo {retry_manager.attempt + 1}")
            
            if not retry_manager.should_retry():
                return None, f"Timeout: il server non ha risposto entro {REQUEST_TIMEOUT} secondi dopo {retry_manager.max_retries + 1} tentativi."
            
            retry_manager.wait_before_retry()
            
        except requests.ConnectionError as e:
            last_error = f"Errore di connessione: {str(e)[:50]}"
            retry_manager.last_error = last_error
            logging.warning(f"⚠ {last_error} - tentativo {retry_manager.attempt + 1}")
            
            if not retry_manager.should_retry():
                return None, "Impossibile connettersi al server dopo più tentativi. Verificare la connessione internet."
            
            retry_manager.wait_before_retry()
            
        except requests.HTTPError as e:
            if e.response and e.response.status_code == 401:
                logging.error("✗ Errore di autenticazione (401)")
                return None, "auth_error"
            elif e.response and e.response.status_code == 403:
                logging.error("✗ Accesso negato (403)")
                return None, "Accesso negato. Non hai i permessi per sincronizzare."
            elif e.response and e.response.status_code >= 500:
                # Errori server (5xx) - retry
                last_error = f"Errore server HTTP {e.response.status_code}"
                retry_manager.last_error = last_error
                logging.warning(f"⚠ {last_error} - tentativo {retry_manager.attempt + 1}")
                
                if not retry_manager.should_retry():
                    return None, f"Errore del server (HTTP {e.response.status_code}) persistente dopo {retry_manager.max_retries + 1} tentativi."
                
                retry_manager.wait_before_retry()
            else:
                # Errori client (4xx) - non retry
                error_msg = f"Errore HTTP {e.response.status_code if e.response else 'N/A'}"
                logging.error(f"✗ {error_msg}")
                return None, f"{error_msg}. Non ritentando (errore client)."
                
        except json.JSONDecodeError as e:
            last_error = "Risposta JSON invalida"
            retry_manager.last_error = last_error
            logging.warning(f"⚠ {last_error} - tentativo {retry_manager.attempt + 1}")
            
            if not retry_manager.should_retry():
                return None, "Il server ha inviato una risposta non valida (JSON) dopo più tentativi."
            
            retry_manager.wait_before_retry()
            
        except Exception as e:
            last_error = f"Errore imprevisto: {str(e)[:50]}"
            retry_manager.last_error = last_error
            logging.warning(f"⚠ {last_error} - tentativo {retry_manager.attempt + 1}")
            
            if not retry_manager.should_retry():
                return None, f"Errore imprevisto dopo {retry_manager.max_retries + 1} tentativi: {str(e)[:100]}"
            
            retry_manager.wait_before_retry()


def unlock_sync():
    """Rimuove il file di lock."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logging.info("Sincronizzazione sbloccata (lock rilasciato).")
    except IOError as e:
        logging.error(f"Impossibile rimuovere il file di lock: {e}")

def _jsonify_value(v):
    # datetime/date → ISO 8601
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    # bytes/bytearray/memoryview → base64 string
    if isinstance(v, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(v)).decode("ascii")
    return v

def _jsonify_record(rec: dict) -> dict:
    return {k: _jsonify_value(v) for k, v in rec.items()}

def _get_unsynced_local_changes():
    """Recupera tutte le modifiche locali non sincronizzate in modo più compatto."""
    
    # Definiamo le query e le trasformazioni per ogni tabella in una struttura dati
    TABLE_SYNC_CONFIG = {
        "customers": ("SELECT * FROM {table} WHERE is_synced = 0", []),
        "mti_instruments": ("SELECT * FROM {table} WHERE is_synced = 0", []),
        "signatures": ("SELECT * FROM {table} WHERE is_synced = 0", []),
        "profiles": ("SELECT * FROM {table} WHERE is_synced = 0", []),
        "functional_profiles": ("SELECT * FROM {table} WHERE is_synced = 0", []),
        "destinations": (
            "SELECT d.*, c.uuid as customer_uuid FROM destinations d JOIN customers c ON d.customer_id = c.id WHERE d.is_synced = 0",
            ["customer_id"] # Colonne da rimuovere prima dell'invio
        ),
        "devices": (
            "SELECT d.*, dest.uuid as destination_uuid FROM devices d JOIN destinations dest ON d.destination_id = dest.id WHERE d.is_synced = 0",
            ["destination_id"]
        ),
        "verifications": (
            "SELECT v.*, d.uuid as device_uuid FROM verifications v JOIN devices d ON v.device_id = d.id WHERE v.is_synced = 0",
            ["device_id"]
        ),
        "functional_verifications": (
            "SELECT fv.*, d.uuid as device_uuid FROM functional_verifications fv JOIN devices d ON fv.device_id = d.id WHERE fv.is_synced = 0",
            ["device_id"]
        ),
        "profile_tests": (
            "SELECT pt.*, p.uuid as profile_uuid FROM profile_tests pt JOIN profiles p ON pt.profile_id = p.id WHERE pt.is_synced = 0",
            ["profile_id"]
        ),
        "audit_log": ("SELECT * FROM {table} WHERE is_synced = 0", [])
    }

    changes = {}
    with database.DatabaseConnection() as conn:
        conn.row_factory = sqlite3.Row
        
        for table, (query, cols_to_pop) in TABLE_SYNC_CONFIG.items():
            # Il nome della tabella viene inserito nella query se necessario
            final_query = query.format(table=table)
            
            rows = conn.execute(final_query).fetchall()
            records_list = []
            for row in rows:
                record_dict = dict(row)
                record_dict.pop('id', None) # Rimuoviamo sempre l'ID locale

                # Rimuoviamo le chiavi esterne (FK) numeriche
                for col in cols_to_pop:
                    record_dict.pop(col, None)
                
                records_list.append(record_dict)
            
            changes[table] = records_list
            
    return changes

def _validate_sync_data(changes):
    """
    Valida i dati ricevuti dal server prima di applicarli.
    
    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        if not isinstance(changes, dict):
            return False, "I dati di sincronizzazione non sono nel formato corretto"
        
        # Verifica che tutte le tabelle siano nell'ordine corretto
        for table in changes.keys():
            if table not in SYNC_ORDER:
                logging.warning(f"⚠ Tabella sconosciuta nei dati di sync: {table}")
        
        # Verifica che ogni record abbia un UUID
        for table, records in changes.items():
            if not isinstance(records, list):
                return False, f"I record della tabella '{table}' non sono una lista"
                
            for idx, record in enumerate(records):
                if not isinstance(record, dict):
                    return False, f"Record {idx} in '{table}' non è un dizionario"
                    
                if 'uuid' not in record and not record.get('is_deleted'):
                    logging.warning(f"⚠ Record senza UUID in '{table}': {record}")
        
        logging.info("✓ Validazione dati di sincronizzazione completata con successo")
        return True, None
        
    except Exception as e:
        return False, f"Errore durante la validazione: {str(e)}"

def _get_valid_columns_sqlite(cursor, table_name: str) -> set:
    """Recupera le colonne valide per una tabella SQLite locale."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    rows = cursor.fetchall()
    return {row[1] for row in rows}  # row[1] è il nome della colonna

def _apply_server_changes(conn, changes):
    """
    Applica le modifiche dal server al database locale con transazione atomica.
    Gli errori su singoli record vengono catturati e salvati come conflitti
    invece di interrompere l'intera sincronizzazione.
    
    Returns:
        tuple: (applied_counts, conflicts_list)
    """
    applied_counts = {table: 0 for table in SYNC_ORDER}
    conflicts_list = []  # Lista dei conflitti generati durante l'applicazione
    uuid_to_local_id = {"customers": {}, "devices": {}, "profiles": {}, "destinations": {}}
    cursor = conn.cursor()
    
    # Log inizio applicazione cambiamenti
    total_records = sum(len(records) for records in changes.values())
    logging.info(f"📥 Inizio applicazione di {total_records} record dal server...")

    for table in SYNC_ORDER:
        records_from_server = changes.get(table, [])
        if not records_from_server:
            continue

        try:
            if table == 'signatures':
                records_to_upsert = []
                for record in records_from_server:
                    if record.get('signature_data'):
                        try:
                            record['signature_data'] = base64.b64decode(record['signature_data'])
                        except (TypeError, base64.binascii.Error):
                            record['signature_data'] = None

                    record['is_synced'] = 1
                    clean = {
                        'username': record.get('username'),
                        'signature_data': record.get('signature_data'),
                        'last_modified': record.get('last_modified'),
                        'is_synced': record.get('is_synced', 1),
                    }
                    records_to_upsert.append(clean)

                if records_to_upsert:
                    cols = ['username', 'signature_data', 'last_modified', 'is_synced']
                    placeholders = ", ".join(["?"] * len(cols))
                    query = (
                        f"INSERT INTO signatures ({', '.join(cols)}) VALUES ({placeholders}) "
                        "ON CONFLICT(username) DO UPDATE SET "
                        "signature_data=excluded.signature_data, "
                        "last_modified=excluded.last_modified, "
                        "is_synced=excluded.is_synced;"
                    )
                    params = [tuple(r[c] for c in cols) for r in records_to_upsert]
                    cursor.executemany(query, params)
                    applied_counts[table] += cursor.rowcount
                continue  # importante: salta il flusso generico

            records_to_insert = []
            records_to_update = []
            skipped_fk_records = []  # Record saltati per FK mancante

            for record in records_from_server:
                if 'customer_id' in record and table == 'devices':
                    record.pop('customer_id')

                def resolve_fk(parent_table_name, parent_uuid_key):
                    parent_uuid = record.pop(parent_uuid_key, None)
                    if not parent_uuid:
                        return -1  # UUID padre assente nel payload → record orfano dal server
                    local_id = uuid_to_local_id.get(parent_table_name, {}).get(parent_uuid)
                    if local_id: return local_id
                    parent_row = cursor.execute(f"SELECT id FROM {parent_table_name} WHERE uuid = ?", (parent_uuid,)).fetchone()
                    if parent_row:
                        return parent_row[0]
                    return None  # FK non trovata localmente

                fk_missing = False
                fk_orphan = False  # True se il server ha inviato un record senza UUID padre

                if table == 'destinations':
                    local_customer_id = resolve_fk("customers", "customer_uuid")
                    if local_customer_id == -1:
                        fk_orphan = True
                    elif local_customer_id is None:
                        fk_missing = True
                    else:
                        record['customer_id'] = local_customer_id
                
                if table == 'devices' and not fk_missing and not fk_orphan:
                    local_destination_id = resolve_fk("destinations", "destination_uuid")
                    if local_destination_id == -1:
                        fk_orphan = True
                    elif local_destination_id is None:
                        fk_missing = True
                    else:
                        record['destination_id'] = local_destination_id
                
                if table == 'verifications' and not fk_missing and not fk_orphan:
                    local_device_id = resolve_fk("devices", "device_uuid")
                    if local_device_id == -1:
                        fk_orphan = True
                    elif local_device_id is None:
                        fk_missing = True
                    else:
                        record['device_id'] = local_device_id

                if table == 'functional_verifications' and not fk_missing and not fk_orphan:
                    local_device_id = resolve_fk("devices", "device_uuid")
                    if local_device_id == -1:
                        fk_orphan = True
                    elif local_device_id is None:
                        fk_missing = True
                    else:
                        record['device_id'] = local_device_id

                if table == 'profile_tests' and not fk_missing and not fk_orphan:
                    local_profile_id = resolve_fk("profiles", "profile_uuid")
                    if local_profile_id == -1:
                        fk_orphan = True
                    elif local_profile_id is None:
                        fk_missing = True
                    else:
                        record['profile_id'] = local_profile_id

                # Record orfano dal server (UUID padre assente nel payload) → salta silenziosamente
                if fk_orphan:
                    record_uuid = record.get('uuid', 'unknown')
                    logging.debug(f"⏭ Record orfano ignorato: '{table}' (uuid={record_uuid}) - UUID padre assente nel payload del server")
                    continue

                if fk_missing:
                    # FK padre non trovata localmente → salva come conflitto risolvibile
                    record_uuid = record.get('uuid', 'unknown')
                    conflict = {
                        'table': table,
                        'record_uuid': record_uuid,
                        'conflict_type': 'foreign_key_missing',
                        'severity': 'medium',
                        'server_data': record.copy(),
                        'error_message': f"Record in '{table}' ha un riferimento a un record padre non trovato localmente."
                    }
                    conflicts_list.append(conflict)
                    logging.warning(f"⚠ Conflitto FK: record in '{table}' (uuid={record_uuid}) - padre non trovato")
                    continue
                
                record_uuid = record.get('uuid')
                if not record_uuid: continue

                existing = cursor.execute(f"SELECT id FROM {table} WHERE uuid = ?", (record_uuid,)).fetchone()
                
                if existing:
                    records_to_update.append(record)
                elif not record.get('is_deleted', False):
                    record.pop('id', None)
                    # Per la tabella devices, controlla se esiste già un record con lo stesso serial_number
                    if table == 'devices':
                        sn = record.get('serial_number')
                        if sn and str(sn).strip():
                            existing_by_sn = cursor.execute(
                                "SELECT id, uuid FROM devices WHERE serial_number = ? AND is_deleted = 0 AND uuid != ?",
                                (sn, record_uuid)
                            ).fetchone()
                            if existing_by_sn:
                                # Crea un conflitto di duplicazione per l'utente
                                local_row = cursor.execute("SELECT * FROM devices WHERE id = ?", (existing_by_sn[0],)).fetchone()
                                local_data = dict(local_row) if local_row else {}
                                
                                conflict = {
                                    'table': table,
                                    'record_uuid': record_uuid,
                                    'conflict_type': 'duplicate_serial_number',
                                    'severity': 'high',
                                    'local_data': local_data,
                                    'server_data': record.copy(),
                                    'error_message': (
                                        f"Il dispositivo con numero di serie '{sn}' esiste già localmente "
                                        f"(UUID locale: {existing_by_sn[1]}) ma il server ha inviato "
                                        f"un dispositivo diverso (UUID server: {record_uuid}) con lo stesso numero di serie."
                                    )
                                }
                                conflicts_list.append(conflict)
                                logging.warning(f"⚠ Conflitto serial_number: '{sn}' in devices (locale={existing_by_sn[1]}, server={record_uuid})")
                                continue
                    records_to_insert.append(record)
            
            # === INSERIMENTO ===
            if records_to_insert:
                valid_cols = _get_valid_columns_sqlite(cursor, table)
                all_cols = list(records_to_insert[0].keys())
                cols = [c for c in all_cols if c in valid_cols]
                
                if not cols:
                    logging.warning(f"Nessuna colonna valida per inserimento in {table}.")
                    continue
                
                for record in records_to_insert:
                    invalid_cols = set(record.keys()) - valid_cols
                    for col in list(invalid_cols):
                        record.pop(col, None)
                
                query = f"INSERT INTO {table} ({', '.join(cols)}, is_synced) VALUES ({', '.join(['?']*len(cols))}, 1)"
                
                # Inserisci uno alla volta per catturare conflitti singoli
                for record in records_to_insert:
                    try:
                        single_params = tuple(record.get(c) for c in cols)
                        cursor.execute(query, single_params)
                        applied_counts[table] += 1
                    except sqlite3.IntegrityError as e:
                        # Conflitto di integrità → salva come conflitto
                        rec_uuid = record.get('uuid', 'unknown')
                        # Prova a recuperare il record locale in conflitto
                        local_data = {}
                        try:
                            local_row = cursor.execute(f"SELECT * FROM {table} WHERE uuid = ?", (rec_uuid,)).fetchone()
                            if local_row:
                                local_data = dict(local_row)
                        except Exception:
                            pass
                        
                        conflict = {
                            'table': table,
                            'record_uuid': rec_uuid,
                            'conflict_type': 'integrity_constraint',
                            'severity': 'high',
                            'local_data': local_data,
                            'server_data': record.copy(),
                            'error_message': f"Vincolo di integrità violato durante inserimento in '{table}': {str(e)}"
                        }
                        conflicts_list.append(conflict)
                        logging.warning(f"⚠ Conflitto integrità in {table} (uuid={rec_uuid}): {e}")
                    except sqlite3.OperationalError as e:
                        rec_uuid = record.get('uuid', 'unknown')
                        conflict = {
                            'table': table,
                            'record_uuid': rec_uuid,
                            'conflict_type': 'operational_error',
                            'severity': 'medium',
                            'server_data': record.copy(),
                            'error_message': f"Errore operativo durante inserimento in '{table}': {str(e)}"
                        }
                        conflicts_list.append(conflict)
                        logging.warning(f"⚠ Errore operativo in {table} (uuid={rec_uuid}): {e}")
                
                if table in uuid_to_local_id:
                    for record in records_to_insert:
                        new_id_row = cursor.execute(f"SELECT id FROM {table} WHERE uuid = ?", (record.get('uuid', ''),)).fetchone()
                        if new_id_row:
                            uuid_to_local_id[table][record['uuid']] = new_id_row[0]

            # === AGGIORNAMENTO ===
            if records_to_update:
                records_update_by_uuid = []
                records_update_by_serial = []
                for record in records_to_update:
                    if record.pop('_update_by_serial', None):
                        records_update_by_serial.append(record)
                    else:
                        records_update_by_uuid.append(record)

                valid_cols = _get_valid_columns_sqlite(cursor, table)

                # --- Aggiornamento per serial_number ---
                if records_update_by_serial:
                    all_cols_sn = [k for k in records_update_by_serial[0].keys() if k not in ['id', 'serial_number']]
                    cols_sn = [c for c in all_cols_sn if c in valid_cols]
                    if 'uuid' not in cols_sn:
                        cols_sn.insert(0, 'uuid')

                    for record in records_update_by_serial:
                        invalid_cols = set(record.keys()) - valid_cols - {'id', 'serial_number', '_update_by_serial'}
                        for col in list(invalid_cols):
                            record.pop(col, None)

                    set_clause_sn = ", ".join([f"{col} = ?" for col in cols_sn])
                    query_sn = f"UPDATE {table} SET {set_clause_sn}, is_synced = 1 WHERE serial_number = ? AND is_deleted = 0"
                    
                    for record in records_update_by_serial:
                        try:
                            params_sn = tuple(record.get(c) for c in cols_sn) + (record['serial_number'],)
                            cursor.execute(query_sn, params_sn)
                            applied_counts[table] += cursor.rowcount
                        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
                            rec_uuid = record.get('uuid', 'unknown')
                            conflict = {
                                'table': table,
                                'record_uuid': rec_uuid,
                                'conflict_type': 'update_serial_error',
                                'severity': 'high',
                                'server_data': record.copy(),
                                'error_message': f"Errore aggiornamento per serial_number in '{table}': {str(e)}"
                            }
                            conflicts_list.append(conflict)
                            logging.warning(f"⚠ Conflitto update serial in {table} (uuid={rec_uuid}): {e}")

                    if table in uuid_to_local_id:
                        for record in records_update_by_serial:
                            new_id_row = cursor.execute(f"SELECT id FROM {table} WHERE uuid = ?", (record.get('uuid', ''),)).fetchone()
                            if new_id_row:
                                uuid_to_local_id[table][record['uuid']] = new_id_row[0]

                # --- Aggiornamento standard per uuid ---
                if records_update_by_uuid:
                    all_cols = [k for k in records_update_by_uuid[0].keys() if k not in ['uuid', 'id']]
                    cols = [c for c in all_cols if c in valid_cols]
                    
                    if not cols:
                        logging.warning(f"Nessuna colonna valida per aggiornamento in {table}.")
                        continue
                    
                    for record in records_update_by_uuid:
                        invalid_cols = set(record.keys()) - valid_cols - {'uuid', 'id'}
                        for col in list(invalid_cols):
                            record.pop(col, None)
                    
                    set_clause = ", ".join([f"{col} = ?" for col in cols])
                    query = f"UPDATE {table} SET {set_clause}, is_synced = 1 WHERE uuid = ?"
                    
                    for record in records_update_by_uuid:
                        try:
                            params = tuple(record.get(c) for c in cols) + (record['uuid'],)
                            cursor.execute(query, params)
                            applied_counts[table] += cursor.rowcount
                        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
                            # Conflitto durante update → salva
                            rec_uuid = record.get('uuid', 'unknown')
                            local_data = {}
                            try:
                                local_row = cursor.execute(f"SELECT * FROM {table} WHERE uuid = ?", (rec_uuid,)).fetchone()
                                if local_row:
                                    local_data = dict(local_row)
                            except Exception:
                                pass
                            
                            conflict = {
                                'table': table,
                                'record_uuid': rec_uuid,
                                'conflict_type': 'update_conflict',
                                'severity': 'medium',
                                'local_data': local_data,
                                'server_data': record.copy(),
                                'error_message': f"Errore durante aggiornamento in '{table}': {str(e)}"
                            }
                            conflicts_list.append(conflict)
                            logging.warning(f"⚠ Conflitto update in {table} (uuid={rec_uuid}): {e}")
        
        except Exception as e:
            # Errore imprevisto a livello di tabella → salva come conflitto generico
            conflict = {
                'table': table,
                'record_uuid': None,
                'conflict_type': 'table_error',
                'severity': 'high',
                'error_message': f"Errore imprevisto durante la sincronizzazione della tabella '{table}': {str(e)}"
            }
            conflicts_list.append(conflict)
            logging.error(f"⚠ Errore imprevisto su tabella {table}: {e}", exc_info=True)
            # Continua con la prossima tabella invece di interrompere tutto

    if conflicts_list:
        logging.warning(f"📌 {len(conflicts_list)} conflitti rilevati durante la sincronizzazione")

    logging.info(f"Modifiche batch dal server applicate: {json.dumps(applied_counts)}")
    return applied_counts, conflicts_list

def _mark_pushed_changes_as_synced(conn):
    cursor = conn.cursor()
    for table in SYNC_ORDER:
        cursor.execute(f"UPDATE {table} SET is_synced = 1 WHERE is_synced = 0")
    logging.info("Tutti i record locali inviati sono stati marcati come sincronizzati.")

def _apply_hard_deletes(conn, hard_deletes: dict) -> dict:
    """
    Applica le eliminazioni definitive ricevute dal server.
    Quando un admin elimina definitivamente un record dal DB online,
    il server invia i tombstone (UUID) che devono essere eliminati anche localmente.
    
    Args:
        conn: Connessione SQLite
        hard_deletes: Dict {table_name: [uuid1, uuid2, ...]} dal server
    
    Returns:
        Dict con conteggi di record eliminati per tabella
    """
    if not hard_deletes:
        return {}
    
    cursor = conn.cursor()
    deleted_counts = {}
    
    allowed_tables = {
        'customers', 'destinations', 'devices', 'verifications',
        'functional_verifications', 'profiles', 'profile_tests',
        'functional_profiles', 'mti_instruments', 'audit_log'
    }
    
    for table_name, uuids in hard_deletes.items():
        if table_name not in allowed_tables:
            logging.warning(f"\u26a0 Tabella '{table_name}' non consentita per hard delete, ignorata")
            continue
        
        if not uuids:
            continue
        
        count = 0
        for uuid_val in uuids:
            try:
                cursor.execute(
                    f"DELETE FROM {table_name} WHERE uuid = ?",
                    (uuid_val,)
                )
                if cursor.rowcount > 0:
                    count += cursor.rowcount
                    logging.info(f"\ud83d\uddd1\ufe0f Hard delete propagato: {table_name} UUID={uuid_val}")
            except Exception as e:
                logging.error(f"Errore hard delete locale per {table_name} UUID={uuid_val}: {e}")
                continue
        
        if count > 0:
            deleted_counts[table_name] = count
            logging.warning(f"\ud83d\uddd1\ufe0f Eliminati definitivamente {count} record da {table_name} (propagazione dal server)")
    
    if deleted_counts:
        total = sum(deleted_counts.values())
        logging.warning(f"\ud83d\uddd1\ufe0f Totale record eliminati definitivamente per propagazione: {total}")
    
    return deleted_counts

def _handle_uuid_maps(conn, uuid_map: dict):
    if not uuid_map: return
    logging.warning(f"Ricevuta mappa di unione UUID dal server: {uuid_map}")
    cursor = conn.cursor()
    for client_uuid, server_uuid in uuid_map.items():
        try:
            cursor.execute("SELECT id FROM customers WHERE uuid = ?", (server_uuid,))
            correct_customer_row = cursor.fetchone()
            cursor.execute("SELECT id FROM customers WHERE uuid = ?", (client_uuid,))
            duplicate_customer_row = cursor.fetchone()
            if not correct_customer_row or not duplicate_customer_row: continue
            correct_customer_id = correct_customer_row[0]
            duplicate_customer_id = duplicate_customer_row[0]
            cursor.execute("UPDATE destinations SET customer_id = ? WHERE customer_id = ?", (correct_customer_id, duplicate_customer_id))
            logging.info(f"Riassegnate {cursor.rowcount} destinazioni dal cliente duplicato a quello corretto.")
            cursor.execute("DELETE FROM customers WHERE id = ?", (duplicate_customer_id,))
            logging.warning(f"Cliente duplicato con UUID {client_uuid} eliminato.")
        except Exception as e:
            logging.error(f"Errore durante la gestione della mappa UUID {client_uuid} -> {server_uuid}", exc_info=True)
            continue


def _detect_and_log_conflicts(conn, local_changes: dict, server_changes: dict) -> Tuple[List[dict], List[dict]]:
    """
    Rileva e analizza conflitti tra modifiche locali e server-side.
    Utilizza ConflictAnalyzer e ConflictResolver per risoluzioni intelligenti.
    
    Returns:
        tuple: (conflicts_auto_resolved, conflicts_manual_review)
    """
    analyzer = ConflictAnalyzer()
    resolver = ConflictResolver(default_strategy='timestamp')
    
    conflicts_resolved = []
    conflicts_manual = []
    cursor = conn.cursor()
    
    try:
        for table in SYNC_ORDER:
            local_records = local_changes.get(table, [])
            server_records = server_changes.get(table, [])
            
            if not local_records or not server_records:
                continue
            
            # Crea mapping di UUID per server records
            server_uuids = {r.get('uuid'): r for r in server_records if r.get('uuid')}
            
            # Controlla ogni record locale
            for local_rec in local_records:
                uuid = local_rec.get('uuid')
                if not uuid or uuid not in server_uuids:
                    continue
                
                server_rec = server_uuids[uuid]
                
                # Confronta timestamp di modifica
                local_modified = local_rec.get('last_modified')
                server_modified = server_rec.get('last_modified')
                
                # Rileva conflitto se timestamps differiscono
                if local_modified and server_modified and local_modified != server_modified:
                    # Analizza il conflitto
                    analysis = analyzer.analyze_modification_conflict(local_rec, server_rec, table)
                    
                    logging.warning(f"⚠ Conflitto rilevato in {table} (UUID: {uuid}): {analysis['severity']}")
                    logging.debug(f"   Campi in conflitto: {analysis['affected_fields']}")
                    logging.debug(f"   Campi non conflittuali: {analysis['non_conflicting_fields']}")
                    
                    # Prepara dati conflitto
                    conflict_data = {
                        'uuid': uuid,
                        'table': table,
                        'type': 'modification_conflict',
                        'severity': analysis['severity'],
                        'local_version': local_rec,
                        'client_version': local_rec,  # ✅ Alias per compatibilità con UI
                        'server_version': server_rec,
                        'analysis': analysis
                    }
                    
                    # Risolvi il conflitto
                    resolution = resolver.resolve(conflict_data, analysis)
                    
                    if resolution['auto_resolved']:
                        logging.info(f"✓ Conflitto auto-risolto in {table} (UUID: {uuid}) usando {resolution['strategy_used']}")
                        conflicts_resolved.append(resolution)
                    else:
                        logging.warning(f"⚠ Conflitto richiede revisione manuale in {table} (UUID: {uuid})")
                        conflict_data['suggestions'] = analyzer._get_conflict_suggestions(analysis)
                        conflicts_manual.append(conflict_data)
    
    except Exception as e:
        logging.error(f"Errore durante la rilevazione e analisi dei conflitti: {e}", exc_info=True)
    
    if conflicts_resolved:
        logging.info(f"✓ {len(conflicts_resolved)} conflitti auto-risolti")
    
    if conflicts_manual:
        logging.warning(f"📌 {len(conflicts_manual)} conflitti richiedono revisione manuale")
    
    return conflicts_resolved, conflicts_manual


# Estensione di ConflictAnalyzer con metodo di suggerimenti
def _get_conflict_suggestions(analysis: dict) -> List[dict]:
    """Genera suggerimenti per la risoluzione di un conflitto."""
    suggestions = []
    
    more_recent = analysis.get('more_recent', 'server')
    
    suggestions.append({
        'option': 1,
        'strategy': 'server_wins',
        'description': f"Usa versione server (più recente del {more_recent})",
        'confidence': 0.9 if more_recent == 'server' else 0.7
    })
    
    suggestions.append({
        'option': 2,
        'strategy': 'client_wins',
        'description': f"Usa versione client (più recente del {more_recent})",
        'confidence': 0.9 if more_recent == 'client' else 0.7
    })
    
    if analysis.get('field_count', 0) <= 2:
        suggestions.append({
            'option': 3,
            'strategy': 'merge',
            'description': "Tenta merge automatico dei campi",
            'confidence': 0.75
        })
    
    return sorted(suggestions, key=lambda x: x['confidence'], reverse=True)


# Aggiungi il metodo a ConflictAnalyzer
ConflictAnalyzer._get_conflict_suggestions = staticmethod(_get_conflict_suggestions)



def run_sync(full_sync=False):
    """
    Esegue la sincronizzazione con il server in modo robusto e sicuro.
    
    Args:
        full_sync: Se True, resetta il database locale e riscarica tutto
        
    Returns:
        tuple: (status, data) dove status può essere 'success', 'error', 'conflict' o None
    """
    backup_path = None
    
    # 1. CONTROLLO DEL LOCK
    if is_sync_locked():
        logging.warning("⚠ Sync già in corso, operazione annullata.")
        QMessageBox.warning(None, "Sincronizzazione in corso",
                              "Un'altra operazione di sincronizzazione è già in corso. "
                              "Attendere il completamento prima di avviarne un'altra.")
        return None, None

    # 2. ACQUISIZIONE DEL LOCK E BLOCCO TRY...FINALLY
    lock_sync()
    
    try:
        # 3. CREAZIONE BACKUP PRE-SINCRONIZZAZIONE
        logging.info("🔄 Inizio sincronizzazione...")
        logging.info("💾 Creazione backup pre-sincronizzazione...")
        backup_path = create_backup("pre_sync")
        
        if not backup_path:
            logging.error("✗ Impossibile creare il backup pre-sincronizzazione")
            return "error", "Impossibile creare il backup di sicurezza. Sincronizzazione annullata per proteggere i dati."
        
        logging.info(f"✓ Backup creato: {backup_path}")
        # 4. RESET DATABASE PER FULL SYNC
        if full_sync:
            try:
                logging.info("🗑 Full sync: cancellazione dati locali...")
                database.wipe_all_syncable_data()
                auth_manager.update_session_timestamp(None)
                logging.info("✓ Dati locali resettati")
            except Exception as e:
                logging.error(f"✗ Errore durante il reset del database: {e}", exc_info=True)
                return "error", f"Impossibile resettare il database locale. Operazione annullata. Errore: {e}"

        # 5. PREPARAZIONE PAYLOAD
        logging.info(f"📤 Preparazione dati per sincronizzazione (Full Sync: {full_sync})...")
        last_sync = auth_manager.get_current_user_info().get('last_sync_timestamp')
        
        local_changes = _get_unsynced_local_changes()
        
        # Conta i record da inviare
        total_to_send = sum(len(records) for records in local_changes.values())
        logging.info(f"📊 Record locali da sincronizzare: {total_to_send}")
        
        # Normalizza i dati per JSON
        for table, rows in list(local_changes.items()):
            if not rows:
                continue
            norm_rows = [_jsonify_record(dict(r) if not isinstance(r, dict) else r) for r in rows]
            local_changes[table] = norm_rows
            
        payload = {"last_sync_timestamp": last_sync, "changes": local_changes}
        
        # Aggiungi checksum e versione per validazione
        payload_checksum = _calculate_checksum(local_changes)
        payload["checksum"] = payload_checksum
        payload["sync_version"] = SYNC_DATA_VERSION
        
        # Verifica dimensione payload
        payload_size = len(json.dumps(payload).encode('utf-8'))
        logging.info(f"📦 Dimensione payload: {payload_size / 1024:.2f} KB (Checksum: {payload_checksum[:8]}...)")
        
        if payload_size > MAX_PAYLOAD_SIZE:
            logging.error(f"✗ Payload troppo grande: {payload_size} bytes")
            return "error", "Troppi dati da sincronizzare in una volta. Contattare il supporto."

        # 6. COMUNICAZIONE CON IL SERVER (CON RETRY)
        try:
            headers = auth_manager.get_auth_headers()
            sync_url = f"{config.SERVER_URL}/sync"
            
            logging.info(f"🌐 Connessione al server: {sync_url}")
            
            # Esegui la richiesta con retry e backoff
            server_response, error_msg = _make_sync_request_with_retry(payload, headers, sync_url)
            
            if error_msg == "auth_error":
                logging.error("✗ Errore di autenticazione (401 - token scaduto o non valido)")
                try:
                    auth_manager.logout()
                except Exception as logout_err:
                    logging.error(f"Errore durante il logout dopo 401: {logout_err}")
                return "auth_error", (
                    "La sessione di accesso è scaduta o non è più valida.\n"
                    "È necessario effettuare nuovamente il login per continuare."
                )
            
            if error_msg:
                logging.error(f"✗ Sincronizzazione fallita: {error_msg}")
                return "error", error_msg
            
            if not server_response:
                return "error", "Errore sconosciuto durante la sincronizzazione"

            # 7. GESTIONE RISPOSTA SERVER
            status = server_response.get("status")
            
            if status == "conflict":
                logging.warning("⚠ Conflitti rilevati durante la sincronizzazione")
                return "conflict", server_response.get("conflicts")
                
            if status != "success":
                error_msg = server_response.get('message', 'Errore sconosciuto')
                logging.error(f"✗ Server ha risposto con errore: {error_msg}")
                raise Exception(f"Il server ha risposto con un errore: {error_msg}")

            # 8. VALIDAZIONE DATI RICEVUTI E CHECKSUM
            changes_from_server = server_response.get("changes", {})
            received_checksum = server_response.get("checksum")
            
            # Valida checksum
            if not _validate_checksum(changes_from_server, received_checksum):
                logging.error("✗ Checksum validazione fallita - dati corrotti")
                raise Exception("I dati ricevuti dal server risultano corrotti (checksum mismatch)")
            
            is_valid, validation_error = _validate_sync_data(changes_from_server)
            
            if not is_valid:
                logging.error(f"✗ Validazione dati fallita: {validation_error}")
                raise Exception(f"I dati ricevuti dal server non sono validi: {validation_error}")

            # 9. APPLICAZIONE MODIFICHE CON TRANSAZIONE ATOMICA
            try:
                with database.DatabaseConnection() as conn:
                    # Inizia transazione esplicita
                    conn.execute("BEGIN IMMEDIATE")
                    
                    try:
                        # Gestione mapping UUID
                        uuid_map = server_response.get("uuid_map", {})
                        if uuid_map:
                            logging.info(f"🔄 Gestione {len(uuid_map)} mapping UUID...")
                            _handle_uuid_maps(conn, uuid_map)
                        
                        # Applica modifiche dal server
                        applied_counts, sync_conflicts = _apply_server_changes(conn, changes_from_server)
                        
                        # Applica eliminazioni definitive propagate dal server
                        hard_deletes_from_server = server_response.get("hard_deletes", {})
                        if hard_deletes_from_server:
                            hard_delete_counts = _apply_hard_deletes(conn, hard_deletes_from_server)
                        else:
                            hard_delete_counts = {}
                        
                        # Marca le modifiche locali come sincronizzate
                        _mark_pushed_changes_as_synced(conn)
                        
                        # Commit transazione
                        conn.commit()
                        logging.info("✓ Transazione completata con successo")
                        
                    except Exception as e:
                        # Rollback automatico in caso di errore
                        conn.rollback()
                        logging.error(f"✗ Errore durante l'applicazione delle modifiche, rollback eseguito: {e}")
                        raise
                
                # Salva i conflitti rilevati nel database (DOPO il commit della transazione principale)
                if sync_conflicts:
                    import uuid as uuid_module
                    for conflict in sync_conflicts:
                        try:
                            conflict_id = str(uuid_module.uuid4())
                            database.save_sync_conflict(
                                conflict_id=conflict_id,
                                table_name=conflict.get('table', 'unknown'),
                                record_uuid=conflict.get('record_uuid'),
                                conflict_type=conflict.get('conflict_type', 'unknown'),
                                severity=conflict.get('severity', 'medium'),
                                local_data=conflict.get('local_data'),
                                server_data=conflict.get('server_data'),
                                error_message=conflict.get('error_message')
                            )
                        except Exception as save_err:
                            logging.error(f"Errore nel salvataggio del conflitto: {save_err}")
                        
            except Exception as e:
                logging.error(f"✗ Errore critico durante la sincronizzazione: {e}", exc_info=True)
                
                # Tentativo di ripristino dal backup
                if backup_path:
                    logging.warning(f"🔄 Tentativo di ripristino dal backup: {backup_path}")
                    if restore_from_backup(backup_path):
                        return "error", f"Sincronizzazione fallita ma database ripristinato dal backup.\nErrore: {e}"
                    else:
                        return "error", f"ERRORE CRITICO: Sincronizzazione fallita e ripristino backup fallito.\nErrore: {e}\nBackup: {backup_path}"
                
                return "error", f"Sincronizzazione fallita: {e}"

            # 10. AGGIORNAMENTO TIMESTAMP
            new_timestamp = server_response.get("new_sync_timestamp")
            auth_manager.update_session_timestamp(new_timestamp)
            logging.info(f"✓ Timestamp aggiornato: {new_timestamp}")

            # 11. PREPARAZIONE MESSAGGIO DI SUCCESSO
            # Mappatura nomi tabelle -> nomi user-friendly (plurale)
            TABLE_DISPLAY_NAMES_PLURAL = {
                "customers": "clienti",
                "mti_instruments": "strumenti",
                "signatures": "firme",
                "profiles": "profili di verifica VE",
                "profile_tests": "test di profilo",
                "functional_profiles": "profili funzionali",
                "destinations": "destinazioni",
                "devices": "dispositivi",
                "verifications": "verifiche elettriche",
                "functional_verifications": "verifiche funzionali",
                "audit_log": "log delle operazioni"
            }
            
            # Mappatura nomi tabelle -> nomi user-friendly (singolare)
            TABLE_DISPLAY_NAMES_SINGULAR = {
                "customers": "cliente",
                "mti_instruments": "strumento",
                "signatures": "firma",
                "profiles": "profilo di verifica VE",
                "profile_tests": "test di profilo",
                "functional_profiles": "profilo funzionale",
                "destinations": "destinazione",
                "devices": "dispositivo",
                "verifications": "verifica elettrica",
                "functional_verifications": "verifica funzionale",
                "audit_log": "log delle operazioni"
            }
            
            summary = []
            for table, count in applied_counts.items():
                if count > 0:
                    if count == 1:
                        display_name = TABLE_DISPLAY_NAMES_SINGULAR.get(table, table)
                    else:
                        display_name = TABLE_DISPLAY_NAMES_PLURAL.get(table, table)
                    summary.append(f"{count} {display_name}")
            
            # Aggiungi info sulle eliminazioni definitive propagate
            hard_delete_summary = []
            if hard_delete_counts:
                for table, count in hard_delete_counts.items():
                    if count > 0:
                        if count == 1:
                            display_name = TABLE_DISPLAY_NAMES_SINGULAR.get(table, table)
                        else:
                            display_name = TABLE_DISPLAY_NAMES_PLURAL.get(table, table)
                        hard_delete_summary.append(f"{count} {display_name}")
            
            if not summary and not hard_delete_summary:
                logging.info("✓ Sincronizzazione completata - nessun nuovo dato")
                base_msg = "Sincronizzazione completata. Nessuna nuova modifica ricevuta."
            else:
                base_msg = "✓ Sincronizzazione completata con successo!"
                if summary:
                    base_msg += "\n\nDati aggiornati:\n- " + "\n- ".join(summary)
                if hard_delete_summary:
                    base_msg += "\n\n🗑️ Eliminati definitivamente:\n- " + "\n- ".join(hard_delete_summary)
            
            logging.info(f"✓ Sincronizzazione completata: {', '.join(summary) if summary else 'nessun dato'}")
            
            # Log audit per sincronizzazione
            try:
                from app import services
                services.log_action('SYNC', 'system', 
                                  entity_description='Sincronizzazione completata',
                                  details={'full_sync': full_sync, 'records': dict(applied_counts)})
            except Exception as e:
                logging.error(f"Errore log audit sync: {e}")
            
            # Se ci sono conflitti locali, ritorna success_with_conflicts
            conflict_count = database.get_pending_conflicts_count()
            if conflict_count > 0:
                base_msg += f"\n\n⚠️ {conflict_count} conflitti rilevati che richiedono la tua attenzione."
                logging.warning(f"📌 Sincronizzazione completata con {conflict_count} conflitti da risolvere")
                return "success_with_conflicts", base_msg
            
            return "success", base_msg
        
        except Exception as e:
            logging.error(f"✗ Errore imprevisto durante la sincronizzazione: {e}", exc_info=True)
            return "error", f"Errore imprevisto: {str(e)}\nControllare i log per maggiori dettagli."

    finally:
        # 13. RILASCIO LOCK
        unlock_sync()
        logging.info("🔓 Lock di sincronizzazione rilasciato")