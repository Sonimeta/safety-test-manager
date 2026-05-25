# app/ui/dialogs/assignments_dialog.py
"""
Dialogs per la gestione delle assegnazioni di verifiche.

BulkAssignDialog         - Assegnazione intelligente multi-dispositivo / sede / cliente
AssignmentsManagerDialog - Lista lavori con apertura dettaglio
AssignmentDetailDialog   - Dettaglio completo con azioni inline
"""

import logging
from datetime import datetime, date as date_cls
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QLineEdit, QTextEdit, QDateEdit, QMessageBox,
    QFormLayout, QFrame, QSplitter, QScrollArea,
    QSizePolicy, QCheckBox, QProgressBar, QApplication,
    QMenu, QListWidget, QListWidgetItem, QButtonGroup, QRadioButton,
)
from PySide6.QtCore import Qt, QDate, QTimer, QSortFilterProxyModel, QStringListModel
from PySide6.QtGui import QColor, QBrush, QFont, QCursor

import database
from app import auth_manager

# ─── Costanti ─────────────────────────────────────────────────────────────────

PRIORITY_COLORS = {
    "urgent": QColor("#fef2f2"),
    "high":   QColor("#fffbeb"),
    "normal": QColor("#eff6ff"),
    "low":    QColor("#f0fdf4"),
}
PRIORITY_LABELS = {
    "urgent": "🔴 Urgente",
    "high":   "🟡 Alta",
    "normal": "🔵 Normale",
    "low":    "🟢 Bassa",
}
STATUS_LABELS = {
    "pending":     "⏳ In attesa",
    "in_progress": "🔄 In corso",
    "completed":   "✅ Completato",
    "cancelled":   "❌ Annullato",
}
STATUS_COLORS = {
    "pending":     QColor("#f1f5f9"),
    "in_progress": QColor("#fef3c7"),
    "completed":   QColor("#d1fae5"),
    "cancelled":   QColor("#fee2e2"),
}
STATUS_BTN_STYLE = {
    "pending":     "background:#64748b;",
    "in_progress": "background:#d97706;",
    "completed":   "background:#16a34a;",
    "cancelled":   "background:#dc2626;",
}

_ST   = "font-size:12px;font-weight:bold;color:#1e3a8a;padding-bottom:2px;"
_CARD = "QFrame#card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:6px;}"
_HDR  = "background:#1e3a8a;"

_BTN_BASE = ("QPushButton{{border:1px solid {bc};color:{fc};border-radius:5px;"
             "padding:4px 10px;font-size:11px;font-weight:bold;}}"
             "QPushButton:hover{{background:{hc};}}"
             "QPushButton:disabled{{color:#94a3b8;border-color:#cbd5e1;}}")


def _hdr_label(text, sub=None):
    w = QFrame(); w.setStyleSheet(_HDR)
    lay = QHBoxLayout(w); lay.setContentsMargins(20, 12, 20, 12)
    col = QVBoxLayout(); col.setSpacing(2)
    t = QLabel(text); t.setStyleSheet("color:white;font-size:15px;font-weight:bold;")
    col.addWidget(t)
    if sub:
        s = QLabel(sub); s.setStyleSheet("color:#93c5fd;font-size:11px;")
        col.addWidget(s)
    lay.addLayout(col); lay.addStretch()
    return w


def _sep():
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("background:#e2e8f0;max-height:1px;"); return f


def _mode_btn(text, checked=False):
    b = QPushButton(text)
    b.setCheckable(True); b.setChecked(checked)
    b.setStyleSheet(
        "QPushButton{border:1px solid #e2e8f0;border-radius:5px;padding:5px 14px;"
        "font-size:12px;font-weight:bold;color:#475569;background:white;}"
        "QPushButton:checked{background:#1e3a8a;color:white;border-color:#1e3a8a;}"
        "QPushButton:hover:!checked{background:#f1f5f9;}")
    return b


# ─────────────────────────────────────────────────────────────────────────────
#  _CheckList — lista piatta con checkbox affidabili
# ─────────────────────────────────────────────────────────────────────────────

