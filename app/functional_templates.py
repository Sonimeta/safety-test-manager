from __future__ import annotations

from app.functional_models import (
    FunctionalField,
    FunctionalProfile,
    FunctionalRowDefinition,
    FunctionalSection,
)

# NOTA SULLE FORMULE: devono restare aritmetica semplice (+ - * / e parentesi)
# perché vengono valutate sia dal motore Python desktop sia da quello
# JavaScript della versione mobile (sostituzione testuale dei nomi campo).


def _esito_field(required: bool = True) -> FunctionalField:
    """Campo esito standard OK/KO/N.A. usato nelle checklist."""
    return FunctionalField(
        key="esito",
        label="Esito",
        field_type="choice",
        options=["OK", "KO", "N.A."],
        required=required,
    )


def _checklist_row(key: str, label: str, extra_fields: list[FunctionalField] | None = None,
                   required: bool = True) -> FunctionalRowDefinition:
    return FunctionalRowDefinition(
        key=key, label=label,
        fields=[_esito_field(required)] + list(extra_fields or []),
    )


def build_visual_checks_section() -> FunctionalSection:
    """Sezione standard di controllo visivo/funzionale, comune a tutti i profili."""
    return FunctionalSection(
        key="visual_checks",
        title="Controllo Visivo/Funzionale",
        section_type="checklist",
        rows=[
            _checklist_row("integrita_generale", "Integrità generale apparecchiatura"),
            _checklist_row("serigrafie", "Leggibilità delle serigrafie/etichette"),
            _checklist_row("cavo_alimentazione", "Integrità cavo di alimentazione"),
            _checklist_row("involucro", "Integrità involucro"),
            _checklist_row("accessori", "Integrità accessori"),
            _checklist_row("manuale", "Manuale d'uso disponibile"),
        ],
    )


def build_normative_section(default_norm: str = "") -> FunctionalSection:
    return FunctionalSection(
        key="normative_references",
        title="Riferimenti Normativi-Procedure",
        section_type="fields",
        fields=[
            FunctionalField(
                key="norme_procedure",
                label="Norme/Procedure",
                field_type="text",
                default=default_norm or None,
            )
        ],
    )


def build_notes_section() -> FunctionalSection:
    return FunctionalSection(
        key="notes",
        title="Note aggiuntive",
        section_type="fields",
        fields=[
            FunctionalField(key="note", label="Note", field_type="multiline"),
        ],
    )


def build_defibrillator_functional_profile() -> FunctionalProfile:
    visual_section = FunctionalSection(
        key="visual_checks",
        title="Controllo Visivo/Funzionale",
        section_type="checklist",
        rows=[
            FunctionalRowDefinition(
                key="serigrafie",
                label="Leggibilità delle serigrafie",
                fields=[
                    FunctionalField(
                        key="esito",
                        label="Esito",
                        field_type="choice",
                        options=["OK", "KO", "N.A."],
                        required=True,
                    )
                ],
            ),
            FunctionalRowDefinition(
                key="manuale",
                label="Manuale d'uso disponibile",
                fields=[
                    FunctionalField(
                        key="esito",
                        label="Esito",
                        field_type="choice",
                        options=["OK", "KO", "N.A."],
                        required=True,
                    )
                ],
            ),
            FunctionalRowDefinition(
                key="involucro",
                label="Integrità involucro",
                fields=[
                    FunctionalField(
                        key="esito",
                        label="Esito",
                        field_type="choice",
                        options=["OK", "KO", "N.A."],
                        required=True,
                    )
                ],
            ),
            FunctionalRowDefinition(
                key="accessori",
                label="Integrità accessori",
                fields=[
                    FunctionalField(
                        key="esito",
                        label="Esito",
                        field_type="choice",
                        options=["OK", "KO", "N.A."],
                        required=True,
                    )
                ],
            ),
        ],
    )

    discharge_rows = []
    for joule in [50, 100, 150, 200, 300]:
        discharge_rows.append(
            FunctionalRowDefinition(
                key=f"level_{joule}",
                label=f"{joule} J",
                fields=[
                    FunctionalField(
                        key="set_value",
                        label="Valore impostato (J)",
                        field_type="number",
                        unit="J",
                        default=joule,
                        read_only=True,
                    ),
                    FunctionalField(
                        key="measured_value",
                        label="Valore misurato (J)",
                        field_type="number",
                        unit="J",
                    ),
                    FunctionalField(
                        key="error_percent",
                        label="Errore %",
                        field_type="number",
                        unit="%",
                        read_only=True,
                        formula="(measured_value - set_value) / set_value * 100",
                        precision=1,
                    ),
                    FunctionalField(
                        key="error_j",
                        label="Errore (J)",
                        field_type="number",
                        unit="J",
                        read_only=True,
                        formula="measured_value - set_value",
                        precision=2,
                    ),
                    FunctionalField(
                        key="charge_time",
                        label="Tempo di carica",
                        field_type="number",
                        unit="s",
                    ),
                    FunctionalField(
                        key="esito",
                        label="Esito",
                        field_type="choice",
                        options=["OK", "KO"],
                        required=True,
                    ),
                ],
            )
        )

    discharge_section = FunctionalSection(
        key="discharge_levels",
        title="Controllo Livelli Scarica",
        section_type="table",
        description=(
            "Non deve differire del ±3J o ±15% (prendere il valore maggiore). "
            "Compilare anche il tempo di carica."
        ),
        rows=discharge_rows,
    )

    functionality_section = FunctionalSection(
        key="functional_checks",
        title="Controllo Funzionalità",
        section_type="checklist",
        rows=[
            FunctionalRowDefinition(
                key="auto_disarm",
                label="Disarmo automatico",
                fields=[
                    FunctionalField(
                        key="esito",
                        label="Esito",
                        field_type="choice",
                        options=["OK", "KO", "N.A."],
                        required=True,
                    ),
                    FunctionalField(
                        key="tempo",
                        label="Tempo (s)",
                        field_type="number",
                        unit="s",
                    ),
                ],
            ),
            FunctionalRowDefinition(
                key="cable_alarm",
                label="Allarme cavo non collegato",
                fields=[
                    FunctionalField(
                        key="esito",
                        label="Esito",
                        field_type="choice",
                        options=["OK", "KO", "N.A."],
                        required=True,
                    )
                ],
            ),
            FunctionalRowDefinition(
                key="pads_alarm",
                label="Allarme piastre non collegate",
                fields=[
                    FunctionalField(
                        key="esito",
                        label="Esito",
                        field_type="choice",
                        options=["OK", "KO", "N.A."],
                        required=True,
                    )
                ],
            ),
        ],
    )

    consumable_section = FunctionalSection(
        key="consumables",
        title="Controllo Consumabili",
        section_type="checklist",
        rows=[
            FunctionalRowDefinition(
                key="electrodes",
                label="Elettrodi",
                fields=[
                    FunctionalField(
                        key="esito",
                        label="Esito",
                        field_type="choice",
                        options=["OK", "KO", "N.A."],
                    ),
                    FunctionalField(
                        key="data",
                        label="Data",
                        field_type="text",
                    ),
                ],
            ),
            FunctionalRowDefinition(
                key="battery",
                label="Batteria",
                fields=[
                    FunctionalField(
                        key="esito",
                        label="Esito",
                        field_type="choice",
                        options=["OK", "KO", "N.A."],
                    ),
                    FunctionalField(
                        key="data",
                        label="Data",
                        field_type="text",
                    ),
                ],
            ),
        ],
    )

    notes_section = FunctionalSection(
        key="notes",
        title="Note aggiuntive",
        section_type="fields",
        fields=[
            FunctionalField(
                key="note",
                label="Note",
                field_type="multiline",
            )
        ],
    )

    return FunctionalProfile(
        profile_key="defibrillatore_fun",
        name="Defibrillatore - Verifica Funzionale",
        device_type="DEFIBRILLATORE",
        sections=[
            visual_section,
            discharge_section,
            functionality_section,
            consumable_section,
            notes_section,
        ],
    )


