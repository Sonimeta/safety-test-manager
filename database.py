# database.py (Versione aggiornata con Gestore di Contesto)
import sqlite3
import json
import os
import logging
from datetime import datetime, timezone
import re
import serial
from app import config
from app.data_models import VerificationProfile, Test, Limit
from app.functional_models import FunctionalField, FunctionalProfile, FunctionalRowDefinition, FunctionalSection
import uuid

IGNORABLE_ERROR_SNIPPETS = (
    "duplicate column name",
    "already exists",
    "no such savepoint",  # difensivo
)

DB_PATH = config.DB_PATH
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ==============================================================================
# SEZIONE 1: GESTORE DI CONTESTO PER LA CONNESSIONE AL DATABASE
# ==============================================================================

class DatabaseConnection:
    """
    Un gestore di contesto robusto per la connessione al database SQLite.
    Gestisce automaticamente l'apertura, la chiusura, il commit e il rollback.
    """
    def __init__(self, db_name=DB_PATH):
        self.db_name = db_name
        self.conn = None

    def __enter__(self):
        """Metodo chiamato quando si entra nel blocco 'with'."""
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON;")
            logging.debug("Connessione al database aperta.")
            return self.conn
        except sqlite3.Error as e:
            logging.error(f"Errore di connessione al database: {e}", exc_info=True)
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Metodo chiamato quando si esce dal blocco 'with'."""
        if exc_type:
            logging.warning(f"Si è verificata un'eccezione, transazione DB annullata (rollback). Errore: {exc_val}")
            if self.conn is not None:
                self.conn.rollback()
        else:
            logging.debug("Transazione DB completata, modifiche confermate (commit).")
            if self.conn is not None:
                self.conn.commit()
        
        if self.conn is not None:
            self.conn.close()
        logging.debug("Connessione al database chiusa.")
        return False # Non sopprime eventuali eccezioni

# ==============================================================================
# SEZIONE 2: MIGRAZIONE DEL DATABASE
# ==============================================================================

def _execute_sql_script_compat(conn, sql_script: str) -> None:
    """
    Esegue uno script SQL rendendolo compatibile con versioni SQLite
    che non supportano 'ADD COLUMN IF NOT EXISTS'.
    - Rimuove 'IF NOT EXISTS' solo nei contesti 'ADD COLUMN'
    - Esegue statement singolarmente
    - Ignora errori idempotenti (colonna già esistente / oggetto già esistente)
    """
    # 1) normalizza gli 'ADD COLUMN IF NOT EXISTS' -> 'ADD COLUMN'
    script = re.sub(
        r'(?i)(ADD\s+COLUMN)\s+IF\s+NOT\s+EXISTS',
        r'\1',
        sql_script,
    )

    # 2) split molto semplice per ';' (gli script di migrazione sono lineari)
    statements = [s.strip() for s in script.split(';') if s.strip()]
    cur = conn.cursor()
    for stmt in statements:
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if any(snippet in msg for snippet in IGNORABLE_ERROR_SNIPPETS):
                logging.info(f"[migrate] Ignoro statement già applicato: {stmt[:120]}... ({e})")
                continue
            logging.warning(f"[migrate] Errore eseguendo: {stmt}\n→ {e}")
            raise
    cur.close()

def migrate_database():
    """Applica le migrazioni SQL al database in modo sequenziale."""
    migrations_path = os.path.join(config.BASE_DIR, 'migrations') 
    if not os.path.isdir(migrations_path):
        logging.info(f"Cartella delle migrazioni '{migrations_path}' non trovata. Migrazione saltata.")
        return

    try:
        with DatabaseConnection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);")
            result = conn.execute("SELECT version FROM schema_version;").fetchone()
            current_version = result['version'] if result else 0
        
        migration_files = sorted([f for f in os.listdir(migrations_path) if f.endswith('.sql')])

        for m_file in migration_files:
            try:
                file_version = int(m_file.split('_')[0])
            except (ValueError, IndexError):
                logging.warning(f"File di migrazione '{m_file}' non nominato correttamente. Ignorato.")
                continue

            if file_version > current_version:
                logging.info(f"Applicando migrazione: {m_file}...")
                with open(os.path.join(migrations_path, m_file), 'r', encoding='utf-8') as f:
                    sql_script = f.read()
                
                with DatabaseConnection() as conn:
                    try:
                        _execute_sql_script_compat(conn, sql_script)
                    except Exception:
                        logging.critical("Errore critico durante la migrazione del database.", exc_info=True)
                        raise
                    # Aggiorna la versione dello schema
                    if current_version == 0 and file_version == 1:
                        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (file_version,))
                    else:
                        conn.execute("UPDATE schema_version SET version = ?", (file_version,))
                
                current_version = file_version
                logging.info(f"Database aggiornato alla versione {current_version}.")
    except Exception as e:
        logging.critical("Errore critico durante la migrazione del database.", exc_info=True)
        raise

# ==============================================================================
# SEZIONE 3: FUNZIONI DI MANIPOLAZIONE DATI (DAO)
# ==============================================================================

# --- Helper per decodifica JSON ---
def _decode_json_fields(row, fields_to_decode):
    if not row: return None
    data = dict(row)
    for field in fields_to_decode:
        json_string = data.get(field)
        new_key = field.replace('_json', '')
        try:
            data[new_key] = json.loads(json_string) if json_string else []
        except (json.JSONDecodeError, TypeError):
            data[new_key] = []
    return data

# --- Gestione Dispositivi (Devices) ---

def find_device_by_serial(serial_number: str, include_deleted: bool = False):
    """
    Trova un dispositivo per matricola (solo attivi).
    Se include_deleted=True, cerca anche tra i record eliminati.
    """
    if not serial_number: return None
    with DatabaseConnection() as conn:
        query = "SELECT * FROM devices WHERE serial_number = ? AND status = 'active'" # Filtra per attivi
        params = [serial_number]
        if not include_deleted:
            query += " AND is_deleted = 0"
        
        row = conn.execute(query, tuple(params)).fetchone()
        return _decode_json_fields(row, ['applied_parts_json']) if row else None

def find_deleted_device_by_serial_with_details(serial_number: str):
    """
    Trova un dispositivo eliminato per matricola con informazioni complete
    (cliente, destinazione, ecc.) per mostrare all'utente.
    Restituisce None se non esiste un dispositivo eliminato con quel S/N.
    """
    if not serial_number:
        return None
    
    with DatabaseConnection() as conn:
        query = """
            SELECT 
                dev.id,
                dev.uuid,
                dev.serial_number,
                dev.description,
                dev.manufacturer,
                dev.model,
                dev.department,
                dev.customer_inventory,
                dev.ams_inventory,
                dev.verification_interval,
                dev.default_profile_key,
                dev.next_verification_date,
                dev.status,
                dev.is_deleted,
                dest.name as destination_name,
                dest.address as destination_address,
                cust.name as customer_name,
                cust.id as customer_id
            FROM devices dev
            LEFT JOIN destinations dest ON dev.destination_id = dest.id
            LEFT JOIN customers cust ON dest.customer_id = cust.id
            WHERE dev.serial_number = ? AND dev.is_deleted = 1
            LIMIT 1
        """
        row = conn.execute(query, (serial_number,)).fetchone()
        return dict(row) if row else None

def add_device(uuid, destination_id, serial, desc, mfg, model, department, applied_parts, customer_inv, ams_inv, verification_interval, default_profile_key, default_functional_profile_key, timestamp):
    # Normalizzazione campi chiave per coerenza (anche per importazioni)
    serial = (serial or "").strip().upper() or None
    customer_inv = (customer_inv or "").strip().upper() or None
    ams_inv = (ams_inv or "").strip().upper() or None

    pa_json = json.dumps([pa if isinstance(pa, dict) else pa.__dict__ for pa in applied_parts])
    interval = int(verification_interval) if verification_interval not in [None, "Nessuno", "NESSUNO", "nessuno"] else None
    
    with DatabaseConnection() as conn:
        query = """
            INSERT INTO devices (
                uuid, destination_id, serial_number, description, manufacturer, 
                model, department, applied_parts_json, customer_inventory, 
                ams_inventory, verification_interval, default_profile_key,
                default_functional_profile_key, last_modified, is_synced, is_deleted, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'active')
        """
        params = (
            uuid, destination_id, serial, desc, mfg, model, department, pa_json,
            customer_inv, ams_inv, interval, default_profile_key,
            default_functional_profile_key, timestamp
        )
        cursor = conn.execute(query, params)
        new_device_id = cursor.lastrowid
    return new_device_id

def update_device(
    dev_id, destination_id, serial, desc, mfg, model, department,
    applied_parts, customer_inv, ams_inv,
    verification_interval, default_profile_key, default_functional_profile_key, timestamp,
    reactivate=False, new_destination_id=None):

    # Normalizzazione campi chiave per coerenza (anche per importazioni)
    serial = (serial or "").strip().upper() or None
    customer_inv = (customer_inv or "").strip().upper() or None
    ams_inv = (ams_inv or "").strip().upper() or None

    final_destination_id = new_destination_id if new_destination_id is not None else destination_id
    pa_json = json.dumps([pa if isinstance(pa, dict) else pa.__dict__ for pa in applied_parts])
    interval = int(verification_interval) if verification_interval not in [None, "Nessuno", "NESSUNO", "nessuno"] else None

    with DatabaseConnection() as conn:
        is_deleted_val = 0 if reactivate else conn.execute(
            "SELECT is_deleted FROM devices WHERE id=?", (dev_id,)
        ).fetchone()[0]

        query = """
            UPDATE devices SET 
                serial_number = ?, destination_id = ?, description = ?, 
                manufacturer = ?, model = ?, department = ?, 
                applied_parts_json = ?, customer_inventory = ?, 
                ams_inventory = ?, default_profile_key = ?, default_functional_profile_key = ?,
                verification_interval = ?, last_modified = ?, 
                is_synced = 0, is_deleted = ?
            WHERE id = ?
        """
        params = (serial, final_destination_id, desc, mfg, model, department,
                  pa_json, customer_inv, ams_inv, default_profile_key,
                  default_functional_profile_key,
                  interval, timestamp, is_deleted_val, dev_id)
        conn.execute(query, params)

def set_device_status(dev_id: int, status: str, timestamp: str):
    """Imposta lo stato di un dispositivo (active o decommissioned)."""
    if status not in ['active', 'decommissioned']:
        raise ValueError("Stato non valido.")
    with DatabaseConnection() as conn:
        conn.execute(
            "UPDATE devices SET status = ?, last_modified = ?, is_synced = 0 WHERE id = ?",
            (status, timestamp, dev_id)
        )

def wipe_all_syncable_data():
    """Cancella i dati locali per forzare un full-sync dal server."""
    with DatabaseConnection() as conn:
        for table in [
            "verifications",
            "functional_verifications",
            "devices",
            "destinations",
            "profile_tests",
            "profiles",
            "functional_profiles",
            "mti_instruments",
            "customers",
        ]:
            conn.execute(f"DELETE FROM {table}")
        # eventuale pulizia firme locali se vuoi ripopolarle dal server:
        # conn.execute("DELETE FROM signatures")

def soft_delete_device(dev_id, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("UPDATE devices SET is_deleted=1, last_modified=?, is_synced=0 WHERE id=?", (timestamp, dev_id,))
    logging.warning(f"Dispositivo ID {dev_id} marcato come eliminato.")

def soft_delete_all_devices_for_customer(customer_id, timestamp):
    with DatabaseConnection() as conn:
        cursor = conn.execute("""
            UPDATE devices
            SET is_deleted = 1, last_modified = ?, is_synced = 0
            WHERE destination_id IN (SELECT id FROM destinations WHERE customer_id = ?)
        """, (timestamp, customer_id))
    logging.warning(f"Marcati come eliminati {cursor.rowcount} dispositivi per il cliente ID {customer_id}.")
    return True

def move_device_to_destination(device_id, new_destination_id, timestamp):
    """Sposta un dispositivo aggiornando il suo destination_id."""
    with DatabaseConnection() as conn:
        conn.execute(
            "UPDATE devices SET destination_id = ?, last_modified = ?, is_synced = 0 WHERE id = ?",
            (new_destination_id, timestamp, device_id)
        )

def get_devices_for_destination(destination_id: int, search_query=None):
    """Recupera tutti i dispositivi ATTIVI per una specifica destinazione."""
    with DatabaseConnection() as conn:
        query = "SELECT * FROM devices WHERE destination_id = ? AND is_deleted = 0 AND status = 'active'"
        params = [destination_id]
        if search_query:
            query += " AND (description LIKE ? OR serial_number LIKE ? OR model LIKE ?)"
            params.extend([f"%{search_query}%"] * 3)
        query += " ORDER BY description"
        return conn.execute(query, params).fetchall()

def get_devices_for_destination_manager(destination_id: int, search_query=None):
    """Recupera TUTTI i dispositivi (attivi e dismessi) per il manager."""
    with DatabaseConnection() as conn:
        query = "SELECT * FROM devices WHERE destination_id = ? AND is_deleted = 0" # No status filter
        params = [destination_id]
        if search_query:
            query += " AND (description LIKE ? OR serial_number LIKE ? OR model LIKE ? OR AMS_inventory LIKE ? OR Customer_inventory LIKE ?)"
            params.extend([f"%{search_query}%"] * 5)
        query += " ORDER BY status, description" # Ordina per stato
        return conn.execute(query, params).fetchall()

def get_device_by_serial(serial_number: str):
    """Trova un dispositivo per numero di serie (solo non eliminati)."""
    with DatabaseConnection() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE serial_number = ? AND is_deleted = 0", 
            (serial_number,)
        ).fetchone()
        return _decode_json_fields(row, ['applied_parts_json']) if row else None

def get_device_by_serial_number(serial_number: str):
    """Alias per get_device_by_serial - per compatibilità."""
    return get_device_by_serial(serial_number)

def get_device_by_inventory_number(inventory_number: str):
    """Trova un dispositivo per numero inventario AMS (solo non eliminati)."""
    with DatabaseConnection() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE AMS_inventory = ? AND is_deleted = 0", 
            (inventory_number,)
        ).fetchone()
        return _decode_json_fields(row, ['applied_parts_json']) if row else None

def get_device_by_customer_inventory(customer_inventory: str):
    """Trova un dispositivo per numero inventario cliente (solo non eliminati)."""
    with DatabaseConnection() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE Customer_inventory = ? AND is_deleted = 0", 
            (customer_inventory,)
        ).fetchone()
        return _decode_json_fields(row, ['applied_parts_json']) if row else None

def get_all_unique_device_descriptions():
    """Recupera una lista di tutte le descrizioni uniche dei dispositivi."""
    with DatabaseConnection() as conn:
        query = "SELECT DISTINCT description FROM devices WHERE is_deleted = 0 AND description IS NOT NULL AND description <> '' ORDER BY description"
        rows = conn.execute(query).fetchall()
        # Restituisce una lista di stringhe, non di tuple
        return [row['description'] for row in rows]

def get_devices_by_description(description: str):
    """Recupera tutti i dispositivi che corrispondono a una specifica descrizione."""
    with DatabaseConnection() as conn:
        query = "SELECT id, description, serial_number, model FROM devices WHERE description = ? AND is_deleted = 0"
        return conn.execute(query, (description,)).fetchall()

def bulk_update_device_description(old_description: str, new_description: str, timestamp: str):
    """
    Aggiorna la descrizione per tutti i dispositivi che corrispondono alla vecchia descrizione.
    Restituisce il numero di righe modificate.
    """
    with DatabaseConnection() as conn:
        cursor = conn.execute(
            "UPDATE devices SET description = ?, last_modified = ?, is_synced = 0 WHERE description = ? AND is_deleted = 0",
            (new_description, timestamp, old_description)
        )
        logging.info(f"Aggiornate {cursor.rowcount} descrizioni da '{old_description}' a '{new_description}'.")
        return cursor.rowcount


def get_devices_for_customer(customer_id, search_query=None):
    with DatabaseConnection() as conn:
        query = """
            SELECT d.* FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE dest.customer_id = ? AND d.is_deleted = 0
        """
        params = [customer_id]
        if search_query:
            query += " AND (d.description LIKE ? OR d.serial_number LIKE ? OR d.model LIKE ?)"
            params.extend([f"%{search_query}%"]*3)
        query += " ORDER BY d.description"
        return conn.execute(query, params).fetchall()

def get_device_by_id(device_id: int):
    with DatabaseConnection() as conn:
        device_row = conn.execute("SELECT * FROM devices WHERE id = ? AND is_deleted = 0", (device_id,)).fetchone()
    return _decode_json_fields(device_row, ['applied_parts_json'])
    
def device_exists(serial_number: str):
    """Controlla se esiste un dispositivo ATTIVO con un dato seriale."""
    with DatabaseConnection() as conn:
        return conn.execute("SELECT id FROM devices WHERE serial_number = ? AND is_deleted = 0 AND status = 'active'", (serial_number,)).fetchone() is not None

def get_device_count_for_customer(customer_id):
    with DatabaseConnection() as conn:
        return conn.execute("""
            SELECT COUNT(d.id)
            FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE dest.customer_id = ? AND d.is_deleted = 0
        """, (customer_id,)).fetchone()[0]

def get_devices_needing_verification(days_in_future=30):
    """Recupera i dispositivi ATTIVI con verifica scaduta o in scadenza."""
    from datetime import date, timedelta
    future_date = date.today() + timedelta(days=days_in_future)
    
    with DatabaseConnection() as conn:
        query = """
            SELECT d.*, c.name as customer_name, dest.name as destination_name
            FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            JOIN customers c ON dest.customer_id = c.id
            WHERE d.next_verification_date IS NOT NULL 
            AND d.next_verification_date <= ?
            AND d.is_deleted = 0 AND d.status = 'active'
            ORDER BY d.next_verification_date ASC
        """
        return conn.execute(query, (future_date.strftime('%Y-%m-%d'),)).fetchall()
    
def search_device_globally(search_term):
    """
    Cerca un dispositivo in tutto il database e restituisce anche il nome del cliente
    a cui appartiene, navigando attraverso le destinazioni.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT d.*, c.name as customer_name 
            FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            JOIN customers c ON dest.customer_id = c.id
            WHERE (
                d.serial_number LIKE ? OR 
                d.ams_inventory LIKE ? OR 
                d.customer_inventory LIKE ? OR
                d.description LIKE ? OR 
                d.model LIKE ?
            ) AND d.is_deleted = 0
        """
        like_term = f"%{search_term}%"
        rows = conn.execute(query, (like_term, like_term, like_term, like_term, like_term)).fetchall()
        
        if not rows:
            return []
        
        results = [_decode_json_fields(row, ['applied_parts_json']) for row in rows]
        return results

def search_destinations_globally(search_term: str):
    """Ricerca destinazioni (con cliente associato) per la ricerca rapida."""
    if not search_term:
        return []

    with DatabaseConnection() as conn:
        # Verifica se l'utente ha inserito un ID numerico di destinazione
        try:
            destination_id = int(search_term)
        except ValueError:
            destination_id = None

        results = []
        if destination_id is not None:
            check_query = """
                SELECT d.*, c.name as customer_name
                FROM destinations d
                JOIN customers c ON d.customer_id = c.id 
                WHERE d.id = ? AND d.is_deleted = 0
            """
            dest = conn.execute(check_query, (destination_id,)).fetchone()
            if dest:
                results.append(dict(dest))

        search_pattern = f"%{search_term}%"
        query = """
            SELECT 
                d.id,
                d.name,
                d.address,
                d.phone,
                d.email,
                d.customer_id,
                c.name as customer_name,
                d.is_deleted,
                d.is_synced,
                d.last_modified,
                d.uuid
            FROM destinations d
            JOIN customers c ON d.customer_id = c.id
            WHERE (
                d.name LIKE ? OR 
                d.address LIKE ? OR 
                c.name LIKE ?
            ) AND d.is_deleted = 0

            UNION

            SELECT 
                dest.id,
                dest.name,
                dest.address,
                dest.phone,
                dest.email,
                dest.customer_id,
                c.name as customer_name,
                dest.is_deleted,
                dest.is_synced,
                dest.last_modified,
                dest.uuid
            FROM devices dev
            JOIN destinations dest ON dev.destination_id = dest.id
            JOIN customers c ON dest.customer_id = c.id
            WHERE (
                dev.description LIKE ? OR
                dev.serial_number LIKE ? OR
                dev.ams_inventory LIKE ? OR
                dev.customer_inventory LIKE ?
            ) AND dev.is_deleted = 0 AND dest.is_deleted = 0
        """

        params = [search_pattern] * 7
        rows = conn.execute(query, params).fetchall()
        results.extend(dict(row) for row in rows)

        logging.debug(f"Global destination search found {len(results)} results for term: {search_term}")
        return results

def get_devices_with_last_verification_for_destination(destination_id: int):
    """
    Recupera tutti i dispositivi di una destinazione con i dati della loro ultima verifica.
    Ora include l'inventario cliente e il nome della destinazione.
    """
    with DatabaseConnection() as conn:
        
        query = """
            SELECT
                CASE
                    WHEN d.status = "active" THEN "ATTIVO"
                    WHEN d.status = "inactive" THEN "DISMESSO"
                END AS "STATO",
                d.ams_inventory AS "INVENTARIO AMS",
                d.customer_inventory AS "INVENTARIO CLIENTE",
                d.description AS "DENOMINAZIONE", 
                d.manufacturer AS "MARCA",
                d.model AS "MODELLO",
                d.serial_number AS "MATRICOLA",
                d.department AS "REPARTO",
                v.verification_date AS "DATA",
                v.technician_name AS "TECNICO",
                CASE
                    WHEN v.overall_status = "PASSATO" THEN "CONFORME"
                    WHEN v.overall_status = "CONFORME CON ANNOTAZIONE" THEN "CONFORME CON ANNOTAZIONE"
                    WHEN v.overall_status = "FALLITO" THEN "NON CONFORME"
                END AS "ESITO",
                dest.name AS "DESTINAZIONE" 
            FROM
                devices d
            LEFT JOIN
                (
                    SELECT
                        *,
                        ROW_NUMBER() OVER(PARTITION BY device_id ORDER BY verification_date DESC) as rn
                    FROM verifications
                    WHERE is_deleted = 0
                ) v ON d.id = v.device_id AND v.rn = 1
            JOIN
                destinations dest ON d.destination_id = dest.id
            WHERE
                d.destination_id = ? AND d.is_deleted = 0
            ORDER BY
                d.description;
        """
        return conn.execute(query, (destination_id,)).fetchall()

def get_devices_with_verifications_for_destination_by_date_range(destination_id: int, start_date: str, end_date: str):
    """
    Recupera TUTTI i dispositivi di una destinazione. Se sono state eseguite
    verifiche nell'intervallo di date specificato, include SOLO i dati della
    verifica PIÙ RECENTE per ciascun dispositivo.
    """
    with DatabaseConnection() as conn:
        # --- INIZIO QUERY CORRETTA ---
        # La query ora recupera TUTTI i dispositivi della destinazione.
        # Poi, tramite un LEFT JOIN su una sottoquery (RankedVerifications), associa
        # i dati della verifica PIÙ RECENTE eseguita nell'intervallo di date.
        # Se un dispositivo non ha verifiche nel periodo, i campi relativi (DATA, TECNICO, ESITO)
        # risulteranno vuoti, ma il dispositivo sarà comunque presente una sola volta.
        query = """
            WITH RankedVerifications AS (
                SELECT
                    v.*,
                    ROW_NUMBER() OVER(PARTITION BY v.device_id ORDER BY v.verification_date DESC) as rn
                FROM
                    verifications v
                WHERE
                    v.is_deleted = 0
                    AND v.verification_date BETWEEN ? AND ?
            ),
            RankedFunctionalVerifications AS (
                SELECT
                    fv.*,
                    ROW_NUMBER() OVER(PARTITION BY fv.device_id ORDER BY fv.verification_date DESC) as rn
                FROM
                    functional_verifications fv
                WHERE
                    fv.is_deleted = 0
                    AND fv.verification_date BETWEEN ? AND ?
            )
            SELECT
                CASE 
                    WHEN d.status = "active" THEN "IN USO"
                    ELSE "DISMESSO" 
                END AS "STATO",
                d.ams_inventory AS "INVENTARIO AMS",
                d.customer_inventory AS "INVENTARIO CLIENTE",
                d.description AS "DENOMINAZIONE", 
                d.manufacturer AS "MARCA",
                d.model AS "MODELLO",
                d.serial_number AS "MATRICOLA",
                d.department AS "REPARTO",
                rv.verification_date AS "DATA",
                rv.technician_name AS "TECNICO",
                CASE 
                    WHEN rv.overall_status = "PASSATO" THEN "CONFORME" 
                    WHEN rv.overall_status = "CONFORME CON ANNOTAZIONE" THEN "CONFORME CON ANNOTAZIONE"
                    WHEN rv.overall_status = "FALLITO" THEN "NON CONFORME"
                END AS "ESITO",
                COALESCE(rfv.overall_status, 'Nessuna verifica') AS "ESITO VERIFICHE FUNZIONALI",
                dest.name AS "DESTINAZIONE" 
            FROM 
                devices d
            JOIN 
                destinations dest ON d.destination_id = dest.id
            LEFT JOIN 
                RankedVerifications rv ON d.id = rv.device_id AND rv.rn = 1
            LEFT JOIN 
                RankedFunctionalVerifications rfv ON d.id = rfv.device_id AND rfv.rn = 1
            WHERE 
                d.destination_id = ? AND d.is_deleted = 0
            ORDER BY 
                d.description;
        """
        # I parametri devono corrispondere ai '?' nella query nell'ordine corretto
        # start_date e end_date vengono usati due volte: una per le verifiche elettriche e una per quelle funzionali
        return conn.execute(query, (start_date, end_date, start_date, end_date, destination_id)).fetchall()
    
def get_devices_for_customer_inventory_export(customer_id: int):
    """Get devices for customer inventory export."""
    with DatabaseConnection() as conn:
        query = """
            SELECT 
                d.ams_inventory as ams_inventory,
                d.customer_inventory as customer_inventory,
                d.description as description,
                d.manufacturer as manufacturer,
                d.model as model,
                d.serial_number as serial_number,
                dest.name as destination,
                CASE 
                    WHEN d.status = "active" THEN "ATTIVO"
                    WHEN d.status = "inactive" THEN "DISMESSO"
                END AS "status"
            FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE dest.customer_id = ?
            AND d.is_deleted = 0
            ORDER BY d.description
        """
        return conn.execute(query, (int(customer_id),)).fetchall()

def add_destination(uuid, customer_id, name, address, timestamp):
    """Aggiunge una nuova destinazione."""
    with DatabaseConnection() as conn:
        conn.execute(
            "INSERT INTO destinations (uuid, customer_id, name, address, last_modified, is_synced, is_deleted) VALUES (?, ?, ?, ?, ?, 0, 0)",
            (uuid, customer_id, name, address, timestamp)
        )

def update_destination(dest_id, name, address, timestamp):
    """Aggiorna una destinazione."""
    with DatabaseConnection() as conn:
        conn.execute(
            "UPDATE destinations SET name = ?, address = ?, last_modified = ?, is_synced = 0 WHERE id = ?",
            (name, address, timestamp, dest_id)
        )

def delete_destination(dest_id, timestamp):
    """Esegue un soft delete di una destinazione."""
    with DatabaseConnection() as conn:
        # Qui potresti aggiungere un controllo per impedire l'eliminazione se ci sono dispositivi
        conn.execute("UPDATE destinations SET is_deleted = 1, last_modified = ?, is_synced = 0 WHERE id = ?", (timestamp, dest_id))

def get_device_count_for_destination(destination_id: int):
    """
    Conta quanti dispositivi attivi sono presenti in una specifica destinazione.
    """
    with DatabaseConnection() as conn:
        # Esegue una query per contare le righe
        count = conn.execute(
            "SELECT COUNT(id) FROM devices WHERE destination_id = ? AND is_deleted = 0",
            (destination_id,)
        ).fetchone()[0]
    return count

def get_destinations_for_customer(customer_id: int, search_query: str = None):
    """Recupera tutte le destinazioni attive per un cliente."""
    with DatabaseConnection() as conn:
        query = "SELECT * FROM destinations WHERE customer_id = ? AND is_deleted = 0"
        params = [customer_id]
        if search_query:
            query += " AND (name LIKE ? OR address LIKE ?)"
            params.extend([f"%{search_query}%"] * 2)
        query += " ORDER BY name"
        return conn.execute(query, tuple(params)).fetchall()

def get_destination_by_id(destination_id: int):
    """
    Recupera una singola destinazione tramite il suo ID numerico.
    """
    with DatabaseConnection() as conn:
        row = conn.execute(
            "SELECT * FROM destinations WHERE id = ? AND is_deleted = 0",
            (destination_id,)
        ).fetchone()
        return row

def advanced_search(criteria: dict):
    """
    Esegue una query di ricerca dinamica nel database.
    """
    base_query = """
        SELECT
            c.name AS "Cliente",
            d.name AS "Destinazione",
            dev.description AS "Apparecchio",
            dev.serial_number AS "Matricola",
            dev.manufacturer AS "Marca",
            dev.model AS "Modello",
            v.verification_date AS "Data Verifica",
            v.technician_name AS "Tecnico",
            CASE
                WHEN v.overall_status = 'PASSATO' THEN 'CONFORME'
                WHEN v.overall_status = 'CONFORME CON ANNOTAZIONE' THEN 'CONFORME CON ANNOTAZIONE'
                WHEN v.overall_status = 'FALLITO' THEN 'NON CONFORME'
                ELSE 'NON VERIFICATO'
            END AS "Esito",
            dev.id AS device_id,  -- Aggiunto per la navigazione
            v.id AS verification_id -- Aggiunto per la navigazione
        FROM
            devices dev
        LEFT JOIN
            verifications v ON dev.id = v.device_id AND v.is_deleted = 0
        JOIN
            destinations d ON dev.destination_id = d.id
        JOIN
            customers c ON d.customer_id = c.id
        WHERE
            dev.is_deleted = 0
    """

    conditions = []
    params = []

    if criteria.get("customer_name"):
        conditions.append("c.name LIKE ?")
        params.append(f"%{criteria['customer_name']}%")
    
    if criteria.get("destination_name"):
        conditions.append("d.name LIKE ?")
        params.append(f"%{criteria['destination_name']}%")

    if criteria.get("device_description"):
        conditions.append("dev.description LIKE ?")
        params.append(f"%{criteria['device_description']}%")

    if criteria.get("serial_number"):
        conditions.append("dev.serial_number LIKE ?")
        params.append(f"%{criteria['serial_number']}%")

    if criteria.get("technician_name"):
        # Se cerco per tecnico, devo assicurarmi che il LEFT JOIN non fallisca
        # per i dispositivi mai verificati. Aggiungo una condizione che forza
        # l'esistenza di una verifica.
        conditions.append("v.id IS NOT NULL")
        # Questa condizione richiede che esista una verifica
        conditions.append("v.technician_name LIKE ?")
        params.append(f"%{criteria['technician_name']}%")

    if conditions:
        base_query += " AND " + " AND ".join(conditions)

    # --- NUOVA LOGICA PER CRITERI AGGIUNTIVI ---
    if criteria.get("manufacturer"):
        base_query += " AND dev.manufacturer LIKE ?"
        params.append(f"%{criteria['manufacturer']}%")

    if criteria.get("model"):
        base_query += " AND dev.model LIKE ?"
        params.append(f"%{criteria['model']}%")
    
    # Filtro per stato dispositivo
    device_status = criteria.get("device_status")
    if device_status and device_status != "QUALSIASI":
        if device_status == "ATTIVO":
            base_query += " AND (dev.status = 'active' OR dev.status IS NULL)"
        elif device_status == "DISMESSO":
            base_query += " AND dev.status = 'decommissioned'"

    if criteria.get("start_date") and criteria.get("end_date"):
        base_query += " AND v.id IS NOT NULL AND v.verification_date BETWEEN ? AND ?"
        params.extend([criteria["start_date"], criteria["end_date"]])

    outcome = criteria.get("outcome")
    if outcome and outcome.upper() not in ["QUALSIASI", ""]:
        if outcome.upper() == "CONFORME":
            base_query += " AND v.id IS NOT NULL AND v.overall_status = 'PASSATO'"
        elif outcome.upper() == "NON CONFORME":
            base_query += " AND v.id IS NOT NULL AND v.overall_status = 'FALLITO'"
        elif outcome.upper() == "NON VERIFICATO":
            # Per cercare dispositivi mai verificati
            base_query += " AND v.id IS NULL"

    base_query += " ORDER BY c.name, d.name, dev.description;"

    with DatabaseConnection() as conn:
        return conn.execute(base_query, tuple(params)).fetchall()

def get_all_destinations_with_customer():
    """
    Recupera tutte le destinazioni attive, includendo l'ID e il nome del cliente associato.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT d.*, c.name as customer_name 
            FROM destinations d
            JOIN customers c ON d.customer_id = c.id
            WHERE d.is_deleted = 0 AND c.is_deleted = 0
            ORDER BY c.name, d.name
        """
        return conn.execute(query).fetchall()

def add_customer(uuid, name, address, phone, email, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("INSERT INTO customers (uuid, name, address, phone, email, last_modified, is_synced) VALUES (?, ?, ?, ?, ?, ?, 0)", (uuid, name, address, phone, email, timestamp))

def add_or_get_customer(name: str, address: str):
    """Trova o crea un cliente e restituisce il suo ID."""
    with DatabaseConnection() as conn:
        # Cerca cliente esistente
        existing = conn.execute(
            "SELECT id FROM customers WHERE name = ? AND is_deleted = 0", 
            (name,)
        ).fetchone()
        
        if existing:
            return existing['id']
        
        # Crea nuovo cliente
        import uuid
        from datetime import datetime, timezone
        new_uuid = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO customers (uuid, name, address, phone, email, last_modified, is_synced) VALUES (?, ?, ?, '', '', ?, 0)",
            (new_uuid, name, address, timestamp)
        )
        return cursor.lastrowid

def update_customer(cust_id, name, address, phone, email, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("UPDATE customers SET name=?, address=?, phone=?, email=?, last_modified=?, is_synced=0 WHERE id=?", (name, address, phone, email, timestamp, cust_id))

def soft_delete_customer(cust_id, timestamp):
    with DatabaseConnection() as conn:
        # --- QUERY AGGIORNATA ---
        # Per contare i dispositivi, ora dobbiamo passare attraverso la tabella 'destinations'.
        # Questa query conta tutti i dispositivi le cui destinazioni appartengono al cliente che stiamo cercando di eliminare.
        query = """
            SELECT COUNT(id) FROM devices 
            WHERE is_deleted = 0 AND destination_id IN (
                SELECT id FROM destinations WHERE customer_id = ?
            )
        """
        count = conn.execute(query, (cust_id,)).fetchone()[0]
        # --- FINE MODIFICA ---

        if count > 0:
            return False, f"Impossibile eliminare: il cliente ha {count} dispositivi associati nelle sue destinazioni."
        
        # Se non ci sono dispositivi, procedi con l'eliminazione
        conn.execute("UPDATE customers SET is_deleted=1, last_modified=?, is_synced=0 WHERE id=?", (timestamp, cust_id))
    
    return True, "Cliente eliminato."


def get_all_customers(search_query=None):
    with DatabaseConnection() as conn:
        query = "SELECT * FROM customers WHERE is_deleted = 0"
        params = []
        if search_query:
            query += " AND name LIKE ?"
            params.append(f"%{search_query}%")
        query += " ORDER BY name"
        return conn.execute(query, params).fetchall()

def get_duplicate_devices_by_serial():
    """
    Restituisce dispositivi potenzialmente duplicati in base a
    UNO dei seguenti identificativi (non vuoti):
    - numero di serie
    - inventario cliente
    - inventario AMS
    """
    with DatabaseConnection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT 
                d.*,
                dest.name AS destination_name,
                c.name AS customer_name,
                CASE 
                    WHEN d.serial_number IS NOT NULL
                         AND TRIM(d.serial_number) <> ''
                         AND d.serial_number IN (
                             SELECT serial_number
                             FROM devices
                             WHERE is_deleted = 0
                               AND serial_number IS NOT NULL
                               AND TRIM(serial_number) <> ''
                             GROUP BY serial_number
                             HAVING COUNT(*) > 1
                         )
                    THEN 'SERIALE'
                    
                    WHEN d.customer_inventory IS NOT NULL
                         AND TRIM(d.customer_inventory) <> ''
                         AND d.customer_inventory IN (
                             SELECT customer_inventory
                             FROM devices
                             WHERE is_deleted = 0
                               AND customer_inventory IS NOT NULL
                               AND TRIM(customer_inventory) <> ''
                             GROUP BY customer_inventory
                             HAVING COUNT(*) > 1
                         )
                    THEN 'INVENTARIO CLIENTE'
                    
                    WHEN d.ams_inventory IS NOT NULL
                         AND TRIM(d.ams_inventory) <> ''
                         AND d.ams_inventory IN (
                             SELECT ams_inventory
                             FROM devices
                             WHERE is_deleted = 0
                               AND ams_inventory IS NOT NULL
                               AND TRIM(ams_inventory) <> ''
                             GROUP BY ams_inventory
                             HAVING COUNT(*) > 1
                         )
                    THEN 'INVENTARIO AMS'
                    ELSE NULL
                END AS duplicate_reason
            FROM devices d
            LEFT JOIN destinations dest ON d.destination_id = dest.id
            LEFT JOIN customers c ON dest.customer_id = c.id
            WHERE d.is_deleted = 0
              AND (
                    (d.serial_number IS NOT NULL 
                     AND TRIM(d.serial_number) <> ''
                     AND d.serial_number IN (
                         SELECT serial_number
                         FROM devices
                         WHERE is_deleted = 0
                           AND serial_number IS NOT NULL
                           AND TRIM(serial_number) <> ''
                         GROUP BY serial_number
                         HAVING COUNT(*) > 1
                     )
                    )
                    OR
                    (d.customer_inventory IS NOT NULL 
                     AND TRIM(d.customer_inventory) <> ''
                     AND d.customer_inventory IN (
                         SELECT customer_inventory
                         FROM devices
                         WHERE is_deleted = 0
                           AND customer_inventory IS NOT NULL
                           AND TRIM(customer_inventory) <> ''
                         GROUP BY customer_inventory
                         HAVING COUNT(*) > 1
                     )
                    )
                    OR
                    (d.ams_inventory IS NOT NULL 
                     AND TRIM(d.ams_inventory) <> ''
                     AND d.ams_inventory IN (
                         SELECT ams_inventory
                         FROM devices
                         WHERE is_deleted = 0
                           AND ams_inventory IS NOT NULL
                           AND TRIM(ams_inventory) <> ''
                         GROUP BY ams_inventory
                         HAVING COUNT(*) > 1
                     )
                    )
                  )
            ORDER BY 
                COALESCE(UPPER(TRIM(d.serial_number)), ''),
                COALESCE(UPPER(TRIM(d.customer_inventory)), ''),
                COALESCE(UPPER(TRIM(d.ams_inventory)), ''),
                c.name,
                dest.name,
                d.description
            """
        ).fetchall()
        return rows

