# examples/sync_improvements_usage.py
"""
Esempi di come utilizzare il nuovo sistema di sincronizzazione migliorato.
"""

import logging
from app import config, sync_manager, sync_monitor
from app.backup_manager import (
    list_all_backups, 
    get_backup_stats,
    restore_from_backup
)

def example_basic_sync():
    """Esempio: Sincronizzazione base con il nuovo sistema."""
    
    logging.info("=== EXAMPLE: Sincronizzazione Base ===")
    
    # Esegui sincronizzazione con retry automatico
    status, message = sync_manager.run_sync(full_sync=False)
    
    logging.info(f"Risultato: {status}")
    logging.info(f"Messaggio: {message}")


def example_full_sync():
    """Esempio: Full sync (scarica tutto dal server)."""
    
    logging.info("=== EXAMPLE: Full Sync ===")
    
    # Full sync con backup di sicurezza
    status, message = sync_manager.run_sync(full_sync=True)
    
    logging.info(f"Risultato: {status}")
    logging.info(f"Messaggio: {message}")


def example_check_backup_status():
    """Esempio: Verifica stato dei backup."""
    
    logging.info("=== EXAMPLE: Stato Backup ===")
    
    # Ottieni statistiche dei backup
    stats = get_backup_stats()
    
    logging.info(f"Numero backup: {stats.get('total_count', 0)}")
    logging.info(f"Dimensione totale: {stats.get('total_size_mb', 0):.2f} MB")
    logging.info(f"Backup validi: {stats.get('valid_count', 0)}")
    logging.info(f"Backup invalidi: {stats.get('invalid_count', 0)}")
    
    # Lista tutti i backup
    backups = list_all_backups()
    for backup_path, size_kb, mtime, is_valid in backups[:5]:  # Primi 5
        status = "✓" if is_valid else "✗"
        logging.info(f"{status} {mtime.strftime('%Y-%m-%d %H:%M')} - {size_kb:.0f}KB - {backup_path}")


def example_sync_history():
    """Esempio: Verifica cronologia sincronizzazioni."""
    
    logging.info("=== EXAMPLE: Cronologia Sincronizzazioni ===")
    
    # Ottieni statistiche generali
    stats = sync_monitor.get_sync_stats()
    
    logging.info(f"Sincronizzazioni totali: {stats.get('total_syncs', 0)}")
    logging.info(f"Riuscite: {stats.get('success_syncs', 0)}")
    logging.info(f"Fallite: {stats.get('failed_syncs', 0)}")
    logging.info(f"Tasso successo: {stats.get('success_rate', 0):.1f}%")
    logging.info(f"Record inviati totali: {stats.get('total_records_sent', 0)}")
    logging.info(f"Record ricevuti totali: {stats.get('total_records_received', 0)}")
    logging.info(f"Durata media: {stats.get('avg_sync_duration', 0):.1f}s")
    
    # Ultima sincronizzazione
    last_sync = stats.get('last_sync', {})
    if last_sync.get('timestamp'):
        logging.info(f"\nUltima sincronizzazione:")
        logging.info(f"  Timestamp: {last_sync.get('timestamp')}")
        logging.info(f"  Status: {last_sync.get('status')}")
        if last_sync.get('error'):
            logging.info(f"  Errore: {last_sync.get('error')}")
    
    # Cronologia dettagliata
    history = sync_monitor.get_sync_history(limit=10)
    logging.info(f"\nUltimi 10 sync:")
    for sync in history:
        logging.info(f"  {sync['timestamp']} - {sync['status']} ({sync['duration_seconds']:.1f}s)")


