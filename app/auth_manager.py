# app/auth_manager.py

import json
import os
import logging
from datetime import datetime, timezone
from jose import jwt, JWTError
from app import config
from PySide6.QtCore import QSettings

CURRENT_USER = {
    "username": None,
    "role": None,
    "token": None,
    "full_name": None,
    "sede": None,
    "last_sync_timestamp": None
}

def _decode_token_claims(token_str: str) -> dict | None:
    """Decodifica in modo sicuro i claims del JWT token senza fidarsi del JSON in chiaro."""
    if not token_str:
        return None
    raw_token = token_str.replace("Bearer ", "").strip()
    try:
        payload = jwt.decode(raw_token, key="", options={"verify_signature": False})
        return payload
    except Exception as e:
        logging.error(f"[auth_manager] Errore decodifica token JWT: {e}")
        return None

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

def set_current_user(username: str, role: str, token: str, full_name: str, sede: str = None):
    """Imposta l'utente attivo per la sessione corrente con validazione claims JWT."""
    raw_token = (token or "").replace("Bearer ", "").strip()
    claims = _decode_token_claims(raw_token) if raw_token else None
    
    if claims:
        effective_username = claims.get("sub") or username
        effective_role = claims.get("role") or role
        effective_full_name = claims.get("full_name") or full_name or effective_username
        effective_sede = claims.get("sede") if "sede" in claims else sede
    else:
        effective_username = username
        effective_role = role
        effective_full_name = full_name
        effective_sede = sede

    CURRENT_USER["username"] = effective_username
    CURRENT_USER["role"] = effective_role
    CURRENT_USER["token"] = f"Bearer {raw_token}" if raw_token else None
    CURRENT_USER["full_name"] = effective_full_name
    CURRENT_USER["sede"] = effective_sede.strip().upper() if effective_sede and str(effective_sede).strip() else None
    CURRENT_USER["last_sync_timestamp"] = get_user_sync_timestamp(effective_username)

def save_session_to_disk():
    """Salva i dati della sessione corrente (token, ruolo, sede) su file, escludendo il timestamp."""
    session_data = CURRENT_USER.copy()
    session_data.pop('last_sync_timestamp', None)
    with open(config.SESSION_FILE, 'w') as f:
        json.dump(session_data, f, indent=2)

def load_session_from_disk() -> bool:
    """
    Carica e valida la sessione da file.
    
    SICUREZZA ANTI-TAMPERING:
    L'identità dell'utente (ruolo, username, sede, nome) viene SEMPRE estratta esclusivamente
    dai claims del token JWT rilasciato e firmato dal server.
    Se un utente manomette a mano il file session.json (es. modificando "role": "admin"),
    la discrepanza viene rilevata immediatamente, la sessione viene distrutta e viene forzato il re-login.
    """
    if not os.path.exists(config.SESSION_FILE):
        return False
    try:
        with open(config.SESSION_FILE, 'r') as f:
            session_data = json.load(f)

        token_str = session_data.get("token")
        if not token_str:
            logout()
            return False

        claims = _decode_token_claims(token_str)
        if not claims:
            logging.warning("[SECURITY] Token JWT non valido o corrotto in session.json. Sessione invalidata.")
            logout()
            return False

        # Verifica scadenza token
        exp = claims.get("exp")
        if exp and datetime.now(timezone.utc).timestamp() > float(exp):
            logging.info("[auth_manager] Token JWT scaduto. Sessione terminata.")
            logout()
            return False

        jwt_username = claims.get("sub")
        jwt_role = claims.get("role")
        jwt_full_name = claims.get("full_name") or session_data.get("full_name") or jwt_username
        jwt_sede = claims.get("sede") if "sede" in claims else session_data.get("sede")

        # Controllo anti-tampering su ruolo e username
        saved_role = session_data.get("role")
        saved_username = session_data.get("username")
        if (saved_role and saved_role != jwt_role) or (saved_username and saved_username != jwt_username):
            logging.critical(
                f"[SECURITY ALERT] Manomissione rilevata in session.json! "
                f"Ruolo file='{saved_role}' vs Ruolo JWT='{jwt_role}'. Sessione distrutta per sicurezza."
            )
            logout()
            return False

        # Assegna esclusivamente i dati certificati dal token JWT
        raw_token = token_str.replace("Bearer ", "").strip()
        CURRENT_USER["username"] = jwt_username
        CURRENT_USER["role"] = jwt_role
        CURRENT_USER["token"] = f"Bearer {raw_token}"
        CURRENT_USER["full_name"] = jwt_full_name
        CURRENT_USER["sede"] = jwt_sede.strip().upper() if jwt_sede and str(jwt_sede).strip() else None
        CURRENT_USER["last_sync_timestamp"] = get_user_sync_timestamp(jwt_username)

        return bool(CURRENT_USER["username"] and CURRENT_USER["token"])

    except (json.JSONDecodeError, KeyError, Exception) as e:
        logging.error(f"[auth_manager] Errore durante il caricamento sessione: {e}")
        logout()
        return False

def get_auth_headers() -> dict:
    """Restituisce gli header di autorizzazione per le chiamate API."""
    return {"Authorization": CURRENT_USER["token"]} if CURRENT_USER["token"] else {}

def get_current_role() -> str:
    """Restituisce il ruolo dell'utente loggato."""
    return CURRENT_USER["role"]

def get_current_username() -> str:
    """Restituisce lo username dell'utente loggato."""
    return CURRENT_USER["username"] or ""

def get_current_sede() -> str | None:
    """Restituisce la sede dell'utente loggato."""
    return CURRENT_USER.get("sede")

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
        "full_name": None, "sede": None, "last_sync_timestamp": None
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