def get_duplicate_devices_by_characteristics():
    """
    Restituisce gruppi di dispositivi che condividono stessa descrizione,
    costruttore e modello nella stessa destinazione (possibili doppioni).
    """
    with DatabaseConnection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT d.*, dest.name AS destination_name, c.name AS customer_name
            FROM devices d
            LEFT JOIN destinations dest ON d.destination_id = dest.id
            LEFT JOIN customers c ON dest.customer_id = c.id
            WHERE d.is_deleted = 0
              AND d.destination_id IS NOT NULL
              AND d.id IN (
                    SELECT id
                    FROM (
                        SELECT d2.id,
                               UPPER(TRIM(COALESCE(d2.description,''))) AS desc_key,
                               UPPER(TRIM(COALESCE(d2.manufacturer,''))) AS mfg_key,
                               UPPER(TRIM(COALESCE(d2.model,''))) AS model_key,
                               d2.destination_id,
                               COUNT(*) OVER (
                                   PARTITION BY 
                                       UPPER(TRIM(COALESCE(d2.description,''))),
                                       UPPER(TRIM(COALESCE(d2.manufacturer,''))),
                                       UPPER(TRIM(COALESCE(d2.model,''))),
                                       d2.destination_id
                               ) AS grp_cnt
                        FROM devices d2
                        WHERE d2.is_deleted = 0
                    )
                    WHERE grp_cnt > 1
              )
            ORDER BY customer_name, destination_name,
                     UPPER(TRIM(COALESCE(description,''))),
                     UPPER(TRIM(COALESCE(manufacturer,''))),
                     UPPER(TRIM(COALESCE(model,'')))
            """
        ).fetchall()
        return rows

def get_device_data_quality_issues():
    """
    Analizza i dispositivi e restituisce una lista di problemi di qualità dati,
    ad es. campi obbligatori mancanti o incoerenti.
    """
    issues = []
    with DatabaseConnection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT d.*, dest.name AS destination_name, c.name AS customer_name
            FROM devices d
            LEFT JOIN destinations dest ON d.destination_id = dest.id
            LEFT JOIN customers c ON dest.customer_id = c.id
            WHERE d.is_deleted = 0
            """
        ).fetchall()

        for row in rows:
            r = dict(row)
            dev_id = r.get("id")
            cust = r.get("customer_name") or "—"
            dest = r.get("destination_name") or "—"
            base_info = {
                "device_id": dev_id,
                "customer_name": cust,
                "destination_name": dest,
                "description": r.get("description") or "",
                "serial_number": r.get("serial_number") or "",
                "manufacturer": r.get("manufacturer") or "",
                "model": r.get("model") or "",
            }

            desc = (r.get("description") or "").strip()
            serial = (r.get("serial_number") or "").strip()
            mfg = (r.get("manufacturer") or "").strip()
            model = (r.get("model") or "").strip()

            if not desc:
                issues.append({
                    **base_info,
                    "issue_code": "missing_description",
                    "issue_message": "Descrizione mancante"
                })
            if not serial:
                issues.append({
                    **base_info,
                    "issue_code": "missing_serial",
                    "issue_message": "Numero di serie mancante"
                })
            if not mfg:
                issues.append({
                    **base_info,
                    "issue_code": "missing_manufacturer",
                    "issue_message": "Costruttore mancante"
                })
            if not model:
                issues.append({
                    **base_info,
                    "issue_code": "missing_model",
                    "issue_message": "Modello mancante"
                })

            # NB: su richiesta, NON controlliamo più profili di verifica
            #     né intervallo di verifica tra i problemi di qualità dati.

    return issues

