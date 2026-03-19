# app/ui/dialogs/expiring_devices_dialog.py

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QAbstractItemView, QMessageBox
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor
from app import config
import database
import qtawesome as qta
import logging
from datetime import datetime, timedelta


class ExpiringDevicesDialog(QDialog):
    """
    Finestra di dialogo per visualizzare gli strumenti di misura in scadenza nei prossimi 30 giorni.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setWindowTitle("⚠ Strumenti di Misura in Scadenza")
        self.resize(1000, 600)
        
        # Applica il tema corrente dalla main window
        if parent and hasattr(parent, 'current_theme'):
            theme = parent.current_theme
        else:
            from PySide6.QtCore import QSettings
            settings = QSettings("ELSON META", "SafetyTester")
            theme = settings.value("theme", "light")
        self.setStyleSheet(config.get_theme_stylesheet(theme))
        
        # Layout principale
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Header con icona e titolo
        header_layout = self._create_header()
        main_layout.addLayout(header_layout)
        
        # Tabella strumenti
        self.table = self._create_table()
        main_layout.addWidget(self.table)
        
        # Pulsanti
        button_layout = self._create_buttons()
        main_layout.addLayout(button_layout)
        
        # Carica dati
        self._load_devices()
    
    def _create_header(self):
        """Crea l'header con icona, titolo e descrizione."""
        layout = QHBoxLayout()
        layout.setSpacing(15)
        
        # Icona di avviso
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.exclamation-triangle', color='#f59e0b', scale_factor=2.0).pixmap(48, 48))
        layout.addWidget(icon_label)
        
        # Titolo e descrizione
        text_layout = QVBoxLayout()
        text_layout.setSpacing(5)
        
        title = QLabel("Strumenti di Misura in Scadenza")
        title.setObjectName("headerTitle")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #f59e0b;")
        
        subtitle = QLabel("I seguenti strumenti di misura hanno la calibrazione in scadenza nei prossimi 30 giorni:")
        subtitle.setObjectName("headerSubtitle")
        subtitle.setStyleSheet("font-size: 14px; color: #64748b;")
        
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)
        
        layout.addLayout(text_layout)
        layout.addStretch()
        
        return layout
    
    def _create_table(self):
        """Crea la tabella per mostrare gli strumenti di misura in scadenza."""
        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels([
            "Nome Strumento",
            "Numero di Serie",
            "Nr certificato cal.",
            "Tipo",
            "Data Scadenza",
            "Giorni Rimanenti"
        ])
        
        # Configurazione tabella
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        
        # Header
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
        return table
    
    def _create_buttons(self):
        """Crea i pulsanti della finestra."""
        layout = QHBoxLayout()
        layout.addStretch()
        
        # Pulsante Chiudi
        close_button = QPushButton(qta.icon('fa5s.times'), " Chiudi")
        close_button.setObjectName("editButton")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
        
        return layout
    
    def _load_devices(self):
        """Carica gli strumenti di misura in scadenza dal database."""
        try:
            instruments = database.get_instruments_needing_calibration(days_in_future=30)
            
            if not instruments:
                # Nessuno strumento in scadenza
                self.table.setRowCount(1)
                item = QTableWidgetItem("Nessuno strumento di misura in scadenza nei prossimi 30 giorni")
                item.setFlags(Qt.NoItemFlags)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(0, 0, item)
                self.table.setSpan(0, 0, 1, 6)
                return
            
            self.table.setRowCount(len(instruments))
            today = QDate.currentDate()
            
            for row_idx, instrument in enumerate(instruments):
                inst_dict = dict(instrument)
                
                # Nome Strumento
                instrument_name = inst_dict.get('instrument_name', 'N/A')
                self.table.setItem(row_idx, 0, QTableWidgetItem(str(instrument_name)))
                
                # Numero di Serie
                serial = inst_dict.get('serial_number', 'N/A')
                self.table.setItem(row_idx, 1, QTableWidgetItem(str(serial)))
                
                # Versione FW
                fw_version = inst_dict.get('fw_version', 'N/A')
                self.table.setItem(row_idx, 2, QTableWidgetItem(str(fw_version)))
                
                # Tipo
                instrument_type = inst_dict.get('instrument_type', 'N/A')
                if instrument_type == 'electrical':
                    type_display = 'Elettrico'
                elif instrument_type == 'functional':
                    type_display = 'Funzionale'
                else:
                    type_display = str(instrument_type)
                self.table.setItem(row_idx, 3, QTableWidgetItem(type_display))
                
                # Data Scadenza (calcolata: 1 anno dopo la data di calibrazione)
                expiration_date_str = inst_dict.get('expiration_date')
                cal_date_str = inst_dict.get('calibration_date')
                
                if expiration_date_str:
                    try:
                        # Parse della data di scadenza (formato YYYY-MM-DD)
                        expiration_date = QDate.fromString(expiration_date_str, Qt.ISODate)
                        if not expiration_date.isValid():
                            # Prova altri formati comuni
                            try:
                                expiration_date = QDate.fromString(expiration_date_str, "dd/MM/yyyy")
                            except:
                                expiration_date = QDate.fromString(expiration_date_str, "yyyy-MM-dd")
                        
                        date_item = QTableWidgetItem(expiration_date.toString("dd/MM/yyyy"))
                        
                        # Calcola giorni rimanenti
                        days_remaining = today.daysTo(expiration_date)
                        
                        # Colora in base ai giorni rimanenti
                        if days_remaining < 0:
                            # Scaduto
                            date_item.setForeground(QColor('#ef4444'))
                            days_item = QTableWidgetItem(f"Scaduto ({abs(days_remaining)} giorni)")
                            days_item.setForeground(QColor('#ef4444'))
                        elif days_remaining <= 7:
                            # Scade entro 7 giorni
                            date_item.setForeground(QColor('#f59e0b'))
                            days_item = QTableWidgetItem(f"{days_remaining} giorni")
                            days_item.setForeground(QColor('#f59e0b'))
                        elif days_remaining <= 15:
                            # Scade entro 15 giorni
                            date_item.setForeground(QColor('#fbbf24'))
                            days_item = QTableWidgetItem(f"{days_remaining} giorni")
                            days_item.setForeground(QColor('#fbbf24'))
                        else:
                            # Scade tra 16-30 giorni
                            days_item = QTableWidgetItem(f"{days_remaining} giorni")
                        
                        self.table.setItem(row_idx, 4, date_item)
                        self.table.setItem(row_idx, 5, days_item)
                    except Exception as e:
                        logging.error(f"Errore parsing data scadenza: {e}, valore: {expiration_date_str}")
                        self.table.setItem(row_idx, 4, QTableWidgetItem(str(expiration_date_str) if expiration_date_str else "N/A"))
                        self.table.setItem(row_idx, 5, QTableWidgetItem("N/A"))
                elif cal_date_str:
                    # Se non c'è expiration_date ma c'è calibration_date, mostra la data di calibrazione
                    try:
                        cal_date = QDate.fromString(cal_date_str, Qt.ISODate)
                        if not cal_date.isValid():
                            cal_date = QDate.fromString(cal_date_str, "dd/MM/yyyy")
                        # Calcola la scadenza aggiungendo 1 anno
                        expiration_date = cal_date.addYears(1)
                        date_item = QTableWidgetItem(expiration_date.toString("dd/MM/yyyy"))
                        days_remaining = today.daysTo(expiration_date)
                        
                        if days_remaining < 0:
                            date_item.setForeground(QColor('#ef4444'))
                            days_item = QTableWidgetItem(f"Scaduto ({abs(days_remaining)} giorni)")
                            days_item.setForeground(QColor('#ef4444'))
                        elif days_remaining <= 7:
                            date_item.setForeground(QColor('#f59e0b'))
                            days_item = QTableWidgetItem(f"{days_remaining} giorni")
                            days_item.setForeground(QColor('#f59e0b'))
                        elif days_remaining <= 15:
                            date_item.setForeground(QColor('#fbbf24'))
                            days_item = QTableWidgetItem(f"{days_remaining} giorni")
                            days_item.setForeground(QColor('#fbbf24'))
                        else:
                            days_item = QTableWidgetItem(f"{days_remaining} giorni")
                        
                        self.table.setItem(row_idx, 4, date_item)
                        self.table.setItem(row_idx, 5, days_item)
                    except Exception as e:
                        logging.error(f"Errore parsing data calibrazione: {e}, valore: {cal_date_str}")
                        self.table.setItem(row_idx, 4, QTableWidgetItem(str(cal_date_str)))
                        self.table.setItem(row_idx, 5, QTableWidgetItem("N/A"))
                else:
                    self.table.setItem(row_idx, 4, QTableWidgetItem("N/A"))
                    self.table.setItem(row_idx, 5, QTableWidgetItem("N/A"))
            
            # Ordina per data di calibrazione (più vicina prima)
            self.table.sortItems(4, Qt.AscendingOrder)
            
        except Exception as e:
            logging.error(f"Errore durante il caricamento degli strumenti di misura in scadenza: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", 
                               f"Impossibile caricare gli strumenti di misura in scadenza:\n{str(e)}")

