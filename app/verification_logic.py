# app/verification_logic.py
"""Logica pura di valutazione delle misure di verifica elettrica (CEI 62353).

Estratta da app/ui/widgets.py per poterla testare senza interfaccia grafica
(vedi tests/test_verification_logic.py).
"""
import re
from typing import List, Optional


def parse_measure_value(value_str) -> Optional[float]:
    """Converte la stringa misura (da strumento o digitata) in float.

    - tollera unità di misura e spazi ("0.45 µA" -> 0.45)
    - accetta la virgola come separatore decimale ("0,5" -> 0.5).
      Nota: in precedenza la virgola veniva semplicemente rimossa dalla
      pulizia regex, quindi "0,5" diventava "05" = 5.0 — un errore di
      un fattore 10 sulla misura inserita a mano.

    Ritorna None se il valore non è interpretabile come numero.
    """
    if value_str is None:
        return None
    s = str(value_str).strip()
    if not s:
        return None
    # Virgola decimale italiana: solo se non c'è già un punto,
    # altrimenti la virgola è un separatore delle migliaia ("1,234.5")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def evaluate_measure(test, value_str, applied_part=None) -> Optional[dict]:
    """Valuta una misura rispetto ai limiti del profilo di verifica.

    Args:
        test: app.data_models.Test (nome, parametro, limiti per chiave)
        value_str: valore misurato come stringa (conservato tal quale nel risultato)
        applied_part: app.data_models.AppliedPart opzionale; se presente il
            limite viene cercato con la chiave "::<tipo parte>" (B/BF/CF),
            altrimenti con "::ST"

    Returns:
        dict nel formato salvato in results_json
        ({name, value, limit_value, unit, passed, polarity}),
        oppure None se value_str non è un numero valido.
    """
    value_float = parse_measure_value(value_str)
    if value_float is None:
        return None

    result_name = f"{test.name} ({test.parameter})" if test.parameter else test.name
    limit_key = "::ST"
    polarity = None

    if applied_part:
        result_name = f"{test.name} - {applied_part.name} - {applied_part.part_type}"
        limit_key = f"::{applied_part.part_type}"
        if test.parameter:
            polarity = test.parameter

    limit_obj = test.limits.get(limit_key)
    is_passed = True
    limit_value = None
    unit = limit_obj.unit if limit_obj else ""
    if limit_obj and limit_obj.high_value is not None:
        is_passed = value_float <= limit_obj.high_value
        limit_value = limit_obj.high_value

    return {
        "name": result_name,
        "value": value_str,
        "limit_value": limit_value,
        "unit": unit,
        "passed": is_passed,
        "polarity": polarity,
    }


# ─── Validazione di plausibilità dei limiti di profilo (CEI 62353) ──────────
#
# Regole per test riconosciuti dal nome. Per ogni regola:
#   - max_sicuro: valore massimo ammesso dalla norma. Un limite PIÙ ALTO è
#     pericoloso: farebbe passare dispositivi che andrebbero bocciati.
#   - min_plausibile: sotto questa soglia il valore è quasi certamente un
#     refuso (es. 0.5 µA invece di 500): farebbe fallire dispositivi sani.
#
# Riferimenti CEI EN 62353 (metodo diretto):
#   resistenza conduttore di terra: 0.3 Ω (fino a 0.5 Ω in casi particolari)
#   corrente dispersione apparecchio: 500 µA (Classe I), 100 µA (Classe II)
#   corrente dispersione parti applicate: 5000 µA (B/BF), 50 µA (CF)

_LIMIT_RULES = [
    # (parole chiave nel nome, tipi P.A. a cui si applica o None=tutti,
    #  min_plausibile, max_sicuro, descrizione del riferimento)
    (("RESISTENZA", "TERRA"), None, 0.05, 0.5, "CEI 62353: 0.3 Ω (max 0.5 Ω)"),
    (("DISPERSIONE", "DISPOSITIVO"), None, 50.0, 500.0, "CEI 62353: 500 µA Classe I / 100 µA Classe II"),
    (("DISPERSIONE", "P.A."), ("B", "BF"), 50.0, 5000.0, "CEI 62353: 5000 µA per parti B/BF"),
    (("DISPERSIONE", "P.A."), ("CF",), 5.0, 50.0, "CEI 62353: 50 µA per parti CF"),
]

# Test che è normale lasciare senza limite (informativi o pause)
_NO_LIMIT_OK_KEYWORDS = ("PAUSA MANUALE", "TENSIONE ALIMENTAZIONE")


def validate_profile_limits(profile) -> List[str]:
    """Controlla la plausibilità dei limiti di un profilo rispetto alla CEI 62353.

    Non blocca nulla: ritorna una lista di avvisi leggibili (vuota se tutto
    sembra coerente) da mostrare all'utente per conferma. I test con nomi non
    riconosciuti non vengono giudicati.

    Args:
        profile: app.data_models.VerificationProfile
    """
    warnings: List[str] = []

    for test in profile.tests:
        name_up = (test.name or "").upper()

        if any(kw in name_up for kw in _NO_LIMIT_OK_KEYWORDS):
            continue

        for limit_key, limit in (test.limits or {}).items():
            ap_type = limit_key.strip(": ").upper()
            label = f"'{test.name}'" + (f" [{ap_type}]" if ap_type != "ST" else "")

            rule = None
            for keywords, ap_types, min_pl, max_safe, ref in _LIMIT_RULES:
                if all(kw in name_up for kw in keywords):
                    if ap_types is None or ap_type in ap_types:
                        rule = (min_pl, max_safe, ref)
                        break
            if rule is None:
                continue
            min_pl, max_safe, ref = rule

            if limit.high_value is None:
                warnings.append(
                    f"{label}: nessun limite impostato, il test risulterà sempre PASSATO ({ref})."
                )
            elif limit.high_value > max_safe:
                warnings.append(
                    f"{label}: limite {limit.high_value:g} {limit.unit} SUPERIORE al massimo di norma "
                    f"— dispositivi fuori norma risulterebbero PASSATI ({ref})."
                )
            elif limit.high_value < min_pl:
                warnings.append(
                    f"{label}: limite {limit.high_value:g} {limit.unit} insolitamente basso, "
                    f"possibile refuso — dispositivi sani risulterebbero FALLITI ({ref})."
                )

    return warnings
