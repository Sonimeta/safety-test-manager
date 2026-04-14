# app/updater.py
import logging
import os
import subprocess
import sys
import tempfile
from urllib.parse import urljoin
import requests
from packaging import version
import re
import shutil

from PySide6.QtCore import QThread, Signal
from app import config


class UpdateCheckWorker(QThread):
    """
    Worker che controlla la disponibilità di aggiornamenti in background.
    Emette un segnale con le info se un aggiornamento è disponibile.
    """
    update_available = Signal(dict)   # Emesso con le info sull'aggiornamento
    no_update = Signal()              # Emesso se non ci sono aggiornamenti
    check_error = Signal(str)         # Emesso in caso di errore (silenzioso)

    def __init__(self, update_url: str, parent=None):
        super().__init__(parent)
        self.update_url = update_url

    def run(self):
        try:
            checker = UpdateChecker(self.update_url)
            update_info = checker.check_for_updates()
            if update_info:
                self.update_available.emit(update_info)
            else:
                self.no_update.emit()
        except Exception as e:
            logging.debug(f"Controllo aggiornamenti in background fallito: {e}")
            self.check_error.emit(str(e))


class UpdateChecker:
    """
    Gestisce il controllo, il download e l'esecuzione degli aggiornamenti dell'applicazione.
    """

    def __init__(self, update_url):
        if not update_url:
            raise ValueError("L'URL per il controllo degli aggiornamenti non è configurato.")
        self.update_url = update_url
        self.update_info = None

    def check_for_updates(self) -> dict | None:
        """
        Controlla se è disponibile una nuova versione.

        Returns:
            Un dizionario con le informazioni sull'aggiornamento se disponibile, altrimenti None.
        """
        try:
            logging.info(f"Controllo aggiornamenti da: {self.update_url}")
            response = requests.get(self.update_url, timeout=10)
            response.raise_for_status()
            self.update_info = response.json()

            current_v = version.parse(config.VERSIONE)
            latest_v = version.parse(self.update_info['latest_version'])

            logging.info(f"Versione corrente: {current_v}, Ultima versione: {latest_v}")

            if latest_v > current_v:
                return self.update_info
            return None

        except requests.RequestException as e:
            logging.error(f"Errore durante il controllo degli aggiornamenti: {e}")
            raise ConnectionError(f"Impossibile connettersi al server degli aggiornamenti.\n{e}")
        except (KeyError, version.InvalidVersion) as e:
            logging.error(f"Formato del file di versione non valido: {e}")
            raise ValueError(f"Il file di versione remoto non è valido.\n{e}")

    def download_update(self, download_url: str, progress_callback) -> str:
        """
        Scarica il file di aggiornamento, gestendo la conferma di Google Drive
        inviando i parametri del form con una richiesta GET.
        """
        try:
            with requests.Session() as session:
                logging.info(f"Avvio download da: {download_url}")
                
                with session.get(download_url, stream=True, timeout=30) as response:
                    response.raise_for_status()
                    final_response = None

                    content_type = response.headers.get('Content-Type', '')
                    if 'text/html' in content_type:
                        logging.info("Pagina di conferma rilevata. Estraggo i dati del modulo.")
                        html_content = response.text
                        
                        action_match = re.search(r'<form.*?action="([^"]+)"', html_content)
                        if not action_match:
                            raise IOError("Impossibile trovare 'action' del modulo di conferma.")
                        
                        action_url_relative = action_match.group(1).replace('&amp;', '&')
                        action_url_absolute = urljoin(response.url, action_url_relative)

                        inputs = re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]+)">', html_content)
                        form_data = {name: value for name, value in inputs}

                        if not form_data:
                            raise IOError("Impossibile trovare i dati del modulo di conferma.")

                        logging.info(f"Invio richiesta GET con parametri a: {action_url_absolute}")

                        # --- LA CORREZIONE FINALE: GET con i dati del form come parametri ---
                        final_response = session.get(action_url_absolute, params=form_data, stream=True, timeout=120)
                        final_response.raise_for_status()
                    else:
                        logging.info("Download diretto, nessuna pagina di conferma rilevata.")
                        final_response = response

                    # --- LOGICA DI DOWNLOAD ---
                    total_size = int(final_response.headers.get('content-length', 0))
                    downloaded_size = 0
                    
                    with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=".exe", prefix="SafetyTestManager_Update_") as f_out:
                        file_path = f_out.name
                        chunk_size = 8192
                        for chunk in final_response.iter_content(chunk_size=chunk_size):
                            f_out.write(chunk)
                            downloaded_size += len(chunk)
                            if total_size > 0:
                                progress = (downloaded_size / total_size) * 100
                                progress_callback(int(progress))
                    
                    if downloaded_size < 1024*1024:
                        raise IOError(f"Download fallito: il file scaricato è troppo piccolo ({downloaded_size} bytes).")

                    progress_callback(100)
                    logging.info(f"Aggiornamento scaricato in: {file_path} (Dimensione: {downloaded_size / 1024 / 1024:.2f} MB)")
                    return file_path

        except requests.RequestException as e:
            logging.error(f"Errore durante il download dell'aggiornamento: {e}")
            raise ConnectionError(f"Download fallito.\n{e}")
    
    @staticmethod
    def run_updater_and_exit(updater_path: str):
        """
        Esegue l'installer dell'aggiornamento e chiude l'applicazione corrente.
        """
        logging.info(f"Esecuzione dell'aggiornamento: {updater_path}")
        # Per Windows, `start` esegue il programma in un nuovo processo indipendente
        if sys.platform == "win32":
            subprocess.Popen(f'start "" "{updater_path}"', shell=True)
        else:
            # Per altri OS (macOS, Linux), potrebbe essere necessario rendere il file eseguibile
            os.chmod(updater_path, 0o755)
            subprocess.Popen([updater_path])
        
        sys.exit(0) # Chiude l'applicazione principale