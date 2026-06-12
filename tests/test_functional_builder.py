# tests/test_functional_builder.py
"""Test della modalità guidata dei profili funzionali (app/functional_builder.py)."""
import pytest

from app.functional_builder import (
    SimpleChecklist,
    SimpleChecklistItem,
    SimpleFunctionalOptions,
    build_sections,
    checklist_from_text,
    format_item_line,
    parse_item_line,
    parse_profile_sections,
)
from app.functional_models import (
    FunctionalProfile,
    validate_functional_profile,
)
from app.functional_templates import FUNCTIONAL_PROFILE_TEMPLATES


class TestParseItemLine:
    def test_voce_semplice(self):
        item = parse_item_line("Integrità involucro")
        assert item.label == "Integrità involucro" and item.unit is None

    def test_voce_con_unita(self):
        item = parse_item_line("Lettura saturazione [%]")
        assert item.label == "Lettura saturazione" and item.unit == "%"

    def test_unita_con_spazi(self):
        item = parse_item_line("Tempo di carica  [ s ]")
        assert item.label == "Tempo di carica" and item.unit == "s"

    def test_riga_vuota(self):
        assert parse_item_line("") is None
        assert parse_item_line("   ") is None

    def test_solo_unita_senza_etichetta(self):
        assert parse_item_line("[bpm]") is None

    def test_format_round_trip(self):
        for line in ("Voce semplice", "Lettura [bpm]"):
            assert format_item_line(parse_item_line(line)) == line


class TestChecklistFromText:
    def test_testo_multiriga(self):
        cl = checklist_from_text("Controlli", "Voce uno\n\nVoce due [V]\n")
        assert [i.label for i in cl.items] == ["Voce uno", "Voce due"]
        assert cl.items[1].unit == "V"

    def test_preserva_chiavi_per_etichetta(self):
        source = SimpleChecklist(title="Controlli", key="sec_orig", items=[
            SimpleChecklistItem(label="Voce uno", key="chiave_storica"),
        ])
        cl = checklist_from_text("Controlli", "Voce uno\nVoce nuova", source=source)
        assert cl.key == "sec_orig"
        assert cl.items[0].key == "chiave_storica"
        assert cl.items[1].key is None  # nuova voce: chiave generata al build


class TestBuildSections:
    def make_opts(self, **kw):
        defaults = dict(
            include_normative=True,
            normative_default="CEI 62353",
            checklists=[SimpleChecklist(title="Controlli Visivi", items=[
                SimpleChecklistItem(label="Integrità involucro"),
                SimpleChecklistItem(label="Lettura SpO2", unit="%"),
            ])],
            include_notes=True,
        )
        defaults.update(kw)
        return SimpleFunctionalOptions(**defaults)

    def test_struttura_canonica(self):
        sections = build_sections(self.make_opts())
        assert [s.section_type for s in sections] == ["fields", "checklist", "fields"]
        assert sections[0].fields[0].default == "CEI 62353"
        assert sections[2].fields[0].field_type == "multiline"

    def test_riga_con_unita(self):
        sections = build_sections(self.make_opts())
        rows = sections[1].rows
        assert len(rows[0].fields) == 1  # solo esito
        assert len(rows[1].fields) == 2  # esito + valore
        assert rows[1].fields[1].unit == "%"
        assert rows[1].fields[1].key == "valore"

    def test_esito_obbligatorio(self):
        sections = build_sections(self.make_opts())
        for row in sections[1].rows:
            esito = row.fields[0]
            assert esito.required is True
            assert esito.options == ["OK", "KO", "N.A."]

    def test_chiavi_uniche_per_voci_duplicate(self):
        opts = self.make_opts(checklists=[SimpleChecklist(title="C", items=[
            SimpleChecklistItem(label="Stessa voce"),
            SimpleChecklistItem(label="Stessa voce"),
        ])])
        rows = build_sections(opts)[1].rows
        assert rows[0].key != rows[1].key

    def test_checklist_vuota_saltata(self):
        opts = self.make_opts(checklists=[SimpleChecklist(title="Vuota", items=[])])
        sections = build_sections(opts)
        assert [s.section_type for s in sections] == ["fields", "fields"]

    def test_profilo_costruito_valido(self):
        profile = FunctionalProfile(
            profile_key="x", name="X",
            sections=build_sections(self.make_opts()),
        )
        assert validate_functional_profile(profile) == []


