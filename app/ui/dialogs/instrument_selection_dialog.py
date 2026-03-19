"""
Dialog per selezionare gli strumenti effettivamente usati durante una verifica funzionale.
"""
from datetime import date, datetime

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QPushButton,
)

from app import services


class UsedInstrumentsSelectionDialog(QDialog):
    """Dialog per selezionare quali strumenti sono stati effettivamente usati durante la verifica."""
    
    def __init__(self, available_instrument_ids: list, preselected_ids: list | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleziona Strumenti Usati")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)
        self.preselected_ids = preselected_ids or []
        
        layout = QVBoxLayout(self)
        
        info_label = QLabel(
            "Seleziona gli strumenti che hai effettivamente utilizzato durante questa verifica (clicca sul nome):"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        filters_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Cerca per nome o matricola...")
        self.calibration_filter_combo = QComboBox()
        self.calibration_filter_combo.addItem("Tutti", "all")
        self.calibration_filter_combo.addItem("Solo calibrazione valida", "valid")
        self.calibration_filter_combo.addItem("Solo calibrazione scaduta", "expired")
        self.reuse_last_button = QPushButton("Riusa ultima selezione")
        filters_layout.addWidget(self.search_edit, 1)
        filters_layout.addWidget(self.calibration_filter_combo)
        filters_layout.addWidget(self.reuse_last_button)
        layout.addLayout(filters_layout)
        
        self.instruments_list = QListWidget()
        self.instruments_list.setSelectionMode(QListWidget.MultiSelection)

        # Normalizza gli ID disponibili (int + fallback stringa)
        allowed_ids_int = set()
        allowed_ids_str = set()
        for raw_id in (available_instrument_ids or []):
            if raw_id is None:
                continue
            allowed_ids_str.add(str(raw_id))
            try:
                allowed_ids_int.add(int(raw_id))
            except (TypeError, ValueError):
                pass
        
        # Carica gli strumenti disponibili.
        # Usiamo sempre anche la lista completa per coprire profili legacy o strumenti
        # salvati con tipo diverso da "functional".
        functional_instruments = services.database.get_all_instruments('functional') or []
        all_instruments_full = services.database.get_all_instruments() or []

        instruments_by_id = {}
        for inst_row in all_instruments_full:
            inst = dict(inst_row)
            inst_id = inst.get('id')
            if inst_id is not None:
                instruments_by_id[inst_id] = inst
        # Mantieni eventuali strumenti functional non presenti nella query full
        for inst_row in functional_instruments:
            inst = dict(inst_row)
            inst_id = inst.get('id')
            if inst_id is not None and inst_id not in instruments_by_id:
                instruments_by_id[inst_id] = inst
        
        self._items_by_id = {}
        for instrument in instruments_by_id.values():
            inst_id = instrument.get('id')
            if (inst_id in allowed_ids_int) or (str(inst_id) in allowed_ids_str):
                display_text = f"{instrument.get('instrument_name', 'N/A')} (S/N: {instrument.get('serial_number', 'N/A')})"
                cal_date = instrument.get('calibration_date')
                if cal_date:
                    display_text += f" - Cal: {cal_date}"
                item = QListWidgetItem(display_text)
                item.setData(Qt.UserRole, inst_id)
                if self._is_calibration_expired(cal_date):
                    item.setToolTip("Calibrazione scaduta")
                    item.setForeground(Qt.darkYellow)
                self.instruments_list.addItem(item)
                self._items_by_id[inst_id] = item

        # Preselezione iniziale
        self._apply_preselection(self.preselected_ids)

        self.search_edit.textChanged.connect(self._apply_filters)
        self.calibration_filter_combo.currentIndexChanged.connect(self._apply_filters)
        self.reuse_last_button.clicked.connect(self._reuse_last_selection)
        self._apply_filters()
        
        layout.addWidget(self.instruments_list)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _parse_date(self, value):
        if not value:
            return None
        value = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except Exception:
                continue
        return None

    def _is_calibration_expired(self, value) -> bool:
        parsed = self._parse_date(value)
        if not parsed:
            return False
        try:
            expiry_date = parsed.replace(year=parsed.year + 1)
        except ValueError:
            # Gestione 29 febbraio -> 28 febbraio anno successivo
            expiry_date = parsed.replace(month=2, day=28, year=parsed.year + 1)
        return expiry_date < date.today()

    def _apply_preselection(self, ids: list):
        selected = set()
        for raw_id in ids or []:
            try:
                selected.add(int(raw_id))
            except (TypeError, ValueError):
                continue

        for inst_id, item in self._items_by_id.items():
            item.setSelected(inst_id in selected)

    def _reuse_last_selection(self):
        # Riapplica la pre-selezione ricevuta dal chiamante (tipicamente ultimi strumenti usati)
        self._apply_preselection(self.preselected_ids)

    def _apply_filters(self):
        search = self.search_edit.text().strip().lower()
        mode = self.calibration_filter_combo.currentData()
        for i in range(self.instruments_list.count()):
            item = self.instruments_list.item(i)
            text = item.text().lower()
            matches_search = not search or search in text

            hide_for_cal = False
            if mode in {"valid", "expired"}:
                inst_id = item.data(Qt.UserRole)
                is_expired = False
                if inst_id in self._items_by_id:
                    # Recupero dal testo per non dipendere da strutture esterne
                    is_expired = "calibrazione scaduta" in (item.toolTip() or "").lower()
                if mode == "valid" and is_expired:
                    hide_for_cal = True
                if mode == "expired" and not is_expired:
                    hide_for_cal = True

            item.setHidden((not matches_search) or hide_for_cal)

    def get_selected_instrument_ids(self) -> list[int]:
        ids = []
        for item in self.instruments_list.selectedItems():
            inst_id = item.data(Qt.UserRole)
            try:
                ids.append(int(inst_id))
            except (TypeError, ValueError):
                continue
        return ids
    
    def get_selected_instruments(self) -> list:
        """Restituisce una lista di dizionari con i dati degli strumenti selezionati."""
        selected_instruments = []
        all_instruments = services.database.get_all_instruments()
        instruments_dict = {dict(inst)['id']: dict(inst) for inst in all_instruments}

        for item in self.instruments_list.selectedItems():
            inst_id = item.data(Qt.UserRole)
            if inst_id in instruments_dict:
                instrument = instruments_dict[inst_id]
                settings = QSettings("ELSON META", "SafetyTester")
                global_com_port = settings.value("global_com_port", "COM1")
                selected_instruments.append({
                    "instrument": instrument.get('instrument_name'),
                    "serial": instrument.get('serial_number'),
                    "version": instrument.get('fw_version'),
                    "cal_date": instrument.get('calibration_date'),
                    "com_port": global_com_port,
                    "id": inst_id
                })
        
        return selected_instruments

