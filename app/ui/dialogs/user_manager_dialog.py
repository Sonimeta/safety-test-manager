# app/ui/dialogs/user_manager_dialog.py
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                               QHBoxLayout, QPushButton, QMessageBox, QAbstractItemView, QHeaderView)
import requests
from app.http_client import http_session
from app import auth_manager, config
from .user_detail_dialog import UserDetailDialog

class UserManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GESTIONE UTENTI")
        self.setMinimumSize(800, 500)
        
        # --- MODIFICA CHIAVE: Inizializziamo l'attributo qui ---
        self.users_data = []
        
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["USERNAME", "NOME", "COGNOME", "RUOLO"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        
        buttons_layout = QHBoxLayout()
        add_btn = QPushButton("AGGIUNGI UTENTE...")
        edit_btn = QPushButton("MODIFICA SELEZIONATO...")
        delete_btn = QPushButton("ELIMINA SELEZIONATO")
        buttons_layout.addStretch()
        buttons_layout.addWidget(add_btn)
        buttons_layout.addWidget(edit_btn)
        buttons_layout.addWidget(delete_btn)
        layout.addLayout(buttons_layout)
        
        add_btn.clicked.connect(self.add_user)
        edit_btn.clicked.connect(self.edit_user)
        delete_btn.clicked.connect(self.delete_user)
        
        self.load_users()

    def load_users(self):
        try:
            users_url = f"{config.SERVER_URL}/users"
            response = http_session.get(users_url, headers=auth_manager.get_auth_headers())
            response.raise_for_status()
            self.users_data = response.json()
            
            self.table.setRowCount(0)
            for user in self.users_data:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(str(user['username']).upper()))
                self.table.setItem(row, 1, QTableWidgetItem(str(user.get('first_name', '')).upper()))
                self.table.setItem(row, 2, QTableWidgetItem(str(user.get('last_name', '')).upper()))
                self.table.setItem(row, 3, QTableWidgetItem(str(user['role']).upper()))
        except requests.RequestException as e:
            self.users_data = []
            self.table.setRowCount(0)
            QMessageBox.critical(self, "ERRORE DI RETE", f"IMPOSSIBILE CARICARE LA LISTA UTENTI DAL SERVER:\n{str(e).upper()}")

    def add_user(self):
        dialog = UserDetailDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            user_data = dialog.get_data()
            if not user_data.get("password"):
                QMessageBox.warning(self, "DATI MANCANTI", "LA PASSWORD È OBBLIGATORIA PER UN NUOVO UTENTE.")
                return
            try:
                users_url = f"{config.SERVER_URL}/users"
                response = http_session.post(users_url, json=user_data, headers=auth_manager.get_auth_headers())
                response.raise_for_status()
                QMessageBox.information(self, "Successo", f"Utente '{user_data['username']}' creato.")
                self.load_users()
            except requests.RequestException as e:
                detail = ""
                try:
                    if e.response is not None and 'application/json' in e.response.headers.get('content-type',''):
                        detail = e.response.json().get('detail',"")
                except Exception:
                    pass
                QMessageBox.critical(self, "ERRORE", f"OPERAZIONE FALLITA:\n{detail or str(e).upper()}")

    def edit_user(self):
        """Gestisce la modifica di un utente selezionato."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "ATTENZIONE", "SELEZIONARE UN UTENTE DA MODIFICARE.")
            return
        
        selected_row_index = selected_rows[0].row()
    
        if selected_row_index >= len(self.users_data):
            return

        user_data_to_edit = self.users_data[selected_row_index]
    
        dialog = UserDetailDialog(user_data=user_data_to_edit, parent=self)
        if dialog.exec() == QDialog.Accepted:
            updated_data = dialog.get_data()
            username_to_edit = user_data_to_edit['username']
        
            payload = {}
            if updated_data['role'] != user_data_to_edit['role']:
                payload['role'] = updated_data['role']
        
            # --- MODIFICA CHIAVE: Usiamo .get() per un accesso sicuro ---
            if updated_data.get('password'):
                payload['password'] = updated_data.get('password')
            # --- FINE MODIFICA ---
        
            # Aggiungiamo il controllo per nome e cognome
            if updated_data['first_name'] != user_data_to_edit.get('first_name', ''):
                payload['first_name'] = updated_data['first_name']
            if updated_data['last_name'] != user_data_to_edit.get('last_name', ''):
                payload['last_name'] = updated_data['last_name']
        
            if not payload:
                QMessageBox.warning(self, "NESSUNA MODIFICA", "NESSUNA MODIFICA EFFETTUATA.")
                return

            try:
                # L'API per la modifica deve essere estesa per accettare first_name e last_name
                user_url = f"{config.SERVER_URL}/users/{username_to_edit}"
                response = http_session.put(user_url, json=payload, headers=auth_manager.get_auth_headers())
                response.raise_for_status()
                QMessageBox.information(self, "Successo", f"Utente '{username_to_edit}' aggiornato.")
                self.load_users()
            except requests.RequestException as e:
                detail = ""
                try:
                    if e.response is not None and 'application/json' in e.response.headers.get('content-type',''):
                        detail = e.response.json().get('detail',"")
                except Exception:
                    pass
                QMessageBox.critical(self, "ERRORE", f"OPERAZIONE FALLITA:\n{detail or str(e).upper()}")

    def delete_user(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "ATTENZIONE", "SELEZIONARE UN UTENTE DA ELIMINARE.")
            return
            
        username = self.table.item(selected_rows[0].row(), 0).text()
        reply = QMessageBox.question(self, "CONFERMA", f"SEI SICURO DI VOLER ELIMINARE L'UTENTE '{username.upper()}'?")
        if reply == QMessageBox.Yes:
            try:
                user_url = f"{config.SERVER_URL}/users/{username}"
                response = http_session.delete(user_url, headers=auth_manager.get_auth_headers())
                response.raise_for_status()
                QMessageBox.information(self, "Successo", f"Utente '{username}' eliminato.")
                self.load_users()
            except requests.RequestException as e:
                detail = ""
                try:
                    if e.response is not None and 'application/json' in e.response.headers.get('content-type',''):
                        detail = e.response.json().get('detail',"")
                except Exception:
                    pass
                QMessageBox.critical(self, "ERRORE", f"OPERAZIONE FALLITA:\n{detail or str(e).upper()}")