"""Shared pytest fixtures for the PrakritiDesk backend test suite.

Uses httpx.AsyncClient with ASGITransport to call the FastAPI app directly,
in-process -- no separate `uvicorn` server needs to be running. Each test
run gets its own throwaway SQLite file (deleted and recreated at session
start) so tests never touch a developer's real prakritidesk.db and are
safe to run repeatedly/in parallel-unsafe CI without manual cleanup.
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

# --------------------------------------------------------------------------
# IMPORTANT: these env vars must be set BEFORE importing anything from
# `app`, since app/database.py reads DATABASE_URL (and other modules read
# their own env vars, e.g. GROQ_API_KEY) at import time, not lazily.
# --------------------------------------------------------------------------
_TEST_DB_PATH = Path(tempfile.gettempdir()) / f"prakritidesk_test_{uuid.uuid4().hex[:8]}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH.as_posix()}"
# A syntactically-present but non-functional key: intake/OCR-structuring
# calls that hit Groq will fail and exercise this codebase's *documented*
# graceful-degradation paths (e.g. raw-text-only OCR results, template
# fallback questions) rather than a real LLM response -- which is exactly
# the deterministic, network-independent behavior a unit/integration suite
# should be asserting against, not live model output.
os.environ.setdefault("GROQ_API_KEY", "test-suite-dummy-key")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app import database as db_module  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_test_engine():
    """Session-scoped, autouse: on teardown, dispose the SQLAlchemy engine
    (closing its pooled connections) before deleting the throwaway test DB
    file. Without this, the file can still be open when we try to remove
    it -- on Windows in particular that's a locked-file error, not just an
    untidy leftover, so this isn't purely cosmetic cleanup."""
    yield
    if db_module._engine is not None:
        await db_module._engine.dispose()
    try:
        if _TEST_DB_PATH.exists():
            _TEST_DB_PATH.unlink()
    except OSError:
        pass  # best-effort; a leftover temp file here is harmless


@pytest_asyncio.fixture
async def client():
    """An httpx.AsyncClient wired directly to the FastAPI app (no network)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def session_id(client: AsyncClient) -> str:
    """A fresh kiosk session with DPDP consent already recorded -- the
    minimum state most /queue, /vitals, and /intake calls need to exist."""
    sid = f"test-session-{uuid.uuid4().hex[:10]}"
    resp = await client.post(
        "/auth/consent",
        json={"session_id": sid, "abha_id_or_mobile": "9876543210", "consent_agreed": True},
    )
    assert resp.status_code == 200, resp.text
    return sid


@pytest.fixture
def sample_patient_dict() -> dict:
    """A representative consolidated session payload, matching what
    app/fhir_engine.py's generate_fhir_bundle() and POST /fhir/generate
    both expect -- see that module's docstring for the full contract."""
    return {
        "patient": {"abha_id": "12-3456-7890-1234", "name": "Test Patient", "age": 42, "gender": "male"},
        "intake_state": {
            "chief_complaint": "Fever and body ache for 3 days",
            "socrates": {
                "site": "Generalized",
                "onset": "3 days ago",
                "character": "Dull ache",
                "radiation": None,
                "associations": "Chills, fatigue",
                "timing": "Constant",
                "exacerbating_relieving": "Worse in the evening",
                "severity": "Moderate (4-7)",
            },
            "ayush_parameters": {
                "dupshya": None,
                "desha": None,
                "bala": None,
                "kala": None,
                "anala_agni": "Mandagni",
                "prakriti": "Kapha",
                "vaya": None,
                "sattva": None,
                "satmya": None,
                "ahara": None,
            },
        },
        "ocr_data": {
            "patient_name": "Test Patient",
            "prescribed_medicines": [{"name": "Paracetamol", "dosage": "500mg", "frequency": "TDS", "duration": "3 days"}],
            "ayush_formulations": [],
            "vitals_noted": {"Temperature": "101 F"},
            "raw_text_extracted": "Tab Paracetamol 500mg TDS x 3 days",
        },
    }
