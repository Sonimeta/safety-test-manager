# app/sync_monitor.py (Monitoraggio e Logging avanzato della sincronizzazione)
import logging
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional
import sqlite3
from app import config, database

# Tabella per tracciare la storia della sincronizzazione
SYNC_HISTORY_TABLE = "sync_history"


def init_sync_history_table():
    """Crea la tabella per la storia della sincronizzazione se non esiste."""
    try:
        with database.DatabaseConnection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {SYNC_HISTORY_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_id TEXT UNIQUE NOT NULL,
                    timestamp DATETIME NOT NULL,
                    status TEXT NOT NULL,
                    sync_type TEXT,
                    total_records_sent INTEGER,
                    total_records_received INTEGER,
                    duration_seconds FLOAT,
                    error_message TEXT,
                    server_checksum TEXT,
                    client_checksum TEXT,
                    details JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            logging.debug(f"✓ Tabella {SYNC_HISTORY_TABLE} inizializzata")
    except Exception as e:
        logging.error(f"Errore durante l'inizializzazione della tabella sync_history: {e}")


class SyncMonitor:
    """Monitora e registra tutti gli eventi di sincronizzazione."""
    
    def __init__(self):
        self.sync_id = None
        self.start_time = None
        self.end_time = None
        self.status = None
        self.error_message = None
        self.total_records_sent = 0
        self.total_records_received = 0
        self.server_checksum = None
        self.client_checksum = None
        self.details = {}
        self.events = []
        
        # Inizializza la tabella
        init_sync_history_table()
    
    def start_sync(self, sync_id: str, sync_type: str = "normal"):
        """Registra l'inizio della sincronizzazione."""
        self.sync_id = sync_id
        self.start_time = datetime.now(timezone.utc)
        self.status = "in_progress"
        self.details['sync_type'] = sync_type
        
        logging.info(f"📊 Monitoraggio sincronizzazione iniziato: ID={sync_id}")
    
    def log_event(self, event_type: str, details: str, level: str = "info"):
        """Registra un evento durante la sincronizzazione."""
        event = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'type': event_type,
            'details': details,
            'level': level
        }
        self.events.append(event)
        
        if level == "error":
            logging.error(f"Sync Event: {event_type} - {details}")
        elif level == "warning":
            logging.warning(f"Sync Event: {event_type} - {details}")
        else:
            logging.info(f"Sync Event: {event_type} - {details}")
    
    def add_records_sent(self, table: str, count: int):
        """Registra i record inviati al server."""
        self.total_records_sent += count
        self.details[f'sent_{table}'] = count
        self.log_event('records_sent', f"{count} record inviati per {table}")
    
    def add_records_received(self, table: str, count: int):
        """Registra i record ricevuti dal server."""
        self.total_records_received += count
        self.details[f'received_{table}'] = count
        self.log_event('records_received', f"{count} record ricevuti per {table}")
    
    def set_checksums(self, client_checksum: str, server_checksum: str):
        """Registra i checksum per la validazione."""
        self.client_checksum = client_checksum
        self.server_checksum = server_checksum
        
        if client_checksum == server_checksum:
            self.log_event('checksum_validated', 'Checksum match confermato')
        else:
            self.log_event('checksum_mismatch', f'Client: {client_checksum[:8]}... Server: {server_checksum[:8]}...', 'error')
    
    def end_sync(self, status: str, error_message: str = None):
        """Registra la fine della sincronizzazione."""
        self.end_time = datetime.now(timezone.utc)
        self.status = status
        self.error_message = error_message
        
        duration = (self.end_time - self.start_time).total_seconds() if self.start_time else 0
        
        logging.info(f"📊 Sincronizzazione completata: Status={status}, Duration={duration:.1f}s, Records=(S:{self.total_records_sent} R:{self.total_records_received})")
        
        # Salva la storia
        self._save_to_database(duration)
    
    def _save_to_database(self, duration: float):
        """Salva la storia della sincronizzazione nel database."""
        try:
            with database.DatabaseConnection() as conn:
                cursor = conn.cursor()
                
                cursor.execute(f"""
                    INSERT INTO {SYNC_HISTORY_TABLE} 
                    (sync_id, timestamp, status, sync_type, total_records_sent, 
                     total_records_received, duration_seconds, error_message, 
                     server_checksum, client_checksum, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.sync_id,
                    self.start_time.isoformat() if self.start_time else None,
                    self.status,
                    self.details.get('sync_type'),
                    self.total_records_sent,
                    self.total_records_received,
                    duration,
                    self.error_message,
                    self.server_checksum,
                    self.client_checksum,
                    json.dumps({
                        'events': self.events,
                        'details': self.details
                    })
                ))
                
                conn.commit()
                logging.debug(f"✓ Storia sincronizzazione salvata nel database")
                
        except Exception as e:
            logging.error(f"Errore durante il salvataggio della storia della sincronizzazione: {e}")


def get_sync_history(limit: int = 50) -> List[dict]:
    """Recupera la storia della sincronizzazione."""
    try:
        with database.DatabaseConnection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute(f"""
                SELECT * FROM {SYNC_HISTORY_TABLE}
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
            
    except Exception as e:
        logging.error(f"Errore durante il recupero della storia della sincronizzazione: {e}")
        return []


def get_sync_stats() -> dict:
    """Restituisce statistiche sulla sincronizzazione."""
    try:
        with database.DatabaseConnection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Sync totali
            cursor.execute(f"SELECT COUNT(*) as total FROM {SYNC_HISTORY_TABLE}")
            total_syncs = cursor.fetchone()['total']
            
            # Sync riusciti
            cursor.execute(f"SELECT COUNT(*) as success FROM {SYNC_HISTORY_TABLE} WHERE status = 'success'")
            success_syncs = cursor.fetchone()['success']
            
            # Sync falliti
            cursor.execute(f"SELECT COUNT(*) as failed FROM {SYNC_HISTORY_TABLE} WHERE status = 'error'")
            failed_syncs = cursor.fetchone()['failed']
            
            # Record totali sincronizzati
            cursor.execute(f"""
                SELECT 
                    SUM(total_records_sent) as total_sent,
                    SUM(total_records_received) as total_received,
                    AVG(duration_seconds) as avg_duration
                FROM {SYNC_HISTORY_TABLE}
                WHERE status = 'success'
            """)
            row = cursor.fetchone()
            total_sent = row['total_sent'] or 0
            total_received = row['total_received'] or 0
            avg_duration = row['avg_duration'] or 0
            
            # Ultima sincronizzazione
            cursor.execute(f"""
                SELECT timestamp, status, error_message 
                FROM {SYNC_HISTORY_TABLE}
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            last_sync = cursor.fetchone()
            
            success_rate = (success_syncs / total_syncs * 100) if total_syncs > 0 else 0
            
            return {
                'total_syncs': total_syncs,
                'success_syncs': success_syncs,
                'failed_syncs': failed_syncs,
                'success_rate': success_rate,
                'total_records_sent': int(total_sent),
                'total_records_received': int(total_received),
                'avg_sync_duration': avg_duration,
                'last_sync': {
                    'timestamp': last_sync['timestamp'] if last_sync else None,
                    'status': last_sync['status'] if last_sync else None,
                    'error': last_sync['error_message'] if last_sync else None
                }
            }
            
    except Exception as e:
        logging.error(f"Errore durante il calcolo delle statistiche di sincronizzazione: {e}")
        return {}


def cleanup_old_sync_history(days: int = 90):
    """Elimina la storia della sincronizzazione più vecchia di X giorni."""
    try:
        from datetime import timedelta
        
        with database.DatabaseConnection() as conn:
            cursor = conn.cursor()
            
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            
            cursor.execute(f"""
                DELETE FROM {SYNC_HISTORY_TABLE}
                WHERE timestamp < ?
            """, (cutoff_date,))
            
            deleted = cursor.rowcount
            conn.commit()
            
            if deleted > 0:
                logging.info(f"✓ Eliminati {deleted} record di storia sincronizzazione più vecchi di {days} giorni")
                
    except Exception as e:
        logging.error(f"Errore durante la pulizia della storia della sincronizzazione: {e}")
