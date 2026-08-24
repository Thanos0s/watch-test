"""Standalone audit script for the smartwatch vitals ingestion pipeline.

Sends a mock POST /vitals/sync request and verifies the injected vitals are
correctly reflected in:
  1. SQLite (app/database.py, via GET /queue/patient/{session_id})
  2. The doctor queue (app/routes/queue.py, via GET /queue/active)
  3. The exported FHIR bundle (app/fhir_engine.py, via POST /fhir/generate)
     -- specifically the LOINC-coded Observation entries for Heart Rate
     (8867-4), SpO2 (2708-6), and Blood Pressure (85354-9).

It also verifies the red-flag triage threshold (HR > 120 or SpO2 < 90) and
the Ayurvedic Nadi trait mapping in ayush_parameters.dupshya.

Usage:
    uvicorn app.main:app --reload --port 8001
    python scripts/test_vitals_injection.py

Requires `requests` and a live server at BASE_URL.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

BASE_URL = "http://127.0.0.1:8001"
TIMEOUT = 15

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

_passed = 0
_failed = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"{GREEN}[PASS]{RESET} {label}")
    else:
        _failed += 1
        print(f"{RED}[FAIL]{RESET} {label}" + (f" -- {detail}" if detail else ""))
    return condition


# LOINC codes this script checks for in the exported FHIR bundle -- must
# match app/fhir_engine.py's LOINC_HEART_RATE / LOINC_SPO2 /
# LOINC_BLOOD_PRESSURE_PANEL constants.
LOINC_HEART_RATE = "8867-4"
LOINC_SPO2 = "2708-6"
LOINC_BLOOD_PRESSURE_PANEL = "85354-9"

# Deliberately abnormal so this run exercises the red-flag path (HR > 120 or
# SpO2 < 90) and lands in the "Vata/Pitta Spikes" Nadi band (HR > 90) in the
# same pass, rather than needing two separate injections.
MOCK_VITALS_PAYLOAD = {
    "heart_rate_bpm": 135,
    "spo2_percent": 88,
    "systolic_bp": 190,
    "diastolic_bp": 125,
}


def main() -> int:
    session_id = f"vitals-injection-test-{uuid.uuid4().hex[:8]}"
    print(f"Running vitals injection audit against {BASE_URL} (session_id={session_id})\n")

    try:
        requests.get(f"{BASE_URL}/", timeout=TIMEOUT)
    except requests.exceptions.ConnectionError:
        print(f"ERROR: could not connect to {BASE_URL}. Is the server running?")
        print("Start it with: uvicorn app.main:app --reload --port 8001")
        return 2

    # 0. A vitals sync needs an existing session -- create one the same way
    # the kiosk check-in flow does.
    setup = requests.post(
        f"{BASE_URL}/auth/consent",
        json={"session_id": session_id, "abha_id_or_mobile": "9876543210", "consent_agreed": True},
        timeout=TIMEOUT,
    )
    if not check("setup: session created via /auth/consent", setup.status_code == 200, setup.text[:300]):
        return 1

    # --------------------------------------------------------------------
    # 1. POST /vitals/sync -- endpoint accepts the mock payload
    # --------------------------------------------------------------------
    print("\n--- 1. POST /vitals/sync ---")
    sync_resp = requests.post(
        f"{BASE_URL}/vitals/sync",
        json={"session_id": session_id, **MOCK_VITALS_PAYLOAD},
        timeout=TIMEOUT,
    )
    if not check("POST /vitals/sync returns 200 (no missing-column errors)", sync_resp.status_code == 200, sync_resp.text[:500]):
        return 1
    sync_body = sync_resp.json()

    check(
        "trigger_red_flag is True (HR 135 > 120 and SpO2 88 < 90)",
        sync_body.get("trigger_red_flag") is True,
        sync_body,
    )
    check(
        "red_flag_reason mentions Tachycardia",
        "Tachycardia" in (sync_body.get("red_flag_reason") or ""),
        sync_body.get("red_flag_reason"),
    )
    check(
        "red_flag_reason mentions Hypoxia",
        "Hypoxia" in (sync_body.get("red_flag_reason") or ""),
        sync_body.get("red_flag_reason"),
    )
    check(
        'nadi_trait_estimate is "Vata/Pitta Spikes (Irregular/Bounding Pulse)" (HR 135 > 90)',
        sync_body.get("nadi_trait_estimate") == "Vata/Pitta Spikes (Irregular/Bounding Pulse)",
        sync_body.get("nadi_trait_estimate"),
    )

    # --------------------------------------------------------------------
    # 2. SQLite persistence -- GET /queue/patient/{session_id}
    # --------------------------------------------------------------------
    print("\n--- 2. SQLite persistence (GET /queue/patient/{session_id}) ---")
    detail_resp = requests.get(f"{BASE_URL}/queue/patient/{session_id}", timeout=TIMEOUT)
    if not check("GET /queue/patient/{id} returns 200", detail_resp.status_code == 200, detail_resp.text[:300]):
        return 1
    detail = detail_resp.json()

    device_vitals = detail.get("device_vitals") or {}
    check("device_vitals.heart_rate_bpm persisted correctly", device_vitals.get("heart_rate_bpm") == 135, device_vitals)
    check("device_vitals.spo2_percent persisted correctly", device_vitals.get("spo2_percent") == 88, device_vitals)
    check("device_vitals.systolic_bp persisted correctly", device_vitals.get("systolic_bp") == 190, device_vitals)
    check("device_vitals.diastolic_bp persisted correctly", device_vitals.get("diastolic_bp") == 125, device_vitals)
    check("trigger_red_flag persisted as True", detail.get("trigger_red_flag") is True, detail.get("trigger_red_flag"))
    check(
        "ayush_parameters.dupshya auto-filled with the Nadi estimate",
        "Vata/Pitta Spikes" in (detail.get("ayush_parameters", {}).get("dupshya") or ""),
        detail.get("ayush_parameters", {}).get("dupshya"),
    )

    # --------------------------------------------------------------------
    # 3. Doctor queue reflection -- GET /queue/active
    # --------------------------------------------------------------------
    print("\n--- 3. Doctor queue reflection (GET /queue/active) ---")
    queue_resp = requests.get(f"{BASE_URL}/queue/active", timeout=TIMEOUT)
    if check("GET /queue/active returns 200", queue_resp.status_code == 200, queue_resp.text[:300]):
        queue_entries = {entry["session_id"]: entry for entry in queue_resp.json()}
        check("injected session appears in the active queue", session_id in queue_entries, list(queue_entries.keys()))
        if session_id in queue_entries:
            check(
                "queue entry reflects trigger_red_flag",
                queue_entries[session_id].get("trigger_red_flag") is True,
                queue_entries[session_id],
            )
            check(
                "queue entry reflects device_vitals.heart_rate_bpm",
                (queue_entries[session_id].get("device_vitals") or {}).get("heart_rate_bpm") == 135,
                queue_entries[session_id].get("device_vitals"),
            )

    # --------------------------------------------------------------------
    # 4. FHIR export reflection -- POST /fhir/generate
    # --------------------------------------------------------------------
    print("\n--- 4. FHIR export reflection (POST /fhir/generate) ---")
    fhir_payload = {
        "patient": {
            "abha_id": detail.get("abha_id"),
            "name": detail.get("patient_name"),
            "age": detail.get("age"),
            "gender": detail.get("gender"),
        },
        "intake_state": {
            "chief_complaint": detail.get("chief_complaint"),
            "socrates": detail.get("socrates"),
            "ayush_parameters": detail.get("ayush_parameters"),
        },
        "ocr_data": detail.get("ocr_data"),
        "device_vitals": detail.get("device_vitals"),
    }
    fhir_resp = requests.post(f"{BASE_URL}/fhir/generate", json=fhir_payload, timeout=TIMEOUT)
    if not check("POST /fhir/generate returns 200", fhir_resp.status_code == 200, fhir_resp.text[:500]):
        return 1
    bundle = fhir_resp.json()

    observations = [e["resource"] for e in bundle.get("entry", []) if e["resource"]["resourceType"] == "Observation"]
    observation_codes = set()
    for obs in observations:
        for coding in obs.get("code", {}).get("coding", []):
            observation_codes.add(coding.get("code"))

    check(f"bundle contains a Heart Rate Observation (LOINC {LOINC_HEART_RATE})", LOINC_HEART_RATE in observation_codes, observation_codes)
    check(f"bundle contains an SpO2 Observation (LOINC {LOINC_SPO2})", LOINC_SPO2 in observation_codes, observation_codes)
    check(
        f"bundle contains a Blood Pressure panel Observation (LOINC {LOINC_BLOOD_PRESSURE_PANEL})",
        LOINC_BLOOD_PRESSURE_PANEL in observation_codes,
        observation_codes,
    )

    bp_observation = next((o for o in observations if LOINC_BLOOD_PRESSURE_PANEL in {c.get("code") for c in o.get("code", {}).get("coding", [])}), None)
    if check("Blood Pressure Observation has systolic/diastolic components", bp_observation is not None and len(bp_observation.get("component", [])) == 2, bp_observation):
        component_values = {c["valueQuantity"]["value"] for c in bp_observation["component"]}
        check("BP components carry the correct injected values (190, 125)", component_values == {190, 125}, component_values)

    hr_observation = next((o for o in observations if LOINC_HEART_RATE in {c.get("code") for c in o.get("code", {}).get("coding", [])}), None)
    check(
        "Heart Rate Observation carries the correct injected value (135)",
        hr_observation is not None and hr_observation.get("valueQuantity", {}).get("value") == 135,
        hr_observation,
    )

    # --------------------------------------------------------------------
    print(f"\n{'=' * 60}\n{_passed} passed, {_failed} failed\n{'=' * 60}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
