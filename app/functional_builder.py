# app/functional_builder.py
"""Costruzione guidata dei profili funzionali (logica pura, testabile).

La modalità guidata rappresenta il profilo come una lista ordinata di BLOCCHI:

- CHECKLIST: scritta come testo, una voce per riga; ogni voce genera una
  riga con esito OK/KO/N.A. obbligatorio. Il suffisso "[unità]" aggiunge
  anche un campo numerico "Valore (unità)".

- MODULO CAMPI: una riga compatta per campo (etichetta, tipo, dettaglio,
  obbligatorio). Supporta TUTTI i tipi di campo del programma; il campo
  "dettaglio" cambia significato in base al tipo:
      scelta multipla  -> opzioni separate da virgola
      numero/percent.  -> unità di misura
      testo/multilinea -> valore predefinito
      calcolato        -> formula (solo aritmetica: vale anche su mobile)
      valutazione      -> valore massimo (es. 5)

Le sezioni con tabelle a righe multiple (es. livelli di scarica del
defibrillatore) non rientrano nello schema: parse_profile_sections ritorna
None e l'editor usa la modalità completa.

Il round-trip preserva chiavi, descrizioni e le proprietà avanzate dei
campi esistenti (help_text, min/max, step, ...) tramite il campo `source`,
per non disallineare i dati delle verifiche passate.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import List, Optional, Union

from app.functional_models import (
    FunctionalField,
    FunctionalProfile,
    FunctionalRowDefinition,
    FunctionalSection,
    sanitize_profile_key,
)

ESITO_OPTIONS = ["OK", "KO", "N.A."]

# Tipi per cui il campo "dettaglio" ha un significato
DETAIL_OPTIONS_TYPES = {"choice"}
DETAIL_UNIT_TYPES = {"number", "integer", "percentage"}
DETAIL_DEFAULT_TYPES = {"text", "multiline"}
DETAIL_FORMULA_TYPES = {"calculated"}
DETAIL_RATING_TYPES = {"rating"}

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
    key: Optional[str] = None
    description: Optional[str] = None
    show_in_summary: bool = False


@dataclass
class SimpleFieldSpec:
    """Un campo di un modulo, nella forma compatta della guidata."""
    label: str
    field_type: str = "text"
    required: bool = False
    detail: str = ""               # significato dipendente dal tipo (v. modulo)
    key: Optional[str] = None
    source: Optional[FunctionalField] = None  # campo originale da preservare


@dataclass
class SimpleFormSection:
    title: str
    fields: List[SimpleFieldSpec] = field(default_factory=list)
    key: Optional[str] = None
    description: Optional[str] = None
    show_in_summary: bool = False


SimpleBlock = Union[SimpleChecklist, SimpleFormSection]


@dataclass
class SimpleFunctionalOptions:
    blocks: List[SimpleBlock] = field(default_factory=list)


# ─── Checklist: grammatica del testo ────────────────────────────────────────

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
        description=source.description if source else None,
        show_in_summary=source.show_in_summary if source else False,
    )


# ─── Dettaglio dei campi modulo ─────────────────────────────────────────────

def detail_for_field(f: FunctionalField) -> str:
    """Estrae dal campo il valore mostrato nella colonna 'dettaglio'."""
    ft = f.field_type
    if ft in DETAIL_OPTIONS_TYPES:
        return ", ".join(f.options or [])
    if ft in DETAIL_UNIT_TYPES:
        return f.unit or ""
    if ft in DETAIL_DEFAULT_TYPES:
        return "" if f.default is None else str(f.default)
    if ft in DETAIL_FORMULA_TYPES:
        return f.formula or ""
    if ft in DETAIL_RATING_TYPES:
        return "" if f.rating_max is None else str(f.rating_max)
    return ""


def detail_placeholder(field_type: str) -> str:
    """Suggerimento per la colonna 'dettaglio' nella UI."""
    if field_type in DETAIL_OPTIONS_TYPES:
        return "Opzioni: OK, KO, N.A."
    if field_type in DETAIL_UNIT_TYPES:
        return "Unità (es. mmHg)"
    if field_type in DETAIL_DEFAULT_TYPES:
        return "Valore predefinito (opzionale)"
    if field_type in DETAIL_FORMULA_TYPES:
        return "Formula (es. misurato - impostato)"
    if field_type in DETAIL_RATING_TYPES:
        return "Massimo (es. 5)"
    return "—"


def _apply_detail(f: FunctionalField, detail: str) -> None:
    ft = f.field_type
    detail = detail.strip()
    if ft in DETAIL_OPTIONS_TYPES:
        f.options = [opt.strip() for opt in detail.split(",") if opt.strip()]
    elif ft in DETAIL_UNIT_TYPES:
        f.unit = detail or None
    elif ft in DETAIL_DEFAULT_TYPES:
        f.default = detail or None
    elif ft in DETAIL_FORMULA_TYPES:
        f.formula = detail or None
        f.read_only = True
    elif ft in DETAIL_RATING_TYPES:
        try:
            f.rating_max = int(detail) if detail else None
        except ValueError:
            f.rating_max = None


def build_field(spec: SimpleFieldSpec, key: str) -> FunctionalField:
    """Costruisce il FunctionalField da una spec, preservando le proprietà
    avanzate del campo originale quando il tipo non è cambiato."""
    if spec.source is not None and spec.source.field_type == spec.field_type:
        f = copy.deepcopy(spec.source)
        f.key = key
        f.label = spec.label
        f.required = spec.required
    else:
        f = FunctionalField(
            key=key, label=spec.label,
            field_type=spec.field_type, required=spec.required,
        )
    _apply_detail(f, spec.detail)
    return f


# ─── Costruzione delle sezioni ──────────────────────────────────────────────

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
    """Genera le sezioni del profilo dai blocchi della modalità guidata."""
    sections: List[FunctionalSection] = []
    used_section_keys: set = set()

    for block in opts.blocks:
        if isinstance(block, SimpleChecklist):
            if not block.items:
                continue
            section_key = block.key or sanitize_profile_key(block.title) or "checklist"
            section_key = _unique_key(section_key, used_section_keys)

            used_row_keys: set = set()
            rows: List[FunctionalRowDefinition] = []
            for item in block.items:
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
                rows.append(FunctionalRowDefinition(
                    key=row_key, label=item.label, fields=fields))

            sections.append(FunctionalSection(
                key=section_key,
                title=block.title or "Checklist",
                section_type="checklist",
                description=block.description or "",
                rows=rows,
                show_in_summary=block.show_in_summary,
            ))

        else:  # SimpleFormSection
            if not block.fields:
                continue
            section_key = block.key or sanitize_profile_key(block.title) or "sezione"
            section_key = _unique_key(section_key, used_section_keys)

            used_field_keys: set = set()
            fields: List[FunctionalField] = []
            for spec in block.fields:
                base_key = spec.key or sanitize_profile_key(spec.label) or "campo"
                field_key = _unique_key(base_key, used_field_keys)
                fields.append(build_field(spec, field_key))

            sections.append(FunctionalSection(
                key=section_key,
                title=block.title or "Sezione",
                section_type="fields",
                description=block.description or "",
                fields=fields,
                show_in_summary=block.show_in_summary,
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


def parse_profile_sections(profile: FunctionalProfile) -> Optional[SimpleFunctionalOptions]:
    """Riconduce le sezioni di un profilo ai blocchi della modalità guidata.

    Ritorna None se una sezione non è rappresentabile (tabelle a righe
    multiple non-checklist, righe checklist con campi non standard):
    in quel caso serve l'editor completo.
    """
    opts = SimpleFunctionalOptions(blocks=[])

    for section in profile.sections or []:
        if section.section_type == "checklist" and not section.fields:
            items: List[SimpleChecklistItem] = []
            ok = True
            for row in section.rows or []:
                item = _parse_checklist_row(row)
                if item is None:
                    ok = False
                    break
                items.append(item)
            if not ok or not items:
                return None
            opts.blocks.append(SimpleChecklist(
                title=section.title or section.key,
                items=items,
                key=section.key or None,
                description=section.description or None,
                show_in_summary=bool(section.show_in_summary),
            ))

        elif section.section_type in {"fields", "form"} and not section.rows:
            if not section.fields:
                return None
            specs = [
                SimpleFieldSpec(
                    label=f.label or f.key,
                    field_type=f.field_type,
                    required=bool(f.required),
                    detail=detail_for_field(f),
                    key=f.key or None,
                    source=f,
                )
                for f in section.fields
            ]
            opts.blocks.append(SimpleFormSection(
                title=section.title or section.key,
                fields=specs,
                key=section.key or None,
                description=section.description or None,
                show_in_summary=bool(section.show_in_summary),
            ))

        else:
            return None  # tabella o struttura particolare: editor completo

    return opts


def default_new_profile_blocks() -> List[SimpleBlock]:
    """Blocchi proposti per un profilo nuovo: punto di partenza tipico."""
    return [
        SimpleFormSection(
            title="Riferimenti Normativi-Procedure",
            key="normative_references",
            fields=[SimpleFieldSpec(label="Norme/Procedure", field_type="text",
                                    key="norme_procedure")],
        ),
        SimpleChecklist(
            title="Controllo Visivo/Funzionale",
            items=[
                SimpleChecklistItem(label="Integrità generale apparecchiatura"),
                SimpleChecklistItem(label="Leggibilità delle serigrafie/etichette"),
                SimpleChecklistItem(label="Integrità cavo di alimentazione"),
                SimpleChecklistItem(label="Integrità involucro"),
                SimpleChecklistItem(label="Integrità accessori"),
                SimpleChecklistItem(label="Manuale d'uso disponibile"),
            ],
        ),
        SimpleFormSection(
            title="Note aggiuntive",
            key="notes",
            fields=[SimpleFieldSpec(label="Note", field_type="multiline", key="note")],
        ),
    ]