def get_customer_by_id(customer_id):
    with DatabaseConnection() as conn:
        return conn.execute("SELECT * FROM customers WHERE id = ? AND is_deleted = 0", (customer_id,)).fetchone()
    
def get_signature_by_username(username: str):
    """
    Recupera i dati binari (BLOB) di una firma dal database locale.
    Restituisce i dati dell'immagine o None se non trovata.
    """
    if not username:
        return None
    with DatabaseConnection() as conn:
        row = conn.execute(
            "SELECT signature_data FROM signatures WHERE username = ?",
            (username,)
        ).fetchone()

    return row['signature_data'] if row and row['signature_data'] else None

# --- Gestione Verifiche (Verifications) ---

def generate_verification_code(
    conn,
    verification_date: str,
    technician_name: str = "",
    technician_username: str = "",
    suffix: str = "VE",
    table_name: str = "verifications",
) -> str:
    """
    Genera un codice univoco per verifica: INIZIALI-AAMMGG-NNNN-SUFFISSO.
    Il progressivo si resetta ogni giorno per iniziali/tecnico.
    Esempio: EM-240731-0001-VE
    """
    def _initials_from(name: str) -> str:
        name = (name or "").strip()
        if not name and technician_username:
            return technician_username[:2].upper()
        parts = name.split()
        if len(parts) >= 2 and parts[0] and parts[1]:
            return (parts[0][0] + parts[1][0]).upper() # Mario Rossi -> MR
        if len(parts) == 1 and len(parts[0]) >= 2:
            return parts[0][:2].upper() # Mario -> MA
        return "XX"

    initials = _initials_from(technician_name)
    
    # Converte la data YYYY-MM-DD in AAMMGG
    try:
        date_obj = datetime.strptime(verification_date, '%Y-%m-%d')
        date_prefix = date_obj.strftime('%y%m%d')
    except (ValueError, TypeError):
        # Fallback nel caso la data non sia valida
        date_prefix = datetime.now().strftime('%y%m%d')

    # Il prefisso completo ora include iniziali e data
    full_prefix = f"{initials}-{date_prefix}-"
    suffix = (suffix or "").strip().upper()
    pattern_suffix = f"-{suffix}" if suffix else ""

    query = f"""
        SELECT verification_code
        FROM {table_name}
        WHERE verification_code LIKE ?
        ORDER BY verification_code DESC
        LIMIT 1;
    """
    like_pattern = f"{full_prefix}%{suffix}"
    cur = conn.execute(query, (like_pattern,))
    row = cur.fetchone()

    if row and row[0]:
        try:
            existing_code = row[0]
            core_part = existing_code[len(full_prefix):]
            if suffix and core_part.endswith(pattern_suffix):
                core_part = core_part[: -len(pattern_suffix)]
            # Rimuove eventuale trattino residuo
            core_part = core_part.rstrip("-")
            last_num = int(core_part)
        except Exception:
            last_num = 0
        new_num = last_num + 1
    else:
        new_num = 1

    if suffix:
        return f"{full_prefix}{new_num:04d}-{suffix}"
    return f"{full_prefix}{new_num:04d}"


def save_verification(uuid, device_id, profile_name, results, overall_status,
                      visual_inspection_data, mti_info,
                      technician_name, technician_username,
                      timestamp, verification_date=None,
                      verification_code: str = None):
    if verification_date is None:
        verification_date = datetime.now().strftime('%Y-%m-%d')

    results_json = json.dumps(results)
    visual_json = json.dumps(visual_inspection_data)
    mti_data = mti_info if isinstance(mti_info, dict) else {}

    with DatabaseConnection() as conn:
        cursor = conn.cursor()

        # Se non passato, generiamo qui il codice
        if not verification_code:
            verification_code = generate_verification_code(
                conn,
                verification_date,
                technician_name,
                technician_username,
                suffix="VE",
                table_name="verifications",
            )

        sql_query = """
            INSERT INTO verifications (
                uuid, device_id, verification_date, profile_name,
                results_json, overall_status, visual_inspection_json,
                mti_instrument, mti_serial, mti_version, mti_cal_date,
                technician_name, technician_username,
                verification_code,
                last_modified, is_deleted, is_synced
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """

        params = (
            uuid, device_id, verification_date, profile_name,
            results_json, overall_status, visual_json,
            mti_data.get('instrument'),
            mti_data.get('serial'),
            mti_data.get('version'),
            mti_data.get('cal_date'),
            technician_name, technician_username,
            verification_code,
            timestamp
        )
        cursor.execute(sql_query, params)
        new_id = cursor.lastrowid
        return verification_code, new_id

def verification_exists(device_id: int, verification_date: str, profile_name: str) -> bool:
    """Verifica se esiste già una verifica per dispositivo/data/profilo."""
    with DatabaseConnection() as conn:
        result = conn.execute(
            "SELECT id FROM verifications WHERE device_id = ? AND verification_date = ? AND profile_name = ? AND is_deleted = 0",
            (device_id, verification_date, profile_name)
        ).fetchone()
        return result is not None

def get_verifications_for_destination_by_date_range(destination_id: int, start_date: str, end_date: str) -> list:
    """
    Recupera tutte le verifiche per una specifica destinazione eseguite in un dato intervallo di date.
    Include tutti i campi del dispositivo necessari per la generazione dei report.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT v.*, 
                   d.serial_number, d.ams_inventory, d.customer_inventory,
                   d.description, d.manufacturer, d.model, d.department,
                   dest.name as destination_name
            FROM verifications v
            JOIN devices d ON v.device_id = d.id
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE v.is_deleted = 0 AND d.is_deleted = 0
            AND d.destination_id = ?
            AND v.verification_date BETWEEN ? AND ?
            ORDER BY d.description, v.verification_date;
        """
        return conn.execute(query, (destination_id, start_date, end_date)).fetchall()

