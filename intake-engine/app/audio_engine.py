"""Bhashini multilingual ASR/TTS engine (Module D) for PrakritiDesk.

Wraps the Bhashini/ULCA pipeline APIs (free, Government of India) so kiosk
patients can speak and be spoken to in their own language:

    kiosk mic (WAV/WEBM bytes) -> transcribe_audio() -> text
                                                          |
                                                          v
                                       ... rest of the intake pipeline ...
                                                          |
                                                          v
    audio_prompt_text -> synthesize_speech() -> kiosk speaker (WAV bytes)

Bhashini access is a two-step call:
  1. `getModelsPipeline` -- given a task type (asr/tts) and language, returns
     a per-request inference endpoint URL, an API key to use with it, and
     the serviceId to request.
  2. The returned inference endpoint -- given the actual audio/text payload,
     returns the transcript (ASR) or a base64-encoded audio clip (TTS).

Step 1's result is cached per (task, language) pair since it rarely changes.

Safety note on fallback behavior:
  - STT has NO safe fallback: a transcript is the patient's literal words,
    and clinical accuracy depends on it. If Bhashini credentials are
    missing or the call fails, `transcribe_audio` raises a clear error
    rather than fabricating or guessing what the patient said.
  - TTS DOES have a safe fallback: if speech synthesis is unavailable, the
    kiosk can still show `audio_prompt_text` as on-screen text and touch
    buttons, so `synthesize_speech` degrades to a short mock silent WAV
    clip instead of raising, so it never blocks the rest of the interview.
"""
import base64
import logging
import os
import struct
import wave
from io import BytesIO
from typing import Any, Dict, Optional, Tuple

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("prakritidesk.audio_engine")

BHASHINI_USER_ID = os.getenv("BHASHINI_USER_ID")
BHASHINI_API_KEY = os.getenv("BHASHINI_API_KEY")
BHASHINI_PIPELINE_ID = os.getenv("BHASHINI_PIPELINE_ID", "64392f96daac500b55c543cd")
BHASHINI_CONFIG_ENDPOINT = os.getenv(
    "BHASHINI_CONFIG_ENDPOINT",
    "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline",
)
REQUEST_TIMEOUT = 30

# Maps the human-readable language names used elsewhere in this app (e.g.
# IntakeTurnRequest.selected_language) to Bhashini/ULCA ISO language codes.
LANGUAGE_CODE_MAP = {
    "hindi": "hi",
    "english": "en",
    "bengali": "bn",
    "tamil": "ta",
    "telugu": "te",
    "marathi": "mr",
    "gujarati": "gu",
    "kannada": "kn",
    "malayalam": "ml",
    "punjabi": "pa",
    "odia": "or",
    "urdu": "ur",
    "assamese": "as",
}


def _to_bhashini_lang_code(language: str) -> str:
    normalized = (language or "").strip().lower()
    if normalized in LANGUAGE_CODE_MAP.values():
        return normalized  # already a code, e.g. "hi"
    return LANGUAGE_CODE_MAP.get(normalized, "en")


def _credentials_available() -> bool:
    return bool(BHASHINI_USER_ID and BHASHINI_API_KEY)


# --------------------------------------------------------------------------
# Step 1: resolve the per-task/language inference endpoint (cached)
# --------------------------------------------------------------------------

_pipeline_config_cache: Dict[Tuple[str, str], dict] = {}


