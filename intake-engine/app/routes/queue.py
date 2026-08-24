"""OPD queue & doctor-kiosk sync (Module G) for PrakritiDesk.

    GET /queue/active                -- all active kiosk sessions (queue overview)
    GET /queue/patient/{session_id}  -- full merged clinical state for one patient
    PUT /queue/patient/{session_id}  -- doctor edits/updates clinical fields

--------------------------------------------------------------------------
Router registration instructions for app/main.py:

    from .routes.queue import router as queue_router
    ...
    app.include_router(queue_router)

(This has already been applied in this repo's app/main.py -- included here
per the task spec, and left in place as documentation for anyone wiring
this router into a different FastAPI app.)
--------------------------------------------------------------------------

NOTE ON STATUS NAMING: the task spec for this router names the queue
statuses "in_progress", "ready_for_doctor", "completed". This codebase's
persistence layer (app/database.py) calls the same "ready for a doctor"
state "transferred_to_doctor" -- that name was fixed by an earlier module
and is also what app/routes/auth.py and app/main.py's session store already
write. Rather than introduce a second, inconsistent status string for the
same state, ACTIVE_QUEUE_STATUSES below maps "ready_for_doctor" onto the
existing "transferred_to_doctor" value.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import get_session_by_id, get_sessions_by_status, save_or_update_session

logger = logging.getLogger("prakritidesk.queue")

router = APIRouter(prefix="/queue", tags=["queue"])

# See "NOTE ON STATUS NAMING" above re: ready_for_doctor -> transferred_to_doctor.
ACTIVE_QUEUE_STATUSES = ["in_progress", "transferred_to_doctor", "completed"]


# --------------------------------------------------------------------------
# GET /queue/active
# --------------------------------------------------------------------------

@router.get("/active", response_model=List[Dict[str, Any]])
async def get_active_queue() -> List[Dict[str, Any]]:
    """All kiosk sessions currently in progress, awaiting a doctor, or just
    completed -- oldest first. Each entry is the same merged shape as
    GET /queue/patient/{session_id} below, so a queue list view and a
    detail view can share one response type."""
    try:
        return await get_sessions_by_status(ACTIVE_QUEUE_STATUSES)
    except Exception as exc:
        logger.exception("Failed to load active queue")
        raise HTTPException(
            status_code=500,
            detail={"error": "queue_fetch_failed", "message": str(exc)},
        ) from exc


# --------------------------------------------------------------------------
# GET /queue/patient/{session_id}
# --------------------------------------------------------------------------

@router.get("/patient/{session_id}", response_model=Dict[str, Any])
async def get_patient_detail(session_id: str) -> Dict[str, Any]:
    """Full merged clinical state for one patient: session/consent info,
    chief complaint, SOCRATES, Dashavidha Pariksha (AYUSH), and OCR
    extractions -- everything the doctor's dashboard needs to render one case."""
    try:
        record = await get_session_by_id(session_id)
    except Exception as exc:
        logger.exception("Failed to fetch session_id=%s", session_id)
        raise HTTPException(
            status_code=500,
            detail={"error": "patient_fetch_failed", "message": str(exc)},
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "session_not_found", "message": f"No session found for session_id={session_id!r}"},
        )
    return record


# --------------------------------------------------------------------------
# PUT /queue/patient/{session_id}
# --------------------------------------------------------------------------

class QueuePatientUpdate(BaseModel):
    """All fields optional: only the ones actually sent are updated. For the
    nested `socrates`/`ayush_parameters`/`ocr_data` objects specifically,
    only the keys present in the sent dict are overwritten (a shallow merge
    against what's already stored) -- so a doctor can PUT just
    `{"socrates": {"site": "..."}}` to correct one field without needing to
    resend the whole case, and the other already-recorded SOCRATES fields
    are preserved rather than wiped."""

    chief_complaint: Optional[str] = None
    socrates: Optional[Dict[str, Any]] = None
    ayush_parameters: Optional[Dict[str, Any]] = None
    ocr_data: Optional[Dict[str, Any]] = None
    trigger_red_flag: Optional[bool] = None
    status: Optional[str] = None


@router.put("/patient/{session_id}", response_model=Dict[str, Any])
async def update_patient(session_id: str, payload: QueuePatientUpdate) -> Dict[str, Any]:
    """Apply doctor edits to a patient's clinical fields ahead of final FHIR
    bundle generation (POST /fhir/generate). Returns the merged record after
    the update, in the same shape as GET /queue/patient/{session_id}."""
    existing = await get_session_by_id(session_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "session_not_found", "message": f"No session found for session_id={session_id!r}"},
        )

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return existing

    try:
        return await save_or_update_session({"session_id": session_id, **updates})
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_update_payload", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to update session_id=%s", session_id)
        raise HTTPException(
            status_code=500,
            detail={"error": "patient_update_failed", "message": str(exc)},
        ) from exc
