from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FunctionalField:
    """
    Descrive un singolo input per una sezione di verifica funzionale.

    Tipi supportati:
      text, multiline, number, integer, choice, bool,
      date, time, percentage, rating, pass_fail, header, calculated
    """
    key: str
    label: str
    field_type: str  # text, number, choice, bool, multiline, date, time, percentage, rating, pass_fail, header, calculated
    required: bool = False
    unit: Optional[str] = None
    options: List[str] = field(default_factory=list)
    read_only: bool = False
    default: Optional[Any] = None
    help_text: Optional[str] = None
    formula: Optional[str] = None
    precision: Optional[int] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    placeholder: Optional[str] = None
    rating_max: Optional[int] = None  # Valore massimo per rating (default 5)


@dataclass
class FunctionalRowDefinition:
    """
    Rappresenta una riga di tabella composta da più campi.
    """
    key: str
    label: Optional[str] = None
    fields: List[FunctionalField] = field(default_factory=list)


@dataclass
class FunctionalSection:
    """
    Sezione logica del profilo funzionale. Può essere un modulo semplice,
    una check-list o una tabella a più righe.
    """
    key: str
    title: str
    section_type: str  # fields | checklist | table
    description: Optional[str] = ""
    fields: List[FunctionalField] = field(default_factory=list)
    rows: List[FunctionalRowDefinition] = field(default_factory=list)
    show_in_summary: bool = False  # Se True, la sezione appare nella prima pagina del report


@dataclass
class FunctionalProfile:
    """
    Definizione completa di un profilo di verifica funzionale.
    """
    profile_key: str
    name: str
    device_type: Optional[str] = None
    instrument_ids: List[int] = field(default_factory=list)  # Lista di ID strumenti disponibili per questo profilo
    instrument_snapshots: List[Dict[str, Any]] = field(default_factory=list)  # Snapshot strumenti associati
    required_min_instruments: int = 0  # Minimo strumenti da selezionare in avvio verifica
    allowed_instrument_types: List[str] = field(default_factory=list)  # Tipi consentiti (es: functional, electrical)
    sections: List[FunctionalSection] = field(default_factory=list)


@dataclass
class FunctionalResult:
    """
    Risultato raccolto per una singola sezione della verifica funzionale.
    """
    section_key: str
    data: Dict[str, Any]


