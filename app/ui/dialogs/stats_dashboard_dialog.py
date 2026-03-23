# app/ui/dialogs/stats_dashboard_dialog.py
from datetime import datetime, date, timedelta
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QSpinBox, QLabel, QWidget, 
                               QSizePolicy, QGroupBox, QGridLayout, QPushButton, QComboBox, QTabWidget,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
                               QMessageBox, QApplication, QFormLayout, QListWidget, QListWidgetItem, QStyle,
                               QScrollArea, QFrame, QProgressBar, QSplitter, QToolTip)
from PySide6.QtCharts import (QChart, QChartView, QBarSet, QPercentBarSeries, QBarCategoryAxis,
                              QPieSeries, QPieSlice, QLineSeries, QValueAxis, QBarSeries,
                              QStackedBarSeries)
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QCursor
from PySide6.QtCore import Qt, QDate, QTimer

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
        
        # Tab 1: Panoramica (solo KPI)
        overview_tab = self._create_overview_tab()
        self.tabs.addTab(overview_tab, qta.icon('fa5s.tachometer-alt'), " Panoramica")
        
        # Tab 2: Conformità (grafici torta VE + VF)
        conformity_tab = self._create_conformity_tab()
        self.tabs.addTab(conformity_tab, qta.icon('fa5s.chart-pie'), " Conformità")
        
        # Tab 3: Andamento Mensile (barre mensili)
        monthly_tab = self._create_monthly_tab()
        self.tabs.addTab(monthly_tab, qta.icon('fa5s.calendar-alt'), " Andamento Mensile")
        
        # Tab 4: Trend & Confronto (trend + confronto anno)
        trend_tab = self._create_trend_tab()
        self.tabs.addTab(trend_tab, qta.icon('fa5s.chart-line'), " Trend & Confronto")
        
        # Tab 5: Produttività
        prod_tab = self._create_productivity_tab()
        self.tabs.addTab(prod_tab, qta.icon('fa5s.chart-bar'), " Produttività")
        
        # Tab 6: Classifiche
        rankings_tab = self._create_rankings_tab()
        self.tabs.addTab(rankings_tab, qta.icon('fa5s.trophy'), " Classifiche")
        
        # Tab 7: Dashboard Operativa
        dashboard_tab = self._create_dashboard_tab()
        self.tabs.addTab(dashboard_tab, qta.icon('fa5s.clipboard-list'), " Dashboard Operativa")
        
        main_layout.addWidget(self.tabs)

        # Overlay di caricamento
        self._loading_overlay = _DashboardLoadingOverlay(self)
        self._loading_overlay.hide()

        self.setWindowState(Qt.WindowMaximized)

        # Caricamento differito: mostra prima la finestra, poi carica i dati
        QTimer.singleShot(100, self._deferred_load)

    def _deferred_load(self):
        """Carica i dati dopo che la finestra è stata visualizzata."""
        self._loading_overlay.show_message("Caricamento statistiche in corso...")
        QApplication.processEvents()
        try:
            self.update_all_data()
        finally:
            self._loading_overlay.hide()

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
    # TAB 1: PANORAMICA (solo KPI)
    # =========================================================================
    def _create_overview_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)
        
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
        
        # Spacer per centrare i KPI verticalmente
        layout.addStretch(1)
        
        return widget
    
    # =========================================================================
    # TAB 2: CONFORMITÀ (torte VE + VF)
    # =========================================================================
    def _create_conformity_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setSpacing(16)
        
        # Grafico a torta conformità elettriche
        pie_group = QGroupBox("Distribuzione Esiti Verifiche Elettriche")
        pie_layout = QVBoxLayout(pie_group)
        self.pie_chart = QChart()
        self.pie_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.pie_chart_view = QChartView(self.pie_chart)
        self.pie_chart_view.setRenderHint(QPainter.Antialiasing)
        self.pie_chart_view.setMinimumHeight(500)
        pie_layout.addWidget(self.pie_chart_view)
        layout.addWidget(pie_group)
        
        # Grafico a torta conformità funzionale
        pie_func_group = QGroupBox("Distribuzione Esiti Verifiche Funzionali")
        pie_func_layout = QVBoxLayout(pie_func_group)
        self.pie_func_chart = QChart()
        self.pie_func_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.pie_func_chart_view = QChartView(self.pie_func_chart)
        self.pie_func_chart_view.setRenderHint(QPainter.Antialiasing)
        self.pie_func_chart_view.setMinimumHeight(500)
        pie_func_layout.addWidget(self.pie_func_chart_view)
        layout.addWidget(pie_func_group)
        
        return widget
    
    # =========================================================================
    # TAB 3: ANDAMENTO MENSILE (barre stacked)
    # =========================================================================
    def _create_monthly_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        monthly_group = QGroupBox("Andamento Mensile Verifiche")
        monthly_layout = QVBoxLayout(monthly_group)
        self.monthly_chart = QChart()
        self.monthly_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.monthly_chart_view = QChartView(self.monthly_chart)
        self.monthly_chart_view.setRenderHint(QPainter.Antialiasing)
        monthly_layout.addWidget(self.monthly_chart_view)
        layout.addWidget(monthly_group)
        
        return widget
    
    # =========================================================================
    # TAB 4: TREND & CONFRONTO
    # =========================================================================
    def _create_trend_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        
        # Grafico trend (occupa metà superiore)
        trend_group = QGroupBox("Andamento Verifiche per Mese")
        trend_layout = QVBoxLayout(trend_group)
        self.trend_chart = QChart()
        self.trend_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.trend_chart_view = QChartView(self.trend_chart)
        self.trend_chart_view.setRenderHint(QPainter.Antialiasing)
        self.trend_chart_view.setMinimumHeight(350)
        trend_layout.addWidget(self.trend_chart_view)
        layout.addWidget(trend_group)
        
        # Confronto anno precedente (occupa metà inferiore)
        comparison_group = QGroupBox("Confronto con Anno Precedente")
        comparison_layout = QVBoxLayout(comparison_group)
        self.comparison_chart = QChart()
        self.comparison_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.comparison_chart_view = QChartView(self.comparison_chart)
        self.comparison_chart_view.setRenderHint(QPainter.Antialiasing)
        self.comparison_chart_view.setMinimumHeight(350)
        comparison_layout.addWidget(self.comparison_chart_view)
        layout.addWidget(comparison_group)
        
        return widget
    
    # =========================================================================
    # TAB 5: PRODUTTIVITÀ
    # =========================================================================
    def _create_productivity_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        productivity_group = QGroupBox("Produttività Mensile (Giorni Lavorativi e Media Verifiche/Giorno)")
        productivity_layout = QVBoxLayout(productivity_group)
        self.productivity_chart = QChart()
        self.productivity_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.productivity_chart_view = QChartView(self.productivity_chart)
        self.productivity_chart_view.setRenderHint(QPainter.Antialiasing)
        productivity_layout.addWidget(self.productivity_chart_view)
        layout.addWidget(productivity_group)
        
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
        main_layout.setSpacing(12)
        
        # --- Riga superiore: KPI operativi con card ---
        top_section = QVBoxLayout()
        
        # Riga 1: Riepilogo Generale (4 card)
        row1_label = QLabel("<b>📊 Riepilogo Generale</b>")
        row1_label.setStyleSheet("font-size: 14px; padding: 4px 0;")
        top_section.addWidget(row1_label)
        
        kpi_row1 = QHBoxLayout()
        kpi_row1.setSpacing(10)
        
        self.op_card_customers = self._create_kpi_card(
            "Clienti", "...", qta.icon('fa5s.hospital'), "#2563eb")
        kpi_row1.addWidget(self.op_card_customers)
        
        self.op_card_destinations = self._create_kpi_card(
            "Destinazioni", "...", qta.icon('fa5s.map-marker-alt'), "#0891b2")
        kpi_row1.addWidget(self.op_card_destinations)
        
        self.op_card_devices_active = self._create_kpi_card(
            "Dispositivi Attivi", "...", qta.icon('fa5s.laptop-medical'), "#16a34a")
        kpi_row1.addWidget(self.op_card_devices_active)
        
        self.op_card_decommissioned = self._create_kpi_card(
            "Dismessi", "...", qta.icon('fa5s.power-off'), "#64748b")
        kpi_row1.addWidget(self.op_card_decommissioned)
        
        top_section.addLayout(kpi_row1)
        
        # Riga 2: Strumenti, Profili, Verifiche periodo (5 card)
        kpi_row2 = QHBoxLayout()
        kpi_row2.setSpacing(10)
        
        self.op_card_instruments = self._create_kpi_card(
            "Strumenti MTI", "...", qta.icon('fa5s.tools'), "#ea580c")
        kpi_row2.addWidget(self.op_card_instruments)
        
        self.op_card_profiles_el = self._create_kpi_card(
            "Profili Elettrici", "...", qta.icon('fa5s.bolt'), "#7c3aed")
        kpi_row2.addWidget(self.op_card_profiles_el)
        
        self.op_card_profiles_fn = self._create_kpi_card(
            "Profili Funzionali", "...", qta.icon('fa5s.cogs'), "#be185d")
        kpi_row2.addWidget(self.op_card_profiles_fn)
        
        self.op_card_last_verif = self._create_kpi_card(
            "Ultima Verifica", "...", qta.icon('fa5s.calendar'), "#4f46e5")
        kpi_row2.addWidget(self.op_card_last_verif)
        
        top_section.addLayout(kpi_row2)
        
        # Riga 3: Attività periodo (6 card)
        row3_label = QLabel("<b>📈 Attività Periodo</b>")
        row3_label.setStyleSheet("font-size: 14px; padding: 4px 0;")
        top_section.addWidget(row3_label)
        
        kpi_row3 = QHBoxLayout()
        kpi_row3.setSpacing(10)
        
        self.op_card_ve_total = self._create_kpi_card(
            "VE Totali", "...", qta.icon('fa5s.bolt'), "#2563eb")
        kpi_row3.addWidget(self.op_card_ve_total)
        
        self.op_card_vf_total = self._create_kpi_card(
            "VF Totali", "...", qta.icon('fa5s.cogs'), "#7c3aed")
        kpi_row3.addWidget(self.op_card_vf_total)
        
        self.op_card_ve_month = self._create_kpi_card(
            "VE Questo Mese", "...", qta.icon('fa5s.calendar-check'), "#0891b2")
        kpi_row3.addWidget(self.op_card_ve_month)
        
        self.op_card_vf_month = self._create_kpi_card(
            "VF Questo Mese", "...", qta.icon('fa5s.calendar-check'), "#be185d")
        kpi_row3.addWidget(self.op_card_vf_month)
        
        self.op_card_ve_today = self._create_kpi_card(
            "VE Oggi", "...", qta.icon('fa5s.clock'), "#16a34a")
        kpi_row3.addWidget(self.op_card_ve_today)
        
        self.op_card_vf_today = self._create_kpi_card(
            "VF Oggi", "...", qta.icon('fa5s.clock'), "#ea580c")
        kpi_row3.addWidget(self.op_card_vf_today)
        
        top_section.addLayout(kpi_row3)
        
        main_layout.addLayout(top_section)
        
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
    # HOVER HELPERS (tooltip interattivi sui grafici)
    # =========================================================================
    _MONTHS_NAMES = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
                     "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

    def _on_pie_hovered(self, pie_slice, state):
        """Effetto hover sulle fette della torta: esplode e mostra tooltip."""
        pie_slice.setExploded(state)
        pie_slice.setExplodeDistanceFactor(0.07)
        if state:
            pct = pie_slice.percentage() * 100
            QToolTip.showText(
                QCursor.pos(),
                f"{pie_slice.label()}\n{pct:.1f}% del totale"
            )

    def _on_bar_hovered(self, status, index, barset):
        """Tooltip hover sulle barre: mostra nome serie, mese e valore."""
        if status:
            month_name = self._MONTHS_NAMES[index + 1] if 0 <= index < 12 else str(index)
            value = int(barset.at(index))
            QToolTip.showText(
                QCursor.pos(),
                f"{barset.label()}\n{month_name}: {value}"
            )

    def _on_line_hovered(self, point, state, series_name):
        """Tooltip hover sui punti delle linee: mostra nome serie, mese e valore."""
        if state:
            month_idx = int(round(point.x()))
            month_name = self._MONTHS_NAMES[month_idx] if 0 < month_idx <= 12 else str(month_idx)
            QToolTip.showText(
                QCursor.pos(),
                f"{series_name}\n{month_name}: {int(point.y())}"
            )

    # =========================================================================
    # UPDATE ALL
    # =========================================================================
    def update_all_data(self):
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Mostra overlay se disponibile (non durante __init__ iniziale)
            if hasattr(self, '_loading_overlay') and not self._loading_overlay.isVisible():
                self._loading_overlay.show_message("Aggiornamento statistiche in corso...")
                QApplication.processEvents()
            
            selected_year = self.year_spinbox.value()
            
            self._update_kpi()
            QApplication.processEvents()
            self._update_pie_chart()
            self._update_pie_func_chart()
            QApplication.processEvents()
            self._update_monthly_chart(selected_year)
            QApplication.processEvents()
            self._update_trend_chart(selected_year)
            self._update_comparison_chart(selected_year)
            QApplication.processEvents()
            self._update_productivity_chart(selected_year)
            QApplication.processEvents()
            self._update_rankings()
            self._update_dashboard_data()
            
        except Exception as e:
            logging.error(f"Errore durante l'aggiornamento della dashboard: {e}", exc_info=True)
            QMessageBox.critical(self, "Errore", f"Impossibile aggiornare la dashboard:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
            if hasattr(self, '_loading_overlay'):
                self._loading_overlay.hide()
    
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
            
            series.hovered.connect(self._on_pie_hovered)
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
            
            series.hovered.connect(self._on_pie_hovered)
            self.pie_func_chart.addSeries(series)
            rate = conformi / total * 100 if total > 0 else 0
            self.pie_func_chart.setTitle(f"Verifiche Funzionali — {rate:.1f}% conformi (tot: {total})")
            self.pie_func_chart.legend().setVisible(True)
            self.pie_func_chart.legend().setAlignment(Qt.AlignBottom)
            
        except Exception as e:
            logging.error(f"Errore aggiornamento grafico torta VF: {e}", exc_info=True)
    
    def _update_monthly_chart(self, year):
        """Grafico barre mensile: 4 barre raggruppate + linea totale + linea % conformità."""
        try:
            self.monthly_chart.removeAllSeries()
            for axis in self.monthly_chart.axes():
                self.monthly_chart.removeAxis(axis)
            
            ve_stats = services.get_verification_stats_by_month(year)
            vf_stats = services.get_functional_verification_stats_by_month(year)
            
            if not ve_stats and not vf_stats:
                self.monthly_chart.setTitle(f"Nessuna verifica per l'anno {year}")
                return

            # --- Raccogli dati per mese ---
            months_ve = {f"{i:02d}": {"passed": 0, "failed": 0} for i in range(1, 13)}
            months_vf = {f"{i:02d}": {"passed": 0, "failed": 0} for i in range(1, 13)}
            
            for row in (ve_stats or []):
                months_ve[row['month']]['passed'] = row['passed'] or 0
                months_ve[row['month']]['failed'] = row['failed'] or 0
            
            for row in (vf_stats or []):
                months_vf[row['month']]['passed'] = row['passed'] or 0
                months_vf[row['month']]['failed'] = row['failed'] or 0

            # --- 4 Bar Sets raggruppati ---
            set_ve_ok = QBarSet("VE Conformi")
            set_ve_ko = QBarSet("VE Non Conformi")
            set_vf_ok = QBarSet("VF Conformi")
            set_vf_ko = QBarSet("VF Non Conformi")
            
            set_ve_ok.setColor(QColor("#2563eb"))
            set_ve_ko.setColor(QColor("#dc2626"))
            set_vf_ok.setColor(QColor("#7c3aed"))
            set_vf_ko.setColor(QColor("#e11d48"))

            # --- Linea totale ---
            line_total = QLineSeries()
            line_total.setName("Totale mensile")
            pen_total = QPen(QColor("#16a34a"))
            pen_total.setWidth(3)
            line_total.setPen(pen_total)
            line_total.setPointsVisible(True)

            # --- Linea % conformità ---
            line_rate = QLineSeries()
            line_rate.setName("% Conformità")
            pen_rate = QPen(QColor("#f59e0b"))
            pen_rate.setWidth(3)
            pen_rate.setStyle(Qt.DashLine)
            line_rate.setPen(pen_rate)
            line_rate.setPointsVisible(True)

            max_value = 0
            month_keys = sorted(months_ve.keys())

            for idx, mk in enumerate(month_keys):
                ve_p = months_ve[mk]['passed']
                ve_f = months_ve[mk]['failed']
                vf_p = months_vf[mk]['passed']
                vf_f = months_vf[mk]['failed']
                
                set_ve_ok.append(ve_p)
                set_ve_ko.append(ve_f)
                set_vf_ok.append(vf_p)
                set_vf_ko.append(vf_f)
                
                grand = ve_p + ve_f + vf_p + vf_f
                line_total.append(idx + 0.5, grand)
                
                # % conformità del mese
                total_ok = ve_p + vf_p
                rate_m = (total_ok / grand * 100) if grand > 0 else 0
                line_rate.append(idx + 0.5, rate_m)
                
                max_value = max(max_value, grand)

            bar_series = QBarSeries()
            bar_series.append(set_ve_ok)
            bar_series.append(set_ve_ko)
            bar_series.append(set_vf_ok)
            bar_series.append(set_vf_ko)
            bar_series.setLabelsVisible(True)
            bar_series.setLabelsPosition(QBarSeries.LabelsOutsideEnd)
            bar_series.setLabelsFormat("@value")
            bar_series.hovered.connect(self._on_bar_hovered)

            line_total.hovered.connect(
                lambda pt, st: self._on_line_hovered(pt, st, "Totale")
            )
            line_rate.hovered.connect(
                lambda pt, st: self._on_line_hovered(pt, st, "% Conformità")
            )

            self.monthly_chart.addSeries(bar_series)
            self.monthly_chart.addSeries(line_total)
            self.monthly_chart.addSeries(line_rate)

            # --- Titolo riepilogativo ---
            total_ve = sum(months_ve[m]['passed'] + months_ve[m]['failed'] for m in months_ve)
            total_vf = sum(months_vf[m]['passed'] + months_vf[m]['failed'] for m in months_vf)
            total_all = total_ve + total_vf
            total_ok_year = sum(months_ve[m]['passed'] + months_vf[m]['passed'] for m in months_ve)
            rate_year = (total_ok_year / total_all * 100) if total_all > 0 else 0
            self.monthly_chart.setTitle(
                f"Andamento Mensile — {year}  |  "
                f"VE: {total_ve}  |  VF: {total_vf}  |  "
                f"Totale: {total_all}  |  Conformità: {rate_year:.1f}%"
            )

            # --- Asse X ---
            months_cat = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
                         "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
            axis_x = QBarCategoryAxis()
            axis_x.append(months_cat)
            axis_x.setLabelsFont(QFont("Segoe UI", 9, QFont.Bold))
            self.monthly_chart.addAxis(axis_x, Qt.AlignBottom)
            bar_series.attachAxis(axis_x)
            line_total.attachAxis(axis_x)
            line_rate.attachAxis(axis_x)

            # --- Asse Y sinistro (conteggio verifiche) ---
            axis_y = QValueAxis()
            axis_y.setRange(0, max(max_value * 1.3, 1))
            axis_y.setLabelFormat("%d")
            axis_y.setTitleText("Numero Verifiche")
            axis_y.setGridLineVisible(True)
            axis_y.setMinorGridLineVisible(True)
            axis_y.setMinorTickCount(1)
            axis_y.applyNiceNumbers()
            self.monthly_chart.addAxis(axis_y, Qt.AlignLeft)
            bar_series.attachAxis(axis_y)
            line_total.attachAxis(axis_y)

            # --- Asse Y destro (percentuale conformità) ---
            axis_y_pct = QValueAxis()
            axis_y_pct.setRange(0, 105)
            axis_y_pct.setLabelFormat("%d%%")
            axis_y_pct.setTitleText("% Conformità")
            axis_y_pct.setTickCount(6)  # 0, 20, 40, 60, 80, 100
            axis_y_pct.setGridLineVisible(False)
            self.monthly_chart.addAxis(axis_y_pct, Qt.AlignRight)
            line_rate.attachAxis(axis_y_pct)

            # --- Legenda ---
            self.monthly_chart.legend().setVisible(True)
            self.monthly_chart.legend().setAlignment(Qt.AlignBottom)
            self.monthly_chart.legend().setFont(QFont("Segoe UI", 9))

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
            
            # Punti visibili e tooltip hover
            for s in [series_ve, series_vf, series_total]:
                s.setPointsVisible(True)
                s.hovered.connect(lambda pt, st, name=s.name(): self._on_line_hovered(pt, st, name))
            
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
            series.hovered.connect(self._on_bar_hovered)
            
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
            bar_series.hovered.connect(self._on_bar_hovered)
            series_avg.setPointsVisible(True)
            series_avg.hovered.connect(lambda pt, st: self._on_line_hovered(pt, st, series_avg.name()))
            
            self.productivity_chart.addSeries(bar_series)
            self.productivity_chart.addSeries(series_avg)
            
            total_days = sum(months_data[m]['days'] for m in months_data)
            total_verif = sum(months_data[m]['total'] for m in months_data)
            avg_overall = total_verif / total_days if total_days > 0 else 0
            self.productivity_chart.setTitle(
                f"Produttività {year} — {total_days} giorni lavorativi, media {avg_overall:.1f} verifiche/giorno")
            
            # Calcola il massimo della media verifiche/giorno
            max_avg = 0
            for mk in sorted(months_data.keys()):
                if months_data[mk]['days'] > 0:
                    avg_val = months_data[mk]['total'] / months_data[mk]['days']
                    max_avg = max(max_avg, avg_val)
            
            months_cat = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", 
                         "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
            axis_x = QBarCategoryAxis()
            axis_x.append(months_cat)
            self.productivity_chart.addAxis(axis_x, Qt.AlignBottom)
            bar_series.attachAxis(axis_x)
            series_avg.attachAxis(axis_x)
            
            # Asse sinistro: Giorni Lavorativi (barre)
            axis_y_left = QValueAxis()
            axis_y_left.setRange(0, max(max_days * 1.2, 1))
            axis_y_left.setLabelFormat("%d")
            axis_y_left.setTitleText("Giorni Lavorativi")
            axis_y_left.applyNiceNumbers()
            self.productivity_chart.addAxis(axis_y_left, Qt.AlignLeft)
            bar_series.attachAxis(axis_y_left)
            
            # Asse destro: Media Verifiche/Giorno (linea)
            axis_y_right = QValueAxis()
            axis_y_right.setRange(0, max(max_avg * 1.3, 1))
            axis_y_right.setLabelFormat("%.1f")
            axis_y_right.setTitleText("Media Verifiche/Giorno")
            axis_y_right.applyNiceNumbers()
            self.productivity_chart.addAxis(axis_y_right, Qt.AlignRight)
            series_avg.attachAxis(axis_y_right)
            
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
                for row_idx, customer_row in enumerate(top_customers):
                    customer = dict(customer_row)
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
                for row_idx, tech_row in enumerate(top_techs):
                    tech = dict(tech_row)
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
                for row_idx, dtype_row in enumerate(top_types):
                    dtype = dict(dtype_row)
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
            
            # Riepilogo Generale - card
            card_mapping = {
                'customers': self.op_card_customers,
                'destinations': self.op_card_destinations,
                'devices_active': self.op_card_devices_active,
                'devices_decommissioned': self.op_card_decommissioned,
                'instruments': self.op_card_instruments,
                'profiles_electrical': self.op_card_profiles_el,
                'profiles_functional': self.op_card_profiles_fn,
                'last_verification': self.op_card_last_verif,
            }
            
            for key, card in card_mapping.items():
                val = summary.get(key, 'N/A')
                if isinstance(val, int):
                    card.value_label.setText(f"{val:,}")
                else:
                    card.value_label.setText(str(val))
            
            # Attività Periodo - card
            ve_total = summary.get('verifications_electrical', 0)
            vf_total = summary.get('verifications_functional', 0)
            ve_month = summary.get('verifications_this_month', 0)
            vf_month = summary.get('functional_verifications_this_month', 0)
            ve_today = summary.get('verifications_today', 0)
            vf_today = summary.get('functional_verifications_today', 0)
            
            self.op_card_ve_total.value_label.setText(f"{ve_total:,}")
            self.op_card_vf_total.value_label.setText(f"{vf_total:,}")
            self.op_card_ve_month.value_label.setText(f"{ve_month:,}")
            self.op_card_vf_month.value_label.setText(f"{vf_month:,}")
            self.op_card_ve_today.value_label.setText(f"{ve_today:,}")
            self.op_card_vf_today.value_label.setText(f"{vf_today:,}")
            
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


class _DashboardLoadingOverlay(QWidget):
    """Overlay semitrasparente con spinner e messaggio di caricamento per la dashboard."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Container centrale con sfondo
        container = QWidget()
        container.setFixedSize(320, 200)
        container.setStyleSheet("""
            QWidget {
                background-color: rgba(30, 30, 30, 220);
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 40);
            }
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setAlignment(Qt.AlignCenter)
        container_layout.setSpacing(16)
        
        # Spinner animato con QMovie (stessa GIF dell'overlay sync)
        from PySide6.QtGui import QMovie
        from PySide6.QtCore import QSize
        self._spinner_label = QLabel()
        self._spinner_label.setAlignment(Qt.AlignCenter)
        self._spinner_label.setStyleSheet("background: transparent; border: none;")
        self._movie = QMovie("./icons/loading.gif")
        self._movie.setScaledSize(QSize(80, 80))
        self._spinner_label.setMovie(self._movie)
        container_layout.addWidget(self._spinner_label)
        
        # Messaggio
        self._message_label = QLabel("Caricamento in corso...")
        self._message_label.setAlignment(Qt.AlignCenter)
        self._message_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 15px;
                font-weight: bold;
                background: transparent;
                border: none;
            }
        """)
        container_layout.addWidget(self._message_label)
        
        layout.addWidget(container)
    
    def show_message(self, text: str):
        """Mostra l'overlay con il messaggio specificato."""
        self._message_label.setText(text)
        if self.parent():
            self.setGeometry(self.parent().rect())
            self.raise_()
        self._movie.start()
        self.show()
    
    def hide(self):
        """Nasconde l'overlay e ferma l'animazione."""
        self._movie.stop()
        super().hide()
    
    def paintEvent(self, event):
        """Disegna lo sfondo semitrasparente."""
        from PySide6.QtGui import QPainter, QColor
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        painter.end()
        super().paintEvent(event)