def get_verifications_by_date_range(start_date: str, end_date: str) -> list:
    """
    Recupera tutte le verifiche eseguite in un dato intervallo di date (tutto il database).
    Include tutti i campi del dispositivo necessari per la generazione dei report.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT v.*, 
                   d.serial_number, d.ams_inventory, d.customer_inventory,
                   d.description, d.manufacturer, d.model, d.department,
                   dest.name as destination_name
            FROM verifications v
            JOIN devices d ON v.device_id = d.id
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE v.is_deleted = 0 AND d.is_deleted = 0
            AND v.verification_date BETWEEN ? AND ?
            ORDER BY d.description, v.verification_date;
        """
        return conn.execute(query, (start_date, end_date)).fetchall()

def get_verifications_for_customer_by_date_range(customer_id: int, start_date: str, end_date: str) -> list:
    """
    Recupera tutte le verifiche per un cliente in un dato intervallo di date.
    Include tutti i campi del dispositivo necessari per la generazione dei report.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT v.*, 
                   d.serial_number, d.ams_inventory, d.customer_inventory,
                   d.description, d.manufacturer, d.model, d.department,
                   dest.name as destination_name
            FROM verifications v
            JOIN devices d ON v.device_id = d.id
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE v.is_deleted = 0 AND d.is_deleted = 0
            AND dest.customer_id = ?
            AND v.verification_date BETWEEN ? AND ?
            ORDER BY d.description, v.verification_date;
        """
        return conn.execute(query, (customer_id, start_date, end_date)).fetchall()

def get_full_verification_data_for_date(target_date: str) -> dict:
    """
    Recupera tutte le verifiche di una data specifica per l'export STM,
    usando la nuova struttura a destinazioni.
    """
    from datetime import datetime
    with DatabaseConnection() as conn:
        # --- UPDATED QUERY ---
        # We now use a double JOIN to get from the device to the customer
        query = """
            SELECT v.*, d.serial_number, d.description, d.manufacturer, d.model,
                   d.applied_parts_json, d.customer_inventory, d.ams_inventory,
                   c.name as customer_name, c.address as customer_address
            FROM verifications v
            JOIN devices d ON v.device_id = d.id
            JOIN destinations dest ON d.destination_id = dest.id
            JOIN customers c ON dest.customer_id = c.id
            WHERE v.verification_date = ? AND v.is_deleted = 0
            ORDER BY c.name, d.description
        """
        rows = conn.execute(query, (target_date,)).fetchall()

    export_structure = {"export_format_version": "1.0", "export_creation_date": datetime.now().isoformat(), "verifications_for_date": target_date, "verifications": []}
    for row_proxy in rows:
        row = dict(row_proxy)
        export_structure["verifications"].append({
            "customer": {"name": row["customer_name"], "address": row["customer_address"]},
            "device": {"serial_number": row["serial_number"], "description": row["description"], "manufacturer": row["manufacturer"], "model": row["model"], "applied_parts_json": row["applied_parts_json"], "customer_inventory": row["customer_inventory"], "ams_inventory": row["ams_inventory"]},
            "verification_details": {
                "verification_date": row["verification_date"], 
                "profile_name": row["profile_name"], 
                "results_json": row["results_json"], 
                "overall_status": row["overall_status"], 
                "visual_inspection_json": row["visual_inspection_json"], 
                "technician_name": row.get("technician_name"),
                "technician_username": row.get("technician_username"),
                "verification_code": row.get("verification_code"),
                "mti_info": {
                    "instrument": row["mti_instrument"], 
                    "serial": row["mti_serial"], 
                    "version": row["mti_version"], 
                    "cal_date": row["mti_cal_date"]
                }
            }
        })
    return export_structure

def update_verification(verification_id: int, verification_date: str, overall_status: str,
                        technician_name: str, timestamp: str, *,
                        results: list | None = None,
                        visual_inspection_data: dict | None = None,
                        mti_instrument: str | None = None,
                        mti_serial: str | None = None,
                        mti_version: str | None = None,
                        mti_cal_date: str | None = None) -> bool:
    """Aggiorna tutti i campi modificabili di una verifica elettrica."""
    sets = [
        "verification_date = ?", "overall_status = ?",
        "technician_name = ?", "last_modified = ?", "is_synced = 0",
    ]
    params: list = [verification_date, overall_status, technician_name, timestamp]

    if results is not None:
        sets.append("results_json = ?")
        params.append(json.dumps(results))
    if visual_inspection_data is not None:
        sets.append("visual_inspection_json = ?")
        params.append(json.dumps(visual_inspection_data))
    if mti_instrument is not None:
        sets.append("mti_instrument = ?")
        params.append(mti_instrument)
    if mti_serial is not None:
        sets.append("mti_serial = ?")
        params.append(mti_serial)
    if mti_version is not None:
        sets.append("mti_version = ?")
        params.append(mti_version)
    if mti_cal_date is not None:
        sets.append("mti_cal_date = ?")
        params.append(mti_cal_date)

    params.append(verification_id)
    with DatabaseConnection() as conn:
        cursor = conn.execute(
            f"UPDATE verifications SET {', '.join(sets)} WHERE id = ? AND is_deleted = 0",
            tuple(params),
        )
    if cursor.rowcount > 0:
        logging.info(f"Verifica elettrica ID {verification_id} aggiornata.")
        return True
    return False


def soft_delete_verification(verification_id, timestamp):
    """Esegue un 'soft delete' di una singola verifica."""
    with DatabaseConnection() as conn:
        cursor = conn.execute(
            "UPDATE verifications SET is_deleted=1, last_modified=?, is_synced=0 WHERE id=?",
            (timestamp, verification_id)
        )
    if cursor.rowcount > 0:
        logging.warning(f"Verifica ID {verification_id} marcata come eliminata.")
        return True
    return False

def get_verifications_for_device(device_id: int, search_query: str = None):
    with DatabaseConnection() as conn:
        query = "SELECT * FROM verifications WHERE device_id = ? AND is_deleted = 0"
        params = [device_id]
        if search_query:
            query += " AND (verification_date LIKE ? OR technician_name LIKE ? OR verification_code LIKE ?)"
            like_term = f"%{search_query}%"
            params.extend([like_term] * 3)
        
        query += " ORDER BY verification_date DESC"
        rows = conn.execute(query, tuple(params)).fetchall()
    return [_decode_json_fields(r, ['results_json', 'visual_inspection_json']) for r in rows]


def get_verification_with_device_info(verification_id: int):
    """Recupera una verifica elettrica con contesto completo del dispositivo."""
    with DatabaseConnection() as conn:
        return conn.execute(
            """
            SELECT
                v.id,
                v.device_id,
                v.verification_code,
                v.verification_date,
                v.overall_status,
                v.profile_name,
                v.technician_name,
                v.technician_username,
                d.description,
                d.serial_number,
                d.manufacturer,
                d.model,
                d.customer_inventory,
                d.ams_inventory,
                d.destination_id,
                dest.name AS destination_name,
                dest.customer_id,
                c.name AS customer_name
            FROM verifications v
            LEFT JOIN devices d ON v.device_id = d.id
            LEFT JOIN destinations dest ON d.destination_id = dest.id
            LEFT JOIN customers c ON dest.customer_id = c.id
            WHERE v.id = ?
            LIMIT 1
            """,
            (verification_id,),
        ).fetchone()

def get_verifications_for_destination_by_month(destination_id: int, year: int, month: int) -> list:
    """
    Recupera tutte le verifiche per una specifica destinazione eseguite in un dato mese e anno.
    """
    month_str = f"{month:02d}"
    year_str = str(year)
    
    with DatabaseConnection() as conn:
        query = """
            SELECT v.*, d.serial_number, d.ams_inventory
            FROM verifications v
            JOIN devices d ON v.device_id = d.id
            WHERE v.is_deleted = 0 AND d.is_deleted = 0
            AND strftime('%Y', v.verification_date) = ?
            AND strftime('%m', v.verification_date) = ?
            AND d.destination_id = ?
            ORDER BY d.description, v.verification_date;
        """
        return conn.execute(query, (year_str, month_str, destination_id)).fetchall()

def update_device_next_verification_date(device_id, interval_months, timestamp):
    from dateutil.relativedelta import relativedelta
    next_date = datetime.now() + relativedelta(months=int(interval_months))
    next_date_str = next_date.strftime('%Y-%m-%d')
    with DatabaseConnection() as conn:
        conn.execute("UPDATE devices SET next_verification_date = ?, last_modified = ?, is_synced = 0 WHERE id = ?", (next_date_str, timestamp, device_id))

def get_devices_with_last_verification():
    """
    Recupera tutti i dispositivi dal database, arricchiti con la data
    e l'esito della loro ultima verifica (elettrica o funzionale).
    Se ci sono verifiche nello stesso giorno, dà priorità a quella con esito peggiore.
    """
    # Approccio in due passi:
    # 1. Trova la data più recente per ogni dispositivo (da entrambe le tabelle)
    # 2. Tra tutte le verifiche con quella data, scegli quella con esito peggiore
    query = """
    WITH all_verifications AS (
        -- Verifiche elettriche
        SELECT 
            device_id,
            verification_date,
            overall_status,
            id,
            'electrical' AS verification_type
        FROM verifications
        WHERE is_deleted = 0
        
        UNION ALL
        
        -- Verifiche funzionali
        SELECT 
            device_id,
            verification_date,
            overall_status,
            id,
            'functional' AS verification_type
        FROM functional_verifications
        WHERE is_deleted = 0
    ),
    max_dates AS (
        -- Trova la data più recente per ogni dispositivo
        SELECT 
            device_id,
            MAX(verification_date) AS max_date
        FROM all_verifications
        GROUP BY device_id
    ),
    worst_outcome_at_max_date AS (
        -- Tra tutte le verifiche con la data più recente, scegli quella con esito peggiore
        SELECT 
            av.device_id,
            av.verification_date,
            av.overall_status,
            av.verification_type,
            ROW_NUMBER() OVER (
                PARTITION BY av.device_id 
                ORDER BY 
                    CASE 
                        WHEN av.overall_status IN ('FALLITO', 'NON CONFORME', 'CONFORME CON ANNOTAZIONE') THEN 1
                        WHEN av.overall_status IN ('PASSATO', 'CONFORME') THEN 2
                        ELSE 3
                    END,
                    av.id DESC
            ) as rn
        FROM all_verifications av
        INNER JOIN max_dates md ON av.device_id = md.device_id AND av.verification_date = md.max_date
    )
    SELECT
        d.*,
        wom.verification_date AS last_verification_date,
        wom.overall_status AS last_verification_outcome
    FROM
        devices d
    LEFT JOIN worst_outcome_at_max_date wom ON wom.device_id = d.id AND wom.rn = 1
    WHERE 
        d.is_deleted = 0
    ORDER BY
        d.id DESC;
    """
    with DatabaseConnection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        results = [dict(row) for row in rows]
        
        # Log per debug: verifica alcuni dispositivi con verifiche
        for result in results[:5]:  # Solo i primi 5 per non intasare i log
            if result.get('last_verification_outcome'):
                logging.debug(
                    f"Device {result.get('id')} ({result.get('description')}): "
                    f"last_verification_outcome={result.get('last_verification_outcome')}, "
                    f"date={result.get('last_verification_date')}"
                )
        
        return results


def get_devices_verification_status_by_period(destination_id: int, start_date: str, end_date: str):
    """
    Recupera tutti i dispositivi di una specifica destinazione e controlla il loro
    stato di verifica in un dato intervallo di date.
    """
    with DatabaseConnection() as conn:
        # 1. Recupera tutti i dispositivi attivi della destinazione selezionata
        all_devices_query = "SELECT id, description, serial_number, model FROM devices WHERE destination_id = ? AND is_deleted = 0 ORDER BY description"
        all_devices = conn.execute(all_devices_query, (destination_id,)).fetchall()

        # 2. Recupera gli ID dei dispositivi di QUESTA destinazione che sono stati verificati nel periodo
        verified_devices_query = """
            SELECT DISTINCT device_id FROM verifications
            WHERE device_id IN (SELECT id FROM devices WHERE destination_id = ?)
            AND verification_date BETWEEN ? AND ?
            AND is_deleted = 0
        """
        verified_ids_cursor = conn.execute(verified_devices_query, (destination_id, start_date, end_date))
        verified_ids = {row['device_id'] for row in verified_ids_cursor}

    verified_list = []
    unverified_list = []

    for device_row in all_devices:
        device_dict = dict(device_row)
        if device_dict['id'] in verified_ids:
            verified_list.append(device_dict)
        else:
            unverified_list.append(device_dict)

    return verified_list, unverified_list

def get_all_devices_for_customer(customer_id: int, search_query=None):
    """
    Recupera TUTTI i dispositivi di un cliente, da tutte le sue destinazioni.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT d.* FROM devices d
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE dest.customer_id = ? AND d.is_deleted = 0
        """
        params = [customer_id]
        if search_query:
            query += " AND (d.description LIKE ? OR d.serial_number LIKE ? OR d.model LIKE ?)"
            params.extend([f"%{search_query}%"] * 3)
        query += " ORDER BY d.description"
        return conn.execute(query, params).fetchall()

def get_unverified_devices_for_destination_in_period(destination_id: int, start_date: str, end_date: str):
    """
    Returns a list of devices for a specific destination that have NOT had
    a verification within the specified period.
    """
    with DatabaseConnection() as conn:
        # First, find the IDs of devices in this destination that WERE verified in the period
        verified_devices_query = """
            SELECT DISTINCT device_id FROM verifications
            WHERE device_id IN (SELECT id FROM devices WHERE destination_id = ?)
            AND verification_date BETWEEN ? AND ?
            AND is_deleted = 0
        """
        verified_ids_cursor = conn.execute(verified_devices_query, (destination_id, start_date, end_date))
        verified_ids = {row['device_id'] for row in verified_ids_cursor}

        # Now, get all devices from this destination that are NOT in the verified list
        # We need to handle the case where verified_ids is empty
        if not verified_ids:
            unverified_devices_query = "SELECT * FROM devices WHERE destination_id = ? AND is_deleted = 0 ORDER BY description"
            params = (destination_id,)
        else:
            # Create a string of placeholders for the IN clause
            placeholders = ', '.join('?' for _ in verified_ids)
            unverified_devices_query = f"""
                SELECT * FROM devices
                WHERE destination_id = ?
                AND is_deleted = 0
                AND id NOT IN ({placeholders})
                ORDER BY description
            """
            params = (destination_id, *verified_ids)

        return conn.execute(unverified_devices_query, params).fetchall()

# --- Gestione Strumenti (Instruments) ---

def get_all_instruments(instrument_type: str = None):
    """
    Recupera tutti gli strumenti, opzionalmente filtrati per tipo.
    
    Args:
        instrument_type: 'electrical' per strumenti elettrici, 'functional' per strumenti funzionali, None per tutti
    """
    with DatabaseConnection() as conn:
        if instrument_type:
            # Verifica se la colonna instrument_type esiste
            try:
                return conn.execute(
                    "SELECT * FROM mti_instruments WHERE is_deleted = 0 AND instrument_type = ? ORDER BY instrument_name",
                    (instrument_type,)
                ).fetchall()
            except sqlite3.OperationalError:
                # Se la colonna non esiste, restituisci tutti gli strumenti (comportamento legacy)
                return conn.execute("SELECT * FROM mti_instruments WHERE is_deleted = 0 ORDER BY instrument_name").fetchall()
        else:
            return conn.execute("SELECT * FROM mti_instruments WHERE is_deleted = 0 ORDER BY instrument_name").fetchall()

def add_instrument(uuid: str, name: str, serial: str, fw: str, 
                   cal_date: str, timestamp: str, instrument_type: str = 'electrical'):
    """Add a new instrument to the database."""
    with DatabaseConnection() as conn:
        # Verifica se la colonna instrument_type esiste
        try:
            conn.execute(
                """INSERT INTO mti_instruments 
                   (uuid, instrument_name, serial_number, fw_version, 
                    calibration_date, instrument_type, last_modified, is_synced) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (uuid, name, serial, fw, cal_date, instrument_type, timestamp)
            )
        except sqlite3.OperationalError:
            # Se la colonna non esiste, usa la query senza instrument_type
            conn.execute(
                """INSERT INTO mti_instruments 
                   (uuid, instrument_name, serial_number, fw_version, 
                    calibration_date, last_modified, is_synced) 
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (uuid, name, serial, fw, cal_date, timestamp)
            )
        conn.commit()

