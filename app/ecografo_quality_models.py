"""Modelli dati per il Controllo Qualità delle sonde ecografiche.

Rappresenta in modo tipizzato:
- EcografoQualityCheck: la verifica complessiva collegata a un dispositivo
- EcografoQualityProbe: ogni sonda testata (numero illimitato)
- EcografoQualityControl: i singoli controlli previsti dal manuale
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EcografoQualityControl:
    """Singolo controllo qualità su una sonda."""
    control_key: str
    control_label: str = ""
    value: Optional[str] = None
    unit: Optional[str] = None
    passed: Optional[bool] = None
    notes: Optional[str] = None
    uuid: Optional[str] = None
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "uuid": self.uuid,
            "control_key": self.control_key,
            "control_label": self.control_label,
            "value": self.value,
            "unit": self.unit,
            "passed": self.passed,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EcografoQualityControl":
        return cls(
            id=data.get("id"),
            uuid=data.get("uuid"),
            control_key=data.get("control_key", ""),
            control_label=data.get("control_label", ""),
            value=data.get("value"),
            unit=data.get("unit"),
            passed=data.get("passed") if data.get("passed") is not None else None,
            notes=data.get("notes"),
        )


@dataclass
class EcografoQualityProbe:
    """Sonda ecografica sottoposta a controllo qualità."""
    inventory: Optional[str] = None
    manufacturer: Optional[str] = None
    probe_type: Optional[str] = None
    serial_number: Optional[str] = None
    model: Optional[str] = None
    test_model: Optional[str] = None
    preset: Optional[str] = None
    gain: Optional[str] = None
    power: Optional[str] = None
    baseline: Optional[str] = None
    control_stage: str = "Baseline"
    overall_judgment: Optional[str] = None
    creation_year: Optional[str] = None
    notes: Optional[str] = None
    probe_order: int = 0
    controls: List[EcografoQualityControl] = field(default_factory=list)
    uuid: Optional[str] = None
    id: Optional[int] = None
    check_id: Optional[int] = None
    verification_date: Optional[str] = None
    technician_name: Optional[str] = None
    technician_username: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "uuid": self.uuid,
            "check_id": self.check_id,
            "probe_order": self.probe_order,
            "inventory": self.inventory,
            "manufacturer": self.manufacturer,
            "probe_type": self.probe_type,
            "serial_number": self.serial_number,
            "model": self.model,
            "test_model": self.test_model,
            "preset": self.preset,
            "gain": self.gain,
            "power": self.power,
            "baseline": self.baseline,
            "control_stage": self.control_stage,
            "overall_judgment": self.overall_judgment,
            "creation_year": self.creation_year,
            "notes": self.notes,
            "controls": [c.to_dict() for c in self.controls],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EcografoQualityProbe":
        controls = data.get("controls") or []
        return cls(
            id=data.get("id"),
            uuid=data.get("uuid"),
            check_id=data.get("check_id"),
            probe_order=data.get("probe_order", 0),
            inventory=data.get("inventory"),
            manufacturer=data.get("manufacturer"),
            probe_type=data.get("probe_type"),
            serial_number=data.get("serial_number"),
            model=data.get("model"),
            test_model=data.get("test_model"),
            preset=data.get("preset"),
            gain=data.get("gain"),
            power=data.get("power"),
            baseline=data.get("baseline"),
            control_stage=data.get("control_stage", "Baseline"),
            overall_judgment=data.get("overall_judgment"),
            creation_year=data.get("creation_year"),
            notes=data.get("notes"),
            controls=[EcografoQualityControl.from_dict(c) for c in controls],
        )


@dataclass
class EcografoQualityCheck:
    """Verifica complessiva di controllo qualità sonde per un ecografo."""
    device_id: int
    verification_date: str
    technician_name: Optional[str] = None
    technician_username: Optional[str] = None
    verification_code: Optional[str] = None
    overall_status: str = "NON VALUTATO"
    notes: Optional[str] = None
    probes: List[EcografoQualityProbe] = field(default_factory=list)
    uuid: Optional[str] = None
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "uuid": self.uuid,
            "device_id": self.device_id,
            "verification_date": self.verification_date,
            "technician_name": self.technician_name,
            "technician_username": self.technician_username,
            "verification_code": self.verification_code,
            "overall_status": self.overall_status,
            "notes": self.notes,
            "probes": [p.to_dict() for p in self.probes],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EcografoQualityCheck":
        probes = data.get("probes") or []
        return cls(
            id=data.get("id"),
            uuid=data.get("uuid"),
            device_id=data.get("device_id", 0),
            verification_date=data.get("verification_date", ""),
            technician_name=data.get("technician_name"),
            technician_username=data.get("technician_username"),
            verification_code=data.get("verification_code"),
            overall_status=data.get("overall_status", "NON VALUTATO"),
            notes=data.get("notes"),
            probes=[EcografoQualityProbe.from_dict(p) for p in probes],
        )
