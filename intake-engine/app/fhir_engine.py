"""ABDM-compliant FHIR R4 resource generation (Module C) for PrakritiDesk.

Takes the data already gathered by the intake engine (app/graph.py) and the
prescription OCR engine (app/ocr_engine.py) and maps it into a FHIR R4
`Bundle` (type: "collection") containing Patient, Condition,
MedicationStatement, and Observation resources.

This module does not decide or infer any new clinical content -- it only
transcribes data that has already been captured elsewhere into the FHIR
shape the ABDM ecosystem expects. It builds and structurally
self-validates the bundle in-process; it does not call out to an external
HAPI FHIR server or any other runtime dependency.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("prakritidesk.fhir_engine")

# ABDM/NDHM FHIR Implementation Guide identifier system for the ABHA number.
ABHA_IDENTIFIER_SYSTEM = "https://healthid.ndhm.gov.in"

FHIR_GENDER_MAP = {
    "male": "male",
    "m": "male",
    "female": "female",
    "f": "female",
    "other": "other",
    "o": "other",
    "unknown": "unknown",
}

SOCRATES_LABELS = {
    "character": "Character",
    "radiation": "Radiation",
    "associations": "Associations",
    "timing": "Timing",
    "exacerbating_relieving": "Exacerbating/Relieving factors",
}

# Full Dashavidha Pariksha (ten-fold Ayurvedic clinical examination).
AYUSH_LABELS = {
    "dupshya": "Dushya (dosha/dhatu imbalance)",
    "desha": "Desha (habitat/climate)",
    "bala": "Bala (physical strength)",
    "kala": "Kala (season/time)",
    "anala_agni": "Anala/Agni (digestive fire type)",
    "prakriti": "Prakriti (constitution)",
    "vaya": "Vaya (age group)",
    "sattva": "Sattva (mental temperament)",
    "satmya": "Satmya (habituation/tolerance)",
    "ahara": "Ahara (diet/bowel pattern)",
}

VITAL_SIGNS_CATEGORY = {
    "coding": [
        {
            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
            "code": "vital-signs",
            "display": "Vital Signs",
        }
    ]
}

# LOINC codes for the smartwatch/wearable vitals (app/routes/vitals.py).
LOINC_HEART_RATE = "8867-4"
LOINC_SPO2 = "2708-6"
LOINC_BLOOD_PRESSURE_PANEL = "85354-9"
LOINC_SYSTOLIC_BP = "8480-6"
LOINC_DIASTOLIC_BP = "8462-4"


def _urn(resource_uuid: str) -> str:
    return f"urn:uuid:{resource_uuid}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_gender(raw_gender: Optional[str]) -> str:
    if not raw_gender:
        return "unknown"
    return FHIR_GENDER_MAP.get(str(raw_gender).strip().lower(), "unknown")


def _approximate_birth_year(age: Optional[int]) -> Optional[str]:
    """FHIR `birthDate` accepts a partial date; a bare year is valid when
    only age (not a DOB) is known. This is explicitly an estimate."""
    if age is None:
        return None
    try:
        age_int = int(age)
    except (TypeError, ValueError):
        return None
    return str(datetime.now(timezone.utc).year - age_int)


# --------------------------------------------------------------------------
# Resource builders
# --------------------------------------------------------------------------

def _build_patient_resource(patient_info: Dict[str, Any]) -> Dict[str, Any]:
    patient_id = str(uuid4())
    resource: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": patient_id,
        "gender": _normalize_gender(patient_info.get("gender")),
    }

    abha_id = patient_info.get("abha_id")
    if abha_id:
        resource["identifier"] = [
            {"system": ABHA_IDENTIFIER_SYSTEM, "value": str(abha_id)}
        ]

    name = patient_info.get("name")
    if name:
        resource["name"] = [{"text": str(name)}]

    birth_year = _approximate_birth_year(patient_info.get("age"))
    if birth_year:
        resource["birthDate"] = birth_year
        resource.setdefault("extension", []).append(
            {
                "url": "https://prakritidesk.example/fhir/StructureDefinition/estimated-birth-year",
                "valueBoolean": True,
            }
        )

    return resource, patient_id


def _build_condition_resource(
    intake_state: Dict[str, Any], patient_urn: str
) -> Optional[Dict[str, Any]]:
    chief_complaint = intake_state.get("chief_complaint")
    if not chief_complaint:
        return None

    socrates = intake_state.get("socrates") or {}
    ayush_parameters = intake_state.get("ayush_parameters") or {}

    condition: Dict[str, Any] = {
        "resourceType": "Condition",
        "id": str(uuid4()),
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                }
            ]
        },
        "code": {"text": str(chief_complaint)},
        "subject": {"reference": patient_urn},
        "recordedDate": _now_iso(),
    }

    if socrates.get("site"):
        condition["bodySite"] = [{"text": str(socrates["site"])}]

    if socrates.get("onset"):
        condition["onsetString"] = str(socrates["onset"])

    if socrates.get("severity"):
        condition["severity"] = {"text": str(socrates["severity"])}

    note_lines: List[str] = []
    for field, label in SOCRATES_LABELS.items():
        value = socrates.get(field)
        if value:
            note_lines.append(f"{label}: {value}")
    for field, label in AYUSH_LABELS.items():
        value = ayush_parameters.get(field)
        if value:
            note_lines.append(f"{label}: {value}")

    if note_lines:
        condition["note"] = [{"text": "; ".join(note_lines)}]

    return condition


def _build_medication_statement(
    medication_name: str,
    dosage_text: Optional[str],
    patient_urn: str,
    category_text: Optional[str] = None,
) -> Dict[str, Any]:
    resource: Dict[str, Any] = {
        "resourceType": "MedicationStatement",
        "id": str(uuid4()),
        "status": "active",
        "medicationCodeableConcept": {"text": medication_name},
        "subject": {"reference": patient_urn},
        "effectiveDateTime": _now_iso(),
    }
    if category_text:
        resource["category"] = {"text": category_text}
    if dosage_text:
        resource["dosage"] = [{"text": dosage_text}]
    return resource


def _build_medication_statements(
    ocr_data: Dict[str, Any], patient_urn: str
) -> List[Dict[str, Any]]:
    statements: List[Dict[str, Any]] = []

    for medicine in ocr_data.get("prescribed_medicines") or []:
        name = medicine.get("name")
        if not name:
            continue
        dosage_parts = [
            medicine.get("dosage"),
            medicine.get("frequency"),
            medicine.get("duration"),
        ]
        dosage_text = ", ".join(part for part in dosage_parts if part) or None
        statements.append(
            _build_medication_statement(str(name), dosage_text, patient_urn, category_text="Allopathic")
        )

    for formulation in ocr_data.get("ayush_formulations") or []:
        herb = formulation.get("herb_or_churn")
        if not herb:
            continue
        dosage_parts = [formulation.get("anupana"), formulation.get("timing")]
        dosage_text = ", ".join(part for part in dosage_parts if part) or None
        statements.append(
            _build_medication_statement(str(herb), dosage_text, patient_urn, category_text="AYUSH formulation")
        )

    return statements


def _build_observations(ocr_data: Dict[str, Any], patient_urn: str) -> List[Dict[str, Any]]:
    observations: List[Dict[str, Any]] = []
    vitals_noted = ocr_data.get("vitals_noted") or {}

    for label, value in vitals_noted.items():
        if value in (None, ""):
            continue
        observations.append(
            {
                "resourceType": "Observation",
                "id": str(uuid4()),
                "status": "final",
                "code": {"text": str(label)},
                "subject": {"reference": patient_urn},
                "effectiveDateTime": _now_iso(),
                "valueString": str(value),
            }
        )

    return observations


def _vital_sign_observation(
    code: str, display: str, value: float, unit: str, unit_code: str, patient_urn: str
) -> Dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": str(uuid4()),
        "status": "final",
        "category": [VITAL_SIGNS_CATEGORY],
        "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}], "text": display},
        "subject": {"reference": patient_urn},
        "effectiveDateTime": _now_iso(),
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit_code},
    }


def _build_device_vitals_observations(device_vitals: Dict[str, Any], patient_urn: str) -> List[Dict[str, Any]]:
    """LOINC-coded Observations from a smartwatch/wearable BLE sync
    (app/routes/vitals.py). Blood pressure is emitted as a single panel
    Observation (LOINC 85354-9) with systolic/diastolic `component`
    entries, per standard FHIR practice -- not two separate resources."""
    observations: List[Dict[str, Any]] = []

    heart_rate = device_vitals.get("heart_rate_bpm")
    if heart_rate is not None:
        observations.append(
            _vital_sign_observation(LOINC_HEART_RATE, "Heart rate", heart_rate, "beats/minute", "/min", patient_urn)
        )

    spo2 = device_vitals.get("spo2_percent")
    if spo2 is not None:
        observations.append(
            _vital_sign_observation(LOINC_SPO2, "Oxygen saturation", spo2, "%", "%", patient_urn)
        )

    systolic = device_vitals.get("systolic_bp")
    diastolic = device_vitals.get("diastolic_bp")
    if systolic is not None and diastolic is not None:
        observations.append(
            {
                "resourceType": "Observation",
                "id": str(uuid4()),
                "status": "final",
                "category": [VITAL_SIGNS_CATEGORY],
                "code": {
                    "coding": [
                        {"system": "http://loinc.org", "code": LOINC_BLOOD_PRESSURE_PANEL, "display": "Blood pressure panel"}
                    ],
                    "text": "Blood pressure",
                },
                "subject": {"reference": patient_urn},
                "effectiveDateTime": _now_iso(),
                "component": [
                    {
                        "code": {
                            "coding": [
                                {"system": "http://loinc.org", "code": LOINC_SYSTOLIC_BP, "display": "Systolic blood pressure"}
                            ]
                        },
                        "valueQuantity": {
                            "value": systolic,
                            "unit": "mmHg",
                            "system": "http://unitsofmeasure.org",
                            "code": "mm[Hg]",
                        },
                    },
                    {
                        "code": {
                            "coding": [
                                {"system": "http://loinc.org", "code": LOINC_DIASTOLIC_BP, "display": "Diastolic blood pressure"}
                            ]
                        },
                        "valueQuantity": {
                            "value": diastolic,
                            "unit": "mmHg",
                            "system": "http://unitsofmeasure.org",
                            "code": "mm[Hg]",
                        },
                    },
                ],
            }
        )

    return observations


# --------------------------------------------------------------------------
# Structural self-validation (no external HAPI server required)
# --------------------------------------------------------------------------

_REQUIRED_FIELDS_BY_TYPE = {
    "Patient": ["id", "gender"],
    "Condition": ["id", "code", "subject"],
    "MedicationStatement": ["id", "status", "medicationCodeableConcept", "subject"],
    "Observation": ["id", "status", "code", "subject"],
}


def validate_fhir_bundle(bundle: Dict[str, Any]) -> List[str]:
    """Lightweight structural check that the bundle looks like valid FHIR R4.

    This is not a substitute for full FHIR profile validation (e.g. against
    a HAPI FHIR server or the ABDM implementation guide's StructureDefinitions)
    -- it only catches shape mistakes made by the builder functions above.
    """
    issues: List[str] = []

    if bundle.get("resourceType") != "Bundle":
        issues.append("Top-level resourceType must be 'Bundle'.")
    if bundle.get("type") != "collection":
        issues.append("Bundle.type must be 'collection'.")
    if not isinstance(bundle.get("entry"), list):
        issues.append("Bundle.entry must be a list.")
        return issues

    for index, entry in enumerate(bundle["entry"]):
        resource = entry.get("resource")
        if not entry.get("fullUrl"):
            issues.append(f"entry[{index}] is missing 'fullUrl'.")
        if not isinstance(resource, dict):
            issues.append(f"entry[{index}] is missing a 'resource' object.")
            continue

        resource_type = resource.get("resourceType")
        required_fields = _REQUIRED_FIELDS_BY_TYPE.get(resource_type)
        if required_fields is None:
            issues.append(f"entry[{index}] has unrecognized resourceType '{resource_type}'.")
            continue

        for field in required_fields:
            if field not in resource:
                issues.append(f"entry[{index}] ({resource_type}) is missing required field '{field}'.")

    return issues


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

async def generate_fhir_bundle(intake_data: dict) -> dict:
    """Build a FHIR R4 `Bundle` (type: "collection") from consolidated intake data.

    Expected shape of `intake_data`:
        {
          "patient": {"abha_id": str, "name": str, "age": int, "gender": str},
          "intake_state": {
            "chief_complaint": str,
            "socrates": {site, onset, character, radiation, associations,
                         timing, exacerbating_relieving, severity},
            "ayush_parameters": {dupshya, desha, bala, kala, anala_agni,
                                 prakriti, vaya, sattva, satmya, ahara},
          },
          "ocr_data": {
            "patient_name": str, "prescribed_medicines": [...],
            "ayush_formulations": [...], "vitals_noted": {...},
            "raw_text_extracted": str,
          },
          "device_vitals": {
            "heart_rate_bpm": int, "spo2_percent": int,
            "systolic_bp": int, "diastolic_bp": int,
          },
        }

    Every key above is optional except `patient` -- resources are only added
    for data that was actually present (e.g. no Condition entry if there is
    no chief complaint, no MedicationStatement entries if none were found).
    """
    patient_info = intake_data.get("patient")
    if not patient_info:
        raise ValueError("intake_data['patient'] is required to build a FHIR bundle")

    intake_state = intake_data.get("intake_state") or {}
    ocr_data = intake_data.get("ocr_data") or {}
    device_vitals = intake_data.get("device_vitals") or {}

    patient_resource, patient_id = _build_patient_resource(patient_info)
    patient_urn = _urn(patient_id)

    entries: List[Dict[str, Any]] = [{"fullUrl": patient_urn, "resource": patient_resource}]

    condition = _build_condition_resource(intake_state, patient_urn)
    if condition:
        entries.append({"fullUrl": _urn(condition["id"]), "resource": condition})

    for statement in _build_medication_statements(ocr_data, patient_urn):
        entries.append({"fullUrl": _urn(statement["id"]), "resource": statement})

    for observation in _build_observations(ocr_data, patient_urn):
        entries.append({"fullUrl": _urn(observation["id"]), "resource": observation})

    for observation in _build_device_vitals_observations(device_vitals, patient_urn):
        entries.append({"fullUrl": _urn(observation["id"]), "resource": observation})

    bundle: Dict[str, Any] = {
        "resourceType": "Bundle",
        "id": str(uuid4()),
        "type": "collection",
        "timestamp": _now_iso(),
        "entry": entries,
    }

    issues = validate_fhir_bundle(bundle)
    if issues:
        logger.warning("Generated FHIR bundle has structural issues: %s", issues)

    return bundle
