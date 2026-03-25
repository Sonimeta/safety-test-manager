# app/config.py
import json
from PySide6.QtWidgets import QMessageBox
from .data_models import Limit, Test, VerificationProfile
from .functional_models import (
    FunctionalField,
    FunctionalProfile,
    FunctionalRowDefinition,
    FunctionalSection,
)
import logging
import os
import sys
import configparser

def get_base_dir():
    """Restituisce il percorso della cartella dell'eseguibile."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
def get_app_data_dir():
    """
    Restituisce il percorso della cartella dati dell'applicazione, creandola se non esiste.
    (es. C:\\Users\\TuoNome\\AppData\\Roaming\\SafetyTestManager)
    """
    # Il nome della tua azienda/applicazione per la cartella dati
    APP_NAME = "SafetyTestManager"
    
    # Trova la cartella AppData
    if sys.platform == "win32":
        app_data_path = os.path.join(os.environ['APPDATA'], APP_NAME)
    else: # Per Mac/Linux
        app_data_path = os.path.join(os.path.expanduser('~'), '.' + APP_NAME)
        
    # Crea la cartella se non esiste
    os.makedirs(app_data_path, exist_ok=True)
    return app_data_path
VERSIONE = "10.0.6"
BASE_DIR = get_base_dir() # La cartella del programma
APP_DATA_DIR = get_app_data_dir() # La cartella dei dati utente

# I file di dati ora vengono cercati/creati nella cartella AppData
DB_PATH = os.path.join(APP_DATA_DIR, "verifiche.db")
SESSION_FILE = os.path.join(APP_DATA_DIR, "session.json")
BACKUP_DIR = os.path.join(APP_DATA_DIR, "backups")
LOG_DIR = os.path.join(APP_DATA_DIR, "logs")
LOCK_FILE_DIR = os.path.join(APP_DATA_DIR, "sync.lock")
ATTACHMENTS_DIR = os.path.join(APP_DATA_DIR, "attachments")

# Crea la cartella allegati se non esiste
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
# Il file di configurazione viene ancora letto dalla cartella del programma
CONFIG_INI_PATH = os.path.join(BASE_DIR, "config.ini")
# --- FINE NUOVA DEFINIZIONE DEI PERCORSI ---


PLACEHOLDER_SERIALS = {
    "N.P.", "NP", "N/A", "NA", "NON PRESENTE", "-", 
    "SENZA SN", "NO SN", "MANCA SN", "N/D", "MANCANTE", "ND", "N.D."
}

def load_server_url():
    """Legge l'URL del server da config.ini."""
    parser = configparser.ConfigParser()
    if os.path.exists(CONFIG_INI_PATH):
        parser.read(CONFIG_INI_PATH)
        return parser.get('server', 'url', fallback='http://localhost:8000')
    return 'http://localhost:8000'

def load_ssl_ca_cert():
    """
    Legge il percorso del certificato CA personalizzato da config.ini.
    Serve per connessioni HTTPS con certificato self-signed.
    
    Returns:
        str | None: Percorso assoluto al file .crt, o None se non configurato.
    """
    parser = configparser.ConfigParser()
    if os.path.exists(CONFIG_INI_PATH):
        parser.read(CONFIG_INI_PATH)
        cert_path = parser.get('server', 'ssl_ca_cert', fallback=None)
        if cert_path:
            # Se il percorso è relativo, lo risolve rispetto alla cartella del programma
            if not os.path.isabs(cert_path):
                cert_path = os.path.join(BASE_DIR, cert_path)
            if os.path.isfile(cert_path):
                logging.info(f"🔒 Certificato SSL CA caricato: {cert_path}")
                return cert_path
            else:
                logging.warning(f"⚠ Certificato SSL CA non trovato: {cert_path}")
    return None

SERVER_URL = load_server_url()
SSL_CA_CERT = load_ssl_ca_cert()
PROFILES = {}
FUNCTIONAL_PROFILES = {}

# --- INIZIO AGGIUNTA PER UPDATER ---
def load_update_url():
    """Legge l'URL per il check degli aggiornamenti da config.ini."""
    parser = configparser.ConfigParser()
    if os.path.exists(CONFIG_INI_PATH):
        parser.read(CONFIG_INI_PATH)
        return parser.get('updater', 'url', fallback=None)
    return None

UPDATE_URL = load_update_url()
# --- FINE AGGIUNTA PER UPDATER ---

