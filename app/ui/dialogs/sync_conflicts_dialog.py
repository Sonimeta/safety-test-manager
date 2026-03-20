# app/ui/dialogs/sync_conflicts_dialog.py
"""
Dialog per la gestione e risoluzione dei conflitti di sincronizzazione.
Supporta:
- Visualizzazione side-by-side con evidenziazione differenze
- Risoluzione per-campo (merge manuale)
- Risoluzione rapida: mantieni locale / usa server / ignora
- Risoluzione batch: tutti locale / tutti server
- Pulizia automatica conflitti risolti
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QGroupBox, QMessageBox, QWidget, QSplitter, QRadioButton,
    QButtonGroup, QScrollArea, QFrame, QSizePolicy
)
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtCore import Qt, Signal
import logging
import json
import database
from app import services
from datetime import datetime, timezone


# ── Mappature user-friendly ──────────────────────────────────────────────────

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
    "audit_log": "Log Operazioni",
}

CONFLICT_TYPE_NAMES = {
    "duplicate_serial_number": "Numero di Serie Duplicato",
    "integrity_constraint": "Vincolo di Integrità",
    "foreign_key_missing": "Riferimento Mancante",
    "operational_error": "Errore Operativo",
    "update_conflict": "Conflitto di Aggiornamento",
    "update_serial_error": "Errore Aggiornamento Seriale",
    "table_error": "Errore Tabella",
    "modification_conflict": "Modifica Conflittuale",
    "serial_conflict": "Conflitto Numero di Serie",
}

SEVERITY_COLORS = {
    "low": "#A3BE8C",       # Verde
    "medium": "#EBCB8B",    # Giallo
    "high": "#D08770",      # Arancione
    "critical": "#BF616A",  # Rosso
}

SEVERITY_NAMES = {
    "low": "Basso",
    "medium": "Medio",
    "high": "Alto",
    "critical": "Critico",
}

# Campi tecnici nascosti nella visualizzazione dei dati
HIDDEN_FIELDS = {'id', 'is_synced', 'last_modified', 'created_at'}

# Campi binari/lunghi da troncare
BINARY_FIELDS = {'signature_data', 'image_data', 'photo'}

# Nomi user-friendly per i campi più comuni
FIELD_DISPLAY_NAMES = {
    "uuid": "ID Univoco",
    "name": "Nome",
    "address": "Indirizzo",
    "phone": "Telefono",
    "email": "Email",
    "serial_number": "Numero di Serie",
    "manufacturer": "Costruttore",
    "model": "Modello",
    "description": "Descrizione",
    "status": "Stato",
    "location": "Ubicazione",
    "destination_id": "Destinazione",
    "customer_id": "Cliente",
    "test_date": "Data Test",
    "notes": "Note",
    "is_deleted": "Eliminato",
    "username": "Utente",
    "profile_key": "Chiave Profilo",
    "profile_name": "Nome Profilo",
    "default_profile_key": "Profilo VE Predefinito",
    "default_functional_profile_key": "Profilo Funzionale Predefinito",
}


class SyncConflictsDialog(QDialog):
    """Dialog principale per la gestione dei conflitti di sincronizzazione."""

    conflicts_resolved = Signal()  # Emesso quando almeno un conflitto è stato risolto

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestione Conflitti di Sincronizzazione")
        self.setMinimumSize(1050, 650)
        self.resize(1200, 750)

        self.conflicts = database.get_pending_sync_conflicts()
        self._resolved_count = 0
        self._merge_radios = {}  # {field_name: QButtonGroup} per il merge per-campo

        self._build_ui()
        self._populate_table()

    # ── Costruzione UI ────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── Header ──
        header = QHBoxLayout()

        title = QLabel("⚠️ Conflitti di Sincronizzazione")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        header.addWidget(title)

        header.addStretch()

        self.count_label = QLabel()
        self.count_label.setFont(QFont("Segoe UI", 11))
        header.addWidget(self.count_label)

        layout.addLayout(header)

        # ── Descrizione ──
        desc = QLabel(
            "Durante la sincronizzazione sono stati rilevati dei conflitti che richiedono la tua attenzione.\n"
            "Seleziona un conflitto dalla lista per vederne i dettagli. "
            "Puoi scegliere quale versione mantenere oppure unire i campi manualmente."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8899A6; margin-bottom: 4px;")
        layout.addWidget(desc)

        # ── Splitter verticale: lista + dettaglio ──
        splitter = QSplitter(Qt.Vertical)

        # ── Tabella conflitti ──
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Tabella", "Tipo Conflitto", "Gravità", "Messaggio", "Data"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.currentCellChanged.connect(self._on_conflict_selected)
        splitter.addWidget(self.table)

        # ── Pannello dettagli ──
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 6, 0, 0)

        # Info conflitto
        self.detail_header = QLabel("Seleziona un conflitto dalla lista per vederne i dettagli.")
        self.detail_header.setFont(QFont("Segoe UI", 10, QFont.Bold))
        detail_layout.addWidget(self.detail_header)

        # Messaggio errore
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(
            "color: #BF616A; background: rgba(191,97,106,0.1); "
            "padding: 6px; border-radius: 4px;"
        )
        self.error_label.hide()
        detail_layout.addWidget(self.error_label)

        # Scroll area per la tabella merge
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self.merge_container = QWidget()
        self.merge_layout = QVBoxLayout(self.merge_container)
        self.merge_layout.setContentsMargins(0, 0, 0, 0)

        scroll.setWidget(self.merge_container)
        detail_layout.addWidget(scroll)

        splitter.addWidget(detail_widget)
        splitter.setSizes([220, 380])
        layout.addWidget(splitter, 1)

        # ── Pulsanti azione singolo conflitto ──
        single_action = QHBoxLayout()

        self.btn_keep_local = QPushButton("📁 Mantieni Versione Locale")
        self.btn_keep_local.setToolTip("Mantiene i dati locali e li forza al prossimo sync")
        self.btn_keep_local.clicked.connect(self._resolve_keep_local)
        self.btn_keep_local.setEnabled(False)
        single_action.addWidget(self.btn_keep_local)

        self.btn_use_server = QPushButton("☁️ Usa Versione Server")
        self.btn_use_server.setToolTip("Sovrascrive i dati locali con quelli del server")
        self.btn_use_server.clicked.connect(self._resolve_use_server)
        self.btn_use_server.setEnabled(False)
        single_action.addWidget(self.btn_use_server)

        self.btn_merge = QPushButton("🔀 Applica Merge Selezionato")
        self.btn_merge.setToolTip(
            "Unisce i campi secondo le scelte fatte nella tabella di confronto"
        )
        self.btn_merge.clicked.connect(self._resolve_merge)
        self.btn_merge.setEnabled(False)
        single_action.addWidget(self.btn_merge)

        self.btn_dismiss = QPushButton("🗑️ Ignora")
        self.btn_dismiss.setToolTip("Ignora il conflitto (il record potrebbe restare incoerente)")
        self.btn_dismiss.clicked.connect(self._resolve_dismiss)
        self.btn_dismiss.setEnabled(False)
        single_action.addWidget(self.btn_dismiss)

        layout.addLayout(single_action)

        # ── Separatore + pulsanti batch ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        batch_layout = QHBoxLayout()

        self.btn_resolve_all_local = QPushButton("Risolvi Tutti → Locale")
        self.btn_resolve_all_local.setToolTip("Risolve tutti i conflitti mantenendo la versione locale")
        self.btn_resolve_all_local.clicked.connect(self._resolve_all_local)
        batch_layout.addWidget(self.btn_resolve_all_local)

        self.btn_resolve_all_server = QPushButton("Risolvi Tutti → Server")
        self.btn_resolve_all_server.setToolTip("Risolve tutti i conflitti usando la versione del server")
        self.btn_resolve_all_server.clicked.connect(self._resolve_all_server)
        batch_layout.addWidget(self.btn_resolve_all_server)

        batch_layout.addStretch()

        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.accept)
        batch_layout.addWidget(close_btn)

        layout.addLayout(batch_layout)

        self._update_count_label()

    # ── Tabella conflitti ─────────────────────────────────────────────────────

    def _populate_table(self):
        """Popola la tabella con i conflitti pendenti."""
        self.table.setRowCount(0)

        for conflict in self.conflicts:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Tabella
            table_name = conflict.get('table_name', 'N/A')
            self.table.setItem(
                row, 0,
                QTableWidgetItem(TABLE_DISPLAY_NAMES.get(table_name, table_name))
            )

            # Tipo conflitto
            conflict_type = conflict.get('conflict_type', 'N/A')
            self.table.setItem(
                row, 1,
                QTableWidgetItem(CONFLICT_TYPE_NAMES.get(conflict_type, conflict_type))
            )

            # Gravità
            severity = conflict.get('severity', 'medium')
            sev_item = QTableWidgetItem(SEVERITY_NAMES.get(severity, severity))
            sev_color = SEVERITY_COLORS.get(severity, '#EBCB8B')
            sev_item.setBackground(QColor(sev_color))
            sev_item.setForeground(QColor("#2E3440"))
            self.table.setItem(row, 2, sev_item)

            # Messaggio
            msg = conflict.get('error_message', '')
            if len(msg) > 120:
                msg = msg[:120] + "…"
            self.table.setItem(row, 3, QTableWidgetItem(msg))

            # Data
            created = conflict.get('created_at', '')
            if created:
                try:
                    dt = datetime.fromisoformat(str(created))
                    created = dt.strftime("%d/%m/%Y %H:%M")
                except Exception:
                    pass
            self.table.setItem(row, 4, QTableWidgetItem(str(created)))

        if not self.conflicts:
            self.table.insertRow(0)
            item = QTableWidgetItem("✅ Nessun conflitto da risolvere!")
            item.setForeground(QColor("#A3BE8C"))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, 5)

    # ── Dettaglio conflitto (tabella merge per-campo) ─────────────────────────

    def _on_conflict_selected(self, current_row, current_col, prev_row, prev_col):
        """Quando l'utente seleziona un conflitto, mostra i dettagli con merge per-campo."""
        has_selection = 0 <= current_row < len(self.conflicts)
        self.btn_keep_local.setEnabled(has_selection)
        self.btn_use_server.setEnabled(has_selection)
        self.btn_dismiss.setEnabled(has_selection)
        self.btn_merge.setEnabled(False)

        # Pulisci il contenitore del merge
        self._clear_merge_panel()

        if not has_selection:
            self.detail_header.setText("Seleziona un conflitto dalla lista per vederne i dettagli.")
            self.error_label.hide()
            return

        conflict = self.conflicts[current_row]
        table_name = conflict.get('table_name', 'N/A')
        display_table = TABLE_DISPLAY_NAMES.get(table_name, table_name)
        conflict_type = conflict.get('conflict_type', '')
        display_type = CONFLICT_TYPE_NAMES.get(conflict_type, conflict_type)

        self.detail_header.setText(
            f"Confronto campi — {display_table} • {display_type}"
        )

        # Messaggio errore
        error_msg = conflict.get('error_message', '')
        if error_msg:
            self.error_label.setText(f"ℹ️ {error_msg}")
            self.error_label.show()
        else:
            self.error_label.hide()

        # Dati
        local_data = conflict.get('local_data') or {}
        server_data = conflict.get('server_data') or {}

        # Costruisci la tabella di merge per-campo
        self._build_merge_table(local_data, server_data)

    def _clear_merge_panel(self):
        """Rimuove tutti i widget dal pannello merge."""
        self._merge_radios = {}
        while self.merge_layout.count():
            item = self.merge_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _build_merge_table(self, local_data: dict, server_data: dict):
        """
        Costruisce una tabella di confronto campo-per-campo con radio buttons
        per selezionare la sorgente preferita per ogni campo divergente.
        """
        # Se non abbiamo dati da entrambi i lati, mostra tabella semplice
        if not local_data and not server_data:
            lbl = QLabel("Nessun dato disponibile per il confronto.")
            lbl.setStyleSheet("color: #8899A6; padding: 12px;")
            self.merge_layout.addWidget(lbl)
            return

        # Raccogli tutti i campi (unione)
        all_keys = set()
        if local_data:
            all_keys.update(local_data.keys())
        if server_data:
            all_keys.update(server_data.keys())

        # Filtra campi nascosti
        visible_keys = sorted(
            [k for k in all_keys if k not in HIDDEN_FIELDS and k != 'id'],
            key=str.lower
        )

        if not visible_keys:
            lbl = QLabel("Nessun campo visibile nel confronto.")
            lbl.setStyleSheet("color: #8899A6; padding: 12px;")
            self.merge_layout.addWidget(lbl)
            return

        has_both_sides = bool(local_data) and bool(server_data)
        has_differences = False

        # Tabella: Campo | Valore Locale | Valore Server | [Radio Locale | Radio Server]
        n_cols = 5 if has_both_sides else 2
        merge_table = QTableWidget()
        merge_table.setColumnCount(n_cols)

        if has_both_sides:
            merge_table.setHorizontalHeaderLabels([
                "Campo", "📁 Valore Locale", "☁️ Valore Server", "Locale", "Server"
            ])
        else:
            if local_data:
                merge_table.setHorizontalHeaderLabels(["Campo", "📁 Valore Locale"])
            else:
                merge_table.setHorizontalHeaderLabels(["Campo", "☁️ Valore Server"])

        merge_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        merge_table.setSelectionMode(QAbstractItemView.NoSelection)
        merge_table.verticalHeader().setVisible(False)
        merge_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        merge_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        if n_cols >= 3:
            merge_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        if n_cols >= 5:
            merge_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            merge_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)

        self._merge_radios = {}

        for key in visible_keys:
            local_val = self._format_value(key, local_data.get(key) if local_data else None)
            server_val = self._format_value(key, server_data.get(key) if server_data else None)
            is_different = (local_val != server_val) and has_both_sides
            if is_different:
                has_differences = True

            row = merge_table.rowCount()
            merge_table.insertRow(row)

            # Campo (con nome user-friendly)
            display_name = FIELD_DISPLAY_NAMES.get(key, key)
            field_item = QTableWidgetItem(display_name)
            field_item.setToolTip(key)  # Mostra il nome tecnico come tooltip
            merge_table.setItem(row, 0, field_item)

            # Valore locale
            local_item = QTableWidgetItem(local_val)
            merge_table.setItem(row, 1, local_item)

            if has_both_sides:
                # Valore server
                server_item = QTableWidgetItem(server_val)
                merge_table.setItem(row, 2, server_item)

                if is_different:
                    # Evidenzia in giallo
                    highlight = QColor("#EBCB8B")
                    for col in range(3):
                        item = merge_table.item(row, col)
                        if item:
                            item.setBackground(highlight)
                            item.setForeground(QColor("#2E3440"))

                    # Radio buttons per merge
                    grp = QButtonGroup(merge_table)
                    radio_local = QRadioButton()
                    radio_server = QRadioButton()
                    radio_server.setChecked(True)  # Default: server vince
                    grp.addButton(radio_local, 0)
                    grp.addButton(radio_server, 1)

                    merge_table.setCellWidget(row, 3, self._center_widget(radio_local))
                    merge_table.setCellWidget(row, 4, self._center_widget(radio_server))

                    self._merge_radios[key] = grp
                    grp.buttonToggled.connect(lambda *_: self._update_merge_button_state())

        self.merge_layout.addWidget(merge_table)

        # Abilita il pulsante merge solo se ci sono differenze e dati su entrambi i lati
        self.btn_merge.setEnabled(has_differences and has_both_sides)

        if not has_differences and has_both_sides:
            info = QLabel("ℹ️ I dati locali e server sono identici. Puoi ignorare questo conflitto.")
            info.setStyleSheet("color: #A3BE8C; padding: 6px;")
            self.merge_layout.addWidget(info)

    @staticmethod
    def _center_widget(widget):
        """Avvolge un widget in un container centrato."""
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setAlignment(Qt.AlignCenter)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget)
        return container

    @staticmethod
    def _format_value(key: str, value) -> str:
        """Formatta un valore per la visualizzazione."""
        if value is None:
            return ""
        if key in BINARY_FIELDS:
            s = str(value)
            if len(s) > 60:
                return f"[dati binari — {len(s)} caratteri]"
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        return str(value)

    def _update_merge_button_state(self):
        """Aggiorna lo stato del pulsante merge."""
        self.btn_merge.setEnabled(len(self._merge_radios) > 0)

    # ── Risoluzione singola ───────────────────────────────────────────────────

    def _get_selected_conflict(self):
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
            record_uuid = conflict.get('record_uuid')
            local_data = conflict.get('local_data') or {}

            if local_data and record_uuid and table_name:
                ts = datetime.now(timezone.utc).isoformat()
                database.force_update_timestamp(table_name, record_uuid, ts)

            database.resolve_sync_conflict(conflict_id, 'keep_local')
            self._after_resolve(row, f"mantieni locale ({table_name}, uuid={record_uuid})")
        except Exception as e:
            logging.error(f"Errore risoluzione conflitto (mantieni locale): {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore durante la risoluzione del conflitto:\n{e}")

    def _resolve_use_server(self):
        """Risolve il conflitto usando la versione del server."""
        row, conflict = self._get_selected_conflict()
        if conflict is None:
            return

        try:
            conflict_id = conflict['conflict_id']
            table_name = conflict.get('table_name')
            record_uuid = conflict.get('record_uuid')
            server_data = conflict.get('server_data') or {}

            if server_data and table_name:
                if record_uuid and 'uuid' not in server_data:
                    server_data['uuid'] = record_uuid
                database.overwrite_local_record(table_name, server_data, is_conflict_resolution=True)

            database.resolve_sync_conflict(conflict_id, 'use_server')
            self._after_resolve(row, f"usa server ({table_name}, uuid={record_uuid})")
        except Exception as e:
            logging.error(f"Errore risoluzione conflitto (usa server): {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore durante la risoluzione del conflitto:\n{e}")

    def _resolve_merge(self):
        """Risolve il conflitto unendo i campi secondo le scelte radio."""
        row, conflict = self._get_selected_conflict()
        if conflict is None:
            return

        try:
            conflict_id = conflict['conflict_id']
            table_name = conflict.get('table_name')
            record_uuid = conflict.get('record_uuid')
            local_data = conflict.get('local_data') or {}
            server_data = conflict.get('server_data') or {}

            if not local_data or not server_data:
                QMessageBox.warning(
                    self, "Merge non possibile",
                    "Per eseguire il merge servono sia i dati locali che quelli del server."
                )
                return

            # Costruisci il record merged: parti dalla versione server
            merged = server_data.copy()

            # Per ogni campo con radio, applica la scelta
            for field_name, grp in self._merge_radios.items():
                checked_id = grp.checkedId()
                if checked_id == 0:
                    # L'utente vuole il valore locale
                    merged[field_name] = local_data.get(field_name)
                # else: valore server (già nel merged)

            # Assicura UUID
            if record_uuid and 'uuid' not in merged:
                merged['uuid'] = record_uuid

            # Scrivi il record merged
            if table_name:
                database.overwrite_local_record(table_name, merged, is_conflict_resolution=True)
                # Forza re-push per inviare i campi locali scelti al server
                try:
                    ts = datetime.now(timezone.utc).isoformat()
                    database.force_update_timestamp(table_name, record_uuid or merged.get('uuid'), ts)
                except Exception:
                    pass

            database.resolve_sync_conflict(conflict_id, 'merged')
            self._after_resolve(row, f"merge manuale ({table_name}, uuid={record_uuid})")
        except Exception as e:
            logging.error(f"Errore merge conflitto: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore durante il merge:\n{e}")

    def _resolve_dismiss(self):
        """Ignora il conflitto."""
        row, conflict = self._get_selected_conflict()
        if conflict is None:
            return

        reply = QMessageBox.question(
            self, "Conferma",
            "Sei sicuro di voler ignorare questo conflitto?\n\n"
            "Il record in questione potrebbe non essere sincronizzato correttamente.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            conflict_id = conflict['conflict_id']
            database.resolve_sync_conflict(conflict_id, 'dismissed')
            self._after_resolve(row, f"ignorato ({conflict.get('table_name')}, uuid={conflict.get('record_uuid')})")
        except Exception as e:
            logging.error(f"Errore dismissione conflitto: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Errore: {e}")

    def _after_resolve(self, row: int, log_msg: str):
        """Operazioni comuni dopo la risoluzione di un conflitto."""
        logging.info(f"Conflitto risolto: {log_msg}")
        self._resolved_count += 1
        self.conflicts.pop(row)
        self._populate_table()
        self._update_count_label()
        self._clear_merge_panel()
        self.detail_header.setText("Seleziona un conflitto dalla lista per vederne i dettagli.")
        self.error_label.hide()
        self.btn_keep_local.setEnabled(False)
        self.btn_use_server.setEnabled(False)
        self.btn_merge.setEnabled(False)
        self.btn_dismiss.setEnabled(False)

    # ── Risoluzione batch ─────────────────────────────────────────────────────

    def _resolve_all_local(self):
        """Risolve tutti i conflitti mantenendo la versione locale."""
        if not self.conflicts:
            return

        reply = QMessageBox.question(
            self, "Conferma Risoluzione Massiva",
            f"Stai per risolvere tutti i {len(self.conflicts)} conflitti "
            f"mantenendo la versione <b>locale</b>.\n\n"
            "I dati locali verranno forzati al prossimo sync.\n"
            "Sei sicuro di voler continuare?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        resolved, errors = 0, 0
        for conflict in list(self.conflicts):
            try:
                cid = conflict['conflict_id']
                table_name = conflict.get('table_name')
                record_uuid = conflict.get('record_uuid')
                local_data = conflict.get('local_data') or {}

                if local_data and record_uuid and table_name:
                    ts = datetime.now(timezone.utc).isoformat()
                    database.force_update_timestamp(table_name, record_uuid, ts)

                database.resolve_sync_conflict(cid, 'keep_local')
                resolved += 1
            except Exception as e:
                errors += 1
                logging.error(f"Errore batch keep_local ({table_name}/{record_uuid}): {e}")

        self._after_batch_resolve(resolved, errors)

    def _resolve_all_server(self):
        """Risolve tutti i conflitti usando la versione del server."""
        if not self.conflicts:
            return

        reply = QMessageBox.question(
            self, "Conferma Risoluzione Massiva",
            f"Stai per risolvere tutti i {len(self.conflicts)} conflitti "
            f"usando la versione del <b>server</b>.\n\n"
            "Le versioni locali in conflitto verranno sovrascritte.\n"
            "Sei sicuro di voler continuare?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        resolved, errors = 0, 0
        for conflict in list(self.conflicts):
            try:
                cid = conflict['conflict_id']
                table_name = conflict.get('table_name')
                record_uuid = conflict.get('record_uuid')
                server_data = conflict.get('server_data') or {}

                if server_data and table_name:
                    if record_uuid and 'uuid' not in server_data:
                        server_data['uuid'] = record_uuid
                    database.overwrite_local_record(table_name, server_data, is_conflict_resolution=True)

                database.resolve_sync_conflict(cid, 'use_server')
                resolved += 1
            except Exception as e:
                errors += 1
                logging.error(f"Errore batch use_server ({table_name}/{record_uuid}): {e}")

        self._after_batch_resolve(resolved, errors)

    def _after_batch_resolve(self, resolved: int, errors: int):
        """Aggiornamento UI dopo risoluzione batch."""
        self._resolved_count += resolved
        self.conflicts = database.get_pending_sync_conflicts()
        self._populate_table()
        self._update_count_label()
        self._clear_merge_panel()
        self.detail_header.setText("Seleziona un conflitto dalla lista per vederne i dettagli.")
        self.error_label.hide()

        msg = f"✅ {resolved} conflitti risolti."
        if errors > 0:
            msg += f"\n⚠️ {errors} conflitti non sono stati risolti a causa di errori."
        QMessageBox.information(self, "Risoluzione Completata", msg)

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _update_count_label(self):
        count = len(self.conflicts)
        has_conflicts = count > 0
        if count == 0:
            self.count_label.setText("✅ Tutti i conflitti risolti!")
            self.count_label.setStyleSheet("color: #A3BE8C; font-weight: bold;")
        else:
            self.count_label.setText(
                f"{count} conflitt{'o' if count == 1 else 'i'} da risolvere"
            )
            self.count_label.setStyleSheet("color: #BF616A; font-weight: bold;")

        self.btn_resolve_all_local.setEnabled(has_conflicts)
        self.btn_resolve_all_server.setEnabled(has_conflicts)

    def accept(self):
        """Override: emetti segnale se abbiamo risolto almeno un conflitto."""
        if self._resolved_count > 0:
            self.conflicts_resolved.emit()
        super().accept()

    def reject(self):
        """Override: emetti segnale se abbiamo risolto almeno un conflitto."""
        if self._resolved_count > 0:
            self.conflicts_resolved.emit()
        super().reject()
