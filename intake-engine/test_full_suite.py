"""Comprehensive smoke test suite for the running PrakritiDesk API.

Covers all four endpoints:
    GET  /
    POST /intake/turn
    POST /prescription/upload
    POST /fhir/generate

Usage:
    uvicorn app.main:app --reload --port 8001
    python test_full_suite.py

Requires `httpx` and `pillow` (`pip install httpx pillow`) and a live server
at BASE_URL. This is a manual/CI smoke check, not a pytest suite.
"""
import io
import sys

import httpx

BASE_URL = "http://127.0.0.1:8001"
TIMEOUT = 30

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

_results: list[tuple[str, bool]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    if condition:
        print(f"{GREEN}✅ PASS{RESET} - {label}")
    else:
        print(f"{RED}❌ FAIL{RESET} - {label}" + (f" -- {detail}" if detail else ""))
    _results.append((label, condition))
    return condition


def warn(label: str, detail: str = "") -> None:
    print(f"{YELLOW}⚠️  WARN{RESET} - {label}" + (f" -- {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{CYAN}--- {title} ---{RESET}")


def _make_test_png_bytes() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (200, 80), color="white")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------
# 1. GET /
# --------------------------------------------------------------------------

def test_health_check(client: httpx.Client) -> None:
    section("GET / (health check)")
    try:
        resp = client.get("/")
    except httpx.RequestError as exc:
        check("GET / did not raise a connection error", False, str(exc))
        return

    check("GET / returns 200", resp.status_code == 200, f"got {resp.status_code}")

    try:
        body = resp.json()
    except ValueError:
        check("GET / returns valid JSON", False, resp.text[:200])
        return

    check('GET / has "status": "online"', body.get("status") == "online", body)
    check("GET / has api name", bool(body.get("api")), body)
    check("GET / has version", bool(body.get("version")), body)


# --------------------------------------------------------------------------
# 2. POST /intake/turn
# --------------------------------------------------------------------------

def test_intake_turn(client: httpx.Client) -> None:
    section("POST /intake/turn (Groq LLM extraction)")
    payload = {
        "session_id": "full_suite_session_01",
        "user_input": "मुझे दो दिन से पेट में जलन हो रही है और भूख कम लग रही है",
        "selected_language": "Hindi",
    }

    try:
        resp = client.post("/intake/turn", json=payload)
    except httpx.RequestError as exc:
        check("POST /intake/turn did not raise a connection error", False, str(exc))
        return

    if not check("POST /intake/turn returns 200", resp.status_code == 200, resp.text[:300]):
        return

    body = resp.json()
    check('response contains non-empty "audio_prompt_text"', bool(body.get("audio_prompt_text")), body)
    check(
        'response contains non-empty "touch_options" list',
        isinstance(body.get("touch_options"), list) and len(body["touch_options"]) > 0,
        body.get("touch_options"),
    )
    check(
        '"updated_clinical_state" is present with a chief_complaint',
        bool((body.get("updated_clinical_state") or {}).get("chief_complaint")),
        body.get("updated_clinical_state"),
    )
    for field in ("is_complete", "trigger_red_flag", "red_flag_reason"):
        check(f'response contains "{field}"', field in body, body)

    # Second turn on the same session should build on the same clinical state
    # rather than starting over -- this only works end-to-end if Groq
    # extraction (or its raw-text fallback) is actually running.
    resp2 = client.post(
        "/intake/turn",
        json={"session_id": payload["session_id"], "user_input": "पेट के ऊपरी हिस्से में", "selected_language": "Hindi"},
    )
    if check("second turn on same session returns 200", resp2.status_code == 200, resp2.text[:300]):
        body2 = resp2.json()
        cc1 = (body.get("updated_clinical_state") or {}).get("chief_complaint")
        cc2 = (body2.get("updated_clinical_state") or {}).get("chief_complaint")
        check(
            "session state persists chief_complaint across turns",
            bool(cc1) and cc1 == cc2,
            f"turn1={cc1!r} turn2={cc2!r}",
        )


# --------------------------------------------------------------------------
# 3. POST /prescription/upload
# --------------------------------------------------------------------------

def test_prescription_upload(client: httpx.Client) -> None:
    section("POST /prescription/upload (multipart edge cases)")

    # 3a. Invalid file type
    resp = client.post(
        "/prescription/upload",
        files={"file": ("notes.txt", io.BytesIO(b"just some text"), "text/plain")},
    )
    check("invalid file type returns 400", resp.status_code == 400, resp.text[:300])
    if resp.status_code == 400:
        check(
            "invalid file type response has structured error detail",
            "error" in resp.json(),
            resp.json(),
        )

    # 3b. Empty file
    resp = client.post(
        "/prescription/upload",
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
    )
    check("empty file returns 400", resp.status_code == 400, resp.text[:300])

    # 3c. Valid file (a genuinely decodable, blank PNG). app/ocr_engine.py
    # guarantees process_prescription_image() never raises -- even with no
    # OCR engine installed and no working Groq key, it degrades through the
    # native-OCR -> Groq-Vision -> structured-fallback cascade and still
    # returns 200. So unlike the OCR module's internal fallback tiers,
    # THIS assertion is a hard requirement, not environment-dependent.
    png_bytes = _make_test_png_bytes()
    resp = client.post(
        "/prescription/upload",
        files={"file": ("prescription.png", io.BytesIO(png_bytes), "image/png")},
    )
    if check("valid PNG upload returns 200", resp.status_code == 200, resp.text[:300]):
        body = resp.json()
        for field in ("filename", "content_type", "file_size_bytes", "raw_text_extracted", "ocr_status", "confidence_score", "needs_review"):
            check(f'valid upload response contains "{field}"', field in body, body)
        if body.get("ocr_status") == "fallback_mode":
            warn(
                "OCR degraded all the way to fallback_mode for this upload",
                "expected when no OCR engine is installed and GROQ_API_KEY/GROQ_VISION_MODEL aren't usable in this environment",
            )


# --------------------------------------------------------------------------
# 4. POST /fhir/generate
# --------------------------------------------------------------------------

def test_fhir_generate(client: httpx.Client) -> None:
    section("POST /fhir/generate (FHIR R4 bundle)")

    valid_payload = {
        "patient": {"abha_id": "12-3456-7890-1234", "name": "Test Patient", "age": 40, "gender": "female"},
        "intake_state": {
            "chief_complaint": "Burning stomach pain",
            "socrates": {"site": "Epigastric region", "severity": "Moderate (4-7)"},
        },
        "ocr_data": {"vitals_noted": {"Pulse": "78 bpm"}},
    }

    resp = client.post("/fhir/generate", json=valid_payload)
    if check("valid session state returns 200", resp.status_code == 200, resp.text[:300]):
        bundle = resp.json()
        check('bundle "resourceType" is "Bundle"', bundle.get("resourceType") == "Bundle", bundle.get("resourceType"))
        check('bundle "type" is "collection"', bundle.get("type") == "collection", bundle.get("type"))
        entries = bundle.get("entry") or []
        resource_types = [e.get("resource", {}).get("resourceType") for e in entries]
        check('bundle contains a "Patient" resource', "Patient" in resource_types, resource_types)
        check('bundle contains a "Condition" resource', "Condition" in resource_types, resource_types)
        check('bundle contains an "Observation" resource', "Observation" in resource_types, resource_types)

    # Missing required "patient" key should be a client error, not a crash.
    resp_invalid = client.post("/fhir/generate", json={})
    check("missing patient returns 400", resp_invalid.status_code == 400, resp_invalid.text[:300])


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def main() -> int:
    print(f"Running full PrakritiDesk API test suite against {BASE_URL}")

    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as client:
        try:
            client.get("/")
        except httpx.ConnectError:
            print(f"\n{RED}ERROR: could not connect to {BASE_URL}. Is the server running?{RESET}")
            print("Start it with: uvicorn app.main:app --reload --port 8001")
            return 2

        test_health_check(client)
        test_intake_turn(client)
        test_prescription_upload(client)
        test_fhir_generate(client)

    print(f"\n{'=' * 50}")
    print("SUMMARY")
    print("=" * 50)
    passed = sum(1 for _, ok in _results if ok)
    failed = len(_results) - passed
    for label, ok in _results:
        marker = f"{GREEN}✅{RESET}" if ok else f"{RED}❌{RESET}"
        print(f"  {marker} {label}")
    print("=" * 50)
    print(f"{GREEN if failed == 0 else RED}{passed}/{len(_results)} assertions passed{RESET}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
