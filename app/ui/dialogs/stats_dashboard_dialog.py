# app/ui/dialogs/stats_dashboard_dialog.py
from datetime import datetime, date, timedelta
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QSpinBox, QLabel, QWidget, 
                               QSizePolicy, QGroupBox, QGridLayout, QPushButton, QComboBox, QTabWidget,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
                               QMessageBox, QApplication, QFormLayout, QListWidget, QListWidgetItem, QStyle,
                               QScrollArea, QFrame, QProgressBar, QSplitter)
from PySide6.QtCharts import (QChart, QChartView, QBarSet, QPercentBarSeries, QBarCategoryAxis,
                              QPieSeries, QPieSlice, QLineSeries, QValueAxis, QBarSeries,
                              QStackedBarSeries)
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
    - KPI generali (totali, conformità, trend, verifiche elettriche/funzionali)
    - Grafico verifiche per mese (elettriche e funzionali combinate)
    - Grafico conformità (torta) con breakdown per tipo
    - Grafico trend annuale con linee multiple
    - Distribuzione tipologie dispositivi
    - Top clienti/tecnici/tipologie con più dettagli
    - Dashboard operativa con scadenze, strumenti, attività recente
    - Esportazione dati avanzata
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statsDashboardDialog")
        self.setWindowTitle("Dashboard Statistiche Verifiche")
        self.setStyleSheet(config.get_current_stylesheet())
        self.setMinimumSize(1200, 800)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # Header con controlli
        header = self._create_header()
        main_layout.addLayout(header)

        # Tabs
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
        self.tabs.addTab(rankings_tab, qta.icon('fa5s.trophy'), " Classifiche")
        
        # Tab 4: Dashboard Operativa
        dashboard_tab = self._create_dashboard_tab()
        self.tabs.addTab(dashboard_tab, qta.icon('fa5s.tachometer-alt'), " Dashboard Operativa")
        
        main_layout.addWidget(self.tabs)

        # Caricamento iniziale
        self.update_all_data()
        self.setWindowState(Qt.WindowMaximized)

    # =========================================================================
    # HEADER
    # =========================================================================
    def _create_header(self):
        layout = QHBoxLayout()
        
        title = QLabel("<h2>📊 Dashboard Statistiche Verifiche</h2>")
        title.setObjectName("statsDashboardTitle")
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Anno
        layout.addWidget(QLabel("<b>Anno:</b>"))
        self.year_spinbox = QSpinBox()
        self.year_spinbox.setObjectName("statsYearSpin")
        self.year_spinbox.setRange(2020, datetime.now().year + 1)
        self.year_spinbox.setValue(datetime.now().year)
        self.year_spinbox.valueChanged.connect(self.update_all_data)
        layout.addWidget(self.year_spinbox)
        
        # Periodo
        layout.addWidget(QLabel("<b>Periodo:</b>"))
        self.period_combo = QComboBox()
        self.period_combo.setObjectName("statsPeriodCombo")
        self.period_combo.addItems(["Anno Corrente", "Ultimi 12 Mesi", "Ultimo Trimestre", "Ultimo Mese", "Tutto"])
        self.period_combo.currentTextChanged.connect(self.update_all_data)
        layout.addWidget(self.period_combo)
        
        # Aggiorna
        refresh_btn = QPushButton(qta.icon('fa5s.sync'), " Aggiorna")
        refresh_btn.setObjectName("editButton")
        refresh_btn.clicked.connect(self.update_all_data)
        layout.addWidget(refresh_btn)
        
        # Esporta
        export_btn = QPushButton(qta.icon('fa5s.file-excel'), " Esporta Report")
        export_btn.setObjectName("autoButton")
        export_btn.clicked.connect(self.export_report)
        layout.addWidget(export_btn)
        
        return layout
    
    # =========================================================================
    # TAB 1: PANORAMICA
    # =========================================================================
    def _create_overview_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        
        # --- Riga 1: KPI principali ---
        kpi_row1 = QHBoxLayout()
        
        self.total_ve_card = self._create_kpi_card(
            "Verifiche Elettriche", "0", qta.icon('fa5s.bolt'), "#2563eb")
        kpi_row1.addWidget(self.total_ve_card)
        
        self.total_vf_card = self._create_kpi_card(
            "Verifiche Funzionali", "0", qta.icon('fa5s.cogs'), "#7c3aed")
        kpi_row1.addWidget(self.total_vf_card)
        
        self.conformi_card = self._create_kpi_card(
            "Conformi (VE)", "0", qta.icon('fa5s.check-circle'), "#16a34a")
        kpi_row1.addWidget(self.conformi_card)
        
        self.non_conformi_card = self._create_kpi_card(
            "Non Conformi (VE)", "0", qta.icon('fa5s.times-circle'), "#dc2626")
        kpi_row1.addWidget(self.non_conformi_card)
        
        self.rate_card = self._create_kpi_card(
            "Tasso Conformità", "0%", qta.icon('fa5s.percentage'), "#0891b2")
        kpi_row1.addWidget(self.rate_card)
        
        layout.addLayout(kpi_row1)
        
        # --- Riga 2: KPI secondari ---
        kpi_row2 = QHBoxLayout()
        
        self.devices_card = self._create_kpi_card(
            "Dispositivi Attivi", "0", qta.icon('fa5s.laptop-medical'), "#0d9488")
        kpi_row2.addWidget(self.devices_card)
        
        self.customers_card = self._create_kpi_card(
            "Clienti", "0", qta.icon('fa5s.hospital'), "#ea580c")
        kpi_row2.addWidget(self.customers_card)
        
        self.month_card = self._create_kpi_card(
            "Verifiche Mese Corrente", "0", qta.icon('fa5s.calendar-check'), "#4f46e5")
        kpi_row2.addWidget(self.month_card)
        
        self.today_card = self._create_kpi_card(
            "Verifiche Oggi", "0", qta.icon('fa5s.clock'), "#be185d")
        kpi_row2.addWidget(self.today_card)
        
        self.never_verified_card = self._create_kpi_card(
            "Mai Verificati", "0", qta.icon('fa5s.exclamation-triangle'), "#b91c1c")
        kpi_row2.addWidget(self.never_verified_card)
        
        layout.addLayout(kpi_row2)
        
        # --- Grafici ---
        charts_layout = QHBoxLayout()
        
        # Grafico a torta conformità elettriche
        pie_group = QGroupBox("Distribuzione Esiti Verifiche Elettriche")
        pie_layout = QVBoxLayout(pie_group)
        self.pie_chart = QChart()
        self.pie_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.pie_chart_view = QChartView(self.pie_chart)
        self.pie_chart_view.setRenderHint(QPainter.Antialiasing)
        pie_layout.addWidget(self.pie_chart_view)
        charts_layout.addWidget(pie_group)
        
        # Grafico a torta conformità funzionale
        pie_func_group = QGroupBox("Distribuzione Esiti Verifiche Funzionali")
        pie_func_layout = QVBoxLayout(pie_func_group)
        self.pie_func_chart = QChart()
        self.pie_func_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.pie_func_chart_view = QChartView(self.pie_func_chart)
        self.pie_func_chart_view.setRenderHint(QPainter.Antialiasing)
        pie_func_layout.addWidget(self.pie_func_chart_view)
        charts_layout.addWidget(pie_func_group)
        
        # Grafico barre mensile combinato
        monthly_group = QGroupBox("Verifiche per Mese (Elettriche + Funzionali)")
        monthly_layout = QVBoxLayout(monthly_group)
        self.monthly_chart = QChart()
        self.monthly_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.monthly_chart_view = QChartView(self.monthly_chart)
        self.monthly_chart_view.setRenderHint(QPainter.Antialiasing)
        monthly_layout.addWidget(self.monthly_chart_view)
        charts_layout.addWidget(monthly_group)
        
        layout.addLayout(charts_layout)
        
        return widget
    
    # =========================================================================
    # TAB 2: GRAFICI DETTAGLIATI
    # =========================================================================
    def _create_charts_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        # Riga superiore: Trend + Confronto anno
        top_row = QHBoxLayout()
        
        # Grafico trend
        trend_group = QGroupBox("Andamento Verifiche per Mese")
        trend_layout = QVBoxLayout(trend_group)
        self.trend_chart = QChart()
        self.trend_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.trend_chart_view = QChartView(self.trend_chart)
        self.trend_chart_view.setRenderHint(QPainter.Antialiasing)
        trend_layout.addWidget(self.trend_chart_view)
        top_row.addWidget(trend_group)
        
        # Confronto anno precedente
        comparison_group = QGroupBox("Confronto con Anno Precedente")
        comparison_layout = QVBoxLayout(comparison_group)
        self.comparison_chart = QChart()
        self.comparison_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.comparison_chart_view = QChartView(self.comparison_chart)
        self.comparison_chart_view.setRenderHint(QPainter.Antialiasing)
        comparison_layout.addWidget(self.comparison_chart_view)
        top_row.addWidget(comparison_group)
        
        layout.addLayout(top_row)
        
        # Riga inferiore: Distribuzione dispositivi + Produttività
        bottom_row = QHBoxLayout()
        
        # Distribuzione tipologie dispositivi
        device_dist_group = QGroupBox("Distribuzione Tipologie Dispositivi")
        device_dist_layout = QVBoxLayout(device_dist_group)
        self.device_dist_chart = QChart()
        self.device_dist_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.device_dist_chart_view = QChartView(self.device_dist_chart)
        self.device_dist_chart_view.setRenderHint(QPainter.Antialiasing)
        device_dist_layout.addWidget(self.device_dist_chart_view)
        bottom_row.addWidget(device_dist_group)
        
        # Produttività
        productivity_group = QGroupBox("Produttività Mensile (Giorni Lavorativi e Media)")
        productivity_layout = QVBoxLayout(productivity_group)
        self.productivity_chart = QChart()
        self.productivity_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.productivity_chart_view = QChartView(self.productivity_chart)
        self.productivity_chart_view.setRenderHint(QPainter.Antialiasing)
        productivity_layout.addWidget(self.productivity_chart_view)
        bottom_row.addWidget(productivity_group)
        
        layout.addLayout(bottom_row)
        
        return widget
    
    # =========================================================================
    # TAB 3: CLASSIFICHE
    # =========================================================================
    def _create_rankings_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Riga superiore: Clienti e Tecnici
        top_row = QHBoxLayout()
        
        # Top Clienti
        clients_group = QGroupBox("🏆 Top Clienti per Numero Verifiche")
        clients_layout = QVBoxLayout(clients_group)
        self.clients_table = QTableWidget()
        self.clients_table.setColumnCount(5)
        self.clients_table.setHorizontalHeaderLabels([
            "Posizione", "Cliente", "Verifiche Totali", "Conformi", "% Conformità"
        ])
        self.clients_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.clients_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.clients_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.clients_table.setAlternatingRowColors(True)
        clients_layout.addWidget(self.clients_table)
        top_row.addWidget(clients_group)
        
        # Top Tecnici
        techs_group = QGroupBox("🔧 Statistiche Tecnici")
        techs_layout = QVBoxLayout(techs_group)
        self.techs_table = QTableWidget()
        self.techs_table.setColumnCount(5)
        self.techs_table.setHorizontalHeaderLabels([
            "Posizione", "Tecnico", "Verifiche Totali", "Conformi", "% Conformità"
        ])
        self.techs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.techs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.techs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.techs_table.setAlternatingRowColors(True)
        techs_layout.addWidget(self.techs_table)
        top_row.addWidget(techs_group)
        
        layout.addLayout(top_row)
        
        # Riga inferiore: Tipologie dispositivi
        device_types_group = QGroupBox("📋 Top Tipologie Dispositivi per Verifiche")
        device_types_layout = QVBoxLayout(device_types_group)
        self.device_types_table = QTableWidget()
        self.device_types_table.setColumnCount(5)
        self.device_types_table.setHorizontalHeaderLabels([
            "Posizione", "Tipologia Dispositivo", "Verifiche Totali", "Conformi", "% Conformità"
        ])
        self.device_types_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.device_types_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.device_types_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.device_types_table.setAlternatingRowColors(True)
        device_types_layout.addWidget(self.device_types_table)
        
        layout.addWidget(device_types_group)
        
        return widget
    
    # =========================================================================
    # TAB 4: DASHBOARD OPERATIVA
    # =========================================================================
    def _create_dashboard_tab(self):
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        
        # --- Riga superiore: KPI operativi ---
        ops_kpi_layout = QHBoxLayout()
        
        # Statistiche generali in una griglia
        stats_group = QGroupBox("📊 Riepilogo Generale")
        stats_grid = QGridLayout(stats_group)
        stats_grid.setSpacing(8)
        
        self.op_labels = {}
        op_items = [
            ("customers", "Clienti", "fa5s.hospital", "#2563eb"),
            ("destinations", "Destinazioni", "fa5s.map-marker-alt", "#0891b2"),
            ("devices_active", "Dispositivi Attivi", "fa5s.laptop-medical", "#16a34a"),
            ("devices_decommissioned", "Dismessi", "fa5s.power-off", "#64748b"),
            ("instruments", "Strumenti MTI", "fa5s.tools", "#ea580c"),
            ("profiles_electrical", "Profili Elettrici", "fa5s.bolt", "#7c3aed"),
            ("profiles_functional", "Profili Funzionali", "fa5s.cogs", "#be185d"),
            ("last_verification", "Ultima Verifica", "fa5s.calendar", "#4f46e5"),
        ]
        
        for idx, (key, label, icon, color) in enumerate(op_items):
            row = idx // 4
            col = idx % 4
            
            icon_label = QLabel()
            icon_label.setPixmap(qta.icon(icon, color=color).pixmap(20, 20))
            stats_grid.addWidget(icon_label, row * 2, col * 2)
            
            text_label = QLabel(f"<b>{label}:</b>")
            stats_grid.addWidget(text_label, row * 2, col * 2 + 1)
            
            value_label = QLabel(f"<b style='font-size: 14px; color: {color};'>...</b>")
            value_label.setAlignment(Qt.AlignCenter)
            stats_grid.addWidget(value_label, row * 2 + 1, col * 2, 1, 2)
            
            self.op_labels[key] = value_label
        
        ops_kpi_layout.addWidget(stats_group, 2)
        
        # Verifiche oggi/mese
        activity_group = QGroupBox("📈 Attività Periodo")
        activity_layout = QFormLayout(activity_group)
        activity_layout.setSpacing(8)
        
        self.op_ve_total = QLabel("...")
        self.op_vf_total = QLabel("...")
        self.op_ve_month = QLabel("...")
        self.op_vf_month = QLabel("...")
        self.op_ve_today = QLabel("...")
        self.op_vf_today = QLabel("...")
        
        activity_layout.addRow("⚡ Verifiche Elettriche totali:", self.op_ve_total)
        activity_layout.addRow("⚙️ Verifiche Funzionali totali:", self.op_vf_total)
        activity_layout.addRow("⚡ VE questo mese:", self.op_ve_month)
        activity_layout.addRow("⚙️ VF questo mese:", self.op_vf_month)
        activity_layout.addRow("⚡ VE oggi:", self.op_ve_today)
        activity_layout.addRow("⚙️ VF oggi:", self.op_vf_today)
        
        ops_kpi_layout.addWidget(activity_group, 1)
        
        main_layout.addLayout(ops_kpi_layout)
        
        # --- Riga inferiore: Scadenze e Attività recente ---
        bottom_splitter = QSplitter(Qt.Horizontal)
        
        # Colonna sinistra: Scadenze verifiche
        scadenze_widget = QWidget()
        scadenze_layout = QVBoxLayout(scadenze_widget)
        scadenze_layout.setContentsMargins(0, 0, 0, 0)
        
        scadenze_header = QHBoxLayout()
        scadenze_header.addWidget(QLabel("<h3>⚠️ Verifiche Scadute o in Scadenza (30 gg)</h3>"))
        scadenze_header.addStretch()
        self.scadenze_count_label = QLabel("")
        scadenze_header.addWidget(self.scadenze_count_label)
        scadenze_layout.addLayout(scadenze_header)
        
        self.scadenze_list = QListWidget()
        self.scadenze_list.setAlternatingRowColors(True)
        scadenze_layout.addWidget(self.scadenze_list)
        
        bottom_splitter.addWidget(scadenze_widget)
        
        # Colonna centrale: Strumenti in scadenza calibrazione
        instruments_widget = QWidget()
        instruments_layout = QVBoxLayout(instruments_widget)
        instruments_layout.setContentsMargins(0, 0, 0, 0)
        
        instruments_header = QHBoxLayout()
        instruments_header.addWidget(QLabel("<h3>🔧 Strumenti - Calibrazione in Scadenza</h3>"))
        instruments_header.addStretch()
        self.instruments_count_label = QLabel("")
        instruments_header.addWidget(self.instruments_count_label)
        instruments_layout.addLayout(instruments_header)
        
        self.instruments_list = QListWidget()
        self.instruments_list.setAlternatingRowColors(True)
        instruments_layout.addWidget(self.instruments_list)
        
        bottom_splitter.addWidget(instruments_widget)
        
        # Colonna destra: Attività recente
        recent_widget = QWidget()
        recent_layout = QVBoxLayout(recent_widget)
        recent_layout.setContentsMargins(0, 0, 0, 0)
        
        recent_layout.addWidget(QLabel("<h3>🕐 Ultime Verifiche Eseguite</h3>"))
        
        self.recent_table = QTableWidget()
        self.recent_table.setColumnCount(6)
        self.recent_table.setHorizontalHeaderLabels([
            "Data", "Tipo", "Esito", "Dispositivo", "Cliente", "Tecnico"
        ])
        self.recent_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.recent_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.recent_table.setAlternatingRowColors(True)
        self.recent_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        recent_layout.addWidget(self.recent_table)
        
        bottom_splitter.addWidget(recent_widget)
        
        bottom_splitter.setSizes([300, 300, 400])
        main_layout.addWidget(bottom_splitter)
        
        return widget
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    def _create_kpi_card(self, title, value, icon, color):
        card = QGroupBox()
        card.setObjectName("kpiCard")
        
        current_theme = config.get_current_theme()
        
        if current_theme == "dark":
            bg_color = "#111a2c"
            text_color = "#dbe6f5"
        else:
            bg_color = "#ffffff"
            text_color = "#223653"
        
        card.setStyleSheet(f"""
            QGroupBox {{
                background-color: {bg_color};
                border: 2px solid {color};
                border-radius: 12px;
                margin-top: 10px;
                font-weight: bold;
                padding: 10px;
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setSpacing(2)
        
        # Titolo
        title_label = QLabel(title.upper())
        title_label.setObjectName("kpiTitle")
        title_label.setStyleSheet(f"""
            color: {text_color};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.5px;
            background-color: transparent;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # Valore
        value_label = QLabel(value)
        value_label.setObjectName("kpiValue")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet(f"""
            color: {color};
            font-size: 28px;
            font-weight: bold;
            background-color: transparent;
        """)
        layout.addWidget(value_label)
        
        # Sottotitolo (per dettagli aggiuntivi)
        subtitle_label = QLabel("")
        subtitle_label.setObjectName("kpiSubtitle")
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet(f"""
            color: {text_color};
            font-size: 10px;
            background-color: transparent;
        """)
        layout.addWidget(subtitle_label)
        
        card.value_label = value_label
        card.subtitle_label = subtitle_label
        card.value_color = color
        
        return card
    
    def _get_medal_icon(self, position):
        """Restituisce icona medaglia per la posizione."""
        if position == 1:
            return "🥇"
        elif position == 2:
            return "🥈"
        elif position == 3:
            return "🥉"
        return f"  {position}."
    
    def _get_rate_color(self, rate):
        """Restituisce il colore di sfondo in base al tasso di conformità."""
        if rate >= 95:
            return QColor("#A3BE8C")
        elif rate >= 85:
            return QColor("#b8d4a3")
        elif rate >= 70:
            return QColor("#EBCB8B")
        elif rate >= 50:
            return QColor("#d4956b")
        else:
            return QColor("#BF616A")
    
    # =========================================================================
    # UPDATE ALL
    # =========================================================================
    def update_all_data(self):
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            selected_year = self.year_spinbox.value()
            
            self._update_kpi()
            self._update_pie_chart()
            self._update_pie_func_chart()
            self._update_monthly_chart(selected_year)
            self._update_trend_chart(selected_year)
            self._update_comparison_chart(selected_year)
            self._update_device_distribution_chart()
            self._update_productivity_chart(selected_year)
            self._update_rankings()
            self._update_dashboard_data()
            
        except Exception as e:
            logging.error(f"Errore durante l'aggiornamento della dashboard: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile aggiornare la dashboard:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    # =========================================================================
    # KPI
    # =========================================================================
    def _update_kpi(self):
        try:
            # Statistiche verifiche elettriche
            ve_stats = services.get_verification_stats()
            total_ve = ve_stats.get('totale', 0)
            conformi_ve = ve_stats.get('conformi', 0)
            non_conformi_ve = ve_stats.get('non_conformi', 0)
            rate_ve = (conformi_ve / total_ve * 100) if total_ve > 0 else 0
            
            # Statistiche verifiche funzionali
            vf_stats = services.get_functional_verification_stats()
            total_vf = vf_stats.get('totale', 0)
            conformi_vf = vf_stats.get('conformi', 0)
            
            # Dashboard summary
            summary = services.get_dashboard_summary_stats()
            
            # KPI riga 1
            self.total_ve_card.value_label.setText(f"{total_ve:,}")
            self.total_ve_card.subtitle_label.setText(f"Conformi: {conformi_ve:,}")
            
            self.total_vf_card.value_label.setText(f"{total_vf:,}")
            self.total_vf_card.subtitle_label.setText(f"Conformi: {conformi_vf:,}")
            
            self.conformi_card.value_label.setText(f"{conformi_ve:,}")
            pct_conf = f"{conformi_ve / total_ve * 100:.0f}%" if total_ve > 0 else "-"
            self.conformi_card.subtitle_label.setText(f"{pct_conf} del totale")
            
            self.non_conformi_card.value_label.setText(f"{non_conformi_ve:,}")
            pct_fail = f"{non_conformi_ve / total_ve * 100:.0f}%" if total_ve > 0 else "-"
            self.non_conformi_card.subtitle_label.setText(f"{pct_fail} del totale")
            
            self.rate_card.value_label.setText(f"{rate_ve:.1f}%")
            # Calcola tasso combinato
            total_all = total_ve + total_vf
            conformi_all = conformi_ve + conformi_vf
            rate_all = (conformi_all / total_all * 100) if total_all > 0 else 0
            self.rate_card.subtitle_label.setText(f"Combinato: {rate_all:.1f}%")
            
            # KPI riga 2
            self.devices_card.value_label.setText(f"{summary.get('devices_active', 0):,}")
            self.devices_card.subtitle_label.setText(
                f"Totali: {summary.get('devices_total', 0):,} | Dismessi: {summary.get('devices_decommissioned', 0):,}")
            
            self.customers_card.value_label.setText(f"{summary.get('customers', 0):,}")
            self.customers_card.subtitle_label.setText(
                f"Destinazioni: {summary.get('destinations', 0):,}")
            
            month_total = summary.get('verifications_this_month', 0) + summary.get('functional_verifications_this_month', 0)
            self.month_card.value_label.setText(f"{month_total:,}")
            self.month_card.subtitle_label.setText(
                f"VE: {summary.get('verifications_this_month', 0)} | VF: {summary.get('functional_verifications_this_month', 0)}")
            
            today_total = summary.get('verifications_today', 0) + summary.get('functional_verifications_today', 0)
            self.today_card.value_label.setText(f"{today_total:,}")
            self.today_card.subtitle_label.setText(
                f"VE: {summary.get('verifications_today', 0)} | VF: {summary.get('functional_verifications_today', 0)}")
            
            self.never_verified_card.value_label.setText(f"{summary.get('devices_never_verified', 0):,}")
            devices_active = summary.get('devices_active', 0)
            if devices_active > 0:
                pct_nv = (summary.get('devices_never_verified', 0) / devices_active * 100)
                self.never_verified_card.subtitle_label.setText(f"{pct_nv:.0f}% dei dispositivi attivi")
            else:
                self.never_verified_card.subtitle_label.setText("Nessun dispositivo attivo")
            
        except Exception as e:
            logging.error(f"Errore aggiornamento KPI: {e}", exc_info=True)
    
    # =========================================================================
    # GRAFICI
    # =========================================================================
    def _update_pie_chart(self):
        """Grafico a torta verifiche elettriche."""
        try:
            self.pie_chart.removeAllSeries()
            stats = services.get_verification_stats()
            
            conformi = stats.get('conformi', 0)
            non_conformi = stats.get('non_conformi', 0)
            total = conformi + non_conformi
            
            if total == 0:
                self.pie_chart.setTitle("Nessuna verifica elettrica disponibile")
                return
            
            series = QPieSeries()
            
            if conformi > 0:
                sl = series.append(f"Conformi ({conformi})", float(conformi))
                sl.setColor(QColor("#16a34a"))
                sl.setLabelVisible(True)
                sl.setLabelPosition(QPieSlice.LabelOutside)
            
            if non_conformi > 0:
                sl = series.append(f"Non Conformi ({non_conformi})", float(non_conformi))
                sl.setColor(QColor("#dc2626"))
                sl.setLabelVisible(True)
                sl.setLabelPosition(QPieSlice.LabelOutside)
            
            self.pie_chart.addSeries(series)
            rate = conformi / total * 100 if total > 0 else 0
            self.pie_chart.setTitle(f"Verifiche Elettriche — {rate:.1f}% conformi (tot: {total})")
            self.pie_chart.legend().setVisible(True)
            self.pie_chart.legend().setAlignment(Qt.AlignBottom)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento grafico torta VE: {e}", exc_info=True)
    
    def _update_pie_func_chart(self):
        """Grafico a torta verifiche funzionali."""
        try:
            self.pie_func_chart.removeAllSeries()
            stats = services.get_functional_verification_stats()
            
            conformi = stats.get('conformi', 0)
            non_conformi = stats.get('non_conformi', 0)
            total = conformi + non_conformi
            
            if total == 0:
                self.pie_func_chart.setTitle("Nessuna verifica funzionale disponibile")
                return
            
            series = QPieSeries()
            
            if conformi > 0:
                sl = series.append(f"Conformi ({conformi})", float(conformi))
                sl.setColor(QColor("#7c3aed"))
                sl.setLabelVisible(True)
                sl.setLabelPosition(QPieSlice.LabelOutside)
            
            if non_conformi > 0:
                sl = series.append(f"Non Conformi ({non_conformi})", float(non_conformi))
                sl.setColor(QColor("#e11d48"))
                sl.setLabelVisible(True)
                sl.setLabelPosition(QPieSlice.LabelOutside)
            
            self.pie_func_chart.addSeries(series)
            rate = conformi / total * 100 if total > 0 else 0
            self.pie_func_chart.setTitle(f"Verifiche Funzionali — {rate:.1f}% conformi (tot: {total})")
            self.pie_func_chart.legend().setVisible(True)
            self.pie_func_chart.legend().setAlignment(Qt.AlignBottom)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento grafico torta VF: {e}", exc_info=True)
    
    def _update_monthly_chart(self, year):
        """Grafico barre mensile con elettriche e funzionali sovrapposte (stacked)."""
        try:
            self.monthly_chart.removeAllSeries()
            for axis in self.monthly_chart.axes():
                self.monthly_chart.removeAxis(axis)
            
            ve_stats = services.get_verification_stats_by_month(year)
            vf_stats = services.get_functional_verification_stats_by_month(year)
            
            if not ve_stats and not vf_stats:
                self.monthly_chart.setTitle(f"Nessuna verifica per l'anno {year}")
                return

            set_ve_passed = QBarSet("VE Conformi")
            set_ve_failed = QBarSet("VE Non Conformi")
            set_vf_passed = QBarSet("VF Conformi")
            set_vf_failed = QBarSet("VF Non Conformi")
            
            set_ve_passed.setColor(QColor("#16a34a"))
            set_ve_failed.setColor(QColor("#dc2626"))
            set_vf_passed.setColor(QColor("#7c3aed"))
            set_vf_failed.setColor(QColor("#e11d48"))

            months_ve = {f"{i:02d}": {"passed": 0, "failed": 0} for i in range(1, 13)}
            months_vf = {f"{i:02d}": {"passed": 0, "failed": 0} for i in range(1, 13)}
            max_value = 0
            
            for row in (ve_stats or []):
                months_ve[row['month']]['passed'] = row['passed'] or 0
                months_ve[row['month']]['failed'] = row['failed'] or 0
            
            for row in (vf_stats or []):
                months_vf[row['month']]['passed'] = row['passed'] or 0
                months_vf[row['month']]['failed'] = row['failed'] or 0

            for mk in sorted(months_ve.keys()):
                set_ve_passed.append(months_ve[mk]['passed'])
                set_ve_failed.append(months_ve[mk]['failed'])
                set_vf_passed.append(months_vf[mk]['passed'])
                set_vf_failed.append(months_vf[mk]['failed'])
                month_total = (months_ve[mk]['passed'] + months_ve[mk]['failed'] + 
                             months_vf[mk]['passed'] + months_vf[mk]['failed'])
                max_value = max(max_value, month_total)

            series = QStackedBarSeries()
            series.append(set_ve_passed)
            series.append(set_ve_failed)
            series.append(set_vf_passed)
            series.append(set_vf_failed)

            self.monthly_chart.addSeries(series)
            
            total_all = sum(months_ve[m]['passed'] + months_ve[m]['failed'] + 
                          months_vf[m]['passed'] + months_vf[m]['failed'] for m in months_ve)
            self.monthly_chart.setTitle(f"Verifiche per Mese - {year} (Totale: {total_all})")
            
            months_cat = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", 
                         "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
            axis_x = QBarCategoryAxis()
            axis_x.append(months_cat)
            self.monthly_chart.addAxis(axis_x, Qt.AlignBottom)
            series.attachAxis(axis_x)
            
            axis_y = QValueAxis()
            axis_y.setRange(0, max(max_value * 1.15, 1))
            axis_y.setLabelFormat("%d")
            axis_y.setTitleText("Numero Verifiche")
            axis_y.applyNiceNumbers()
            self.monthly_chart.addAxis(axis_y, Qt.AlignLeft)
            series.attachAxis(axis_y)
            
            self.monthly_chart.legend().setVisible(True)
            self.monthly_chart.legend().setAlignment(Qt.AlignBottom)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento grafico mensile: {e}", exc_info=True)
    
    def _update_trend_chart(self, year):
        """Grafico trend con linee per VE totali, VF totali e Totale."""
        try:
            self.trend_chart.removeAllSeries()
            for axis in self.trend_chart.axes():
                self.trend_chart.removeAxis(axis)
            
            ve_stats = services.get_verification_stats_by_month(year)
            vf_stats = services.get_functional_verification_stats_by_month(year)
            
            if not ve_stats and not vf_stats:
                self.trend_chart.setTitle(f"Nessun dato per l'anno {year}")
                return
            
            # Linee
            series_ve = QLineSeries()
            series_ve.setName("Verifiche Elettriche")
            pen_ve = QPen(QColor("#2563eb"))
            pen_ve.setWidth(3)
            series_ve.setPen(pen_ve)
            
            series_vf = QLineSeries()
            series_vf.setName("Verifiche Funzionali")
            pen_vf = QPen(QColor("#7c3aed"))
            pen_vf.setWidth(3)
            series_vf.setPen(pen_vf)
            
            series_total = QLineSeries()
            series_total.setName("Totale")
            pen_total = QPen(QColor("#16a34a"))
            pen_total.setWidth(4)
            series_total.setPen(pen_total)
            
            months_ve = {i: 0 for i in range(1, 13)}
            months_vf = {i: 0 for i in range(1, 13)}
            max_value = 0
            
            for row in (ve_stats or []):
                months_ve[int(row['month'])] = row['total'] or 0
            
            for row in (vf_stats or []):
                months_vf[int(row['month'])] = row['total'] or 0
            
            for m in range(1, 13):
                total = months_ve[m] + months_vf[m]
                series_ve.append(m, months_ve[m])
                series_vf.append(m, months_vf[m])
                series_total.append(m, total)
                max_value = max(max_value, total)
            
            self.trend_chart.addSeries(series_total)
            self.trend_chart.addSeries(series_ve)
            self.trend_chart.addSeries(series_vf)
            
            total_year = sum(months_ve[m] + months_vf[m] for m in range(1, 13))
            self.trend_chart.setTitle(f"Andamento - {year} (Totale: {total_year})")
            
            axis_x = QValueAxis()
            axis_x.setRange(1, 12)
            axis_x.setLabelFormat("%d")
            axis_x.setTitleText("Mese")
            axis_x.setTickCount(12)
            self.trend_chart.addAxis(axis_x, Qt.AlignBottom)
            series_ve.attachAxis(axis_x)
            series_vf.attachAxis(axis_x)
            series_total.attachAxis(axis_x)
            
            axis_y = QValueAxis()
            axis_y.setRange(0, max(max_value * 1.15, 1))
            axis_y.setLabelFormat("%d")
            axis_y.setTitleText("Numero Verifiche")
            axis_y.applyNiceNumbers()
            self.trend_chart.addAxis(axis_y, Qt.AlignLeft)
            series_ve.attachAxis(axis_y)
            series_vf.attachAxis(axis_y)
            series_total.attachAxis(axis_y)
            
            self.trend_chart.legend().setVisible(True)
            self.trend_chart.legend().setAlignment(Qt.AlignBottom)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento grafico trend: {e}", exc_info=True)
    
    def _update_comparison_chart(self, year):
        """Confronto con anno precedente (VE + VF combinate)."""
        try:
            self.comparison_chart.removeAllSeries()
            for axis in self.comparison_chart.axes():
                self.comparison_chart.removeAxis(axis)
            
            current_ve = services.get_verification_stats_by_month(year)
            previous_ve = services.get_verification_stats_by_month(year - 1)
            current_vf = services.get_functional_verification_stats_by_month(year)
            previous_vf = services.get_functional_verification_stats_by_month(year - 1)
            
            if not current_ve and not previous_ve and not current_vf and not previous_vf:
                self.comparison_chart.setTitle("Nessun dato disponibile")
                return
            
            set_current = QBarSet(f"{year}")
            set_previous = QBarSet(f"{year - 1}")
            
            set_current.setColor(QColor("#2563eb"))
            set_previous.setColor(QColor("#94a3b8"))
            
            months_current = {f"{i:02d}": 0 for i in range(1, 13)}
            months_previous = {f"{i:02d}": 0 for i in range(1, 13)}
            
            for row in (current_ve or []):
                months_current[row['month']] += row['total'] or 0
            for row in (current_vf or []):
                months_current[row['month']] += row['total'] or 0
            for row in (previous_ve or []):
                months_previous[row['month']] += row['total'] or 0
            for row in (previous_vf or []):
                months_previous[row['month']] += row['total'] or 0
            
            for mk in sorted(months_current.keys()):
                set_current.append(months_current[mk])
                set_previous.append(months_previous[mk])
            
            series = QBarSeries()
            series.append(set_previous)
            series.append(set_current)
            
            self.comparison_chart.addSeries(series)
            
            total_curr = sum(months_current.values())
            total_prev = sum(months_previous.values())
            diff = total_curr - total_prev
            diff_str = f"+{diff}" if diff >= 0 else str(diff)
            self.comparison_chart.setTitle(
                f"Confronto: {year} ({total_curr}) vs {year-1} ({total_prev}) — {diff_str}")
            
            months_cat = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", 
                         "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
            axis_x = QBarCategoryAxis()
            axis_x.append(months_cat)
            self.comparison_chart.addAxis(axis_x, Qt.AlignBottom)
            series.attachAxis(axis_x)

            max_val = max(max(months_current.values(), default=0), max(months_previous.values(), default=0))
            axis_y = QValueAxis()
            axis_y.setRange(0, max(max_val * 1.15, 1))
            axis_y.setLabelFormat("%d")
            axis_y.setTitleText("Verifiche (VE + VF)")
            axis_y.applyNiceNumbers()
            self.comparison_chart.addAxis(axis_y, Qt.AlignLeft)
            series.attachAxis(axis_y)
            
            self.comparison_chart.legend().setVisible(True)
            self.comparison_chart.legend().setAlignment(Qt.AlignBottom)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento grafico confronto: {e}", exc_info=True)
    
    def _update_device_distribution_chart(self):
        """Grafico a torta distribuzione tipologie dispositivi."""
        try:
            self.device_dist_chart.removeAllSeries()
            
            data = services.get_device_type_distribution()
            
            if not data:
                self.device_dist_chart.setTitle("Nessun dato disponibile")
                return
            
            series = QPieSeries()
            colors = [
                "#2563eb", "#16a34a", "#dc2626", "#7c3aed", "#ea580c",
                "#0891b2", "#be185d", "#4f46e5", "#0d9488", "#b91c1c",
                "#65a30d", "#c026d3", "#0369a1", "#d97706", "#6d28d9"
            ]
            
            total_devices = sum(row['count'] for row in data)
            
            for idx, row in enumerate(data):
                desc = row['description'] or "N/D"
                # Tronca nomi lunghi
                if len(desc) > 25:
                    desc = desc[:22] + "..."
                count = row['count']
                sl = series.append(f"{desc} ({count})", float(count))
                sl.setColor(QColor(colors[idx % len(colors)]))
                if idx < 5:  # Mostra label solo per i top 5
                    sl.setLabelVisible(True)
                    sl.setLabelPosition(QPieSlice.LabelOutside)
            
            self.device_dist_chart.addSeries(series)
            self.device_dist_chart.setTitle(f"Tipologie Dispositivi (tot: {total_devices})")
            self.device_dist_chart.legend().setVisible(True)
            self.device_dist_chart.legend().setAlignment(Qt.AlignRight)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento distribuzione dispositivi: {e}", exc_info=True)
    
    def _update_productivity_chart(self, year):
        """Grafico produttività mensile: giorni lavorativi + media verifiche/giorno."""
        try:
            self.productivity_chart.removeAllSeries()
            for axis in self.productivity_chart.axes():
                self.productivity_chart.removeAxis(axis)
            
            data = services.get_monthly_productivity(year)
            
            if not data:
                self.productivity_chart.setTitle(f"Nessun dato per l'anno {year}")
                return
            
            set_days = QBarSet("Giorni Lavorativi")
            set_days.setColor(QColor("#2563eb"))
            
            series_avg = QLineSeries()
            series_avg.setName("Media Verifiche/Giorno")
            pen = QPen(QColor("#dc2626"))
            pen.setWidth(3)
            series_avg.setPen(pen)
            
            months_data = {f"{i:02d}": {"days": 0, "total": 0} for i in range(1, 13)}
            max_days = 0
            
            for row in data:
                mk = row['month']
                months_data[mk]['days'] = row['working_days'] or 0
                months_data[mk]['total'] = row['total_verifications'] or 0
                max_days = max(max_days, row['working_days'] or 0)
            
            for idx, mk in enumerate(sorted(months_data.keys())):
                set_days.append(months_data[mk]['days'])
                avg = months_data[mk]['total'] / months_data[mk]['days'] if months_data[mk]['days'] > 0 else 0
                series_avg.append(idx + 0.5, avg)  # centrato sulla barra
            
            bar_series = QBarSeries()
            bar_series.append(set_days)
            
            self.productivity_chart.addSeries(bar_series)
            self.productivity_chart.addSeries(series_avg)
            
            total_days = sum(months_data[m]['days'] for m in months_data)
            total_verif = sum(months_data[m]['total'] for m in months_data)
            avg_overall = total_verif / total_days if total_days > 0 else 0
            self.productivity_chart.setTitle(
                f"Produttività {year} — {total_days} giorni lavorativi, media {avg_overall:.1f} verifiche/giorno")
            
            months_cat = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", 
                         "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
            axis_x = QBarCategoryAxis()
            axis_x.append(months_cat)
            self.productivity_chart.addAxis(axis_x, Qt.AlignBottom)
            bar_series.attachAxis(axis_x)
            series_avg.attachAxis(axis_x)
            
            axis_y = QValueAxis()
            axis_y.setRange(0, max(max_days * 1.2, 1))
            axis_y.setLabelFormat("%d")
            axis_y.setTitleText("Giorni / Media")
            axis_y.applyNiceNumbers()
            self.productivity_chart.addAxis(axis_y, Qt.AlignLeft)
            bar_series.attachAxis(axis_y)
            series_avg.attachAxis(axis_y)
            
            self.productivity_chart.legend().setVisible(True)
            self.productivity_chart.legend().setAlignment(Qt.AlignBottom)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento produttività: {e}", exc_info=True)
    
    # =========================================================================
    # CLASSIFICHE
    # =========================================================================
    def _update_rankings(self):
        try:
            # --- Top Clienti ---
            self.clients_table.setRowCount(0)
            top_customers = services.get_top_customers_by_verifications(15)
            
            if top_customers:
                self.clients_table.setRowCount(len(top_customers))
                for row_idx, customer in enumerate(top_customers):
                    # Posizione
                    pos_item = QTableWidgetItem(self._get_medal_icon(row_idx + 1))
                    pos_item.setTextAlignment(Qt.AlignCenter)
                    self.clients_table.setItem(row_idx, 0, pos_item)
                    
                    # Nome
                    name_item = QTableWidgetItem(customer['customer_name'])
                    if row_idx < 3:
                        font = name_item.font()
                        font.setBold(True)
                        name_item.setFont(font)
                    self.clients_table.setItem(row_idx, 1, name_item)
                    
                    # Verifiche totali
                    total = customer['total_verifications']
                    verif_item = QTableWidgetItem(f"{total:,}")
                    verif_item.setTextAlignment(Qt.AlignCenter)
                    self.clients_table.setItem(row_idx, 2, verif_item)
                    
                    # Conformi
                    passed = customer.get('passed', 0) or 0
                    passed_item = QTableWidgetItem(f"{passed:,}")
                    passed_item.setTextAlignment(Qt.AlignCenter)
                    self.clients_table.setItem(row_idx, 3, passed_item)
                    
                    # % Conformità
                    rate = customer['conformity_rate'] or 0
                    rate_item = QTableWidgetItem(f"{rate:.1f}%")
                    rate_item.setTextAlignment(Qt.AlignCenter)
                    rate_item.setBackground(self._get_rate_color(rate))
                    self.clients_table.setItem(row_idx, 4, rate_item)
            
            # --- Top Tecnici ---
            self.techs_table.setRowCount(0)
            top_techs = services.get_top_technicians_by_verifications(15)
            
            if top_techs:
                self.techs_table.setRowCount(len(top_techs))
                for row_idx, tech in enumerate(top_techs):
                    pos_item = QTableWidgetItem(self._get_medal_icon(row_idx + 1))
                    pos_item.setTextAlignment(Qt.AlignCenter)
                    self.techs_table.setItem(row_idx, 0, pos_item)
                    
                    name_item = QTableWidgetItem(tech['technician_name'])
                    if row_idx < 3:
                        font = name_item.font()
                        font.setBold(True)
                        name_item.setFont(font)
                    self.techs_table.setItem(row_idx, 1, name_item)
                    
                    total = tech['total_verifications']
                    verif_item = QTableWidgetItem(f"{total:,}")
                    verif_item.setTextAlignment(Qt.AlignCenter)
                    self.techs_table.setItem(row_idx, 2, verif_item)
                    
                    passed = tech.get('passed', 0) or 0
                    passed_item = QTableWidgetItem(f"{passed:,}")
                    passed_item.setTextAlignment(Qt.AlignCenter)
                    self.techs_table.setItem(row_idx, 3, passed_item)
                    
                    rate = tech['conformity_rate'] or 0
                    rate_item = QTableWidgetItem(f"{rate:.1f}%")
                    rate_item.setTextAlignment(Qt.AlignCenter)
                    rate_item.setBackground(self._get_rate_color(rate))
                    self.techs_table.setItem(row_idx, 4, rate_item)
            
            # --- Top Tipologie Dispositivi ---
            self.device_types_table.setRowCount(0)
            top_types = services.get_top_device_types_by_verifications(15)
            
            if top_types:
                self.device_types_table.setRowCount(len(top_types))
                for row_idx, dtype in enumerate(top_types):
                    pos_item = QTableWidgetItem(self._get_medal_icon(row_idx + 1))
                    pos_item.setTextAlignment(Qt.AlignCenter)
                    self.device_types_table.setItem(row_idx, 0, pos_item)
                    
                    name_item = QTableWidgetItem(dtype['device_type'] or "N/D")
                    if row_idx < 3:
                        font = name_item.font()
                        font.setBold(True)
                        name_item.setFont(font)
                    self.device_types_table.setItem(row_idx, 1, name_item)
                    
                    total = dtype['total_verifications']
                    verif_item = QTableWidgetItem(f"{total:,}")
                    verif_item.setTextAlignment(Qt.AlignCenter)
                    self.device_types_table.setItem(row_idx, 2, verif_item)
                    
                    passed = dtype.get('passed', 0) or 0
                    passed_item = QTableWidgetItem(f"{passed:,}")
                    passed_item.setTextAlignment(Qt.AlignCenter)
                    self.device_types_table.setItem(row_idx, 3, passed_item)
                    
                    rate = dtype['conformity_rate'] or 0
                    rate_item = QTableWidgetItem(f"{rate:.1f}%")
                    rate_item.setTextAlignment(Qt.AlignCenter)
                    rate_item.setBackground(self._get_rate_color(rate))
                    self.device_types_table.setItem(row_idx, 4, rate_item)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento classifiche: {e}", exc_info=True)
    
    # =========================================================================
    # DASHBOARD OPERATIVA
    # =========================================================================
    def _update_dashboard_data(self):
        try:
            logging.info("Aggiornamento dashboard operativa...")
            
            # --- KPI operativi ---
            summary = services.get_dashboard_summary_stats()
            
            for key, label_widget in self.op_labels.items():
                val = summary.get(key, 'N/A')
                if isinstance(val, int):
                    label_widget.setText(f"<b style='font-size: 14px;'>{val:,}</b>")
                else:
                    label_widget.setText(f"<b style='font-size: 14px;'>{val}</b>")
            
            # Attività
            self.op_ve_total.setText(f"<b>{summary.get('verifications_electrical', 0):,}</b>")
            self.op_vf_total.setText(f"<b>{summary.get('verifications_functional', 0):,}</b>")
            self.op_ve_month.setText(f"<b>{summary.get('verifications_this_month', 0):,}</b>")
            self.op_vf_month.setText(f"<b>{summary.get('functional_verifications_this_month', 0):,}</b>")
            self.op_ve_today.setText(f"<b>{summary.get('verifications_today', 0):,}</b>")
            self.op_vf_today.setText(f"<b>{summary.get('functional_verifications_today', 0):,}</b>")
            
            # --- Scadenze verifiche ---
            self.scadenze_list.clear()
            devices_to_check = services.get_devices_needing_verification()
            
            expired_count = 0
            expiring_count = 0
            
            if not devices_to_check:
                item = QListWidgetItem("✅ Nessuna verifica in scadenza")
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
                    days_diff = today.daysTo(next_date)
                    
                    if days_diff < 0:
                        expired_count += 1
                        status_icon = "🔴"
                        days_text = f"Scaduta da {abs(days_diff)} giorni"
                    elif days_diff == 0:
                        expired_count += 1
                        status_icon = "🟠"
                        days_text = "Scade OGGI"
                    else:
                        expiring_count += 1
                        status_icon = "🟡"
                        days_text = f"Scade tra {days_diff} giorni"
                    
                    item_text = (
                        f"{status_icon} <b>{device.get('description', 'N/D')}</b> "
                        f"(S/N: {device.get('serial_number', 'N/D')})<br>"
                        f"<small>&nbsp;&nbsp;&nbsp;&nbsp;<i>{device.get('customer_name', 'N/D')}</i> — "
                        f"{next_date.toString('dd/MM/yyyy')} — <b>{days_text}</b></small>"
                    )
                    
                    list_item = QListWidgetItem()
                    label = QLabel(item_text)
                    
                    if days_diff < 0:
                        label.setStyleSheet("color: #dc2626; padding: 4px;")
                        list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_MessageBoxCritical))
                    elif days_diff <= 7:
                        label.setStyleSheet("color: #ea580c; font-weight: bold; padding: 4px;")
                        list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_MessageBoxWarning))
                    else:
                        label.setStyleSheet("color: #ca8a04; padding: 4px;")
                        list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_MessageBoxInformation))
                    
                    list_item.setSizeHint(label.sizeHint())
                    self.scadenze_list.addItem(list_item)
                    self.scadenze_list.setItemWidget(list_item, label)
            
            total_scadenze = expired_count + expiring_count
            self.scadenze_count_label.setText(
                f"<b style='color: #dc2626;'>🔴 {expired_count} scadute</b> | "
                f"<b style='color: #ca8a04;'>🟡 {expiring_count} in scadenza</b> | "
                f"Totale: <b>{total_scadenze}</b>"
            )
            
            # --- Strumenti in scadenza calibrazione ---
            self.instruments_list.clear()
            try:
                instruments_expiring = services.get_instruments_needing_calibration()
                
                inst_expired = 0
                inst_expiring = 0
                
                if not instruments_expiring:
                    item = QListWidgetItem("✅ Tutti gli strumenti hanno calibrazione valida")
                    item.setForeground(QColor("#16a34a"))
                    self.instruments_list.addItem(item)
                else:
                    today_date = date.today()
                    for inst in instruments_expiring:
                        exp_date_str = inst.get('expiration_date', '')
                        inst_name = inst.get('instrument_name', 'N/D')
                        inst_serial = inst.get('serial_number', 'N/D')
                        
                        try:
                            exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
                            days_left = (exp_date - today_date).days
                        except (ValueError, TypeError):
                            days_left = -999
                        
                        if days_left < 0:
                            inst_expired += 1
                            status_icon = "🔴"
                            days_text = f"Scaduta da {abs(days_left)} giorni"
                        elif days_left == 0:
                            inst_expired += 1
                            status_icon = "🟠"
                            days_text = "Scade OGGI"
                        else:
                            inst_expiring += 1
                            status_icon = "🟡"
                            days_text = f"Scade tra {days_left} giorni"
                        
                        item_text = (
                            f"{status_icon} <b>{inst_name}</b> (S/N: {inst_serial})<br>"
                            f"<small>&nbsp;&nbsp;&nbsp;&nbsp;Scadenza calibrazione: "
                            f"<b>{exp_date_str}</b> — {days_text}</small>"
                        )
                        
                        list_item = QListWidgetItem()
                        label = QLabel(item_text)
                        
                        if days_left < 0:
                            label.setStyleSheet("color: #dc2626; padding: 4px;")
                        elif days_left <= 7:
                            label.setStyleSheet("color: #ea580c; font-weight: bold; padding: 4px;")
                        else:
                            label.setStyleSheet("color: #ca8a04; padding: 4px;")
                        
                        list_item.setSizeHint(label.sizeHint())
                        self.instruments_list.addItem(list_item)
                        self.instruments_list.setItemWidget(list_item, label)
                
                self.instruments_count_label.setText(
                    f"<b style='color: #dc2626;'>🔴 {inst_expired} scadute</b> | "
                    f"<b style='color: #ca8a04;'>🟡 {inst_expiring} in scadenza</b>"
                )
            except Exception as e:
                logging.error(f"Errore caricamento strumenti: {e}", exc_info=True)
                self.instruments_count_label.setText("<i>Errore</i>")
            
            # --- Attività recente ---
            self.recent_table.setRowCount(0)
            try:
                recent = services.get_recent_verifications(25)
                
                if recent:
                    self.recent_table.setRowCount(len(recent))
                    for row_idx, row in enumerate(recent):
                        r = dict(row)
                        
                        # Data
                        date_item = QTableWidgetItem(r.get('verification_date', ''))
                        self.recent_table.setItem(row_idx, 0, date_item)
                        
                        # Tipo
                        tipo = r.get('tipo', '')
                        tipo_item = QTableWidgetItem("⚡ VE" if tipo == 'elettrica' else "⚙️ VF")
                        tipo_item.setTextAlignment(Qt.AlignCenter)
                        self.recent_table.setItem(row_idx, 1, tipo_item)
                        
                        # Esito
                        status = r.get('overall_status', '')
                        status_item = QTableWidgetItem("✅ PASSATO" if status == 'PASSATO' else "❌ FALLITO")
                        status_item.setTextAlignment(Qt.AlignCenter)
                        if status == 'PASSATO':
                            status_item.setBackground(QColor("#dcfce7"))
                        else:
                            status_item.setBackground(QColor("#fee2e2"))
                        self.recent_table.setItem(row_idx, 2, status_item)
                        
                        # Dispositivo
                        dev_text = r.get('device_desc', 'N/D') or 'N/D'
                        sn = r.get('serial_number', '')
                        if sn:
                            dev_text += f" (S/N: {sn})"
                        dev_item = QTableWidgetItem(dev_text)
                        self.recent_table.setItem(row_idx, 3, dev_item)
                        
                        # Cliente
                        cust_item = QTableWidgetItem(r.get('customer_name', 'N/D') or 'N/D')
                        self.recent_table.setItem(row_idx, 4, cust_item)
                        
                        # Tecnico
                        tech_item = QTableWidgetItem(r.get('technician_name', 'N/D') or 'N/D')
                        self.recent_table.setItem(row_idx, 5, tech_item)
            except Exception as e:
                logging.error(f"Errore caricamento attività recente: {e}", exc_info=True)
            
            logging.info("Dashboard operativa aggiornata con successo")
            
        except Exception as e:
            logging.error(f"Errore aggiornamento dashboard operativa: {e}", exc_info=True)
    
    # =========================================================================
    # EXPORT
    # =========================================================================
    def export_report(self):
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
            
            # Raccogli dati
            ve_stats = services.get_verification_stats()
            vf_stats = services.get_functional_verification_stats()
            ve_monthly = services.get_verification_stats_by_month(year)
            vf_monthly = services.get_functional_verification_stats_by_month(year)
            summary = services.get_dashboard_summary_stats()
            top_customers = services.get_top_customers_by_verifications(20)
            top_techs = services.get_top_technicians_by_verifications(20)
            top_types = services.get_top_device_types_by_verifications(20)
            
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                # Riepilogo Generale
                df_summary = pd.DataFrame([{
                    'Clienti': summary.get('customers', 0),
                    'Destinazioni': summary.get('destinations', 0),
                    'Dispositivi Attivi': summary.get('devices_active', 0),
                    'Dispositivi Dismessi': summary.get('devices_decommissioned', 0),
                    'Strumenti MTI': summary.get('instruments', 0),
                    'Profili Elettrici': summary.get('profiles_electrical', 0),
                    'Profili Funzionali': summary.get('profiles_functional', 0),
                    'VE Totali': ve_stats.get('totale', 0),
                    'VE Conformi': ve_stats.get('conformi', 0),
                    'VE Non Conformi': ve_stats.get('non_conformi', 0),
                    'VF Totali': vf_stats.get('totale', 0),
                    'VF Conformi': vf_stats.get('conformi', 0),
                    'VF Non Conformi': vf_stats.get('non_conformi', 0),
                    'Ultima Verifica': summary.get('last_verification', 'N/A'),
                }])
                df_summary.to_excel(writer, sheet_name='Riepilogo', index=False)
                
                # Verifiche Elettriche per Mese
                if ve_monthly:
                    df_ve = pd.DataFrame([dict(row) for row in ve_monthly])
                    df_ve.to_excel(writer, sheet_name='VE Mensile', index=False)
                
                # Verifiche Funzionali per Mese
                if vf_monthly:
                    df_vf = pd.DataFrame([dict(row) for row in vf_monthly])
                    df_vf.to_excel(writer, sheet_name='VF Mensile', index=False)
                
                # Top Clienti
                if top_customers:
                    df_cust = pd.DataFrame([dict(row) for row in top_customers])
                    df_cust.to_excel(writer, sheet_name='Top Clienti', index=False)
                
                # Top Tecnici
                if top_techs:
                    df_tech = pd.DataFrame([dict(row) for row in top_techs])
                    df_tech.to_excel(writer, sheet_name='Top Tecnici', index=False)
                
                # Top Tipologie
                if top_types:
                    df_types = pd.DataFrame([dict(row) for row in top_types])
                    df_types.to_excel(writer, sheet_name='Top Tipologie', index=False)
            
            QApplication.restoreOverrideCursor()
            QMessageBox.information(
                self,
                "Esportazione Completata",
                f"Report esportato con successo in:\n{file_path}\n\n"
                f"Fogli inclusi: Riepilogo, VE Mensile, VF Mensile, "
                f"Top Clienti, Top Tecnici, Top Tipologie"
            )

        except Exception as e:
            QApplication.restoreOverrideCursor()
            logging.error(f"Errore esportazione report: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile esportare il report:\n{str(e)}")
