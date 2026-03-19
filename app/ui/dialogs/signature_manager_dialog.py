# app/ui/dialogs/signature_manager_dialog.py

import requests
import logging
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QPushButton, QLabel, 
                               QFileDialog, QMessageBox, QGroupBox)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
import os
from app import auth_manager, config
import mimetypes

class SignatureManagerDialog(QDialog):
    """
    Finestra di dialogo per caricare, visualizzare e rimuovere l'immagine
    della firma dal server centrale.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GESTIONE FIRMA (SINCRONIZZATA)")
        self.setMinimumSize(400, 300)

        # Non usiamo più QSettings per la firma
        self.user_info = auth_manager.get_current_user_info()
        self.username = self.user_info.get('username')

        main_layout = QVBoxLayout(self)

        preview_group = QGroupBox("ANTEPRIMA FIRMA CORRENTE (DAL SERVER)")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_label = QLabel("CARICAMENTO FIRMA DAL SERVER...")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(150)
        self.preview_label.setStyleSheet("border: 1px dashed #81A1C1; border-radius: 5px;")
        preview_layout.addWidget(self.preview_label)
        main_layout.addWidget(preview_group)

        load_button = QPushButton("CARICA NUOVA IMMAGINE...")
        remove_button = QPushButton("RIMUOVI FIRMA DAL SERVER")
        close_button = QPushButton("CHIUDI")

        main_layout.addWidget(load_button)
        main_layout.addWidget(remove_button)
        main_layout.addStretch()
        main_layout.addWidget(close_button)

        load_button.clicked.connect(self.upload_signature_image)
        remove_button.clicked.connect(self.remove_signature)
        close_button.clicked.connect(self.accept)

        self.load_preview()

    def load_preview(self):
        """
        --- MODIFICATO ---
        Scarica l'immagine della firma dal server e la mostra.
        """
        self.preview_label.setText("CARICAMENTO...")
        try:
            url = f"{config.SERVER_URL}/signatures/{self.username}"
            response = requests.get(url, headers=auth_manager.get_auth_headers(), timeout=10)
            
            if response.status_code == 200:
                pixmap = QPixmap()
                pixmap.loadFromData(response.content)
                self.preview_label.setPixmap(pixmap.scaled(
                    self.preview_label.size() * 0.9, 
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                ))
            elif response.status_code == 404:
                self.preview_label.setText("NESSUNA FIRMA IMPOSTATA SUL SERVER.")
                self.preview_label.setPixmap(QPixmap())
            else:
                raise requests.RequestException(f"Errore del server: {response.status_code}")

        except requests.RequestException as e:
            logging.error(f"Impossibile scaricare l'anteprima della firma: {e}")
            self.preview_label.setText("ERRORE DI CONNESSIONE.")
            self.preview_label.setPixmap(QPixmap())

    def upload_signature_image(self):
        """
        --- MODIFICATO ---
        Apre una dialog per selezionare un file e lo carica sul server.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "SELEZIONA IMMAGINE FIRMA", "", "Image Files (*.png *.jpg *.jpeg)")
        
        if not file_path:
            return

        try:
            url = f"{config.SERVER_URL}/signatures/{self.username}"
            with open(file_path, 'rb') as f:
                mime, _ = mimetypes.guess_type(file_path)
                files = {'file': (os.path.basename(file_path), f, mime or 'application/octet-stream')}
                response = requests.post(url, files=files, headers=auth_manager.get_auth_headers())
            
            response.raise_for_status() # Lancia un errore se la richiesta fallisce
            
            QMessageBox.information(self, "SUCCESSO", "FIRMA CARICATA CON SUCCESSO SUL SERVER.")
            self.load_preview() # Aggiorna l'anteprima

        except requests.RequestException as e:
            logging.error(f"Fallimento upload firma: {e}")
            QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE CARICARE LA FIRMA SUL SERVER:\n{str(e).upper()}")
    def resizeEvent(self, e):
        super().resizeEvent(e)
        pm = self.preview_label.pixmap()
        if pm and not pm.isNull():
            self.preview_label.setPixmap(pm.scaled(
                self.preview_label.size()*0.9, Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    def remove_signature(self):
        """

        --- MODIFICATO ---
        Invia una richiesta per eliminare la firma dal server.
        """
        reply = QMessageBox.question(self, "CONFERMA", "SEI SICURO DI VOLER RIMUOVERE LA TUA FIRMA DAL SERVER?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No:
            return

        try:
            url = f"{config.SERVER_URL}/signatures/{self.username}"
            response = requests.delete(url, headers=auth_manager.get_auth_headers())
            response.raise_for_status()
            
            QMessageBox.information(self, "OPERAZIONE COMPLETATA", "FIRMA RIMOSSA DAL SERVER.")
            self.load_preview()

        except requests.RequestException as e:
            logging.error(f"Fallimento eliminazione firma: {e}")
            QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE RIMUOVERE LA FIRMA:\n{str(e).upper()}")