class TestRoundTrip:
    def test_round_trip_completo(self):
        opts = SimpleFunctionalOptions(
            include_normative=True, normative_default="CEI 62353",
            checklists=[
                SimpleChecklist(title="Visivi", items=[
                    SimpleChecklistItem(label="Involucro"),
                ]),
                SimpleChecklist(title="Funzionali", items=[
                    SimpleChecklistItem(label="Lettura FC", unit="bpm"),
                ]),
            ],
            include_notes=True,
        )
        sections = build_sections(opts)
        profile = FunctionalProfile(profile_key="rt", name="RT", sections=sections)
        parsed = parse_profile_sections(profile)
        assert parsed is not None
        assert build_sections(parsed) == sections

    def test_template_ecg_riconosciuto(self):
        ecg = FUNCTIONAL_PROFILE_TEMPLATES["ecg_fun"]
        parsed = parse_profile_sections(ecg)
        assert parsed is not None
        assert parsed.include_normative and parsed.include_notes
        assert len(parsed.checklists) == 2  # visivi + funzionalità
        assert build_sections(parsed) == ecg.sections

    def test_template_spo2_riconosciuto(self):
        spo2 = FUNCTIONAL_PROFILE_TEMPLATES["spo2_fun"]
        parsed = parse_profile_sections(spo2)
        assert parsed is not None
        assert build_sections(parsed) == spo2.sections

    def test_template_generico_riconosciuto(self):
        gen = FUNCTIONAL_PROFILE_TEMPLATES["generico_fun"]
        parsed = parse_profile_sections(gen)
        assert parsed is not None
        assert build_sections(parsed) == gen.sections

    def test_template_defibrillatore_va_in_modalita_completa(self):
        # Il defibrillatore ha una tabella con formule: non rientra nello schema
        defib = FUNCTIONAL_PROFILE_TEMPLATES["defibrillatore_fun"]
        assert parse_profile_sections(defib) is None

    def test_profilo_vuoto_apre_la_guidata(self):
        empty = FunctionalProfile(profile_key="e", name="E", sections=[])
        parsed = parse_profile_sections(empty)
        assert parsed is not None
        assert parsed.checklists == []


class TestParseRifiuta:
    def test_campo_con_formula(self):
        from app.functional_models import (
            FunctionalField, FunctionalRowDefinition, FunctionalSection,
        )
        p = FunctionalProfile(profile_key="x", name="X", sections=[
            FunctionalSection(key="c", title="C", section_type="checklist", rows=[
                FunctionalRowDefinition(key="r", label="R", fields=[
                    FunctionalField(key="esito", label="Esito", field_type="choice",
                                    options=["OK", "KO", "N.A."], required=True),
                    FunctionalField(key="valore", label="V", field_type="number",
                                    unit="J", formula="a - b"),
                ]),
            ]),
        ])
        assert parse_profile_sections(p) is None

    def test_esito_pass_fail_non_riconosciuto(self):
        from app.functional_models import (
            FunctionalField, FunctionalRowDefinition, FunctionalSection,
        )
        p = FunctionalProfile(profile_key="x", name="X", sections=[
            FunctionalSection(key="c", title="C", section_type="checklist", rows=[
                FunctionalRowDefinition(key="r", label="R", fields=[
                    FunctionalField(key="esito", label="Esito", field_type="pass_fail",
                                    options=["PASS", "FAIL", "N.A."], required=True),
                ]),
            ]),
        ])
        assert parse_profile_sections(p) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
