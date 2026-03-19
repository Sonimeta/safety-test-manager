# app/ui/dialogs/audit_log_dialog.py

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                               QPushButton, QLabel, QComboBox, QLineEdit, QHeaderView, QAbstractItemView,
                               QGroupBox, QMessageBox, QApplication, QFileDialog, QDateEdit)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor, QFont
from app import services, config
import qtawesome as qta
import logging
import pandas as pd
import os
import json

# ============================================================================
# DIZIONARI DI TRADUZIONE PER IL LOG ATTIVITÀ
# ============================================================================

# Traduzione tipi di azione (inglese -> italiano)
ACTION_TRANSLATIONS = {
    'CREATE': 'Creazione',
    'UPDATE': 'Modifica',
    'DELETE': 'Eliminazione',
    'VERIFY': 'Verifica',
    'LOGIN': 'Accesso',
    'LOGOUT': 'Disconnessione',
    'SYNC': 'Sincronizzazione',
    'EXPORT': 'Esportazione',
    'DECOMMISSION': 'Dismissione',
    'REACTIVATE': 'Riattivazione',
    'IMPORT': 'Importazione',
}

# Icone per tipo di azione
ACTION_ICONS = {
    'CREATE': '➕',
    'UPDATE': '✏️',
    'DELETE': '🗑️',
    'VERIFY': '✅',
    'LOGIN': '🔐',
    'LOGOUT': '🚪',
    'SYNC': '🔄',
    'EXPORT': '📤',
    'DECOMMISSION': '⛔',
    'REACTIVATE': '♻️',
    'IMPORT': '📥',
}

# Colori per tipo di azione (sfondo, testo)
ACTION_COLORS = {
    'CREATE': ('#dcfce7', '#16a34a'),      # Verde chiaro
    'UPDATE': ('#dbeafe', '#2563eb'),      # Blu chiaro
    'DELETE': ('#fee2e2', '#dc2626'),      # Rosso chiaro
    'VERIFY': ('#fef3c7', '#d97706'),      # Arancione chiaro
    'LOGIN': ('#e0e7ff', '#4338ca'),       # Indigo chiaro
    'LOGOUT': ('#f3e8ff', '#7c3aed'),      # Viola chiaro
    'SYNC': ('#cffafe', '#0891b2'),        # Ciano chiaro
    'EXPORT': ('#fce7f3', '#db2777'),      # Rosa chiaro
    'DECOMMISSION': ('#fef2f2', '#991b1b'), # Rosso scuro
    'REACTIVATE': ('#ecfdf5', '#059669'),  # Verde smeraldo
    'IMPORT': ('#fff7ed', '#ea580c'),      # Arancione
}

# Traduzione tipi di entità (inglese -> italiano) 
ENTITY_TRANSLATIONS = {
    'customer': 'Cliente',
    'device': 'Dispositivo',
    'verification': 'Verifica Elettrica',
    'functional_verification': 'Verifica Funzionale',
    'destination': 'Destinazione',
    'user': 'Utente',
    'instrument': 'Strumento',
    'profile': 'Profilo',
    'functional_profile': 'Profilo Funzionale',
    'settings': 'Impostazioni',
    'report': 'Report',
    'backup': 'Backup',
}

# Icone per tipo di entità
ENTITY_ICONS = {
    'customer': '🏢',
    'device': '🔌',
    'verification': '⚡',
    'functional_verification': '🔧',
    'destination': '📍',
    'user': '👤',
    'instrument': '📏',
    'profile': '📋',
    'functional_profile': '📝',
    'settings': '⚙️',
    'report': '📄',
    'backup': '💾',
}


def translate_action(action_code: str) -> str:
    """Traduce il codice azione in italiano."""
    return ACTION_TRANSLATIONS.get(action_code, action_code)


def translate_entity(entity_code: str) -> str:
    """Traduce il codice entità in italiano."""
    return ENTITY_TRANSLATIONS.get(entity_code, entity_code)


def get_action_display(action_code: str) -> str:
    """Restituisce la stringa di visualizzazione per un'azione (con icona)."""
    icon = ACTION_ICONS.get(action_code, '•')
    name = translate_action(action_code)
    return f"{icon} {name}"


def get_entity_display(entity_code: str) -> str:
    """Restituisce la stringa di visualizzazione per un'entità (con icona)."""
    icon = ENTITY_ICONS.get(entity_code, '📦')
    name = translate_entity(entity_code)
    return f"{icon} {name}"


