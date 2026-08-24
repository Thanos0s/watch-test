"""Smartwatch/wearable BLE vitals ingestion (Module H) for PrakritiDesk.

    POST /vitals/sync -- ingest a BLE-synced vitals reading for an active
    kiosk session, evaluate emergency triage thresholds, derive a coarse
    Ayurvedic Nadi (pulse) trait estimate, and persist all of it via
    app.database so it shows up on the doctor's queue and feeds into the
    LOINC-coded FHIR Observations in app/fhir_engine.py.

--------------------------------------------------------------------------
Router registration instructions for app/main.py:

    from .routes.vitals import router as vitals_router
    ...
    app.include_router(vitals_router)

(This has already been applied in this repo's app/main.py -- included here
per the task spec, and left in place as documentation for anyone wiring
this router into a different FastAPI app.)
--------------------------------------------------------------------------

SAFETY NOTES:
  - Triage thresholds here (tachycardia, hypoxia, hypertensive crisis) are
    a coarse, deterministic safety net layered ON TOP OF -- not a
    replacement for -- app/red_flags.py's keyword scan and the LLM's
    secondary opinion during conversational intake (app/graph.py). A
    vitals sync can only ever set trigger_red_flag to True; it never
    clears an existing True back to False (in-range vitals don't mean an
    earlier-reported emergency stopped mattering). Only a doctor clearing
    it explicitly via PUT /queue/patient/{id} should do that.
  - The Nadi (pulse) trait mapping is a coarse, educational heuristic
    derived only from heart rate and a rough PPG-based HRV approximation.
    It is NOT a substitute for a vaidya's actual tactile Nadi Pariksha, and
    every value it writes is explicitly suffixed "(pulse-derived estimate,
    unverified)" so it can never be mistaken for a clinician-confirmed
    Prakriti/Dushya assessment. It also only fills the ayush_parameters
    `dupshya` field if the patient's conversational intake hasn't already
    recorded one -- it never overwrites a value the patient/doctor already
    established.
  - The HRV estimate itself is a simple local-maxima peak detector over
    the raw PPG sample, not clinical-grade HRV analysis (which needs
    proper bandpass filtering, motion-artifact rejection, and much longer
    recordings). Treat `hrv_sdnn_ms` as a rough irregularity signal only.
"""
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..database import get_session_by_id, save_or_update_session

logger = logging.getLogger("prakritidesk.vitals")

router = APIRouter(prefix="/vitals", tags=["vitals"])

# --------------------------------------------------------------------------
# Triage thresholds -- deterministic, not LLM-based, so they never depend
# on an external API being up. The spec's examples (HR > 120, SpO2 < 90%)
# plus a standard hypertensive-crisis BP threshold, since blood pressure is
# already part of every sync payload and it's a well-established emergency
# criterion.
# --------------------------------------------------------------------------
RED_FLAG_HR_HIGH_BPM = 120
RED_FLAG_SPO2_LOW_PERCENT = 90
RED_FLAG_SYSTOLIC_BP_HIGH = 180
RED_FLAG_DIASTOLIC_BP_HIGH = 120

# --------------------------------------------------------------------------
# Nadi (pulse) trait heuristic thresholds -- see the SAFETY NOTES above.
# --------------------------------------------------------------------------
VATA_PITTA_HR_THRESHOLD_BPM = 90
KAPHA_HR_THRESHOLD_BPM = 60
VATA_HRV_SDNN_THRESHOLD_MS = 100.0

NADI_VATA_PITTA_LABEL = "Vata/Pitta Spikes (Irregular/Bounding Pulse)"
NADI_KAPHA_LABEL = "Kapha Dominance (Slow Steady Pulse)"
NADI_BALANCED_LABEL = "Sama Agni / Balanced Pulse"

# Real HRV needs a sampling rate to convert peak spacing into milliseconds,
# which the wearable payload doesn't include -- default to a rate typical
# of cheap consumer PPG sensors, overridable per-request or via env.
DEFAULT_PPG_SAMPLE_RATE_HZ = float(os.getenv("PPG_DEFAULT_SAMPLE_RATE_HZ", "25"))


# --------------------------------------------------------------------------
# Request/response models
# --------------------------------------------------------------------------

class VitalsSyncRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    # All four vitals are individually optional: a real BLE client only
    # ever has what its paired device(s) actually expose -- a plain heart-
    # rate strap has no SpO2 or blood pressure at all (those need separate
    # GATT services, e.g. Pulse Oximeter 0x1822, that most simple wearables
    # don't implement), and a dedicated BP cuff has no heart-rate-service
    # PPG waveform. Forcing all four would push a client to fabricate
    # values it doesn't have, which this API refuses to accept implicitly
    # -- at least one vital must be present (enforced below), but never all four.
    heart_rate_bpm: Optional[int] = Field(default=None, ge=20, le=300)
    spo2_percent: Optional[int] = Field(default=None, ge=0, le=100)
    systolic_bp: Optional[int] = Field(default=None, ge=40, le=300)
    diastolic_bp: Optional[int] = Field(default=None, ge=20, le=200)
    ppg_waveform_sample: Optional[List[float]] = None
    # Not in the original wearable payload spec -- optional so existing
    # callers that omit it still work, defaulting to
    # DEFAULT_PPG_SAMPLE_RATE_HZ. See the HRV note above for why this is
    # needed at all.
    ppg_sample_rate_hz: Optional[float] = Field(default=None, gt=0)


class VitalsSyncResponse(BaseModel):
    session_id: str
    trigger_red_flag: bool
    red_flag_reason: Optional[str]
    nadi_trait_estimate: Optional[str]
    hrv_sdnn_ms: Optional[float]
    patient_record: Dict[str, Any]


# --------------------------------------------------------------------------
# HRV estimation + Nadi (pulse) trait mapping
# --------------------------------------------------------------------------

def _estimate_hrv_sdnn_ms(ppg_waveform: Optional[List[float]], sample_rate_hz: float) -> Optional[float]:
    """A simple SDNN-style HRV estimate from a raw PPG waveform via basic
    local-maxima peak detection. Returns None if the sample is too short
    or too few peaks are found to say anything meaningful -- this quietly
    degrades to "no HRV signal" rather than fabricating a number."""
    if not ppg_waveform or len(ppg_waveform) < 10 or sample_rate_hz <= 0:
        return None

    values = np.asarray(ppg_waveform, dtype=float)
    # A minimum peak spacing guard (>=200bpm cap) so small noisy wiggles
    # right next to a real peak aren't double-counted as separate beats.
    min_spacing_samples = max(1, int(sample_rate_hz * 0.3))

    peaks: List[int] = []
    for i in range(1, len(values) - 1):
        if values[i] > values[i - 1] and values[i] >= values[i + 1]:
            if not peaks or (i - peaks[-1]) >= min_spacing_samples:
                peaks.append(i)

    if len(peaks) < 3:
        return None

    rr_intervals_ms = np.diff(peaks) / sample_rate_hz * 1000.0
    return round(float(np.std(rr_intervals_ms)), 1)


def _map_pulse_to_nadi_trait(heart_rate_bpm: Optional[int], hrv_sdnn_ms: Optional[float]) -> Optional[str]:
    """Heuristic, non-diagnostic mapping from pulse characteristics to a
    baseline Ayurvedic Nadi (pulse) trait -- see the SAFETY NOTES above.
    Returns None (not a guess) if no heart rate was even provided, e.g. a
    sync from a BP-cuff-only device.

    Three bands, per spec:
      HR > 90 bpm            -> Vata/Pitta Spikes (Irregular/Bounding Pulse)
      HR < 60 bpm             -> Kapha Dominance (Slow Steady Pulse)
      60 <= HR <= 90 bpm      -> Sama Agni / Balanced Pulse
    An irregular HRV reading (see SAFETY NOTES) also counts as a Vata/Pitta
    spike even if HR itself is in the balanced band, since pulse
    irregularity is itself a classic Vata sign -- this is an addition on
    top of the pure HR thresholds above, not a contradiction of them.
    """
    if heart_rate_bpm is None:
        return None

    irregular = hrv_sdnn_ms is not None and hrv_sdnn_ms > VATA_HRV_SDNN_THRESHOLD_MS

    if heart_rate_bpm > VATA_PITTA_HR_THRESHOLD_BPM or irregular:
        return NADI_VATA_PITTA_LABEL
    if heart_rate_bpm < KAPHA_HR_THRESHOLD_BPM:
        return NADI_KAPHA_LABEL
    return NADI_BALANCED_LABEL


# --------------------------------------------------------------------------
# Triage evaluation
# --------------------------------------------------------------------------