def example_restore_backup():
    """Esempio: Ripristino da backup."""
    
    logging.info("=== EXAMPLE: Ripristino da Backup ===")
    
    # Ottieni il backup più recente
    backups = list_all_backups()
    
    if not backups:
        logging.warning("Nessun backup disponibile")
        return
    
    backup_path, size_kb, mtime, is_valid = backups[0]
    
    if not is_valid:
        logging.error("Il backup non è valido")
        return
    
    logging.info(f"Ripristino da: {backup_path}")
    logging.info(f"Data: {mtime}")
    logging.info(f"Dimensione: {size_kb:.0f}KB")
    
    # Ripristina il backup
    success = restore_from_backup(backup_path)
    
    if success:
        logging.info("✓ Ripristino completato con successo")
    else:
        logging.error("✗ Ripristino fallito")


def example_monitor_sync():
    """Esempio: Monitoraggio manuale di una sincronizzazione."""
    
    import uuid
    from datetime import datetime
    
    logging.info("=== EXAMPLE: Monitoraggio Manuale ===")
    
    # Crea un monitor
    monitor = sync_monitor.SyncMonitor()
    
    # Simula una sincronizzazione
    sync_id = str(uuid.uuid4())[:8]
    monitor.start_sync(sync_id, sync_type="manual")
    
    try:
        # Simula invio dati
        logging.info("Inviando dati...")
        monitor.add_records_sent("customers", 10)
        monitor.add_records_sent("devices", 25)
        
        # Simula ricezione dati
        logging.info("Ricevendo dati...")
        monitor.add_records_received("verifications", 50)
        
        # Simula checksum
        monitor.set_checksums(
            client_checksum="abc123def456",
            server_checksum="abc123def456"
        )
        
        # Completamento
        monitor.end_sync(status="success")
        logging.info("✓ Sincronizzazione monitorata completata")
        
    except Exception as e:
        logging.error(f"Errore durante il monitoraggio: {e}")
        monitor.end_sync(status="error", error_message=str(e))


def example_handle_sync_error():
    """Esempio: Gestione errori di sincronizzazione."""
    
    logging.info("=== EXAMPLE: Gestione Errori ===")
    
    try:
        status, message = sync_manager.run_sync(full_sync=False)
        
        if status == "success":
            logging.info(f"✓ Sincronizzazione riuscita: {message}")
            
        elif status == "conflict":
            logging.warning(f"⚠ Conflitti rilevati: {message}")
            # Qui si potrebbe chiedere all'utente come risolverli
            
        elif status == "auth_error":
            logging.error(f"✗ Errore di autenticazione: {message}")
            # Occorre fare login di nuovo
            
        else:
            logging.error(f"✗ Errore di sincronizzazione: {message}")
            # Controllare i backup e riprovare più tardi
            
    except Exception as e:
        logging.critical(f"Errore imprevisto: {e}")


def example_cleanup_old_history():
    """Esempio: Pulizia della cronologia vecchia."""
    
    logging.info("=== EXAMPLE: Pulizia Cronologia ===")
    
    # Elimina record di sincronizzazione più vecchi di 30 giorni
    sync_monitor.cleanup_old_sync_history(days=30)
    
    logging.info("✓ Pulizia completata")


if __name__ == "__main__":
    from app.logging_config import setup_logging
    
    # Configura logging
    setup_logging()
    
    # Scegli quale esempio eseguire
    print("Esempi disponibili:")
    print("1. Sincronizzazione base")
    print("2. Full sync")
    print("3. Stato backup")
    print("4. Cronologia sync")
    print("5. Ripristino backup")
    print("6. Monitoraggio manuale")
    print("7. Gestione errori")
    print("8. Pulizia cronologia")
    
    choice = input("Seleziona numero (1-8): ").strip()
    
    examples = {
        "1": example_basic_sync,
        "2": example_full_sync,
        "3": example_check_backup_status,
        "4": example_sync_history,
        "5": example_restore_backup,
        "6": example_monitor_sync,
        "7": example_handle_sync_error,
        "8": example_cleanup_old_history,
    }
    
    if choice in examples:
        examples[choice]()
    else:
        print("Scelta non valida")
