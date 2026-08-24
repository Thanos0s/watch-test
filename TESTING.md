# PrakritiDesk Automation Testing Strategy

Two independent, complementary suites:

- **`intake-engine/tests/`** (Pytest + `httpx.AsyncClient`) — unit tests for pure logic (`red_flags.py`, `fhir_engine.py`) and integration tests for the FastAPI routes (`routes/auth.py`, `routes/queue.py`), running in-process against the real app with no live server or external API calls required.
- **`frontend/e2e/`** (Playwright + TypeScript, Page Object Model) — browser-driven tests of the patient kiosk flow (`KioskUI.tsx`) and the doctor dashboard (`app/doctor/page.tsx` + `DoctorDesk.tsx`), with every backend call mocked via `page.route()`.

> **Scope correction from the original brief:** this codebase's `auth.py` implements ABHA-ID OTP verification (`POST /auth/abha/init-otp` + `/verify-otp`), not JWT login — there's no doctor username/password/token system today. `queue.py`'s `GET /queue/active` is FIFO (oldest-first), not priority-sorted, and there's no WebSocket/SSE — the doctor dashboard polls via an explicit refresh. Both suites test the system as it actually exists; see the module docstrings in `tests/integration/test_auth_routes.py`, `tests/integration/test_queue_routes.py`, and `e2e/tests/realtime-sync.spec.ts` for the specifics.

## Directory structure

```
PrakritiDesk/
├── .github/workflows/test.yml       CI: runs both suites on push/PR
├── intake-engine/
│   ├── pytest.ini
│   └── tests/
│       ├── conftest.py              Shared fixtures: client, session_id, sample_patient_dict
│       ├── unit/
│       │   ├── test_red_flags.py    Pure-function emergency-keyword tests
│       │   └── test_fhir_engine.py  Pure-function FHIR bundle generation tests
│       └── integration/
│           ├── test_auth_routes.py  OTP init/verify, DPDP consent (real HTTP calls, in-process)
│           └── test_queue_routes.py Active queue, patient detail, doctor edits, red-flag visibility
└── frontend/
    ├── playwright.config.ts
    └── e2e/
        ├── fixtures/
        │   ├── mocks.ts             Response builders matching the real API contracts exactly
        │   ├── mockRoutes.ts        Wires mocks.ts builders to page.route() for a whole flow
        │   └── test-fixtures.ts     Extends Playwright's `test` with kioskPage/doctorPage POM fixtures
        ├── pages/
        │   ├── KioskPage.ts         Page Object for the patient kiosk flow
        │   └── DoctorDashboardPage.ts  Page Object for the doctor dashboard
        └── tests/
            ├── patient-intake.spec.ts    Check-in -> OTP -> consent -> vitals -> intake -> completion/red-flag
            ├── doctor-dashboard.spec.ts  Queue, urgent badges, case review, FHIR export
            └── realtime-sync.spec.ts     Multi-context: kiosk check-in reflected on doctor refresh
```

## `playwright.config.ts` (key parts)

```ts
export default defineConfig({
  testDir: "./e2e/tests",
  timeout: 30_000,           // per-test: multiple sequential screens, each a network round trip
  expect: { timeout: 5_000 }, // per-assertion: should resolve fast once a mocked route fulfills
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000",
    actionTimeout: 10_000,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "kiosk-touchscreen", testMatch: /patient-intake\.spec\.ts/, use: { viewport: { width: 1080, height: 1920 }, hasTouch: true } },
    { name: "doctor-desktop", testMatch: /doctor-dashboard\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
    { name: "realtime-sync", testMatch: /realtime-sync\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: process.env.CI ? undefined : { command: "npm run dev", url: "http://127.0.0.1:3000" },
});
```

(Full file: `frontend/playwright.config.ts`.)

## Running locally

**Backend:**
```bash
cd intake-engine
pip install -r requirements.txt pytest pytest-asyncio
pytest -v                          # all tests
pytest tests/unit -v               # unit only
pytest tests/integration -v        # integration only
pytest -k "red_flag" -v            # by keyword
```
No running server, no real `GROQ_API_KEY`, no Docker needed — `tests/conftest.py` calls the FastAPI app in-process via `httpx.ASGITransport` against a throwaway SQLite file that's created and disposed of automatically.

**Frontend E2E:**
```bash
cd frontend
npm install
npx playwright install --with-deps chromium   # first time only
npm run test:e2e            # headless, auto-starts `next dev`
npm run test:e2e:ui         # Playwright's interactive UI mode, for debugging
npx playwright test patient-intake.spec.ts     # a single spec file
npx playwright show-report                     # view the last HTML report
```

## Running in CI/CD

See `.github/workflows/test.yml` for the full pipeline. Summary:

1. **Backend job** — installs `tesseract-ocr`/`tesseract-ocr-hin` (so the native-OCR test paths exercise real Tesseract, not just the Groq Vision/fallback tiers), installs Python deps, runs `pytest -v --junitxml=pytest-results.xml`, uploads the JUnit report as an artifact.
2. **Frontend job** (depends on the backend job passing) — installs Node deps + Playwright's Chromium, `npm run build`s the Next.js app, starts it with `npm run start`, waits for it to respond, then runs `npx playwright test` with `PLAYWRIGHT_BASE_URL` pointed at it. The HTML report is uploaded as an artifact on every run (pass or fail) for post-mortem debugging.

Both jobs run on every push to `main` and every pull request.

## What's verified vs. what's mocked

- **Pytest suite**: calls the real FastAPI app, the real `app/database.py` (a real, throwaway SQLite file), the real `app/red_flags.py` and `app/fhir_engine.py` logic. Only external network calls (Groq, Bhashini, ABDM) are absent — those paths are exercised by supplying a non-functional `GROQ_API_KEY`, which makes the app's own documented fallback behavior run for real (e.g. a template question instead of an LLM-generated one), rather than mocking Groq's client library directly.
- **Playwright suite**: the real Next.js app, the real React component tree, real user interactions (typing, clicking, `page.route()`-level network mocking). The FastAPI backend itself is not running for these tests — every HTTP call KioskUI/DoctorDesk make is intercepted and fulfilled with a fixture response, so this suite verifies the frontend's state machine and API contracts, not the backend's actual behavior (that's the pytest suite's job).
