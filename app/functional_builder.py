# app/functional_builder.py
"""Costruzione guidata dei profili funzionali (logica pura, testabile).

La modalità guidata copre la struttura più comune dei profili funzionali:

    [Riferimenti normativi]  +  N checklist  +  [Note aggiuntive]

Ogni checklist è scritta come testo semplice, una voce per riga:

    Integrità involucro
    Lettura saturazione dal simulatore [%]
    Lettura frequenza cardiaca [bpm]

Una voce genera una riga con campo esito OK/KO/N.A. obbligatorio; il
suffisso "[unità]" aggiunge anche un campo numerico "Valore (unità)".

Le sezioni con tabelle, formule o campi particolari non rientrano nello
schema: parse_profile_sections ritorna None e l'editor usa la modalità
completa. Le chiavi di sezioni e righe esistenti vengono preservate nel
round-trip per non disallineare i dati delle verifiche.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.functional_models import (
    FunctionalField,
    FunctionalProfile,
    FunctionalRowDefinition,
    FunctionalSection,
    sanitize_profile_key,
)

ESITO_OPTIONS = ["OK", "KO", "N.A."]
NORMATIVE_SECTION_KEY = "normative_references"
NOTES_SECTION_KEY = "notes"

# "Etichetta voce [unità]" — l'unità è opzionale
_ITEM_LINE_RE = re.compile(r"^(?P<label>.*?)(?:\s*\[(?P<unit>[^\[\]]+)\])?\s*$")


@dataclass
class SimpleChecklistItem:
    label: str
    unit: Optional[str] = None   # se presente aggiunge un campo numerico
    key: Optional[str] = None    # chiave originale da preservare


@dataclass
class SimpleChecklist:
    title: str
    items: List[SimpleChecklistItem] = field(default_factory=list)
    key: Optional[str] = None    # chiave sezione originale da preservare


@dataclass
class SimpleFunctionalOptions:
    include_normative: bool = True
    normative_default: str = ""
    checklists: List[SimpleChecklist] = field(default_factory=list)
    include_notes: bool = True
    # Chiavi originali da preservare nel round-trip (None = usa le canoniche)
    normative_key: Optional[str] = None
    notes_key: Optional[str] = None


def parse_item_line(line: str) -> Optional[SimpleChecklistItem]:
    """Interpreta una riga di testo della checklist. Ritorna None se vuota."""
    stripped = line.strip()
    if not stripped:
        return None
    match = _ITEM_LINE_RE.match(stripped)
    label = (match.group("label") or "").strip()
    unit = (match.group("unit") or "").strip() or None
    if not label:
        return None
    return SimpleChecklistItem(label=label, unit=unit)


def format_item_line(item: SimpleChecklistItem) -> str:
    return f"{item.label} [{item.unit}]" if item.unit else item.label


def checklist_from_text(title: str, text: str,
                        source: Optional[SimpleChecklist] = None) -> SimpleChecklist:
    """Costruisce una checklist dal testo dell'editor, preservando le chiavi
    delle voci della checklist di origine quando l'etichetta coincide."""
    source_by_label = {}
    if source:
        for item in source.items:
            if item.key and item.label not in source_by_label:
                source_by_label[item.label] = item.key

    items: List[SimpleChecklistItem] = []
    for line in text.splitlines():
        item = parse_item_line(line)
        if item is None:
            continue
        item.key = source_by_label.get(item.label)
        items.append(item)

    return SimpleChecklist(
        title=title.strip(),
        items=items,
        key=source.key if source else None,
    )


def _unique_key(base: str, used: set) -> str:
    key = base or "voce"
    if key not in used:
        used.add(key)
        return key
    suffix = 2
    while f"{key}_{suffix}" in used:
        suffix += 1
    key = f"{key}_{suffix}"
    used.add(key)
    return key


