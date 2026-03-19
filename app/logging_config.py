# app/logging_config.py
import logging
import logging.handlers
import sys
import os
from datetime import datetime
from app import config

LOG_DIR = config.LOG_DIR

def setup_logging():
    """Configura il sistema di logging per salvare su file e mostrare in console."""
    
    # Crea la cartella dei log se non esiste
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    # Formato del messaggio di log
    log_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)-8s - %(name)-15s - %(message)s'
    )

    # Configura il logger principale (root logger)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Cattura tutti i messaggi dal livello DEBUG in su

    # 1. Handler per salvare i log su un file giornaliero
    log_filename = os.path.join(LOG_DIR, f"app_{datetime.now().strftime('%Y-%m-%d')}.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_filename, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.INFO)  # Salva nel file solo i messaggi da INFO in su

    # 2. Handler per mostrare i log nella console (utile durante lo sviluppo)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.DEBUG) # Mostra tutto in console

    # Aggiungi gli handler al root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.info("Sistema di logging configurato.")