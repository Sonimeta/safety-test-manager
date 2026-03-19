# app/ui/dialogs/stats_dashboard_dialog.py
from datetime import datetime, date, timedelta
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QSpinBox, QLabel, QWidget, 
                               QSizePolicy, QGroupBox, QGridLayout, QPushButton, QComboBox, QTabWidget,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
                               QMessageBox, QApplication, QFormLayout, QListWidget, QListWidgetItem, QStyle)
from PySide6.QtCharts import (QChart, QChartView, QBarSet, QPercentBarSeries, QBarCategoryAxis,
                              QPieSeries, QPieSlice, QLineSeries, QValueAxis, QBarSeries)
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtCore import Qt, QDate

from app import services, config
import qtawesome as qta
import logging
import pandas as pd
import os

class StatsDashboardDialog(QDialog):
    """
    Dashboard avanzata per visualizzare le statistiche delle verifiche.
    
    Funzionalità:
    - KPI generali (totali, conformità, trend)
    - Grafico verifiche per mese
    - Grafico conformità (torta)
    - Grafico trend annuale
    - Top clienti/tecnici
    - Esportazione dati
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statsDashboardDialog")
        self.setWindowTitle("Dashboard Statistiche Verifiche")
        # Applica il tema corrente
        self.setStyleSheet(config.get_current_stylesheet())
        
        # Imposta dimensione minima e poi massimizza
        self.setMinimumSize(1200, 800)

        # Layout principale
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        # Header con controlli
        header = self._create_header()
        main_layout.addLayout(header)

        # Tabs per organizzare le sezioni
        self.tabs = QTabWidget()
        self.tabs.setObjectName("statsTabs")
        
        # Tab 1: Panoramica
        overview_tab = self._create_overview_tab()
        self.tabs.addTab(overview_tab, qta.icon('fa5s.chart-line'), " Panoramica")
        
        # Tab 2: Grafici Dettagliati
        charts_tab = self._create_charts_tab()
        self.tabs.addTab(charts_tab, qta.icon('fa5s.chart-bar'), " Grafici")
        
        # Tab 3: Classifiche
        rankings_tab = self._create_rankings_tab()
        self.tabs.addTab(rankings_tab, qta.icon('fa5s.trophy'), " Statistiche")
        
        # Tab 4: Dashboard Operativa (ex ControlPanel)
        dashboard_tab = self._create_dashboard_tab()
        self.tabs.addTab(dashboard_tab, qta.icon('fa5s.tachometer-alt'), " Dashboard")
        
        main_layout.addWidget(self.tabs)

        # Caricamento iniziale dei dati
        self.update_all_data()
        
        # FORZA MASSIMIZZAZIONE ALLA FINE (dopo aver costruito il layout)
        self.setWindowState(Qt.WindowMaximized)

    def _create_header(self):
        """Crea l'header con controlli e pulsanti."""
        layout = QHBoxLayout()
        
        # Titolo
        title = QLabel("<h1>📊 Dashboard Statistiche</h1>")
        title.setObjectName("statsDashboardTitle")
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Selezione anno
        layout.addWidget(QLabel("<b>Anno:</b>"))
        self.year_spinbox = QSpinBox()
        self.year_spinbox.setObjectName("statsYearSpin")
        self.year_spinbox.setRange(2020, datetime.now().year + 1)
        self.year_spinbox.setValue(datetime.now().year)
        self.year_spinbox.valueChanged.connect(self.update_all_data)
        layout.addWidget(self.year_spinbox)
        
        # Selezione periodo
        layout.addWidget(QLabel("<b>Periodo:</b>"))
        self.period_combo = QComboBox()
        self.period_combo.setObjectName("statsPeriodCombo")
        self.period_combo.addItems(["Anno Corrente", "Ultimi 12 Mesi", "Ultimo Trimestre", "Ultimo Mese", "Tutto"])
        self.period_combo.currentTextChanged.connect(self.update_all_data)
        layout.addWidget(self.period_combo)
        
        # Pulsante refresh
        refresh_btn = QPushButton(qta.icon('fa5s.sync'), " Aggiorna")
        refresh_btn.setObjectName("editButton")
        refresh_btn.clicked.connect(self.update_all_data)
        layout.addWidget(refresh_btn)
        
        # Pulsante esporta
        export_btn = QPushButton(qta.icon('fa5s.file-excel'), " Esporta Report")
        export_btn.setObjectName("autoButton")
        export_btn.clicked.connect(self.export_report)
        layout.addWidget(export_btn)
        
        return layout
    
    def _create_overview_tab(self):
        """Crea il tab con la panoramica generale."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # KPI Cards
        kpi_layout = QHBoxLayout()
        
        # Card Totale Verifiche
        self.total_card = self._create_kpi_card("Totale Verifiche", "0", qta.icon('fa5s.clipboard-check'), "#2563eb")
        kpi_layout.addWidget(self.total_card)
        
        # Card Conformi
        self.conformi_card = self._create_kpi_card("Conformi", "0", qta.icon('fa5s.check-circle'), "#16a34a")
        kpi_layout.addWidget(self.conformi_card)
        
        # Card Non Conformi
        self.non_conformi_card = self._create_kpi_card("Non Conformi", "0", qta.icon('fa5s.times-circle'), "#dc2626")
        kpi_layout.addWidget(self.non_conformi_card)
        
        # Card Tasso Conformità
        self.rate_card = self._create_kpi_card("Tasso Conformità", "0%", qta.icon('fa5s.percentage'), "#8b5cf6")
        kpi_layout.addWidget(self.rate_card)
        
        layout.addLayout(kpi_layout)
        
        # Grafici principali
        charts_layout = QHBoxLayout()
        
        # Grafico a torta conformità
        pie_group = QGroupBox("Distribuzione Esiti")
        pie_layout = QVBoxLayout(pie_group)
        self.pie_chart = QChart()
        self.pie_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.pie_chart_view = QChartView(self.pie_chart)
        self.pie_chart_view.setRenderHint(QPainter.Antialiasing)
        pie_layout.addWidget(self.pie_chart_view)
        charts_layout.addWidget(pie_group)
        
        # Grafico mensile
        monthly_group = QGroupBox("Verifiche per Mese")
        monthly_layout = QVBoxLayout(monthly_group)
        self.monthly_chart = QChart()
        self.monthly_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.monthly_chart_view = QChartView(self.monthly_chart)
        self.monthly_chart_view.setRenderHint(QPainter.Antialiasing)
        monthly_layout.addWidget(self.monthly_chart_view)
        charts_layout.addWidget(monthly_group)
        
        layout.addLayout(charts_layout)
        
        return widget
    
    def _create_charts_tab(self):
        """Crea il tab con grafici dettagliati."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Grafico trend temporale
        trend_group = QGroupBox("Andamento Numero Verifiche per Mese")
        trend_layout = QVBoxLayout(trend_group)
        self.trend_chart = QChart()
        self.trend_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.trend_chart_view = QChartView(self.trend_chart)
        self.trend_chart_view.setRenderHint(QPainter.Antialiasing)
        trend_layout.addWidget(self.trend_chart_view)
        layout.addWidget(trend_group)
        
        # Grafico confronto annuale
        comparison_group = QGroupBox("Confronto con Anno Precedente")
        comparison_layout = QVBoxLayout(comparison_group)
        self.comparison_chart = QChart()
        self.comparison_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.comparison_chart_view = QChartView(self.comparison_chart)
        self.comparison_chart_view.setRenderHint(QPainter.Antialiasing)
        comparison_layout.addWidget(self.comparison_chart_view)
        layout.addWidget(comparison_group)
        
        return widget
    
    def _create_rankings_tab(self):
        """Crea il tab con le classifiche."""
        widget = QWidget()
        layout = QHBoxLayout(widget)

        # Clienti con più Verifiche
        clients_group = QGroupBox("Clienti con più Verifiche")
        clients_layout = QVBoxLayout(clients_group)
        self.clients_table = QTableWidget()
        self.clients_table.setColumnCount(3)
        self.clients_table.setHorizontalHeaderLabels(["Cliente", "Verifiche", "% Conformità"])
        self.clients_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.clients_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.clients_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        clients_layout.addWidget(self.clients_table)
        layout.addWidget(clients_group)
        
        # Top Tecnici
        techs_group = QGroupBox("Statistiche Tecnici")
        techs_layout = QVBoxLayout(techs_group)
        self.techs_table = QTableWidget()
        self.techs_table.setColumnCount(3)
        self.techs_table.setHorizontalHeaderLabels(["Tecnico", "Verifiche", "% Conformità"])
        self.techs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.techs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.techs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        techs_layout.addWidget(self.techs_table)
        layout.addWidget(techs_group)
        
        return widget
    
    def _create_dashboard_tab(self):
        """Crea il tab Dashboard con info operative (clienti, dispositivi, scadenze)."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        
        # Colonna Sinistra: Statistiche generali
        stats_group = QGroupBox("📊 Statistiche Generali")
        stats_layout = QFormLayout(stats_group)
        stats_layout.setRowWrapPolicy(QFormLayout.WrapAllRows)
        
        self.customers_stat_label = QLabel("Caricamento...")
        self.devices_stat_label = QLabel("Caricamento...")
        
        stats_layout.addRow("<b>Numero Clienti:</b>", self.customers_stat_label)
        stats_layout.addRow("<b>Numero Dispositivi:</b>", self.devices_stat_label)
        
        layout.addWidget(stats_group, 1)
        
        # Colonna Destra: Verifiche in scadenza
        scadenze_group = QGroupBox("⚠️ Verifiche Scadute o in Scadenza (30 gg)")
        scadenze_layout = QVBoxLayout(scadenze_group)
        
        self.scadenze_list = QListWidget()
        self.scadenze_list.setAlternatingRowColors(True)
        scadenze_layout.addWidget(self.scadenze_list)
        
        layout.addWidget(scadenze_group, 2)
        
        return widget
    
    def _create_kpi_card(self, title, value, icon, color):
        """Crea una card KPI con sfondo che garantisce leggibilità in entrambi i temi."""
        card = QGroupBox()
        card.setObjectName("kpiCard")
        
        # Determina il tema corrente per impostare colori appropriati
        current_theme = config.get_current_theme()
        
        if current_theme == "dark":
            # Tema scuro: sfondo scuro semi-trasparente, testo chiaro
            bg_color = "#111a2c"
            text_color = "#dbe6f5"
            value_color = color  # Mantieni il colore distintivo per il valore
        else:
            # Tema chiaro: sfondo bianco, testo scuro
            bg_color = "#ffffff"
            text_color = "#223653"
            value_color = color  # Mantieni il colore distintivo per il valore
        
        card.setStyleSheet(f"""
            QGroupBox {{
                background-color: {bg_color};
                border: 2px solid {color};
                border-radius: 12px;
                margin-top: 10px;
                font-weight: bold;
                padding: 15px;
            }}
        """)
        
        layout = QVBoxLayout(card)
        
        # Titolo (usa colore del testo del tema)
        title_label = QLabel(title.upper())
        title_label.setObjectName("kpiTitle")
        title_label.setStyleSheet(f"""
            color: {text_color};
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 0.5px;
            background-color: transparent;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # Valore (usa il colore distintivo della card)
        value_label = QLabel(value)
        value_label.setObjectName("kpiValue")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet(f"""
            color: {value_color};
            font-size: 34px;
            font-weight: bold;
            background-color: transparent;
        """)
        layout.addWidget(value_label)
        
        # Salva il label e il colore per aggiornamenti futuri
        card.value_label = value_label
        card.value_color = value_color
        
        return card
    
    def update_all_data(self):
        """Aggiorna tutti i dati della dashboard."""
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            selected_year = self.year_spinbox.value()
            
            # Aggiorna KPI
            self._update_kpi()
            
            # Aggiorna grafici
            self._update_pie_chart()
            self._update_monthly_chart(selected_year)
            self._update_trend_chart(selected_year)
            self._update_comparison_chart(selected_year)
            
            # Aggiorna classifiche
            self._update_rankings()
            
            # Aggiorna dashboard operativa
            self._update_dashboard_data()
            
        except Exception as e:
            logging.error(f"Errore durante l'aggiornamento della dashboard: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile aggiornare la dashboard:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def _update_kpi(self):
        """Aggiorna le card KPI."""
        try:
            stats = services.get_verification_stats()
            
            total = stats.get('totale', 0)
            conformi = stats.get('conformi', 0)
            non_conformi = stats.get('non_conformi', 0)
            
            rate = (conformi / total * 100) if total > 0 else 0
            
            self.total_card.value_label.setText(f"{total:,}")
            self.conformi_card.value_label.setText(f"{conformi:,}")
            self.non_conformi_card.value_label.setText(f"{non_conformi:,}")
            self.rate_card.value_label.setText(f"{rate:.1f}%")
            
        except Exception as e:
            logging.error(f"Errore aggiornamento KPI: {e}", exc_info=True)
    
    def _update_pie_chart(self):
        """Aggiorna il grafico a torta."""
        try:
            self.pie_chart.removeAllSeries()
            
            stats = services.get_verification_stats()
            logging.info(f"Stats ricevute per pie chart: {stats}")
            
            conformi = stats.get('conformi', 0)
            non_conformi = stats.get('non_conformi', 0)
            total = conformi + non_conformi
            
            logging.info(f"Pie chart - Conformi: {conformi}, Non Conformi: {non_conformi}, Totale: {total}")
            
            if total == 0:
                self.pie_chart.setTitle("Nessuna verifica disponibile")
                logging.warning("Nessun dato disponibile per il grafico a torta")
                return
            
            series = QPieSeries()
            
            # Aggiungi solo se ci sono conformi
            if conformi > 0:
                slice_conformi = series.append(f"Conformi ({conformi})", float(conformi))
                slice_conformi.setColor(QColor("#16a34a"))
                slice_conformi.setLabelVisible(True)
                slice_conformi.setLabelPosition(QPieSlice.LabelOutside)
            
            # Aggiungi solo se ci sono non conformi
            if non_conformi > 0:
                slice_non_conformi = series.append(f"Non Conformi ({non_conformi})", float(non_conformi))
                slice_non_conformi.setColor(QColor("#dc2626"))
                slice_non_conformi.setLabelVisible(True)
                slice_non_conformi.setLabelPosition(QPieSlice.LabelOutside)
            
            self.pie_chart.addSeries(series)
            self.pie_chart.setTitle(f"Distribuzione Esiti (totale: {total})")
            self.pie_chart.legend().setVisible(True)
            self.pie_chart.legend().setAlignment(Qt.AlignBottom)
            
            logging.info("Grafico a torta aggiornato con successo")
            
        except Exception as e:
            logging.error(f"Errore aggiornamento grafico torta: {e}", exc_info=True)
            self.pie_chart.setTitle(f"Errore: {str(e)}")
    
    def _update_monthly_chart(self, year):
        """Aggiorna il grafico mensile."""
        try:
            self.monthly_chart.removeAllSeries()
            
            for axis in self.monthly_chart.axes():
                self.monthly_chart.removeAxis(axis)
            
            stats = services.get_verification_stats_by_month(year)
            
            if not stats:
                self.monthly_chart.setTitle(f"Nessuna verifica per l'anno {year}")
                return

            # Crea i set di barre
            set_passed = QBarSet("Conformi")
            set_failed = QBarSet("Non Conformi")
            
            set_passed.setColor(QColor("#16a34a"))
            set_failed.setColor(QColor("#dc2626"))

            months_data = {f"{i:02d}": {"passed": 0, "failed": 0} for i in range(1, 13)}
            max_value = 0
            
            for row in stats:
                month_key = row['month']
                months_data[month_key]['passed'] = row['passed'] or 0
                months_data[month_key]['failed'] = row['failed'] or 0
                # Calcola il massimo per l'asse Y
                month_total = months_data[month_key]['passed'] + months_data[month_key]['failed']
                max_value = max(max_value, month_total)

            for month_key in sorted(months_data.keys()):
                set_passed.append(months_data[month_key]['passed'])
                set_failed.append(months_data[month_key]['failed'])

            series = QBarSeries()
            series.append(set_passed)
            series.append(set_failed)

            self.monthly_chart.addSeries(series)
            
            # Calcola totale verifiche
            total_verifications = sum(months_data[m]['passed'] + months_data[m]['failed'] for m in months_data)
            self.monthly_chart.setTitle(f"Verifiche per Mese - Anno {year} (Totale: {total_verifications})")
            
            # Asse X (mesi)
            months_categories = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", 
                               "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
            axis_x = QBarCategoryAxis()
            axis_x.append(months_categories)
            self.monthly_chart.addAxis(axis_x, Qt.AlignBottom)
            series.attachAxis(axis_x)
            
            # Asse Y (numero verifiche)
            axis_y = QValueAxis()
            axis_y.setRange(0, max_value * 1.1)  # Aggiungi 10% di margine
            axis_y.setLabelFormat("%d")
            axis_y.setTitleText("Numero Verifiche")
            axis_y.applyNiceNumbers()  # Arrotonda i valori per renderli più leggibili
            self.monthly_chart.addAxis(axis_y, Qt.AlignLeft)
            series.attachAxis(axis_y)
            
            self.monthly_chart.legend().setVisible(True)
            self.monthly_chart.legend().setAlignment(Qt.AlignBottom)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento grafico mensile: {e}", exc_info=True)
    
    def _update_trend_chart(self, year):
        """Aggiorna il grafico trend con numero verifiche per mese."""
        try:
            self.trend_chart.removeAllSeries()
            
            for axis in self.trend_chart.axes():
                self.trend_chart.removeAxis(axis)
            
            stats = services.get_verification_stats_by_month(year)
            
            if not stats:
                self.trend_chart.setTitle(f"Nessun dato per l'anno {year}")
                return
            
            # Serie per totale verifiche
            series_total = QLineSeries()
            series_total.setName("Totale Verifiche")
            
            pen_total = QPen(QColor("#2563eb"))
            pen_total.setWidth(4)
            series_total.setPen(pen_total)
            
            # Serie per conformi
            series_passed = QLineSeries()
            series_passed.setName("Conformi")
            
            pen_passed = QPen(QColor("#16a34a"))
            pen_passed.setWidth(3)
            series_passed.setPen(pen_passed)
            
            # Serie per non conformi
            series_failed = QLineSeries()
            series_failed.setName("Non Conformi")
            
            pen_failed = QPen(QColor("#dc2626"))
            pen_failed.setWidth(3)
            series_failed.setPen(pen_failed)
            
            months_data = {i: {"total": 0, "passed": 0, "failed": 0} for i in range(1, 13)}
            max_value = 0
            
            for row in stats:
                month_num = int(row['month'])
                months_data[month_num]['total'] = row['total'] or 0
                months_data[month_num]['passed'] = row['passed'] or 0
                months_data[month_num]['failed'] = row['failed'] or 0
                max_value = max(max_value, months_data[month_num]['total'])
            
            for month_num in sorted(months_data.keys()):
                series_total.append(month_num, months_data[month_num]['total'])
                series_passed.append(month_num, months_data[month_num]['passed'])
                series_failed.append(month_num, months_data[month_num]['failed'])
            
            self.trend_chart.addSeries(series_total)
            self.trend_chart.addSeries(series_passed)
            self.trend_chart.addSeries(series_failed)
            
            # Calcola totale anno
            total_year = sum(m['total'] for m in months_data.values())
            self.trend_chart.setTitle(f"Andamento Verifiche per Mese - Anno {year} (Totale: {total_year})")
            
            # Asse X (mesi)
            axis_x = QValueAxis()
            axis_x.setRange(1, 12)
            axis_x.setLabelFormat("%d")
            axis_x.setTitleText("Mese")
            axis_x.setTickCount(12)
            self.trend_chart.addAxis(axis_x, Qt.AlignBottom)
            series_total.attachAxis(axis_x)
            series_passed.attachAxis(axis_x)
            series_failed.attachAxis(axis_x)
            
            # Asse Y (numero verifiche)
            axis_y = QValueAxis()
            axis_y.setRange(0, max_value * 1.1)  # Aggiungi 10% margine
            axis_y.setLabelFormat("%d")
            axis_y.setTitleText("Numero Verifiche")
            axis_y.applyNiceNumbers()
            self.trend_chart.addAxis(axis_y, Qt.AlignLeft)
            series_total.attachAxis(axis_y)
            series_passed.attachAxis(axis_y)
            series_failed.attachAxis(axis_y)
            
            self.trend_chart.legend().setVisible(True)
            self.trend_chart.legend().setAlignment(Qt.AlignBottom)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento grafico trend: {e}", exc_info=True)
    
    def _update_comparison_chart(self, year):
        """Aggiorna il grafico di confronto con anno precedente."""
        try:
            self.comparison_chart.removeAllSeries()
            
            for axis in self.comparison_chart.axes():
                self.comparison_chart.removeAxis(axis)
            
            current_stats = services.get_verification_stats_by_month(year)
            previous_stats = services.get_verification_stats_by_month(year - 1)
            
            if not current_stats and not previous_stats:
                self.comparison_chart.setTitle("Nessun dato disponibile")
                return
            
            set_current = QBarSet(str(year))
            set_previous = QBarSet(str(year - 1))
            
            set_current.setColor(QColor("#2563eb"))
            set_previous.setColor(QColor("#64748b"))
            
            months_current = {f"{i:02d}": 0 for i in range(1, 13)}
            months_previous = {f"{i:02d}": 0 for i in range(1, 13)}
            
            for row in current_stats:
                months_current[row['month']] = row['total'] or 0
            
            for row in previous_stats:
                months_previous[row['month']] = row['total'] or 0
            
            for month_key in sorted(months_current.keys()):
                set_current.append(months_current[month_key])
                set_previous.append(months_previous[month_key])
            
            series = QBarSeries()
            series.append(set_current)
            series.append(set_previous)
            
            self.comparison_chart.addSeries(series)
            self.comparison_chart.setTitle(f"Confronto Verifiche: {year} vs {year-1}")
            
            months_categories = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", 
                               "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
            axis_x = QBarCategoryAxis()
            axis_x.append(months_categories)
            self.comparison_chart.addAxis(axis_x, Qt.AlignBottom)
            series.attachAxis(axis_x)

            self.comparison_chart.legend().setVisible(True)
            self.comparison_chart.legend().setAlignment(Qt.AlignBottom)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento grafico confronto: {e}", exc_info=True)
    
    def _update_rankings(self):
        """Aggiorna le tabelle delle classifiche."""
        try:
            logging.info("Aggiornamento classifiche...")
            
            # Top Clienti
            self.clients_table.setRowCount(0)
            top_customers = services.get_top_customers_by_verifications(10)
            
            logging.info(f"Top customers ricevuti: {len(top_customers) if top_customers else 0}")
            
            if top_customers:
                self.clients_table.setRowCount(len(top_customers))
                for row_idx, customer in enumerate(top_customers):
                    # Nome cliente
                    name_item = QTableWidgetItem(customer['customer_name'])
                    self.clients_table.setItem(row_idx, 0, name_item)
                    
                    # Numero verifiche
                    verif_item = QTableWidgetItem(str(customer['total_verifications']))
                    verif_item.setTextAlignment(Qt.AlignCenter)
                    self.clients_table.setItem(row_idx, 1, verif_item)
                    
                    # % Conformità
                    rate = customer['conformity_rate'] or 0
                    rate_item = QTableWidgetItem(f"{rate:.1f}%")
                    rate_item.setTextAlignment(Qt.AlignCenter)
                    
                    # Colora in base alla conformità
                    if rate >= 90:
                        rate_item.setBackground(QColor("#A3BE8C"))  # Verde
                    elif rate >= 70:
                        rate_item.setBackground(QColor("#EBCB8B"))  # Giallo
                    else:
                        rate_item.setBackground(QColor("#BF616A"))  # Rosso
                    
                    self.clients_table.setItem(row_idx, 2, rate_item)
            
            # Top Tecnici
            self.techs_table.setRowCount(0)
            top_techs = services.get_top_technicians_by_verifications(10)
            
            logging.info(f"Top technicians ricevuti: {len(top_techs) if top_techs else 0}")
            
            if top_techs:
                self.techs_table.setRowCount(len(top_techs))
                for row_idx, tech in enumerate(top_techs):
                    # Nome tecnico
                    name_item = QTableWidgetItem(tech['technician_name'])
                    self.techs_table.setItem(row_idx, 0, name_item)
                    
                    # Numero verifiche
                    verif_item = QTableWidgetItem(str(tech['total_verifications']))
                    verif_item.setTextAlignment(Qt.AlignCenter)
                    self.techs_table.setItem(row_idx, 1, verif_item)
                    
                    # % Conformità
                    rate = tech['conformity_rate'] or 0
                    rate_item = QTableWidgetItem(f"{rate:.1f}%")
                    rate_item.setTextAlignment(Qt.AlignCenter)
                    
                    # Colora in base alla conformità
                    if rate >= 90:
                        rate_item.setBackground(QColor("#A3BE8C"))  # Verde
                    elif rate >= 70:
                        rate_item.setBackground(QColor("#EBCB8B"))  # Giallo
                    else:
                        rate_item.setBackground(QColor("#BF616A"))  # Rosso
                    
                    self.techs_table.setItem(row_idx, 2, rate_item)
            
            logging.info("Classifiche aggiornate con successo")
            
        except Exception as e:
            logging.error(f"Errore aggiornamento classifiche: {e}", exc_info=True)
    
    def _update_dashboard_data(self):
        """Aggiorna i dati del tab Dashboard (clienti, dispositivi, scadenze)."""
        try:
            logging.info("Aggiornamento dashboard operativa...")
            
            # Carica statistiche generali
            stats = services.get_stats()
            self.customers_stat_label.setText(f"<b style='font-size: 16px; color: #2563eb;'>{stats.get('customers', 0):,}</b>")
            self.devices_stat_label.setText(f"<b style='font-size: 16px; color: #16a34a;'>{stats.get('devices', 0):,}</b>")
            
            # Carica dispositivi in scadenza
            self.scadenze_list.clear()
            devices_to_check = services.get_devices_needing_verification()
            
            if not devices_to_check:
                item = QListWidgetItem("✓ Nessuna verifica in scadenza")
                item.setForeground(QColor("#16a34a"))
                self.scadenze_list.addItem(item)
            else:
                today = QDate.currentDate()
                for device_row in devices_to_check:
                    device = dict(device_row)
                    next_date_str = device.get('next_verification_date')
                    if not next_date_str:
                        continue
                    
                    next_date = QDate.fromString(next_date_str, "yyyy-MM-dd")
                    
                    # Testo del dispositivo
                    item_text = (
                        f"<b>{device.get('description')}</b> (S/N: {device.get('serial_number')})<br>"
                        f"<small><i>{device.get('customer_name')}</i> - "
                        f"Scadenza: <b>{next_date.toString('dd/MM/yyyy')}</b></small>"
                    )
                    
                    list_item = QListWidgetItem()
                    label = QLabel(item_text)
                    
                    # Colora in base alla scadenza
                    if next_date < today:
                        label.setStyleSheet("color: #dc2626; font-weight: bold; padding: 5px;")
                        list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_MessageBoxCritical))
                    else:
                        label.setStyleSheet("color: #ea580c; padding: 5px;")
                        list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_MessageBoxWarning))
                    
                    self.scadenze_list.addItem(list_item)
                    self.scadenze_list.setItemWidget(list_item, label)
            
            logging.info("Dashboard operativa aggiornata con successo")
            
        except Exception as e:
            logging.error(f"Errore aggiornamento dashboard operativa: {e}", exc_info=True)
            self.customers_stat_label.setText("<b style='color:red;'>Errore</b>")
            self.devices_stat_label.setText("<b style='color:red;'>Errore</b>")
    
    def export_report(self):
        """Esporta un report completo delle statistiche."""
        try:
            year = self.year_spinbox.value()
            default_filename = f"Report_Statistiche_{year}.xlsx"
            
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Esporta Report Statistiche",
                os.path.join(os.path.expanduser("~"), "Desktop", default_filename),
                "Excel Files (*.xlsx)"
            )
            
            if not file_path:
                return
            
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Raccogli tutti i dati
            stats_general = services.get_verification_stats()
            stats_monthly = services.get_verification_stats_by_month(year)
            
            # Crea DataFrame
            df_monthly = pd.DataFrame([dict(row) for row in stats_monthly]) if stats_monthly else pd.DataFrame()
            
            # Esporta in Excel con più fogli
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                # Foglio Riepilogo
                df_summary = pd.DataFrame([stats_general])
                df_summary.to_excel(writer, sheet_name='Riepilogo', index=False)
                
                # Foglio Mensile
                if not df_monthly.empty:
                    df_monthly.to_excel(writer, sheet_name='Dettaglio Mensile', index=False)
            
            QApplication.restoreOverrideCursor()
            QMessageBox.information(
                self,
                "Esportazione Completata",
                f"Report esportato con successo in:\n{file_path}"
            )

        except Exception as e:
            QApplication.restoreOverrideCursor()
            logging.error(f"Errore esportazione report: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile esportare il report:\n{str(e)}")