def update_instrument(inst_id, name, serial, fw, cal_date, timestamp, instrument_type: str = None, com_port: str = None):
    """Update an instrument in the database.
    
    Args:
        inst_id: Instrument ID
        name: Instrument name
        serial: Serial number
        fw: Firmware version
        cal_date: Calibration date
        timestamp: Last modified timestamp
        instrument_type: Optional instrument type ('electrical' or 'functional')
        com_port: Optional COM port (not used in update, kept for backward compatibility)
    """
    with DatabaseConnection() as conn:
        # Verifica se la colonna instrument_type esiste
        try:
            if instrument_type is not None:
                conn.execute(
                    "UPDATE mti_instruments SET instrument_name=?, serial_number=?, fw_version=?, calibration_date=?, instrument_type=?, last_modified=?, is_synced=0 WHERE id=?",
                    (name, serial, fw, cal_date, instrument_type, timestamp, inst_id)
                )
            else:
                conn.execute(
                    "UPDATE mti_instruments SET instrument_name=?, serial_number=?, fw_version=?, calibration_date=?, last_modified=?, is_synced=0 WHERE id=?",
                    (name, serial, fw, cal_date, timestamp, inst_id)
                )
        except sqlite3.OperationalError:
            # Se la colonna non esiste, usa la query senza instrument_type
            conn.execute(
                "UPDATE mti_instruments SET instrument_name=?, serial_number=?, fw_version=?, calibration_date=?, last_modified=?, is_synced=0 WHERE id=?",
                (name, serial, fw, cal_date, timestamp, inst_id)
            )

