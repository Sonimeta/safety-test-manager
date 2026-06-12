# tests/test_functional_models.py
"""Test dei modelli e dei template dei profili funzionali."""
import pytest

from app.functional_models import (
    FunctionalField,
    FunctionalProfile,
    FunctionalRowDefinition,
    FunctionalSection,
    functional_profile_from_dict,
    functional_profile_to_dict,
    sanitize_profile_key,
    validate_functional_profile,
)
from app.functional_templates import FUNCTIONAL_PROFILE_TEMPLATES


class TestSanitizeProfileKey:
    def test_spazi_e_maiuscole(self):
        assert sanitize_profile_key("Monitor ECG 12 Derivazioni") == "monitor_ecg_12_derivazioni"

    def test_caratteri_speciali_rimossi(self):
        assert sanitize_profile_key("Pompa (siringa) 50ml!") == "pompa_siringa_50ml"

    def test_trattini_e_punti(self):
        assert sanitize_profile_key("AMS-MOD.PROVA, X") == "ams_mod_prova__x"


class TestRoundTripDict:
    def test_template_defibrillatore_round_trip(self):
        original = FUNCTIONAL_PROFILE_TEMPLATES["defibrillatore_fun"]
        data = functional_profile_to_dict(original)
        ricostruito = functional_profile_from_dict(data)
        assert ricostruito == original

    def test_tutti_i_template_round_trip(self):
        for key, template in FUNCTIONAL_PROFILE_TEMPLATES.items():
            data = functional_profile_to_dict(template)
            ricostruito = functional_profile_from_dict(data)
            assert ricostruito == template, f"Round-trip fallito per template '{key}'"

    def test_retrocompatibilita_instrument_id_singolo(self):
        data = {"profile_key": "x", "name": "X", "instrument_id": 7, "sections": []}
        p = functional_profile_from_dict(data)
        assert p.instrument_ids == [7]

    def test_formula_implica_read_only(self):
        data = {
            "profile_key": "x", "name": "X",
            "sections": [{
                "key": "s", "title": "S", "section_type": "fields",
                "fields": [{"key": "f", "label": "F", "field_type": "number",
                            "formula": "a + b"}],
            }],
        }
        p = functional_profile_from_dict(data)
        assert p.sections[0].fields[0].read_only is True


class TestValidazione:
    def make_profile(self, **kw):
        defaults = dict(
            profile_key="test_fun", name="TEST",
            sections=[FunctionalSection(
                key="s1", title="Sezione", section_type="fields",
                fields=[FunctionalField(key="f1", label="Campo", field_type="text")],
            )],
        )
        defaults.update(kw)
        return FunctionalProfile(**defaults)

    def test_profilo_valido(self):
        assert validate_functional_profile(self.make_profile()) == []

    def test_chiave_mancante(self):
        errors = validate_functional_profile(self.make_profile(profile_key=""))
        assert any("chiave" in e.lower() for e in errors)

    def test_senza_sezioni(self):
        errors = validate_functional_profile(self.make_profile(sections=[]))
        assert any("sezione" in e.lower() for e in errors)

    def test_chiavi_sezione_duplicate(self):
        s = FunctionalSection(
            key="dup", title="S", section_type="fields",
            fields=[FunctionalField(key="f", label="F", field_type="text")],
        )
        errors = validate_functional_profile(self.make_profile(sections=[s, s]))
        assert any("duplicata" in e.lower() for e in errors)

    def test_checklist_senza_righe(self):
        s = FunctionalSection(key="c", title="Checklist", section_type="checklist")
        errors = validate_functional_profile(self.make_profile(sections=[s]))
        assert any("riga" in e.lower() for e in errors)

    def test_chiavi_campo_duplicate_in_riga(self):
        s = FunctionalSection(
            key="t", title="Tabella", section_type="table",
            rows=[FunctionalRowDefinition(key="r1", label="R", fields=[
                FunctionalField(key="x", label="X", field_type="number"),
                FunctionalField(key="x", label="X2", field_type="number"),
            ])],
        )
        errors = validate_functional_profile(self.make_profile(sections=[s]))
        assert any("duplicata" in e.lower() for e in errors)


class TestTemplateIntegrati:
    """Test 'golden': i template funzionali predefiniti devono essere validi."""

    def test_tutti_i_template_validi(self):
        for key, template in FUNCTIONAL_PROFILE_TEMPLATES.items():
            errors = validate_functional_profile(template)
            assert errors == [], f"Template '{key}' non valido: {errors}"

    def test_chiavi_template_coerenti(self):
        for key, template in FUNCTIONAL_PROFILE_TEMPLATES.items():
            assert template.profile_key == key

    def test_formule_solo_aritmetica_semplice(self):
        # Le formule devono funzionare anche nel motore JS mobile:
        # niente funzioni Python, solo + - * / parentesi e nomi campo
        import re
        allowed = re.compile(r"^[\w\s+\-*/().]+$")
        for key, template in FUNCTIONAL_PROFILE_TEMPLATES.items():
            for section in template.sections:
                all_fields = list(section.fields)
                for row in section.rows:
                    all_fields.extend(row.fields)
                for f in all_fields:
                    if f.formula:
                        assert allowed.match(f.formula), (
                            f"Formula non portabile in '{key}': {f.formula}")

    def test_formula_errore_percentuale_defibrillatore(self):
        defib = FUNCTIONAL_PROFILE_TEMPLATES["defibrillatore_fun"]
        discharge = next(s for s in defib.sections if s.key == "discharge_levels")
        for row in discharge.rows:
            err_pct = next(f for f in row.fields if f.key == "error_percent")
            assert err_pct.formula == "(measured_value - set_value) / set_value * 100"
            # Verifica numerica: 100 J impostati, 103 misurati -> 3%
            result = eval(err_pct.formula, {"__builtins__": {}},
                          {"measured_value": 103.0, "set_value": 100.0})
            assert abs(result - 3.0) < 1e-9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
