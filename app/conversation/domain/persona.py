"""Enterprise Persona Models."""

from enum import Enum
from pydantic import BaseModel, Field


class PersonaType(str, Enum):
    CEO = "CEO"
    CTO = "CTO"
    ENGINEER = "ENGINEER"
    LEGAL_COUNSEL = "LEGAL_COUNSEL"
    SUPPORT = "SUPPORT"
    HR = "HR"
    FINANCE = "FINANCE"
    SECURITY = "SECURITY"
    AUDITOR = "AUDITOR"
    PRODUCT_MANAGER = "PRODUCT_MANAGER"


class PersonaConfig(BaseModel):
    persona_type: PersonaType
    title: str
    tone: str
    verbosity: str
    system_instruction: str
