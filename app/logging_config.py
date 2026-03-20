# app/logging_config.py
"""
Configurazione centralizzata del sistema di logging.

Miglioramenti:
- Mostra il nome del modulo chiamante (non piu' solo 'root')
- Formattatore emoji-safe per i file (emoji -> simboli ASCII)
- Banner di sessione all'avvio per separare le esecuzioni
- Formato piu' pulito e leggibile con separatori '|'
- Silenzia il rumore DB (open/close/commit) nel file (restano in console)
"""
import logging
import logging.handlers
import sys
import os
import re
from datetime import datetime
from app import config

LOG_DIR = config.LOG_DIR


# ==============================================================================
# FORMATTER PERSONALIZZATI
# ==============================================================================

class EmojiSafeFormatter(logging.Formatter):
    """
    Formatter che sostituisce automaticamente le emoji con simboli ASCII
    leggibili. Evita i caratteri mojibake nei file di log aperti con editor
    che non supportano UTF-8 o in terminali Windows.
    """
    _REPLACEMENTS = {
        '\u2713': '[OK]',   '\u2714': '[OK]',                    # ✓ ✔
        '\u2717': '[FAIL]', '\u2718': '[FAIL]', '\u274c': '[FAIL]',  # ✗ ✘ ❌
        '\u26a0': '[!]',                                          # ⚠
        '\U0001f504': '[SYNC]',                                   # 🔄
        '\U0001f4e1': '[NET]',  '\U0001f310': '[NET]',            # 📡 🌐
        '\U0001f4e5': '[IN]',                                     # 📥
        '\u23f3': '[..]',                                         # ⏳
        '\u23ed': '[SKIP]',                                       # ⏭
        '\U0001f4be': '[SAVE]',                                   # 💾
        '\U0001f511': '[KEY]',                                    # 🔑
        '\U0001f4cb': '[LIST]',                                   # 📋
    }

    # Regex per rimuovere emoji residue non mappate
    _EMOJI_RE = re.compile(
        "["
        "\U0001F300-\U0001FAFF"   # Emoji vari
        "\U00002702-\U000027B0"   # Dingbats
        "\U0000FE00-\U0000FE0F"   # Variation selectors
        "\U0000200D"              # Zero width joiner
        "\U00002600-\U000026FF"   # Misc symbols
        "\U00002700-\U000027BF"   # Dingbats
        "]+", flags=re.UNICODE
    )

    def format(self, record):
        result = super().format(record)
        for emoji_char, ascii_sym in self._REPLACEMENTS.items():
            result = result.replace(emoji_char, ascii_sym)
        result = self._EMOJI_RE.sub('', result)
        return result


class DatabaseNoiseFilter(logging.Filter):
    """
    Filtra i messaggi ripetitivi di apertura/chiusura connessione DB
    dal file handler (restano visibili in console a livello DEBUG).
    """
    _NOISE_KEYWORDS = (
        'Connessione al database aperta',
        'Connessione al database chiusa',
        'Transazione DB completata, modifiche confermate',
    )

    def filter(self, record):
        if record.levelno <= logging.INFO and isinstance(record.msg, str):
            for keyword in self._NOISE_KEYWORDS:
                if keyword in record.msg:
                    return False  # Blocca questo messaggio
        return True


# ==============================================================================
# SETUP PRINCIPALE
# ==============================================================================

def setup_logging():
    """
    Configura il sistema di logging con:
    - File handler: INFO+, emoji-safe, filtro rumore DB
    - Console handler: DEBUG+, formato compatto
    - Banner di sessione all'avvio
    """

    os.makedirs(LOG_DIR, exist_ok=True)

    # --- Formati ---
    # File: data completa + modulo chiamante + messaggio (senza emoji)
    file_formatter = EmojiSafeFormatter(
        '%(asctime)s | %(levelname)-8s | %(module)-20s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console: orario breve + modulo + messaggio (emoji visibili)
    console_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(module)-20s | %(message)s',
        datefmt='%H:%M:%S'
    )

    # --- Root logger ---
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Evita duplicazione handler se setup_logging viene chiamato piu' volte
    if root_logger.handlers:
        root_logger.handlers.clear()

    # --- File handler (INFO+, emoji-safe, filtro DB noise) ---
    log_filename = os.path.join(
        LOG_DIR, f"app_{datetime.now().strftime('%Y-%m-%d')}.log"
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_filename,
        maxBytes=5 * 1024 * 1024,   # 5 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.INFO)
    file_handler.addFilter(DatabaseNoiseFilter())

    # --- Console handler (DEBUG+) ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.DEBUG)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Silenzia logger rumorosi di librerie esterne
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)

    logging.info("Sistema di logging configurato.")


def log_session_start(version: str = None):
    """
    Scrive un banner di sessione nel log per separare visivamente
    le diverse esecuzioni dell'applicazione.
    """
    version = version or config.VERSIONE
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    separator = '=' * 80
    logging.info(separator)
    logging.info(f"  SAFETY TEST MANAGER v{version} - Avvio sessione {now}")
    logging.info(f"  Python {sys.version.split()[0]} | PID {os.getpid()}")
    logging.info(separator)