async def _get_pipeline_config(task_type: str, language_code: str) -> dict:
    """Return {"callback_url", "auth_header_name", "auth_header_value", "service_id"}."""
    cache_key = (task_type, language_code)
    if cache_key in _pipeline_config_cache:
        return _pipeline_config_cache[cache_key]

    if not _credentials_available():
        raise RuntimeError("BHASHINI_USER_ID / BHASHINI_API_KEY are not set")

    body = {
        "pipelineTasks": [
            {"taskType": task_type, "config": {"language": {"sourceLanguage": language_code}}}
        ],
        "pipelineRequestConfig": {"pipelineId": BHASHINI_PIPELINE_ID},
    }
    headers = {
        "Content-Type": "application/json",
        "userID": BHASHINI_USER_ID,
        "ulcaApiKey": BHASHINI_API_KEY,
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.post(BHASHINI_CONFIG_ENDPOINT, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    inference_endpoint = data["pipelineInferenceAPIEndPoint"]
    api_key = inference_endpoint["inferenceApiKey"]
    service_id = data["pipelineResponseConfig"][0]["config"][0]["serviceId"]

    config = {
        "callback_url": inference_endpoint["callbackUrl"],
        "auth_header_name": api_key["name"],
        "auth_header_value": api_key["value"],
        "service_id": service_id,
    }
    _pipeline_config_cache[cache_key] = config
    return config


# --------------------------------------------------------------------------
# Fallback audio (used only by TTS -- see module docstring for why STT has
# no equivalent fallback)
# --------------------------------------------------------------------------

def _generate_silent_wav_bytes(duration_seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    """A short, valid, silent mono 16-bit PCM WAV clip."""
    num_samples = int(duration_seconds * sample_rate)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(struct.pack("<%dh" % num_samples, *([0] * num_samples)))
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Public: Speech-to-Text
# --------------------------------------------------------------------------

async def transcribe_audio(audio_bytes: bytes, source_language: str) -> str:
    """Transcribe recorded kiosk audio (WAV/WEBM) to text via Bhashini ASR.

    Raises RuntimeError if Bhashini credentials are missing or the API call
    fails -- a transcript is never fabricated, since it stands in for the
    patient's literal spoken words.
    """
    if not audio_bytes:
        raise ValueError("audio_bytes is empty")

    language_code = _to_bhashini_lang_code(source_language)
    config = await _get_pipeline_config("asr", language_code)

    body = {
        "pipelineTasks": [
            {
                "taskType": "asr",
                "config": {
                    "language": {"sourceLanguage": language_code},
                    "serviceId": config["service_id"],
                    "audioFormat": "wav",
                    "samplingRate": 16000,
                },
            }
        ],
        "inputData": {"audio": [{"audioContent": base64.b64encode(audio_bytes).decode("ascii")}]},
    }
    headers = {
        "Content-Type": "application/json",
        config["auth_header_name"]: config["auth_header_value"],
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.post(config["callback_url"], json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    try:
        return data["pipelineResponse"][0]["output"][0]["source"].strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise RuntimeError(f"Unexpected Bhashini ASR response shape: {data}") from exc


# --------------------------------------------------------------------------
# Public: Text-to-Speech
# --------------------------------------------------------------------------

async def synthesize_speech(text: str, target_language: str) -> bytes:
    """Convert `audio_prompt_text` into spoken audio bytes (WAV) via Bhashini TTS.

    Degrades to a short mock silent WAV clip if Bhashini credentials are
    missing or the API call fails, so a TTS outage never blocks the kiosk
    interview (the text is still shown on-screen either way).
    """
    if not text or not text.strip():
        return _generate_silent_wav_bytes(duration_seconds=0.2)

    language_code = _to_bhashini_lang_code(target_language)

    try:
        config = await _get_pipeline_config("tts", language_code)

        body = {
            "pipelineTasks": [
                {
                    "taskType": "tts",
                    "config": {
                        "language": {"sourceLanguage": language_code},
                        "serviceId": config["service_id"],
                        "gender": "female",
                        "samplingRate": 16000,
                    },
                }
            ],
            "inputData": {"input": [{"source": text}]},
        }
        headers = {
            "Content-Type": "application/json",
            config["auth_header_name"]: config["auth_header_value"],
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(config["callback_url"], json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        audio_content_b64 = data["pipelineResponse"][0]["audio"][0]["audioContent"]
        return base64.b64decode(audio_content_b64)
    except Exception:
        logger.exception("Bhashini TTS unavailable, falling back to mock silent audio")
        return _generate_silent_wav_bytes(duration_seconds=1.0)


# --------------------------------------------------------------------------
# FastAPI endpoint helpers
#
# Kept separate from the two functions above so this module's core logic
# stays framework-agnostic and independently testable; these are thin
# adapters meant to be called directly from an `app/main.py` route.
# --------------------------------------------------------------------------

async def handle_transcription_request(audio_bytes: bytes, source_language: str) -> Dict[str, Any]:
    """Adapter for a `POST /audio/transcribe` route: returns a JSON-ready dict."""
    transcript = await transcribe_audio(audio_bytes, source_language)
    return {"transcript": transcript, "source_language": source_language}


async def handle_synthesis_request(text: str, target_language: str):
    """Adapter for a `POST /audio/synthesize` route: returns a ready-to-send
    FastAPI `Response` with the WAV bytes and correct media type."""
    from fastapi import Response  # imported lazily so importing this module never requires FastAPI

    audio_bytes = await synthesize_speech(text, target_language)
    return Response(content=audio_bytes, media_type="audio/wav")
