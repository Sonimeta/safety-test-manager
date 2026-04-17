# app/backup_manager.py
import os
import shutil
import logging
import sqlite3
import hashlib
from datetime import datetime
from app import config

# ✅ Usa i percorsi centralizzati in AppData
DB_FILE = config.DB_PATH
BACKUP_DIR = config.BACKUP_DIR
BACKUP_RETENTION_COUNT = 5  # Numero di backup da conservare


def _verify_database_integrity(db_path: str) -> bool:
    """
    Verifica l'integrità del database SQLite.
    
    Args:
        db_path: Percorso del file database
        
    Returns:
        bool: True se il database è integro, False altrimenti
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()[0]
        conn.close()
        
        if result == "ok":
            logging.debug(f"✓ Integrità database verificata: {db_path}")
            return True
        else:
            logging.error(f"✗ Database corrotto: {result}")
            return False
            
    except Exception as e:
        logging.error(f"✗ Errore durante la verifica dell'integrità: {e}")
        return False


def _calculate_backup_checksum(backup_path: str) -> str:
    """Calcola il checksum SHA256 del file di backup."""
    try:
        sha256 = hashlib.sha256()
        with open(backup_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        logging.error(f"Errore nel calcolo del checksum del backup: {e}")
        return ""


def create_backup(backup_type="manual"):
    """
    Crea un backup del file del database con un timestamp e verifica di integrità.
    
    Args:
        backup_type: Tipo di backup ('manual', 'pre_sync', 'auto')
    
    Returns:
        str: Percorso del file di backup creato, None se fallito
    """
    # ✅ Assicurati che la cartella backup esista in AppData
    os.makedirs(BACKUP_DIR, exist_ok=True)

    if not os.path.exists(DB_FILE):
        logging.warning(f"File database '{DB_FILE}' non trovato. Backup saltato.")
        return None

    # Verifica integrità del database prima di fare il backup
    if not _verify_database_integrity(DB_FILE):
        logging.error("✗ Backup annullato: database corrotto")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.splitext(os.path.basename(DB_FILE))[0]  # 'verifiche'
    backup_name = f"{base}_{backup_type}_{timestamp}.db.bak"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    try:
        # Usa copy2 per preservare i metadata del file
        shutil.copy2(DB_FILE, backup_path)
        
        # Verifica l'integrità del backup
        if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
            logging.error(f"✗ Backup creato ma file risulta vuoto o non esistente: {backup_path}")
            return None
        
        # Verifica che il backup sia un database valido
        if not _verify_database_integrity(backup_path):
            logging.error("✗ Il backup non è un database valido")
            return None
        
        # Calcola il checksum del backup
        checksum = _calculate_backup_checksum(backup_path)
        logging.info(f"✓ Backup '{backup_type}' creato con successo: {backup_path}")
        logging.info(f"  Checksum: {checksum[:16]}... Dimensione: {os.path.getsize(backup_path) / 1024:.2f} KB")
        
        _rotate_old_backups()
        return backup_path
            
    except Exception as e:
        logging.error(f"✗ Errore durante la creazione del backup '{backup_type}': {e}", exc_info=True)
        # Tenta di rimuovere il backup incompleto
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except:
                pass
        return None

def _rotate_old_backups():
    """Mantiene solo gli ultimi BACKUP_RETENTION_COUNT backup, elimina i più vecchi."""
    try:
        if not os.path.isdir(BACKUP_DIR):
            return
        backups = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR)
                   if f.lower().endswith(".bak")]
        backups.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        to_remove = backups[BACKUP_RETENTION_COUNT:]
        if to_remove:
            logging.info(f"Rotazione backup: {len(backups)} trovati, rimozione di {len(to_remove)} vecchi backup...")
            for f in to_remove:
                try:
                    size_mb = os.path.getsize(f) / (1024 * 1024)
                    os.remove(f)
                    logging.info(f"Vecchio backup rimosso: {os.path.basename(f)} ({size_mb:.1f} MB)")
                except Exception:
                    logging.warning(f"Impossibile rimuovere backup: {f}", exc_info=True)
    except Exception:
        logging.error("Errore durante la rotazione dei vecchi backup.", exc_info=True)

def restore_from_backup(backup_path):
    """
    Ripristina il database da un file di backup, sovrascrivendo quello corrente.
    Con validazioni di integrità e rollback.
    
    Args:
        backup_path: Percorso del file di backup da ripristinare
        
    Returns:
        bool: True se il ripristino è riuscito, False altrimenti
    """
    try:
        # Verifica che il backup esista e sia valido
        if not os.path.exists(backup_path):
            logging.error(f"✗ File di backup non trovato: {backup_path}")
            return False
            
        if os.path.getsize(backup_path) == 0:
            logging.error(f"✗ File di backup vuoto: {backup_path}")
            return False
        
        # Verifica integrità del backup prima del ripristino
        if not _verify_database_integrity(backup_path):
            logging.error("✗ Il backup non è un database valido - ripristino annullato")
            return False
        
        # Crea un backup del database corrente prima del ripristino (double backup)
        current_backup = create_backup("pre_restore")
        if not current_backup:
            logging.warning("⚠ Impossibile creare backup di sicurezza prima del ripristino")
            # Continua comunque con il ripristino
        
        logging.info(f"🔄 Ripristino in corso dal file: {backup_path}")
        
        # Ripristina il database
        shutil.copy2(backup_path, DB_FILE)
        
        # Verifica che il ripristino sia riuscito
        if not _verify_database_integrity(DB_FILE):
            logging.critical("✗ Errore: database ripristinato ma non valido!")
            
            # Tenta il rollback al backup precedente
            if current_backup:
                logging.warning(f"🔄 Tentativo di rollback al backup precedente: {current_backup}")
                try:
                    shutil.copy2(current_backup, DB_FILE)
                    if _verify_database_integrity(DB_FILE):
                        logging.warning("✓ Rollback completato con successo")
                        return False
                except Exception as e:
                    logging.critical(f"✗ Errore durante il rollback: {e}")
            
            return False
        
        logging.warning(f"✓ Database ripristinato con successo dal file: {backup_path}")
        
        # Verifica il backup di sicurezza
        if current_backup:
            logging.info(f"✓ Backup di sicurezza disponibile: {current_backup}")
        
        return True
        
    except Exception as e:
        logging.critical(f"✗ Errore critico durante il ripristino dal backup: {backup_path} - {e}", exc_info=True)
        return False

def get_latest_backup(backup_type=None):
    """
    Ottiene il percorso del backup più recente.
    
    Args:
        backup_type: Se specificato, filtra per tipo di backup (es. 'pre_sync')
        
    Returns:
        str: Percorso del backup più recente, None se non trovato
    """
    try:
        if not os.path.isdir(BACKUP_DIR):
            return None
            
        backups = [
            os.path.join(BACKUP_DIR, f) 
            for f in os.listdir(BACKUP_DIR)
            if f.lower().endswith(".bak")
        ]
        
        if backup_type:
            backups = [b for b in backups if f"_{backup_type}_" in os.path.basename(b)]
        
        if not backups:
            return None
            
        # Ordina per data di modifica (più recente prima)
        backups.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return backups[0]
        
    except Exception as e:
        logging.error(f"Errore durante la ricerca del backup più recente: {e}")
        return None

def list_all_backups(backup_type=None):
    """
    Elenca tutti i backup disponibili.
    
    Args:
        backup_type: Se specificato, filtra per tipo di backup
        
    Returns:
        list: Lista di tuple (backup_path, size_kb, datetime, integrity_ok)
    """
    try:
        if not os.path.isdir(BACKUP_DIR):
            return []
        
        backups = [
            os.path.join(BACKUP_DIR, f)
            for f in os.listdir(BACKUP_DIR)
            if f.lower().endswith(".bak")
        ]
        
        if backup_type:
            backups = [b for b in backups if f"_{backup_type}_" in os.path.basename(b)]
        
        result = []
        for backup_path in backups:
            try:
                size_kb = os.path.getsize(backup_path) / 1024
                mtime = datetime.fromtimestamp(os.path.getmtime(backup_path))
                is_valid = _verify_database_integrity(backup_path)
                result.append((backup_path, size_kb, mtime, is_valid))
            except Exception as e:
                logging.warning(f"Errore nell'analisi del backup {backup_path}: {e}")
        
        # Ordina per data (più recente primo)
        result.sort(key=lambda x: x[2], reverse=True)
        return result
        
    except Exception as e:
        logging.error(f"Errore durante l'elenco dei backup: {e}")
        return []


def get_backup_stats() -> dict:
    """
    Restituisce statistiche sui backup disponibili.
    
    Returns:
        dict: Statistiche con numero, dimensione totale, backup più recente, etc.
    """
    try:
        backups = list_all_backups()
        
        if not backups:
            return {
                'total_count': 0,
                'total_size_mb': 0,
                'latest_backup': None,
                'valid_count': 0,
                'invalid_count': 0
            }
        
        total_size = sum(b[1] for b in backups)
        valid_count = sum(1 for b in backups if b[3])
        invalid_count = len(backups) - valid_count
        latest = backups[0] if backups else None
        
        return {
            'total_count': len(backups),
            'total_size_mb': total_size / 1024,
            'latest_backup': latest[0] if latest else None,
            'latest_timestamp': latest[2] if latest else None,
            'valid_count': valid_count,
            'invalid_count': invalid_count,
            'backups': backups
        }
        
    except Exception as e:
        logging.error(f"Errore nel calcolo delle statistiche dei backup: {e}")
        return {}