def build_sections(opts: SimpleFunctionalOptions) -> List[FunctionalSection]:
    """Genera le sezioni del profilo dalle opzioni della modalità guidata."""
    sections: List[FunctionalSection] = []

    normative_key = opts.normative_key or NORMATIVE_SECTION_KEY
    notes_key = opts.notes_key or NOTES_SECTION_KEY

    if opts.include_normative:
        sections.append(FunctionalSection(
            key=normative_key,
            title="Riferimenti Normativi-Procedure",
            section_type="fields",
            fields=[FunctionalField(
                key="norme_procedure",
                label="Norme/Procedure",
                field_type="text",
                default=opts.normative_default.strip() or None,
            )],
        ))

    used_section_keys = {normative_key, notes_key}
    for checklist in opts.checklists:
        if not checklist.items:
            continue
        section_key = checklist.key or sanitize_profile_key(checklist.title) or "checklist"
        section_key = _unique_key(section_key, used_section_keys)

        used_row_keys: set = set()
        rows: List[FunctionalRowDefinition] = []
        for item in checklist.items:
            row_key = item.key or sanitize_profile_key(item.label) or "voce"
            row_key = _unique_key(row_key, used_row_keys)
            fields = [FunctionalField(
                key="esito", label="Esito", field_type="choice",
                options=list(ESITO_OPTIONS), required=True,
            )]
            if item.unit:
                fields.append(FunctionalField(
                    key="valore", label=f"Valore ({item.unit})",
                    field_type="number", unit=item.unit,
                ))
            rows.append(FunctionalRowDefinition(key=row_key, label=item.label, fields=fields))

        sections.append(FunctionalSection(
            key=section_key,
            title=checklist.title or "Checklist",
            section_type="checklist",
            rows=rows,
        ))

    if opts.include_notes:
        sections.append(FunctionalSection(
            key=notes_key,
            title="Note aggiuntive",
            section_type="fields",
            fields=[FunctionalField(key="note", label="Note", field_type="multiline")],
        ))

    return sections


# ─── Riconoscimento di un profilo esistente ─────────────────────────────────

def _parse_checklist_row(row: FunctionalRowDefinition) -> Optional[SimpleChecklistItem]:
    fields = row.fields or []
    if not fields or len(fields) > 2:
        return None
    esito = fields[0]
    if (esito.key != "esito" or esito.field_type != "choice"
            or [o.upper() for o in esito.options] != ESITO_OPTIONS):
        return None
    unit = None
    if len(fields) == 2:
        value_field = fields[1]
        if (value_field.key != "valore" or value_field.field_type != "number"
                or value_field.formula):
            return None
        unit = value_field.unit or None
        if unit is None:
            return None
    label = (row.label or "").strip()
    if not label:
        return None
    return SimpleChecklistItem(label=label, unit=unit, key=row.key or None)


def _is_single_text_section(section: FunctionalSection, field_type: str) -> bool:
    return (
        section.section_type in {"fields", "form"}
        and len(section.fields or []) == 1
        and not section.rows
        and section.fields[0].field_type == field_type
        and not section.fields[0].formula
    )


def parse_profile_sections(profile: FunctionalProfile) -> Optional[SimpleFunctionalOptions]:
    """Riconduce le sezioni di un profilo alle opzioni della modalità guidata.

    Ritorna None se la struttura non rientra nello schema canonico
    ([normative] + checklists + [note]): in quel caso serve l'editor completo.
    """
    opts = SimpleFunctionalOptions(
        include_normative=False, normative_default="",
        checklists=[], include_notes=False,
    )

    sections = list(profile.sections or [])
    if not sections:
        return opts  # profilo vuoto: guidata con tutto da costruire

    idx = 0
    # Eventuale sezione normativa: solo come PRIMA sezione
    first = sections[0]
    if _is_single_text_section(first, "text"):
        opts.include_normative = True
        opts.normative_default = str(first.fields[0].default or "")
        opts.normative_key = first.key or None
        idx = 1

    # Eventuale sezione note: solo come ULTIMA sezione
    last_idx = len(sections)
    if last_idx > idx and _is_single_text_section(sections[last_idx - 1], "multiline"):
        opts.include_notes = True
        opts.notes_key = sections[last_idx - 1].key or None
        last_idx -= 1

    # In mezzo: solo checklist riconoscibili
    for section in sections[idx:last_idx]:
        if section.section_type != "checklist" or section.fields:
            return None
        items: List[SimpleChecklistItem] = []
        for row in section.rows or []:
            item = _parse_checklist_row(row)
            if item is None:
                return None
            items.append(item)
        if not items:
            return None
        opts.checklists.append(SimpleChecklist(
            title=section.title or section.key,
            items=items,
            key=section.key or None,
        ))

    return opts
