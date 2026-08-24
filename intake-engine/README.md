# PrakritiDesk Intake Engine

The FastAPI backend behind the PrakritiDesk OPD kiosk: conversational clinical intake (SOCRATES + Ayurvedic Dashavidha Pariksha), prescription OCR, FHIR R4 export for ABDM, Bhashini ASR/TTS, and the doctor-kiosk sync layer.

This service is intake-only. It never diagnoses, recommends medication, or suggests a treatment plan — every LLM-facing prompt in this codebase says so explicitly, and every clinical decision stays with the doctor.

## Modules

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI app: route wiring, CORS, structured error handling |
| `app/graph.py` | LangGraph + Groq: the SOCRATES/AYUSH conversational intake state machine |
| `app/red_flags.py` | Deterministic keyword emergency-detector, runs before any LLM call |
| `app/ocr_engine.py` | PaddleOCR/pytesseract + Groq: prescription image/PDF -> structured JSON |
| `app/fhir_engine.py` | Consolidated session data -> FHIR R4 `Bundle` for ABDM |
| `app/audio_engine.py` | Bhashini ASR/TTS for multilingual voice input/output |
| `app/database.py` | Async SQLite (SQLAlchemy) persistence for sessions and the doctor queue |
| `app/schema.py` | Pydantic models for the intake API contract |
| `app/routes/auth.py` | ABHA check-in (OTP-verified) + DPDP consent capture |
| `app/routes/queue.py` | Doctor-kiosk sync: active queue, patient detail, doctor edits |
| `app/routes/vitals.py` | Smartwatch/BLE vitals sync: triage thresholds, Ayurvedic Nadi (pulse) trait estimate |

## How the intake flow works

Each turn of `POST /intake/turn` runs a two-node LangGraph:

```
extract_entities_node ──► generate_prompt_node ──► END
```

1. **`extract_entities_node`** first runs the deterministic keyword scan in `red_flags.py`. If that finds an emergency phrase, the Groq call is skipped entirely. Otherwise it sends the patient's answer to Groq (`llama-3.1-8b-instant`, temperature `0.1`) to extract SOCRATES/AYUSH field values and get a secondary red-flag opinion — falling back to storing the raw text if Groq is unavailable, so the interview always makes forward progress.
2. **`generate_prompt_node`** picks the next *unfilled* slot from a fixed ontology order (chief complaint → 8 SOCRATES fields → all 10 Dashavidha Pariksha parameters) and asks Groq to phrase one short question + 3-4 touch options for that specific field — never to choose the topic itself. A malformed or failed Groq response falls back to a static template question, so the kiosk never gets stuck.

The full Dashavidha Pariksha collected: `dupshya`, `desha`, `bala`, `kala`, `anala_agni`, `prakriti`, `vaya`, `sattva`, `satmya`, `ahara`.

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # fill in GROQ_API_KEY (free at console.groq.com)
uvicorn app.main:app --reload --port 8001
```

```bash
curl http://127.0.0.1:8001/
python test_full_suite.py                     # end-to-end suite across all routes
python test_intake.py                         # focused intake-flow smoke test
python scripts/seed_demo.py                   # seed 3 realistic OPD cases for a demo
python scripts/test_vitals_injection.py       # audits vitals.py -> database.py -> queue.py -> fhir_engine.py
```

## API summary

See the [root README](../README.md#backend-api) for the full endpoint table, or `http://127.0.0.1:8001/docs` once running.

### `POST /intake/turn`

```json
{
  "session_id": "kiosk-session-001",
  "user_input": "मुझे दो दिन से पेट में जलन हो रही है",
  "selected_language": "Hindi"
}
```

```json
{
  "audio_prompt_text": "Where exactly do you feel it?",
  "touch_options": ["Head", "Chest", "Stomach", "Other/Describe"],
  "updated_clinical_state": { "chief_complaint": "...", "socrates": { ... }, "ayush_parameters": { ... } },
  "is_complete": false,
  "trigger_red_flag": false,
  "red_flag_reason": null
}
```

If either the keyword layer or Groq's secondary check detects an emergency (e.g. "chest pain radiating to my arm"), the response short-circuits instead of asking the next question:

```json
{
  "audio_prompt_text": "Please stay seated. A staff member is being called to see you right now.",
  "touch_options": ["Call staff now"],
  "trigger_red_flag": true,
  "red_flag_reason": "Possible acute coronary event (chest pain with radiation/associated symptoms)"
}
```

## Configuration

All settings live in `.env` (see `.env.example`):

| Variable | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Yes | Powers intake extraction, question generation, OCR structuring, and the Groq Vision OCR fallback |
| `GROQ_MODEL` | No | Defaults to `llama-3.1-8b-instant` |
| `GROQ_VISION_MODEL` | No | Defaults to `llama-3.2-11b-vision-instruct`; OCR's tier-2 fallback model |
| `BHASHINI_USER_ID` / `BHASHINI_API_KEY` | No | ASR/TTS; without these, transcription raises a clear error and speech synthesis falls back to a silent audio clip rather than blocking the kiosk |
| `DATABASE_URL` | No | Defaults to a local SQLite file |
| `OCR_LANG` / `TESSERACT_LANG` | No | Language hints for the OCR engines (`TESSERACT_LANG` defaults to `eng+hin`) |
| `TESSERACT_CMD` | No | Path to the Tesseract binary; auto-detected on Windows if left unset |
| `ABDM_CLIENT_ID` / `ABDM_CLIENT_SECRET` | No | Real ABDM Sandbox Gateway credentials for `/auth/abha/init-otp` + `/verify-otp`; a simulated OTP is used if unset |
| `PPG_DEFAULT_SAMPLE_RATE_HZ` | No | Defaults to `25`; assumed sampling rate for HRV estimation in `/vitals/sync` when a client doesn't supply `ppg_sample_rate_hz` |

## Known gaps (see the root README for the full list)

- The real ABDM Sandbox Gateway integration in `/auth/abha/init-otp` / `/auth/abha/verify-otp` is unvalidated (no live sandbox account) and falls back to a simulated OTP on missing credentials or any failure.
- PaddleOCR remains commented out in `requirements.txt` by default (it's heavy); `pytesseract` is a default dependency and works out of the box (see `TESSERACT_CMD` above). Either way, `/prescription/upload` never fails because of this: it always returns 200, cascading from native OCR to a Groq Vision fallback to a structured `"ocr_status": "fallback_mode"` payload (`needs_review: true`) if nothing else works.
- `/vitals/sync`'s Nadi-pulse mapping and BLE ingestion haven't been exercised against a real wearable — `scripts/test_vitals_injection.py` verifies the pipeline with a mocked HTTP payload, not a live sensor.
