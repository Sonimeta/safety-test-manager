from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QDialogButtonBox, QMessageBox, QListWidget,
    QListWidgetItem, QLabel, QGroupBox
)
from PySide6.QtCore import Qt
from app import services
import logging

class CorrectionDialog(QDialog):
    """
    Finestra di dialogo per la correzione in blocco delle descrizioni dei dispositivi.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Correggi Descrizioni Dispositivi")
        self.setMinimumSize(600, 500)

        # Layout principale
        main_layout = QVBoxLayout(self)

        # Sezione di input
        form_layout = QFormLayout()
        self.old_desc_combo = QComboBox()
        self.old_desc_combo.setEditable(True)
        self.old_desc_combo.completer().setFilterMode(Qt.MatchContains)
        
        self.new_desc_input = QLineEdit()
        self.new_desc_input.setPlaceholderText("Inserisci la nuova descrizione corretta")

        form_layout.addRow("Descrizione da correggere:", self.old_desc_combo)
        form_layout.addRow("Nuova descrizione:", self.new_desc_input)
        main_layout.addLayout(form_layout)

        # Pulsante di anteprima
        self.preview_button = QPushButton("Mostra Anteprima Dispositivi")
        self.preview_button.clicked.connect(self.show_preview)
        main_layout.addWidget(self.preview_button)

        # Sezione di anteprima
        preview_group = QGroupBox("Dispositivi che verranno modificati")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_list = QListWidget()
        preview_layout.addWidget(self.preview_list)
        main_layout.addWidget(preview_group)

        # Pulsanti finali
        self.buttons = QDialogButtonBox()
        self.execute_button = self.buttons.addButton("Esegui Correzione", QDialogButtonBox.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.Cancel)
        
        self.execute_button.setEnabled(False) # Abilitato solo dopo l'anteprima

        self.buttons.accepted.connect(self.execute_correction)
        self.buttons.rejected.connect(self.reject)
        main_layout.addWidget(self.buttons)

        self.load_descriptions()

    def load_descriptions(self):
        """Carica le descrizioni uniche nel combobox."""
        try:
            descriptions = services.get_all_unique_device_descriptions()
            self.old_desc_combo.addItems(descriptions)
        except Exception as e:
            logging.error(f"Impossibile caricare le descrizioni per la correzione: {e}")
            QMessageBox.critical(self, "Errore", "Impossibile caricare le descrizioni dal database.")

    def show_preview(self):
        """Mostra un'anteprima dei dispositivi che verranno modificati."""
        old_desc = self.old_desc_combo.currentText().strip()
        new_desc = self.new_desc_input.text().strip()

        if not old_desc or not new_desc:
            QMessageBox.warning(self, "Dati Mancanti", "Seleziona una descrizione da correggere e inserisci quella nuova.")
            return

        if old_desc.upper() == new_desc.upper():
            QMessageBox.warning(self, "Dati Uguali", "La vecchia e la nuova descrizione sono identiche.")
            return

        try:
            devices_rows = services.get_devices_by_description(old_desc)
            self.preview_list.clear()
            if not devices_rows:
                self.preview_list.addItem("Nessun dispositivo trovato con questa descrizione.")
                self.execute_button.setEnabled(False)
            else:
                devices = [dict(row) for row in devices_rows]
                for device in devices:
                    item_text = f"ID: {device['id']} - S/N: {device.get('serial_number', 'N/D')} - Modello: {device.get('model', 'N/D')}"
                    self.preview_list.addItem(QListWidgetItem(item_text))
                self.execute_button.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "Errore Anteprima", f"Impossibile recuperare i dispositivi: {e}")
            self.execute_button.setEnabled(False)

    def execute_correction(self):
        """Esegue la correzione dopo conferma."""
        old_desc = self.old_desc_combo.currentText().strip()
        new_desc = self.new_desc_input.text().strip().upper()
        
        reply = QMessageBox.question(self, "Conferma Correzione",
                                     f"Sei sicuro di voler sostituire la descrizione:\n\n'{old_desc}'\n\ncon\n\n'{new_desc}'\n\nsu {self.preview_list.count()} dispositivi? L'operazione non è reversibile.",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            try:
                rows_affected = services.correct_device_description(old_desc, new_desc)
                QMessageBox.information(self, "Successo", f"Operazione completata. Sono stati aggiornati {rows_affected} dispositivi.")
                self.accept()
            except Exception as e:
                QMessageBox.critical(self, "Errore Esecuzione", f"Impossibile completare la correzione: {e}")