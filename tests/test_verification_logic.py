# tests/test_verification_logic.py
"""Test della logica di valutazione misure CEI 62353 (app/verification_logic.py).

Eseguire con: python -m pytest tests/ -v
"""
import pytest

# "Test" rinominato per non confondere il collector di pytest
from app.data_models import AppliedPart, Limit, Test as ProfileTest
from app.verification_logic import evaluate_measure, parse_measure_value


# ─── parse_measure_value ────────────────────────────────────────────────────

class TestParseMeasureValue:
    def test_numero_semplice(self):
        assert parse_measure_value("0.45") == 0.45

    def test_numero_intero(self):
        assert parse_measure_value("450") == 450.0

    def test_virgola_decimale_italiana(self):
        # Bug storico: "0,5" diventava "05" = 5.0 (errore di un fattore 10)
        assert parse_measure_value("0,5") == 0.5

    def test_virgola_decimale_con_unita(self):
        assert parse_measure_value("0,45 µA") == 0.45

    def test_unita_di_misura(self):
        assert parse_measure_value("450 µA") == 450.0
        assert parse_measure_value("1.2 MΩ") == 1.2
        assert parse_measure_value("0.123 ohm") == 0.123

    def test_spazi(self):
        assert parse_measure_value("  1.5  ") == 1.5

    def test_negativo(self):
        assert parse_measure_value("-0.3") == -0.3

    def test_migliaia_con_punto_e_virgola(self):
        # Se ci sono sia virgola che punto, la virgola è il separatore migliaia
        assert parse_measure_value("1,234.5") == 1234.5

    def test_vuoto(self):
        assert parse_measure_value("") is None
        assert parse_measure_value("   ") is None

    def test_none(self):
        assert parse_measure_value(None) is None

    def test_non_numerico(self):
        assert parse_measure_value("abc") is None
        assert parse_measure_value("ERR") is None


# ─── evaluate_measure ───────────────────────────────────────────────────────

def make_test(name="RESISTENZA TERRA", parameter="", limits=None, **kw):
    return ProfileTest(name=name, parameter=parameter, limits=limits or {}, **kw)


class TestEvaluateMeasureLimiti:
    def test_sotto_il_limite_passa(self):
        t = make_test(limits={"::ST": Limit(unit="Ω", high_value=0.3)})
        r = evaluate_measure(t, "0.2")
        assert r["passed"] is True
        assert r["limit_value"] == 0.3
        assert r["unit"] == "Ω"

    def test_uguale_al_limite_passa(self):
        # CEI 62353: il valore limite è incluso (<=)
        t = make_test(limits={"::ST": Limit(unit="Ω", high_value=0.3)})
        assert evaluate_measure(t, "0.3")["passed"] is True

    def test_sopra_il_limite_fallisce(self):
        t = make_test(limits={"::ST": Limit(unit="Ω", high_value=0.3)})
        assert evaluate_measure(t, "0.31")["passed"] is False

    def test_virgola_decimale_valutata_correttamente(self):
        # Con il vecchio parsing "0,5" diventava 5.0 e il test falliva
        t = make_test(limits={"::ST": Limit(unit="Ω", high_value=1.0)})
        assert evaluate_measure(t, "0,5")["passed"] is True

    def test_senza_limite_passa_sempre(self):
        t = make_test(limits={})
        r = evaluate_measure(t, "9999")
        assert r["passed"] is True
        assert r["limit_value"] is None

    def test_limite_senza_high_value_passa(self):
        t = make_test(limits={"::ST": Limit(unit="µA", high_value=None)})
        r = evaluate_measure(t, "9999")
        assert r["passed"] is True
        assert r["unit"] == "µA"

    def test_valore_non_numerico_ritorna_none(self):
        t = make_test(limits={"::ST": Limit(unit="Ω", high_value=0.3)})
        assert evaluate_measure(t, "abc") is None

    def test_valore_originale_conservato(self):
        t = make_test(limits={"::ST": Limit(unit="µA", high_value=100)})
        r = evaluate_measure(t, "45 µA")
        assert r["value"] == "45 µA"


class TestEvaluateMeasureParteApplicata:
    def make_part(self, part_type="CF"):
        return AppliedPart(name="ELETTRODO 1", part_type=part_type, code="V1")

    def test_usa_limite_della_parte_applicata(self):
        t = make_test(
            name="CORRENTE DISPERSIONE PAZIENTE",
            limits={
                "::ST": Limit(unit="µA", high_value=500),
                "::CF": Limit(unit="µA", high_value=50),
            },
        )
        part = self.make_part("CF")
        r = evaluate_measure(t, "49", applied_part=part)
        assert r["passed"] is True
        assert r["limit_value"] == 50
        r = evaluate_measure(t, "51", applied_part=part)
        assert r["passed"] is False

    def test_nome_risultato_con_parte_applicata(self):
        t = make_test(name="DISPERSIONE", limits={"::BF": Limit(unit="µA", high_value=100)})
        r = evaluate_measure(t, "10", applied_part=self.make_part("BF"))
        assert r["name"] == "DISPERSIONE - ELETTRODO 1 - BF"

    def test_polarita_dal_parametro(self):
        t = make_test(name="DISPERSIONE", parameter="N.C.",
                      limits={"::CF": Limit(unit="µA", high_value=50)})
        r = evaluate_measure(t, "10", applied_part=self.make_part("CF"))
        assert r["polarity"] == "N.C."

    def test_senza_parte_applicata_polarita_none(self):
        t = make_test(parameter="N.C.", limits={"::ST": Limit(unit="µA", high_value=50)})
        r = evaluate_measure(t, "10")
        assert r["polarity"] is None
        assert r["name"] == "RESISTENZA TERRA (N.C.)"

    def test_limite_parte_mancante_passa(self):
        # Parte applicata B ma nel profilo c'è solo il limite CF:
        # nessun limite trovato -> passa (comportamento storico)
        t = make_test(limits={"::CF": Limit(unit="µA", high_value=50)})
        r = evaluate_measure(t, "9999", applied_part=self.make_part("B"))
        assert r["passed"] is True
        assert r["limit_value"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
