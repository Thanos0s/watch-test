"""Integration tests for app/routes/queue.py.

NOTE ON SCOPE: GET /queue/active returns sessions oldest-first (FIFO /
walk-in order) -- there is no clinical-priority sort in this codebase.
Red-flag patients are identified via `trigger_red_flag` on each entry
(the doctor dashboard renders an "URGENT" badge from this field), but the
queue endpoint itself does not reorder around it. There is also no
WebSocket/SSE push -- the dashboard is refreshed by an explicit GET
/queue/active call (a button click, or on selecting a new patient), which
is exactly what these tests exercise directly.
"""
import pytest


class TestActiveQueue:
    @pytest.mark.asyncio
    async def test_active_queue_includes_a_freshly_created_session(self, client, session_id):
        resp = await client.get("/queue/active")
        assert resp.status_code == 200
        session_ids = [entry["session_id"] for entry in resp.json()]
        assert session_id in session_ids

    @pytest.mark.asyncio
    async def test_active_queue_entries_include_full_clinical_shape(self, client, session_id):
        resp = await client.get("/queue/active")
        entry = next(e for e in resp.json() if e["session_id"] == session_id)
        for field in ("chief_complaint", "socrates", "ayush_parameters", "ocr_data", "trigger_red_flag", "status"):
            assert field in entry

    @pytest.mark.asyncio
    async def test_queue_is_ordered_oldest_first(self, client):
        import asyncio

        first_id, second_id = "queue-order-first", "queue-order-second"
        await client.post("/auth/consent", json={"session_id": first_id, "abha_id_or_mobile": "9000000001", "consent_agreed": True})
        await asyncio.sleep(0.05)  # ensure a distinct created_at ordering
        await client.post("/auth/consent", json={"session_id": second_id, "abha_id_or_mobile": "9000000002", "consent_agreed": True})

        resp = await client.get("/queue/active")
        ids_in_order = [e["session_id"] for e in resp.json()]
        assert ids_in_order.index(first_id) < ids_in_order.index(second_id)


class TestPatientDetail:
    @pytest.mark.asyncio
    async def test_get_patient_detail_returns_full_record(self, client, session_id):
        resp = await client.get(f"/queue/patient/{session_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == session_id
        assert body["consent_given"] is True

    @pytest.mark.asyncio
    async def test_get_unknown_patient_returns_404(self, client):
        resp = await client.get("/queue/patient/does-not-exist")
        assert resp.status_code == 404
        assert resp.json()["error"] == "session_not_found"


class TestUpdatePatientStatus:
    @pytest.mark.asyncio
    async def test_put_updates_status(self, client, session_id):
        resp = await client.put(f"/queue/patient/{session_id}", json={"status": "transferred_to_doctor"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "transferred_to_doctor"

        # and the change is visible on a subsequent independent fetch
        follow_up = await client.get(f"/queue/patient/{session_id}")
        assert follow_up.json()["status"] == "transferred_to_doctor"

    @pytest.mark.asyncio
    async def test_put_rejects_invalid_status(self, client, session_id):
        resp = await client.put(f"/queue/patient/{session_id}", json={"status": "bogus_status"})
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_update_payload"

    @pytest.mark.asyncio
    async def test_put_on_unknown_session_returns_404(self, client):
        resp = await client.put("/queue/patient/does-not-exist", json={"status": "completed"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_put_partial_socrates_update_merges_instead_of_overwriting(self, client, session_id):
        """Regression guard: a doctor correcting a single SOCRATES field
        must not silently wipe out previously-recorded fields (a real bug
        found and fixed in this codebase during development)."""
        await client.put(f"/queue/patient/{session_id}", json={"socrates": {"site": "Chest", "severity": "Moderate"}})
        second = await client.put(f"/queue/patient/{session_id}", json={"socrates": {"onset": "2 days ago"}})

        socrates = second.json()["socrates"]
        assert socrates["site"] == "Chest"
        assert socrates["severity"] == "Moderate"
        assert socrates["onset"] == "2 days ago"


class TestRedFlagVisibilityInQueue:
    @pytest.mark.asyncio
    async def test_red_flag_from_vitals_is_visible_in_queue_entry(self, client):
        sid = "queue-redflag-via-vitals"
        await client.post("/auth/consent", json={"session_id": sid, "abha_id_or_mobile": "9000000099", "consent_agreed": True})

        vitals_resp = await client.post(
            "/vitals/sync",
            json={"session_id": sid, "heart_rate_bpm": 140, "spo2_percent": 85},
        )
        assert vitals_resp.status_code == 200
        assert vitals_resp.json()["trigger_red_flag"] is True

        queue_resp = await client.get("/queue/active")
        entry = next(e for e in queue_resp.json() if e["session_id"] == sid)
        assert entry["trigger_red_flag"] is True

    @pytest.mark.asyncio
    async def test_normal_vitals_do_not_set_red_flag(self, client):
        sid = "queue-normal-vitals"
        await client.post("/auth/consent", json={"session_id": sid, "abha_id_or_mobile": "9000000098", "consent_agreed": True})

        vitals_resp = await client.post(
            "/vitals/sync",
            json={"session_id": sid, "heart_rate_bpm": 75, "spo2_percent": 98},
        )
        assert vitals_resp.json()["trigger_red_flag"] is False

        queue_resp = await client.get("/queue/active")
        entry = next(e for e in queue_resp.json() if e["session_id"] == sid)
        assert entry["trigger_red_flag"] is False