def build_ecg_functional_profile() -> FunctionalProfile:
    return FunctionalProfile(
        profile_key="ecg_fun",
        name="ECG/Monitor ECG - Verifica Funzionale",
        device_type="ECG",
        sections=[
            build_normative_section("CEI 62-26/AMS-MOD-PROVECG1"),
            build_visual_checks_section(),
            FunctionalSection(
                key="functional_checks",
                title="Controllo Funzionalità",
                section_type="checklist",
                rows=[
                    _checklist_row("traccia", "Visualizzazione corretta della traccia ECG"),
                    _checklist_row("frequenza", "Lettura frequenza cardiaca dal simulatore",
                                   extra_fields=[FunctionalField(
                                       key="valore", label="Valore letto (bpm)",
                                       field_type="number", unit="bpm")]),
                    _checklist_row("allarmi", "Funzionamento allarmi"),
                    _checklist_row("stampa", "Stampa/registrazione traccia", required=False),
                ],
            ),
            build_notes_section(),
        ],
    )


def build_spo2_functional_profile() -> FunctionalProfile:
    return FunctionalProfile(
        profile_key="spo2_fun",
        name="Monitor SpO2 - Verifica Funzionale",
        device_type="SPO2",
        sections=[
            build_normative_section(),
            build_visual_checks_section(),
            FunctionalSection(
                key="functional_checks",
                title="Controllo Funzionalità",
                section_type="checklist",
                rows=[
                    _checklist_row("lettura_sat", "Lettura saturazione dal simulatore",
                                   extra_fields=[FunctionalField(
                                       key="valore", label="Valore letto (%)",
                                       field_type="number", unit="%")]),
                    _checklist_row("lettura_fc", "Lettura frequenza cardiaca dal simulatore",
                                   extra_fields=[FunctionalField(
                                       key="valore", label="Valore letto (bpm)",
                                       field_type="number", unit="bpm")]),
                    _checklist_row("allarmi", "Funzionamento allarmi"),
                    _checklist_row("sensore", "Integrità sensore e cavo"),
                ],
            ),
            build_notes_section(),
        ],
    )


def build_generic_functional_profile() -> FunctionalProfile:
    """Template minimo: checklist visiva standard + note."""
    return FunctionalProfile(
        profile_key="generico_fun",
        name="Verifica Funzionale Generica",
        device_type=None,
        sections=[
            build_normative_section(),
            build_visual_checks_section(),
            build_notes_section(),
        ],
    )


# Unica fonte dei template: usata dal wizard di creazione profili
# e dall'eventuale seeding iniziale (STM_SEED_FUNCTIONAL_TEMPLATES)
FUNCTIONAL_PROFILE_TEMPLATES: dict[str, FunctionalProfile] = {
    "defibrillatore_fun": build_defibrillator_functional_profile(),
    "ecg_fun": build_ecg_functional_profile(),
    "spo2_fun": build_spo2_functional_profile(),
    "generico_fun": build_generic_functional_profile(),
}


