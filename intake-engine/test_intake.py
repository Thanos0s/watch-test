"""Automated smoke test for the running PrakritiDesk intake API.

Usage:
    uvicorn app.main:app --reload --port 8001
    python test_intake.py

Requires the `requests` package (`pip install requests`) and a live server
at BASE_URL. This is a manual/CI smoke check, not a pytest suite (though
the test_* functions are pytest-discoverable if you want to run it that way).
"""
import sys

import requests

# Windows terminals sometimes default stdout to a legacy codepage (e.g.
# cp1252) that can't encode the emoji status indicators below; force UTF-8
# so this script's output is portable across Windows/macOS/Linux terminals.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

BASE_URL = "http://127.0.0.1:8001"
TIMEOUT = 15

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def _ok(message: str) -> None:
    print(f"{GREEN}✅ PASS{RESET} - {message}")


def _fail(message: str) -> None:
    print(f"{RED}❌ FAIL{RESET} - {message}")


def _warn(message: str) -> None:
    print(f"{YELLOW}⚠️  WARN{RESET} - {message}")


def test_health_check() -> bool:
    """GET / should return 200 with status: online."""
    print("\n--- test_health_check ---")
    try:
        resp = requests.get(f"{BASE_URL}/", timeout=TIMEOUT)
    except requests.exceptions.RequestException as exc:
        _fail(f"GET / raised an exception: {exc}")
        return False

    passed = True

    if resp.status_code == 200:
        _ok(f"GET / returned status_code 200")
    else:
        _fail(f"GET / returned status_code {resp.status_code}, expected 200")
        passed = False

    try:
        body = resp.json()
    except ValueError:
        _fail(f"GET / did not return valid JSON: {resp.text[:200]!r}")
        return False

    if body.get("status") == "online":
        _ok('GET / response contains "status": "online"')
    else:
        _fail(f'GET / expected "status": "online", got {body.get("status")!r}')
        passed = False

    return passed


def test_intake_turn() -> bool:
    """POST /intake/turn with a Hindi symptom description should return a valid intake prompt."""
    print("\n--- test_intake_turn ---")
    payload = {
        "session_id": "test_sih_01",
        "user_input": "मुझे दो दिन से पेट में जलन हो रही है और भूख कम लग रही है",
        "selected_language": "Hindi",
    }

    try:
        resp = requests.post(f"{BASE_URL}/intake/turn", json=payload, timeout=TIMEOUT)
    except requests.exceptions.RequestException as exc:
        _fail(f"POST /intake/turn raised an exception: {exc}")
        return False

    passed = True

    if resp.status_code == 200:
        _ok("POST /intake/turn returned status_code 200")
    else:
        _fail(f"POST /intake/turn returned status_code {resp.status_code}: {resp.text[:300]}")
        return False

    try:
        body = resp.json()
    except ValueError:
        _fail(f"POST /intake/turn did not return valid JSON: {resp.text[:300]!r}")
        return False

    if "audio_prompt_text" in body and body["audio_prompt_text"]:
        _ok(f'response contains non-empty "audio_prompt_text": {body["audio_prompt_text"]!r}')
    else:
        _fail('response missing or empty "audio_prompt_text"')
        passed = False

    if "touch_options" in body and isinstance(body["touch_options"], list) and body["touch_options"]:
        _ok(f'response contains non-empty "touch_options": {body["touch_options"]}')
    else:
        _fail('response missing or empty "touch_options"')
        passed = False

    # Burning stomach pain + reduced appetite for two days is not one of the
    # hard emergency red flags (chest pain, breathlessness, stroke signs,
    # sudden vision loss), so this should NOT trigger the triage alert.
    if body.get("trigger_red_flag") is False:
        _ok('"trigger_red_flag" correctly False for this non-emergency symptom')
    else:
        _warn(f'expected "trigger_red_flag": false, got {body.get("trigger_red_flag")!r}')

    return passed


def main() -> int:
    print(f"Running PrakritiDesk intake API tests against {BASE_URL}")

    try:
        requests.get(f"{BASE_URL}/", timeout=TIMEOUT)
    except requests.exceptions.ConnectionError:
        print(f"\n{RED}ERROR: could not connect to {BASE_URL}. Is the server running?{RESET}")
        print("Start it with: uvicorn app.main:app --reload --port 8001")
        return 2

    results = {
        "test_health_check": test_health_check(),
        "test_intake_turn": test_intake_turn(),
    }

    print(f"\n{'=' * 40}")
    for name, passed in results.items():
        if passed:
            _ok(name)
        else:
            _fail(name)
    print("=" * 40)

    total = len(results)
    passed_count = sum(1 for v in results.values() if v)
    print(f"{passed_count}/{total} tests passed")

    return 0 if passed_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
