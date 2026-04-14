# app/ui/dialogs/change_password_dialog.py
import logging
import requests
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel,
    QDialogButtonBox, QMessageBox,
)
from PySide6.QtCore import Qt
from app.http_client import http_session
from app import auth_manager, config


class ChangePasswordDialog(QDialog):
    """Dialog per permettere all'utente loggato di cambiare la propria password."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CAMBIA PASSWORD")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        # Info utente
        user_info = auth_manager.get_current_user_info()
        username = user_info.get("username", "")
        info_label = QLabel(f"Cambio password per l'utente: <b>{username.upper()}</b>")
        layout.addWidget(info_label)

        # Form
        form = QFormLayout()

        self.current_password_edit = QLineEdit()
        self.current_password_edit.setEchoMode(QLineEdit.Password)
        self.current_password_edit.setProperty("_stm_password", True)
        self.current_password_edit.setPlaceholderText("Inserisci la password attuale")
        form.addRow("PASSWORD ATTUALE:", self.current_password_edit)

        self.new_password_edit = QLineEdit()
        self.new_password_edit.setEchoMode(QLineEdit.Password)
        self.new_password_edit.setProperty("_stm_password", True)
        self.new_password_edit.setPlaceholderText("Minimo 8 caratteri")
        form.addRow("NUOVA PASSWORD:", self.new_password_edit)

        self.confirm_password_edit = QLineEdit()
        self.confirm_password_edit.setEchoMode(QLineEdit.Password)
        self.confirm_password_edit.setProperty("_stm_password", True)
        self.confirm_password_edit.setPlaceholderText("Ripeti la nuova password")
        form.addRow("CONFERMA PASSWORD:", self.confirm_password_edit)

        layout.addLayout(form)

        # Pulsanti
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("CAMBIA PASSWORD")
        buttons.button(QDialogButtonBox.Cancel).setText("ANNULLA")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.current_password_edit.setFocus()

    def _on_accept(self):
        """Valida i campi e invia la richiesta al server."""
        current_pw = self.current_password_edit.text()
        new_pw = self.new_password_edit.text()
        confirm_pw = self.confirm_password_edit.text()

        if not current_pw:
            QMessageBox.warning(self, "DATI MANCANTI", "INSERIRE LA PASSWORD ATTUALE.")
            self.current_password_edit.setFocus()
            return

        if not new_pw:
            QMessageBox.warning(self, "DATI MANCANTI", "INSERIRE LA NUOVA PASSWORD.")
            self.new_password_edit.setFocus()
            return

        if len(new_pw) < 8:
            QMessageBox.warning(self, "PASSWORD TROPPO CORTA", "LA NUOVA PASSWORD DEVE ESSERE DI ALMENO 8 CARATTERI.")
            self.new_password_edit.setFocus()
            return

        if new_pw != confirm_pw:
            QMessageBox.warning(self, "ERRORE", "LA NUOVA PASSWORD E LA CONFERMA NON COINCIDONO.")
            self.confirm_password_edit.setFocus()
            return

        if current_pw == new_pw:
            QMessageBox.warning(self, "ERRORE", "LA NUOVA PASSWORD DEVE ESSERE DIVERSA DA QUELLA ATTUALE.")
            self.new_password_edit.setFocus()
            return

        try:
            url = f"{config.SERVER_URL}/me/change-password"
            payload = {
                "current_password": current_pw,
                "new_password": new_pw,
            }
            response = http_session.post(url, json=payload, headers=auth_manager.get_auth_headers())
            response.raise_for_status()
            QMessageBox.information(self, "SUCCESSO", "PASSWORD CAMBIATA CON SUCCESSO.")
            self.accept()
        except requests.RequestException as e:
            detail = ""
            try:
                if e.response is not None and 'application/json' in e.response.headers.get('content-type', ''):
                    detail = e.response.json().get('detail', '')
            except Exception:
                pass
            error_msg = detail.upper() if detail else str(e).upper()
            QMessageBox.critical(self, "ERRORE", f"IMPOSSIBILE CAMBIARE LA PASSWORD:\n{error_msg}")
