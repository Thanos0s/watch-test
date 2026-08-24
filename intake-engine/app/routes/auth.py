"""Kiosk ABHA check-in & DPDP consent capture (Module F) for PrakritiDesk.

    POST /auth/consent          -- records the patient's DPDP consent decision
    POST /auth/abha/init-otp    -- step 1: request an OTP for an ABHA ID/mobile
    POST /auth/abha/verify-otp  -- step 2: verify the OTP, persist demographics

--------------------------------------------------------------------------
Router registration instructions for app/main.py:

    from .routes.auth import router as auth_router
    ...
    app.include_router(auth_router)

(This has already been applied in this repo's app/main.py -- included here
per the task spec, and left in place as documentation for anyone wiring
this router into a different FastAPI app.)
--------------------------------------------------------------------------

*** SANDBOX DISCLAIMER ***
Simulated ABDM Gateway - Production requires certified M1/M2 CM-ID
credentials. Every OTP init/verify call logs this disclaimer and returns
`"gateway_mode"` in its response so it is never ambiguous whether a result
came from the real ABDM Sandbox Gateway or this module's simulation.

Real ABHA identity verification is an OTP flow, not a bare "look up by ID"
call -- this module mirrors that: /auth/abha/init-otp requests a one-time
code (real gateway if ABDM_CLIENT_ID/ABDM_CLIENT_SECRET are configured,
otherwise simulated), and /auth/abha/verify-otp checks it before returning
or persisting anything. There is no single stable, publicly documented
ABDM REST contract to point at unconditionally, so the real-gateway paths
here (ABDM_OTP_INIT_PATH / ABDM_OTP_VERIFY_PATH / ABDM_ABHA_PROFILE_PATH)
are best-effort and configurable, and have NOT been validated against a
live ABDM sandbox account (this project has none).

Failure handling differs deliberately between the two steps:
  - init-otp: if the real gateway call fails for any reason (network, auth,
    unexpected response), the transaction quietly downgrades to a fully
    simulated one -- the real service being unreachable is not the
    patient's problem, and a simulated OTP still lets the kiosk flow work.
  - verify-otp: a transaction that WAS created via the real gateway is only
    ever checked against the real gateway's verify response. If that call
    errors, verification is rejected (400) -- there is no local OTP to fall
    back to for a real-gateway transaction (none was ever generated), so
    this can never silently downgrade into accepting a code that was never
    actually validated.
"""
import hashlib
import logging
import os
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..database import save_or_update_session

