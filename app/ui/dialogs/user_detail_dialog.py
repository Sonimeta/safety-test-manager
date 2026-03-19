from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QLabel, QDialogButtonBox, QFormLayout, QComboBox

class UserDetailDialog(QDialog):
    def __init__(self, user_data=None, parent=None):
        super().__init__(parent)
        self.is_edit_mode = user_data is not None

        title = "MODIFICA UTENTE" if self.is_edit_mode else "AGGIUNGI NUOVO UTENTE"
        self.setWindowTitle(title)
        
        data = user_data or {}
        
        layout = QFormLayout(self)
        self.username_edit = QLineEdit(data.get('username', ''))
        self.first_name_edit = QLineEdit(data.get('first_name', ''))
        self.last_name_edit = QLineEdit(data.get('last_name', ''))
        self.password_edit = QLineEdit()
        self.role_combo = QComboBox()
        self.role_combo.addItems(['technician', 'moderator', 'admin'])
        self.role_combo.setCurrentText(data.get('role', 'technician'))
        
        if self.is_edit_mode:
            self.username_edit.setReadOnly(True) # Non si può cambiare lo username
            self.password_edit.setPlaceholderText("LASCIARE VUOTO PER NON CAMBIARE")
        
        layout.addRow("USERNAME:", self.username_edit)
        layout.addRow("NOME:", self.first_name_edit)
        layout.addRow("COGNOME:", self.last_name_edit)
        layout.addRow("PASSWORD:", self.password_edit)
        layout.addRow("RUOLO:", self.role_combo)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        """Restituisce i dati inseriti nella dialog."""
        data = {
            "username": self.username_edit.text().strip().lower(),
            "first_name": self.first_name_edit.text().strip().upper(),
            "last_name": self.last_name_edit.text().strip().upper(),
            "role": self.role_combo.currentText(),
            "password": self.password_edit.text()
        }
        # In modalità modifica, non includere la password se il campo è vuoto
        if self.is_edit_mode and not data["password"]:
            del data["password"]
        return data