# tests/test_profile_builder.py
"""Test della costruzione guidata dei profili (app/profile_builder.py)."""
import pytest

from app.data_models import Limit, Test as ProfileTest, VerificationProfile
from app.profile_builder import (
    BuilderOptions,
    NAME_AP_LEAKAGE,
    NAME_EARTH_RESISTANCE,
    NAME_EQUIPMENT_LEAKAGE,
    NAME_MAINS_VOLTAGE,
    build_tests,
    class_defaults,
    describe_tests,
    parse_profile,
)
from app.verification_logic import validate_profile_limits


class TestBuildTests:
    def test_profilo_classe_i_default(self):
        tests = build_tests(BuilderOptions())
        names = [t.name for t in tests]
        # terra + dispersione N + dispersione I (niente tensione/P.A. di default)
        assert names == [NAME_EARTH_RESISTANCE, NAME_EQUIPMENT_LEAKAGE, NAME_EQUIPMENT_LEAKAGE]
        assert tests[0].limits["::ST"].high_value == 0.3
        assert tests[1].limits["::ST"].high_value == 500.0

    def test_polarita_generate(self):
        tests = build_tests(BuilderOptions())
        disp = [t for t in tests if t.name == NAME_EQUIPMENT_LEAKAGE]
        assert "INVERS" not in disp[0].parameter.upper()
        assert "INVERS" in disp[1].parameter.upper()

    def test_parti_applicate_complete(self):
        opts = BuilderOptions(include_ap_leakage=True)
        tests = build_tests(opts)
        ap = [t for t in tests if t.is_applied_part_test]
        assert len(ap) == 2  # normale + inversa
        for t in ap:
            assert t.limits["::B"].high_value == 5000.0
            assert t.limits["::BF"].high_value == 5000.0
            assert t.limits["::CF"].high_value == 50.0

    def test_pausa_prima_delle_pa(self):
        opts = BuilderOptions(include_ap_leakage=True,
                              include_pause_before_ap=True,
                              pause_before_ap="Collegare gli elettrodi")
        tests = build_tests(opts)
        pause_idx = next(i for i, t in enumerate(tests) if "PAUSA" in t.name)
        first_ap_idx = next(i for i, t in enumerate(tests) if t.is_applied_part_test)
        assert pause_idx < first_ap_idx
        assert tests[pause_idx].parameter == "Collegare gli elettrodi"

    def test_tensione_alimentazione(self):
        opts = BuilderOptions(include_mains_voltage=True)
        tests = build_tests(opts)
        mains = [t for t in tests if t.name == NAME_MAINS_VOLTAGE]
        assert len(mains) == 3
        assert tests[:3] == mains  # sempre per prime

    def test_profilo_generato_conforme_alla_norma(self):
        # Qualunque combinazione con i default deve passare il validatore
        opts = BuilderOptions(include_mains_voltage=True, include_ap_leakage=True)
        profile = VerificationProfile(name="X", tests=build_tests(opts))
        assert validate_profile_limits(profile) == []

    def test_classe_ii_defaults(self):
        d = class_defaults("II")
        assert d["include_earth_resistance"] is False
        assert d["equipment_leakage_limit"] == 100.0
        d1 = class_defaults("I")
        assert d1["include_earth_resistance"] is True
        assert d1["equipment_leakage_limit"] == 500.0


class TestRoundTrip:
    def test_round_trip_completo(self):
        opts = BuilderOptions(
            include_mains_voltage=True,
            include_ap_leakage=True,
            include_pause_before_ap=True,
            pause_before_ap="Posizionare le P.A.",
        )
        profile = VerificationProfile(name="RT", tests=build_tests(opts))
        parsed = parse_profile(profile)
        assert parsed is not None
        assert build_tests(parsed) == build_tests(opts)

    def test_round_trip_classe_ii(self):
        opts = BuilderOptions(include_earth_resistance=False,
                              equipment_leakage_limit=100.0)
        profile = VerificationProfile(name="RT2", tests=build_tests(opts))
        parsed = parse_profile(profile)
        assert parsed is not None
        assert parsed.device_class == "II"
        assert parsed.equipment_leakage_limit == 100.0
        assert build_tests(parsed) == build_tests(opts)

    def test_template_integrato_riconosciuto(self):
        from app.profile_templates import PROFILE_TEMPLATES
        tests = PROFILE_TEMPLATES["Verifica con Parti Applicate (BF/CF)"]
        profile = VerificationProfile(name="T", tests=list(tests))
        parsed = parse_profile(profile)
        assert parsed is not None
        assert parsed.include_earth_resistance
        assert parsed.include_ap_leakage
        assert parsed.ap_limits == {"B": 5000.0, "BF": 5000.0, "CF": 50.0}


class TestParseRifiutaProfiliNonStandard:
    def test_test_personalizzato(self):
        p = VerificationProfile(name="X", tests=[
            ProfileTest(name="MISURA SPECIALE", parameter="",
                        limits={"::ST": Limit(unit="uA", high_value=10)}),
        ])
        assert parse_profile(p) is None

    def test_ordine_non_canonico(self):
        # Dispersione PRIMA della terra: ordine custom, va in modalità avanzata
        p = VerificationProfile(name="X", tests=[
            ProfileTest(name=NAME_EQUIPMENT_LEAKAGE, parameter="Polarità Normale",
                        limits={"::ST": Limit(unit="uA", high_value=500)}),
            ProfileTest(name=NAME_EARTH_RESISTANCE, parameter="",
                        limits={"::ST": Limit(unit="Ohm", high_value=0.3)}),
        ])
        assert parse_profile(p) is None

    def test_pausa_senza_pa(self):
        p = VerificationProfile(name="X", tests=[
            ProfileTest(name="--- PAUSA MANUALE ---", parameter="msg", limits={}),
        ])
        assert parse_profile(p) is None

    def test_limiti_dispersione_diversi_tra_polarita(self):
        p = VerificationProfile(name="X", tests=[
            ProfileTest(name=NAME_EQUIPMENT_LEAKAGE, parameter="Polarità Normale",
                        limits={"::ST": Limit(unit="uA", high_value=500)}),
            ProfileTest(name=NAME_EQUIPMENT_LEAKAGE, parameter="Polarità Inversa",
                        limits={"::ST": Limit(unit="uA", high_value=100)}),
        ])
        assert parse_profile(p) is None

    def test_pa_con_tipo_sconosciuto(self):
        p = VerificationProfile(name="X", tests=[
            ProfileTest(name=NAME_AP_LEAKAGE, parameter="Polarità Normale",
                        limits={"::XX": Limit(unit="uA", high_value=50)},
                        is_applied_part_test=True),
        ])
        assert parse_profile(p) is None


class TestDescribeTests:
    def test_descrizione_leggibile(self):
        opts = BuilderOptions(include_ap_leakage=True)
        lines = describe_tests(build_tests(opts))
        assert len(lines) == 5  # terra + 2 dispersione + 2 P.A.
        assert "0.3" in lines[0]
        assert "parte applicata" in lines[3]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
