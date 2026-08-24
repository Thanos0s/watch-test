"""Integration tests for app/routes/auth.py.

NOTE ON SCOPE: this codebase's auth.py implements ABHA-ID identity
verification via a two-step OTP flow (POST /auth/abha/init-otp + POST
/auth/abha/verify-otp) plus separate DPDP consent capture (POST
/auth/consent) -- there is no username/password/JWT-based doctor login
anywhere in this system. These tests cover what's actually implemented.

No ABDM_CLIENT_ID/ABDM_CLIENT_SECRET are set in the test environment
(see tests/conftest.py), so every OTP transaction below runs in
"simulated" gateway mode -- the sandbox OTP is returned directly in the
init response (`sandbox_otp_hint`) specifically so it can be asserted
against here without needing a real SMS gateway.
"""
import pytest


class TestAbhaOtpVerificationFlow:
    @pytest.mark.asyncio
    async def test_init_otp_returns_txn_id_and_simulated_gateway_mode(self, client):
        resp = await client.post(
            "/auth/abha/init-otp",
            json={"abha_id_or_mobile": "9876543220", "session_id": "otp-flow-init"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["txn_id"]
        assert body["gateway_mode"] == "simulated"
        assert body["sandbox_otp_hint"] is not None
        assert "Simulated ABDM Gateway" in body["disclaimer"]

    @pytest.mark.asyncio
    async def test_init_otp_rejects_malformed_identifier(self, client):
        resp = await client.post(
            "/auth/abha/init-otp",
            # 13 digits: long enough to pass min_length, wrong format for
            # both the 14-digit ABHA ID and 10-digit mobile patterns.
            json={"abha_id_or_mobile": "1234567890123", "session_id": "otp-flow-bad-id"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_identifier"

    @pytest.mark.asyncio
    async def test_verify_otp_with_correct_code_returns_demographics(self, client):
        init_resp = await client.post(
            "/auth/abha/init-otp",
            json={"abha_id_or_mobile": "9876543221", "session_id": "otp-flow-verify-ok"},
        )
        txn_id = init_resp.json()["txn_id"]
        correct_otp = init_resp.json()["sandbox_otp_hint"]

        verify_resp = await client.post("/auth/abha/verify-otp", json={"txn_id": txn_id, "otp": correct_otp})
        assert verify_resp.status_code == 200
        body = verify_resp.json()
        assert body["verification_status"] == "mock_verified"
        assert body["is_mock"] is True
        record = body["patient_record"]
        assert record["patient_name"] is not None
        assert record["abha_address"] is not None
        assert record["consent_given"] is True  # completing OTP verification is itself consent-bearing

    @pytest.mark.asyncio
    async def test_verify_otp_with_wrong_code_is_rejected(self, client):
        init_resp = await client.post(
            "/auth/abha/init-otp",
            json={"abha_id_or_mobile": "9876543222", "session_id": "otp-flow-verify-wrong"},
        )
        txn_id = init_resp.json()["txn_id"]
        real_otp = init_resp.json()["sandbox_otp_hint"]
        wrong_otp = "000000" if real_otp != "000000" else "111111"

        resp = await client.post("/auth/abha/verify-otp", json={"txn_id": txn_id, "otp": wrong_otp})
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_otp"

    @pytest.mark.asyncio
    async def test_verify_otp_is_single_use(self, client):
        init_resp = await client.post(
            "/auth/abha/init-otp",
            json={"abha_id_or_mobile": "9876543223", "session_id": "otp-flow-single-use"},
        )
        txn_id = init_resp.json()["txn_id"]
        otp = init_resp.json()["sandbox_otp_hint"]

        first = await client.post("/auth/abha/verify-otp", json={"txn_id": txn_id, "otp": otp})
        second = await client.post("/auth/abha/verify-otp", json={"txn_id": txn_id, "otp": otp})

        assert first.status_code == 200
        assert second.status_code == 404  # transaction was deleted after first successful use
        assert second.json()["error"] == "txn_not_found"

    @pytest.mark.asyncio
    async def test_verify_otp_with_unknown_txn_id_returns_404(self, client):
        resp = await client.post("/auth/abha/verify-otp", json={"txn_id": "does-not-exist", "otp": "123456"})
        assert resp.status_code == 404


class TestDpdpConsent:
    @pytest.mark.asyncio
    async def test_consent_agreed_is_recorded(self, client):
        resp = await client.post(
            "/auth/consent",
            json={"session_id": "consent-agree", "abha_id_or_mobile": "9876543224", "consent_agreed": True},
        )
        assert resp.status_code == 200
        assert resp.json()["consent_given"] is True

    @pytest.mark.asyncio
    async def test_consent_declined_is_still_recorded_not_rejected(self, client):
        """Declining consent is a valid, auditable outcome -- not a 4xx error.
        It's the caller's job to not proceed into clinical intake afterwards."""
        resp = await client.post(
            "/auth/consent",
            json={"session_id": "consent-decline", "abha_id_or_mobile": "9876543225", "consent_agreed": False},
        )
        assert resp.status_code == 200
        assert resp.json()["consent_given"] is False

    @pytest.mark.asyncio
    async def test_consent_requires_session_id(self, client):
        resp = await client.post(
            "/auth/consent",
            json={"abha_id_or_mobile": "9876543226", "consent_agreed": True},
        )
        assert resp.status_code == 422  # FastAPI/Pydantic request validation