def _safe_float(value: Any) -> Optional[float]:
    """Converte un valore in float, restituisce None in caso di errore."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    """Converte un valore in int, restituisce None in caso di errore."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def functional_field_from_dict(data: Dict[str, Any]) -> FunctionalField:
    precision_value: Optional[int] = None
    if "precision" in data:
        try:
            precision_value = int(data.get("precision"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            precision_value = None

    formula_value = (str(data.get("formula")).strip() or None) if data.get("formula") else None
    read_only_flag = bool(data.get("read_only", False))
    if formula_value and not read_only_flag:
        read_only_flag = True

    return FunctionalField(
        key=str(data.get("key", "")).strip(),
        label=data.get("label", ""),
        field_type=str(data.get("field_type", "text")).strip(),
        required=bool(data.get("required", False)),
        unit=data.get("unit"),
        options=list(data.get("options") or []),
        read_only=read_only_flag,
        default=data.get("default"),
        help_text=data.get("help_text"),
        formula=formula_value,
        precision=precision_value,
        min_value=_safe_float(data.get("min_value")),
        max_value=_safe_float(data.get("max_value")),
        step=_safe_float(data.get("step")),
        placeholder=data.get("placeholder"),
        rating_max=_safe_int(data.get("rating_max")),
    )


def functional_row_from_dict(data: Dict[str, Any]) -> FunctionalRowDefinition:
    fields_data = data.get("fields", []) or []
    fields = [functional_field_from_dict(field) for field in fields_data]
    return FunctionalRowDefinition(
        key=str(data.get("key", "")).strip(),
        label=data.get("label"),
        fields=fields,
    )


def functional_section_from_dict(data: Dict[str, Any]) -> FunctionalSection:
    fields_data = data.get("fields", []) or []
    rows_data = data.get("rows", []) or []
    fields = [functional_field_from_dict(field) for field in fields_data]
    rows = [functional_row_from_dict(row) for row in rows_data]
    return FunctionalSection(
        key=str(data.get("key", "")).strip(),
        title=data.get("title", ""),
        section_type=str(data.get("section_type", "fields")).strip(),
        description=data.get("description"),
        fields=fields,
        rows=rows,
        show_in_summary=bool(data.get("show_in_summary", False)),
    )


def functional_profile_from_dict(data: Dict[str, Any]) -> FunctionalProfile:
    sections_data = data.get("sections", []) or []
    sections = [functional_section_from_dict(section) for section in sections_data]
    
    # Gestisce sia la vecchia versione (instrument_id singolo) che la nuova (instrument_ids lista)
    instrument_ids = []
    if "instrument_ids" in data:
        # Nuova versione: lista di ID
        ids_data = data.get("instrument_ids", [])
        if isinstance(ids_data, list):
            for inst_id in ids_data:
                try:
                    instrument_ids.append(int(inst_id))
                except (TypeError, ValueError):
                    pass
    elif "instrument_id" in data:
        # Vecchia versione: singolo ID (retrocompatibilità)
        instrument_id = data.get("instrument_id")
        if instrument_id is not None:
            try:
                instrument_ids.append(int(instrument_id))
            except (TypeError, ValueError):
                pass
    
    snapshots = data.get("instrument_snapshots", []) or []
    if not isinstance(snapshots, list):
        snapshots = []

    allowed_types = data.get("allowed_instrument_types", []) or []
    if not isinstance(allowed_types, list):
        allowed_types = []

    min_required = data.get("required_min_instruments", 0)
    try:
        min_required = int(min_required)
    except (TypeError, ValueError):
        min_required = 0

    return FunctionalProfile(
        profile_key=str(data.get("profile_key", "")).strip(),
        name=data.get("name", ""),
        device_type=data.get("device_type"),
        instrument_ids=instrument_ids,
        instrument_snapshots=[snap for snap in snapshots if isinstance(snap, dict)],
        required_min_instruments=max(0, min_required),
        allowed_instrument_types=[str(t).strip() for t in allowed_types if str(t).strip()],
        sections=sections,
    )


def functional_profile_to_dict(profile: FunctionalProfile) -> Dict[str, Any]:
    return asdict(profile)


def sanitize_profile_key(value: str) -> str:
    key = value.strip().lower()
    for char in (" ", "-", ".", ","):
        key = key.replace(char, "_")
    return "".join(c for c in key if c.isalnum() or c == "_")


def validate_functional_profile(profile: FunctionalProfile) -> List[str]:
    errors: List[str] = []
    if not profile.profile_key:
        errors.append("La chiave del profilo è obbligatoria.")
    if not profile.name:
        errors.append("Il nome del profilo è obbligatorio.")
    if not profile.sections:
        errors.append("Aggiungere almeno una sezione al profilo.")
    if profile.required_min_instruments < 0:
        errors.append("Il numero minimo di strumenti non può essere negativo.")

    section_keys = set()
    for section in profile.sections:
        if not section.key:
            errors.append(f"Sezione senza chiave: {section.title or '(senza titolo)'}")
        elif section.key in section_keys:
            errors.append(f"Chiave sezione duplicata: {section.key}")
        section_keys.add(section.key)

        if section.section_type in {"fields", "form"}:
            if not section.fields:
                errors.append(f"La sezione '{section.title or section.key}' deve contenere almeno un campo.")
            field_keys = set()
            for field in section.fields:
                if not field.key:
                    errors.append(
                        f"Campo senza chiave nella sezione '{section.title or section.key}'."
                    )
                elif field.key in field_keys:
                    errors.append(
                        f"Chiave campo duplicata '{field.key}' nella sezione '{section.title or section.key}'."
                    )
                field_keys.add(field.key)
        else:
            if not section.rows:
                errors.append(f"La sezione '{section.title or section.key}' deve contenere almeno una riga.")
            row_keys = set()
            for row in section.rows:
                if not row.key:
                    errors.append(
                        f"Riga senza chiave nella sezione '{section.title or section.key}'."
                    )
                elif row.key in row_keys:
                    errors.append(
                        f"Chiave riga duplicata '{row.key}' nella sezione '{section.title or section.key}'."
                    )
                row_keys.add(row.key)

                field_keys = set()
                for field in row.fields:
                    if not field.key:
                        errors.append(
                            f"Campo senza chiave nella riga '{row.label or row.key}' della sezione '{section.title or section.key}'."
                        )
                    elif field.key in field_keys:
                        errors.append(
                            f"Chiave campo duplicata '{field.key}' nella riga '{row.label or row.key}' della sezione '{section.title or section.key}'."
                        )
                    field_keys.add(field.key)
    return errors