class _CheckList(QWidget):
    """
    Lista piatta di elementi selezionabili con checkbox.
    Ogni elemento ha: id (int), label (str), sub-label (str), checked (bool).
    Nessuna logica a cascata — semplice e affidabile.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(4)

        # Barra ricerca + azioni rapide
        top = QHBoxLayout(); top.setSpacing(4)
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Cerca...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        top.addWidget(self._search, 1)

        for icon, tip, fn in [("☑", "Seleziona tutto", self.check_all),
                               ("☐", "Deseleziona tutto", self.uncheck_all)]:
            b = QPushButton(icon); b.setFixedSize(28, 28)
            b.setToolTip(tip)
            b.setStyleSheet("QPushButton{border:1px solid #e2e8f0;border-radius:4px;font-size:13px;}"
                            "QPushButton:hover{background:#f1f5f9;}")
            b.clicked.connect(fn); top.addWidget(b)
        lay.addLayout(top)

        # Lista
        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget{border:1px solid #e2e8f0;border-radius:6px;background:white;"
            "font-size:12px;outline:none;}"
            "QListWidget::item{padding:6px 8px;border-bottom:1px solid #f1f5f9;min-height:28px;}"
            "QListWidget::item:hover{background:#f8fafc;}"
            "QListWidget::item:selected{background:#dbeafe;color:#1e3a8a;}")
        self._list.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self._list, 1)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color:#64748b;font-size:11px;")
        lay.addWidget(self._count_lbl)

        self._items: list[dict] = []  # {id, label, sublabel, checked}
        self._on_change_cb = None

    def set_on_change(self, cb):
        self._on_change_cb = cb

    def set_items(self, items: list[dict], reset_search=True):
        """items: lista di dict {id, label, sublabel='', checked=False}"""
        self._items = [dict(i) for i in items]
        if reset_search:
            self._search.blockSignals(True)
            self._search.clear()
            self._search.blockSignals(False)
        self._rebuild_list()

    def _rebuild_list(self, filter_text=""):
        self._list.blockSignals(True)
        self._list.clear()
        ft = filter_text.lower()
        for item in self._items:
            if ft and ft not in item["label"].lower() and ft not in item.get("sublabel","").lower():
                continue
            li = QListWidgetItem()
            li.setData(Qt.UserRole, item["id"])
            li.setCheckState(Qt.Checked if item["checked"] else Qt.Unchecked)
            # Testo principale + sub
            sub = item.get("sublabel", "")
            if sub:
                li.setText(f"{item['label']}\n{sub}")
            else:
                li.setText(item["label"])
            li.setFont(QFont("", 11))
            self._list.addItem(li)
        self._list.blockSignals(False)
        self._refresh_count()

    def _apply_filter(self, text):
        self._rebuild_list(text)

    def _on_item_changed(self, li: QListWidgetItem):
        item_id = li.data(Qt.UserRole)
        checked = li.checkState() == Qt.Checked
        for item in self._items:
            if item["id"] == item_id:
                item["checked"] = checked
                break
        self._refresh_count()
        if self._on_change_cb:
            self._on_change_cb()

    def _refresh_count(self):
        checked = sum(1 for i in self._items if i["checked"])
        total = len(self._items)
        self._count_lbl.setText(f"{checked} / {total} selezionati")

    def check_all(self):
        self._list.blockSignals(True)
        ft = self._search.text().lower()
        for item in self._items:
            if not ft or ft in item["label"].lower() or ft in item.get("sublabel","").lower():
                item["checked"] = True
        for i in range(self._list.count()):
            li = self._list.item(i); li.setCheckState(Qt.Checked)
        self._list.blockSignals(False)
        self._refresh_count()
        if self._on_change_cb: self._on_change_cb()

    def uncheck_all(self):
        self._list.blockSignals(True)
        for item in self._items:
            item["checked"] = False
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.Unchecked)
        self._list.blockSignals(False)
        self._refresh_count()
        if self._on_change_cb: self._on_change_cb()

    def get_checked_ids(self) -> list[int]:
        return [i["id"] for i in self._items if i["checked"]]

    def get_checked_items(self) -> list[dict]:
        return [i for i in self._items if i["checked"]]

    def check_by_ids(self, ids: set):
        self._list.blockSignals(True)
        for item in self._items:
            item["checked"] = item["id"] in ids
        for i in range(self._list.count()):
            li = self._list.item(i)
            li.setCheckState(Qt.Checked if li.data(Qt.UserRole) in ids else Qt.Unchecked)
        self._list.blockSignals(False)
        self._refresh_count()
        if self._on_change_cb: self._on_change_cb()


# ─────────────────────────────────────────────────────────────────────────────
#  BulkAssignDialog
# ─────────────────────────────────────────────────────────────────────────────

class BulkAssignDialog(QDialog):
    """
    Assegnazione intelligente.

    Modalità SEDI   → seleziona 1+ destinazioni → 1 assegnazione per sede
    Modalità DISPOSITIVI → seleziona 1+ dispositivi (con filtri cliente/sede) → 1 per dispositivo
    """

    def __init__(self, parent=None,
                 preselect_device_id: int | None = None,
                 preselect_destination_id: int | None = None,
                 preselect_customer_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("📋  Nuova Assegnazione Verifiche")
        self.setMinimumSize(1080, 700)
        self.setModal(True)

        self._pre_dev  = preselect_device_id
        self._pre_dest = preselect_destination_id
        self._pre_cust = preselect_customer_id

        # Cache dati
        self._customers: list[dict] = []
        self._destinations: list[dict] = []   # {id, name, customer_id, customer_name, n_devices}
        self._devices: list[dict] = []        # {id, label, dest_id, cust_id}

        self._build_ui()
        QTimer.singleShot(0, self._load_data)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0); root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(_hdr_label(
            "📋  Nuova Assegnazione Verifiche",
            "①  Seleziona sedi o dispositivi  ·  ②  Configura parametri  ·  ③  Crea"
        ))

        # ── Body splitter ──────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        # ══════════════════════════════════════════════════════════════════════
        # COL 1 — Selezione
        # ══════════════════════════════════════════════════════════════════════
        col1 = QWidget(); col1.setMinimumWidth(440)
        c1l = QVBoxLayout(col1); c1l.setContentsMargins(14, 14, 8, 8); c1l.setSpacing(8)

        # Step label
        step1 = QLabel("① Cosa vuoi assegnare?"); step1.setStyleSheet(_ST)
        c1l.addWidget(step1)

        # ── Modalità ─────────────────────────────────────────────────────────
        mode_row = QHBoxLayout(); mode_row.setSpacing(6)
        self._mode_dest = _mode_btn("📍  Per sede (intera)", checked=True)
        self._mode_dev  = _mode_btn("🔧  Per dispositivo")

        grp = QButtonGroup(self)
        grp.addButton(self._mode_dest); grp.addButton(self._mode_dev)
        grp.setExclusive(True)
        self._mode_dest.toggled.connect(self._on_mode_changed)

        mode_row.addWidget(self._mode_dest)
        mode_row.addWidget(self._mode_dev)
        mode_row.addStretch()
        c1l.addLayout(mode_row)

        # ── Filtri rapidi (solo in modalità dispositivo) ──────────────────────
        self._filter_bar = QWidget()
        fb_l = QHBoxLayout(self._filter_bar)
        fb_l.setContentsMargins(0, 0, 0, 0); fb_l.setSpacing(6)

        fb_l.addWidget(QLabel("Cliente:"))
        self._cust_filter = QComboBox()
        self._cust_filter.addItem("Tutti i clienti", None)
        self._cust_filter.currentIndexChanged.connect(self._apply_dev_filters)
        fb_l.addWidget(self._cust_filter, 1)

        fb_l.addWidget(QLabel("Sede:"))
        self._dest_filter = QComboBox()
        self._dest_filter.addItem("Tutte le sedi", None)
        self._dest_filter.currentIndexChanged.connect(self._apply_dev_filters)
        fb_l.addWidget(self._dest_filter, 1)

        self._filter_bar.setVisible(False)
        c1l.addWidget(self._filter_bar)

        # ── Liste (sedi / dispositivi) ────────────────────────────────────────
        self._dest_list = _CheckList()
        self._dest_list.set_on_change(self._refresh_preview)
        c1l.addWidget(self._dest_list, 1)

        self._dev_list = _CheckList()
        self._dev_list.set_on_change(self._refresh_preview)
        self._dev_list.setVisible(False)
        c1l.addWidget(self._dev_list, 1)

        # ── Quick-select buttons ──────────────────────────────────────────────
        qs = QHBoxLayout(); qs.setSpacing(6)
        self._btn_sel_dest = QPushButton("📍 Sede corrente")
        self._btn_sel_dest.setStyleSheet(_BTN_BASE.format(bc="#3b82f6",fc="#1d4ed8",hc="#eff6ff"))
        self._btn_sel_dest.setEnabled(False)
        self._btn_sel_dest.clicked.connect(self._quick_sel_dest)
        qs.addWidget(self._btn_sel_dest)

        self._btn_sel_cust = QPushButton("🏢 Cliente corrente")
        self._btn_sel_cust.setStyleSheet(_BTN_BASE.format(bc="#8b5cf6",fc="#6d28d9",hc="#f5f3ff"))
        self._btn_sel_cust.setEnabled(False)
        self._btn_sel_cust.clicked.connect(self._quick_sel_cust)
        qs.addWidget(self._btn_sel_cust)
        qs.addStretch()
        c1l.addLayout(qs)

        splitter.addWidget(col1)

        # ══════════════════════════════════════════════════════════════════════
        # COL 2 — Parametri
        # ══════════════════════════════════════════════════════════════════════
        col2 = QWidget(); col2.setMinimumWidth(280); col2.setMaximumWidth(320)
        c2l = QVBoxLayout(col2); c2l.setContentsMargins(8, 14, 8, 8); c2l.setSpacing(10)

        step2 = QLabel("② Parametri assegnazione"); step2.setStyleSheet(_ST)
        c2l.addWidget(step2)

        form = QFormLayout(); form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # Tecnico
        self._tech_combo = QComboBox()
        self._tech_combo.setEditable(True)
        self._tech_combo.setInsertPolicy(QComboBox.NoInsert)
        self._tech_combo.lineEdit().setPlaceholderText("Digita o seleziona...")
        self._tech_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._tech_combo.currentTextChanged.connect(lambda _: self._refresh_preview())
        form.addRow("Tecnico *:", self._tech_combo)

        # Priorità
        self._prio_combo = QComboBox()
        for k, v in PRIORITY_LABELS.items():
            self._prio_combo.addItem(v, k)
        self._prio_combo.setCurrentIndex(2)  # normal
        self._prio_combo.currentIndexChanged.connect(lambda _: self._refresh_preview())
        form.addRow("Priorità:", self._prio_combo)

        # Scadenza
        due_w = QWidget(); due_l = QVBoxLayout(due_w)
        due_l.setContentsMargins(0, 0, 0, 0); due_l.setSpacing(4)
        dr = QHBoxLayout()
        self._due_edit = QDateEdit()
        self._due_edit.setCalendarPopup(True)
        self._due_edit.setDate(QDate.currentDate().addDays(14))
        self._due_edit.setMinimumDate(QDate.currentDate())
        self._due_edit.dateChanged.connect(lambda _: self._refresh_preview())
        dr.addWidget(self._due_edit)
        self._no_date_chk = QCheckBox("Nessuna")
        self._no_date_chk.toggled.connect(lambda c: (
            self._due_edit.setEnabled(not c), self._refresh_preview()
        ))
        dr.addWidget(self._no_date_chk)
        due_l.addLayout(dr)
        # Scorciatoie data
        qd = QHBoxLayout(); qd.setSpacing(4)
        for days, lbl in [(7, "+7g"), (14, "+14g"), (30, "+1m"), (90, "+3m")]:
            b = QPushButton(lbl); b.setFixedWidth(44)
            b.setStyleSheet("QPushButton{font-size:10px;border:1px solid #e2e8f0;"
                            "border-radius:4px;padding:2px;color:#475569;}"
                            "QPushButton:hover{background:#f1f5f9;}")
            b.clicked.connect(lambda _, d=days: (
                self._no_date_chk.setChecked(False),
                self._due_edit.setDate(QDate.currentDate().addDays(d))
            ))
            qd.addWidget(b)
        qd.addStretch()
        due_l.addLayout(qd)
        form.addRow("Scadenza:", due_w)

        # Note
        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText("Istruzioni per il tecnico (opzionale)...")
        self._notes_edit.setFixedHeight(80)
        form.addRow("Note:", self._notes_edit)

        c2l.addLayout(form)
        c2l.addStretch()
        splitter.addWidget(col2)

        # ══════════════════════════════════════════════════════════════════════
        # COL 3 — Anteprima
        # ══════════════════════════════════════════════════════════════════════
        col3 = QWidget(); col3.setMinimumWidth(240)
        c3l = QVBoxLayout(col3); c3l.setContentsMargins(8, 14, 14, 8); c3l.setSpacing(6)

        step3 = QLabel("③ Anteprima"); step3.setStyleSheet(_ST)
        c3l.addWidget(step3)

        # Card info tecnico/prio/scadenza
        card = QFrame(); card.setObjectName("card"); card.setStyleSheet(_CARD)
        cl = QVBoxLayout(card); cl.setContentsMargins(10, 8, 10, 8); cl.setSpacing(4)
        self._pv_tech = QLabel("—"); self._pv_tech.setStyleSheet("font-size:11px;font-weight:bold;")
        self._pv_prio = QLabel("—"); self._pv_prio.setStyleSheet("font-size:11px;")
        self._pv_due  = QLabel("—"); self._pv_due.setStyleSheet("font-size:11px;")
        for lbl_text, widget in [("👤 Tecnico", self._pv_tech),
                                  ("⚡ Priorità", self._pv_prio),
                                  ("📅 Scadenza", self._pv_due)]:
            row = QHBoxLayout()
            ll = QLabel(f"{lbl_text}:"); ll.setStyleSheet("font-size:11px;color:#64748b;min-width:70px;")
            row.addWidget(ll); row.addWidget(widget, 1)
            cl.addLayout(row)
        c3l.addWidget(card)

        # Lista anteprima attività
        pv_hdr = QLabel("Attività che verranno create:")
        pv_hdr.setStyleSheet("font-size:11px;color:#475569;font-weight:bold;margin-top:4px;")
        c3l.addWidget(pv_hdr)

        from PySide6.QtWidgets import QListWidget as _LW
        self._pv_list = _LW()
        self._pv_list.setStyleSheet(
            "QListWidget{border:1px solid #e2e8f0;border-radius:6px;background:white;font-size:11px;}"
            "QListWidget::item{padding:5px 8px;border-bottom:1px solid #f1f5f9;min-height:24px;}")
        self._pv_list.setSelectionMode(QAbstractItemView.NoSelection)
        c3l.addWidget(self._pv_list, 1)

        self._total_lbl = QLabel("")
        self._total_lbl.setStyleSheet("color:#1e3a8a;font-weight:bold;font-size:12px;")
        c3l.addWidget(self._total_lbl)

        splitter.addWidget(col3)
        splitter.setSizes([480, 300, 280])
        root.addWidget(splitter, 1)

        # ── Footer ──────────────────────────────────────────────────────────
        foot = QFrame(); foot.setStyleSheet("background:#f8fafc;border-top:1px solid #e2e8f0;")
        fl = QHBoxLayout(foot); fl.setContentsMargins(16, 10, 16, 10); fl.setSpacing(8)

        self._progress = QProgressBar()
        self._progress.setVisible(False); self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        fl.addWidget(self._progress, 1)

        cancel_btn = QPushButton("Annulla"); cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("QPushButton{padding:7px 16px;border-radius:5px;border:1px solid #e2e8f0;}")

        self._create_btn = QPushButton("✔  Crea Assegnazioni")
        self._create_btn.setStyleSheet(
            "QPushButton{background:#1e3a8a;color:white;font-weight:bold;"
            "padding:8px 24px;border-radius:6px;font-size:13px;}"
            "QPushButton:hover{background:#1d4ed8;}"
            "QPushButton:disabled{background:#94a3b8;}")
        self._create_btn.setDefault(True)
        self._create_btn.setEnabled(False)
        self._create_btn.clicked.connect(self._create_assignments)

        fl.addStretch()
        fl.addWidget(cancel_btn)
        fl.addWidget(self._create_btn)
        root.addWidget(foot)

    # ── Load data ─────────────────────────────────────────────────────────────

    def _load_data(self):
        try:
            self._customers = [dict(r) for r in database.get_all_customers()]
            destinations_raw = [dict(r) for r in database.get_all_destinations_with_customer()]

            # Recupera conteggio dispositivi per sede
            dev_count: dict[int, int] = {}
            all_devices_raw: list[dict] = []
            for dest in destinations_raw:
                devs = [dict(d) for d in database.get_devices_for_destination(dest["id"])]
                dev_count[dest["id"]] = len(devs)
                for dev in devs:
                    lbl = dev.get("description") or dev.get("model") or f"#{dev['id']}"
                    sn = dev.get("serial_number")
                    if sn: lbl += f"  —  S/N {sn}"
                    all_devices_raw.append({
                        "id":       dev["id"],
                        "label":    lbl,
                        "dest_id":  dest["id"],
                        "dest_name": dest["name"],
                        "cust_id":  dest.get("customer_id"),
                        "cust_name": dest.get("customer_name") or "",
                    })

            self._destinations = [
                {
                    "id":          d["id"],
                    "name":        d["name"],
                    "customer_id": d.get("customer_id"),
                    "customer_name": d.get("customer_name") or "",
                    "n_devices":   dev_count.get(d["id"], 0),
                }
                for d in destinations_raw
            ]
            self._devices = all_devices_raw

            # Popola filtri cliente/sede
            self._cust_filter.blockSignals(True)
            self._dest_filter.blockSignals(True)
            self._cust_filter.clear(); self._cust_filter.addItem("Tutti i clienti", None)
            for c in self._customers:
                self._cust_filter.addItem(c["name"], c["id"])
            self._dest_filter.clear(); self._dest_filter.addItem("Tutte le sedi", None)
            for d in self._destinations:
                self._dest_filter.addItem(f"{d['name']}  ({d['customer_name']})", d["id"])
            self._cust_filter.blockSignals(False)
            self._dest_filter.blockSignals(False)

            # Popola lista sedi
            self._dest_list.set_items([
                {
                    "id": d["id"],
                    "label": d["name"],
                    "sublabel": f"🏢 {d['customer_name']}  ·  {d['n_devices']} dispositivi",
                    "checked": False,
                }
                for d in self._destinations
            ])

            # Popola lista dispositivi (tutto)
            self._dev_list.set_items([
                {
                    "id": dv["id"],
                    "label": dv["label"],
                    "sublabel": f"📍 {dv['dest_name']}  ·  🏢 {dv['cust_name']}",
                    "checked": False,
                }
                for dv in self._devices
            ])

        except Exception as e:
            logging.error(f"BulkAssignDialog load error: {e}", exc_info=True)

        self._load_technicians()
        self._apply_preselections()
        self._btn_sel_dest.setEnabled(self._pre_dest is not None)
        self._btn_sel_cust.setEnabled(self._pre_cust is not None)

    def _load_technicians(self):
        self._tech_combo.clear()
        self._tech_combo.addItem("", "")
        added: set[str] = {""}
        try:
            from app.http_client import http_session
            from app import config as _cfg
            resp = http_session.get(f"{_cfg.SERVER_URL}/users",
                                    headers=auth_manager.get_auth_headers(), timeout=5)
            if resp.status_code == 200:
                for u in resp.json():
                    uname = u.get("username", "")
                    if not uname or uname in added: continue
                    fn = (u.get("first_name") or "").strip()
                    ln = (u.get("last_name") or "").strip()
                    display = f"{fn} {ln}".strip()
                    self._tech_combo.addItem(f"{display}  ({uname})" if display else uname, uname)
                    added.add(uname)
        except Exception as e:
            logging.debug(f"_load_technicians server fallback: {e}")
        try:
            for row in database.get_unique_technicians():
                name = row[0] if not isinstance(row, str) else row
                if name and name not in added:
                    self._tech_combo.addItem(name, name); added.add(name)
        except Exception:
            pass

    def _apply_preselections(self):
        """Seleziona automaticamente dispositivo/sede/cliente dalla context corrente."""
        if self._pre_dev:
            self._mode_dev.setChecked(True)
            self._dev_list.check_by_ids({self._pre_dev})
        elif self._pre_dest:
            self._mode_dest.setChecked(True)
            self._dest_list.check_by_ids({self._pre_dest})
        elif self._pre_cust:
            dest_ids = {d["id"] for d in self._destinations if d["customer_id"] == self._pre_cust}
            self._mode_dest.setChecked(True)
            self._dest_list.check_by_ids(dest_ids)
        self._refresh_preview()

    # ── Modalità selezione ────────────────────────────────────────────────────

    def _on_mode_changed(self, dest_mode: bool):
        self._dest_list.setVisible(dest_mode)
        self._dev_list.setVisible(not dest_mode)
        self._filter_bar.setVisible(not dest_mode)
        self._refresh_preview()

    @property
    def _is_dest_mode(self) -> bool:
        return self._mode_dest.isChecked()

    # ── Filtri dispositivi ────────────────────────────────────────────────────

    def _apply_dev_filters(self):
        cust_id = self._cust_filter.currentData()
        dest_id = self._dest_filter.currentData()

        # Aggiorna dest_filter in base al cliente selezionato
        self._dest_filter.blockSignals(True)
        cur_dest = self._dest_filter.currentData()
        self._dest_filter.clear()
        self._dest_filter.addItem("Tutte le sedi", None)
        for d in self._destinations:
            if cust_id is None or d["customer_id"] == cust_id:
                self._dest_filter.addItem(f"{d['name']}  ({d['customer_name']})", d["id"])
        # Ripristina la sede selezionata se ancora valida
        idx = self._dest_filter.findData(cur_dest)
        self._dest_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self._dest_filter.blockSignals(False)
        dest_id = self._dest_filter.currentData()

        # Ricarica lista dispositivi filtrata
        filtered = [
            {
                "id": dv["id"],
                "label": dv["label"],
                "sublabel": f"📍 {dv['dest_name']}  ·  🏢 {dv['cust_name']}",
                "checked": False,
            }
            for dv in self._devices
            if (cust_id is None or dv["cust_id"] == cust_id)
            and (dest_id is None or dv["dest_id"] == dest_id)
        ]
        self._dev_list.set_items(filtered)
        self._refresh_preview()

    # ── Quick-select ──────────────────────────────────────────────────────────

    def _quick_sel_dest(self):
        if not self._pre_dest: return
        if self._is_dest_mode:
            self._dest_list.uncheck_all()
            self._dest_list.check_by_ids({self._pre_dest})
        else:
            # Filtra per la sede corrente
            self._dest_filter.setCurrentIndex(self._dest_filter.findData(self._pre_dest))

    def _quick_sel_cust(self):
        if not self._pre_cust: return
        if self._is_dest_mode:
            self._dest_list.uncheck_all()
            ids = {d["id"] for d in self._destinations if d["customer_id"] == self._pre_cust}
            self._dest_list.check_by_ids(ids)
        else:
            self._cust_filter.setCurrentIndex(self._cust_filter.findData(self._pre_cust))

    # ── Preview ───────────────────────────────────────────────────────────────

    def _get_selected_units(self) -> tuple[list[dict], list[dict]]:
        """
        Restituisce (dest_items, dev_items) secondo la modalità attiva.
        Sempre escludibili — nessuna logica a cascata.
        """
        if self._is_dest_mode:
            return self._dest_list.get_checked_items(), []
        else:
            return [], self._dev_list.get_checked_items()

    def _refresh_preview(self):
        dest_units, dev_units = self._get_selected_units()
        total = len(dest_units) + len(dev_units)
        tech = (self._tech_combo.currentData() or self._tech_combo.currentText() or "").strip()
        prio = PRIORITY_LABELS.get(self._prio_combo.currentData(), "—")
        due  = "Nessuna" if self._no_date_chk.isChecked() else self._due_edit.date().toString("dd/MM/yyyy")

        self._pv_tech.setText(tech or "(non impostato)")
        self._pv_prio.setText(prio)
        self._pv_due.setText(due)

        self._pv_list.clear()
        from PySide6.QtWidgets import QListWidgetItem as _LI
        from PySide6.QtGui import QBrush as _B, QColor as _C
        for d in dest_units:
            li = _LI(f"📍  {d['label']}")
            li.setForeground(_B(_C("#166534")))
            self._pv_list.addItem(li)
        for d in dev_units:
            li = _LI(f"🔧  {d['label']}")
            li.setForeground(_B(_C("#1e3a8a")))
            self._pv_list.addItem(li)

        self._total_lbl.setText(
            f"Tot. {total} assegnazion{'e' if total == 1 else 'i'} da creare" if total else ""
        )
        self._create_btn.setEnabled(total > 0)

    # ── Crea assegnazioni ─────────────────────────────────────────────────────

    def _create_assignments(self):
        tech = (self._tech_combo.currentData() or self._tech_combo.currentText() or "").strip()
        if not tech:
            QMessageBox.warning(self, "Campo obbligatorio",
                "Seleziona o digita l'username del tecnico.")
            return

        dest_units, dev_units = self._get_selected_units()
        total = len(dest_units) + len(dev_units)
        if not total:
            QMessageBox.warning(self, "Nessuna selezione",
                "Seleziona almeno una sede o un dispositivo.")
            return

        parts = []
        if dest_units: parts.append(f"{len(dest_units)} sed{'e' if len(dest_units)==1 else 'i'}")
        if dev_units: parts.append(f"{len(dev_units)} dispositiv{'o' if len(dev_units)==1 else 'i'}")

        if QMessageBox.question(self, "Conferma",
            f"Creare <b>{total}</b> assegnazion{'e' if total==1 else 'i'} "
            f"({', '.join(parts)}) per <b>{tech}</b>?",
            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        priority    = self._prio_combo.currentData()
        due_date    = None if self._no_date_chk.isChecked() else self._due_edit.date().toString("yyyy-MM-dd")
        notes       = self._notes_edit.toPlainText().strip() or None
        assigned_by = auth_manager.get_current_username()

        self._progress.setVisible(True)
        self._progress.setMaximum(total); self._progress.setValue(0)
        self._create_btn.setEnabled(False)
        QApplication.processEvents()

        ok = errors = 0

        for idx, d in enumerate(dest_units):
            try:
                database.create_assignment(
                    device_id=None, destination_id=d["id"],
                    assigned_to=tech, assigned_by=assigned_by,
                    notes=notes, priority=priority, due_date=due_date,
                )
                ok += 1
            except Exception as e:
                logging.error(f"Errore sede {d['id']}: {e}"); errors += 1
            self._progress.setValue(idx + 1); QApplication.processEvents()

        for idx2, d in enumerate(dev_units):
            try:
                database.create_assignment(
                    device_id=d["id"], destination_id=None,
                    assigned_to=tech, assigned_by=assigned_by,
                    notes=notes, priority=priority, due_date=due_date,
                )
                ok += 1
            except Exception as e:
                logging.error(f"Errore device {d['id']}: {e}"); errors += 1
            self._progress.setValue(len(dest_units) + idx2 + 1); QApplication.processEvents()

        self._progress.setVisible(False)
        if errors:
            QMessageBox.warning(self, "Completato con errori",
                f"Assegnazioni create: <b>{ok}</b><br>Errori: <b>{errors}</b>")
        else:
            QMessageBox.information(self, "Fatto",
                f"✅  <b>{ok}</b> assegnazion{'e' if ok==1 else 'i'} creat{'a' if ok==1 else 'e'} "
                f"per <b>{tech}</b>.")
        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
#  AssignmentsManagerDialog
# ─────────────────────────────────────────────────────────────────────────────

class AssignmentsManagerDialog(QDialog):
    """Lista lavori assegnati con possibilità di aprire il dettaglio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestione Lavori Assegnati")
        self.setMinimumSize(1020, 660)
        self.setModal(True)
        self._role       = auth_manager.get_current_role()
        self._is_manager = self._role in ("admin", "moderator")
        self._username   = auth_manager.get_current_username()
        self._assignments: list[dict] = []
        self.started_assignment: dict | None = None  # impostato quando si avvia un'attività
        self._build_ui()
        self._load_assignments()

    def _build_ui(self):
        lay = QVBoxLayout(self); lay.setSpacing(0); lay.setContentsMargins(0, 0, 0, 0)

        lay.addWidget(_hdr_label(
            "📊  Gestione Lavori Assegnati",
            "Tutti i lavori" if self._is_manager else f"I tuoi lavori — {self._username}"
        ))

        # Stats bar
        stats_bar = QFrame()
        stats_bar.setStyleSheet("background:#eff6ff;border-bottom:1px solid #bfdbfe;")
        sbl = QHBoxLayout(stats_bar); sbl.setContentsMargins(16, 6, 16, 6); sbl.setSpacing(20)
        self._stat_labels: dict[str, QLabel] = {}
        for key, color in [("pending","#475569"),("in_progress","#d97706"),
                            ("completed","#16a34a"),("cancelled","#dc2626")]:
            lbl = QLabel()
            lbl.setStyleSheet(f"color:{color};font-size:11px;font-weight:bold;")
            self._stat_labels[key] = lbl
            sbl.addWidget(lbl)
        sbl.addStretch()
        if self._is_manager:
            nb = QPushButton("➕  Nuova Assegnazione")
            nb.setStyleSheet("QPushButton{background:#1e3a8a;color:white;font-weight:bold;"
                             "padding:5px 14px;border-radius:5px;font-size:11px;}"
                             "QPushButton:hover{background:#1d4ed8;}")
            nb.clicked.connect(self._open_new)
            sbl.addWidget(nb)
        lay.addWidget(stats_bar)

        # Toolbar filtri
        tb = QFrame(); tb.setStyleSheet("background:#f8fafc;border-bottom:1px solid #e2e8f0;")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(16, 8, 16, 8); tbl.setSpacing(8)
        tbl.addWidget(QLabel("Stato:"))
        self._f_status = QComboBox()
        self._f_status.addItem("Tutti", "")
        for k, v in STATUS_LABELS.items():
            self._f_status.addItem(v, k)
        self._f_status.currentIndexChanged.connect(self._load_assignments)
        tbl.addWidget(self._f_status)

        if self._is_manager:
            tbl.addWidget(QLabel("Tecnico:"))
            self._f_user = QComboBox(); self._f_user.addItem("Tutti", "")
            try:
                from app.http_client import http_session
                from app import config as _cfg
                resp = http_session.get(f"{_cfg.SERVER_URL}/users",
                                        headers=auth_manager.get_auth_headers(), timeout=5)
                if resp.status_code == 200:
                    for u in resp.json():
                        un = u.get("username", "")
                        if un: self._f_user.addItem(un, un)
            except Exception:
                try:
                    for u in database.get_unique_technicians():
                        n = u[0] if not isinstance(u, str) else u
                        if n: self._f_user.addItem(n, n)
                except Exception: pass
            self._f_user.currentIndexChanged.connect(self._load_assignments)
            tbl.addWidget(self._f_user)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("🔍 Cerca in tutti i campi...")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._filter_table)
        tbl.addWidget(self._search_box, 1)

        rb = QPushButton("🔄"); rb.setFixedWidth(32); rb.setToolTip("Aggiorna")
        rb.clicked.connect(self._load_assignments); tbl.addWidget(rb)
        lay.addWidget(tb)

        # Tabella
        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(12, 8, 12, 0)
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Lavoro", "Cliente / Sede", "Priorità", "Stato",
            "Tecnico", "Scadenza", "Assegnato da", "Creato il"
        ])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in range(2, 8):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self._table.itemDoubleClicked.connect(self._open_detail)
        self._table.itemSelectionChanged.connect(self._on_sel)
        self._table.setStyleSheet(
            "QTableWidget{font-size:12px;}"
            "QTableWidget::item{padding:5px 6px;}"
            "QHeaderView::section{background:#f8fafc;font-weight:bold;font-size:11px;"
            "border:none;border-bottom:2px solid #e2e8f0;padding:6px;}")
        bl.addWidget(self._table)
        lay.addWidget(body, 1)

        # Footer
        foot = QFrame(); foot.setStyleSheet("background:#f8fafc;border-top:1px solid #e2e8f0;")
        fl = QHBoxLayout(foot); fl.setContentsMargins(16, 10, 16, 10); fl.setSpacing(8)
        self._count_lbl = QLabel()
        self._count_lbl.setStyleSheet("color:#64748b;font-size:11px;")
        fl.addWidget(self._count_lbl); fl.addStretch()

        self._open_btn = QPushButton("📂  Apri Lavoro")
        self._open_btn.setStyleSheet(
            "QPushButton{background:#0f172a;color:white;font-weight:bold;padding:6px 16px;"
            "border-radius:5px;} QPushButton:hover{background:#1e293b;}"
            "QPushButton:disabled{background:#e2e8f0;color:#94a3b8;}")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_detail)
        fl.addWidget(self._open_btn)

        self._start_btn = QPushButton("▶  Avvia Attività")
        self._start_btn.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;font-weight:bold;padding:6px 16px;"
            "border-radius:5px;font-size:12px;} QPushButton:hover{background:#15803d;}"
            "QPushButton:disabled{background:#e2e8f0;color:#94a3b8;}")
        self._start_btn.setEnabled(False)
        self._start_btn.setToolTip("Segna come 'in corso' e vai al dispositivo/sede per avviare le verifiche")
        self._start_btn.clicked.connect(self._start_activity)
        fl.addWidget(self._start_btn)

        if self._is_manager:
            self._del_btn = QPushButton("🗑  Elimina")
            self._del_btn.setStyleSheet(
                "QPushButton{background:#dc2626;color:white;font-weight:bold;padding:6px 16px;"
                "border-radius:5px;} QPushButton:hover{background:#b91c1c;}"
                "QPushButton:disabled{background:#e2e8f0;color:#94a3b8;}")
            self._del_btn.setEnabled(False)
            self._del_btn.clicked.connect(self._delete_selected)
            fl.addWidget(self._del_btn)

        close_btn = QPushButton("Chiudi"); close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept); fl.addWidget(close_btn)
        lay.addWidget(foot)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_assignments(self):
        sf = self._f_status.currentData() or None
        uf = getattr(self, "_f_user", None)
        uf = (uf.currentData() or None) if uf else None
        try:
            if self._is_manager:
                rows = database.get_all_assignments(status_filter=sf)
                if uf: rows = [r for r in rows if r.get("assigned_to") == uf]
            else:
                rows = database.get_assignments_for_user(self._username, status_filter=sf)
        except Exception as e:
            logging.error(f"Errore caricamento assegnazioni: {e}"); rows = []
        self._assignments = rows
        self._populate(rows)
        self._update_stats(rows)

    def _update_stats(self, rows: list[dict]):
        counts: dict[str, int] = {k: 0 for k in STATUS_LABELS}
        for r in rows:
            s = r.get("status", "pending")
            counts[s] = counts.get(s, 0) + 1
        for key, lbl in self._stat_labels.items():
            lbl.setText(f"{STATUS_LABELS[key]}  {counts.get(key, 0)}")

    def _populate(self, items: list[dict]):
        self._table.setRowCount(0)
        for ri, a in enumerate(items):
            self._table.insertRow(ri)
            if a.get("device_id"):
                dev = a.get("description") or a.get("model") or "Dispositivo"
                if a.get("serial_number"): dev += f" — S/N {a['serial_number']}"
                dev_item = QTableWidgetItem(f"🔧  {dev}")
            else:
                dev_item = QTableWidgetItem(f"📍  {a.get('destination_name') or 'Sede'}")
            self._table.setItem(ri, 0, dev_item)

            cust = a.get("customer_name") or ""; dest = a.get("destination_name") or ""
            self._table.setItem(ri, 1, QTableWidgetItem(f"{cust} / {dest}" if (cust and dest) else cust or dest))

            p = a.get("priority", "normal")
            pi = QTableWidgetItem(PRIORITY_LABELS.get(p, p))
            pi.setBackground(PRIORITY_COLORS.get(p, QColor("white")))
            self._table.setItem(ri, 2, pi)

            st = a.get("status", "pending")
            si = QTableWidgetItem(STATUS_LABELS.get(st, st))
            si.setBackground(STATUS_COLORS.get(st, QColor("white")))
            self._table.setItem(ri, 3, si)

            self._table.setItem(ri, 4, QTableWidgetItem(a.get("assigned_to", "")))

            due = a.get("due_date") or ""
            di = QTableWidgetItem(str(due) if due else "—")
            if due:
                try:
                    dd = date_cls.fromisoformat(str(due))
                    if dd < date_cls.today() and st not in ("completed", "cancelled"):
                        di.setForeground(QBrush(QColor("#dc2626")))
                        bf = QFont(); bf.setBold(True); di.setFont(bf)
                        di.setText(f"⚠️ {due}")
                except Exception: pass
            self._table.setItem(ri, 5, di)
            self._table.setItem(ri, 6, QTableWidgetItem(a.get("assigned_by", "")))

            created = a.get("created_at") or ""
            try:
                created = datetime.fromisoformat(str(created).replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
            except Exception: pass
            self._table.setItem(ri, 7, QTableWidgetItem(str(created)))

        n = self._table.rowCount()
        self._count_lbl.setText(f"{n} lavo{'ro' if n == 1 else 'ri'}")

    def _filter_table(self, text: str):
        text = text.lower()
        for row in range(self._table.rowCount()):
            match = any(
                text in (self._table.item(row, c).text().lower() if self._table.item(row, c) else "")
                for c in range(self._table.columnCount())
            )
            self._table.setRowHidden(row, not match)

    def _on_sel(self):
        has = bool(self._table.selectedItems())
        self._open_btn.setEnabled(has)
        self._start_btn.setEnabled(has)
        if hasattr(self, "_del_btn"): self._del_btn.setEnabled(has)

    def _get_selected(self) -> dict | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows: return None
        return self._assignments[rows[0].row()] if rows[0].row() < len(self._assignments) else None

    def _start_activity(self):
        a = self._get_selected()
        if not a: return
        st = a.get("status", "pending")
        if st in ("completed", "cancelled"):
            QMessageBox.information(self, "Attività non avviabile",
                f"Il lavoro è già {STATUS_LABELS.get(st, st)} e non può essere avviato.")
            return
        dev = a.get("description") or a.get("destination_name") or "Lavoro"
        if QMessageBox.question(self, "Avvia attività",
            f"Avviare il lavoro <b>{dev}</b>?<br>"
            f"<small>Lo stato verrà impostato a <b>In corso</b> e il programma ti porterà "
            f"al dispositivo/sede per eseguire le verifiche.</small>",
            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            database.update_assignment_status(a["uuid"], "in_progress")
            a["status"] = "in_progress"
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile aggiornare lo stato:\n{e}")
            return
        self.started_assignment = a
        self.accept()

    def _open_detail(self, *_):
        a = self._get_selected()
        if not a: return
        dlg = AssignmentDetailDialog(a, parent=self)
        dlg.exec()
        # Se il dettaglio ha avviato l'attività, propaga al chiamante
        if dlg.started_assignment:
            self.started_assignment = dlg.started_assignment
            self.accept()
            return
        self._load_assignments()

    def _context_menu(self, pos):
        a = self._get_selected()
        if not a: return
        menu = QMenu(self)
        menu.addAction("📂  Apri dettaglio", self._open_detail)
        menu.addSeparator()
        menu.addAction("✏  Cambia stato", self._change_status_quick)
        if self._is_manager:
            menu.addSeparator()
            menu.addAction("🗑  Elimina", self._delete_selected)
        menu.exec(QCursor.pos())

    def _change_status_quick(self):
        a = self._get_selected()
        if not a: return
        dlg = _ChangeStatusDialog(a, parent=self)
        if dlg.exec() == QDialog.Accepted:
            try:
                database.update_assignment_status(a["uuid"], dlg.selected_status)
                self._load_assignments()
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile aggiornare:\n{e}")

    def _delete_selected(self):
        a = self._get_selected()
        if not a: return
        dev = a.get("description") or a.get("destination_name") or "Lavoro"
        if QMessageBox.question(self, "Conferma",
            f"Eliminare il lavoro <b>{dev}</b>?",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                database.delete_assignment(a["uuid"])
                self._load_assignments()
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile eliminare:\n{e}")

    def _open_new(self):
        dlg = BulkAssignDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._load_assignments()


# ─────────────────────────────────────────────────────────────────────────────
#  AssignmentDetailDialog
# ─────────────────────────────────────────────────────────────────────────────

class AssignmentDetailDialog(QDialog):
    """Vista dettagliata di un lavoro assegnato."""

    def __init__(self, assignment: dict, parent=None):
        super().__init__(parent)
        self.a = assignment
        self._is_manager = auth_manager.get_current_role() in ("admin", "moderator")
        self._username   = auth_manager.get_current_username()
        self._changed    = False
        self.started_assignment: dict | None = None  # impostato se il tecnico avvia da qui
        self.setWindowTitle("Dettaglio Lavoro")
        self.setMinimumSize(720, 560)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        a = self.a
        lay = QVBoxLayout(self); lay.setSpacing(0); lay.setContentsMargins(0, 0, 0, 0)

        # Header
        hdr = QFrame(); hdr.setStyleSheet(_HDR)
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20, 14, 20, 14)
        col = QVBoxLayout(); col.setSpacing(3)
        if a.get("device_id"):
            dev = a.get("description") or a.get("model") or "Dispositivo"
            if a.get("serial_number"): dev += f"  —  S/N {a['serial_number']}"
            title = f"🔧  {dev}"
        else:
            title = f"📍  {a.get('destination_name') or 'Sede'}"
        t = QLabel(title); t.setStyleSheet("color:white;font-size:15px;font-weight:bold;")
        cust = a.get("customer_name") or ""; dest = a.get("destination_name") or ""
        sub_txt = f"{cust} / {dest}" if (cust and dest) else cust or dest
        s = QLabel(sub_txt); s.setStyleSheet("color:#93c5fd;font-size:11px;")
        col.addWidget(t); col.addWidget(s)
        hl.addLayout(col); hl.addStretch()

        st = a.get("status", "pending")
        badge = QLabel(STATUS_LABELS.get(st, st))
        badge.setStyleSheet(
            f"QLabel{{{STATUS_BTN_STYLE.get(st,'background:#475569;')}"
            f"color:white;font-weight:bold;font-size:12px;border-radius:6px;padding:5px 12px;}}")
        hl.addWidget(badge)
        lay.addWidget(hdr)

        # Body
        body = QSplitter(Qt.Horizontal)
        body.setHandleWidth(1); body.setChildrenCollapsible(False)

        # Left: info
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_w = QWidget(); ll = QVBoxLayout(left_w)
        ll.setContentsMargins(20, 16, 12, 16); ll.setSpacing(10)

        def _row(icon, label, value, bold=False):
            w = QWidget(); rl = QHBoxLayout(w); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(6)
            lw = QLabel(f"{icon}  {label}:")
            lw.setStyleSheet("color:#64748b;font-size:12px;"); lw.setFixedWidth(120)
            vw = QLabel(str(value) if value else "—")
            vw.setWordWrap(True)
            vw.setStyleSheet(f"font-size:12px;{'font-weight:bold;' if bold else ''}")
            rl.addWidget(lw); rl.addWidget(vw, 1); return w

        ll.addWidget(_row("👤", "Assegnato a",  a.get("assigned_to"),  bold=True))
        ll.addWidget(_row("👤", "Assegnato da", a.get("assigned_by")))
        ll.addWidget(_row("⚡", "Priorità",     PRIORITY_LABELS.get(a.get("priority", "normal"))))
        ll.addWidget(_row("📅", "Scadenza",      a.get("due_date") or "Nessuna"))
        ll.addWidget(_row("🏷", "Stato",         STATUS_LABELS.get(st, st)))
        ll.addWidget(_row("📅", "Creato il",     self._fmt(a.get("created_at"))))
        ll.addWidget(_row("📅", "Aggiornato il", self._fmt(a.get("updated_at"))))
        if a.get("completed_at"):
            ll.addWidget(_row("✅", "Completato il", self._fmt(a.get("completed_at"))))

        ll.addWidget(_sep())
        note_lbl = QLabel("Note:"); note_lbl.setStyleSheet("font-size:12px;color:#64748b;")
        ll.addWidget(note_lbl)
        can_edit = self._is_manager or a.get("assigned_to") == self._username
        self._notes_view = QTextEdit()
        self._notes_view.setText(a.get("notes") or "")
        self._notes_view.setReadOnly(not can_edit)
        self._notes_view.setStyleSheet(
            "border:1px solid #e2e8f0;border-radius:6px;font-size:12px;"
            + ("background:#f8fafc;" if not can_edit else ""))
        self._notes_view.setFixedHeight(110)
        ll.addWidget(self._notes_view)
        ll.addStretch()
        left_scroll.setWidget(left_w)
        body.addWidget(left_scroll)

        # Right: azioni
        right_w = QWidget(); right_w.setMaximumWidth(250); right_w.setMinimumWidth(210)
        rl = QVBoxLayout(right_w); rl.setContentsMargins(12, 16, 20, 16); rl.setSpacing(8)
        rl.addWidget(QLabel("Azioni rapide")).setStyleSheet if False else None
        act_lbl = QLabel("Azioni rapide"); act_lbl.setStyleSheet(_ST)
        rl.addWidget(act_lbl)

        def _action_btn(label, style, fn):
            b = QPushButton(label)
            b.setStyleSheet(style); b.clicked.connect(fn)
            return b

        can_act = self._is_manager or a.get("assigned_to") == self._username

        # Avvia attività — disponibile per pending e in_progress
        if can_act and st in ("pending", "in_progress"):
            rl.addWidget(_action_btn("▶  Avvia Attività",
                "QPushButton{background:#16a34a;color:white;font-weight:bold;padding:10px;"
                "border-radius:6px;font-size:13px;} QPushButton:hover{background:#15803d;}",
                self._launch_activity))
            rl.addWidget(_sep())

        if can_act and st == "pending":
            rl.addWidget(_action_btn("▶  Prendi in carico",
                "QPushButton{background:#d97706;color:white;font-weight:bold;padding:9px;"
                "border-radius:6px;} QPushButton:hover{background:#b45309;}",
                lambda: self._set_status("in_progress")))

        if can_act and st in ("pending", "in_progress"):
            rl.addWidget(_action_btn("✅  Segna completato",
                "QPushButton{background:#16a34a;color:white;font-weight:bold;padding:9px;"
                "border-radius:6px;} QPushButton:hover{background:#15803d;}",
                lambda: self._set_status("completed")))

        if can_act and st not in ("cancelled", "completed"):
            rl.addWidget(_action_btn("❌  Annulla lavoro",
                "QPushButton{background:#e5e7eb;color:#374151;font-weight:bold;padding:9px;"
                "border-radius:6px;} QPushButton:hover{background:#d1d5db;}",
                lambda: self._set_status("cancelled")))

        if self._is_manager:
            rl.addWidget(_action_btn("✏  Cambia stato...",
                "QPushButton{background:#1e3a8a;color:white;font-weight:bold;padding:9px;"
                "border-radius:6px;} QPushButton:hover{background:#1d4ed8;}",
                self._change_status_dialog))

        rl.addWidget(_sep())

        if can_edit:
            rl.addWidget(_action_btn("💾  Salva note",
                "QPushButton{border:1px solid #3b82f6;color:#1d4ed8;font-weight:bold;"
                "padding:8px;border-radius:6px;} QPushButton:hover{background:#eff6ff;}",
                self._save_notes))

        rl.addStretch()

        if self._is_manager:
            rl.addWidget(_sep())
            rl.addWidget(_action_btn("🗑  Elimina lavoro",
                "QPushButton{border:1px solid #fca5a5;color:#dc2626;font-weight:bold;"
                "padding:8px;border-radius:6px;} QPushButton:hover{background:#fef2f2;}",
                self._delete))

        body.addWidget(right_w)
        body.setSizes([480, 240])
        lay.addWidget(body, 1)

        # Footer
        foot = QFrame(); foot.setStyleSheet("background:#f8fafc;border-top:1px solid #e2e8f0;")
        fl = QHBoxLayout(foot); fl.setContentsMargins(16, 10, 16, 10)
        fl.addWidget(QLabel(f"UUID: {a.get('uuid','')[:20]}...").setStyleSheet("color:#94a3b8;font-size:10px;") or QLabel())
        fl.addStretch()
        cb = QPushButton("Chiudi"); cb.setFixedWidth(80); cb.clicked.connect(self.accept)
        fl.addWidget(cb)
        lay.addWidget(foot)

    def _fmt(self, val) -> str:
        if not val: return "—"
        try:
            return datetime.fromisoformat(str(val).replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
        except Exception:
            return str(val)

    def _launch_activity(self):
        """Imposta in_progress e segnala al chiamante di navigare al target."""
        st = self.a.get("status", "pending")
        dev = self.a.get("description") or self.a.get("destination_name") or "Lavoro"
        if QMessageBox.question(self, "Avvia attività",
            f"Avviare il lavoro <b>{dev}</b>?<br>"
            f"<small>Il programma ti porterà al dispositivo/sede corretto per le verifiche.</small>",
            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if st != "in_progress":
            try:
                database.update_assignment_status(self.a["uuid"], "in_progress")
                self.a["status"] = "in_progress"
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile aggiornare lo stato:\n{e}")
                return
        self._changed = True
        self.started_assignment = self.a
        # Accetta direttamente (il genitore intercetterà started_assignment)
        QDialog.accept(self)

    def _set_status(self, new_st: str):
        try:
            database.update_assignment_status(self.a["uuid"], new_st)
            self.a["status"] = new_st
            self._changed = True
            QMessageBox.information(self, "Stato aggiornato",
                f"Lavoro segnato come: {STATUS_LABELS.get(new_st, new_st)}")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile aggiornare:\n{e}")

    def _change_status_dialog(self):
        dlg = _ChangeStatusDialog(self.a, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._set_status(dlg.selected_status)

    def _save_notes(self):
        notes = self._notes_view.toPlainText().strip() or None
        try:
            from datetime import timezone
            now = datetime.now(timezone.utc).isoformat()
            with database.DatabaseConnection() as conn:
                conn.execute(
                    "UPDATE verification_assignments SET notes=?, updated_at=?, is_synced=0, last_modified=? WHERE uuid=?",
                    (notes, now, now, self.a["uuid"])
                )
            self.a["notes"] = notes
            self._changed = True
            QMessageBox.information(self, "Salvato", "Note aggiornate.")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile salvare:\n{e}")

    def _delete(self):
        dev = self.a.get("description") or self.a.get("destination_name") or "Lavoro"
        if QMessageBox.question(self, "Conferma",
            f"Eliminare definitivamente <b>{dev}</b>?",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                database.delete_assignment(self.a["uuid"])
                self._changed = True
                self.accept()
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile eliminare:\n{e}")

    def exec(self):
        result = super().exec()
        return QDialog.Accepted if self._changed else result


# ─────────────────────────────────────────────────────────────────────────────
#  _ChangeStatusDialog
# ─────────────────────────────────────────────────────────────────────────────

class _ChangeStatusDialog(QDialog):
    def __init__(self, assignment: dict, parent=None):
        super().__init__(parent)
        self.assignment = assignment
        self.selected_status = assignment.get("status", "pending")
        self.setWindowTitle("Cambia Stato Lavoro")
        self.setFixedSize(380, 220)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self); lay.setSpacing(14); lay.setContentsMargins(20, 20, 20, 20)
        if self.assignment.get("device_id"):
            dev = self.assignment.get("description") or self.assignment.get("model") or "Dispositivo"
        else:
            dev = f"Sede: {self.assignment.get('destination_name','')}"
        lbl = QLabel(f"<b>{dev}</b><br><small>Tecnico: {self.assignment.get('assigned_to','')}</small>")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("padding:8px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;")
        lay.addWidget(lbl)
        form = QFormLayout()
        self._combo = QComboBox()
        for k, v in STATUS_LABELS.items():
            self._combo.addItem(v, k)
            if k == self.assignment.get("status"):
                self._combo.setCurrentIndex(self._combo.count() - 1)
        form.addRow("Nuovo stato:", self._combo)
        lay.addLayout(form)
        br = QHBoxLayout()
        ok = QPushButton("✔  Conferma")
        ok.setStyleSheet("QPushButton{background:#1e3a8a;color:white;font-weight:bold;"
                         "padding:6px 20px;border-radius:5px;}")
        ok.clicked.connect(self._accept)
        cn = QPushButton("Annulla"); cn.clicked.connect(self.reject)
        br.addStretch(); br.addWidget(cn); br.addWidget(ok)
        lay.addLayout(br)

    def _accept(self):
        self.selected_status = self._combo.currentData()
        self.accept()
