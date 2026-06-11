# app/verification_logic.py
"""Logica pura di valutazione delle misure di verifica elettrica (CEI 62353).

Estratta da app/ui/widgets.py per poterla testare senza interfaccia grafica
(vedi tests/test_verification_logic.py).
"""
import re
from typing import Optional


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
