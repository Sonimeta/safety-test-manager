from __future__ import annotations

from app.functional_models import (
    FunctionalField,
    FunctionalProfile,
    FunctionalRowDefinition,
    FunctionalSection,
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
                    ),
                    FunctionalField(
                        key="error_j",
                        label="Errore (J)",
                        field_type="number",
                        unit="J",
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


FUNCTIONAL_PROFILE_TEMPLATES: dict[str, FunctionalProfile] = {
    "defibrillatore_fun": build_defibrillator_functional_profile(),
}