def _evaluate_triage(
    heart_rate_bpm: Optional[int],
    spo2_percent: Optional[int],
    systolic_bp: Optional[int],
    diastolic_bp: Optional[int],
) -> Optional[str]:
    """Returns a human-readable reason string if any threshold is breached
    by whichever vitals were actually provided, else None."""
    reasons: List[str] = []
    if heart_rate_bpm is not None and heart_rate_bpm > RED_FLAG_HR_HIGH_BPM:
        reasons.append(f"Tachycardia (HR {heart_rate_bpm} bpm > {RED_FLAG_HR_HIGH_BPM})")
    if spo2_percent is not None and spo2_percent < RED_FLAG_SPO2_LOW_PERCENT:
        reasons.append(f"Hypoxia (SpO2 {spo2_percent}% < {RED_FLAG_SPO2_LOW_PERCENT}%)")
    if systolic_bp is not None and diastolic_bp is not None and (
        systolic_bp >= RED_FLAG_SYSTOLIC_BP_HIGH or diastolic_bp >= RED_FLAG_DIASTOLIC_BP_HIGH
    ):
        reasons.append(f"Hypertensive crisis (BP {systolic_bp}/{diastolic_bp} mmHg)")
    return "; ".join(reasons) if reasons else None


# --------------------------------------------------------------------------
# Route
# --------------------------------------------------------------------------

@router.post("/sync", response_model=VitalsSyncResponse)
async def sync_vitals(payload: VitalsSyncRequest) -> VitalsSyncResponse:
    if all(
        v is None
        for v in (payload.heart_rate_bpm, payload.spo2_percent, payload.systolic_bp, payload.diastolic_bp)
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "no_vitals_provided",
                "message": "At least one of heart_rate_bpm, spo2_percent, or systolic_bp+diastolic_bp is required.",
            },
        )

    existing = await get_session_by_id(payload.session_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "session_not_found", "message": f"No session found for session_id={payload.session_id!r}"},
        )

    sample_rate_hz = payload.ppg_sample_rate_hz or DEFAULT_PPG_SAMPLE_RATE_HZ
    hrv_sdnn_ms = _estimate_hrv_sdnn_ms(payload.ppg_waveform_sample, sample_rate_hz)
    nadi_trait = _map_pulse_to_nadi_trait(payload.heart_rate_bpm, hrv_sdnn_ms)

    vitals_triage_reason = _evaluate_triage(
        payload.heart_rate_bpm, payload.spo2_percent, payload.systolic_bp, payload.diastolic_bp
    )

    # Never downgrade an existing red flag; combine reasons if both fired
    # for different causes.
    existing_red_flag = bool(existing.get("trigger_red_flag"))
    existing_reason = existing.get("red_flag_reason")
    new_trigger = existing_red_flag or bool(vitals_triage_reason)

    if vitals_triage_reason and existing_reason and existing_reason != vitals_triage_reason:
        combined_reason: Optional[str] = f"{existing_reason}; {vitals_triage_reason}"
    else:
        combined_reason = vitals_triage_reason or existing_reason

    # Sparse on purpose: device_vitals is shallow-merged onto whatever was
    # already stored (see database.py), so including a None here for a
    # vital this sync didn't provide would silently overwrite a real
    # reading from an earlier sync (e.g. a BP cuff's numbers getting wiped
    # out by a later heart-rate-strap-only sync).
    device_vitals: Dict[str, Any] = {
        key: value
        for key, value in {
            "heart_rate_bpm": payload.heart_rate_bpm,
            "spo2_percent": payload.spo2_percent,
            "systolic_bp": payload.systolic_bp,
            "diastolic_bp": payload.diastolic_bp,
            "hrv_sdnn_ms": hrv_sdnn_ms,
            "nadi_trait_estimate": nadi_trait,
        }.items()
        if value is not None
    }

    update: Dict[str, Any] = {
        "session_id": payload.session_id,
        "device_vitals": device_vitals,
        "trigger_red_flag": new_trigger,
    }
    if combined_reason:
        update["red_flag_reason"] = combined_reason

    # Only fill dupshya (dosha/dhatu imbalance) from the pulse estimate if
    # one was actually computed (requires a heart rate) AND the patient's
    # conversational intake hasn't already recorded one -- see the SAFETY
    # NOTES above for why this never overwrites.
    existing_ayush = existing.get("ayush_parameters") or {}
    if nadi_trait and not existing_ayush.get("dupshya"):
        update["ayush_parameters"] = {"dupshya": f"{nadi_trait} (pulse-derived estimate, unverified)"}

    try:
        record = await save_or_update_session(update)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_vitals_payload", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to persist vitals for session_id=%s", payload.session_id)
        raise HTTPException(
            status_code=500,
            detail={"error": "vitals_storage_failed", "message": str(exc)},
        ) from exc

    if new_trigger and not existing_red_flag:
        logger.warning(
            "Vitals-triggered red flag for session_id=%s: %s", payload.session_id, vitals_triage_reason
        )

    return VitalsSyncResponse(
        session_id=payload.session_id,
        trigger_red_flag=new_trigger,
        red_flag_reason=combined_reason,
        nadi_trait_estimate=nadi_trait,
        hrv_sdnn_ms=hrv_sdnn_ms,
        patient_record=record,
    )
