# app/workers/sync_worker.py (Versione Robusta con Backoff Esponenziale)
from PySide6.QtCore import QObject, Signal
from app import sync_manager
import logging
import time
import random

class SyncWorker(QObject):
    """
    Worker per eseguire la sincronizzazione in background con retry intelligente.
    """
    finished = Signal(str)
    error = Signal(str)
    conflict = Signal(list)
    auth_error = Signal(str)  # Sessione scaduta / token non valido
    progress = Signal(str)  # Nuovo segnale per aggiornamenti di progresso
    success_with_conflicts = Signal(str)  # Sync OK ma con conflitti da risolvere

    def __init__(self, full_sync=False):
        super().__init__()
        self.full_sync = full_sync
        self.max_retries = 3
        self.base_delay = 5  # Secondi base per il backoff esponenziale

    def run(self):
        """
        Esegue la sincronizzazione con retry automatico e backoff esponenziale.
        
        Il backoff esponenziale aumenta il tempo di attesa tra i tentativi
        per evitare di sovraccaricare il server in caso di problemi.
        """
        logging.info(f"🔄 SyncWorker avviato (Full Sync: {self.full_sync})")
        self.progress.emit("Avvio sincronizzazione...")

        for attempt in range(self.max_retries):
            try:
                attempt_num = attempt + 1
                logging.info(f"📡 Tentativo {attempt_num}/{self.max_retries}...")
                self.progress.emit(f"Tentativo {attempt_num}/{self.max_retries}...")
                
                # Esegui la sincronizzazione
                status, data = sync_manager.run_sync(full_sync=self.full_sync)
                
                # Gestione casi speciali
                if status is None:
                    logging.warning("⚠ Sincronizzazione già in corso, worker terminato")
                    return

                if status == "success":
                    logging.info(f"✓ Sincronizzazione completata al tentativo {attempt_num}")
                    self.finished.emit(data)
                    return

                if status == "success_with_conflicts":
                    logging.info(f"✓ Sincronizzazione completata con conflitti al tentativo {attempt_num}")
                    self.success_with_conflicts.emit(data)
                    return

                if status == "conflict":
                    logging.warning(f"⚠ Conflitti rilevati al tentativo {attempt_num}")
                    self.conflict.emit(data)
                    return

                if status == "auth_error":
                    # Errore di autenticazione: nessun retry, si richiede nuovo login
                    logging.error("✗ Errore di autenticazione durante la sincronizzazione: sessione scaduta o non valida")
                    self.auth_error.emit(data)
                    return

                # Gestione errori con retry
                if status == "error":
                    logging.warning(f"⚠ Tentativo {attempt_num} fallito: {data}")
                    
                    # Se è l'ultimo tentativo, notifica l'errore
                    if attempt_num >= self.max_retries:
                        logging.error(f"✗ Tutti i {self.max_retries} tentativi falliti")
                        self.error.emit(f"Sincronizzazione fallita dopo {self.max_retries} tentativi.\n\nUltimo errore:\n{data}")
                        return
                    
                    # Calcola il delay con backoff esponenziale + jitter
                    # Formula: base_delay * (2 ^ attempt) + random jitter
                    exponential_delay = self.base_delay * (2 ** attempt)
                    jitter = random.uniform(0, exponential_delay * 0.1)  # 10% di jitter
                    total_delay = exponential_delay + jitter
                    
                    # Limita il delay massimo a 60 secondi
                    total_delay = min(total_delay, 60)
                    
                    logging.info(f"⏳ Attesa di {total_delay:.1f} secondi prima del prossimo tentativo...")
                    self.progress.emit(f"Nuovo tentativo tra {int(total_delay)} secondi...")
                    
                    # Attesa con controllo ogni secondo per permettere cancellazione
                    for i in range(int(total_delay)):
                        time.sleep(1)
                        remaining = int(total_delay) - i
                        if remaining % 5 == 0 and remaining > 0:
                            self.progress.emit(f"Nuovo tentativo tra {remaining} secondi...")
                    
                    continue
                
                # Stato imprevisto
                logging.error(f"✗ Stato di sincronizzazione non riconosciuto: {status}")
                self.error.emit(f"Errore: stato non riconosciuto '{status}'")
                return
                
            except Exception as e:
                # Gestione errori imprevisti nel worker stesso
                logging.error(f"✗ Errore imprevisto nel worker (tentativo {attempt + 1})", exc_info=True)
                
                if attempt + 1 >= self.max_retries:
                    self.error.emit(f"Errore critico dopo {self.max_retries} tentativi:\n{str(e)}\n\nControllare i log per dettagli.")
                    return
                
                # Backoff anche per errori imprevisti
                delay = self.base_delay * (2 ** attempt)
                logging.info(f"⏳ Attesa di {delay} secondi dopo errore imprevisto...")
                time.sleep(delay)
        
        # Questo punto non dovrebbe mai essere raggiunto
        logging.error("✗ Worker terminato in modo anomalo")
        self.error.emit("Sincronizzazione fallita: tutti i tentativi esauriti")