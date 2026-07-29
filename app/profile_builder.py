# app/profile_builder.py
"""Costruzione guidata dei profili di verifica elettrica (CEI EN 62353).

Logica pura (testabile senza GUI) usata dalla modalità guidata del gestore
profili: da un insieme di opzioni ad alto livello (quali prove fare, classe
del dispositivo, limiti) genera la lista di Test nel formato eseguibile,
e viceversa riconosce un profilo esistente riportandolo alle opzioni.

ATTENZIONE: i nomi dei test e la parola "inversa" nei parametri sono un
contratto con il driver dello strumento (app/hardware/fluke_esa612.py,
test_function_map in app/ui/widgets.py). Non cambiarli.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.data_models import Limit, Test

# Nomi canonici dei test (chiavi del test_function_map in widgets.py)
NAME_MAINS_VOLTAGE = "Tensione alimentazione"
NAME_EARTH_RESISTANCE = "Resistenza conduttore di terra"
NAME_EQUIPMENT_LEAKAGE = "Corrente dispersione diretta dispositivo"
NAME_AP_LEAKAGE = "Corrente dispersione diretta P.A."
NAME_PAUSE = "--- PAUSA MANUALE ---"

# Parametri canonici (il driver Fluke li confronta in minuscolo)
MAINS_VOLTAGE_MEASURES = ("Da fase a neutro", "Da neutro a terra", "Da fase a terra")
PARAM_POLARITY_NORMAL = "Polarità Normale"
PARAM_POLARITY_REVERSE = "Polarità Inversa"

# Valori CEI EN 62353 (metodo diretto)
CEI_EARTH_LIMIT = 0.3            # Ohm
CEI_EQUIPMENT_LEAKAGE_CL1 = 500.0  # µA, Classe I
CEI_EQUIPMENT_LEAKAGE_CL2 = 100.0  # µA, Classe II
CEI_AP_LIMITS = {"B": 5000.0, "BF": 5000.0, "CF": 50.0}  # µA


@dataclass
class BuilderOptions:
    """Stato della modalità guidata: cosa includere e con quali limiti."""
    device_class: str = "I"  # "I" oppure "II"

    include_mains_voltage: bool = False
    mains_voltage_measures: List[str] = field(
        default_factory=lambda: list(MAINS_VOLTAGE_MEASURES))

    include_earth_resistance: bool = True
    earth_limit: float = CEI_EARTH_LIMIT

    include_equipment_leakage: bool = True
    equipment_leakage_limit: float = CEI_EQUIPMENT_LEAKAGE_CL1
    equipment_polarity_normal: bool = True
    equipment_polarity_reverse: bool = True

    include_ap_leakage: bool = False
    ap_limits: Dict[str, float] = field(default_factory=lambda: dict(CEI_AP_LIMITS))
    ap_polarity_normal: bool = True
    ap_polarity_reverse: bool = True

    include_pause_before_ap: bool = False
    pause_before_ap: str = ""  # messaggio mostrato all'operatore


def class_defaults(device_class: str) -> dict:
    """Valori di default CEI 62353 in base alla classe del dispositivo.

    Classe I: con conduttore di terra, dispersione apparecchio 500 µA.
    Classe II: senza conduttore di terra (doppio isolamento), 100 µA.
    """
    if device_class == "II":
        return {
            "include_earth_resistance": False,
            "equipment_leakage_limit": CEI_EQUIPMENT_LEAKAGE_CL2,
        }
    return {
        "include_earth_resistance": True,
        "earth_limit": CEI_EARTH_LIMIT,
        "equipment_leakage_limit": CEI_EQUIPMENT_LEAKAGE_CL1,
    }


def build_tests(opts: BuilderOptions) -> List[Test]:
    """Genera la sequenza di Test nell'ordine canonico di esecuzione:
    tensione di rete → terra → dispersione apparecchio (N, I) →
    eventuale pausa → dispersione parti applicate (N, I)."""
    tests: List[Test] = []

    if opts.include_mains_voltage:
        for measure in opts.mains_voltage_measures:
            tests.append(Test(
                name=NAME_MAINS_VOLTAGE, parameter=measure,
                limits={"::ST": Limit(unit="V", high_value=None)},
            ))

    if opts.include_earth_resistance:
        tests.append(Test(
            name=NAME_EARTH_RESISTANCE, parameter="",
            limits={"::ST": Limit(unit="Ohm", high_value=opts.earth_limit)},
        ))

    if opts.include_equipment_leakage:
        polarities = []
        if opts.equipment_polarity_normal:
            polarities.append(PARAM_POLARITY_NORMAL)
        if opts.equipment_polarity_reverse:
            polarities.append(PARAM_POLARITY_REVERSE)
        for pol in polarities:
            tests.append(Test(
                name=NAME_EQUIPMENT_LEAKAGE, parameter=pol,
                limits={"::ST": Limit(unit="uA", high_value=opts.equipment_leakage_limit)},
            ))

    if opts.include_ap_leakage and opts.ap_limits:
        if opts.include_pause_before_ap:
            tests.append(Test(
                name=NAME_PAUSE, parameter=opts.pause_before_ap.strip(), limits={},
            ))
        ap_limit_objs = {
            f"::{ap_type}": Limit(unit="uA", high_value=value)
            for ap_type, value in opts.ap_limits.items()
        }
        polarities = []
        if opts.ap_polarity_normal:
            polarities.append(PARAM_POLARITY_NORMAL)
        if opts.ap_polarity_reverse:
            polarities.append(PARAM_POLARITY_REVERSE)
        for pol in polarities:
            tests.append(Test(
                name=NAME_AP_LEAKAGE, parameter=pol,
                limits=dict(ap_limit_objs), is_applied_part_test=True,
            ))

    return tests


def describe_tests(tests: List[Test]) -> List[str]:
    """Descrizione leggibile della sequenza, per l'anteprima nel dialog."""
    lines = []
    for i, t in enumerate(tests, 1):
        if "PAUSA MANUALE" in t.name.upper():
            lines.append(f"{i}. ⏸ Pausa: {t.parameter or 'messaggio per l’operatore'}")
            continue
        desc = t.name
        if t.parameter:
            desc += f" — {t.parameter}"
        limit_parts = []
        for key, lim in (t.limits or {}).items():
            if lim.high_value is not None:
                tipo = key.strip(": ")
                prefix = f"{tipo}: " if tipo != "ST" else ""
                limit_parts.append(f"{prefix}≤ {lim.high_value:g} {lim.unit}")
        if limit_parts:
            desc += f"   [{' · '.join(limit_parts)}]"
        if t.is_applied_part_test:
            desc += "   (su ogni parte applicata)"
        lines.append(f"{i}. {desc}")
    return lines


