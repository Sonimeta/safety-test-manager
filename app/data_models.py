# app/data_models.py
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class Limit:
    unit: str
    high_value: Optional[float] = None

@dataclass
class AppliedPart:
    name: str      # Nome descrittivo per l'utente (es. "Elettrodo Torace 1")
    part_type: str # Tipo di parte applicata (B, BF, CF)
    code: str      # Codice specifico per lo strumento (es. "V1") <-- NUOVO CAMPO

@dataclass
class Test:
    name: str
    parameter: Optional[str] = ""
    limits: Dict[str, Limit] = field(default_factory=dict)
    is_applied_part_test: bool = False

@dataclass
class VerificationProfile:
    name: str
    tests: List[Test]