def soft_delete_instrument(inst_id, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("UPDATE mti_instruments SET is_deleted=1, last_modified=?, is_synced=0 WHERE id=?", (timestamp, inst_id))

def set_default_instrument(inst_id, timestamp):
    with DatabaseConnection() as conn:
        conn.execute("UPDATE mti_instruments SET is_default = 0, last_modified=?, is_synced=0", (timestamp,))
        conn.execute("UPDATE mti_instruments SET is_default = 1, last_modified=?, is_synced=0 WHERE id = ?", (timestamp, inst_id))

def get_instruments_needing_calibration(days_in_future=30):
    """Recupera gli strumenti di misura ATTIVI con calibrazione scaduta o in scadenza.
    
    La scadenza è calcolata aggiungendo 1 anno alla data di calibrazione.
    """
    from datetime import date, timedelta
    from dateutil.relativedelta import relativedelta
    
    today = date.today()
    future_date = today + timedelta(days=days_in_future)
    
    with DatabaseConnection() as conn:
        # Recupera tutti gli strumenti con data di calibrazione
        all_instruments = conn.execute("""
            SELECT * 
            FROM mti_instruments
            WHERE calibration_date IS NOT NULL 
            AND calibration_date != ''
            AND is_deleted = 0
        """).fetchall()
        
        # Filtra quelli con scadenza entro i prossimi giorni
        expiring_instruments = []
        for inst_row in all_instruments:
            inst_dict = dict(inst_row)
            cal_date_str = inst_dict.get('calibration_date')
            
            if not cal_date_str:
                continue
            
            try:
                # Prova diversi formati di data
                cal_date = None
                cal_date_str_clean = cal_date_str.strip()
                
                # Prova formato YYYY-MM-DD
                try:
                    cal_date = datetime.strptime(cal_date_str_clean, '%Y-%m-%d').date()
                except ValueError:
                    # Prova formato DD/MM/YYYY
                    try:
                        cal_date = datetime.strptime(cal_date_str_clean, '%d/%m/%Y').date()
                    except ValueError:
                        # Prova formato DD-MM-YYYY
                        try:
                            cal_date = datetime.strptime(cal_date_str_clean, '%d-%m-%Y').date()
                        except ValueError:
                            # Prova formato YYYY/MM/DD
                            try:
                                cal_date = datetime.strptime(cal_date_str_clean, '%Y/%m/%d').date()
                            except ValueError:
                                logging.warning(f"Formato data non riconosciuto per strumento {inst_dict.get('id')}: {cal_date_str}")
                                continue
                
                if cal_date:
                    # Calcola la data di scadenza (1 anno dopo la calibrazione)
                    expiration_date = cal_date + relativedelta(years=1)
                    
                    # Debug logging
                    logging.debug(f"Strumento {inst_dict.get('id')} ({inst_dict.get('instrument_name')}): calibrazione={cal_date}, scadenza={expiration_date}, oggi={today}, future_date={future_date}, giorni_rimanenti={(expiration_date - today).days}")
                    
                    # Controlla se la scadenza è entro i prossimi giorni (inclusi quelli già scaduti)
                    # Mostra se la scadenza è entro i prossimi 30 giorni o già scaduta
                    if expiration_date <= future_date:
                        # Aggiungi la data di scadenza calcolata al dizionario
                        inst_dict['expiration_date'] = expiration_date.strftime('%Y-%m-%d')
                        expiring_instruments.append(inst_dict)
                        logging.info(f"Strumento {inst_dict.get('id')} ({inst_dict.get('instrument_name')}) aggiunto alla lista scadenze: scade il {expiration_date}")
            except Exception as e:
                # Se il formato della data non è valido, salta questo strumento
                logging.warning(f"Errore parsing data di calibrazione per strumento {inst_dict.get('id')}: {cal_date_str}, errore: {e}")
                continue
        
        # Ordina per data di scadenza (più vicina prima)
        expiring_instruments.sort(key=lambda x: x.get('expiration_date', ''))
        
        return expiring_instruments

# --- Statistiche ---
def get_stats():
    with DatabaseConnection() as conn:
        try:
            device_count = conn.execute("SELECT COUNT(id) FROM devices WHERE is_deleted = 0").fetchone()[0]
            customer_count = conn.execute("SELECT COUNT(id) FROM customers WHERE is_deleted = 0").fetchone()[0]
            last_verif_date = conn.execute("SELECT MAX(verification_date) FROM verifications WHERE is_deleted = 0").fetchone()[0]
        except (TypeError, IndexError):
            return {"devices": 0, "customers": 0, "last_verif": "N/A"}
    return {"devices": device_count, "customers": customer_count, "last_verif": last_verif_date if last_verif_date else "Nessuna"}


def force_update_timestamp(table_name, uuid, timestamp):
    """Aggiorna solo il timestamp di un record e lo marca come non sincronizzato."""
    with DatabaseConnection() as conn:
        conn.execute(f"UPDATE {table_name} SET last_modified = ?, is_synced = 0 WHERE uuid = ?", (timestamp, uuid))


def resolve_device_serial_conflict_keep_local(conflict: dict, timestamp):
    """
    Gestione specifica del conflitto di numero di serie per la tabella devices
    quando l'utente sceglie di mantenere la versione LOCALE.

    Obiettivo: far sì che la versione locale del dispositivo diventi quella
    "vincente" anche sul server, in modo che tutti gli utenti vedano i dati locali.

    Strategia:
    - recuperiamo UUID locale (client) e UUID server dalla struttura di conflitto
    - cerchiamo nel DB locale le righe corrispondenti
    - se esiste già una riga con l'UUID del server, aggiorniamo quella riga
      con i dati locali e marchiamo come eliminata l'eventuale riga con l'UUID client
    - se NON esiste una riga con l'UUID del server, rinominiamo la riga locale
      (UUID client) usando l'UUID server
    - in entrambi i casi, impostiamo is_synced = 0 e last_modified = timestamp
      così al prossimo sync il server riceve un UPDATE per l'UUID già esistente.
    """
    client_version = conflict.get("client_version") or {}
    server_version = conflict.get("server_version") or {}

    client_uuid = client_version.get("uuid")
    server_uuid = server_version.get("uuid")

    if not client_uuid or not server_uuid:
        logging.error("resolve_device_serial_conflict_keep_local: UUID mancanti, impossibile procedere.")
        return

    with DatabaseConnection() as conn:
        conn.row_factory = sqlite3.Row

        # Recupera eventuali righe locali
        row_client = conn.execute(
            "SELECT * FROM devices WHERE uuid = ?", (client_uuid,)
        ).fetchone()
        row_server = conn.execute(
            "SELECT * FROM devices WHERE uuid = ?", (server_uuid,)
        ).fetchone()

        # Se non abbiamo neanche la riga locale, non possiamo fare molto
        if not row_client and not row_server:
            logging.warning("resolve_device_serial_conflict_keep_local: nessuna riga locale per client/server UUID.")
            return

        # Otteniamo l'elenco delle colonne valide per la tabella devices
        cols_info = conn.execute("PRAGMA table_info(devices)").fetchall()
        valid_cols = [
            (c["name"] if isinstance(c, sqlite3.Row) else c[1])
            for c in cols_info
        ]

        # Helper: costruisce un dict dati basato su client_version limitato alle colonne valide
        def _build_data_from_client():
            data = {}
            for k, v in client_version.items():
                if k in valid_cols and k not in ("id",):
                    data[k] = v
            # forza campi di stato per la sync
            data["last_modified"] = timestamp
            data["is_synced"] = 0
            data["is_deleted"] = 0
            return data

        if row_server:
            # Caso 1: esiste già localmente una riga con l'UUID del server.
            # Aggiorniamo QUELLA riga con i dati locali.
            data = _build_data_from_client()
            # Assicuriamoci di mantenere l'UUID del server
            data["uuid"] = server_uuid

            set_clause = ", ".join(f"{k} = ?" for k in data.keys())
            params = list(data.values()) + [server_uuid]

            conn.execute(
                f"UPDATE devices SET {set_clause} WHERE uuid = ?", params
            )

            # Se esiste anche una riga separata con l'UUID client, la marchiamo come eliminata
            if row_client and row_client["uuid"] != server_uuid:
                conn.execute(
                    """
                    UPDATE devices
                    SET is_deleted = 1, is_synced = 0, last_modified = ?
                    WHERE uuid = ?
                    """,
                    (timestamp, client_uuid),
                )

            logging.info(
                "Conflitto devices.serial_conflict risolto: dati locali applicati alla riga con UUID server."
            )
        else:
            # Caso 2: non esiste ancora localmente la riga con l'UUID del server.
            # Rinominiano la riga locale (client_uuid) usando server_uuid.
            data = _build_data_from_client()
            data["uuid"] = server_uuid

            set_clause = ", ".join(f"{k} = ?" for k in data.keys())
            params = list(data.values()) + [client_uuid]

            conn.execute(
                f"UPDATE devices SET {set_clause} WHERE uuid = ?", params
            )

            logging.info(
                "Conflitto devices.serial_conflict risolto: riga locale rinominata con UUID server."
            )


def get_suggested_profiles_for_device(manufacturer: str | None, model: str | None, description: str | None):
    """
    Suggerisce profili di verifica (elettrico + funzionale) sulla base
    dei dispositivi già presenti in archivio.

    Strategia:
    - prima prova con combinazione COSTRUTTORE + MODELLO
    - se non trova nulla, prova solo con la DESCRIZIONE
    Restituisce un dict con chiavi:
        {
          "default_profile_key": <str|None>,
          "default_functional_profile_key": <str|None>
        }
    """
    manu = (manufacturer or "").strip().upper()
    mod = (model or "").strip().upper()
    desc = (description or "").strip().upper()

    result = {
        "default_profile_key": None,
        "default_functional_profile_key": None,
    }

    with DatabaseConnection() as conn:
        conn.row_factory = sqlite3.Row

        # 1) COSTRUTTORE + MODELLO
        if manu and mod:
            row = conn.execute(
                """
                SELECT default_profile_key, default_functional_profile_key, COUNT(*) AS cnt
                FROM devices
                WHERE is_deleted = 0
                  AND COALESCE(TRIM(UPPER(manufacturer)),'') = ?
                  AND COALESCE(TRIM(UPPER(model)),'') = ?
                  AND (default_profile_key IS NOT NULL OR default_functional_profile_key IS NOT NULL)
                GROUP BY default_profile_key, default_functional_profile_key
                ORDER BY cnt DESC
                LIMIT 1
                """,
                (manu, mod),
            ).fetchone()
            if row:
                result["default_profile_key"] = row["default_profile_key"]
                result["default_functional_profile_key"] = row["default_functional_profile_key"]
                return result

        # 2) DESCRIZIONE (come fallback)
        if desc:
            row = conn.execute(
                """
                SELECT default_profile_key, default_functional_profile_key, COUNT(*) AS cnt
                FROM devices
                WHERE is_deleted = 0
                  AND COALESCE(TRIM(UPPER(description)),'') = ?
                  AND (default_profile_key IS NOT NULL OR default_functional_profile_key IS NOT NULL)
                GROUP BY default_profile_key, default_functional_profile_key
                ORDER BY cnt DESC
                LIMIT 1
                """,
                (desc,),
            ).fetchone()
            if row:
                result["default_profile_key"] = row["default_profile_key"]
                result["default_functional_profile_key"] = row["default_functional_profile_key"]

    return result

def overwrite_local_record(table_name: str, record_data: dict, is_conflict_resolution: bool = False):
    """
    Sovrascrive (o inserisce) un record locale con la versione fornita dal server.
    Questa funzione è dinamica e funziona per qualsiasi tabella.
    
    Args:
        table_name: Nome della tabella
        record_data: Dati del record da inserire/aggiornare
        is_conflict_resolution: Se True, salta il controllo dei duplicati di serial_number
                               (usato quando si risolve un conflitto e il record ha UUID diverso)
    
    NOTA: Disabilita temporaneamente i vincoli di chiave estera poiché il server
    potrebbe inviare record con riferimenti a tabelle correlate che non sono state
    ancora sincronizzate localmente.
    """
    with DatabaseConnection() as conn:
        # Rimuoviamo l'ID numerico locale, non ci serve. L'UUID è la nostra chiave.
        record_data.pop('id', None)

        # Assicuriamoci che il record sia marcato come sincronizzato
        record_data['is_synced'] = 1

        # Gestione speciale per la tabella devices in caso di conflitti sul numero di serie:
        # se esiste già in locale un altro dispositivo ATTIVO con lo stesso serial_number
        # ma UUID diverso, lo marchiamo come eliminato prima di applicare la versione server.
        if table_name == "devices":
            serial = record_data.get("serial_number")
            uuid_value = record_data.get("uuid")
            if serial and uuid_value:
                try:
                    existing = conn.execute(
                        """
                        SELECT id, uuid
                        FROM devices
                        WHERE serial_number = ?
                          AND uuid <> ?
                          AND is_deleted = 0
                        """,
                        (serial, uuid_value),
                    ).fetchone()
                    if existing:
                        logging.warning(
                            "overwrite_local_record: trovato dispositivo locale con stesso "
                            "numero di serie ma UUID diverso (id=%s, uuid=%s). "
                            "Lo marco come eliminato per applicare la versione server.",
                            existing["id"],
                            existing["uuid"],
                        )
                        ts = record_data.get("last_modified")
                        if not ts:
                            from datetime import datetime, timezone
                            ts = datetime.now(timezone.utc).isoformat()
                        conn.execute(
                            """
                            UPDATE devices
                            SET is_deleted = 1, last_modified = ?
                            WHERE id = ?
                            """,
                            (ts, existing["id"]),
                        )
                except Exception as e:
                    logging.error(
                        "Errore durante il controllo dei duplicati di serial_number "
                        "in overwrite_local_record per devices: %s",
                        e,
                        exc_info=True,
                    )

        # Filtra le colonne: mantieni solo quelle che esistono nella tabella locale.
        # I dati dal server (specie PUSH conflicts) possono contenere colonne extra
        # (es. customer_uuid, destination_uuid) che non esistono nella tabella SQLite.
        cursor = conn.execute(f'PRAGMA table_info("{table_name}")')
        valid_columns = {row[1] for row in cursor.fetchall()}
        # Rimuovi dal dict i campi che non esistono nella tabella locale
        invalid_keys = [k for k in record_data if k not in valid_columns]
        for k in invalid_keys:
            record_data.pop(k)
        if invalid_keys:
            logging.debug(f"overwrite_local_record: rimossi campi non validi per '{table_name}': {invalid_keys}")

        if 'uuid' not in record_data:
            logging.error(f"overwrite_local_record: nessun campo 'uuid' nel record per '{table_name}' dopo il filtraggio")
            return  # Senza UUID non possiamo fare UPSERT

        # Prepara le parti della query dinamicamente
        columns = record_data.keys()
        # Quota i nomi delle colonne per evitare conflitti con parole riservate SQL
        columns_str = ", ".join([f'"{col}"' for col in columns])
        placeholders_str = ", ".join(["?"] * len(columns))

        # Prepara la parte di UPDATE in caso di conflitto sull'UUID
        # "excluded" è una parola chiave di SQLite per riferirsi ai valori che si stavano per inserire
        update_clause = ", ".join([f'"{col}" = excluded."{col}"' for col in columns if col != 'uuid'])

        # Componi la query UPSERT completa - quota anche il nome della tabella
        query = f"""
            INSERT INTO "{table_name}" ({columns_str})
            VALUES ({placeholders_str})
            ON CONFLICT(uuid) DO UPDATE SET {update_clause};
        """

        # Prepara i parametri nell'ordine corretto
        params = tuple(record_data[col] for col in columns)

        try:
            # === IMPORTANTE: Differisce i vincoli FK alla fine della transazione ===
            # PRAGMA foreign_keys=OFF è ignorato dentro una transazione attiva in SQLite.
            # defer_foreign_keys=ON funziona dentro una transazione: i vincoli FK vengono
            # verificati al COMMIT invece che al momento dell'INSERT/UPDATE, evitando
            # errori quando il record padre non è ancora stato sincronizzato.
            conn.execute("PRAGMA defer_foreign_keys=ON")
            
            conn.execute(query, params)
            logging.info(f"Record {record_data['uuid']} nella tabella '{table_name}' sovrascritto con la versione del server.")
        except Exception as e:
            logging.error(f"Fallimento UPSERT per record {record_data['uuid']} in '{table_name}'", exc_info=True)
            raise e
# ==============================================================================
# SEZIONE 4: GESTORE PROFILI DI VERIFICA
# ==============================================================================

def get_all_profiles_from_db():
    """
    Legge i profili e i test dal database locale e li ricostruisce
    nello stesso formato del vecchio file JSON.
    """
    profiles_dict = {}
    with DatabaseConnection() as conn:
        # 1. Recupera tutti i profili
        profiles_rows = conn.execute("SELECT * FROM profiles WHERE is_deleted = 0").fetchall()

        for profile_row in profiles_rows:
            profile_id = profile_row['id']
            profile_key = profile_row['profile_key']

            # 2. Per ogni profilo, recupera i suoi test
            tests_rows = conn.execute("SELECT * FROM profile_tests WHERE profile_id = ? AND is_deleted = 0", (profile_id,)).fetchall()

            tests_list = []
            for test_row in tests_rows:
                limits_data = json.loads(test_row['limits_json'] or '{}')
                limits_obj = {key: Limit(**data) for key, data in limits_data.items()}

                tests_list.append(Test(
                    name=test_row['name'],
                    parameter=test_row['parameter'],
                    limits=limits_obj,
                    is_applied_part_test=bool(test_row['is_applied_part_test'])
                ))

            profiles_dict[profile_key] = VerificationProfile(
                name=profile_row['name'],
                tests=tests_list
            )

    logging.info(f"Caricati {len(profiles_dict)} profili dal database locale.")
    return profiles_dict


def _serialize_functional_sections(sections: list[FunctionalSection]) -> list[dict]:
    serialized = []
    for section in sections:
        serialized.append(
            {
                "key": section.key,
                "title": section.title,
                "section_type": section.section_type,
                "description": section.description,
                "show_in_summary": section.show_in_summary,
                "fields": [field.__dict__ for field in section.fields],
                "rows": [
                    {
                        "key": row.key,
                        "label": row.label,
                        "fields": [field.__dict__ for field in row.fields],
                    }
                    for row in section.rows
                ],
            }
        )
    return serialized


def _serialize_functional_profile_schema(profile: FunctionalProfile) -> dict:
    """Serializza sezioni + metadata avanzati del profilo funzionale."""
    return {
        "sections": _serialize_functional_sections(profile.sections),
        "instrument_snapshots": profile.instrument_snapshots or [],
        "required_min_instruments": int(profile.required_min_instruments or 0),
        "allowed_instrument_types": profile.allowed_instrument_types or [],
    }


def _deserialize_functional_sections(schema_data: list[dict]) -> list[FunctionalSection]:
    sections: list[FunctionalSection] = []
    for section_dict in schema_data or []:
        if not isinstance(section_dict, dict):
            continue
        fields = [
            FunctionalField(**field_dict)
            for field_dict in section_dict.get("fields", [])
            if isinstance(field_dict, dict)
        ]
        row_definitions: list[FunctionalRowDefinition] = []
        for row_dict in section_dict.get("rows", []):
            if not isinstance(row_dict, dict):
                continue
            row_fields = [
                FunctionalField(**field_dict)
                for field_dict in row_dict.get("fields", [])
                if isinstance(field_dict, dict)
            ]
            row_definitions.append(
                FunctionalRowDefinition(
                    key=row_dict.get("key", ""),
                    label=row_dict.get("label"),
                    fields=row_fields,
                )
            )
        sections.append(
            FunctionalSection(
                key=section_dict.get("key", ""),
                title=section_dict.get("title", ""),
                section_type=section_dict.get("section_type", "fields"),
                description=section_dict.get("description"),
                fields=fields,
                rows=row_definitions,
                show_in_summary=bool(section_dict.get("show_in_summary", False)),
            )
        )
    return sections


def _parse_functional_profile_schema(schema_json: str | None) -> dict:
    """
    Supporta sia formato legacy (lista sezioni) sia formato nuovo (dict con metadata).
    """
    if not schema_json:
        return {
            "sections": [],
            "instrument_snapshots": [],
            "required_min_instruments": 0,
            "allowed_instrument_types": [],
        }

    try:
        raw = json.loads(schema_json)
    except json.JSONDecodeError:
        return {
            "sections": [],
            "instrument_snapshots": [],
            "required_min_instruments": 0,
            "allowed_instrument_types": [],
        }

    if isinstance(raw, list):
        return {
            "sections": raw,
            "instrument_snapshots": [],
            "required_min_instruments": 0,
            "allowed_instrument_types": [],
        }

    if isinstance(raw, dict):
        min_required = raw.get("required_min_instruments", 0)
        try:
            min_required = int(min_required)
        except (TypeError, ValueError):
            min_required = 0

        snapshots = raw.get("instrument_snapshots", [])
        if not isinstance(snapshots, list):
            snapshots = []

        allowed_types = raw.get("allowed_instrument_types", [])
        if not isinstance(allowed_types, list):
            allowed_types = []

        sections = raw.get("sections", [])
        if not isinstance(sections, list):
            sections = []

        return {
            "sections": sections,
            "instrument_snapshots": [snap for snap in snapshots if isinstance(snap, dict)],
            "required_min_instruments": max(0, min_required),
            "allowed_instrument_types": [str(t).strip() for t in allowed_types if str(t).strip()],
        }

    return {
        "sections": [],
        "instrument_snapshots": [],
        "required_min_instruments": 0,
        "allowed_instrument_types": [],
    }


def get_all_functional_profiles_from_db() -> dict[str, FunctionalProfile]:
    profiles_dict: dict[str, FunctionalProfile] = {}
    with DatabaseConnection() as conn:
        rows = conn.execute(
            "SELECT * FROM functional_profiles WHERE is_deleted = 0"
        ).fetchall()

        for row in rows:
            schema_payload = _parse_functional_profile_schema(row["schema_json"])
            sections = _deserialize_functional_sections(schema_payload.get("sections", []))
            # Leggi instrument_ids come JSON (o instrument_id singolo per retrocompatibilità)
            instrument_ids = []
            if "instrument_ids" in row.keys():
                # Nuova versione: campo JSON con lista di ID
                instrument_ids_json = row["instrument_ids"]
                if instrument_ids_json:
                    try:
                        ids_list = json.loads(instrument_ids_json)
                        if isinstance(ids_list, list):
                            for inst_id in ids_list:
                                try:
                                    instrument_ids.append(int(inst_id))
                                except (TypeError, ValueError):
                                    pass
                    except (json.JSONDecodeError, TypeError):
                        pass
            elif "instrument_id" in row.keys():
                # Vecchia versione: singolo ID (retrocompatibilità)
                instrument_id = row["instrument_id"]
                if instrument_id is not None:
                    try:
                        instrument_ids.append(int(instrument_id))
                    except (TypeError, ValueError):
                        pass
            profiles_dict[row["profile_key"]] = FunctionalProfile(
                profile_key=row["profile_key"],
                name=row["name"],
                device_type=row["device_type"],
                instrument_ids=instrument_ids,
                instrument_snapshots=schema_payload.get("instrument_snapshots", []),
                required_min_instruments=int(schema_payload.get("required_min_instruments", 0) or 0),
                allowed_instrument_types=schema_payload.get("allowed_instrument_types", []),
                sections=sections,
            )
    logging.info("Caricati %s profili funzionali dal database locale.", len(profiles_dict))
    return profiles_dict


def add_functional_profile(profile_key: str, profile: FunctionalProfile, timestamp: str) -> int:
    schema_json = json.dumps(_serialize_functional_profile_schema(profile))
    instrument_ids_json = json.dumps(profile.instrument_ids) if profile.instrument_ids else None
    with DatabaseConnection() as conn:
        profile_uuid = str(uuid.uuid4())
        # Prova prima con instrument_ids (nuovo campo JSON)
        try:
            cursor = conn.execute(
                """
                INSERT INTO functional_profiles
                    (uuid, profile_key, name, device_type, instrument_ids, schema_json, last_modified, is_synced, is_deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
                RETURNING id
                """,
                (
                    profile_uuid,
                    profile_key,
                    profile.name,
                    profile.device_type,
                    instrument_ids_json,
                    schema_json,
                    timestamp,
                ),
            )
        except sqlite3.OperationalError:
            # Se instrument_ids non esiste, prova con instrument_id (retrocompatibilità)
            try:
                first_instrument_id = profile.instrument_ids[0] if profile.instrument_ids else None
                cursor = conn.execute(
                    """
                    INSERT INTO functional_profiles
                        (uuid, profile_key, name, device_type, instrument_id, schema_json, last_modified, is_synced, is_deleted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
                    RETURNING id
                    """,
                    (
                        profile_uuid,
                        profile_key,
                        profile.name,
                        profile.device_type,
                        first_instrument_id,
                        schema_json,
                        timestamp,
                    ),
                )
            except sqlite3.OperationalError:
                # Se neanche instrument_id esiste, usa la query senza strumenti
                cursor = conn.execute(
                    """
                    INSERT INTO functional_profiles
                        (uuid, profile_key, name, device_type, schema_json, last_modified, is_synced, is_deleted)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                    RETURNING id
                    """,
                    (
                        profile_uuid,
                        profile_key,
                        profile.name,
                        profile.device_type,
                        schema_json,
                        timestamp,
                    ),
                )
        new_id = cursor.fetchone()[0]
    return new_id


def update_functional_profile(profile_id: int, profile: FunctionalProfile, timestamp: str) -> None:
    schema_json = json.dumps(_serialize_functional_profile_schema(profile))
    instrument_ids_json = json.dumps(profile.instrument_ids) if profile.instrument_ids else None
    with DatabaseConnection() as conn:
        # Recupera il vecchio profile_key per verificare se è cambiato
        old_profile_row = conn.execute(
            "SELECT profile_key FROM functional_profiles WHERE id = ?",
            (profile_id,)
        ).fetchone()
        old_profile_key = old_profile_row[0] if old_profile_row else None
        
        # Prova prima con instrument_ids (nuovo campo JSON)
        try:
            conn.execute(
                """
                UPDATE functional_profiles
                SET profile_key = ?, name = ?, device_type = ?, instrument_ids = ?, schema_json = ?, last_modified = ?, is_synced = 0
                WHERE id = ?
                """,
                (profile.profile_key, profile.name, profile.device_type, instrument_ids_json, schema_json, timestamp, profile_id),
            )
        except sqlite3.OperationalError:
            # Se instrument_ids non esiste, prova con instrument_id (retrocompatibilità)
            try:
                first_instrument_id = profile.instrument_ids[0] if profile.instrument_ids else None
                conn.execute(
                    """
                    UPDATE functional_profiles
                    SET profile_key = ?, name = ?, device_type = ?, instrument_id = ?, schema_json = ?, last_modified = ?, is_synced = 0
                    WHERE id = ?
                    """,
                    (profile.profile_key, profile.name, profile.device_type, first_instrument_id, schema_json, timestamp, profile_id),
                )
            except sqlite3.OperationalError:
                # Se neanche instrument_id esiste, usa la query senza strumenti
                conn.execute(
                    """
                    UPDATE functional_profiles
                    SET profile_key = ?, name = ?, device_type = ?, schema_json = ?, last_modified = ?, is_synced = 0
                    WHERE id = ?
                    """,
                    (profile.profile_key, profile.name, profile.device_type, schema_json, timestamp, profile_id),
                )
        
        # Se il profile_key è cambiato, aggiorna tutti i dispositivi che hanno il vecchio profile_key come default
        if old_profile_key and old_profile_key != profile.profile_key:
            conn.execute(
                """
                UPDATE devices
                SET default_functional_profile_key = ?, last_modified = ?, is_synced = 0
                WHERE default_functional_profile_key = ? AND is_deleted = 0
                """,
                (profile.profile_key, timestamp, old_profile_key),
            )
            logging.info(
                f"Aggiornati i dispositivi con default_functional_profile_key da '{old_profile_key}' a '{profile.profile_key}'"
            )


def delete_functional_profile(profile_id: int, timestamp: str) -> None:
    with DatabaseConnection() as conn:
        conn.execute(
            """
            UPDATE functional_profiles
            SET is_deleted = 1, last_modified = ?, is_synced = 0
            WHERE id = ?
            """,
            (timestamp, profile_id),
        )


def save_functional_verification(
    uuid: str,
    device_id: int,
    profile_key: str,
    results: dict,
    structured_results: dict,
    overall_status: str,
    notes: str,
    mti_info: dict,
    technician_name: str,
    technician_username: str,
    timestamp: str,
    verification_date: str | None = None,
    verification_code: str | None = None,
    used_instruments: list | None = None,
) -> int:
    if verification_date is None:
        verification_date = datetime.now().strftime("%Y-%m-%d")

    used_instruments_json = json.dumps(used_instruments or []) if used_instruments else None

    with DatabaseConnection() as conn:
        if not verification_code:
            verification_code = generate_verification_code(
                conn,
                verification_date,
                technician_name,
                technician_username,
                suffix="VF",
                table_name="functional_verifications",
            )

        # Prova prima con used_instruments_json (nuovo campo)
        try:
            cursor = conn.execute(
                """
                INSERT INTO functional_verifications (
                    uuid, device_id, profile_key, verification_date,
                    technician_name, technician_username,
                    mti_instrument, mti_serial, mti_version, mti_cal_date,
                    results_json, overall_status, notes, verification_code, structured_results_json,
                    used_instruments_json,
                    last_modified, is_synced, is_deleted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                RETURNING id
                """,
                (
                    uuid,
                    device_id,
                    profile_key,
                    verification_date,
                    technician_name,
                    technician_username,
                    (mti_info or {}).get("instrument"),
                    (mti_info or {}).get("serial"),
                    (mti_info or {}).get("version"),
                    (mti_info or {}).get("cal_date"),
                    json.dumps(results or {}),
                    overall_status,
                    notes,
                    verification_code,
                    json.dumps(structured_results or {}),
                    used_instruments_json,
                    timestamp,
                ),
            )
        except sqlite3.OperationalError:
            # Se used_instruments_json non esiste, usa la query senza questo campo
            cursor = conn.execute(
                """
                INSERT INTO functional_verifications (
                    uuid, device_id, profile_key, verification_date,
                    technician_name, technician_username,
                    mti_instrument, mti_serial, mti_version, mti_cal_date,
                    results_json, overall_status, notes, verification_code, structured_results_json,
                    last_modified, is_synced, is_deleted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                RETURNING id
                """,
                (
                    uuid,
                    device_id,
                    profile_key,
                    verification_date,
                    technician_name,
                    technician_username,
                    (mti_info or {}).get("instrument"),
                    (mti_info or {}).get("serial"),
                    (mti_info or {}).get("version"),
                    (mti_info or {}).get("cal_date"),
                    json.dumps(results or {}),
                    overall_status,
                    notes,
                    verification_code,
                    json.dumps(structured_results or {}),
                    timestamp,
                ),
            )
        new_id = cursor.fetchone()[0]
    return verification_code, new_id


def has_functional_verification_today(device_id: int, verification_date: str) -> bool:
    """
    Controlla se esiste già una verifica funzionale per un dispositivo in una data specifica.
    
    Args:
        device_id: ID del dispositivo
        verification_date: Data della verifica nel formato 'YYYY-MM-DD'
    
    Returns:
        True se esiste già una verifica funzionale per quel dispositivo in quella data, False altrimenti
    """
    with DatabaseConnection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) as count
            FROM functional_verifications
            WHERE device_id = ? AND verification_date = ? AND is_deleted = 0
            """,
            (device_id, verification_date),
        ).fetchone()
    return row[0] > 0 if row else False


def get_functional_verifications_for_device(device_id: int) -> list[dict]:
    with DatabaseConnection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM functional_verifications
            WHERE device_id = ? AND is_deleted = 0
            ORDER BY verification_date DESC, id DESC
            """,
            (device_id,),
        ).fetchall()
    verifications: list[dict] = []
    for row in rows:
        data = dict(row)
        try:
            data["results"] = json.loads(data.get("results_json") or "{}")
        except json.JSONDecodeError:
            data["results"] = {}
        try:
            data["structured_results"] = json.loads(data.get("structured_results_json") or "{}")
        except json.JSONDecodeError:
            data["structured_results"] = {}
        # Aggiungi used_instruments_json se presente
        if "used_instruments_json" in row.keys():
            used_instruments_json = row["used_instruments_json"]
            if used_instruments_json:
                try:
                    data["used_instruments_json"] = used_instruments_json
                except (json.JSONDecodeError, TypeError):
                    data["used_instruments_json"] = None
        verifications.append(data)
    return verifications


