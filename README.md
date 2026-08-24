# PrakritiDesk

An intelligent OPD kiosk platform that takes a patient's clinical history — SOCRATES history-of-present-illness *and* Ayurvedic Dashavidha Pariksha — before they ever step into the consultation room, so the doctor starts each visit with a structured summary instead of a blank slate.

```
Kiosk check-in (ABHA ID/mobile)
        │
        ▼
ABHA OTP verification
        │
        ▼
DPDP consent
        │
        ▼
Vitals & pulse check  (BLE pairing, optional -- manual entry / skip always available)
        │
        ▼
Conversational intake  ──────────────►  Emergency red-flag detection
 (SOCRATES + AYUSH)                      (short-circuits to a triage alert)
        │
        ▼
Prescription / lab OCR  (optional)
        │
        ▼
Doctor review & correction
        │
        ▼
FHIR R4 bundle  ──────────────►  ABDM
```

## Repository layout

```
PrakritiDesk/
├── intake-engine/          FastAPI backend
│   ├── app/
│   │   ├── main.py         API entrypoint, route wiring, CORS, error handling
│   │   ├── graph.py        LangGraph + Groq: SOCRATES/AYUSH intake, red-flag detection
│   │   ├── red_flags.py    Deterministic emergency-keyword safety net
│   │   ├── ocr_engine.py   PaddleOCR/pytesseract + Groq: prescription -> structured JSON
│   │   ├── fhir_engine.py  Consolidated session state -> FHIR R4 Bundle
│   │   ├── audio_engine.py Bhashini ASR/TTS for voice input/output
│   │   ├── database.py     SQLite (async SQLAlchemy) session & doctor-queue persistence
│   │   ├── schema.py       Pydantic API contract models
│   │   └── routes/
│   │       ├── auth.py     ABHA check-in + DPDP consent capture
│   │       ├── queue.py    Doctor-kiosk sync: active queue, patient detail, edits
│   │       └── vitals.py   Smartwatch/BLE vitals sync, triage thresholds, Nadi mapping
│   ├── scripts/
│   │   ├── seed_demo.py               3 realistic OPD cases for demos/judging
│   │   └── test_vitals_injection.py   Audits vitals.py -> database.py -> queue.py -> fhir_engine.py end-to-end
│   ├── test_full_suite.py  End-to-end API test suite
│   ├── test_intake.py      Focused intake-flow smoke test
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                Next.js 14 (App Router) + Tailwind + TypeScript
│   ├── app/
│   │   ├── layout.tsx       Root layout: fonts, kiosk touch-screen base styles
│   │   ├── page.tsx         "/" -- renders KioskUI
│   │   └── doctor/page.tsx  "/doctor" -- full doctor OPD dashboard (queue + case review)
│   ├── components/
│   │   ├── KioskUI.tsx           Patient-facing touch + voice kiosk screen (embeds SmartwatchBridge)
│   │   ├── DoctorDesk.tsx        Editable FHIR-summary review widget (used by app/doctor/page.tsx)
│   │   └── SmartwatchBridge.tsx  Web Bluetooth pulse sensor pairing + auto-sync
│   └── package.json / tailwind.config.js / tsconfig.json / next.config.mjs
└── docker-compose.yml       Edge deployment: backend + SQLite volume
```

## Backend API

| Method | Path                          | Purpose                                                       |
|--------|-------------------------------|----------------------------------------------------------------|
| GET    | `/`                            | Health check                                                   |
| GET    | `/intake/opening-question`     | First kiosk question, before any patient input                 |
| POST   | `/intake/turn`                 | One turn of the SOCRATES/AYUSH conversational intake            |
| POST   | `/prescription/upload`         | Upload a prescription/lab image or PDF for OCR + structuring   |
| POST   | `/audio/transcribe`             | Speech-to-text via Bhashini (never fabricates a transcript — 503 if unavailable) |
| POST   | `/audio/synthesize`              | Text-to-speech via Bhashini (always 200 — silent-clip fallback if unavailable) |
| POST   | `/fhir/generate`                | Build the final FHIR R4 bundle for ABDM                        |
| POST   | `/auth/consent`                | Record DPDP consent (agree or decline) for a session           |
| POST   | `/auth/abha/init-otp`           | Step 1: request an OTP for an ABHA ID / mobile (real ABDM Sandbox Gateway if configured, simulated otherwise) |
| POST   | `/auth/abha/verify-otp`        | Step 2: verify the OTP — persists demographics + a consent-audit record |
| GET    | `/queue/active`                 | All in-progress / awaiting-doctor / completed sessions          |
| GET    | `/queue/patient/{session_id}`  | Full merged clinical state for one patient                     |
| PUT    | `/queue/patient/{session_id}`  | Doctor edits to clinical fields (partial updates merge safely) |
| POST   | `/vitals/sync`                  | Smartwatch/BLE vitals sync: triage thresholds + Nadi (pulse) trait estimate |

