# app/ui/dialogs/reactivate_device_dialog.py
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QGroupBox, QFormLayout, QMessageBox)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
import qtawesome as qta
from app import config

class ReactivateDeviceDialog(QDialog):
    """
    Dialog per confermare la riattivazione di un dispositivo eliminato
    con lo stesso numero di serie.
    """
    def __init__(self, deleted_device, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚠️ Dispositivo Eliminato Trovato")
        self.setModal(True)
        self.setMinimumWidth(600)
        # Applica il tema corrente
        self.setStyleSheet(config.get_current_stylesheet())
        
        self.deleted_device = deleted_device
        self.reactivate_choice = False  # True = riattiva, False = crea nuovo
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Costruisce l'interfaccia."""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        
        # Titolo con icona
        title_layout = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.exclamation-triangle', color='#ea580c').pixmap(48, 48))
        title_layout.addWidget(icon_label)
        
        title_label = QLabel("<h2>Numero di Serie già Utilizzato</h2>")
        title_label.setStyleSheet("color: #ea580c;")
        title_layout.addWidget(title_label, 1)
        layout.addLayout(title_layout)
        
        # Messaggio principale
        message = QLabel(
            f"<p>È stato trovato un dispositivo <b>eliminato</b> con lo stesso numero di serie:</p>"
            f"<p><b style='font-size: 16px; color: #2563eb;'>{self.deleted_device.get('serial_number', 'N/A')}</b></p>"
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        
        # Dettagli dispositivo eliminato
        details_group = QGroupBox("📋 Dettagli Dispositivo Eliminato")
        details_layout = QFormLayout(details_group)
        details_layout.setRowWrapPolicy(QFormLayout.WrapAllRows)
        
        # Info dispositivo
        desc_label = QLabel(f"<b>{self.deleted_device.get('description', 'N/A')}</b>")
        details_layout.addRow("Descrizione:", desc_label)
        
        mfg_model = f"{self.deleted_device.get('manufacturer', 'N/A')} - {self.deleted_device.get('model', 'N/A')}"
        details_layout.addRow("Produttore/Modello:", QLabel(mfg_model))
        
        # Info destinazione
        customer_name = self.deleted_device.get('customer_name', 'N/A')
        dest_name = self.deleted_device.get('destination_name', 'N/A')
        location = f"<b>{customer_name}</b> → {dest_name}"
        location_label = QLabel(location)
        location_label.setWordWrap(True)
        details_layout.addRow("Ubicazione:", location_label)
        
        # Inventari
        if self.deleted_device.get('customer_inventory'):
            details_layout.addRow("Inv. Cliente:", QLabel(self.deleted_device['customer_inventory']))
        if self.deleted_device.get('ams_inventory'):
            details_layout.addRow("Inv. AMS:", QLabel(self.deleted_device['ams_inventory']))
        
        layout.addWidget(details_group)
        
        # Domanda
        question_label = QLabel(
            "<h3 style='color: #1e293b;'>Cosa desideri fare?</h3>"
            "<p>Puoi <b>riattivare</b> il dispositivo esistente o <b>crearne uno nuovo</b> "
            "con lo stesso numero di serie.</p>"
        )
        question_label.setWordWrap(True)
        layout.addWidget(question_label)
        
        # Pulsanti
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Pulsante "Crea Nuovo" (secondario)
        create_new_btn = QPushButton(qta.icon('fa5s.plus-circle'), " Crea Nuovo Dispositivo")
        create_new_btn.setObjectName("secondaryButton")
        create_new_btn.setMinimumHeight(50)
        create_new_btn.setToolTip("Crea un nuovo dispositivo mantenendo quello eliminato")
        create_new_btn.clicked.connect(self.choose_create_new)
        button_layout.addWidget(create_new_btn)
        
        # Pulsante "Riattiva" (primario, consigliato)
        reactivate_btn = QPushButton(qta.icon('fa5s.redo'), " Riattiva Dispositivo Esistente")
        reactivate_btn.setObjectName("autoButton")
        reactivate_btn.setMinimumHeight(50)
        reactivate_btn.setToolTip("Riattiva il dispositivo eliminato con i nuovi dati")
        reactivate_btn.clicked.connect(self.choose_reactivate)
        reactivate_btn.setDefault(True)  # Pulsante predefinito
        button_layout.addWidget(reactivate_btn)
        
        # Pulsante Annulla
        cancel_btn = QPushButton(qta.icon('fa5s.times'), " Annulla")
        cancel_btn.setObjectName("deleteButton")
        cancel_btn.setMinimumHeight(50)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Note
        note_label = QLabel(
            "<p style='color: #64748b; font-size: 12px;'>"
            "<b>Nota:</b> Se scegli di riattivare, tutti i dati del dispositivo (descrizione, "
            "produttore, modello, ecc.) verranno <b>aggiornati</b> con i nuovi valori inseriti, "
            "ma la <b>cronologia delle verifiche</b> passate sarà mantenuta."
            "</p>"
        )
        note_label.setWordWrap(True)
        layout.addWidget(note_label)
    
    def choose_reactivate(self):
        """Utente sceglie di riattivare il dispositivo esistente."""
        self.reactivate_choice = True
        self.accept()
    
    def choose_create_new(self):
        """Utente sceglie di creare un nuovo dispositivo."""
        # Conferma
        reply = QMessageBox.question(
            self,
            "Conferma Creazione Nuovo",
            f"Sei sicuro di voler creare un NUOVO dispositivo?\n\n"
            f"Avrai DUE dispositivi con lo stesso numero di serie:\n"
            f"- Uno eliminato (vecchio)\n"
            f"- Uno attivo (nuovo)\n\n"
            f"Questo è sconsigliato e potrebbe creare confusione.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.reactivate_choice = False
            self.accept()