def get_functional_verification_with_device_info(verification_id: int):
    """Recupera una verifica funzionale con contesto completo del dispositivo."""
    with DatabaseConnection() as conn:
        return conn.execute(
            """
            SELECT
                fv.id,
                fv.device_id,
                fv.verification_code,
                fv.verification_date,
                fv.overall_status,
                fv.profile_key,
                fv.technician_name,
                fv.technician_username,
                d.description,
                d.serial_number,
                d.manufacturer,
                d.model,
                d.customer_inventory,
                d.ams_inventory,
                d.destination_id,
                dest.name AS destination_name,
                dest.customer_id,
                c.name AS customer_name
            FROM functional_verifications fv
            LEFT JOIN devices d ON fv.device_id = d.id
            LEFT JOIN destinations dest ON d.destination_id = dest.id
            LEFT JOIN customers c ON dest.customer_id = c.id
            WHERE fv.id = ?
            LIMIT 1
            """,
            (verification_id,),
        ).fetchone()


def get_functional_verifications_for_destination_by_date_range(destination_id: int, start_date: str, end_date: str) -> list:
    """
    Recupera tutte le verifiche funzionali per una specifica destinazione eseguite in un dato intervallo di date.
    Include tutti i campi del dispositivo necessari per la generazione dei report.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT fv.*, 
                   d.serial_number, d.ams_inventory, d.customer_inventory,
                   d.description, d.manufacturer, d.model, d.department,
                   dest.name as destination_name
            FROM functional_verifications fv
            JOIN devices d ON fv.device_id = d.id
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE fv.is_deleted = 0 AND d.is_deleted = 0
            AND d.destination_id = ?
            AND fv.verification_date BETWEEN ? AND ?
            ORDER BY d.description, fv.verification_date;
        """
        return conn.execute(query, (destination_id, start_date, end_date)).fetchall()

def get_functional_verifications_by_date_range(start_date: str, end_date: str) -> list:
    """
    Recupera tutte le verifiche funzionali eseguite in un dato intervallo di date (tutto il database).
    Include tutti i campi del dispositivo necessari per la generazione dei report.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT fv.*, 
                   d.serial_number, d.ams_inventory, d.customer_inventory,
                   d.description, d.manufacturer, d.model, d.department,
                   dest.name as destination_name
            FROM functional_verifications fv
            JOIN devices d ON fv.device_id = d.id
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE fv.is_deleted = 0 AND d.is_deleted = 0
            AND fv.verification_date BETWEEN ? AND ?
            ORDER BY d.description, fv.verification_date;
        """
        return conn.execute(query, (start_date, end_date)).fetchall()

def get_functional_verifications_for_customer_by_date_range(customer_id: int, start_date: str, end_date: str) -> list:
    """
    Recupera tutte le verifiche funzionali per un cliente in un dato intervallo di date.
    Include tutti i campi del dispositivo necessari per la generazione dei report.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT fv.*, 
                   d.serial_number, d.ams_inventory, d.customer_inventory,
                   d.description, d.manufacturer, d.model, d.department,
                   dest.name as destination_name
            FROM functional_verifications fv
            JOIN devices d ON fv.device_id = d.id
            JOIN destinations dest ON d.destination_id = dest.id
            WHERE fv.is_deleted = 0 AND d.is_deleted = 0
            AND dest.customer_id = ?
            AND fv.verification_date BETWEEN ? AND ?
            ORDER BY d.description, fv.verification_date;
        """
        return conn.execute(query, (customer_id, start_date, end_date)).fetchall()


def update_functional_verification(verification_id: int, verification_date: str, overall_status: str,
                                    technician_name: str, notes: str, timestamp: str, *,
                                    results: dict | None = None,
                                    structured_results: dict | None = None,
                                    mti_instrument: str | None = None,
                                    mti_serial: str | None = None,
                                    mti_version: str | None = None,
                                    mti_cal_date: str | None = None) -> bool:
    """Aggiorna tutti i campi modificabili di una verifica funzionale."""
    sets = [
        "verification_date = ?", "overall_status = ?",
        "technician_name = ?", "notes = ?",
        "last_modified = ?", "is_synced = 0",
    ]
    params: list = [verification_date, overall_status, technician_name, notes, timestamp]

    if results is not None:
        sets.append("results_json = ?")
        params.append(json.dumps(results))
    if structured_results is not None:
        sets.append("structured_results_json = ?")
        params.append(json.dumps(structured_results))
    if mti_instrument is not None:
        sets.append("mti_instrument = ?")
        params.append(mti_instrument)
    if mti_serial is not None:
        sets.append("mti_serial = ?")
        params.append(mti_serial)
    if mti_version is not None:
        sets.append("mti_version = ?")
        params.append(mti_version)
    if mti_cal_date is not None:
        sets.append("mti_cal_date = ?")
        params.append(mti_cal_date)

    params.append(verification_id)
    with DatabaseConnection() as conn:
        cursor = conn.execute(
            f"UPDATE functional_verifications SET {', '.join(sets)} WHERE id = ? AND is_deleted = 0",
            tuple(params),
        )
    if cursor.rowcount > 0:
        logging.info(f"Verifica funzionale ID {verification_id} aggiornata.")
        return True
    return False


def delete_functional_verification(verification_id: int, timestamp: str) -> None:
    with DatabaseConnection() as conn:
        conn.execute(
            """
            UPDATE functional_verifications
            SET is_deleted = 1, last_modified = ?, is_synced = 0
            WHERE id = ?
            """,
            (timestamp, verification_id),
        )

def add_profile_with_tests(profile_key, profile_name, tests_list, timestamp):
    """Aggiunge un nuovo profilo e i suoi test in una singola transazione."""
    with DatabaseConnection() as conn:
        # Inserisci il profilo
        profile_uuid = str(uuid.uuid4())
        cursor = conn.execute(
            "INSERT INTO profiles (uuid, profile_key, name, last_modified, is_synced, is_deleted) VALUES (?, ?, ?, ?, 0, 0) RETURNING id",
            (profile_uuid, profile_key, profile_name, timestamp)
        )
        profile_id = cursor.fetchone()[0]

        # Inserisci i test associati
        if tests_list:
            tests_to_insert = []
            for test in tests_list:
                tests_to_insert.append((
                    str(uuid.uuid4()), profile_id, test.name, test.parameter,
                    json.dumps({k: v.__dict__ for k, v in test.limits.items()}),
                    test.is_applied_part_test, timestamp
                ))

            conn.executemany(
                "INSERT INTO profile_tests (uuid, profile_id, name, parameter, limits_json, is_applied_part_test, last_modified, is_synced, is_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
                tests_to_insert
            )
    return profile_id

def update_profile_with_tests(profile_id, profile_name, tests_list, timestamp):
    """Aggiorna un profilo e la sua lista di test."""
    with DatabaseConnection() as conn:
        # Aggiorna il nome del profilo
        conn.execute(
            "UPDATE profiles SET name = ?, last_modified = ?, is_synced = 0 WHERE id = ?",
            (profile_name, timestamp, profile_id)
        )

        # Approccio semplice: cancella i vecchi test e inserisce i nuovi
        # Questo marca i vecchi come eliminati e i nuovi come da inserire per il sync
        conn.execute(
            "UPDATE profile_tests SET is_deleted = 1, last_modified = ?, is_synced = 0 WHERE profile_id = ?",
            (timestamp, profile_id)
        )

        if tests_list:
            tests_to_insert = []
            for test in tests_list:
                tests_to_insert.append((
                    str(uuid.uuid4()), profile_id, test.name, test.parameter,
                    json.dumps({k: v.__dict__ for k, v in test.limits.items()}),
                    test.is_applied_part_test, timestamp
                ))

            conn.executemany(
                "INSERT INTO profile_tests (uuid, profile_id, name, parameter, limits_json, is_applied_part_test, last_modified, is_synced, is_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
                tests_to_insert
            )

def delete_profile(profile_id, timestamp):
    """Esegue un soft delete di un profilo e dei suoi test associati."""
    with DatabaseConnection() as conn:
        conn.execute("UPDATE profiles SET is_deleted = 1, last_modified = ?, is_synced = 0 WHERE id = ?", (timestamp, profile_id))
        conn.execute("UPDATE profile_tests SET is_deleted = 1, last_modified = ?, is_synced = 0 WHERE profile_id = ?", (timestamp, profile_id))


