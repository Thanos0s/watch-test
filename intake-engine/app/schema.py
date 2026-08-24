"""Pydantic models for the clinical intake API contract."""
from typing import List, Optional
from pydantic import BaseModel, Field


class SocratesSlots(BaseModel):
    site: Optional[str] = None
    onset: Optional[str] = None
    character: Optional[str] = None
    radiation: Optional[str] = None
    associations: Optional[str] = None
    timing: Optional[str] = None
    exacerbating_relieving: Optional[str] = None
    severity: Optional[str] = None


class AyushParameters(BaseModel):
    """The full Dashavidha Pariksha (ten-fold Ayurvedic clinical examination)."""

    dupshya: Optional[str] = None
    desha: Optional[str] = None
    bala: Optional[str] = None
    kala: Optional[str] = None
    anala_agni: Optional[str] = None
    prakriti: Optional[str] = None
    vaya: Optional[str] = None
    sattva: Optional[str] = None
    satmya: Optional[str] = None
    ahara: Optional[str] = None


class ClinicalState(BaseModel):
    chief_complaint: Optional[str] = None
    socrates: SocratesSlots = Field(default_factory=SocratesSlots)
    ayush_parameters: AyushParameters = Field(default_factory=AyushParameters)


class TurnResponse(BaseModel):
    audio_prompt_text: str
    touch_options: List[str]
    updated_clinical_state: ClinicalState
    is_complete: bool = False
    trigger_red_flag: bool = False
    red_flag_reason: Optional[str] = None
