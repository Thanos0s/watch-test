"""Seed the local SQLite database with 3 realistic OPD cases for demo/judging.

Run from the `intake-engine` directory:

    python scripts/seed_demo.py

(It also works from the repo root or anywhere else -- the script adds
`intake-engine/` to `sys.path` itself so `import app...` resolves regardless
of the current working directory.)

This writes directly into app/database.py's persistence layer -- it does
NOT call Groq or any LLM, so it needs no GROQ_API_KEY and produces
deterministic, reviewable data every time. Each case uses
`status="transferred_to_doctor"`, so right after seeding, `GET /queue/active`
and the doctor dashboard will show all three immediately.

Re-running this script is safe: save_or_update_session() upserts by
session_id, so seeding twice just overwrites the same three demo rows
rather than creating duplicates.

Cases:
  1. Standard allopathic intake, 45M, chest discomfort -- RED FLAG triggered
     (SOCRATES fully populated; AYUSH left empty since a real red-flag
     interview would be interrupted before reaching those questions).
  2. Ayurvedic intake (AIIA-style), 32F, chronic digestive distress -- full
     Dashavidha Pariksha: Manda Agni, Krura Koshtha, Vata-Pitta Prakriti.
  3. OCR/scanned document case, 58M -- a messy simulated handwritten
     prescription with deliberately garbled/missing OCR fields, so the
     doctor dashboard's low-confidence (yellow) and missing-field (red)
     highlighting both have something real to flag.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import save_or_update_session  # noqa: E402

CASE_1_CHEST_PAIN = {
    "session_id": "demo-case-1-chest-pain",
    "abha_id": "12-3456-7890-0001",
    "language": "Hindi",
    "consent_given": True,
    "status": "transferred_to_doctor",
    "chief_complaint": "Chest discomfort and mild breathlessness",
    "socrates": {
        "site": "Central chest",
        "onset": "Started 2 hours ago",
        "character": "Tight, pressure-like",
        "radiation": "Radiates to left arm and jaw",
        "associations": "Sweating and nausea",
        "timing": "Constant since onset",
        "exacerbating_relieving": "Worse with exertion, no relief with rest",
        "severity": "Severe (8-10)",
    },
    # Left empty: a real red-flag interview short-circuits before the AYUSH
    # (Dashavidha Pariksha) questions are ever reached -- see app/graph.py.
    "ayush_parameters": {},
    "ocr_data": {},
    "trigger_red_flag": True,
}

CASE_2_AYURVEDIC_DIGESTIVE = {
    "session_id": "demo-case-2-ayurvedic-digestive",
    "abha_id": "12-3456-7890-0002",
    "language": "Hindi",
    "consent_given": True,
    "status": "transferred_to_doctor",
    "chief_complaint": "Chronic digestive distress and bloating",
    "socrates": {
        "site": "Abdomen, diffuse",
        "onset": "Gradual, over the last 6 months",
        "character": "Bloating with dull ache",
        "radiation": "None",
        "associations": "Occasional constipation and fatigue",
        "timing": "Worse after meals, intermittent through the day",
        "exacerbating_relieving": "Worse with heavy/oily food, better with warm water",
        "severity": "Moderate (4-7)",
    },
    "ayush_parameters": {
        "dupshya": "Vata-Pitta dosha imbalance",
        "desha": "Urban, dry climate",
        "bala": "Moderate physical strength",
        "kala": "Symptoms worsen in the monsoon season",
        "anala_agni": "Manda Agni (weak, sluggish digestive fire)",
        "prakriti": "Vata-Pitta",
        "vaya": "Adult (32 years)",
        "sattva": "Anxious, mildly stressed temperament",
        "satmya": "Habituated to a vegetarian, spice-heavy diet",
        "ahara": "Krura Koshtha (hard/costive bowel), irregular meal timing",
    },
    "ocr_data": {},
    "trigger_red_flag": False,
}

CASE_3_OCR_REVIEW = {
    "session_id": "demo-case-3-ocr-review",
    "abha_id": "12-3456-7890-0003",
    "language": "English",
    "consent_given": True,
    "status": "transferred_to_doctor",
    "chief_complaint": "Follow-up for hypertension and bilateral knee joint pain",
    "socrates": {
        "site": "Bilateral knee joints",
        "onset": "Chronic, over several years",
        "character": "Aching",
        "radiation": "None",
        "associations": "Mild swelling",
        "timing": "Worse in the morning, improves through the day",
        "exacerbating_relieving": "Worse in cold weather, better with gentle movement",
        "severity": "Mild to moderate (3-5)",
    },
    # Deliberately partial: 45M-style completed forms are rare in the wild,
    # and an incomplete AYUSH profile is exactly what should light up red
    # ("missing from intake") on the doctor dashboard next to case 3's
    # yellow OCR flags -- a good demo of both highlight colors at once.
    "ayush_parameters": {
        "dupshya": "Vata dosha imbalance",
        "desha": "Urban, temperate climate",
        "bala": "Average physical strength",
        "prakriti": "Vata",
        "vaya": "Elderly (58 years)",
    },
    "ocr_data": {
        "patient_name": "Suresh Kumar",
        "prescribed_medicines": [
            {"name": "Amlodipine", "dosage": "5mg", "frequency": "OD", "duration": "30 days"},
            # Garbled handwriting-OCR read -- deliberately low-confidence.
            {"name": "T�b Glimipr�de", "dosage": "1mg", "frequency": "BD", "duration": "�5 days"},
            # Illegible entirely -- name never resolved by OCR.
            {"name": "", "dosage": None, "frequency": "SOS", "duration": None},
        ],
        "ayush_formulations": [
            {"herb_or_churn": "Triphala Churna", "anupana": "Warm water", "timing": "Night (HS)"},
            {"herb_or_churn": "Ashw�g4ndha", "anupana": None, "timing": "��"},
        ],
        "vitals_noted": {
            "Blood Pressure": "150/95 mmHg",
            "Pulse": "8O bpm",  # OCR misread '0' as letter 'O'
            "Weight": "",  # illegible on the scan
        },
        "raw_text_extracted": (
            "Dr. R. Mehta, MBBS MD\n"
            "Date: ..\n"
            "Rx:\n"
            "1) Amlodipine 5mg OD x 30 days\n"
            "2) T�b Glimipr�de 1mg BD x �5 days\n"
            "3) _______ SOS\n"
            "Advice: Triphala Churna 1 tsp HS c warm water\n"
            "Ashw�g4ndha ��\n"
            "BP 150/95, P 8O, Wt: ___\n"
        ),
    },
    "trigger_red_flag": False,
}

DEMO_CASES = [CASE_1_CHEST_PAIN, CASE_2_AYURVEDIC_DIGESTIVE, CASE_3_OCR_REVIEW]


async def seed() -> None:
    print("Seeding PrakritiDesk demo data...\n")
    for case in DEMO_CASES:
        record = await save_or_update_session(case)
        red_flag_note = " [RED FLAG]" if record["trigger_red_flag"] else ""
        print(f"  - {record['session_id']}: {record['chief_complaint']}{red_flag_note}")

    print(f"\nSeeded {len(DEMO_CASES)} case(s), all with status='transferred_to_doctor'.")
    print("They will appear immediately in GET /queue/active and the doctor dashboard.")


if __name__ == "__main__":
    asyncio.run(seed())