class AuditLogDialog(QDialog):
    """
    Finestra di dialogo per visualizzare il log delle attività (Chi ha fatto cosa).
    Mostra tutte le azioni eseguite dagli utenti nel sistema.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log Attività - Registro delle Operazioni")
        self.setWindowState(Qt.WindowMaximized)
        # Applica il tema corrente
        self.setStyleSheet(config.get_current_stylesheet())
        
        self.current_results = []
        
        # Layout principale
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = self._create_header()
        main_layout.addLayout(header)
        
        # Filtri
        filters_group = self._create_filters_group()
        main_layout.addWidget(filters_group)
        
        # Risultati
        results_group = self._create_results_group()
        main_layout.addWidget(results_group)
        
        # Pulsanti
        button_layout = self._create_buttons()
        main_layout.addLayout(button_layout)
        
        # Carica dati iniziali
        self._load_data()
    
    def _create_header(self):
        """Crea l'header con titolo e statistiche."""
        layout = QHBoxLayout()
        
        title = QLabel("<h1>📋 Registro Attività</h1>")
        title.setStyleSheet("font-size: 18px;")
        layout.addWidget(title)
        
        subtitle = QLabel("<i style='color: #666;'>Traccia tutte le operazioni eseguite nel sistema</i>")
        layout.addWidget(subtitle)
        
        layout.addStretch()
        
        # Statistiche rapide
        self.stats_label = QLabel("<i>Caricamento statistiche...</i>")
        self.stats_label.setStyleSheet("font-size: 13px; padding: 5px 10px; background: #f0f0f0; border-radius: 5px;")
        layout.addWidget(self.stats_label)
        
        # Pulsante esporta
        export_btn = QPushButton(qta.icon('fa5s.file-excel'), " Esporta Excel")
        export_btn.setObjectName("editButton")
        export_btn.setMinimumWidth(130)
        export_btn.clicked.connect(self._export_log)
        layout.addWidget(export_btn)
        
        # Pulsante refresh
        refresh_btn = QPushButton(qta.icon('fa5s.sync'), " Aggiorna")
        refresh_btn.setObjectName("autoButton")
        refresh_btn.setMinimumWidth(100)
        refresh_btn.clicked.connect(self._load_data)
        layout.addWidget(refresh_btn)
        
        return layout
    
    def _create_filters_group(self):
        """Crea il gruppo con i filtri."""
        group = QGroupBox("🔍 Filtri di Ricerca")
        layout = QHBoxLayout()
        layout.setSpacing(15)
        
        # Filtro utente
        layout.addWidget(QLabel("<b>Utente:</b>"))
        self.user_filter = QComboBox()
        self.user_filter.addItem("👥 Tutti gli utenti", None)
        self.user_filter.setMinimumWidth(180)
        layout.addWidget(self.user_filter)
        
        # Filtro azione - in italiano
        layout.addWidget(QLabel("<b>Tipo Azione:</b>"))
        self.action_filter = QComboBox()
        self.action_filter.addItem("📋 Tutte le azioni", "")
        # Aggiungi le azioni tradotte
        for code, name in ACTION_TRANSLATIONS.items():
            icon = ACTION_ICONS.get(code, '•')
            self.action_filter.addItem(f"{icon} {name}", code)
        self.action_filter.setMinimumWidth(180)
        layout.addWidget(self.action_filter)
        
        # Filtro entità - in italiano
        layout.addWidget(QLabel("<b>Tipo Entità:</b>"))
        self.entity_filter = QComboBox()
        self.entity_filter.addItem("📦 Tutte le entità", "")
        # Aggiungi le entità tradotte
        for code, name in ENTITY_TRANSLATIONS.items():
            icon = ENTITY_ICONS.get(code, '📦')
            self.entity_filter.addItem(f"{icon} {name}", code)
        self.entity_filter.setMinimumWidth(180)
        layout.addWidget(self.entity_filter)
        
        # Ricerca testo
        layout.addWidget(QLabel("<b>Cerca:</b>"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔎 Cerca nella descrizione o nei dettagli...")
        self.search_input.setMinimumWidth(250)
        self.search_input.returnPressed.connect(self._load_data)
        layout.addWidget(self.search_input)
        
        # Pulsante cerca
        search_btn = QPushButton(qta.icon('fa5s.search'), " Cerca")
        search_btn.clicked.connect(self._load_data)
        layout.addWidget(search_btn)
        
        # Pulsante reset
        reset_btn = QPushButton(qta.icon('fa5s.eraser'), " Pulisci Filtri")
        reset_btn.setObjectName("warningButton")
        reset_btn.clicked.connect(self._reset_filters)
        layout.addWidget(reset_btn)
        
        layout.addStretch()
        
        group.setLayout(layout)
        return group
    
    def _create_results_group(self):
        """Crea il gruppo con i risultati."""
        group = QGroupBox("📜 Cronologia Operazioni")
        layout = QVBoxLayout()
        
        self.results_count_label = QLabel("<i>Caricamento in corso...</i>")
        self.results_count_label.setStyleSheet("font-size: 13px; padding: 5px;")
        layout.addWidget(self.results_count_label)
        
        # Configura tabella
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "📅 Data e Ora", "👤 Utente", "🎯 Azione", "📦 Entità", "📝 Descrizione", "ℹ️ Dettagli", "ID"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        
        # Stile tabella
        self.table.setStyleSheet("""
            QTableWidget {
                font-size: 12px;
                gridline-color: #e0e0e0;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                padding: 10px;
                font-weight: bold;
                border: 1px solid #ddd;
            }
        """)
        
        # Nascondi colonna ID
        self.table.hideColumn(6)
        
        # Ridimensiona colonne
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        
        # Altezza righe
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.verticalHeader().setVisible(False)
        
        layout.addWidget(self.table)
        
        group.setLayout(layout)
        return group
    
    def _create_buttons(self):
        """Crea i pulsanti."""
        layout = QHBoxLayout()
        
        # Legenda
        legend_label = QLabel(
            "<span style='color: #666;'>"
            "<b>Legenda:</b> "
            "➕ Creazione | ✏️ Modifica | 🗑️ Eliminazione | ✅ Verifica | 🔐 Accesso | 🔄 Sincronizzazione"
            "</span>"
        )
        layout.addWidget(legend_label)
        
        layout.addStretch()
        
        close_btn = QPushButton("Chiudi")
        close_btn.setMinimumWidth(120)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        return layout
    
    def _reset_filters(self):
        """Reset tutti i filtri."""
        self.user_filter.setCurrentIndex(0)
        self.action_filter.setCurrentIndex(0)
        self.entity_filter.setCurrentIndex(0)
        self.search_input.clear()
        self._load_data()
    
    def _load_data(self):
        """Carica i dati del log con i filtri applicati."""
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Prepara filtri
            filters = {}
            
            if self.user_filter.currentIndex() > 0:
                filters['username'] = self.user_filter.currentData()
            
            # Usa il codice originale per il filtro (non la traduzione)
            action_code = self.action_filter.currentData()
            if action_code:
                filters['action_type'] = action_code
            
            entity_code = self.entity_filter.currentData()
            if entity_code:
                filters['entity_type'] = entity_code
            
            search_text = self.search_input.text().strip()
            if search_text:
                filters['search_text'] = search_text
            
            # Carica dati
            records = services.get_audit_log(filters, limit=500)
            self.current_results = records
            
            # Popola tabella
            self._populate_table(records)
            
            # Aggiorna statistiche
            self._update_stats()
            
        except Exception as e:
            logging.error(f"Errore caricamento audit log: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile caricare il registro attività:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def _populate_table(self, records):
        """Popola la tabella con i record."""
        self.table.setRowCount(0)
        
        if not records:
            self.results_count_label.setText("<b>📭 Nessuna attività registrata con i filtri selezionati</b>")
            return
        
        self.table.setRowCount(len(records))
        
        for row_idx, record in enumerate(records):
            # Data/Ora - formattata in italiano
            timestamp_str = record['timestamp']
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                formatted_time = dt.strftime("%d/%m/%Y alle %H:%M:%S")
            except:
                formatted_time = timestamp_str
            
            time_item = QTableWidgetItem(formatted_time)
            time_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 0, time_item)
            
            # Utente - nome completo se disponibile
            user_display = record['user_full_name'] or record['username']
            user_item = QTableWidgetItem(f"👤 {user_display}")
            self.table.setItem(row_idx, 1, user_item)
            
            # Azione (tradotta e colorata)
            action_code = record['action_type']
            action_display = get_action_display(action_code)
            action_item = QTableWidgetItem(action_display)
            action_item.setTextAlignment(Qt.AlignCenter)
            
            # Applica colori
            if action_code in ACTION_COLORS:
                bg_color, fg_color = ACTION_COLORS[action_code]
                action_item.setBackground(QColor(bg_color))
                action_item.setForeground(QColor(fg_color))
            
            # Font bold per l'azione
            font = action_item.font()
            font.setBold(True)
            action_item.setFont(font)
            
            self.table.setItem(row_idx, 2, action_item)
            
            # Entità (tradotta)
            entity_code = record['entity_type']
            entity_display = get_entity_display(entity_code)
            entity_item = QTableWidgetItem(entity_display)
            self.table.setItem(row_idx, 3, entity_item)
            
            # Descrizione
            description = record['entity_description'] or "—"
            desc_item = QTableWidgetItem(description)
            self.table.setItem(row_idx, 4, desc_item)
            
            # Dettagli (formatta JSON se presente)
            details_text = self._format_details(record['details'])
            details_item = QTableWidgetItem(details_text)
            details_item.setToolTip(record['details'] if record['details'] else "")
            self.table.setItem(row_idx, 5, details_item)
            
            # ID (nascosto)
            id_item = QTableWidgetItem(str(record['id']))
            self.table.setItem(row_idx, 6, id_item)
        
        self.results_count_label.setText(
            f"<b>📊 Visualizzate {len(records)} operazioni</b> "
            f"<span style='color: #666;'>(massimo 500 più recenti)</span>"
        )
    
    def _format_details(self, details_json: str) -> str:
        """Formatta i dettagli JSON in modo leggibile."""
        if not details_json or details_json == "—":
            return "—"
        
        try:
            details_obj = json.loads(details_json)
            
            # Traduci le chiavi comuni
            key_translations = {
                'old_value': 'Valore precedente',
                'new_value': 'Nuovo valore',
                'field': 'Campo',
                'label': 'Campo',
                'reason': 'Motivo',
                'ip': 'Indirizzo IP',
                'changes': 'Modifiche',
                'count': 'Quantità',
                'status': 'Stato',
                'result': 'Risultato',
                'file': 'File',
                'path': 'Percorso',
                'code': 'Codice verifica',
                'verification_code': 'Codice verifica',
                'verification_date': 'Data verifica',
                'profile': 'Profilo',
                'profile_name': 'Profilo',
                'profile_key': 'Profilo',
                'serial': 'Seriale',
                'serial_number': 'Seriale',
                'device_label': 'Dispositivo',
                'device_id': 'ID dispositivo',
                'manufacturer': 'Costruttore',
                'model': 'Modello',
                'destination_name': 'Destinazione',
                'destination_id': 'ID destinazione',
                'technician_name': 'Tecnico',
                'technician_username': 'Username tecnico',
                'changed_fields_count': 'Campi modificati',
                'reactivated': 'Riattivato',
            }

            # 1) Se presenti modifiche campo-per-campo, mostra prima quelle
            changes = details_obj.get('changes') if isinstance(details_obj, dict) else None
            if isinstance(changes, list) and changes:
                change_parts = []
                for change in changes[:3]:
                    if not isinstance(change, dict):
                        continue
                    label = change.get('label') or change.get('field') or 'Campo'
                    old_value = change.get('old') if change.get('old') not in [None, ""] else '—'
                    new_value = change.get('new') if change.get('new') not in [None, ""] else '—'
                    change_parts.append(f"{label}: {old_value} → {new_value}")

                if change_parts:
                    prefix = " | ".join(change_parts)
                    if len(changes) > 3:
                        prefix += f" | ... (+{len(changes) - 3} modifiche)"

                    device_label = details_obj.get('device_label')
                    if device_label:
                        return f"Dispositivo: {device_label} | {prefix}"
                    return prefix

            # 2) Se presente una label dispositivo, mettila in evidenza
            prioritized_parts = []
            device_label = details_obj.get('device_label') if isinstance(details_obj, dict) else None
            if device_label:
                prioritized_parts.append(f"Dispositivo: {device_label}")

            verification_code = details_obj.get('verification_code') or details_obj.get('code') if isinstance(details_obj, dict) else None
            if verification_code:
                prioritized_parts.append(f"Codice verifica: {verification_code}")

            if prioritized_parts:
                # Aggiungi poi qualche campo riassuntivo standard
                summary_parts = []
                for key in ['status', 'profile', 'verification_date', 'destination_name', 'technician_name', 'serial']:
                    value = details_obj.get(key) if isinstance(details_obj, dict) else None
                    if value not in [None, "", []]:
                        translated_key = key_translations.get(key, key.replace('_', ' ').title())
                        summary_parts.append(f"{translated_key}: {value}")
                return " | ".join(prioritized_parts + summary_parts[:3])
            
            # Crea un riassunto leggibile
            parts = []
            for key, value in list(details_obj.items())[:4]:
                translated_key = key_translations.get(key, key.replace('_', ' ').title())
                if isinstance(value, dict):
                    value = "..."
                elif isinstance(value, list):
                    value = f"[{len(value)} elementi]"
                parts.append(f"{translated_key}: {value}")
            
            summary = " | ".join(parts)
            if len(details_obj) > 4:
                summary += " | ..."
            
            return summary
            
        except:
            return details_json[:100] + "..." if len(details_json) > 100 else details_json
    
    def _update_stats(self):
        """Aggiorna le statistiche nel header."""
        try:
            stats = services.get_audit_log_stats()
            total = stats.get('total', 0)
            self.stats_label.setText(f"<b>📈 Totale operazioni registrate: {total:,}</b>")
            
            # Popola filtro utenti - blocca segnali per evitare loop
            current_user = self.user_filter.currentData()
            self.user_filter.blockSignals(True)
            self.user_filter.clear()
            self.user_filter.addItem("👥 Tutti gli utenti", None)
            
            for user in stats.get('by_user', []):
                display_name = user['user_full_name'] or user['username']
                self.user_filter.addItem(
                    f"👤 {display_name} ({user['count']} azioni)",
                    user['username']
                )
            
            # Ripristina selezione
            if current_user:
                idx = self.user_filter.findData(current_user)
                if idx >= 0:
                    self.user_filter.setCurrentIndex(idx)
            
            self.user_filter.blockSignals(False)
                    
        except Exception as e:
            logging.error(f"Errore aggiornamento statistiche audit: {e}", exc_info=True)
            self.user_filter.blockSignals(False)
    
    def _export_log(self):
        """Esporta il log in Excel."""
        if not self.current_results:
            QMessageBox.warning(self, "Nessun Dato", "Non ci sono dati da esportare.\nProva a modificare i filtri.")
            return
        
        default_filename = f"Registro_Attivita_{QDate.currentDate().toString('yyyy-MM-dd')}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Esporta Registro Attività",
            os.path.join(os.path.expanduser("~"), "Desktop", default_filename),
            "File Excel (*.xlsx)"
        )
        
        if not file_path:
            return
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Prepara dati per export
            export_data = []
            for record in self.current_results:
                # Formatta timestamp
                timestamp_str = record['timestamp']
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    formatted_time = dt.strftime("%d/%m/%Y %H:%M:%S")
                except:
                    formatted_time = timestamp_str
                
                # Formatta dettagli
                details_text = record['details'] or ""
                if details_text:
                    try:
                        details_obj = json.loads(details_text)
                        details_text = json.dumps(details_obj, indent=2, ensure_ascii=False)
                    except:
                        pass
                
                export_data.append({
                    'Data e Ora': formatted_time,
                    'Utente': record['user_full_name'] or record['username'],
                    'Nome Utente': record['username'],
                    'Azione': translate_action(record['action_type']),
                    'Codice Azione': record['action_type'],
                    'Entità': translate_entity(record['entity_type']),
                    'Codice Entità': record['entity_type'],
                    'ID Entità': record['entity_id'] or "",
                    'Descrizione': record['entity_description'] or "",
                    'Dettagli': details_text,
                    'Indirizzo IP': record['ip_address'] or ""
                })
            
            # Crea DataFrame ed esporta
            df = pd.DataFrame(export_data)
            
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Registro Attività')
                
                # Auto-ridimensiona colonne
                worksheet = writer.sheets['Registro Attività']
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 60)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
            
            QApplication.restoreOverrideCursor()
            QMessageBox.information(
                self,
                "Esportazione Completata",
                f"✅ Registro attività esportato con successo!\n\n"
                f"📁 File: {file_path}\n"
                f"📊 Record esportati: {len(export_data)}"
            )
            
        except Exception as e:
            QApplication.restoreOverrideCursor()
            logging.error(f"Errore esportazione registro attività: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile esportare il registro:\n{str(e)}")