# --- INIZIO AGGIUNTA PER AUTO SYNC ---
def load_sync_interval() -> int:
    """
    Legge l'intervallo di sincronizzazione automatica da config.ini.
    
    Returns:
        Intervallo in minuti. 0 significa disabilitato.
        Default: 10 minuti.
    """
    parser = configparser.ConfigParser()
    if os.path.exists(CONFIG_INI_PATH):
        parser.read(CONFIG_INI_PATH)
        try:
            interval = parser.getint('sync', 'interval_minutes', fallback=10)
            return max(0, interval)  # Assicura che non sia negativo
        except (ValueError, configparser.Error):
            logging.warning("Valore non valido per sync.interval_minutes, uso default 10 minuti")
            return 10
    return 10

SYNC_INTERVAL_MINUTES = load_sync_interval()
# --- FINE AGGIUNTA PER AUTO SYNC ---

def load_qss_file(filename: str) -> str:
    """
    Carica un file QSS dalla cartella styles.
    
    Args:
        filename: Nome del file QSS (es. 'main.qss', 'login.qss')
    
    Returns:
        Contenuto del file QSS come stringa, o stringa vuota se il file non esiste
    """
    styles_dir = os.path.join(BASE_DIR, "styles")
    qss_path = os.path.join(styles_dir, filename)
    
    try:
        if os.path.exists(qss_path):
            with open(qss_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            logging.warning(f"File QSS non trovato: {qss_path}")
            return ""
    except Exception as e:
        logging.error(f"Errore nel caricamento del file QSS {filename}: {e}")
        return ""

def load_stylesheet(*filenames: str) -> str:
    """
    Carica e combina più file QSS.
    
    Args:
        *filenames: Nomi dei file QSS da caricare e combinare
    
    Returns:
        Contenuto combinato dei file QSS
    """
    stylesheets = []
    for filename in filenames:
        content = load_qss_file(filename)
        if content:
            stylesheets.append(content)
    return "\n".join(stylesheets)

# Carica gli stili dai file QSS esterni
MODERN_STYLESHEET = load_stylesheet("main.qss", "components.qss")

# Gestione temi
def get_theme_stylesheet(theme: str = "light") -> str:
    """
    Carica il foglio di stile in base al tema selezionato.
    
    Args:
        theme: "light" o "dark"
    
    Returns:
        Contenuto combinato dei file QSS per il tema selezionato
    """
    if theme == "dark":
        return load_stylesheet("dark.qss", "components.qss")
    else:
        return load_stylesheet("main.qss", "components.qss")


def get_current_theme() -> str:
    """
    Ottiene il tema corrente dalle impostazioni dell'applicazione.
    
    Returns:
        "light" o "dark"
    """
    from PySide6.QtCore import QSettings
    settings = QSettings("ELSON META", "SafetyTester")
    return settings.value("theme", "light")


def get_current_stylesheet() -> str:
    """
    Ottiene lo stylesheet corretto per il tema corrente.
    
    Returns:
        Contenuto combinato dei file QSS per il tema corrente
    """
    return get_theme_stylesheet(get_current_theme())


def apply_theme_to_widget(widget) -> None:
    """
    Applica il tema corrente a un widget (es. dialog).
    Utile per i dialog che vengono creati al di fuori della MainWindow.
    
    Args:
        widget: Il widget a cui applicare il tema
    """
    from PySide6.QtWidgets import QApplication, QWidget
    stylesheet = get_current_stylesheet()
    widget.setStyleSheet(stylesheet)
    
    # Forza il refresh dei widget figli
    try:
        for child in widget.findChildren(QWidget):
            try:
                child.style().unpolish(child)
                child.style().polish(child)
                child.repaint()
            except Exception:
                pass
    except Exception:
        pass

def load_verification_profiles(file_path=None):
    import database
    global PROFILES
    PROFILES = {}
    try:
        # La logica ora chiama la nuova funzione del database
        PROFILES = database.get_all_profiles_from_db()
        if not PROFILES:
            logging.warning("Nessun profilo di verifica trovato nel database locale.")

        return True
    except Exception as e:
        # Rilancia qualsiasi eccezione del database
        logging.error("Errore critico durante il caricamento dei profili dal database.", exc_info=True)
        raise e


def load_functional_profiles():
    import database

    global FUNCTIONAL_PROFILES
    FUNCTIONAL_PROFILES = {}
    try:
        FUNCTIONAL_PROFILES = database.get_all_functional_profiles_from_db()
        if not FUNCTIONAL_PROFILES:
            logging.warning("Nessun profilo funzionale trovato nel database locale.")
        return True
    except Exception as e:
        logging.error(
            "Errore critico durante il caricamento dei profili funzionali dal database.",
            exc_info=True,
        )
        raise e