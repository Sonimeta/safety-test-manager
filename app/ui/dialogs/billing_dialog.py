# app/ui/dialogs/billing_dialog.py
"""Report di fatturazione: statistiche di verifiche eseguite per cliente/destinazione
in un intervallo di date (apparecchi verificati, esiti, tempo impiegato)."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QPushButton, QGroupBox, QDateEdit, QTableWidget,
                               QTableWidgetItem, QHeaderView, QMessageBox, QGridLayout,
                               QSizePolicy, QFileDialog, QApplication)
from PySide6.QtCore import Qt, QDate
import qtawesome as qta
import pandas as pd
import os
import logging

from app import config, services


def _format_duration(total_seconds: int) -> str:
    total_seconds = int(total_seconds or 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _seconds = divmod(remainder, 60)
    decimal_hours = round(total_seconds / 3600.0, 2)
    return f"{hours}h {minutes:02d}m ({decimal_hours:.2f} ore)"


class BillingReportDialog(QDialog):
    """Schermata per generare il report di fatturazione per cliente/destinazione."""

    ESITO_ORDER = ["CONFORME", "CONFORME CON ANNOTAZIONE", "NON CONFORME", "NON VERIFICATO"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("billingReportDialog")
        self.setWindowTitle("Report Fatturazione")
        self.setStyleSheet(config.get_current_stylesheet())
        self.setMinimumSize(1000, 700)

        self._kpi_value_labels = {}
        self.current_summary = None
        self.current_filters = None

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        title = QLabel("<h2>🧾 Report Fatturazione</h2>")
        main_layout.addWidget(title)

        main_layout.addWidget(self._build_filters_group())
        main_layout.addWidget(self._build_kpi_group())

        tables_layout = QHBoxLayout()
        tables_layout.addWidget(self._build_device_type_group(), 1)
        tables_layout.addWidget(self._build_outcome_group("Verifiche Elettriche", "electrical"), 1)
        tables_layout.addWidget(self._build_outcome_group("Verifiche Funzionali", "functional"), 1)
        main_layout.addLayout(tables_layout, 1)

        main_layout.addWidget(self._build_cq_ecografi_group(), 1)

        self._load_customers()

    # ------------------------------------------------------------------ UI --

    def _build_filters_group(self) -> QGroupBox:
        group = QGroupBox("Filtri")
        layout = QHBoxLayout(group)

        layout.addWidget(QLabel("Cliente:"))
        self.customer_combo = QComboBox()
        self.customer_combo.setMinimumWidth(220)
        self.customer_combo.currentIndexChanged.connect(self._on_customer_changed)
        layout.addWidget(self.customer_combo)

        layout.addWidget(QLabel("Destinazione:"))
        self.destination_combo = QComboBox()
        self.destination_combo.setMinimumWidth(220)
        layout.addWidget(self.destination_combo)

        layout.addWidget(QLabel("Dal:"))
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("dd/MM/yyyy")
        today = QDate.currentDate()
        self.start_date_edit.setDate(QDate(today.year(), today.month(), 1))
        layout.addWidget(self.start_date_edit)

        layout.addWidget(QLabel("Al:"))
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.end_date_edit.setDate(today)
        layout.addWidget(self.end_date_edit)

        self.generate_btn = QPushButton(qta.icon('fa5s.calculator'), " Genera Report")
        self.generate_btn.setObjectName("autoButton")
        self.generate_btn.clicked.connect(self._generate_report)
        layout.addWidget(self.generate_btn)

        self.export_btn = QPushButton(qta.icon('fa5s.file-excel'), " Esporta Excel")
        self.export_btn.setObjectName("exportButton")
        self.export_btn.clicked.connect(self._export_to_excel)
        self.export_btn.setEnabled(False)
        layout.addWidget(self.export_btn)

        layout.addStretch()
        return group

    def _build_kpi_group(self) -> QGroupBox:
        group = QGroupBox("Riepilogo")
        layout = QGridLayout(group)
        layout.setSpacing(10)

        kpis = [
            ("totale_apparecchi", "Apparecchi Verificati", "#2563eb"),
            ("verifiche_elettriche", "Verifiche Elettriche", "#0d9488"),
            ("verifiche_funzionali", "Verifiche Funzionali", "#d97706"),
            ("totale_sonde_controllate", "Sonde Controllate (CQ)", "#0284c7"),
            ("tempo_impiegato", "Tempo Impiegato", "#7c3aed"),
        ]
        for col, (key, label, color) in enumerate(kpis):
            layout.addWidget(self._create_kpi_card(key, label, color), 0, col)
        return group

    def _create_kpi_card(self, key: str, title: str, color: str) -> QGroupBox:
        card = QGroupBox()
        card.setStyleSheet(
            f"QGroupBox {{ border: 2px solid {color}; border-radius: 10px; padding: 8px; }}"
        )
        layout = QVBoxLayout(card)
        layout.setSpacing(2)

        title_label = QLabel(title.upper())
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 11px; font-weight: 600; letter-spacing: 0.5px;")
        layout.addWidget(title_label)

        value_label = QLabel("--")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {color};")
        layout.addWidget(value_label)

        self._kpi_value_labels[key] = value_label
        return card

    def _build_device_type_group(self) -> QGroupBox:
        group = QGroupBox("Apparecchi e Verifiche per Tipologia")
        layout = QVBoxLayout(group)
        self.device_type_table = QTableWidget(0, 4)
        self.device_type_table.setHorizontalHeaderLabels(["Tipologia", "Apparecchi", "V. Elettriche", "V. Funzionali"])
        self.device_type_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.device_type_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.device_type_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.device_type_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.device_type_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.device_type_table.verticalHeader().setVisible(False)
        layout.addWidget(self.device_type_table)
        return group

    def _build_cq_ecografi_group(self) -> QGroupBox:
        group = QGroupBox("Controllo Qualità Sonde (Sonde Controllate per Ecografo)")
        layout = QVBoxLayout(group)
        self.cq_ecografi_table = QTableWidget(0, 7)
        self.cq_ecografi_table.setHorizontalHeaderLabels([
            "Inv. AMS", "Inv. Cliente", "Modello", "Matricola", "Reparto", "N° Controlli CQ", "Sonde Controllate"
        ])
        self.cq_ecografi_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.cq_ecografi_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.cq_ecografi_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.cq_ecografi_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.cq_ecografi_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.cq_ecografi_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.cq_ecografi_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.cq_ecografi_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cq_ecografi_table.verticalHeader().setVisible(False)
        layout.addWidget(self.cq_ecografi_table)
        return group

    def _build_outcome_group(self, title: str, key: str) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Esito", "Quantità"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        layout.addWidget(table)
        setattr(self, f"{key}_outcome_table", table)
        return group

    # -------------------------------------------------------------- DATI --

    def _load_customers(self):
        self.customer_combo.blockSignals(True)
        self.customer_combo.clear()
        self.customer_combo.addItem("Seleziona un cliente...", None)
        for customer in services.get_all_customers():
            self.customer_combo.addItem(customer["name"], customer["id"])
        self.customer_combo.blockSignals(False)
        self._load_destinations(None)

    def _on_customer_changed(self):
        customer_id = self.customer_combo.currentData()
        self._load_destinations(customer_id)
        self.export_btn.setEnabled(False)
        self.current_summary = None
        self.current_filters = None

    def _load_destinations(self, customer_id):
        self.destination_combo.clear()
        self.destination_combo.addItem("Tutte le destinazioni", None)
        if not customer_id:
            return
        for dest in services.get_destinations_for_customer(customer_id):
            self.destination_combo.addItem(dest["name"], dest["id"])

    def _generate_report(self):
        customer_id = self.customer_combo.currentData()
        if not customer_id:
            QMessageBox.warning(self, "Cliente mancante", "Seleziona un cliente per generare il report.")
            return

        destination_id = self.destination_combo.currentData()
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")

        if self.start_date_edit.date() > self.end_date_edit.date():
            QMessageBox.warning(self, "Intervallo non valido", "La data di inizio deve precedere la data di fine.")
            return

        try:
            summary = services.get_billing_summary(customer_id, destination_id, start_date, end_date)
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile calcolare le statistiche:\n{e}")
            return

        self._display_summary(summary)
        self.current_summary = summary
        self.current_filters = {
            "customer_id": customer_id,
            "customer_name": self.customer_combo.currentText(),
            "destination_id": destination_id,
            "destination_name": self.destination_combo.currentText(),
            "start_date": start_date,
            "end_date": end_date
        }
        self.export_btn.setEnabled(True)

    def _display_summary(self, summary: dict):
        functional = summary.get("verifiche_funzionali", {})
        electrical = summary.get("verifiche_elettriche", {})

        self._kpi_value_labels["totale_apparecchi"].setText(str(summary.get("totale_apparecchi", 0)))
        self._kpi_value_labels["verifiche_elettriche"].setText(str(electrical.get("totale", 0)))
        self._kpi_value_labels["verifiche_funzionali"].setText(str(functional.get("totale", 0)))
        self._kpi_value_labels["totale_sonde_controllate"].setText(str(summary.get("totale_sonde_controllate", 0)))
        self._kpi_value_labels["tempo_impiegato"].setText(_format_duration(summary.get("tempo_totale_secondi", 0)))

        self._fill_device_type_table(
            summary.get("apparecchi_per_tipologia", {}),
            summary.get("verifiche_elettriche_per_tipologia", {}),
            summary.get("verifiche_funzionali_per_tipologia", {})
        )
        self._fill_outcome_table(self.electrical_outcome_table, electrical)
        self._fill_outcome_table(self.functional_outcome_table, functional)
        self._fill_cq_ecografi_table(summary.get("ecografi_cq", []))

    def _fill_cq_ecografi_table(self, ecografi_cq: list):
        self.cq_ecografi_table.setRowCount(0)
        tot_checks = 0
        tot_probes = 0
        for eco in ecografi_cq:
            row = self.cq_ecografi_table.rowCount()
            self.cq_ecografi_table.insertRow(row)

            ams_item = QTableWidgetItem(str(eco.get("ams_inventory") or "N/D"))
            ams_item.setTextAlignment(Qt.AlignCenter)
            self.cq_ecografi_table.setItem(row, 0, ams_item)

            cust_item = QTableWidgetItem(str(eco.get("customer_inventory") or "N/D"))
            cust_item.setTextAlignment(Qt.AlignCenter)
            self.cq_ecografi_table.setItem(row, 1, cust_item)

            self.cq_ecografi_table.setItem(row, 2, QTableWidgetItem(str(eco.get("model") or "N/D")))

            sn_item = QTableWidgetItem(str(eco.get("serial_number") or "N/D"))
            sn_item.setTextAlignment(Qt.AlignCenter)
            self.cq_ecografi_table.setItem(row, 3, sn_item)

            self.cq_ecografi_table.setItem(row, 4, QTableWidgetItem(str(eco.get("department") or "N/D")))

            checks_item = QTableWidgetItem(str(eco.get("check_count", 0)))
            checks_item.setTextAlignment(Qt.AlignCenter)
            self.cq_ecografi_table.setItem(row, 5, checks_item)

            probes_item = QTableWidgetItem(str(eco.get("probe_count", 0)))
            probes_item.setTextAlignment(Qt.AlignCenter)
            probes_font = probes_item.font()
            probes_font.setBold(True)
            probes_item.setFont(probes_font)
            self.cq_ecografi_table.setItem(row, 6, probes_item)

            tot_checks += eco.get("check_count", 0)
            tot_probes += eco.get("probe_count", 0)

        if ecografi_cq:
            row = self.cq_ecografi_table.rowCount()
            self.cq_ecografi_table.insertRow(row)
            tot_label = QTableWidgetItem("Totale")
            font = tot_label.font()
            font.setBold(True)
            tot_label.setFont(font)
            self.cq_ecografi_table.setItem(row, 0, tot_label)

            tot_c_item = QTableWidgetItem(str(tot_checks))
            tot_c_item.setFont(font)
            tot_c_item.setTextAlignment(Qt.AlignCenter)
            self.cq_ecografi_table.setItem(row, 5, tot_c_item)

            tot_p_item = QTableWidgetItem(str(tot_probes))
            tot_p_item.setFont(font)
            tot_p_item.setTextAlignment(Qt.AlignCenter)
            self.cq_ecografi_table.setItem(row, 6, tot_p_item)

    def _fill_device_type_table(self, devices_by_type: dict,
                                elec_by_type: dict, func_by_type: dict):
        self.device_type_table.setRowCount(0)
        # Unisci tutte le tipologie presenti in qualsiasi dizionario
        all_types = sorted(set(list(devices_by_type.keys()) +
                               list(elec_by_type.keys()) +
                               list(func_by_type.keys())))
        for tipo in all_types:
            row = self.device_type_table.rowCount()
            self.device_type_table.insertRow(row)
            self.device_type_table.setItem(row, 0, QTableWidgetItem(tipo))

            app_item = QTableWidgetItem(str(devices_by_type.get(tipo, 0)))
            app_item.setTextAlignment(Qt.AlignCenter)
            self.device_type_table.setItem(row, 1, app_item)

            elec_item = QTableWidgetItem(str(elec_by_type.get(tipo, 0)))
            elec_item.setTextAlignment(Qt.AlignCenter)
            self.device_type_table.setItem(row, 2, elec_item)

            func_item = QTableWidgetItem(str(func_by_type.get(tipo, 0)))
            func_item.setTextAlignment(Qt.AlignCenter)
            self.device_type_table.setItem(row, 3, func_item)

    def _fill_outcome_table(self, table: QTableWidget, stats: dict):
        table.setRowCount(0)
        per_esito = stats.get("per_esito", {})
        for esito in self.ESITO_ORDER:
            count = per_esito.get(esito, 0)
            if esito == "NON VERIFICATO" and count == 0:
                continue
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(esito))
            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 1, count_item)

        row = table.rowCount()
        table.insertRow(row)
        total_label = QTableWidgetItem("Totale")
        font = total_label.font()
        font.setBold(True)
        total_label.setFont(font)
        table.setItem(row, 0, total_label)
        total_value = QTableWidgetItem(str(stats.get("totale", 0)))
        total_value.setFont(font)
        total_value.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 1, total_value)

    def _export_to_excel(self):
        if not self.current_summary or not self.current_filters:
            QMessageBox.warning(self, "Nessun dato", "Genera prima un report per poterlo esportare.")
            return

        import re
        cust_clean = re.sub(r'[^\w\-]', '_', self.current_filters["customer_name"])
        dest_clean = re.sub(r'[^\w\-]', '_', self.current_filters["destination_name"])
        default_filename = f"Report_Fatturazione_{cust_clean}_{dest_clean}_{self.current_filters['start_date']}_al_{self.current_filters['end_date']}.xlsx"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Esporta Report Fatturazione",
            os.path.join(os.path.expanduser("~"), "Desktop", default_filename),
            "Excel Files (*.xlsx)"
        )

        if not file_path:
            return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)

            customer_id = self.current_filters["customer_id"]
            destination_id = self.current_filters["destination_id"]
            start_date = self.current_filters["start_date"]
            end_date = self.current_filters["end_date"]

            # Recupera i dettagli delle verifiche
            if destination_id:
                elec_details = services.get_verifications_for_destination_by_date_range(destination_id, start_date, end_date)
                func_details = services.get_functional_verifications_for_destination_by_date_range(destination_id, start_date, end_date)
            else:
                elec_details = services.get_verifications_for_customer_by_date_range(customer_id, start_date, end_date)
                func_details = services.get_functional_verifications_for_customer_by_date_range(customer_id, start_date, end_date)

            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                # --- FOGLIO 1: RIEPILOGO ---
                meta_data = [
                    ["REPORT DI FATTURAZIONE - VERIFICHE DI SICUREZZA", ""],
                    ["Cliente:", self.current_filters["customer_name"]],
                    ["Destinazione:", self.current_filters["destination_name"]],
                    ["Periodo:", f"Dal {self.current_filters['start_date']} Al {self.current_filters['end_date']}"],
                    ["Data Esportazione:", QDate.currentDate().toString("dd/MM/yyyy")],
                    ["", ""],
                ]

                kpi_data = [
                    ["Riepilogo Generali", ""],
                    ["Apparecchi Verificati Totali", self.current_summary.get("totale_apparecchi", 0)],
                    ["Verifiche Elettriche Totali", self.current_summary.get("verifiche_elettriche", {}).get("totale", 0)],
                    ["Verifiche Funzionali Totali", self.current_summary.get("verifiche_funzionali", {}).get("totale", 0)],
                    ["Sonde Controllate (CQ) Totali", self.current_summary.get("totale_sonde_controllate", 0)],
                    ["Tempo Impiegato Totale (Ore Decimali)", round(self.current_summary.get("tempo_totale_secondi", 0) / 3600.0, 2)],
                    ["Tempo Impiegato Formattato", _format_duration(self.current_summary.get("tempo_totale_secondi", 0))],
                    ["", ""],
                ]

                apparecchi_per_tipo = self.current_summary.get("apparecchi_per_tipologia", {})
                elec_per_tipo = self.current_summary.get("verifiche_elettriche_per_tipologia", {})
                func_per_tipo = self.current_summary.get("verifiche_funzionali_per_tipologia", {})
                all_types = sorted(set(list(apparecchi_per_tipo.keys()) +
                                       list(elec_per_tipo.keys()) +
                                       list(func_per_tipo.keys())))

                tipologia_headers = ["Tipologia Apparecchio", "Apparecchi", "V. Elettriche", "V. Funzionali"]
                tipologia_rows = []
                for tipo in all_types:
                    tipologia_rows.append([
                        tipo,
                        apparecchi_per_tipo.get(tipo, 0),
                        elec_per_tipo.get(tipo, 0),
                        func_per_tipo.get(tipo, 0)
                    ])

                elettriche_headers = ["Esito Verifica Elettrica", "Quantità"]
                elettriche_rows = []
                el_stats = self.current_summary.get("verifiche_elettriche", {})
                for esito in self.ESITO_ORDER:
                    count = el_stats.get("per_esito", {}).get(esito, 0)
                    if esito == "NON VERIFICATO" and count == 0:
                        continue
                    elettriche_rows.append([esito, count])
                elettriche_rows.append(["Totale", el_stats.get("totale", 0)])

                funzionali_headers = ["Esito Verifica Funzionale", "Quantità"]
                funzionali_rows = []
                fun_stats = self.current_summary.get("verifiche_funzionali", {})
                for esito in self.ESITO_ORDER:
                    count = fun_stats.get("per_esito", {}).get(esito, 0)
                    if esito == "NON VERIFICATO" and count == 0:
                        continue
                    funzionali_rows.append([esito, count])
                funzionali_rows.append(["Totale", fun_stats.get("totale", 0)])

                row_idx = 0

                # Scrittura metadati
                df_meta = pd.DataFrame(meta_data)
                df_meta.to_excel(writer, sheet_name='Riepilogo', startrow=row_idx, index=False, header=False)
                row_idx += len(meta_data)

                # Scrittura KPI
                df_kpi = pd.DataFrame(kpi_data)
                df_kpi.to_excel(writer, sheet_name='Riepilogo', startrow=row_idx, index=False, header=False)
                row_idx += len(kpi_data)

                # Tabella Apparecchi per tipologia
                pd.DataFrame([["DISTRIBUZIONE PER TIPOLOGIA APPARECCHIO", ""]]).to_excel(writer, sheet_name='Riepilogo', startrow=row_idx, index=False, header=False)
                row_idx += 1
                df_tipologia = pd.DataFrame(tipologia_rows, columns=tipologia_headers)
                df_tipologia.to_excel(writer, sheet_name='Riepilogo', startrow=row_idx, index=False)
                row_idx += len(tipologia_rows) + 2

                # Tabella Esiti Elettrici
                pd.DataFrame([["RIEPILOGO VERIFICHE ELETTRICHE", ""]]).to_excel(writer, sheet_name='Riepilogo', startrow=row_idx, index=False, header=False)
                row_idx += 1
                df_elec = pd.DataFrame(elettriche_rows, columns=elettriche_headers)
                df_elec.to_excel(writer, sheet_name='Riepilogo', startrow=row_idx, index=False)
                row_idx += len(elettriche_rows) + 2

                # Tabella Esiti Funzionali
                pd.DataFrame([["RIEPILOGO VERIFICHE FUNZIONALI", ""]]).to_excel(writer, sheet_name='Riepilogo', startrow=row_idx, index=False, header=False)
                row_idx += 1
                df_func = pd.DataFrame(funzionali_rows, columns=funzionali_headers)
                df_func.to_excel(writer, sheet_name='Riepilogo', startrow=row_idx, index=False)
                row_idx += len(funzionali_rows) + 2

                # Tabella Sonde Controllate per Ecografo
                ecografi_cq = self.current_summary.get("ecografi_cq", [])
                if ecografi_cq:
                    cq_headers = ["Inv. AMS", "Inv. Cliente", "Denominazione", "Modello", "Matricola", "Reparto", "N° Controlli CQ", "N° Sonde Controllate"]
                    cq_rows = []
                    for eco in ecografi_cq:
                        cq_rows.append([
                            eco.get("ams_inventory", ""),
                            eco.get("customer_inventory", ""),
                            eco.get("description", ""),
                            eco.get("model", ""),
                            eco.get("serial_number", ""),
                            eco.get("department", ""),
                            eco.get("check_count", 0),
                            eco.get("probe_count", 0)
                        ])
                    pd.DataFrame([["SONDE CONTROLLATE PER ECOGRAFO (CQ)", ""]]).to_excel(writer, sheet_name='Riepilogo', startrow=row_idx, index=False, header=False)
                    row_idx += 1
                    df_cq_summary = pd.DataFrame(cq_rows, columns=cq_headers)
                    df_cq_summary.to_excel(writer, sheet_name='Riepilogo', startrow=row_idx, index=False)

                # --- FOGLIO 2: DETTAGLIO VERIFICHE ELETTRICHE ---
                if elec_details:
                    elec_list = []
                    for row in elec_details:
                        r_dict = dict(row)
                        sec = r_dict.get("duration_seconds") or 0
                        elec_list.append({
                            "Codice Verifica": r_dict.get("verification_code", ""),
                            "Data": r_dict.get("verification_date", ""),
                            "Destinazione": r_dict.get("destination_name", ""),
                            "Inventario AMS": r_dict.get("ams_inventory", ""),
                            "Inventario Cliente": r_dict.get("customer_inventory", ""),
                            "Denominazione": r_dict.get("description", ""),
                            "Produttore": r_dict.get("manufacturer", ""),
                            "Modello": r_dict.get("model", ""),
                            "Matricola (S/N)": r_dict.get("serial_number", ""),
                            "Reparto": r_dict.get("department", ""),
                            "Profilo Applicato": r_dict.get("profile_name", ""),
                            "Esito": r_dict.get("overall_status", ""),
                            "Tecnico": r_dict.get("technician_name", ""),
                            "Durata": _format_duration(sec),
                            "Durata (Ore Decimali)": round(sec / 3600.0, 2)
                        })
                    df_elec_det = pd.DataFrame(elec_list)
                    df_elec_det.to_excel(writer, sheet_name='Dettaglio Verifiche Elettriche', index=False)

                # --- FOGLIO 3: DETTAGLIO VERIFICHE FUNZIONALI ---
                if func_details:
                    func_list = []
                    for row in func_details:
                        r_dict = dict(row)
                        sec = r_dict.get("duration_seconds") or 0
                        func_list.append({
                            "Codice Verifica": r_dict.get("verification_code", ""),
                            "Data": r_dict.get("verification_date", ""),
                            "Destinazione": r_dict.get("destination_name", ""),
                            "Inventario AMS": r_dict.get("ams_inventory", ""),
                            "Inventario Cliente": r_dict.get("customer_inventory", ""),
                            "Denominazione": r_dict.get("description", ""),
                            "Produttore": r_dict.get("manufacturer", ""),
                            "Modello": r_dict.get("model", ""),
                            "Matricola (S/N)": r_dict.get("serial_number", ""),
                            "Reparto": r_dict.get("department", ""),
                            "Esito": r_dict.get("overall_status", ""),
                            "Tecnico": r_dict.get("technician_name", ""),
                            "Note": r_dict.get("notes", ""),
                            "Durata": _format_duration(sec),
                            "Durata (Ore Decimali)": round(sec / 3600.0, 2)
                        })
                    df_func_det = pd.DataFrame(func_list)
                    df_func_det.to_excel(writer, sheet_name='Dettaglio Verifiche Funzionali', index=False)

                # --- FOGLIO 4: DETTAGLIO CQ SONDE ---
                import database
                if destination_id:
                    cq_details = database.get_ecografo_quality_checks_by_date_range(start_date, end_date, destination_id=destination_id)
                else:
                    cq_details = database.get_ecografo_quality_checks_by_date_range(start_date, end_date, customer_id=customer_id)

                if cq_details:
                    cq_list = []
                    for row in cq_details:
                        r_dict = dict(row)
                        check_obj = database.get_ecografo_quality_check(r_dict.get("id"))
                        p_count = len(check_obj.probes) if check_obj and check_obj.probes else 0
                        cq_list.append({
                            "Codice Controllo": r_dict.get("verification_code", ""),
                            "Data": r_dict.get("verification_date", ""),
                            "Destinazione": r_dict.get("destination_name", ""),
                            "Inventario AMS": r_dict.get("ams_inventory", ""),
                            "Inventario Cliente": r_dict.get("customer_inventory", ""),
                            "Denominazione": r_dict.get("description", ""),
                            "Produttore": r_dict.get("manufacturer", ""),
                            "Modello": r_dict.get("model", ""),
                            "Matricola (S/N)": r_dict.get("serial_number", ""),
                            "Reparto": r_dict.get("department", ""),
                            "Giudizio Complessivo": r_dict.get("overall_judgment", ""),
                            "N° Sonde Controllate": p_count,
                            "Tecnico": r_dict.get("technician_name", ""),
                        })
                    df_cq_det = pd.DataFrame(cq_list)
                    df_cq_det.to_excel(writer, sheet_name='Dettaglio CQ Sonde', index=False)

                # Regola la larghezza delle colonne
                for sheet_name in writer.sheets:
                    worksheet = writer.sheets[sheet_name]
                    for column in worksheet.columns:
                        max_length = 0
                        column_letter = column[0].column_letter
                        for cell in column:
                            try:
                                if cell.value:
                                    max_length = max(max_length, len(str(cell.value)))
                            except Exception:
                                pass
                        adjusted_width = min(max_length + 3, 50)
                        worksheet.column_dimensions[column_letter].width = max(adjusted_width, 10)

            QApplication.restoreOverrideCursor()
            QMessageBox.information(
                self,
                "Esportazione Completata",
                f"Report di fatturazione esportato con successo in:\n{file_path}"
            )

        except Exception as e:
            QApplication.restoreOverrideCursor()
            logging.error(f"Errore durante l'esportazione Excel del report di fatturazione: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Errore Esportazione",
                f"Impossibile esportare il report:\n{str(e)}"
            )
