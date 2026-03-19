# app/ui/dialogs/deleted_data_dialog.py
"""
Dialog per la gestione dei dati eliminati (soft-deleted).
Visibile solo agli utenti admin.
Consente di visualizzare e eliminare definitivamente i record marcati come eliminati,
sia dal database locale che dal database online.
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QTableWidget, QTableWidgetItem, QPushButton, QLabel,
                               QHeaderView, QAbstractItemView, QMessageBox, QWidget,
                               QGroupBox, QApplication)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from app import config, auth_manager
import qtawesome as qta
import database
import requests
import logging

# Costanti sorgente
SOURCE_LOCAL = 'local'
SOURCE_ONLINE = 'online'
SOURCE_BOTH = 'both'

SOURCE_LABELS = {
    SOURCE_LOCAL: '📱 Locale',
    SOURCE_ONLINE: '☁️ Online',
    SOURCE_BOTH: '📱☁️ Entrambi',
}

SOURCE_COLORS = {
    SOURCE_LOCAL: '#2563eb',   # Blu
    SOURCE_ONLINE: '#7c3aed',  # Viola
    SOURCE_BOTH: '#059669',    # Verde
}

# Configurazione delle tab con le entità gestite
ENTITY_TABS = [
    {
        'key': 'customers',
        'label': '🏢 Clienti',
        'icon': 'fa5s.building',
        'columns': ['ID', 'UUID', 'Nome', 'Indirizzo', 'Telefono', 'Email', 'Ultima Modifica', 'Sorgente'],
        'fields': ['id', 'uuid', 'name', 'address', 'phone', 'email', 'last_modified', '_source'],
        'loader': 'get_deleted_customers',
    },
    {
        'key': 'destinations',
        'label': '📍 Destinazioni',
        'icon': 'fa5s.map-marker-alt',
        'columns': ['ID', 'UUID', 'Nome', 'Indirizzo', 'Cliente', 'Ultima Modifica', 'Sorgente'],
        'fields': ['id', 'uuid', 'name', 'address', 'customer_name', 'last_modified', '_source'],
        'loader': 'get_deleted_destinations',
    },
    {
        'key': 'devices',
        'label': '🔌 Dispositivi',
        'icon': 'fa5s.plug',
        'columns': ['ID', 'UUID', 'Matricola', 'Descrizione', 'Produttore', 'Modello', 'Destinazione', 'Cliente', 'Ultima Modifica', 'Sorgente'],
        'fields': ['id', 'uuid', 'serial_number', 'description', 'manufacturer', 'model', 'destination_name', 'customer_name', 'last_modified', '_source'],
        'loader': 'get_deleted_devices',
    },
    {
        'key': 'verifications',
        'label': '⚡ Verifiche Elettriche',
        'icon': 'fa5s.bolt',
        'columns': ['ID', 'UUID', 'Data', 'Profilo', 'Esito', 'Tecnico', 'Codice', 'Dispositivo', 'Descrizione Disp.', 'Ultima Modifica', 'Sorgente'],
        'fields': ['id', 'uuid', 'verification_date', 'profile_name', 'overall_status', 'technician_name', 'verification_code', 'device_serial', 'device_description', 'last_modified', '_source'],
        'loader': 'get_deleted_verifications',
    },
    {
        'key': 'functional_verifications',
        'label': '🔧 Verifiche Funzionali',
        'icon': 'fa5s.heartbeat',
        'columns': ['ID', 'UUID', 'Data', 'Profilo', 'Esito', 'Tecnico', 'Codice', 'Dispositivo', 'Descrizione Disp.', 'Ultima Modifica', 'Sorgente'],
        'fields': ['id', 'uuid', 'verification_date', 'profile_key', 'overall_status', 'technician_name', 'verification_code', 'device_serial', 'device_description', 'last_modified', '_source'],
        'loader': 'get_deleted_functional_verifications',
    },
    {
        'key': 'profiles',
        'label': '📋 Profili Elettrici',
        'icon': 'fa5s.clipboard-list',
        'columns': ['ID', 'UUID', 'Chiave Profilo', 'Nome', 'Ultima Modifica', 'Sorgente'],
        'fields': ['id', 'uuid', 'profile_key', 'name', 'last_modified', '_source'],
        'loader': 'get_deleted_profiles',
    },
    {
        'key': 'functional_profiles',
        'label': '📝 Profili Funzionali',
        'icon': 'fa5s.clipboard-check',
        'columns': ['ID', 'UUID', 'Chiave Profilo', 'Nome', 'Tipo Dispositivo', 'Ultima Modifica', 'Sorgente'],
        'fields': ['id', 'uuid', 'profile_key', 'name', 'device_type', 'last_modified', '_source'],
        'loader': 'get_deleted_functional_profiles',
    },
    {
        'key': 'mti_instruments',
        'label': '📏 Strumenti',
        'icon': 'fa5s.tools',
        'columns': ['ID', 'UUID', 'Nome', 'Matricola', 'Versione FW', 'Data Calibrazione', 'Tipo', 'Ultima Modifica', 'Sorgente'],
        'fields': ['id', 'uuid', 'instrument_name', 'serial_number', 'fw_version', 'calibration_date', 'instrument_type', 'last_modified', '_source'],
        'loader': 'get_deleted_instruments',
    },
]


def _fetch_online_deleted_data() -> dict | None:
    """
    Recupera i dati eliminati dal database online via API.
    Restituisce None se il server non è raggiungibile o in caso di errore.
    """
    try:
        headers = auth_manager.get_auth_headers()
        if not headers:
            logging.warning("Nessun token di autenticazione disponibile per la richiesta al server.")
            return None
        
        url = f"{config.SERVER_URL}/admin/deleted-data"
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 403:
            logging.warning("Accesso negato dal server per i dati eliminati (non admin).")
            return None
        else:
            logging.error(f"Errore dal server per dati eliminati: HTTP {response.status_code}")
            return None
    except requests.ConnectionError:
        logging.warning("Server non raggiungibile per il recupero dei dati eliminati.")
        return None
    except requests.Timeout:
        logging.warning("Timeout nella richiesta dei dati eliminati al server.")
        return None
    except Exception as e:
        logging.error(f"Errore imprevisto nel recupero dati eliminati online: {e}", exc_info=True)
        return None


def _merge_local_and_online(local_rows: list, online_rows: list | None) -> list:
    """
    Unisce i dati locali e online in un'unica lista, deduplicando per UUID.
    Ogni record avrà un campo '_source' che indica la provenienza:
    - 'local': solo nel DB locale
    - 'online': solo nel DB online
    - 'both': presente in entrambi
    """
    merged = {}
    
    for row in local_rows:
        row_dict = dict(row)
        row_uuid = row_dict.get('uuid', '')
        row_dict['_source'] = SOURCE_LOCAL
        row_dict['_local_id'] = row_dict.get('id')
        row_dict['_online_id'] = None
        merged[row_uuid] = row_dict
    
    if online_rows:
        for row_dict in online_rows:
            if not isinstance(row_dict, dict):
                row_dict = dict(row_dict)
            row_uuid = row_dict.get('uuid', '')
            row_dict_copy = dict(row_dict)
            
            if row_uuid in merged:
                # Record presente in entrambi
                merged[row_uuid]['_source'] = SOURCE_BOTH
                merged[row_uuid]['_online_id'] = row_dict_copy.get('id')
            else:
                # Record solo online
                row_dict_copy['_source'] = SOURCE_ONLINE
                row_dict_copy['_local_id'] = None
                row_dict_copy['_online_id'] = row_dict_copy.get('id')
                merged[row_uuid] = row_dict_copy
    
    return list(merged.values())


class DeletedDataDialog(QDialog):
    """
    Finestra di dialogo per la gestione dei dati eliminati.
    Consente di visualizzare i record soft-deleted e di eliminarli definitivamente
    da entrambi i database (locale e online).
    Accessibile solo agli utenti con ruolo admin.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🗑️ Gestione Dati Eliminati - Amministrazione")
        self.setWindowState(Qt.WindowMaximized)
        self.setStyleSheet(config.get_current_stylesheet())
        
        self.tables = {}       # dizionario tab_key -> QTableWidget
        self.tab_data = {}     # dizionario tab_key -> list of merged row dicts
        self.online_data = None  # Dati dal server online (cache)
        self.online_available = False
        
        self._setup_ui()
        self._load_all_data()

    def _setup_ui(self):
        """Costruisce l'interfaccia utente."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # ── Header ──
        header_layout = QHBoxLayout()
        
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.trash-alt', color='#dc2626').pixmap(40, 40))
        header_layout.addWidget(icon_label)
        
        title = QLabel("<h1>Gestione Dati Eliminati</h1>")
        header_layout.addWidget(title)
        
        subtitle = QLabel("<i style='color: #666;'>Visualizza e gestisci i record eliminati dal database locale e online</i>")
        header_layout.addWidget(subtitle)
        
        header_layout.addStretch()
        
        # Stato connessione server
        self.server_status_label = QLabel()
        self.server_status_label.setStyleSheet(
            "font-size: 12px; padding: 6px 12px; border-radius: 5px;"
        )
        header_layout.addWidget(self.server_status_label)
        
        # Conteggio totale
        self.total_label = QLabel()
        self.total_label.setStyleSheet(
            "font-size: 13px; padding: 8px 14px; background: #fee2e2; "
            "color: #991b1b; border-radius: 6px; font-weight: bold;"
        )
        header_layout.addWidget(self.total_label)
        
        # Pulsante aggiorna
        refresh_btn = QPushButton(qta.icon('fa5s.sync'), " Aggiorna")
        refresh_btn.setObjectName("autoButton")
        refresh_btn.setMinimumWidth(110)
        refresh_btn.clicked.connect(self._load_all_data)
        header_layout.addWidget(refresh_btn)
        
        main_layout.addLayout(header_layout)

        # ── Legenda sorgenti ──
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(QLabel("<b>Legenda:</b>"))
        for source_key, label in SOURCE_LABELS.items():
            color = SOURCE_COLORS[source_key]
            lbl = QLabel(f"<span style='color: {color}; font-weight: bold;'>{label}</span>")
            legend_layout.addWidget(lbl)
            legend_layout.addSpacing(15)
        legend_layout.addStretch()
        main_layout.addLayout(legend_layout)

        # ── Avviso ──
        warning_box = QGroupBox()
        warning_box.setStyleSheet(
            "QGroupBox { background: #fef3c7; border: 1px solid #f59e0b; border-radius: 8px; padding: 12px; }"
        )
        warning_layout = QHBoxLayout(warning_box)
        warning_icon = QLabel()
        warning_icon.setPixmap(qta.icon('fa5s.exclamation-triangle', color='#d97706').pixmap(24, 24))
        warning_layout.addWidget(warning_icon)
        warning_text = QLabel(
            "<b style='color: #92400e;'>⚠️ ATTENZIONE:</b> "
            "<span style='color: #78350f;'>L'eliminazione definitiva è <b>irreversibile</b>. "
            "I record verranno eliminati dal database di appartenenza (locale, online o entrambi). "
            "I dati eliminati definitivamente non potranno essere recuperati in alcun modo.</span>"
        )
        warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_text, 1)
        main_layout.addWidget(warning_box)

        # ── Tab Widget ──
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        
        for entity in ENTITY_TABS:
            tab = self._create_entity_tab(entity)
            self.tab_widget.addTab(tab, qta.icon(entity['icon']), entity['label'])
        
        main_layout.addWidget(self.tab_widget, 1)

        # ── Pulsanti in basso ──
        bottom_layout = QHBoxLayout()
        
        # Pulsante elimina selezionato
        self.delete_selected_btn = QPushButton(qta.icon('fa5s.trash', color='white'), " Elimina Selezionati Definitivamente")
        self.delete_selected_btn.setObjectName("deleteButton")
        self.delete_selected_btn.setMinimumHeight(38)
        self.delete_selected_btn.setMinimumWidth(280)
        self.delete_selected_btn.setStyleSheet(
            "QPushButton { background-color: #dc2626; color: white; font-weight: bold; "
            "border-radius: 6px; padding: 8px 18px; font-size: 13px; } "
            "QPushButton:hover { background-color: #b91c1c; } "
            "QPushButton:pressed { background-color: #991b1b; }"
        )
        self.delete_selected_btn.clicked.connect(self._delete_selected)
        bottom_layout.addWidget(self.delete_selected_btn)
        
        # Pulsante elimina tutti della tab corrente
        self.delete_all_tab_btn = QPushButton(qta.icon('fa5s.dumpster-fire', color='white'), " Elimina Tutti della Categoria")
        self.delete_all_tab_btn.setMinimumHeight(38)
        self.delete_all_tab_btn.setMinimumWidth(260)
        self.delete_all_tab_btn.setStyleSheet(
            "QPushButton { background-color: #7f1d1d; color: white; font-weight: bold; "
            "border-radius: 6px; padding: 8px 18px; font-size: 13px; } "
            "QPushButton:hover { background-color: #450a0a; } "
            "QPushButton:pressed { background-color: #300808; }"
        )
        self.delete_all_tab_btn.clicked.connect(self._delete_all_in_current_tab)
        bottom_layout.addWidget(self.delete_all_tab_btn)
        
        bottom_layout.addStretch()
        
        # Info selezione
        self.selection_label = QLabel("Nessun record selezionato")
        self.selection_label.setStyleSheet("color: #6b7280; font-style: italic;")
        bottom_layout.addWidget(self.selection_label)
        
        bottom_layout.addStretch()
        
        # Pulsante chiudi
        close_btn = QPushButton(qta.icon('fa5s.times'), " Chiudi")
        close_btn.setMinimumHeight(38)
        close_btn.setMinimumWidth(120)
        close_btn.clicked.connect(self.close)
        bottom_layout.addWidget(close_btn)
        
        main_layout.addLayout(bottom_layout)

    def _create_entity_tab(self, entity: dict) -> QWidget:
        """Crea un widget tab per un tipo di entità."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 10, 5, 5)
        
        # Info label per la tab
        info_layout = QHBoxLayout()
        count_label = QLabel()
        count_label.setObjectName(f"count_{entity['key']}")
        count_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #374151; padding: 4px;")
        info_layout.addWidget(count_label)
        info_layout.addStretch()
        
        # Checkbox seleziona tutti
        select_all_btn = QPushButton(qta.icon('fa5s.check-double'), " Seleziona Tutti")
        select_all_btn.setMinimumWidth(140)
        select_all_btn.clicked.connect(lambda checked, key=entity['key']: self._toggle_select_all(key))
        info_layout.addWidget(select_all_btn)
        
        layout.addLayout(info_layout)
        
        # Tabella
        table = QTableWidget()
        table.setColumnCount(len(entity['columns']))
        table.setHorizontalHeaderLabels(entity['columns'])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.MultiSelection)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        
        # Ridimensionamento colonne
        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        for i in range(len(entity['columns'])):
            col_name = entity['columns'][i]
            if col_name == 'ID':
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            elif col_name == 'UUID':
                # Nascondi la colonna UUID (serve internamente)
                table.setColumnHidden(i, True)
            elif col_name == 'Sorgente':
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)
        
        table.selectionModel().selectionChanged.connect(self._update_selection_label)
        
        self.tables[entity['key']] = table
        layout.addWidget(table, 1)
        
        return widget

    def _load_all_data(self):
        """Carica i dati eliminati da locale e online per tutte le tab."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # 1) Fetch dati online
            self.online_data = _fetch_online_deleted_data()
            self.online_available = self.online_data is not None
            
            # Aggiorna stato connessione
            if self.online_available:
                self.server_status_label.setText("☁️ Server online connesso")
                self.server_status_label.setStyleSheet(
                    "font-size: 12px; padding: 6px 12px; background: #dcfce7; "
                    "color: #166534; border-radius: 5px; font-weight: bold;"
                )
            else:
                self.server_status_label.setText("⚠️ Server non raggiungibile (solo dati locali)")
                self.server_status_label.setStyleSheet(
                    "font-size: 12px; padding: 6px 12px; background: #fef3c7; "
                    "color: #92400e; border-radius: 5px; font-weight: bold;"
                )
            
            total_deleted = 0
            
            # 2) Per ogni tab, carica locale + online e merge
            for idx, entity in enumerate(ENTITY_TABS):
                key = entity['key']
                
                # Carica dati locali
                loader_func = getattr(database, entity['loader'], None)
                local_rows = []
                if loader_func:
                    try:
                        local_rows = loader_func()
                    except Exception as e:
                        logging.error(f"Errore caricamento dati locali eliminati per {key}: {e}", exc_info=True)
                
                # Dati online per questa tabella
                online_rows = self.online_data.get(key, []) if self.online_data else None
                
                # Merge
                try:
                    merged = _merge_local_and_online(local_rows, online_rows)
                    self.tab_data[key] = merged
                    self._populate_table(key, entity, merged)
                    count = len(merged)
                    total_deleted += count
                    
                    # Conteggi per sorgente
                    local_only = sum(1 for r in merged if r.get('_source') == SOURCE_LOCAL)
                    online_only = sum(1 for r in merged if r.get('_source') == SOURCE_ONLINE)
                    both_count = sum(1 for r in merged if r.get('_source') == SOURCE_BOTH)
                    
                    # Aggiorna conteggio nella tab
                    tab_widget = self.tab_widget.widget(idx)
                    count_label = tab_widget.findChild(QLabel, f"count_{key}")
                    if count_label:
                        if count > 0:
                            detail_parts = []
                            if local_only > 0:
                                detail_parts.append(f"📱 {local_only} solo locale")
                            if online_only > 0:
                                detail_parts.append(f"☁️ {online_only} solo online")
                            if both_count > 0:
                                detail_parts.append(f"📱☁️ {both_count} entrambi")
                            detail_str = " | ".join(detail_parts)
                            count_label.setText(f"🗑️ {count} record eliminati trovati  ({detail_str})")
                            count_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #dc2626; padding: 4px;")
                        else:
                            count_label.setText("✅ Nessun record eliminato")
                            count_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #16a34a; padding: 4px;")
                    
                    # Aggiorna titolo tab con conteggio
                    tab_label = entity['label']
                    if count > 0:
                        tab_label += f" ({count})"
                    self.tab_widget.setTabText(idx, tab_label)
                    
                except Exception as e:
                    logging.error(f"Errore merge/caricamento dati eliminati per {key}: {e}", exc_info=True)
            
            # Aggiorna conteggio totale
            if total_deleted > 0:
                self.total_label.setText(f"🗑️ Totale record eliminati: {total_deleted}")
                self.total_label.setStyleSheet(
                    "font-size: 13px; padding: 8px 14px; background: #fee2e2; "
                    "color: #991b1b; border-radius: 6px; font-weight: bold;"
                )
            else:
                self.total_label.setText("✅ Nessun record eliminato nel database")
                self.total_label.setStyleSheet(
                    "font-size: 13px; padding: 8px 14px; background: #dcfce7; "
                    "color: #166534; border-radius: 6px; font-weight: bold;"
                )
        finally:
            QApplication.restoreOverrideCursor()

    def _populate_table(self, key: str, entity: dict, rows: list):
        """Popola una tabella con i dati forniti (merged local + online)."""
        table = self.tables[key]
        table.setSortingEnabled(False)
        table.setRowCount(0)
        table.setRowCount(len(rows))
        
        for row_idx, row_dict in enumerate(rows):
            for col_idx, field in enumerate(entity['fields']):
                if field == '_source':
                    source = row_dict.get('_source', SOURCE_LOCAL)
                    value = SOURCE_LABELS.get(source, source)
                    item = QTableWidgetItem(value)
                    color = SOURCE_COLORS.get(source, '#374151')
                    item.setForeground(QColor(color))
                    item.setFont(QFont("", -1, QFont.Bold))
                else:
                    value = str(row_dict.get(field, '') or '')
                    item = QTableWidgetItem(value)
                
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                
                # Colora l'ID in grigio
                if field == 'id':
                    item.setForeground(QColor('#9ca3af'))
                
                # Colora lo stato esito
                if field == 'overall_status':
                    if value.upper() in ('PASS', 'CONFORME', 'OK'):
                        item.setForeground(QColor('#16a34a'))
                        item.setFont(QFont("", -1, QFont.Bold))
                    elif value.upper() in ('FAIL', 'NON CONFORME', 'KO'):
                        item.setForeground(QColor('#dc2626'))
                        item.setFont(QFont("", -1, QFont.Bold))
                
                # Colora l'ultima modifica in grigio chiaro
                if field == 'last_modified':
                    item.setForeground(QColor('#6b7280'))
                
                table.setItem(row_idx, col_idx, item)
        
        table.setSortingEnabled(True)

    def _get_current_entity(self) -> dict:
        """Restituisce la configurazione dell'entità corrente."""
        idx = self.tab_widget.currentIndex()
        if 0 <= idx < len(ENTITY_TABS):
            return ENTITY_TABS[idx]
        return None

    def _get_selected_records(self) -> list:
        """
        Restituisce i dati completi dei record selezionati nella tab corrente.
        Ogni elemento è un dict con _source, _local_id, _online_id, uuid, ecc.
        """
        entity = self._get_current_entity()
        if not entity:
            return []
        
        key = entity['key']
        table = self.tables[key]
        all_rows = self.tab_data.get(key, [])
        
        selected_row_indices = set()
        for index in table.selectionModel().selectedRows():
            selected_row_indices.add(index.row())
        
        # Recupera UUID dalla colonna nascosta per trovare il record nel tab_data
        uuid_col_idx = entity['fields'].index('uuid') if 'uuid' in entity['fields'] else -1
        
        selected = []
        for row_idx in selected_row_indices:
            if uuid_col_idx >= 0:
                uuid_item = table.item(row_idx, uuid_col_idx)
                if uuid_item:
                    uuid_val = uuid_item.text()
                    # Trova il record corrispondente in tab_data
                    for rd in all_rows:
                        if rd.get('uuid') == uuid_val:
                            selected.append(rd)
                            break
        return selected

    def _toggle_select_all(self, key: str):
        """Seleziona o deseleziona tutti i record nella tab specificata."""
        table = self.tables.get(key)
        if not table:
            return
        
        if table.selectionModel().hasSelection() and len(table.selectionModel().selectedRows()) == table.rowCount():
            table.clearSelection()
        else:
            table.selectAll()

    def _update_selection_label(self):
        """Aggiorna l'etichetta con il conteggio dei record selezionati."""
        records = self._get_selected_records()
        if records:
            local_count = sum(1 for r in records if r.get('_source') in (SOURCE_LOCAL, SOURCE_BOTH))
            online_count = sum(1 for r in records if r.get('_source') in (SOURCE_ONLINE, SOURCE_BOTH))
            self.selection_label.setText(
                f"📌 {len(records)} selezionati (📱 {local_count} locale, ☁️ {online_count} online)"
            )
            self.selection_label.setStyleSheet("color: #2563eb; font-weight: bold;")
        else:
            self.selection_label.setText("Nessun record selezionato")
            self.selection_label.setStyleSheet("color: #6b7280; font-style: italic;")

    def _hard_delete_record_local(self, table_name: str, record_id: int) -> bool:
        """Elimina un record dal database locale."""
        try:
            return database.hard_delete_record(table_name, record_id)
        except Exception as e:
            logging.error(f"Errore hard delete locale {table_name}/{record_id}: {e}")
            return False

    def _hard_delete_record_online(self, table_name: str, record_id: int) -> bool:
        """Elimina un record dal database online via API."""
        try:
            headers = auth_manager.get_auth_headers()
            if not headers:
                return False
            url = f"{config.SERVER_URL}/admin/deleted-data/{table_name}/{record_id}"
            response = requests.delete(url, headers=headers, timeout=15)
            return response.status_code == 200
        except Exception as e:
            logging.error(f"Errore hard delete online {table_name}/{record_id}: {e}")
            return False

    def _hard_delete_all_online(self, table_name: str) -> int:
        """Elimina tutti i record soft-deleted dal database online per una tabella."""
        try:
            headers = auth_manager.get_auth_headers()
            if not headers:
                return 0
            url = f"{config.SERVER_URL}/admin/deleted-data/{table_name}"
            response = requests.delete(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get('deleted_count', 0)
            return 0
        except Exception as e:
            logging.error(f"Errore hard delete massivo online {table_name}: {e}")
            return 0

    def _delete_selected(self):
        """Elimina definitivamente i record selezionati da locale e/o online."""
        entity = self._get_current_entity()
        if not entity:
            return
        
        records = self._get_selected_records()
        if not records:
            QMessageBox.information(
                self, "Nessuna Selezione",
                "Seleziona almeno un record da eliminare definitivamente."
            )
            return
        
        # Analisi sorgenti
        local_count = sum(1 for r in records if r.get('_source') in (SOURCE_LOCAL, SOURCE_BOTH))
        online_count = sum(1 for r in records if r.get('_source') in (SOURCE_ONLINE, SOURCE_BOTH))
        
        source_detail = []
        if local_count > 0:
            source_detail.append(f"📱 {local_count} dal database locale")
        if online_count > 0:
            source_detail.append(f"☁️ {online_count} dal database online")
        source_str = "\n".join(source_detail)
        
        # Conferma
        reply = QMessageBox.warning(
            self,
            "⚠️ Conferma Eliminazione Definitiva",
            f"Stai per eliminare <b>definitivamente</b> {len(records)} record dalla tabella "
            f"<b>{entity['label']}</b>:\n\n{source_str}\n\n"
            f"<b style='color: red;'>Questa operazione è IRREVERSIBILE!</b>\n\n"
            f"Vuoi procedere?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Seconda conferma per sicurezza
        reply2 = QMessageBox.critical(
            self,
            "🛑 ULTIMA CONFERMA",
            f"Sei ASSOLUTAMENTE sicuro di voler eliminare definitivamente "
            f"{len(records)} record?\n\n"
            f"I dati andranno persi per sempre.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply2 != QMessageBox.Yes:
            return
        
        # Esegui eliminazione
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            deleted_local = 0
            deleted_online = 0
            errors_list = []
            table_name = entity['key']
            
            for record in records:
                source = record.get('_source', SOURCE_LOCAL)
                local_id = record.get('_local_id')
                online_id = record.get('_online_id')
                
                # Elimina dal locale se presente
                if source in (SOURCE_LOCAL, SOURCE_BOTH) and local_id:
                    if self._hard_delete_record_local(table_name, local_id):
                        deleted_local += 1
                    else:
                        errors_list.append(f"Locale ID {local_id}")
                
                # Elimina dall'online se presente
                if source in (SOURCE_ONLINE, SOURCE_BOTH) and online_id:
                    if self._hard_delete_record_online(table_name, online_id):
                        deleted_online += 1
                    else:
                        errors_list.append(f"Online ID {online_id}")
        finally:
            QApplication.restoreOverrideCursor()
        
        # Messaggio risultato
        result_parts = []
        if deleted_local > 0:
            result_parts.append(f"📱 {deleted_local} eliminati dal database locale")
        if deleted_online > 0:
            result_parts.append(f"☁️ {deleted_online} eliminati dal database online")
        result_str = "\n".join(result_parts) if result_parts else "Nessun record eliminato."
        
        if not errors_list:
            QMessageBox.information(
                self, "Eliminazione Completata",
                f"✅ Eliminazione completata:\n\n{result_str}"
            )
        else:
            QMessageBox.warning(
                self, "Eliminazione Parziale",
                f"⚠️ Eliminazione parziale:\n\n{result_str}\n\n"
                f"Errori su: {', '.join(errors_list)}"
            )
        
        # Ricarica dati
        self._load_all_data()

    def _delete_all_in_current_tab(self):
        """Elimina definitivamente tutti i record nella tab corrente da locale e online."""
        entity = self._get_current_entity()
        if not entity:
            return
        
        key = entity['key']
        rows = self.tab_data.get(key, [])
        if not rows:
            QMessageBox.information(
                self, "Nessun Dato",
                f"Non ci sono record eliminati nella categoria {entity['label']}."
            )
            return
        
        count = len(rows)
        has_local = any(r.get('_source') in (SOURCE_LOCAL, SOURCE_BOTH) for r in rows)
        has_online = any(r.get('_source') in (SOURCE_ONLINE, SOURCE_BOTH) for r in rows)
        
        source_detail = []
        if has_local:
            source_detail.append("📱 Database locale")
        if has_online:
            source_detail.append("☁️ Database online")
        source_str = " e ".join(source_detail)
        
        # Conferma
        reply = QMessageBox.warning(
            self,
            "⚠️ Conferma Eliminazione Massiva",
            f"Stai per eliminare <b>definitivamente</b> TUTTI i <b>{count}</b> record "
            f"eliminati dalla tabella <b>{entity['label']}</b> ({source_str}).\n\n"
            f"<b style='color: red;'>Questa operazione è IRREVERSIBILE!</b>\n\n"
            f"Vuoi procedere?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Seconda conferma
        reply2 = QMessageBox.critical(
            self,
            "🛑 ULTIMA CONFERMA",
            f"Sei ASSOLUTAMENTE sicuro di voler eliminare definitivamente "
            f"TUTTI i {count} record della categoria {entity['label']}?\n\n"
            f"I dati andranno persi per sempre.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply2 != QMessageBox.Yes:
            return
        
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result_parts = []
            
            # Elimina tutti dal locale
            if has_local:
                try:
                    deleted_local = database.hard_delete_all_for_entity(key)
                    result_parts.append(f"📱 {deleted_local} eliminati dal database locale")
                except Exception as e:
                    logging.error(f"Errore eliminazione massiva locale per {key}: {e}", exc_info=True)
                    result_parts.append(f"📱 Errore locale: {str(e)}")
            
            # Elimina tutti dall'online
            if has_online:
                try:
                    deleted_online = self._hard_delete_all_online(key)
                    result_parts.append(f"☁️ {deleted_online} eliminati dal database online")
                except Exception as e:
                    logging.error(f"Errore eliminazione massiva online per {key}: {e}", exc_info=True)
                    result_parts.append(f"☁️ Errore online: {str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
        
        result_str = "\n".join(result_parts)
        QMessageBox.information(
            self, "Eliminazione Completata",
            f"✅ Risultato eliminazione:\n\n{result_str}"
        )
        
        # Ricarica dati
        self._load_all_data()
