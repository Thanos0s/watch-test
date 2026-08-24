import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .audio_engine import synthesize_speech, transcribe_audio
from .fhir_engine import generate_fhir_bundle
from .graph import FALLBACK_QUESTIONS, run_turn
from .ocr_engine import process_prescription_image
from .routes.auth import router as auth_router
from .routes.queue import router as queue_router
from .routes.vitals import router as vitals_router
from .schema import ClinicalState, TurnResponse



logger = logging.getLogger("prakritidesk.intake")

API_VERSION = "1.0.0"

app = FastAPI(title="PrakritiDesk Clinical History Intake Engine", version=API_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to the kiosk frontend's origin(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(queue_router)
app.include_router(vitals_router)

# In-memory session store: session_id -> ClinicalState.
# Fine for a single-process dev/demo deployment; swap for Redis/a DB-backed
# store before running multiple workers or across restarts.
_SESSIONS: dict[str, ClinicalState] = {}

ALLOWED_UPLOAD_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_UPLOAD_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


class IntakeTurnRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    user_input: str = Field(..., min_length=1)
    selected_language: str = "Hindi"


class SynthesizeSpeechRequest(BaseModel):
    text: str = Field(..., min_length=1)
    language: str = "Hindi"


@app.get("/")
def root():
    return {
        "api": "PrakritiDesk Clinical History Intake Engine",
        "status": "online",
        "version": API_VERSION,
        "docs": "/docs",
    }


@app.get("/intake/opening-question")
def opening_question():
    """The first question a kiosk session should show, before any patient input exists."""
    q = FALLBACK_QUESTIONS["chief_complaint"]
    return {
        "audio_prompt_text": q["audio_prompt_text"],
        "touch_options": q["touch_options"],
        "updated_clinical_state": ClinicalState().model_dump(),
        "is_complete": False,
        "trigger_red_flag": False,
        "red_flag_reason": None,
    }


@app.post("/intake/turn", response_model=TurnResponse)
async def intake_turn(req: IntakeTurnRequest) -> TurnResponse:
    current_state = _SESSIONS.get(req.session_id) or ClinicalState()

    payload = {
        "session_id": req.session_id,
        "user_input": req.user_input,
        "selected_language": req.selected_language,
        "chief_complaint": current_state.chief_complaint,
        "socrates": current_state.socrates.model_dump(),
        "ayush_parameters": current_state.ayush_parameters.model_dump(),
    }

    try:
        result = await run_turn(payload)
    except Exception as exc:
        logger.exception("intake_turn failed for session_id=%s", req.session_id)
        raise HTTPException(
            status_code=500,
            detail={"error": "intake_turn_failed", "message": str(exc)},
        ) from exc

    updated_state = ClinicalState(**result["updated_clinical_state"])
    _SESSIONS[req.session_id] = updated_state

    return TurnResponse(
        audio_prompt_text=result["audio_prompt_text"],
        touch_options=result["touch_options"],
        updated_clinical_state=updated_state,
        is_complete=result["is_complete"],
        trigger_red_flag=result["trigger_red_flag"],
        red_flag_reason=result["red_flag_reason"],
    )


@app.post("/prescription/upload")
async def upload_prescription(file: UploadFile = File(...)) -> dict:
    if file.content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_file_type",
                "message": f"Unsupported content type '{file.content_type}'. "
                f"Allowed types: {sorted(ALLOWED_UPLOAD_CONTENT_TYPES)}.",
            },
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail={"error": "empty_file", "message": "Uploaded file is empty."},
        )

    if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "file_too_large",
                "message": f"File exceeds the {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB upload limit.",
            },
        )

    try:
        structured_result = await process_prescription_image(file_bytes)
    except Exception as exc:
        logger.exception("prescription OCR/structuring failed for filename=%s", file.filename)
        raise HTTPException(
            status_code=500,
            detail={"error": "prescription_processing_failed", "message": str(exc)},
        ) from exc

    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "file_size_bytes": len(file_bytes),
        **structured_result,
    }


@app.post("/audio/transcribe")
async def audio_transcribe(
    file: UploadFile = File(...),
    language: str = Form(default="Hindi"),
) -> dict:
    """Speech-to-text via Bhashini (app/audio_engine.py). Unlike OCR, this
    deliberately does NOT have a fallback: a transcript stands in for the
    patient's literal spoken words, so transcribe_audio() raises rather
    than fabricating one if Bhashini isn't configured/reachable -- mapped
    to 503 here (a configuration/availability problem, not a bad request)."""
    audio_bytes = await file.read()

    try:
        transcript = await transcribe_audio(audio_bytes, language)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_audio_payload", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Speech-to-text failed for filename=%s", file.filename)
        raise HTTPException(
            status_code=503,
            detail={"error": "speech_to_text_unavailable", "message": str(exc)},
        ) from exc

    return {"transcript": transcript, "language": language}


@app.post("/audio/synthesize")
async def audio_synthesize(payload: SynthesizeSpeechRequest) -> Response:
    """Text-to-speech via Bhashini (app/audio_engine.py). synthesize_speech()
    never raises -- it falls back to a short silent WAV clip on any
    failure, so the kiosk can always show the prompt as text/buttons even
    when TTS itself is unavailable. This route is therefore always 200."""
    audio_bytes = await synthesize_speech(payload.text, payload.language)
    return Response(content=audio_bytes, media_type="audio/wav")


@app.post("/fhir/generate")
async def fhir_generate(payload: dict) -> dict:
    try:
        bundle = await generate_fhir_bundle(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_fhir_payload", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("FHIR bundle generation failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "fhir_generation_failed", "message": str(exc)},
        ) from exc

    return bundle


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if not isinstance(detail, dict):
        detail = {"error": "http_error", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "message": "An unexpected error occurred."},
    )
