# app/ui/dialogs/update_dialog.py
import logging
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QMessageBox
from PySide6.QtCore import QThread, Signal, Slot
from app.updater import UpdateChecker

class UpdateDownloadWorker(QThread):
    """Worker per eseguire il download in un thread separato."""
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, checker: UpdateChecker, download_url: str, parent=None):
        super().__init__(parent)
        self.checker = checker
        self.download_url = download_url

    def run(self):
        try:
            filepath = self.checker.download_update(self.download_url, self.progress.emit)
            self.finished.emit(filepath)
        except Exception as e:
            logging.error("Errore nel worker di download", exc_info=True)
            self.error.emit(str(e))


class UpdateDialog(QDialog):
    """Finestra di dialogo per mostrare il progresso del download dell'aggiornamento."""

    def __init__(self, checker: UpdateChecker, update_info: dict, parent=None):
        super().__init__(parent)
        self.checker = checker
        self.update_info = update_info
        self.updater_path = None

        self.setWindowTitle("Download Aggiornamento")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        self.label = QLabel(f"Download della versione {self.update_info['latest_version']} in corso...")
        self.progress_bar = QProgressBar()
        layout.addWidget(self.label)
        layout.addWidget(self.progress_bar)

        self.start_download()

    def start_download(self):
        self.worker = UpdateDownloadWorker(self.checker, self.update_info['download_url'])
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.error.connect(self.on_download_error)
        self.worker.finished.connect(self.on_download_finished)
        self.worker.start()

    @Slot(str)
    def on_download_finished(self, filepath: str):
        self.updater_path = filepath
        QMessageBox.information(self, "Download Completato", "L'aggiornamento è pronto per essere installato. L'applicazione verrà chiusa per avviare l'installazione.")
        self.accept()

    @Slot(str)
    def on_download_error(self, error_message: str):
        QMessageBox.critical(self, "Errore di Download", f"Impossibile scaricare l'aggiornamento:\n{error_message}")
        self.reject()