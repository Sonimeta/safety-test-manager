"""Logica pura di valutazione per il Controllo Qualità Sonde Ecografo.

Implementa i criteri del manuale di qualità per apparecchio ecografico:
- Ispezione visiva: BUONO/SUFFICIENTE/INSUFFICIENTE
- Uniformità: BUONO/SUFFICIENTE/INSUFFICIENTE
- Profondità massima di penetrazione in base alla frequenza
- Misure verticali: scarto < 1,5 mm fra due misure contigue
- Misure orizzontali: scarto < 2 mm fra due misure contigue
- Zona morta in base alla frequenza
- Risoluzione assiale/laterale a 3 cm e 11 cm
- Analisi masse anecoiche/iperecogene (senza limiti standardizzati)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.ecografo_quality_models import (
    EcografoQualityCheck,
    EcografoQualityControl,
    EcografoQualityProbe,
)


# ─── Chiavi dei controlli previsti dal manuale ───────────────────────────────

CONTROL_INSPECTION = "ispezione_visiva"
CONTROL_UNIFORMITY = "uniformita"
CONTROL_MAX_DEPTH = "profondita_max"
CONTROL_VERTICAL_MEASURES = "misure_verticali"
CONTROL_HORIZONTAL_MEASURES = "misure_orizzontali"
CONTROL_DEAD_ZONE = "zona_morta"
CONTROL_RESOLUTION_3CM_AXIAL = "risoluzione_3cm_assiale"
CONTROL_RESOLUTION_3CM_LATERAL = "risoluzione_3cm_laterale"
CONTROL_RESOLUTION_11CM_AXIAL = "risoluzione_11cm_assiale"
CONTROL_RESOLUTION_11CM_LATERAL = "risoluzione_11cm_laterale"
CONTROL_ANECHOIC_MASS = "massa_anecoica"
CONTROL_HYPOERECHOIC_MASS = "massa_iperecogena"


# ─── Helper di parsing numerico ──────────────────────────────────────────────

def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(value: Any) -> Optional[int]:
    f = _parse_float(value)
    if f is None:
        return None
    return int(f)


# ─── Definizione dei controlli standard ──────────────────────────────────────

@dataclass
class ControlDefinition:
    key: str
    label: str
    unit: Optional[str] = None
    requires_passed: bool = True


DEFAULT_CONTROLS: List[ControlDefinition] = [
    ControlDefinition(CONTROL_INSPECTION, "Ispezione visiva"),
    ControlDefinition(CONTROL_UNIFORMITY, "Uniformità"),
    ControlDefinition(CONTROL_MAX_DEPTH, "Profondità max", unit="cm"),
    ControlDefinition(CONTROL_VERTICAL_MEASURES, "Misure verticali", unit="mm"),
    ControlDefinition(CONTROL_HORIZONTAL_MEASURES, "Misure orizzontali", unit="mm"),
    ControlDefinition(CONTROL_DEAD_ZONE, "Zona morta", unit="mm"),
    ControlDefinition(CONTROL_RESOLUTION_3CM_AXIAL, "Risoluzione assiale 3 cm", unit="mm"),
    ControlDefinition(CONTROL_RESOLUTION_3CM_LATERAL, "Risoluzione laterale 3 cm", unit="mm"),
    ControlDefinition(CONTROL_RESOLUTION_11CM_AXIAL, "Risoluzione assiale 11 cm", unit="mm"),
    ControlDefinition(CONTROL_RESOLUTION_11CM_LATERAL, "Risoluzione laterale 11 cm", unit="mm"),
    ControlDefinition(CONTROL_ANECHOIC_MASS, "Massa anecoica", unit="mm²"),
    ControlDefinition(CONTROL_HYPOERECHOIC_MASS, "Massa iperecogena", unit="mm²"),
]


def get_default_controls() -> List[EcografoQualityControl]:
    """Restituisce i controlli vuoti di default per una nuova sonda."""
    return [
        EcografoQualityControl(
            control_key=defn.key,
            control_label=defn.label,
            unit=defn.unit,
        )
        for defn in DEFAULT_CONTROLS
    ]


# ─── Valutazione singoli controlli ───────────────────────────────────────────

def evaluate_inspection(value: Optional[str]) -> Optional[bool]:
    if not value:
        return None
    v = str(value).strip().upper()
    if v in ("BUONO", "B"):
        return True
    if v in ("SUFFICIENTE", "S"):
        return True
    if v in ("INSUFFICIENTE", "I", "KO"):
        return False
    return None


def evaluate_uniformity(value: Optional[str]) -> Optional[bool]:
    return evaluate_inspection(value)


def evaluate_max_depth(value: Optional[str], frequency_mhz: Optional[float] = None) -> Tuple[Optional[bool], Optional[str]]:
    """Valuta la profondità massima in base alla frequenza del trasduttore.

    Ritorna (passed, note).
    """
    depth = _parse_float(value)
    if depth is None:
        return None, None

    if frequency_mhz is None:
        # Se non conosciamo la frequenza, non possiamo valutare automaticamente
        return None, "Frequenza non disponibile: impossibile valutare automaticamente"

    if frequency_mhz < 2.5:
        min_depth = 16.0
    elif frequency_mhz < 5.0:
        min_depth = 13.0
    elif frequency_mhz < 8.0:
        min_depth = 6.0
    elif frequency_mhz <= 12.0:
        min_depth = 4.0
    else:
        min_depth = None

    if min_depth is None:
        return None, f"Frequenza {frequency_mhz} MHz fuori dai range di riferimento"

    passed = depth >= min_depth
    return passed, f"Minimo richiesto: > {min_depth} cm per {frequency_mhz} MHz"


def _evaluate_measure_table(
    value: Optional[str],
    expected_values: List[float],
    max_gap: float,
) -> Tuple[Optional[bool], Optional[str]]:
    """Valuta una tabella di misure nel formato 'misurato1;misurato2;...'.

    Il manuale richiede che lo scarto fra due misure contigue sia inferiore
    a una soglia. Poiché il valore effettivo è noto, calcoliamo lo scarto
    assoluto rispetto al valore atteso per ogni riga.
    """
    if not value:
        return None, None

    measured = [_parse_float(v) for v in str(value).split(";")]
    if len(measured) != len(expected_values):
        return None, f"Attese {len(expected_values)} misure, trovate {len(measured)}"

    if any(m is None for m in measured):
        return None, "Misure incomplete"

    gaps: List[float] = []
    for exp, meas in zip(expected_values, measured):
        gaps.append(abs(exp - meas))  # type: ignore[arg-type]

    max_gap_found = max(gaps)
    passed = max_gap_found < max_gap
    return passed, f"Scarto max: {max_gap_found:.2f} mm (limite < {max_gap} mm)"


def evaluate_vertical_measures(value: Optional[str]) -> Tuple[Optional[bool], Optional[str]]:
    expected = [20.0, 40.0, 60.0, 80.0, 100.0, 120.0, 140.0, 160.0]
    return _evaluate_measure_table(value, expected, 1.5)


def evaluate_horizontal_measures(value: Optional[str]) -> Tuple[Optional[bool], Optional[str]]:
    expected = [-20.0, 40.0, -40.0, 20.0, -60.0, -80.0]
    return _evaluate_measure_table(value, expected, 2.0)


def evaluate_dead_zone(value: Optional[str], frequency_mhz: Optional[float] = None) -> Tuple[Optional[bool], Optional[str]]:
    dead_zone = _parse_float(value)
    if dead_zone is None:
        return None, None

    if frequency_mhz is None:
        return None, "Frequenza non disponibile: impossibile valutare automaticamente"

    if frequency_mhz < 3.0:
        limit = 7.0
    elif frequency_mhz <= 7.0:
        limit = 5.0
    else:
        limit = 3.0

    passed = dead_zone < limit
    return passed, f"Limite: < {limit} mm per {frequency_mhz} MHz"


def evaluate_resolution(
    value: Optional[str],
    expected_pairs: List[float],
) -> Tuple[Optional[bool], Optional[str]]:
    """Valuta la risoluzione: ultima coppia distinguibile."""
    if not value or str(value).strip() in ("N/A", "Non Applicabile"):
        return True, "Non applicabile"

    resolution = _parse_float(value)
    if resolution is None:
        return True, "Valore registrato"

    if not expected_pairs:
        return True, "Coppia registrata"

    closest = min(expected_pairs, key=lambda x: abs(x - resolution))
    passed = resolution <= closest + 1.0
    return passed, f"Coppia nominale: {closest} mm, limite <= {closest + 1.0} mm"


def evaluate_resolution_3cm_axial(value: Optional[str]) -> Tuple[Optional[bool], Optional[str]]:
    return evaluate_resolution(value, [4.0, 3.0, 2.0, 1.0, 0.5, 0.25])


def evaluate_resolution_3cm_lateral(value: Optional[str]) -> Tuple[Optional[bool], Optional[str]]:
    return evaluate_resolution(value, [4.0, 3.0, 2.0, 1.0, 0.5, 0.25])


def evaluate_resolution_11cm_axial(value: Optional[str]) -> Tuple[Optional[bool], Optional[str]]:
    return evaluate_resolution(value, [5.0, 4.0, 3.0, 2.0, 1.0])


def evaluate_resolution_11cm_lateral(value: Optional[str]) -> Tuple[Optional[bool], Optional[str]]:
    return evaluate_resolution(value, [5.0, 4.0, 3.0, 2.0, 1.0])


def evaluate_mass(value: Optional[str]) -> Tuple[Optional[bool], Optional[str]]:
    """Le masse anecoiche/iperecogene non hanno limiti standardizzati."""
    if value is None or str(value).strip() in ("", "N/A"):
        return True, "Non applicabile / Nessun dato"
    return True, "Non esistono limiti standardizzati: valutazione documentativa"


# ─── Estrazione frequenza dal tipo/modello sonda ─────────────────────────────

_FREQUENCY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*MHz", re.IGNORECASE)


def extract_frequency_mhz(probe: EcografoQualityProbe) -> Optional[float]:
    """Cerca di estrarre la frequenza in MHz da tipo o modello della sonda."""
    for source in (probe.probe_type, probe.model, probe.test_model):
        if not source:
            continue
        match = _FREQUENCY_RE.search(str(source))
        if match:
            return _parse_float(match.group(1))
    return None


# ─── Valutazione completa di una sonda ───────────────────────────────────────

def evaluate_probe(probe: EcografoQualityProbe) -> List[str]:
    """Valuta tutti i controlli di una sonda e restituisce eventuali avvisi."""
    warnings: List[str] = []
    frequency = extract_frequency_mhz(probe)

    for control in probe.controls:
        key = control.control_key
        value = control.value

        if key == CONTROL_INSPECTION:
            control.passed = evaluate_inspection(value)
        elif key == CONTROL_UNIFORMITY:
            control.passed = evaluate_uniformity(value)
        elif key == CONTROL_MAX_DEPTH:
            control.passed, note = evaluate_max_depth(value, frequency)
            if note:
                control.notes = note
        elif key == CONTROL_VERTICAL_MEASURES:
            control.passed, note = evaluate_vertical_measures(value)
            if note:
                control.notes = note
        elif key == CONTROL_HORIZONTAL_MEASURES:
            control.passed, note = evaluate_horizontal_measures(value)
            if note:
                control.notes = note
        elif key == CONTROL_DEAD_ZONE:
            control.passed, note = evaluate_dead_zone(value, frequency)
            if note:
                control.notes = note
        elif key in (CONTROL_RESOLUTION_3CM_AXIAL, CONTROL_RESOLUTION_3CM_LATERAL):
            control.passed, note = evaluate_resolution_3cm_axial(value)
            if note:
                control.notes = note
        elif key in (CONTROL_RESOLUTION_11CM_AXIAL, CONTROL_RESOLUTION_11CM_LATERAL):
            control.passed, note = evaluate_resolution_11cm_axial(value)
            if note:
                control.notes = note
        elif key in (CONTROL_ANECHOIC_MASS, CONTROL_HYPOERECHOIC_MASS):
            control.passed, note = evaluate_mass(value)
            if note:
                control.notes = note

    return warnings


def determine_next_control_stage(existing_count: int) -> str:
    """Restituisce lo stadio del controllo in base allo storico registrato per la sonda.

    0 precedenti -> Baseline
    1 precedente -> Controllo 1
    2 precedenti -> Controllo 2
    3 precedenti -> Controllo 3
    ...
    """
    if existing_count <= 0:
        return "Baseline"
    return f"Controllo {existing_count}"


# ─── Valutazione complessiva della verifica ──────────────────────────────────

def evaluate_check(check: EcografoQualityCheck) -> str:
    """Calcola l'esito complessivo della verifica.

    - Se almeno un controllo è False → NON CONFORME
    - Se tutti i controlli valutabili sono True → CONFORME
    - Se ci sono controlli non valutabili (None) ma nessun False → CONFORME CON ANNOTAZIONE
    """
    all_passed: List[Optional[bool]] = []
    for probe in check.probes:
        evaluate_probe(probe)
        for control in probe.controls:
            all_passed.append(control.passed)

    if any(p is False for p in all_passed):
        return "NON CONFORME"
    if all(p is True for p in all_passed):
        return "CONFORME"
    return "CONFORME CON ANNOTAZIONE"


def update_overall_status(check: EcografoQualityCheck) -> None:
    """Aggiorna in-place l'esito complessivo della verifica."""
    check.overall_status = evaluate_check(check)

