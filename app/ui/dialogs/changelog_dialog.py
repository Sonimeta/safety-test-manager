# app/ui/dialogs/changelog_dialog.py
import json
import os
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QFont, QColor
import qtawesome as qta
from app import config


# ── Categorie di modifiche con colori e icone ──────────────────────
CHANGE_CATEGORIES = {
    "✨": {"label": "Novità",       "color": "#10b981", "dark_color": "#34d399", "icon": "fa5s.star"},
    "🐛": {"label": "Correzioni",   "color": "#f59e0b", "dark_color": "#fbbf24", "icon": "fa5s.bug"},
    "🔧": {"label": "Miglioramenti","color": "#6366f1", "dark_color": "#818cf8", "icon": "fa5s.wrench"},
    "🗑️": {"label": "Rimossi",      "color": "#ef4444", "dark_color": "#f87171", "icon": "fa5s.trash"},
    "📌": {"label": "Altro",        "color": "#64748b", "dark_color": "#94a3b8", "icon": "fa5s.info-circle"},
}

DEFAULT_CATEGORY_KEY = "📌"


class ChangelogDialog(QDialog):
    """Dialog per mostrare il changelog delle versioni con design migliorato."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📋 Novità dell'Applicazione")
        self.setMinimumSize(750, 560)
        self.resize(800, 650)
        self.setModal(True)

        # Tema
        self.settings = QSettings("ELSON META", "SafetyTester")
        self.current_theme = self.settings.value("theme", "light")
        self._apply_theme(self.current_theme)
        self._is_dark = self.current_theme == "dark"

        # Dati
        self.changelog_data = self._load_changelog()
        self._build_ui()

    # ── Tema ────────────────────────────────────────────────────────
    def _apply_theme(self, theme: str):
        from app.config import get_theme_stylesheet
        self.setStyleSheet(get_theme_stylesheet(theme))

    # ── Caricamento dati ────────────────────────────────────────────
    def _load_changelog(self):
        changelog_path = os.path.join(config.BASE_DIR, "CHANGELOG.json")
        try:
            if os.path.exists(changelog_path):
                with open(changelog_path, "r", encoding="utf-8") as f:
                    return json.load(f).get("changelog", [])
            else:
                logging.warning("File CHANGELOG.json non trovato: %s", changelog_path)
                return []
        except Exception as e:
            logging.error("Errore nel caricamento del changelog: %s", e)
            return []

    # ── Classificazione modifiche ───────────────────────────────────
    @staticmethod
    def _categorize_changes(changes: list[str]) -> dict[str, list[str]]:
        """Raggruppa le modifiche per emoji/categoria."""
        groups: dict[str, list[str]] = {}
        for raw in changes:
            text = raw.strip()
            key = DEFAULT_CATEGORY_KEY
            for emoji in CHANGE_CATEGORIES:
                if text.startswith(emoji):
                    key = emoji
                    text = text[len(emoji):].strip()
                    break
            groups.setdefault(key, []).append(text)
        return groups

    # ── Colori utili ────────────────────────────────────────────────
    def _cat_color(self, key: str) -> str:
        cat = CHANGE_CATEGORIES.get(key, CHANGE_CATEGORIES[DEFAULT_CATEGORY_KEY])
        return cat["dark_color"] if self._is_dark else cat["color"]

    def _text_color(self) -> str:
        return "#e2e8f0" if self._is_dark else "#334155"

    def _sub_text_color(self) -> str:
        return "#94a3b8" if self._is_dark else "#64748b"

    def _badge_bg(self) -> str:
        return "#312e81" if self._is_dark else "#eef2ff"

    def _badge_fg(self) -> str:
        return "#c7d2fe" if self._is_dark else "#4338ca"

    def _separator_color(self) -> str:
        return "#253352" if self._is_dark else "#e2e8f0"

    # ── UI principale ───────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(24, 24, 24, 20)

        # ── Header ──
        header = QLabel("🎉 Novità dell'Applicazione")
        hf = QFont(); hf.setPointSize(18); hf.setBold(True)
        header.setFont(hf)
        header.setAlignment(Qt.AlignCenter)
        root.addWidget(header)

        # Badge versione corrente
        badge_html = (
            f'<div style="text-align:center;">'
            f'<span style="background:{self._badge_bg()};color:{self._badge_fg()};'
            f'padding:4px 14px;border-radius:12px;font-size:12px;font-weight:600;">'
            f'v{config.VERSIONE}</span></div>'
        )
        badge = QLabel(badge_html)
        badge.setAlignment(Qt.AlignCenter)
        root.addWidget(badge)

        # ── Scroll area ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{border:1px solid " + self._separator_color() + ";"
            "border-radius:10px;background:transparent;}"
        )

        container = QWidget()
        clayout = QVBoxLayout(container)
        clayout.setSpacing(24)
        clayout.setContentsMargins(16, 16, 16, 16)

        # Filtra versioni valide
        versions_to_show = [
            e for e in self.changelog_data
            if self._version_compare(e["version"], config.VERSIONE) <= 0
        ]

        if not versions_to_show:
            empty = QLabel("Nessuna informazione disponibile.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color:{self._sub_text_color()};padding:30px;")
            clayout.addWidget(empty)
        else:
            for idx, entry in enumerate(versions_to_show):
                clayout.addWidget(self._create_version_card(entry, is_latest=(idx == 0)))

        clayout.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # ── Pulsante OK ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok = QPushButton(qta.icon("fa5s.check"), "  Ho capito")
        ok.setObjectName("editButton")
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        root.addLayout(btn_row)

    # ── Card per singola versione ───────────────────────────────────
    def _create_version_card(self, entry: dict, *, is_latest: bool = False) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.NoFrame)
        frame.setObjectName("changelogVersionFrame")

        lay = QVBoxLayout(frame)
        lay.setSpacing(14)
        lay.setContentsMargins(18, 18, 18, 18)

        # ── Riga titolo ──
        top = QHBoxLayout()
        top.setSpacing(10)

        # Icona versione
        if is_latest:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(
                qta.icon("fa5s.gift", color=self._cat_color("✨")).pixmap(22, 22)
            )
            top.addWidget(icon_lbl)

        title_text = entry.get("title", f"Versione {entry['version']}")
        title = QLabel(title_text)
        tf = QFont(); tf.setPointSize(14); tf.setBold(True)
        title.setFont(tf)
        title.setObjectName("changelogVersionTitle")
        top.addWidget(title)

        if is_latest:
            new_badge = QLabel(
                f'<span style="background:#10b981;color:#fff;padding:2px 10px;'
                f'border-radius:10px;font-size:10px;font-weight:700;">NUOVA</span>'
            )
            top.addWidget(new_badge)

        top.addStretch()

        if "date" in entry:
            date_lbl = QLabel(f"📅 {entry['date']}")
            date_lbl.setStyleSheet(f"color:{self._sub_text_color()};font-size:11px;")
            top.addWidget(date_lbl)

        lay.addLayout(top)

        # ── Separatore ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{self._separator_color()};")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

        # ── Modifiche raggruppate per categoria ──
        changes = entry.get("changes", [])
        if changes:
            groups = self._categorize_changes(changes)
            # Ordine fisso delle categorie
            order = ["✨", "🔧", "🐛", "🗑️", "📌"]
            for cat_key in order:
                items = groups.get(cat_key)
                if not items:
                    continue
                cat = CHANGE_CATEGORIES[cat_key]
                color = self._cat_color(cat_key)

                # Intestazione categoria
                cat_header = QHBoxLayout()
                cat_header.setSpacing(6)
                cat_header.setContentsMargins(0, 6, 0, 2)

                dot = QLabel(f'<span style="color:{color};font-size:16px;">●</span>')
                cat_header.addWidget(dot)

                cat_title = QLabel(
                    f'<span style="color:{color};font-weight:700;font-size:12px;">'
                    f'{cat["label"].upper()}</span>'
                    f'<span style="color:{self._sub_text_color()};font-size:11px;"> — '
                    f'{len(items)} modific{"a" if len(items) == 1 else "he"}</span>'
                )
                cat_header.addWidget(cat_title)
                cat_header.addStretch()
                lay.addLayout(cat_header)

                # Elenco modifiche della categoria
                for item_text in items:
                    row = QHBoxLayout()
                    row.setContentsMargins(22, 0, 0, 0)
                    row.setSpacing(8)

                    bullet = QLabel(f'<span style="color:{color};font-size:10px;">▸</span>')
                    bullet.setFixedWidth(14)
                    bullet.setAlignment(Qt.AlignTop)
                    row.addWidget(bullet)

                    desc = QLabel(item_text)
                    desc.setWordWrap(True)
                    desc.setStyleSheet(
                        f"color:{self._text_color()};font-size:12px;padding:1px 0;"
                    )
                    desc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                    row.addWidget(desc, 1)

                    lay.addLayout(row)

        return frame

    # ── Confronto versioni ──────────────────────────────────────────
    @staticmethod
    def _version_compare(v1: str, v2: str) -> int:
        """Ritorna -1 se v1 < v2, 0 se uguali, 1 se v1 > v2."""
        try:
            from packaging import version
            p1, p2 = version.parse(v1), version.parse(v2)
            return -1 if p1 < p2 else (1 if p1 > p2 else 0)
        except Exception:
            parts1 = [int(x) for x in v1.split(".")]
            parts2 = [int(x) for x in v2.split(".")]
            for a, b in zip(parts1, parts2):
                if a < b:
                    return -1
                if a > b:
                    return 1
            return 0

