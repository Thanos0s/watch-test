"""Offline session/queue persistence (Module E) for the PrakritiDesk kiosk.

A kiosk needs to survive being unplugged mid-interview and to hand
completed intakes off to a doctor's queue -- both of which need state that
outlives a single FastAPI process's memory (see the `_SESSIONS` dict in
app/main.py, which is explicitly documented there as dev-only). This module
is the persistent backing store for that: a local SQLite file via
SQLAlchemy's async engine (aiosqlite driver), so it keeps working even if
the kiosk has no network connectivity.

Two tables:
  - `sessions`: one row per kiosk session (who, what language, whether
    DPDP consent was given, and where the session currently stands).
  - `clinical_states`: one row per session (chief complaint, SOCRATES,
    AYUSH/Dashavidha Pariksha, and OCR data as JSON columns), FK'd to
    `sessions.session_id`.

Tables are created automatically on first use -- no separate migration step
or explicit FastAPI startup hook is required, though calling `init_db()`
once at startup is still fine (and slightly faster for the first request).
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger("prakritidesk.database")

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./prakritidesk.db")

VALID_SESSION_STATUSES = {"in_progress", "completed", "transferred_to_doctor"}


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    abha_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    language: Mapped[str] = mapped_column(String, default="Hindi")
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    # Demographics from an ABHA lookup (app/routes/auth.py's POST /auth/abha/verify-otp).
    patient_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    abha_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class ClinicalStateRecord(Base):
    __tablename__ = "clinical_states"

    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.session_id"), primary_key=True)
    chief_complaint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    socrates_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ayush_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ocr_data_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger_red_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    # Latest smartwatch/wearable BLE sync (app/routes/vitals.py).
    device_vitals_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Why trigger_red_flag is set -- conversational intake (app/graph.py)
    # only ever surfaces this in a per-turn API response, but a vitals-
    # triggered flag needs somewhere durable to explain itself on the
    # doctor's queue.
    red_flag_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)


# --------------------------------------------------------------------------
# Engine / session factory -- lazily created, then reused for the process
# lifetime. `_init_lock` makes concurrent first-use safe: whichever asyncio
# task gets there first creates the engine and tables; everyone else just
# awaits the same lock and finds it already done.
# --------------------------------------------------------------------------

_engine = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_init_lock = asyncio.Lock()
_initialized = False


# Columns added to these tables after they originally shipped. `create_all()`
# only creates tables that don't exist yet -- it never alters an existing
# table's schema, so a `prakritidesk.db` file created before these columns
# existed would otherwise crash every query with "no such column". This map
# drives an idempotent `ALTER TABLE ... ADD COLUMN` migration that runs once
# at startup per table: a no-op on a fresh DB (create_all already includes
# these columns), a real migration on an older one.
_MIGRATION_COLUMNS_BY_TABLE = {
    "sessions": {
        "patient_name": "TEXT",
        "age": "INTEGER",
        "gender": "TEXT",
        "abha_address": "TEXT",
    },
    "clinical_states": {
        "device_vitals_json": "TEXT",
        "red_flag_reason": "TEXT",
    },
}


async def _migrate_table_columns(conn: AsyncConnection, table_name: str, columns: Dict[str, str]) -> None:
    result = await conn.exec_driver_sql(f"PRAGMA table_info({table_name})")
    existing_columns = {row[1] for row in result.fetchall()}  # row[1] == column name

    for column_name, column_type in columns.items():
        if column_name not in existing_columns:
            logger.info("Migrating %s table: adding missing column %r", table_name, column_name)
            await conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


async def _run_migrations(conn: AsyncConnection) -> None:
    for table_name, columns in _MIGRATION_COLUMNS_BY_TABLE.items():
        await _migrate_table_columns(conn, table_name, columns)


async def init_db() -> None:
    """Create the engine (if needed), all tables, and run any pending
    lightweight schema migrations. Safe to call multiple times."""
    global _engine, _session_factory, _initialized

    async with _init_lock:
        if _initialized:
            return

        if _engine is None:
            _engine = create_async_engine(DATABASE_URL, echo=False)

        try:
            async with _engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await _run_migrations(conn)
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize PrakritiDesk database at {DATABASE_URL!r}") from exc

        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        _initialized = True


async def _ensure_initialized() -> async_sessionmaker[AsyncSession]:
    if not _initialized:
        await init_db()
    assert _session_factory is not None  # guaranteed by init_db() above
    return _session_factory


# --------------------------------------------------------------------------
# Serialization helpers
# --------------------------------------------------------------------------

def _safe_json_loads(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _serialize(session_row: SessionRecord, clinical_row: Optional[ClinicalStateRecord]) -> Dict[str, Any]:
    return {
        "session_id": session_row.session_id,
        "abha_id": session_row.abha_id,
        "language": session_row.language,
        "consent_given": session_row.consent_given,
        "status": session_row.status,
        "created_at": session_row.created_at.isoformat(),
        "patient_name": session_row.patient_name,
        "age": session_row.age,
        "gender": session_row.gender,
        "abha_address": session_row.abha_address,
        "chief_complaint": clinical_row.chief_complaint if clinical_row else None,
        "socrates": _safe_json_loads(clinical_row.socrates_json if clinical_row else None),
        "ayush_parameters": _safe_json_loads(clinical_row.ayush_json if clinical_row else None),
        "ocr_data": _safe_json_loads(clinical_row.ocr_data_json if clinical_row else None),
        "trigger_red_flag": clinical_row.trigger_red_flag if clinical_row else False,
        "device_vitals": _safe_json_loads(clinical_row.device_vitals_json if clinical_row else None),
        "red_flag_reason": clinical_row.red_flag_reason if clinical_row else None,
    }


# --------------------------------------------------------------------------
# Public helper functions
# --------------------------------------------------------------------------

async def save_or_update_session(session_data: dict) -> Dict[str, Any]:
    """Upsert a session (and, if present in `session_data`, its clinical state).

    `session_data` may contain any of: session_id (required), abha_id,
    language, consent_given, status, patient_name, age, gender,
    abha_address, chief_complaint, socrates, ayush_parameters, ocr_data,
    device_vitals, trigger_red_flag, red_flag_reason. Only the keys
    actually present are written -- omitted keys leave the existing stored
    value untouched, so callers can persist a session-only update (e.g.
    consent given at check-in, or demographics from an ABHA lookup)
    without needing to already have clinical data.
    """
    session_id = session_data.get("session_id")
    if not session_id:
        raise ValueError("session_data['session_id'] is required")

    status = session_data.get("status")
    if status is not None and status not in VALID_SESSION_STATUSES:
        raise ValueError(f"Invalid status {status!r}; must be one of {sorted(VALID_SESSION_STATUSES)}")

    session_factory = await _ensure_initialized()

    async with session_factory() as db:
        async with db.begin():
            session_row = await db.get(SessionRecord, session_id)
            if session_row is None:
                session_row = SessionRecord(session_id=session_id)
                db.add(session_row)

            if "abha_id" in session_data:
                session_row.abha_id = session_data["abha_id"]
            if "language" in session_data:
                session_row.language = session_data["language"]
            if "consent_given" in session_data:
                session_row.consent_given = bool(session_data["consent_given"])
            if status is not None:
                session_row.status = status
            if "patient_name" in session_data:
                session_row.patient_name = session_data["patient_name"]
            if "age" in session_data:
                session_row.age = session_data["age"]
            if "gender" in session_data:
                session_row.gender = session_data["gender"]
            if "abha_address" in session_data:
                session_row.abha_address = session_data["abha_address"]

            clinical_fields = (
                "chief_complaint",
                "socrates",
                "ayush_parameters",
                "ocr_data",
                "device_vitals",
                "trigger_red_flag",
                "red_flag_reason",
            )
            if any(field in session_data for field in clinical_fields):
                clinical_row = await db.get(ClinicalStateRecord, session_id)
                if clinical_row is None:
                    clinical_row = ClinicalStateRecord(session_id=session_id)
                    db.add(clinical_row)

                if "chief_complaint" in session_data:
                    clinical_row.chief_complaint = session_data["chief_complaint"]
                # socrates/ayush_parameters/ocr_data are each stored as one JSON
                # blob, so a naive overwrite of the whole blob would silently
                # discard previously-captured keys on a partial update (e.g. a
                # doctor PUT-ing just {"socrates": {"onset": ...}} would wipe
                # out an already-recorded "site"/"severity"). Shallow-merge the
                # incoming dict over the existing one instead.
                if "socrates" in session_data:
                    merged = {**_safe_json_loads(clinical_row.socrates_json), **session_data["socrates"]}
                    clinical_row.socrates_json = json.dumps(merged)
                if "ayush_parameters" in session_data:
                    merged = {**_safe_json_loads(clinical_row.ayush_json), **session_data["ayush_parameters"]}
                    clinical_row.ayush_json = json.dumps(merged)
                if "ocr_data" in session_data:
                    merged = {**_safe_json_loads(clinical_row.ocr_data_json), **session_data["ocr_data"]}
                    clinical_row.ocr_data_json = json.dumps(merged)
                if "device_vitals" in session_data:
                    merged = {**_safe_json_loads(clinical_row.device_vitals_json), **session_data["device_vitals"]}
                    clinical_row.device_vitals_json = json.dumps(merged)
                if "trigger_red_flag" in session_data:
                    clinical_row.trigger_red_flag = bool(session_data["trigger_red_flag"])
                if "red_flag_reason" in session_data:
                    clinical_row.red_flag_reason = session_data["red_flag_reason"]

        await db.refresh(session_row)
        clinical_row = await db.get(ClinicalStateRecord, session_id)
        return _serialize(session_row, clinical_row)


async def get_session_by_id(session_id: str) -> Optional[Dict[str, Any]]:
    """Fetch one session (with its clinical state, if any) as a plain dict, or None."""
    session_factory = await _ensure_initialized()

    async with session_factory() as db:
        session_row = await db.get(SessionRecord, session_id)
        if session_row is None:
            return None
        clinical_row = await db.get(ClinicalStateRecord, session_id)
        return _serialize(session_row, clinical_row)


async def get_sessions_by_status(statuses: List[str]) -> List[Dict[str, Any]]:
    """Sessions whose status is any of `statuses`, oldest first (i.e. the
    actual walk-in order they should be worked in)."""
    invalid = [s for s in statuses if s not in VALID_SESSION_STATUSES]
    if invalid:
        raise ValueError(f"Invalid status(es) {invalid}; must be a subset of {sorted(VALID_SESSION_STATUSES)}")

    session_factory = await _ensure_initialized()

    async with session_factory() as db:
        result = await db.execute(
            select(SessionRecord)
            .where(SessionRecord.status.in_(statuses))
            .order_by(SessionRecord.created_at.asc())
        )
        session_rows = result.scalars().all()

        sessions: List[Dict[str, Any]] = []
        for session_row in session_rows:
            clinical_row = await db.get(ClinicalStateRecord, session_row.session_id)
            sessions.append(_serialize(session_row, clinical_row))
        return sessions


async def get_pending_doctor_queue() -> List[Dict[str, Any]]:
    """Sessions handed off to a doctor (status == "transferred_to_doctor"),
    oldest first -- i.e. the actual walk-in order the doctor should see them in.
    """
    return await get_sessions_by_status(["transferred_to_doctor"])