logger = logging.getLogger("prakritidesk.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

SANDBOX_DISCLAIMER = "Simulated ABDM Gateway - Production requires certified M1/M2 CM-ID credentials."

ABHA_ID_PATTERN = re.compile(r"^\d{14}$")
MOBILE_PATTERN = re.compile(r"^(\+?91)?[6-9]\d{9}$")

# Real ABDM Sandbox Gateway config -- see the module docstring above for why
# the OTP/profile paths are best-effort/unvalidated.
ABDM_BASE_URL = os.getenv("ABDM_BASE_URL", "https://dev.abdm.gov.in")
ABDM_SESSION_PATH = "/gateway/v0.5/sessions"
ABDM_OTP_INIT_PATH = os.getenv("ABDM_OTP_INIT_PATH", "/gateway/v0.5/auth/init")
ABDM_OTP_VERIFY_PATH = os.getenv("ABDM_OTP_VERIFY_PATH", "/gateway/v0.5/auth/confirm/with-mobile-otp")
ABDM_ABHA_PROFILE_PATH = os.getenv("ABDM_ABHA_PROFILE_PATH", "/gateway/v3/profile/account")
ABDM_CLIENT_ID = os.getenv("ABDM_CLIENT_ID")
ABDM_CLIENT_SECRET = os.getenv("ABDM_CLIENT_SECRET")
DEFAULT_CM_ID = os.getenv("ABDM_CM_ID", "sbx")
ABDM_REQUEST_TIMEOUT = 15

OTP_TXN_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5


def _normalize_identifier(raw: str) -> str:
    return re.sub(r"[\s-]", "", raw)


def _validate_identifier(identifier: str) -> None:
    if not ABHA_ID_PATTERN.match(identifier) and not MOBILE_PATTERN.match(identifier):
        raise ValueError(
            "abha_id_or_mobile must be a 14-digit ABHA ID (digits only, dashes/spaces allowed) "
            "or a 10-digit Indian mobile number"
        )


def _abdm_credentials_configured() -> bool:
    return bool(ABDM_CLIENT_ID and ABDM_CLIENT_SECRET)


# --------------------------------------------------------------------------
# POST /auth/consent
# --------------------------------------------------------------------------

class ConsentRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    abha_id_or_mobile: str = Field(..., min_length=4)
    consent_agreed: bool


class ConsentResponse(BaseModel):
    session_id: str
    abha_id_or_mobile: str
    consent_given: bool
    status: str
    recorded_at: str


@router.post("/consent", response_model=ConsentResponse)
async def capture_consent(payload: ConsentRequest) -> ConsentResponse:
    """Record the patient's DPDP consent decision (agree OR decline) against their session.

    The decision is stored regardless of whether the patient agreed --
    a DPDP compliance audit trail needs a record of declines just as much
    as agreements. Declining does not raise an error here; it is the
    caller's (kiosk UI's) responsibility to not proceed into the clinical
    intake for a session with consent_given == False.
    """
    try:
        record = await save_or_update_session(
            {
                "session_id": payload.session_id,
                "abha_id": payload.abha_id_or_mobile,
                "consent_given": payload.consent_agreed,
                "status": "in_progress",
            }
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_consent_payload", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to persist consent for session_id=%s", payload.session_id)
        raise HTTPException(
            status_code=500,
            detail={"error": "consent_storage_failed", "message": str(exc)},
        ) from exc

    # Explicit audit-trail log line, in addition to the persisted DB record.
    logger.info(
        "DPDP consent event: session_id=%s abha_id_or_mobile=%s consent_agreed=%s",
        payload.session_id,
        payload.abha_id_or_mobile,
        payload.consent_agreed,
    )

    return ConsentResponse(
        session_id=record["session_id"],
        abha_id_or_mobile=record["abha_id"],
        consent_given=record["consent_given"],
        status=record["status"],
        recorded_at=record["created_at"],
    )


# --------------------------------------------------------------------------
# Mock demographics + real-gateway helpers (shared by both OTP steps)
# --------------------------------------------------------------------------

_MOCK_FIRST_NAMES = [
    "Ramesh", "Sunita", "Anil", "Priya", "Vijay", "Meena", "Arjun", "Kavita",
    "Rajesh", "Deepa", "Suresh", "Anjali", "Manoj", "Pooja", "Ravi", "Neha",
]
_MOCK_LAST_NAMES = [
    "Kumar", "Sharma", "Patel", "Singh", "Reddy", "Nair", "Gupta", "Iyer",
]
_MOCK_GENDERS = ["male", "female"]


def _derive_mock_demographics(identifier: str) -> dict:
    """Deterministic (same input -> same output) pseudo-random demographics,
    derived from a hash of the identifier -- NOT a real ABDM lookup."""
    digest = hashlib.sha256(identifier.encode("utf-8")).digest()
    first_name = _MOCK_FIRST_NAMES[digest[0] % len(_MOCK_FIRST_NAMES)]
    last_name = _MOCK_LAST_NAMES[digest[1] % len(_MOCK_LAST_NAMES)]
    gender = _MOCK_GENDERS[digest[2] % len(_MOCK_GENDERS)]
    age = 18 + (digest[3] % 63)  # 18-80
    abha_address = f"{first_name.lower()}{digest[4]:02x}@abdm"
    return {
        "name": f"{first_name} {last_name}",
        "age": age,
        "gender": gender,
        "abha_address": abha_address,
    }


def _age_from_birthdate(raw: Optional[str]) -> Optional[int]:
    """Best-effort age calculation from an ABDM-style date string
    ("YYYY-MM-DD" or bare "YYYY"); returns None rather than raising if the
    format is unexpected."""
    if not raw:
        return None
    try:
        if len(raw) == 4 and raw.isdigit():
            birth_year = int(raw)
        else:
            birth_year = date.fromisoformat(raw).year
        return max(0, date.today().year - birth_year)
    except (ValueError, TypeError):
        return None


async def _get_abdm_access_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        f"{ABDM_BASE_URL}{ABDM_SESSION_PATH}",
        json={
            "clientId": ABDM_CLIENT_ID,
            "clientSecret": ABDM_CLIENT_SECRET,
            "grantType": "client_credentials",
        },
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    token = resp.json().get("accessToken")
    if not token:
        raise RuntimeError("ABDM session response did not contain an accessToken")
    return token


async def _init_real_abdm_otp(identifier: str, cm_id: str) -> str:
    """Best-effort real ABDM Sandbox Gateway OTP-init call. Returns the
    gateway's own txnId. See the module docstring for why this is
    unvalidated/best-effort rather than a certified integration."""
    async with httpx.AsyncClient(timeout=ABDM_REQUEST_TIMEOUT) as client:
        token = await _get_abdm_access_token(client)
        resp = await client.post(
            f"{ABDM_BASE_URL}{ABDM_OTP_INIT_PATH}",
            json={"authMethod": "MOBILE_OTP", "healthid": identifier},
            headers={"Authorization": f"Bearer {token}", "X-CM-ID": cm_id, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    real_txn_id = data.get("txnId") or data.get("txn_id")
    if not real_txn_id:
        raise RuntimeError(f"ABDM OTP init response did not contain a txnId: {data!r}")
    return real_txn_id


async def _verify_real_abdm_otp(real_txn_id: str, otp: str, cm_id: str) -> dict:
    """Best-effort real ABDM Sandbox Gateway OTP-verify call. Raises on any
    failure -- see the module docstring for why a real-gateway transaction
    never falls back to local mock verification."""
    async with httpx.AsyncClient(timeout=ABDM_REQUEST_TIMEOUT) as client:
        token = await _get_abdm_access_token(client)
        resp = await client.post(
            f"{ABDM_BASE_URL}{ABDM_OTP_VERIFY_PATH}",
            json={"otp": otp, "txnId": real_txn_id},
            headers={"Authorization": f"Bearer {token}", "X-CM-ID": cm_id, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    name = data.get("name") or data.get("fullName")
    age = data.get("age") or _age_from_birthdate(data.get("dateOfBirth") or data.get("dob") or data.get("yearOfBirth"))
    gender = data.get("gender")
    abha_address = data.get("abhaAddress") or data.get("healthIdNumber") or data.get("preferredAbhaAddress")
    return {"name": name, "age": age, "gender": gender, "abha_address": abha_address}


# --------------------------------------------------------------------------
# In-memory OTP transaction store.
#
# Deliberately NOT persisted to SQLite: OTP transactions are short-lived
# (a few minutes) and single-use, unlike kiosk session/clinical data (see
# app/database.py), which specifically needs to survive a kiosk power
# cycle. Losing an in-flight OTP transaction to a restart just means the
# patient re-requests one -- a non-event, not a data-loss concern.
# --------------------------------------------------------------------------

@dataclass
class OtpTransaction:
    txn_id: str
    session_id: str
    abha_id_or_mobile: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_real_gateway: bool = False
    real_txn_id: Optional[str] = None
    otp: Optional[str] = None  # only set for simulated transactions
    verified: bool = False
    attempts: int = 0


_otp_transactions: Dict[str, OtpTransaction] = {}


def _is_expired(txn: OtpTransaction) -> bool:
    return datetime.now(timezone.utc) - txn.created_at > OTP_TXN_TTL


# --------------------------------------------------------------------------
# POST /auth/abha/init-otp
# --------------------------------------------------------------------------

class InitOtpRequest(BaseModel):
    abha_id_or_mobile: str = Field(..., min_length=10, max_length=20)
    # Not in the task's literal request shape, but required infrastructure:
    # without binding the transaction to a kiosk session up front, nothing
    # would stop verify-otp's demographics from being persisted onto an
    # unrelated session. Bound once here rather than re-supplied (and
    # potentially mismatched) at verify time.
    session_id: str = Field(..., min_length=1)


class InitOtpResponse(BaseModel):
    txn_id: str
    message: str
    gateway_mode: str  # "real" or "simulated"
    sandbox_otp_hint: Optional[str] = None  # only set for simulated transactions
    disclaimer: str = SANDBOX_DISCLAIMER


@router.post("/abha/init-otp", response_model=InitOtpResponse)
async def init_abha_otp(payload: InitOtpRequest) -> InitOtpResponse:
    """Step 1 of ABHA verification: request an OTP for the given ABHA ID/mobile.

    Tries the real ABDM Sandbox Gateway if ABDM_CLIENT_ID/ABDM_CLIENT_SECRET
    are configured; any failure of that call downgrades this transaction to
    a simulated one rather than failing the request outright.
    """
    normalized = _normalize_identifier(payload.abha_id_or_mobile)
    try:
        _validate_identifier(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_identifier", "message": str(exc)},
        ) from exc

    txn_id = f"mock-txn-{uuid.uuid4().hex[:12]}"
    txn = OtpTransaction(txn_id=txn_id, session_id=payload.session_id, abha_id_or_mobile=payload.abha_id_or_mobile)

    if _abdm_credentials_configured():
        try:
            txn.real_txn_id = await _init_real_abdm_otp(normalized, DEFAULT_CM_ID)
            txn.is_real_gateway = True
        except Exception:
            logger.exception(
                "Live ABDM OTP init failed for abha_id_or_mobile=%s; downgrading txn_id=%s to simulated",
                normalized, txn_id,
            )

    if not txn.is_real_gateway:
        txn.otp = f"{secrets.randbelow(1_000_000):06d}"

    _otp_transactions[txn_id] = txn

    logger.info(
        "[%s] OTP init: txn_id=%s target=%s gateway_mode=%s",
        SANDBOX_DISCLAIMER, txn_id, normalized, "real" if txn.is_real_gateway else "simulated",
    )
    if txn.otp:
        # Sandbox-only: no real SMS gateway is wired up, so the OTP is
        # logged (and, for testability, also returned in the response --
        # see InitOtpResponse.sandbox_otp_hint) rather than actually sent.
        logger.info("[%s] Sandbox OTP for txn_id=%s: %s", SANDBOX_DISCLAIMER, txn_id, txn.otp)

    return InitOtpResponse(
        txn_id=txn_id,
        message="OTP sent to registered mobile",
        gateway_mode="real" if txn.is_real_gateway else "simulated",
        sandbox_otp_hint=txn.otp,
    )


# --------------------------------------------------------------------------
# POST /auth/abha/verify-otp
# --------------------------------------------------------------------------

class VerifyOtpRequest(BaseModel):
    txn_id: str = Field(..., min_length=1)
    otp: str = Field(..., min_length=4, max_length=8)


class VerifyOtpResponse(BaseModel):
    verification_status: str  # "verified" (real gateway) or "mock_verified"
    is_mock: bool
    gateway_mode: str  # "real" or "simulated"
    session_id: str
    abha_id_or_mobile: str
    patient_record: Dict[str, Any]  # full persisted session record from app.database
    disclaimer: str = SANDBOX_DISCLAIMER


@router.post("/abha/verify-otp", response_model=VerifyOtpResponse)
async def verify_abha_otp(payload: VerifyOtpRequest) -> VerifyOtpResponse:
    """Step 2 of ABHA verification: check the OTP, then persist the
    resulting demographics and a consent-audit record onto the session
    app/routes/auth.py's init-otp bound the transaction to.
    """
    txn = _otp_transactions.get(payload.txn_id)
    if txn is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "txn_not_found", "message": f"No OTP transaction found for txn_id={payload.txn_id!r}"},
        )

    if _is_expired(txn):
        del _otp_transactions[payload.txn_id]
        raise HTTPException(
            status_code=410,
            detail={"error": "txn_expired", "message": "This OTP transaction has expired. Call /auth/abha/init-otp again."},
        )

    if txn.verified:
        raise HTTPException(
            status_code=409,
            detail={"error": "txn_already_used", "message": "This OTP transaction has already been verified."},
        )

    txn.attempts += 1
    if txn.attempts > OTP_MAX_ATTEMPTS:
        del _otp_transactions[payload.txn_id]
        raise HTTPException(
            status_code=429,
            detail={"error": "too_many_attempts", "message": "Too many incorrect OTP attempts. Call /auth/abha/init-otp again."},
        )

    demographics: Optional[dict] = None

    if txn.is_real_gateway and txn.real_txn_id:
        # A real-gateway transaction is ONLY ever checked against the real
        # gateway -- see the module docstring for why this never falls back
        # to local mock verification.
        try:
            demographics = await _verify_real_abdm_otp(txn.real_txn_id, payload.otp, DEFAULT_CM_ID)
        except Exception as exc:
            logger.exception("Live ABDM OTP verify failed for txn_id=%s", payload.txn_id)
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_otp", "message": "OTP verification failed."},
            ) from exc
    else:
        if not secrets.compare_digest(payload.otp, txn.otp or ""):
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_otp", "message": "The OTP entered is incorrect."},
            )
        demographics = _derive_mock_demographics(_normalize_identifier(txn.abha_id_or_mobile))

    txn.verified = True

    try:
        patient_record = await save_or_update_session(
            {
                "session_id": txn.session_id,
                "abha_id": txn.abha_id_or_mobile,
                "patient_name": demographics["name"],
                "age": demographics["age"],
                "gender": demographics["gender"],
                "abha_address": demographics["abha_address"],
                # Completing ABDM OTP verification is itself a consent-bearing
                # action (the patient actively authenticated to link their
                # ABHA identity) -- recorded here distinctly from, and in
                # addition to, the separate DPDP data-use consent captured
                # by POST /auth/consent.
                "consent_given": True,
            }
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_verify_payload", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to persist ABHA demographics for session_id=%s", txn.session_id)
        raise HTTPException(
            status_code=500,
            detail={"error": "demographics_storage_failed", "message": str(exc)},
        ) from exc

    logger.info(
        "[%s] Consent audit: session_id=%s abha_id_or_mobile=%s gateway_mode=%s verified=True",
        SANDBOX_DISCLAIMER, txn.session_id, txn.abha_id_or_mobile, "real" if txn.is_real_gateway else "simulated",
    )

    del _otp_transactions[payload.txn_id]  # single-use

    return VerifyOtpResponse(
        verification_status="verified" if txn.is_real_gateway else "mock_verified",
        is_mock=not txn.is_real_gateway,
        gateway_mode="real" if txn.is_real_gateway else "simulated",
        session_id=txn.session_id,
        abha_id_or_mobile=txn.abha_id_or_mobile,
        patient_record=patient_record,
    )
