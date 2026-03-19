# app/ui/dialogs/sync_conflicts_dialog.py
"""
Dialog per la gestione e risoluzione dei conflitti di sincronizzazione.
Mostra tutti i conflitti pendenti e permette all'utente di risolverli.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QGroupBox, QMessageBox, QDialogButtonBox, QWidget, QScrollArea,
    QFrame, QSplitter, QTextEdit, QComboBox
)
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtCore import Qt
import logging
import json
import database
from app import services
from datetime import datetime, timezone


# Mappatura nomi tabelle user-friendly
TABLE_DISPLAY_NAMES = {
    "customers": "Clienti",
    "mti_instruments": "Strumenti di Misura",
    "signatures": "Firme",
    "profiles": "Profili di Verifica",
    "profile_tests": "Test di Profilo",
    "functional_profiles": "Profili Funzionali",
    "destinations": "Destinazioni",
    "devices": "Dispositivi",
    "verifications": "Verifiche Elettriche",
    "functional_verifications": "Verifiche Funzionali",
    "audit_log": "Log Operazioni"
}

# Mappatura tipi di conflitto user-friendly
CONFLICT_TYPE_NAMES = {
    "duplicate_serial_number": "Numero di Serie Duplicato",
    "integrity_constraint": "Vincolo di Integrità",
    "foreign_key_missing": "Riferimento Mancante",
    "operational_error": "Errore Operativo",
    "update_conflict": "Conflitto di Aggiornamento",
    "update_serial_error": "Errore Aggiornamento Seriale",
    "table_error": "Errore Tabella",
    "modification_conflict": "Modifica Conflittuale",
}

SEVERITY_COLORS = {
    "low": "#A3BE8C",      # Verde
    "medium": "#EBCB8B",   # Giallo
    "high": "#D08770",     # Arancione
    "critical": "#BF616A", # Rosso
}

SEVERITY_NAMES = {
    "low": "Basso",
    "medium": "Medio",
    "high": "Alto",
    "critical": "Critico",
}

# Campi da nascondere nella visualizzazione dei dati
HIDDEN_FIELDS = {'is_synced', 'last_modified', 'created_at'}


class SyncConflictsDialog(QDialog):
    """Dialog principale per la gestione dei conflitti di sincronizzazione."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conflitti di Sincronizzazione")
        self.setMinimumSize(1000, 600)
        self.resize(1100, 700)
        
        self.conflicts = database.get_pending_sync_conflicts()
        self._build_ui()
        self._populate_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header_layout = QHBoxLayout()
        
        title = QLabel("⚠️ Conflitti di Sincronizzazione")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        count_label = QLabel(f"{len(self.conflicts)} conflitt{'o' if len(self.conflicts) == 1 else 'i'} da risolvere")
        count_label.setFont(QFont("Segoe UI", 11))
        count_label.setStyleSheet("color: #BF616A; font-weight: bold;")
        header_layout.addWidget(count_label)
        self.count_label = count_label
        
        layout.addLayout(header_layout)

        # Descrizione
        desc = QLabel(
            "Durante la sincronizzazione sono stati rilevati dei conflitti che richiedono la tua attenzione.\n"
            "Per ogni conflitto puoi scegliere di mantenere la versione locale, usare quella del server, o ignorare il conflitto."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8899A6; margin-bottom: 8px;")
        layout.addWidget(desc)

        # Splitter: lista conflitti + dettaglio
        splitter = QSplitter(Qt.Vertical)
        
        # === Tabella conflitti ===
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Tabella", "Tipo Conflitto", "Gravità", "Messaggio", "Data"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.currentCellChanged.connect(self._on_conflict_selected)
        splitter.addWidget(self.table)

        # === Pannello dettagli ===
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 4, 0, 0)

        detail_label = QLabel("Dettagli del conflitto selezionato:")
        detail_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        detail_layout.addWidget(detail_label)

        # Layout a due colonne per versione locale e server
        comparison_layout = QHBoxLayout()
        
        # Versione locale
        local_group = QGroupBox("📁 Versione Locale")
        local_group_layout = QVBoxLayout(local_group)
        self.local_table = self._create_details_table()
        local_group_layout.addWidget(self.local_table)
        comparison_layout.addWidget(local_group)

        # Versione server
        server_group = QGroupBox("☁️ Versione Server")
        server_group_layout = QVBoxLayout(server_group)
        self.server_table = self._create_details_table()
        server_group_layout.addWidget(self.server_table)
        comparison_layout.addWidget(server_group)

        detail_layout.addLayout(comparison_layout)

        # Messaggio errore
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #BF616A; background: rgba(191,97,106,0.1); padding: 6px; border-radius: 4px;")
        self.error_label.hide()
        detail_layout.addWidget(self.error_label)

        splitter.addWidget(detail_widget)
        splitter.setSizes([250, 350])
        layout.addWidget(splitter)

        # === Pulsanti azione ===
        action_layout = QHBoxLayout()

        self.btn_keep_local = QPushButton("✅ Mantieni Versione Locale")
        self.btn_keep_local.setToolTip("Mantiene i dati locali e li forza al prossimo sync")
        self.btn_keep_local.clicked.connect(self._resolve_keep_local)
        self.btn_keep_local.setEnabled(False)
        action_layout.addWidget(self.btn_keep_local)

        self.btn_use_server = QPushButton("☁️ Usa Versione Server")
        self.btn_use_server.setToolTip("Sovrascrive i dati locali con quelli del server")
        self.btn_use_server.clicked.connect(self._resolve_use_server)
        self.btn_use_server.setEnabled(False)
        action_layout.addWidget(self.btn_use_server)

        self.btn_dismiss = QPushButton("🗑️ Ignora Conflitto")
        self.btn_dismiss.setToolTip("Ignora il conflitto (il record non verrà sincronizzato)")
        self.btn_dismiss.clicked.connect(self._resolve_dismiss)
        self.btn_dismiss.setEnabled(False)
        action_layout.addWidget(self.btn_dismiss)

        action_layout.addStretch()

        self.btn_resolve_all_server = QPushButton("Risolvi Tutti → Server")
        self.btn_resolve_all_server.setToolTip("Risolve tutti i conflitti usando la versione del server")
        self.btn_resolve_all_server.clicked.connect(self._resolve_all_server)
        action_layout.addWidget(self.btn_resolve_all_server)

        layout.addLayout(action_layout)

        # Pulsante chiudi
        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.accept)
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)

    def _create_details_table(self):
        """Crea una tabella per i dettagli di una versione."""
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Campo", "Valore"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        return table

    def _populate_table(self):
        """Popola la tabella con i conflitti."""
        self.table.setRowCount(0)
        
        for conflict in self.conflicts:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            # Tabella
            table_name = conflict.get('table_name', 'N/A')
            display_table = TABLE_DISPLAY_NAMES.get(table_name, table_name)
            self.table.setItem(row, 0, QTableWidgetItem(display_table))

            # Tipo conflitto
            conflict_type = conflict.get('conflict_type', 'N/A')
            display_type = CONFLICT_TYPE_NAMES.get(conflict_type, conflict_type)
            self.table.setItem(row, 1, QTableWidgetItem(display_type))

            # Gravità (con colore)
            severity = conflict.get('severity', 'medium')
            severity_item = QTableWidgetItem(SEVERITY_NAMES.get(severity, severity))
            severity_color = SEVERITY_COLORS.get(severity, '#EBCB8B')
            severity_item.setBackground(QColor(severity_color))
            self.table.setItem(row, 2, severity_item)

            # Messaggio (troncato)
            msg = conflict.get('error_message', '')
            if len(msg) > 100:
                msg = msg[:100] + "..."
            self.table.setItem(row, 3, QTableWidgetItem(msg))

            # Data
            created = conflict.get('created_at', '')
            self.table.setItem(row, 4, QTableWidgetItem(str(created)))

        if not self.conflicts:
            self.table.insertRow(0)
            item = QTableWidgetItem("✅ Nessun conflitto da risolvere!")
            item.setForeground(QColor("#A3BE8C"))
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, 5)

    def _on_conflict_selected(self, current_row, current_col, prev_row, prev_col):
        """Gestisce la selezione di un conflitto dalla tabella."""
        has_selection = 0 <= current_row < len(self.conflicts)
        self.btn_keep_local.setEnabled(has_selection)
        self.btn_use_server.setEnabled(has_selection)
        self.btn_dismiss.setEnabled(has_selection)
        
        if not has_selection:
            self.local_table.setRowCount(0)
            self.server_table.setRowCount(0)
            self.error_label.hide()
            return

        conflict = self.conflicts[current_row]
        
        # Popola versione locale
        local_data = conflict.get('local_data') or {}
        self._fill_detail_table(self.local_table, local_data)
        
        # Popola versione server
        server_data = conflict.get('server_data') or {}
        self._fill_detail_table(self.server_table, server_data)
        
        # Evidenzia differenze
        self._highlight_differences(local_data, server_data)
        
        # Mostra messaggio errore
        error_msg = conflict.get('error_message', '')
        if error_msg:
            self.error_label.setText(f"ℹ️ {error_msg}")
            self.error_label.show()
        else:
            self.error_label.hide()

    def _fill_detail_table(self, table_widget, data):
        """Popola una tabella dettagli con i dati di un record."""
        table_widget.setRowCount(0)
        
        if not data:
            row = table_widget.rowCount()
            table_widget.insertRow(row)
            table_widget.setItem(row, 0, QTableWidgetItem("—"))
            table_widget.setItem(row, 1, QTableWidgetItem("Nessun dato disponibile"))
            return

        for key in sorted(data.keys(), key=str.lower):
            if key in HIDDEN_FIELDS or key == 'id':
                continue
            val = data.get(key, "")
            if val is None:
                val = ""
            if hasattr(val, 'isoformat'):
                val = val.isoformat()
            
            row = table_widget.rowCount()
            table_widget.insertRow(row)
            table_widget.setItem(row, 0, QTableWidgetItem(str(key)))
            table_widget.setItem(row, 1, QTableWidgetItem(str(val)))

    def _highlight_differences(self, local_data, server_data):
        """Evidenzia le righe diverse tra le due tabelle."""
        if not local_data or not server_data:
            return
            
        highlight_color = QColor("#EBCB8B")  # Giallo Nord
        
        for row in range(self.local_table.rowCount()):
            key_item = self.local_table.item(row, 0)
            val_item = self.local_table.item(row, 1)
            if not key_item or not val_item:
                continue
            
            key = key_item.text()
            local_val = val_item.text()
            server_val = str(server_data.get(key, ''))

            if local_val != server_val:
                key_item.setBackground(highlight_color)
                val_item.setBackground(highlight_color)
                
                # Cerca e evidenzia nella tabella server
                for srv_row in range(self.server_table.rowCount()):
                    srv_key_item = self.server_table.item(srv_row, 0)
                    if srv_key_item and srv_key_item.text() == key:
                        srv_key_item.setBackground(highlight_color)
                        srv_val_item = self.server_table.item(srv_row, 1)
                        if srv_val_item:
                            srv_val_item.setBackground(highlight_color)
                        break

    def _get_selected_conflict(self):
        """Restituisce il conflitto attualmente selezionato."""
        row = self.table.currentRow()
        if 0 <= row < len(self.conflicts):
            return row, self.conflicts[row]
        return None, None

    def _resolve_keep_local(self):
        """Risolve il conflitto mantenendo la versione locale."""
        row, conflict = self._get_selected_conflict()
        if conflict is None:
            return

        try:
            conflict_id = conflict['conflict_id']
            table_name = conflict.get('table_name')
            local_data = conflict.get('local_data') or {}
            record_uuid = conflict.get('record_uuid')

            # Se abbiamo dati locali, forza aggiornamento timestamp per ri-pushare
            if local_data and record_uuid and table_name:
                try:
                    timestamp = datetime.now(timezone.utc).isoformat()
                    database.force_update_timestamp(table_name, record_uuid, timestamp)
                except Exception as e:
                    logging.warning(f"Impossibile forzare timestamp per {table_name}/{record_uuid}: {e}")

            database.resolve_sync_conflict(conflict_id, 'keep_local')
            
            self.conflicts.pop(row)
            self._populate_table()
            self._update_count_label()
            self.local_table.setRowCount(0)
            self.server_table.setRowCount(0)
            self.error_label.hide()
            
            logging.info(f"Conflitto risolto: mantieni locale ({table_name}, uuid={record_uuid})")
        except Exception as e:
            logging.error(f"Errore risoluzione conflitto: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore durante la risoluzione del conflitto: {e}")

    def _resolve_use_server(self):
        """Risolve il conflitto usando la versione server."""
        row, conflict = self._get_selected_conflict()
        if conflict is None:
            return

        try:
            conflict_id = conflict['conflict_id']
            table_name = conflict.get('table_name')
            server_data = conflict.get('server_data') or {}
            record_uuid = conflict.get('record_uuid')

            # Se abbiamo dati server, sovrascriviamo il record locale
            if server_data and table_name:
                try:
                    # Assicurati che l'uuid sia nei dati
                    if record_uuid and 'uuid' not in server_data:
                        server_data['uuid'] = record_uuid
                    database.overwrite_local_record(table_name, server_data, is_conflict_resolution=True)
                except Exception as e:
                    logging.warning(f"Impossibile sovrascrivere record locale per {table_name}/{record_uuid}: {e}")

            database.resolve_sync_conflict(conflict_id, 'use_server')
            
            self.conflicts.pop(row)
            self._populate_table()
            self._update_count_label()
            self.local_table.setRowCount(0)
            self.server_table.setRowCount(0)
            self.error_label.hide()
            
            logging.info(f"Conflitto risolto: usa server ({table_name}, uuid={record_uuid})")
        except Exception as e:
            logging.error(f"Errore risoluzione conflitto: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore durante la risoluzione del conflitto: {e}")

    def _resolve_dismiss(self):
        """Ignora/scarta il conflitto."""
        row, conflict = self._get_selected_conflict()
        if conflict is None:
            return

        reply = QMessageBox.question(
            self, "Conferma",
            "Sei sicuro di voler ignorare questo conflitto?\n"
            "Il record in questione potrebbe non essere sincronizzato correttamente.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            conflict_id = conflict['conflict_id']
            database.resolve_sync_conflict(conflict_id, 'dismissed')
            
            self.conflicts.pop(row)
            self._populate_table()
            self._update_count_label()
            self.local_table.setRowCount(0)
            self.server_table.setRowCount(0)
            self.error_label.hide()
            
            logging.info(f"Conflitto ignorato: {conflict.get('table_name')}, uuid={conflict.get('record_uuid')}")
        except Exception as e:
            logging.error(f"Errore dismissione conflitto: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore: {e}")

    def _resolve_all_server(self):
        """Risolve tutti i conflitti usando la versione del server."""
        if not self.conflicts:
            return

        reply = QMessageBox.question(
            self, "Conferma Risoluzione Massiva",
            f"Stai per risolvere tutti i {len(self.conflicts)} conflitti usando la versione del server.\n\n"
            "Le versioni locali in conflitto verranno sovrascritte.\n"
            "Sei sicuro di voler continuare?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        resolved = 0
        errors = 0
        for conflict in list(self.conflicts):
            try:
                conflict_id = conflict['conflict_id']
                table_name = conflict.get('table_name')
                server_data = conflict.get('server_data') or {}
                record_uuid = conflict.get('record_uuid')

                if server_data and table_name:
                    try:
                        if record_uuid and 'uuid' not in server_data:
                            server_data['uuid'] = record_uuid
                        database.overwrite_local_record(table_name, server_data, is_conflict_resolution=True)
                    except Exception as e:
                        logging.warning(f"Impossibile sovrascrivere {table_name}/{record_uuid}: {e}")

                database.resolve_sync_conflict(conflict_id, 'use_server')
                resolved += 1
            except Exception as e:
                errors += 1
                logging.error(f"Errore risoluzione massiva: {e}")

        self.conflicts = database.get_pending_sync_conflicts()
        self._populate_table()
        self._update_count_label()
        self.local_table.setRowCount(0)
        self.server_table.setRowCount(0)
        self.error_label.hide()

        msg = f"Risolti {resolved} conflitti usando la versione del server."
        if errors > 0:
            msg += f"\n{errors} conflitti non sono stati risolti."
        QMessageBox.information(self, "Risoluzione Completata", msg)

    def _update_count_label(self):
        """Aggiorna il contatore dei conflitti."""
        count = len(self.conflicts)
        if count == 0:
            self.count_label.setText("✅ Tutti i conflitti risolti!")
            self.count_label.setStyleSheet("color: #A3BE8C; font-weight: bold;")
        else:
            self.count_label.setText(f"{count} conflitt{'o' if count == 1 else 'i'} da risolvere")
            self.count_label.setStyleSheet("color: #BF616A; font-weight: bold;")
        
        # Disabilita pulsanti se non ci sono più conflitti
        has_conflicts = count > 0
        self.btn_resolve_all_server.setEnabled(has_conflicts)
