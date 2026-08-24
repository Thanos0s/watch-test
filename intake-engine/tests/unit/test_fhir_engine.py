"""Unit tests for app/fhir_engine.py -- consolidated session data ->
FHIR R4 Bundle. No HTTP client or database needed; generate_fhir_bundle()
is a pure transformation function.
"""
import pytest

from app.fhir_engine import generate_fhir_bundle, validate_fhir_bundle


def _resource_types(bundle: dict) -> list[str]:
    return [entry["resource"]["resourceType"] for entry in bundle["entry"]]


def _observations_by_loinc(bundle: dict) -> dict[str, dict]:
    """Maps LOINC code -> Observation resource. Skips OCR-derived vitals
    Observations (app/fhir_engine.py's _build_observations), which only
    have `code.text` (a free-text label from the prescription/lab
    document) and no `code.coding` at all, since there's no LOINC mapping
    for arbitrary OCR'd vital labels."""
    codes: dict[str, dict] = {}
    for entry in bundle["entry"]:
        resource = entry["resource"]
        if resource["resourceType"] != "Observation":
            continue
        for coding in resource["code"].get("coding", []):
            codes[coding["code"]] = resource
    return codes


class TestBundleShape:
    @pytest.mark.asyncio
    async def test_valid_patient_dict_produces_a_well_formed_bundle(self, sample_patient_dict):
        bundle = await generate_fhir_bundle(sample_patient_dict)

        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "collection"
        assert "id" in bundle and "timestamp" in bundle
        assert isinstance(bundle["entry"], list) and len(bundle["entry"]) > 0
        # generate_fhir_bundle self-validates internally and only logs a
        # warning on issues rather than raising -- assert directly here so
        # a structural regression fails the test, not just a log line.
        assert validate_fhir_bundle(bundle) == []

    @pytest.mark.asyncio
    async def test_bundle_includes_patient_condition_and_medication_resources(self, sample_patient_dict):
        bundle = await generate_fhir_bundle(sample_patient_dict)
        resource_types = _resource_types(bundle)

        assert "Patient" in resource_types
        assert "Condition" in resource_types  # chief_complaint was provided
        assert "MedicationStatement" in resource_types  # one prescribed medicine was provided

    @pytest.mark.asyncio
    async def test_patient_resource_carries_abha_identifier_and_estimated_birth_year(self, sample_patient_dict):
        bundle = await generate_fhir_bundle(sample_patient_dict)
        patient_resource = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient")

        assert patient_resource["identifier"][0]["system"] == "https://healthid.ndhm.gov.in"
        assert patient_resource["identifier"][0]["value"] == "12-3456-7890-1234"
        assert patient_resource["gender"] == "male"
        # age=42 in sample_patient_dict -> only a birth *year* can be
        # derived (not a real DOB), and it must be flagged as an estimate.
        assert "birthDate" in patient_resource
        assert any(
            ext.get("url", "").endswith("estimated-birth-year") and ext.get("valueBoolean") is True
            for ext in patient_resource.get("extension", [])
        )

    @pytest.mark.asyncio
    async def test_missing_patient_key_raises_value_error(self):
        with pytest.raises(ValueError):
            await generate_fhir_bundle({})

    @pytest.mark.asyncio
    async def test_patient_only_payload_produces_a_minimal_but_valid_bundle(self):
        bundle = await generate_fhir_bundle({"patient": {"age": 30, "gender": "female"}})
        assert _resource_types(bundle) == ["Patient"]  # no spurious Condition/Observation entries
        assert validate_fhir_bundle(bundle) == []


class TestDeviceVitalsLoincObservations:
    """Requirement: HR/SpO2/BP from a smartwatch sync must appear as
    standard LOINC-coded Observations (app/routes/vitals.py -> here)."""

    @pytest.mark.asyncio
    async def test_heart_rate_and_spo2_and_bp_panel_all_present(self, sample_patient_dict):
        payload = {**sample_patient_dict, "device_vitals": {
            "heart_rate_bpm": 88, "spo2_percent": 97, "systolic_bp": 118, "diastolic_bp": 76,
        }}
        bundle = await generate_fhir_bundle(payload)
        observations = _observations_by_loinc(bundle)

        assert "8867-4" in observations  # Heart rate
        assert observations["8867-4"]["valueQuantity"]["value"] == 88

        assert "2708-6" in observations  # Oxygen saturation
        assert observations["2708-6"]["valueQuantity"]["value"] == 97

        assert "85354-9" in observations  # Blood pressure panel
        bp = observations["85354-9"]
        component_codes = {c["code"]["coding"][0]["code"] for c in bp["component"]}
        assert component_codes == {"8480-6", "8462-4"}  # systolic, diastolic

    @pytest.mark.asyncio
    async def test_partial_device_vitals_only_produces_matching_observations(self, sample_patient_dict):
        payload = {**sample_patient_dict, "device_vitals": {"heart_rate_bpm": 75}}
        bundle = await generate_fhir_bundle(payload)
        observations = _observations_by_loinc(bundle)

        assert "8867-4" in observations
        assert "2708-6" not in observations
        assert "85354-9" not in observations

    @pytest.mark.asyncio
    async def test_no_device_vitals_produces_no_vital_sign_observations(self, sample_patient_dict):
        bundle = await generate_fhir_bundle(sample_patient_dict)
        observations = _observations_by_loinc(bundle)
        assert not {"8867-4", "2708-6", "85354-9"} & set(observations.keys())
