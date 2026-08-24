"""Deterministic red-flag safety net.

This is a keyword-based first line of defense that runs on every turn
BEFORE any LLM call. It must never depend on the LLM being available or
behaving correctly, since a missed emergency is the single worst failure
mode of this system.

The LLM extraction step (see llm.py) also returns a secondary red-flag
opinion; the two are OR-ed together in graph.py so either layer catching
a case is enough to trigger the alert.
"""
from typing import Optional, Tuple

# Each tuple is (reason_shown_to_staff, keywords/phrases that trigger it).
# Keep phrases lowercase; matching is done on a lowercased, whitespace-
# normalized copy of the patient's text.
RED_FLAG_PATTERNS: list[Tuple[str, list[str]]] = [
    (
        "Possible acute coronary event (chest pain with radiation/associated symptoms)",
        [
            "chest pain radiating to arm",
            "chest pain radiating to my arm",
            "chest pain going to my arm",
            "crushing chest pain",
            "pain in chest and left arm",
            "chest pain and jaw pain",
            "chest pain and sweating",
        ],
    ),
    (
        "Sudden severe breathlessness",
        [
            "can't breathe",
            "cannot breathe",
            "can't catch my breath",
            "gasping for air",
            "sudden breathlessness",
            "suddenly breathless",
            "severe breathlessness",
            "choking",
        ],
    ),
    (
        "Possible stroke (unilateral weakness / slurred speech / facial droop)",
        [
            "slurred speech",
            "can't speak properly",
            "face drooping",
            "one side of my face",
            "weakness on one side",
            "can't move my arm",
            "can't move my leg",
            "sudden weakness",
            "sudden numbness",
        ],
    ),
    (
        "Sudden vision loss",
        [
            "sudden loss of vision",
            "suddenly can't see",
            "went blind",
            "lost vision suddenly",
        ],
    ),
    (
        "Severe uncontrolled bleeding",
        [
            "bleeding heavily",
            "won't stop bleeding",
            "severe bleeding",
        ],
    ),
    (
        "Loss of consciousness / seizure",
        [
            "passed out",
            "lost consciousness",
            "fainted",
            "had a seizure",
            "fitting",
        ],
    ),
]


def check_red_flags(text: str) -> Optional[Tuple[str, str]]:
    """Return (reason, matched_phrase) if a red-flag pattern is found, else None."""
    normalized = " ".join(text.lower().split())
    for reason, phrases in RED_FLAG_PATTERNS:
        for phrase in phrases:
            if phrase in normalized:
                return reason, phrase
    return None
