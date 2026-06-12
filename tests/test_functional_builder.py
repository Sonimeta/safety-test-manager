# tests/test_functional_builder.py
"""Test della modalità guidata dei profili funzionali (app/functional_builder.py)."""
import pytest

from app.functional_builder import (
    SimpleChecklist,
    SimpleChecklistItem,
    SimpleFieldSpec,
    SimpleFormSection,
    SimpleFunctionalOptions,
    build_sections,
    checklist_from_text,
    default_new_profile_blocks,
    detail_for_field,
    format_item_line,
    parse_item_line,
    parse_profile_sections,
)
from app.functional_models import (
    FunctionalField,
    FunctionalProfile,
    FunctionalRowDefinition,
    FunctionalSection,
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

    def test_riga_vuota(self):
        assert parse_item_line("") is None
        assert parse_item_line("   ") is None

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
        assert cl.items[1].key is None


class TestBuildChecklist:
    def make_opts(self):
        return SimpleFunctionalOptions(blocks=[
            SimpleChecklist(title="Controlli Visivi", items=[
                SimpleChecklistItem(label="Integrità involucro"),
                SimpleChecklistItem(label="Lettura SpO2", unit="%"),
            ]),
        ])

    def test_struttura(self):
        sections = build_sections(self.make_opts())
        assert len(sections) == 1
        rows = sections[0].rows
        assert len(rows[0].fields) == 1   # solo esito
        assert len(rows[1].fields) == 2   # esito + valore
        assert rows[1].fields[1].unit == "%"

    def test_esito_obbligatorio(self):
        for row in build_sections(self.make_opts())[0].rows:
            assert row.fields[0].required is True
            assert row.fields[0].options == ["OK", "KO", "N.A."]

    def test_chiavi_uniche_per_voci_duplicate(self):
        opts = SimpleFunctionalOptions(blocks=[SimpleChecklist(title="C", items=[
            SimpleChecklistItem(label="Stessa voce"),
            SimpleChecklistItem(label="Stessa voce"),
        ])])
        rows = build_sections(opts)[0].rows
        assert rows[0].key != rows[1].key

    def test_checklist_vuota_saltata(self):
        opts = SimpleFunctionalOptions(blocks=[SimpleChecklist(title="Vuota")])
        assert build_sections(opts) == []


class TestBuildFormSection:
    def test_tutti_i_tipi_di_campo(self):
        tipi = ["text", "multiline", "number", "integer", "choice", "bool",
                "date", "time", "percentage", "rating", "pass_fail",
                "header", "calculated"]
        block = SimpleFormSection(title="Tutti i tipi", fields=[
            SimpleFieldSpec(label=f"Campo {t}", field_type=t) for t in tipi
        ])
        sections = build_sections(SimpleFunctionalOptions(blocks=[block]))
        assert [f.field_type for f in sections[0].fields] == tipi

    def test_dettaglio_opzioni(self):
        spec = SimpleFieldSpec(label="Esito", field_type="choice",
                               detail="OK, KO, N.A.")
        sections = build_sections(SimpleFunctionalOptions(
            blocks=[SimpleFormSection(title="S", fields=[spec])]))
        assert sections[0].fields[0].options == ["OK", "KO", "N.A."]

    def test_dettaglio_unita(self):
        spec = SimpleFieldSpec(label="Pressione", field_type="number", detail="mmHg")
        sections = build_sections(SimpleFunctionalOptions(
            blocks=[SimpleFormSection(title="S", fields=[spec])]))
        assert sections[0].fields[0].unit == "mmHg"

    def test_dettaglio_default_testo(self):
        spec = SimpleFieldSpec(label="Norme", field_type="text", detail="CEI 62353")
        sections = build_sections(SimpleFunctionalOptions(
            blocks=[SimpleFormSection(title="S", fields=[spec])]))
        assert sections[0].fields[0].default == "CEI 62353"

    def test_dettaglio_formula_calcolato(self):
        spec = SimpleFieldSpec(label="Errore", field_type="calculated",
                               detail="a - b")
        f = build_sections(SimpleFunctionalOptions(
            blocks=[SimpleFormSection(title="S", fields=[spec])]))[0].fields[0]
        assert f.formula == "a - b"
        assert f.read_only is True

    def test_dettaglio_rating_max(self):
        spec = SimpleFieldSpec(label="Stato", field_type="rating", detail="10")
        f = build_sections(SimpleFunctionalOptions(
            blocks=[SimpleFormSection(title="S", fields=[spec])]))[0].fields[0]
        assert f.rating_max == 10

    def test_source_preserva_proprieta_avanzate(self):
        original = FunctionalField(
            key="x", label="X", field_type="number", unit="J",
            help_text="aiuto", min_value=0, max_value=100, step=0.5,
        )
        spec = SimpleFieldSpec(label="X rinominato", field_type="number",
                               detail="J", key="x", source=original)
        f = build_sections(SimpleFunctionalOptions(
            blocks=[SimpleFormSection(title="S", fields=[spec])]))[0].fields[0]
        assert f.label == "X rinominato"
        assert f.help_text == "aiuto" and f.max_value == 100 and f.step == 0.5

    def test_cambio_tipo_riparte_da_campo_pulito(self):
        original = FunctionalField(key="x", label="X", field_type="number",
                                   unit="J", help_text="aiuto")
        spec = SimpleFieldSpec(label="X", field_type="date", key="x", source=original)
        f = build_sections(SimpleFunctionalOptions(
            blocks=[SimpleFormSection(title="S", fields=[spec])]))[0].fields[0]
        assert f.field_type == "date"
        assert f.unit is None and f.help_text is None

    def test_modulo_vuoto_saltato(self):
        opts = SimpleFunctionalOptions(blocks=[SimpleFormSection(title="Vuoto")])
        assert build_sections(opts) == []


class TestRoundTrip:
    def test_round_trip_misto(self):
        opts = SimpleFunctionalOptions(blocks=[
            SimpleFormSection(title="Dati", fields=[
                SimpleFieldSpec(label="Norme", field_type="text", detail="CEI 62353"),
                SimpleFieldSpec(label="Data prova", field_type="date"),
            ]),
            SimpleChecklist(title="Visivi", items=[
                SimpleChecklistItem(label="Involucro"),
                SimpleChecklistItem(label="Lettura FC", unit="bpm"),
            ]),
        ])
        sections = build_sections(opts)
        profile = FunctionalProfile(profile_key="rt", name="RT", sections=sections)
        parsed = parse_profile_sections(profile)
        assert parsed is not None
        assert build_sections(parsed) == sections

    @pytest.mark.parametrize("template_key", ["ecg_fun", "spo2_fun", "generico_fun"])
    def test_template_riconosciuti(self, template_key):
        template = FUNCTIONAL_PROFILE_TEMPLATES[template_key]
        parsed = parse_profile_sections(template)
        assert parsed is not None, f"template {template_key} non riconosciuto"
        assert build_sections(parsed) == template.sections

    def test_template_defibrillatore_va_in_modalita_completa(self):
        defib = FUNCTIONAL_PROFILE_TEMPLATES["defibrillatore_fun"]
        assert parse_profile_sections(defib) is None

    def test_profilo_vuoto(self):
        empty = FunctionalProfile(profile_key="e", name="E", sections=[])
        parsed = parse_profile_sections(empty)
        assert parsed is not None and parsed.blocks == []

    def test_show_in_summary_preservato(self):
        section = FunctionalSection(
            key="s", title="S", section_type="fields", show_in_summary=True,
            fields=[FunctionalField(key="f", label="F", field_type="text")],
        )
        p = FunctionalProfile(profile_key="x", name="X", sections=[section])
        parsed = parse_profile_sections(p)
        assert build_sections(parsed)[0].show_in_summary is True

    def test_descrizione_sezione_preservata(self):
        section = FunctionalSection(
            key="s", title="S", section_type="fields", description="istruzioni",
            fields=[FunctionalField(key="f", label="F", field_type="text")],
        )
        p = FunctionalProfile(profile_key="x", name="X", sections=[section])
        parsed = parse_profile_sections(p)
        assert build_sections(parsed)[0].description == "istruzioni"


class TestParseRifiuta:
    def test_tabella_va_in_completa(self):
        p = FunctionalProfile(profile_key="x", name="X", sections=[
            FunctionalSection(key="t", title="T", section_type="table", rows=[
                FunctionalRowDefinition(key="r", label="R", fields=[
                    FunctionalField(key="a", label="A", field_type="number"),
                    FunctionalField(key="b", label="B", field_type="number"),
                    FunctionalField(key="c", label="C", field_type="number"),
                ]),
            ]),
        ])
        assert parse_profile_sections(p) is None

    def test_checklist_con_esito_pass_fail(self):
        p = FunctionalProfile(profile_key="x", name="X", sections=[
            FunctionalSection(key="c", title="C", section_type="checklist", rows=[
                FunctionalRowDefinition(key="r", label="R", fields=[
                    FunctionalField(key="esito", label="Esito", field_type="pass_fail",
                                    options=["PASS", "FAIL", "N.A."], required=True),
                ]),
            ]),
        ])
        assert parse_profile_sections(p) is None


class TestDefaultNewProfile:
    def test_blocchi_di_partenza(self):
        blocks = default_new_profile_blocks()
        assert len(blocks) == 3
        sections = build_sections(SimpleFunctionalOptions(blocks=blocks))
        assert [s.section_type for s in sections] == ["fields", "checklist", "fields"]
        assert len(sections[1].rows) == 6
        profile = FunctionalProfile(profile_key="n", name="N", sections=sections)
        assert validate_functional_profile(profile) == []

    def test_detail_for_field_simmetrico(self):
        # detail_for_field deve essere l'inverso di _apply_detail
        f = FunctionalField(key="x", label="X", field_type="choice",
                            options=["A", "B"])
        assert detail_for_field(f) == "A, B"
        f2 = FunctionalField(key="y", label="Y", field_type="rating", rating_max=7)
        assert detail_for_field(f2) == "7"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
