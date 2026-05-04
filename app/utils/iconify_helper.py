"""
iconify_helper.py
=================
Modulo centralizzato per le icone dell'app, basato esclusivamente su qtawesome.

Fornisce:
- ``get_icon(name, color, theme)``        → QIcon
- ``get_pixmap(name, color, theme, size)`` → QPixmap
- ``icon_color(theme)``                   → str (colore CSS)
- ``icon_color_accent(theme)``            → str (colore accento CSS)
- ``ICONS``                               → dizionario nome simbolico → fa5s.*
"""
from __future__ import annotations
import logging

from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize

import qtawesome as qta

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Colori predefiniti
# ─────────────────────────────────────────────────────────────────────────────
_LIGHT_COLOR = "#1e293b"   # slate-800
_DARK_COLOR  = "#e2e8f0"   # slate-200

# ─────────────────────────────────────────────────────────────────────────────
# Dizionario centralizzato  nome simbolico → fa5s.*
# ─────────────────────────────────────────────────────────────────────────────
ICONS: dict[str, str] = {
    # ── Azioni principali ──────────────────────────────────────────────────
    "electrical_verify":    "fa5s.bolt",
    "functional_verify":    "fa5s.heartbeat",
    "archive":              "fa5s.database",
    "sync":                 "fa5s.sync-alt",
    "search":               "fa5s.search",
    "add":                  "fa5s.plus-circle",
    "edit":                 "fa5s.edit",
    "delete":               "fa5s.trash-alt",
    "save":                 "fa5s.save",
    "close":                "fa5s.times-circle",
    "export":               "fa5s.download",
    "import":               "fa5s.upload",
    "print":                "fa5s.print",
    "refresh":              "fa5s.sync-alt",
    # ── Navigazione ────────────────────────────────────────────────────────
    "back":                 "fa5s.arrow-left",
    "forward":              "fa5s.arrow-right",
    "home":                 "fa5s.home",
    "settings":             "fa5s.cog",
    "help":                 "fa5s.question-circle",
    "info":                 "fa5s.info-circle",
    # ── Sessione / utenti ──────────────────────────────────────────────────
    "user":                 "fa5s.user",
    "users":                "fa5s.users",
    "login":                "fa5s.sign-in-alt",
    "logout":               "fa5s.sign-out-alt",
    "lock":                 "fa5s.lock",
    "password":             "fa5s.key",
    # ── Dispositivi / strumenti ────────────────────────────────────────────
    "device":               "fa5s.microchip",
    "instrument":           "fa5s.tools",
    "com_port":             "fa5s.plug",
    "calendar":             "fa5s.calendar-alt",
    "clock":                "fa5s.clock",
    "history":              "fa5s.history",
    "report":               "fa5s.file-alt",
    # ── Stato / feedback ───────────────────────────────────────────────────
    "ok":                   "fa5s.check-circle",
    "warning":              "fa5s.exclamation-triangle",
    "error":                "fa5s.times-circle",
    "pending":              "fa5s.spinner",
    "conflict":             "fa5s.exclamation-circle",
    # ── Statistiche / dashboard ────────────────────────────────────────────
    "chart":                "fa5s.chart-bar",
    "pie":                  "fa5s.chart-pie",
    "stats":                "fa5s.chart-line",
    "audit":                "fa5s.list-alt",
    "quality":              "fa5s.check-double",
    # ── Temi / personalizzazione ───────────────────────────────────────────
    "theme":                "fa5s.palette",
    "logo":                 "fa5s.image",
    "qr":                   "fa5s.qrcode",
    "update":               "fa5s.download",
    "changelog":            "fa5s.list-alt",
    "shortcuts":            "fa5s.keyboard",
    "about":                "fa5s.info-circle",
    # ── Dati ───────────────────────────────────────────────────────────────
    "backup":               "fa5s.file-archive",
    "restore":              "fa5s.undo",
    "duplicate":            "fa5s.clone",
    "trash":                "fa5s.trash-alt",
    "magic":                "fa5s.magic",
}


# ─────────────────────────────────────────────────────────────────────────────
# API pubblica
# ─────────────────────────────────────────────────────────────────────────────

def icon_color(theme: str = "light") -> str:
    """Colore icona corretto per il tema corrente."""
    return _DARK_COLOR if theme == "dark" else _LIGHT_COLOR


def icon_color_accent(theme: str = "light") -> str:
    """Colore di accento per icone evidenziate."""
    return "#60a5fa" if theme == "dark" else "#2563eb"


def get_icon(
    name: str,
    color: str | None = None,
    theme: str = "light",
    **kwargs,
) -> QIcon:
    """
    Restituisce un ``QIcon`` qtawesome per il nome simbolico.

    Parameters
    ----------
    name : str
        Chiave in ``ICONS`` oppure direttamente una stringa ``fa5s.*``.
    color : str, optional
        Colore CSS. Se omesso viene scelto in base al tema.
    theme : str
        ``"light"`` o ``"dark"``.
    """
    if color is None:
        color = _DARK_COLOR if theme == "dark" else _LIGHT_COLOR
    qta_name = ICONS.get(name, name)
    try:
        return qta.icon(qta_name, color=color)
    except Exception as exc:
        logger.debug("get_icon fallback per '%s': %s", name, exc)
        return QIcon()


def get_pixmap(
    name: str,
    color: str | None = None,
    theme: str = "light",
    size: int = 24,
):
    """
    Restituisce un ``QPixmap`` qtawesome per il nome simbolico.

    Parameters
    ----------
    name : str
        Chiave in ``ICONS`` oppure direttamente una stringa ``fa5s.*``.
    color : str, optional
        Colore CSS. Se omesso viene scelto in base al tema.
    theme : str
        ``"light"`` o ``"dark"``.
    size : int
        Lato del pixmap quadrato in pixel.
    """
    if color is None:
        color = _DARK_COLOR if theme == "dark" else _LIGHT_COLOR
    qta_name = ICONS.get(name, name)
    try:
        return qta.icon(qta_name, color=color).pixmap(QSize(size, size))
    except Exception as exc:
        logger.debug("get_pixmap fallback per '%s': %s", name, exc)
        from PySide6.QtGui import QPixmap as _QPixmap
        return _QPixmap(size, size)