# ==============================================================================
# SEZIONE 5 FULL UPLOAD
# ==============================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _get_pk_column(conn: sqlite3.Connection, table: str) -> str:
    """
    Ritorna il nome della colonna PK della tabella.
    Se non c'è una PK esplicita, ritorna 'rowid' (valido per tabelle normali).
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    pk_cols = []
    for r in rows:
        # r: (cid, name, type, notnull, dflt_value, pk) oppure Row
        name = r["name"] if isinstance(r, sqlite3.Row) else r[1]
        is_pk = (r["pk"] if isinstance(r, sqlite3.Row) else r[5]) == 1
        if is_pk:
            pk_cols.append(name)
    if len(pk_cols) == 1:
        return pk_cols[0]
    # se PK multipla o assente, usiamo rowid (funziona finché non è WITHOUT ROWID)
    return "rowid"

def _ensure_uuid_for_table(conn: sqlite3.Connection, table: str) -> int:
    """
    Genera un uuid per tutte le righe della tabella che non lo hanno.
    Usa la PK reale (o rowid) per l'UPDATE.
    """
    # assicura che la colonna uuid esista (difensivo; altrove lo fai già)
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    colnames = { (c["name"] if isinstance(c, sqlite3.Row) else c[1]).lower() for c in cols }
    if "uuid" not in colnames:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN uuid TEXT")

    pk_col = _get_pk_column(conn, table)

    cur = conn.execute(f"SELECT {pk_col} FROM {table} WHERE uuid IS NULL OR uuid = ''")
    rows = cur.fetchall()
    count = 0
    for r in rows:
        # r può essere Row o tuple; recupera il valore della PK
        if isinstance(r, sqlite3.Row):
            pk_val = r[pk_col] if pk_col in r.keys() else r[0]
        else:
            pk_val = r[0]
        conn.execute(f"UPDATE {table} SET uuid=? WHERE {pk_col}=?", (str(uuid.uuid4()), pk_val))
        count += 1
    return count

def mark_everything_for_full_push(conn: sqlite3.Connection) -> dict:
    """
    Segna tutte le tabelle come 'da sincronizzare' (is_synced=0),
    forza last_modified = adesso, garantisce uuid presenti
    e normalizza serial_number placeholder -> NULL.
    """
    conn.row_factory = sqlite3.Row
    tables = [
        "customers",
        "destinations",
        "devices",
        "verifications",
        "functional_verifications",
        "profiles",
        "profile_tests",
        "functional_profiles",
        "mti_instruments",
        "signatures",
    ]
    res = {}
    now = _now_iso()

    with conn:  # transazione
        # garantisci colonne base (difensivo)
        def _col_exists(table, col):
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            names = [row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows]
            return col in names

        for t in tables:
            if not _col_exists(t, "uuid"):
                conn.execute(f"ALTER TABLE {t} ADD COLUMN uuid TEXT")
            if not _col_exists(t, "last_modified"):
                conn.execute(f"ALTER TABLE {t} ADD COLUMN last_modified TEXT")
            if not _col_exists(t, "is_synced"):
                conn.execute(f"ALTER TABLE {t} ADD COLUMN is_synced INTEGER NOT NULL DEFAULT 0")

        # uuid per tutte le tabelle (usando la PK corretta)
        created = {}
        for t in tables:
            created[t] = _ensure_uuid_for_table(conn, t)

        # normalizza seriali (devices)
        conn.execute("UPDATE devices SET serial_number=NULL WHERE serial_number IS NOT NULL AND TRIM(serial_number) = ''")
        for ph in config.PLACEHOLDER_SERIALS:
            conn.execute(
                "UPDATE devices SET serial_number=NULL WHERE serial_number IS NOT NULL AND UPPER(serial_number)=UPPER(?)",
                (ph,)
            )

        # marca tutto come non sincronizzato e bump last_modified
        for t in tables:
            cur = conn.execute(f"UPDATE {t} SET is_synced=0, last_modified=?", (now,))
            res[t] = {"rows_marked": cur.rowcount, "uuid_added": created[t]}

    logging.info(f"[full-push] Marcate come da sincronizzare: {res}")
    return res

# ==============================================================================
# ESECUZIONE INIZIALE
# ==============================================================================

def get_verification_stats_by_month(year: int):
    """
    Recupera il numero di verifiche totali, passate e fallite per ogni mese di un dato anno.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT
                strftime('%m', verification_date) as month,
                COUNT(id) as total,
                SUM(CASE WHEN overall_status = 'PASSATO' THEN 1 ELSE 0 END) as passed,
                SUM(CASE WHEN overall_status = 'FALLITO' THEN 1 ELSE 0 END) as failed
            FROM verifications
            WHERE strftime('%Y', verification_date) = ? AND is_deleted = 0
            GROUP BY month
            ORDER BY month;
        """
        return conn.execute(query, (str(year),)).fetchall()

def get_top_customers_by_verifications(limit=10):
    """
    Recupera i top clienti per numero di verifiche.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT 
                c.name as customer_name,
                COUNT(v.id) as total_verifications,
                SUM(CASE WHEN v.overall_status = 'PASSATO' THEN 1 ELSE 0 END) as passed,
                SUM(CASE WHEN v.overall_status = 'FALLITO' THEN 1 ELSE 0 END) as failed,
                ROUND(CAST(SUM(CASE WHEN v.overall_status = 'PASSATO' THEN 1 ELSE 0 END) AS FLOAT) / 
                      COUNT(v.id) * 100, 1) as conformity_rate
            FROM customers c
            JOIN destinations d ON c.id = d.customer_id
            JOIN devices dev ON d.id = dev.destination_id
            JOIN verifications v ON dev.id = v.device_id
            WHERE c.is_deleted = 0 AND d.is_deleted = 0 AND dev.is_deleted = 0 AND v.is_deleted = 0
            GROUP BY c.id, c.name
            HAVING COUNT(v.id) > 0
            ORDER BY total_verifications DESC
            LIMIT ?;
        """
        return conn.execute(query, (limit,)).fetchall()

def get_top_technicians_by_verifications(limit=10):
    """
    Recupera i top tecnici per numero di verifiche.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT 
                technician_name,
                COUNT(id) as total_verifications,
                SUM(CASE WHEN overall_status = 'PASSATO' THEN 1 ELSE 0 END) as passed,
                SUM(CASE WHEN overall_status = 'FALLITO' THEN 1 ELSE 0 END) as failed,
                ROUND(CAST(SUM(CASE WHEN overall_status = 'PASSATO' THEN 1 ELSE 0 END) AS FLOAT) / 
                      COUNT(id) * 100, 1) as conformity_rate
            FROM verifications
            WHERE is_deleted = 0 AND technician_name IS NOT NULL AND technician_name != ''
            GROUP BY technician_name
            HAVING COUNT(id) > 0
            ORDER BY total_verifications DESC
            LIMIT ?;
        """
        return conn.execute(query, (limit,)).fetchall()

# ==============================================================================
# AUDIT LOG FUNCTIONS
# ==============================================================================

def log_audit(username, user_full_name, action_type, entity_type, entity_id=None, 
              entity_description=None, details=None, ip_address=None):
    """
    Registra un'azione nel log di audit.
    
    Args:
        username: Username dell'utente che ha eseguito l'azione
        user_full_name: Nome completo dell'utente
        action_type: Tipo di azione ('CREATE', 'UPDATE', 'DELETE', 'VERIFY', 'LOGIN', 'SYNC', etc.)
        entity_type: Tipo di entità ('customer', 'device', 'verification', 'user', etc.)
        entity_id: ID dell'entità (opzionale)
        entity_description: Descrizione leggibile (es. nome cliente, descrizione dispositivo)
        details: Dizionario con dettagli aggiuntivi (verrà convertito in JSON)
        ip_address: Indirizzo IP (opzionale)
    """
    import uuid as uuid_lib
    import json
    from datetime import datetime, timezone
    
    try:
        with DatabaseConnection() as conn:
            new_uuid = str(uuid_lib.uuid4())
            timestamp = datetime.now(timezone.utc).isoformat()
            
            # Converte details in JSON se è un dizionario
            details_json = None
            if details:
                if isinstance(details, dict):
                    details_json = json.dumps(details, ensure_ascii=False)
                else:
                    details_json = str(details)
            
            query = """
                INSERT INTO audit_log 
                (uuid, timestamp, username, user_full_name, action_type, entity_type, 
                 entity_id, entity_description, details, ip_address, last_modified, is_synced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """
            
            conn.execute(query, (
                new_uuid, timestamp, username, user_full_name, action_type, entity_type,
                entity_id, entity_description, details_json, ip_address, timestamp
            ))
            
            logging.debug(f"Audit log: {action_type} on {entity_type} by {username}")
            
    except Exception as e:
        # Non bloccare l'operazione se il logging fallisce
        logging.error(f"Errore durante il logging audit: {e}", exc_info=True)

def get_audit_log(filters=None, limit=100, offset=0):
    """
    Recupera i record dal log di audit.
    
    Args:
        filters: Dizionario con filtri (username, action_type, entity_type, date_from, date_to)
        limit: Numero massimo di record da recuperare
        offset: Offset per paginazione
    
    Returns:
        Lista di record di audit
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT 
                id, timestamp, username, user_full_name, action_type, entity_type,
                entity_id, entity_description, details, ip_address
            FROM audit_log
            WHERE action_type != 'SYNC'
        """
        params = []
        
        if filters:
            if filters.get('username'):
                query += " AND username = ?"
                params.append(filters['username'])
            
            if filters.get('action_type'):
                query += " AND action_type = ?"
                params.append(filters['action_type'])
            
            if filters.get('entity_type'):
                query += " AND entity_type = ?"
                params.append(filters['entity_type'])
            
            if filters.get('date_from'):
                query += " AND timestamp >= ?"
                params.append(filters['date_from'])
            
            if filters.get('date_to'):
                query += " AND timestamp <= ?"
                params.append(filters['date_to'])
            
            if filters.get('search_text'):
                query += " AND (entity_description LIKE ? OR details LIKE ?)"
                search_pattern = f"%{filters['search_text']}%"
                params.extend([search_pattern, search_pattern])
        
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        return conn.execute(query, tuple(params)).fetchall()

def get_audit_log_stats():
    """
    Recupera statistiche sul log di audit.
    
    Returns:
        Dizionario con statistiche (total, by_action, by_user, by_entity)
    """
    with DatabaseConnection() as conn:
        stats = {}
        
        # Totale azioni
        total = conn.execute("SELECT COUNT(*) as count FROM audit_log WHERE action_type != 'SYNC'").fetchone()
        stats['total'] = total['count'] if total else 0
        
        # Per tipo di azione
        by_action = conn.execute("""
            SELECT action_type, COUNT(*) as count 
            FROM audit_log 
            WHERE action_type != 'SYNC'
            GROUP BY action_type 
            ORDER BY count DESC
        """).fetchall()
        stats['by_action'] = [dict(row) for row in by_action]
        
        # Per utente
        by_user = conn.execute("""
            SELECT username, user_full_name, COUNT(*) as count 
            FROM audit_log 
            WHERE action_type != 'SYNC'
            GROUP BY username 
            ORDER BY count DESC 
            LIMIT 10
        """).fetchall()
        stats['by_user'] = [dict(row) for row in by_user]
        
        # Per tipo di entità
        by_entity = conn.execute("""
            SELECT entity_type, COUNT(*) as count 
            FROM audit_log 
            WHERE action_type != 'SYNC'
            GROUP BY entity_type 
            ORDER BY count DESC
        """).fetchall()
        stats['by_entity'] = [dict(row) for row in by_entity]
        
        return stats

def search_destinations_globally(search_term: str):
    """
    Cerca destinazioni in tutto il database per nome, indirizzo.
    Restituisce destinazioni con informazioni del cliente.
    """
    with DatabaseConnection() as conn:
        query = """
            SELECT 
                d.id,
                d.uuid,
                d.name,
                d.address,
                d.customer_id,
                c.name as customer_name,
                d.last_modified,
                d.is_synced
            FROM destinations d
            JOIN customers c ON d.customer_id = c.id
            WHERE d.is_deleted = 0
            AND (d.name LIKE ? OR d.address LIKE ?)
            ORDER BY d.name
        """
        pattern = f"%{search_term}%"
        return conn.execute(query, (pattern, pattern)).fetchall()


# ==============================================================================
# SEZIONE: GESTIONE DATI ELIMINATI (SOFT-DELETED) - ADMIN
# ==============================================================================

def get_deleted_customers():
    """Restituisce tutti i clienti marcati come eliminati."""
    with DatabaseConnection() as conn:
        return conn.execute(
            "SELECT id, uuid, name, address, phone, email, last_modified FROM customers WHERE is_deleted = 1 ORDER BY last_modified DESC"
        ).fetchall()

def get_deleted_destinations():
    """Restituisce tutte le destinazioni marcate come eliminate con info cliente."""
    with DatabaseConnection() as conn:
        return conn.execute("""
            SELECT d.id, d.uuid, d.name, d.address, d.last_modified,
                   COALESCE(c.name, '(Cliente eliminato)') as customer_name
            FROM destinations d
            LEFT JOIN customers c ON d.customer_id = c.id
            WHERE d.is_deleted = 1
            ORDER BY d.last_modified DESC
        """).fetchall()

def get_deleted_devices():
    """Restituisce tutti i dispositivi marcati come eliminati con info destinazione/cliente."""
    with DatabaseConnection() as conn:
        return conn.execute("""
            SELECT dev.id, dev.uuid, dev.serial_number, dev.description, 
                   dev.manufacturer, dev.model, dev.last_modified,
                   COALESCE(dest.name, '(Dest. eliminata)') as destination_name,
                   COALESCE(c.name, '(Cliente eliminato)') as customer_name
            FROM devices dev
            LEFT JOIN destinations dest ON dev.destination_id = dest.id
            LEFT JOIN customers c ON dest.customer_id = c.id
            WHERE dev.is_deleted = 1
            ORDER BY dev.last_modified DESC
        """).fetchall()

def get_deleted_verifications():
    """Restituisce tutte le verifiche elettriche marcate come eliminate."""
    with DatabaseConnection() as conn:
        return conn.execute("""
            SELECT v.id, v.uuid, v.verification_date, v.profile_name, 
                   v.overall_status, v.technician_name, v.verification_code, v.last_modified,
                   COALESCE(d.serial_number, 'N/A') as device_serial,
                   COALESCE(d.description, 'N/A') as device_description
            FROM verifications v
            LEFT JOIN devices d ON v.device_id = d.id
            WHERE v.is_deleted = 1
            ORDER BY v.last_modified DESC
        """).fetchall()

def get_deleted_functional_verifications():
    """Restituisce tutte le verifiche funzionali marcate come eliminate."""
    with DatabaseConnection() as conn:
        return conn.execute("""
            SELECT fv.id, fv.uuid, fv.verification_date, fv.profile_key,
                   fv.overall_status, fv.technician_name, fv.verification_code, fv.last_modified,
                   COALESCE(d.serial_number, 'N/A') as device_serial,
                   COALESCE(d.description, 'N/A') as device_description
            FROM functional_verifications fv
            LEFT JOIN devices d ON fv.device_id = d.id
            WHERE fv.is_deleted = 1
            ORDER BY fv.last_modified DESC
        """).fetchall()

def get_deleted_profiles():
    """Restituisce tutti i profili elettrici marcati come eliminati."""
    with DatabaseConnection() as conn:
        return conn.execute(
            "SELECT id, uuid, profile_key, name, last_modified FROM profiles WHERE is_deleted = 1 ORDER BY last_modified DESC"
        ).fetchall()

def get_deleted_functional_profiles():
    """Restituisce tutti i profili funzionali marcati come eliminati."""
    with DatabaseConnection() as conn:
        return conn.execute(
            "SELECT id, uuid, profile_key, name, device_type, last_modified FROM functional_profiles WHERE is_deleted = 1 ORDER BY last_modified DESC"
        ).fetchall()

def get_deleted_instruments():
    """Restituisce tutti gli strumenti di misura marcati come eliminati."""
    with DatabaseConnection() as conn:
        return conn.execute(
            "SELECT id, uuid, instrument_name, serial_number, fw_version, calibration_date, instrument_type, last_modified FROM mti_instruments WHERE is_deleted = 1 ORDER BY last_modified DESC"
        ).fetchall()

def hard_delete_record(table_name: str, record_id: int) -> bool:
    """
    Elimina definitivamente un record dal database.
    Funziona solo su record già marcati come is_deleted = 1.
    Restituisce True se il record è stato eliminato, False altrimenti.
    """
    allowed_tables = {
        'customers', 'destinations', 'devices', 'verifications',
        'functional_verifications', 'profiles', 'functional_profiles',
        'mti_instruments'
    }
    if table_name not in allowed_tables:
        logging.error(f"Tentativo di hard delete su tabella non consentita: {table_name}")
        return False
    
    with DatabaseConnection() as conn:
        # Elimina solo record già soft-deleted
        cursor = conn.execute(
            f"DELETE FROM {table_name} WHERE id = ? AND is_deleted = 1",
            (record_id,)
        )
        deleted = cursor.rowcount > 0
    
    if deleted:
        logging.warning(f"Record ID {record_id} eliminato definitivamente dalla tabella {table_name}.")
    return deleted

def hard_delete_all_for_entity(table_name: str) -> int:
    """
    Elimina definitivamente TUTTI i record soft-deleted di una tabella.
    Restituisce il numero di record eliminati.
    """
    allowed_tables = {
        'customers', 'destinations', 'devices', 'verifications',
        'functional_verifications', 'profiles', 'functional_profiles',
        'mti_instruments'
    }
    if table_name not in allowed_tables:
        logging.error(f"Tentativo di hard delete massivo su tabella non consentita: {table_name}")
        return 0
    
    with DatabaseConnection() as conn:
        cursor = conn.execute(
            f"DELETE FROM {table_name} WHERE is_deleted = 1"
        )
        count = cursor.rowcount
    
    if count > 0:
        logging.warning(f"Eliminati definitivamente {count} record dalla tabella {table_name}.")
    return count

def get_deleted_counts() -> dict:
    """Restituisce il conteggio dei record eliminati per ogni tabella."""
    counts = {}
    tables = ['customers', 'destinations', 'devices', 'verifications',
              'functional_verifications', 'profiles', 'functional_profiles',
              'mti_instruments']
    with DatabaseConnection() as conn:
        for table in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE is_deleted = 1").fetchone()[0]
            counts[table] = count
    return counts


# ==============================================================================
# SEZIONE: GESTIONE CONFLITTI DI SINCRONIZZAZIONE
# ==============================================================================

def save_sync_conflict(conflict_id: str, table_name: str, record_uuid: str,
                       conflict_type: str, severity: str,
                       local_data: dict = None, server_data: dict = None,
                       error_message: str = None):
    """
    Salva un conflitto di sincronizzazione nel database locale.
    Se esiste già un conflitto con lo stesso conflict_id, lo aggiorna.
    """
    with DatabaseConnection() as conn:
        conn.execute("""
            INSERT INTO sync_conflicts 
                (conflict_id, table_name, record_uuid, conflict_type, severity,
                 local_data, server_data, error_message, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', datetime('now'))
            ON CONFLICT(conflict_id) DO UPDATE SET
                local_data = excluded.local_data,
                server_data = excluded.server_data,
                error_message = excluded.error_message,
                severity = excluded.severity,
                status = 'pending',
                created_at = datetime('now')
        """, (
            conflict_id, table_name, record_uuid, conflict_type, severity,
            json.dumps(local_data, default=str) if local_data else None,
            json.dumps(server_data, default=str) if server_data else None,
            error_message
        ))
    logging.info(f"Conflitto di sync salvato: {conflict_type} in {table_name} (uuid={record_uuid})")


def get_pending_sync_conflicts() -> list:
    """Restituisce tutti i conflitti di sincronizzazione non ancora risolti."""
    with DatabaseConnection() as conn:
        rows = conn.execute("""
            SELECT * FROM sync_conflicts 
            WHERE status = 'pending' 
            ORDER BY created_at DESC
        """).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            # Parse JSON fields
            if d.get('local_data'):
                try:
                    d['local_data'] = json.loads(d['local_data'])
                except (json.JSONDecodeError, TypeError):
                    pass
            if d.get('server_data'):
                try:
                    d['server_data'] = json.loads(d['server_data'])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(d)
        return result


def get_pending_conflicts_count() -> int:
    """Restituisce il numero di conflitti di sincronizzazione non risolti."""
    try:
        with DatabaseConnection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM sync_conflicts WHERE status = 'pending'"
            ).fetchone()
            return row['cnt'] if row else 0
    except Exception:
        return 0


def resolve_sync_conflict(conflict_id: str, resolution: str):
    """
    Marca un conflitto come risolto.
    
    Args:
        conflict_id: ID univoco del conflitto
        resolution: Tipo di risoluzione ('keep_local', 'use_server', 'merged', 'dismissed')
    """
    with DatabaseConnection() as conn:
        conn.execute("""
            UPDATE sync_conflicts 
            SET status = 'resolved', resolution = ?, resolved_at = datetime('now')
            WHERE conflict_id = ?
        """, (resolution, conflict_id))
    logging.info(f"Conflitto {conflict_id} risolto con: {resolution}")


def delete_resolved_conflicts():
    """Elimina tutti i conflitti già risolti."""
    with DatabaseConnection() as conn:
        cursor = conn.execute("DELETE FROM sync_conflicts WHERE status = 'resolved'")
        count = cursor.rowcount
    if count > 0:
        logging.info(f"Eliminati {count} conflitti di sync risolti.")
    return count


def delete_all_conflicts():
    """Elimina tutti i conflitti (usato per reset)."""
    with DatabaseConnection() as conn:
        cursor = conn.execute("DELETE FROM sync_conflicts")
        count = cursor.rowcount
    if count > 0:
        logging.info(f"Eliminati tutti i {count} conflitti di sync.")
    return count


# Applica le migrazioni del database all'avvio del modulo
migrate_database()