# ─── Riconoscimento di un profilo esistente ─────────────────────────────────

def _is_normal(param: str) -> bool:
    return "INVERS" not in (param or "").upper()


def parse_profile(profile) -> Optional[BuilderOptions]:
    """Prova a ricondurre un profilo esistente alle opzioni della modalità
    guidata. Ritorna None se il profilo non rientra nello schema (test
    personalizzati, ordine diverso, pause in posizioni arbitrarie...):
    in quel caso il dialog usa la modalità avanzata.

    Nota: l'ordine canonico è richiesto, perché la modalità guidata
    rigenera i test in quell'ordine e non deve alterare la sequenza
    di esecuzione di un profilo esistente.
    """
    opts = BuilderOptions(
        include_mains_voltage=False, mains_voltage_measures=[],
        include_earth_resistance=False,
        include_equipment_leakage=False,
        equipment_polarity_normal=False, equipment_polarity_reverse=False,
        include_ap_leakage=False, ap_limits={},
        ap_polarity_normal=False, ap_polarity_reverse=False,
    )

    # Fasi in ordine canonico: 0=tensione, 1=terra, 2=dispersione disp.,
    # 3=pausa pre-P.A., 4=dispersione P.A.  Una fase può essere assente,
    # ma non si può tornare a una fase precedente.
    phase = 0

    def single_st_limit(test) -> Optional[Limit]:
        keys = list((test.limits or {}).keys())
        if keys not in (["::ST"], []):
            return None
        return (test.limits or {}).get("::ST") or Limit(unit="", high_value=None)

    for test in profile.tests:
        name_up = (test.name or "").strip().upper()

        if name_up == NAME_MAINS_VOLTAGE.upper():
            if phase > 0 or test.is_applied_part_test:
                return None
            measure = (test.parameter or "").strip()
            canonical = {m.upper(): m for m in MAINS_VOLTAGE_MEASURES}
            if measure.upper() not in canonical or single_st_limit(test) is None:
                return None
            opts.include_mains_voltage = True
            opts.mains_voltage_measures.append(canonical[measure.upper()])

        elif name_up == NAME_EARTH_RESISTANCE.upper():
            if phase > 1 or test.is_applied_part_test:
                return None
            phase = 1
            lim = single_st_limit(test)
            if lim is None or lim.high_value is None or opts.include_earth_resistance:
                return None
            opts.include_earth_resistance = True
            opts.earth_limit = lim.high_value

        elif name_up == NAME_EQUIPMENT_LEAKAGE.upper():
            if phase > 2 or test.is_applied_part_test:
                return None
            phase = 2
            lim = single_st_limit(test)
            if lim is None or lim.high_value is None:
                return None
            if opts.include_equipment_leakage and lim.high_value != opts.equipment_leakage_limit:
                return None
            opts.include_equipment_leakage = True
            opts.equipment_leakage_limit = lim.high_value
            if _is_normal(test.parameter):
                if opts.equipment_polarity_normal:
                    return None
                opts.equipment_polarity_normal = True
            else:
                if opts.equipment_polarity_reverse:
                    return None
                opts.equipment_polarity_reverse = True

        elif "PAUSA MANUALE" in name_up:
            if phase > 3 or opts.include_pause_before_ap:
                return None
            phase = 3
            opts.include_pause_before_ap = True
            opts.pause_before_ap = (test.parameter or "").strip()

        elif name_up == NAME_AP_LEAKAGE.upper():
            if not test.is_applied_part_test:
                return None
            phase = 4
            limits = {k.strip(": ").upper(): lim for k, lim in (test.limits or {}).items()}
            if not limits or any(k not in ("B", "BF", "CF") for k in limits):
                return None
            if any(lim.high_value is None for lim in limits.values()):
                return None
            values = {k: lim.high_value for k, lim in limits.items()}
            if opts.include_ap_leakage and values != opts.ap_limits:
                return None
            opts.include_ap_leakage = True
            opts.ap_limits = values
            if _is_normal(test.parameter):
                if opts.ap_polarity_normal:
                    return None
                opts.ap_polarity_normal = True
            else:
                if opts.ap_polarity_reverse:
                    return None
                opts.ap_polarity_reverse = True

        else:
            return None  # test personalizzato: serve la modalità avanzata

    # Una pausa senza prove P.A. successive non rientra nello schema
    if opts.include_pause_before_ap and not opts.include_ap_leakage:
        return None

    # Stima della classe per coerenza dell'interfaccia
    opts.device_class = "I" if opts.include_earth_resistance else "II"
    return opts