Interactive docs are served at `/docs` once the API is running.

## Quick start

```bash
cd intake-engine
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # fill in GROQ_API_KEY (free at console.groq.com)
uvicorn app.main:app --reload --port 8001
```

Verify it's up:

```bash
curl http://127.0.0.1:8001/
python test_full_suite.py
```

## Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000 (kiosk) and /doctor (dashboard)
```

Pinned to Next.js 14.2.x (the newest available 14.x patch) rather than the `latest`/`15`+ tag, since this is explicitly a Next.js 14 App Router project — bumping the major version would need re-verifying every component against Next 15's changes first. Tailwind is likewise pinned to 3.x, matching the classic `content`-array config style used in `tailwind.config.js`; Tailwind 4 uses a different, CSS-first config model.

## Testing

Backend (Pytest, in-process against the real app — no server or live LLM needed) and frontend E2E (Playwright, POM-based, backend fully mocked) suites, plus a GitHub Actions pipeline running both on every push/PR. See **[TESTING.md](TESTING.md)** for the full strategy, directory layout, and commands.

```bash
cd intake-engine && pytest -v                 # backend: 51 tests
cd frontend && npm run test:e2e               # frontend E2E: 14 tests
```

## Docker

```bash
# from the repo root, with a .env containing GROQ_API_KEY
docker compose up --build -d
```

This builds `intake-engine/Dockerfile` and mounts `./data` for the SQLite database, so patient sessions and the doctor queue survive container restarts.

## Safety & compliance

- **Intake-only, always.** The system never diagnoses, recommends medication, or suggests a treatment plan — every LLM-facing prompt in the codebase says so explicitly.
- **Red-flag detection is layered.** A deterministic keyword scan runs before any LLM call and cannot be disabled by an LLM outage; the LLM extraction step adds a secondary opinion on top of it.
- **DPDP consent is explicit and audited.** Both agreement and decline are recorded, not just success.
- **The ABDM lookup is honest about its confidence level, and mirrors the real OTP lifecycle.** `/auth/abha/init-otp` + `/auth/abha/verify-otp` try the real ABDM Sandbox Gateway if `ABDM_CLIENT_ID`/`ABDM_CLIENT_SECRET` are configured. A failed *init* call downgrades gracefully to a simulated OTP; a failed *verify* call on an already-real-gateway transaction is rejected outright rather than silently falling back to local mock verification (there's no local OTP to check for a real-gateway transaction in the first place — none was ever generated). Every response says exactly which path was used (`is_mock`, `gateway_mode`, `verification_status`) so a live vs. simulated result is never ambiguous. Every log line and response also carries the explicit disclaimer: *"Simulated ABDM Gateway - Production requires certified M1/M2 CM-ID credentials."*

## Known gaps

- The real ABDM Sandbox Gateway integration in `/auth/abha/init-otp` / `/auth/abha/verify-otp` has not been validated against a live sandbox account (this project has none) — treat those real-gateway code paths as a starting point rather than a certified integration.
- `pytesseract` (native OCR, tier 1) is a default dependency and works out of the box on both Docker (`tesseract-ocr`/`tesseract-ocr-hin` installed via apt in `Dockerfile`) and local dev (auto-detects the Windows installer's default path, or set `TESSERACT_CMD` in `.env`). PaddleOCR is a separate, still-optional/commented-out dependency (heavier, no auto-setup) that's tried first when installed. Regardless of what's available, `/prescription/upload` never fails because of this — it cascades to a Groq Vision fallback and then a structured `fallback_mode` payload.
- The vitals/Nadi-pulse mapping and the Web Bluetooth pairing in `SmartwatchBridge.tsx` are both real, working code paths, but neither has been exercised against an actual BLE heart-rate device — verification so far is via `scripts/test_vitals_injection.py` (a mocked HTTP payload) and the component's GATT byte-parsing unit tests, not a live sensor.
- The doctor dashboard (`/doctor`) currently only surfaces the vitals `SmartwatchBridge` captured during kiosk intake for FHIR export (via `device_vitals`); there's no UI yet for a doctor to re-pair a device or re-sync vitals mid-consultation.
