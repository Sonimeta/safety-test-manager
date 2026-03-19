# app/ui/dialogs/changelog_dialog.py
import json
import os
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QScrollArea, QWidget, QFrame
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QFont
import qtawesome as qta
from app import config


class ChangelogDialog(QDialog):
    """Dialog per mostrare il changelog delle versioni."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📋 Novità dell'Applicazione")
        self.setMinimumSize(700, 500)
        self.setModal(True)
        
        # Applica il tema corrente
        self.settings = QSettings("ELSON META", "SafetyTester")
        current_theme = self.settings.value("theme", "light")
        self._apply_theme(current_theme)
        
        # Carica il changelog
        self.changelog_data = self._load_changelog()
        
        self._build_ui()
    
    def _apply_theme(self, theme: str):
        """Applica il tema al dialog."""
        from app.config import get_theme_stylesheet
        stylesheet = get_theme_stylesheet(theme)
        self.setStyleSheet(stylesheet)
        
    def _load_changelog(self):
        """Carica il file CHANGELOG.json."""
        changelog_path = os.path.join(config.BASE_DIR, "CHANGELOG.json")
        
        try:
            if os.path.exists(changelog_path):
                with open(changelog_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('changelog', [])
            else:
                logging.warning(f"File CHANGELOG.json non trovato: {changelog_path}")
                return []
        except Exception as e:
            logging.error(f"Errore nel caricamento del changelog: {e}")
            return []
    
    def _build_ui(self):
        """Costruisce l'interfaccia del dialog."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header_label = QLabel("🎉 Novità dell'Applicazione")
        header_font = QFont()
        header_font.setPointSize(18)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        # Versione corrente
        version_label = QLabel(f"Versione attuale: <b>{config.VERSIONE}</b>")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(version_label)
        
        # Area scrollabile per il contenuto
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                background-color: transparent;
            }
        """)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(20)
        scroll_layout.setContentsMargins(15, 15, 15, 15)
        
        # Mostra solo le versioni fino alla versione corrente
        current_version = config.VERSIONE
        versions_to_show = []
        
        for entry in self.changelog_data:
            if self._version_compare(entry['version'], current_version) <= 0:
                versions_to_show.append(entry)
        
        if not versions_to_show:
            # Se non ci sono voci nel changelog, mostra un messaggio
            no_changelog_label = QLabel("Nessuna informazione disponibile sul changelog.")
            no_changelog_label.setAlignment(Qt.AlignCenter)
            no_changelog_label.setStyleSheet("color: #94a3b8; padding: 20px;")
            scroll_layout.addWidget(no_changelog_label)
        else:
            # Mostra le versioni (dalla più recente alla più vecchia)
            for entry in versions_to_show:
                version_widget = self._create_version_widget(entry)
                scroll_layout.addWidget(version_widget)
        
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)
        
        # Pulsanti
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        ok_button = QPushButton(qta.icon('fa5s.check'), " Ho capito")
        ok_button.setObjectName("editButton")
        ok_button.clicked.connect(self.accept)
        button_layout.addWidget(ok_button)
        
        layout.addLayout(button_layout)
    
    def _create_version_widget(self, entry):
        """Crea un widget per una singola versione."""
        frame = QFrame()
        frame.setFrameShape(QFrame.Box)
        frame.setObjectName("changelogVersionFrame")
        # Lo stile viene applicato dal tema globale
        
        layout = QVBoxLayout(frame)
        layout.setSpacing(10)
        
        # Header versione
        version_header = QHBoxLayout()
        
        version_title = QLabel(f"<b>{entry.get('title', entry['version'])}</b>")
        version_font = QFont()
        version_font.setPointSize(14)
        version_font.setBold(True)
        version_title.setFont(version_font)
        version_title.setObjectName("changelogVersionTitle")
        # Il colore viene applicato dal tema globale
        version_header.addWidget(version_title)
        
        version_header.addStretch()
        
        # Data
        if 'date' in entry:
            date_label = QLabel(entry['date'])
            date_label.setStyleSheet("color: #64748b; font-size: 11px;")
            version_header.addWidget(date_label)
        
        layout.addLayout(version_header)
        
        # Lista modifiche
        if 'changes' in entry and entry['changes']:
            changes_text = QTextEdit()
            changes_text.setReadOnly(True)
            changes_text.setMaximumHeight(150)
            changes_text.setObjectName("changelogChangesText")
            # Lo stile viene applicato dal tema globale
            
            # Formatta le modifiche come lista HTML
            changes_html = "<ul style='margin: 0; padding-left: 20px;'>"
            for change in entry['changes']:
                changes_html += f"<li style='margin-bottom: 5px;'>{change}</li>"
            changes_html += "</ul>"
            
            changes_text.setHtml(changes_html)
            layout.addWidget(changes_text)
        
        return frame
    
    def _version_compare(self, v1, v2):
        """
        Confronta due versioni nel formato X.Y.Z
        Ritorna: -1 se v1 < v2, 0 se v1 == v2, 1 se v1 > v2
        """
        try:
            from packaging import version
            v1_parsed = version.parse(v1)
            v2_parsed = version.parse(v2)
            
            if v1_parsed < v2_parsed:
                return -1
            elif v1_parsed > v2_parsed:
                return 1
            else:
                return 0
        except Exception as e:
            logging.error(f"Errore nel confronto versioni: {e}")
            # Fallback: confronto stringa semplice
            if v1 < v2:
                return -1
            elif v1 > v2:
                return 1
            else:
                return 0

