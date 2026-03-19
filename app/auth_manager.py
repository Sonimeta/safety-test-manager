# app/auth_manager.py

import json
import os
import logging
from app import config
from PySide6.QtCore import QSettings

CURRENT_USER = {
    "username": None,
    "role": None,
    "token": None,
    "full_name": None,
    "last_sync_timestamp": None
}

def get_user_sync_timestamp(username: str) -> str | None:
    """Recupera l'ultimo timestamp di sync per un utente specifico dalle impostazioni persistenti."""
    if not username:
        return None
    settings = QSettings("ELSON META", "SafetyTester")
    return settings.value(f"sync_timestamp_{username}", None)

def set_user_sync_timestamp(username: str, timestamp: str | None):
    """Salva l'ultimo timestamp di sync per un utente specifico nelle impostazioni persistenti."""
    if not username:
        return
    settings = QSettings("ELSON META", "SafetyTester")
    settings.setValue(f"sync_timestamp_{username}", timestamp)

def set_current_user(username: str, role: str, token: str, full_name: str):
    """Imposta l'utente attivo per la sessione corrente e carica il suo timestamp personale."""
    CURRENT_USER["username"] = username
    CURRENT_USER["role"] = role
    CURRENT_USER["token"] = f"Bearer {token}"
    CURRENT_USER["full_name"] = full_name
    # Carica il timestamp specifico per questo utente dalle impostazioni persistenti
    CURRENT_USER["last_sync_timestamp"] = get_user_sync_timestamp(username)

def save_session_to_disk():
    """Salva i dati della sessione corrente (token, ruolo) su file, escludendo il timestamp."""
    session_data = CURRENT_USER.copy()
    session_data.pop('last_sync_timestamp', None)
    with open(config.SESSION_FILE, 'w') as f:
        json.dump(session_data, f, indent=2)

def load_session_from_disk() -> bool:
    """Carica una sessione da file e recupera il timestamp specifico dell'utente."""
    if not os.path.exists(config.SESSION_FILE):
        return False
    try:
        with open(config.SESSION_FILE, 'r') as f:
            session_data = json.load(f)
            if session_data.get("username") and session_data.get("token"):
                CURRENT_USER.update(session_data)
                CURRENT_USER["last_sync_timestamp"] = get_user_sync_timestamp(session_data.get("username"))
                return True
    except (json.JSONDecodeError, KeyError):
        logout()
    return False

def get_auth_headers() -> dict:
    """Restituisce gli header di autorizzazione per le chiamate API."""
    return {"Authorization": CURRENT_USER["token"]} if CURRENT_USER["token"] else {}

def get_current_role() -> str:
    """Restituisce il ruolo dell'utente loggato."""
    return CURRENT_USER["role"]

def get_current_user_info() -> dict:
    """Restituisce l'intero dizionario con le informazioni dell'utente corrente."""
    return CURRENT_USER

def is_logged_in() -> bool:
    """Controlla se un utente è loggato."""
    return CURRENT_USER["token"] is not None

def logout():
    """Esegue il logout, resetta i dati in memoria e cancella il file di sessione."""
    global CURRENT_USER
    CURRENT_USER = {
        "username": None, "role": None, "token": None,
        "full_name": None, "last_sync_timestamp": None
    }
    if os.path.exists(config.SESSION_FILE):
        os.remove(config.SESSION_FILE)

def update_session_timestamp(timestamp_str: str | None):
    """Aggiorna il timestamp per l'utente corrente sia in memoria che nelle impostazioni persistenti."""
    username = CURRENT_USER.get("username")
    if username:
        CURRENT_USER["last_sync_timestamp"] = timestamp_str
        set_user_sync_timestamp(username, timestamp_str)
    else:
        logging.warning("Tentativo di aggiornare il timestamp senza un utente loggato.")