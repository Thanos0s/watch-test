"""LangGraph + Groq intake engine for PrakritiDesk.

Two-node workflow, run per conversational turn:

    extract_entities_node -> generate_prompt_node -> END

`extract_entities_node` pulls SOCRATES (HPI) and Dashavidha Pariksha (AYUSH)
clinical parameters out of the patient's free-text answer via Groq, and
determines whether the answer describes a medical emergency. A fast,
deterministic keyword scan (see red_flags.py) runs first on every turn as a
safety net that does not depend on the LLM being available or correct; if it
already finds an emergency phrase, the Groq extraction call is skipped
entirely.

`generate_prompt_node` picks the next unfilled clinical slot (in a fixed
ontology order) and asks Groq to phrase a single short spoken question plus
3-4 kiosk touch-button options for it. The LLM only ever phrases the
question for a slot chosen by the deterministic ontology walk -- it never
decides what topic to ask about next, which is what keeps the dialogue
ontology-constrained rather than open-ended.

This module never diagnoses, recommends medication, or suggests treatment.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional, TypedDict

from dotenv import load_dotenv
from groq import AsyncGroq
from langgraph.graph import END, StateGraph

from .red_flags import check_red_flags

load_dotenv()

logger = logging.getLogger("prakritidesk.graph")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

_groq_client: Optional[AsyncGroq] = None


def get_groq_client() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        _groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq_client


# --------------------------------------------------------------------------
# State schema
# --------------------------------------------------------------------------

class IntakeState(TypedDict):
    session_id: str
    selected_language: str
    user_input: str
    chief_complaint: Optional[str]
    socrates: Dict[str, Any]
    ayush_parameters: Dict[str, Any]
    audio_prompt_text: Optional[str]
    touch_options: List[str]
    trigger_red_flag: bool
    red_flag_reason: Optional[str]
    is_complete: bool


SOCRATES_FIELDS = [
    "site",
    "onset",
    "character",
    "radiation",
    "associations",
    "timing",
    "exacerbating_relieving",
    "severity",
]

# Full Dashavidha Pariksha (the ten-fold Ayurvedic clinical examination).
AYUSH_FIELDS = [
    "dupshya",
    "desha",
    "bala",
    "kala",
    "anala_agni",
    "prakriti",
    "vaya",
    "sattva",
    "satmya",
    "ahara",
]

# Ontology walk order: chief complaint, then HPI/SOCRATES, then AYUSH
# (Dashavidha Pariksha) parameters. This fixed order is what keeps the
# interview a decision tree instead of an LLM freely choosing topics.
SLOT_ORDER = ["chief_complaint"] + SOCRATES_FIELDS + AYUSH_FIELDS

SLOT_DESCRIPTIONS = {
    "chief_complaint": "the patient's main presenting complaint, in a few words",
    "site": "SOCRATES - Site: exact anatomical location of the symptom",
    "onset": "SOCRATES - Onset: when/how the symptom started",
    "character": "SOCRATES - Character: what the symptom feels like (e.g. sharp, dull, burning)",
    "radiation": "SOCRATES - Radiation: whether/where the symptom spreads",
    "associations": "SOCRATES - Associations: other symptoms occurring alongside it",
    "timing": "SOCRATES - Timing: constant, intermittent, time-of-day pattern",
    "exacerbating_relieving": "SOCRATES - Exacerbating/Relieving factors: what makes it better or worse",
    "severity": "SOCRATES - Severity: how bad it is, e.g. on a 1-10 scale",
    "dupshya": "Dashavidha Pariksha - Dushya: the dosha(s)/dhatu(s) currently in an imbalanced state",
    "desha": "Dashavidha Pariksha - Desha: the patient's habitat/climate (e.g. dry-cold, hot-humid, temperate)",
    "bala": "Dashavidha Pariksha - Bala: the patient's overall physical strength/stamina",
    "kala": "Dashavidha Pariksha - Kala: the season/time pattern linked to the complaint",
    "anala_agni": "Dashavidha Pariksha - Anala (Agni): digestive fire type (Vishamagni/irregular, Tikshnagni/sharp-excessive, Mandagni/weak, or Samagni/balanced)",
    "prakriti": "Dashavidha Pariksha - Prakriti: the patient's baseline constitution (Vata, Pitta, Kapha, or a combination)",
    "vaya": "Dashavidha Pariksha - Vaya: the patient's age group (child, adult, elderly)",
    "sattva": "Dashavidha Pariksha - Sattva: the patient's mental temperament/resilience",
    "satmya": "Dashavidha Pariksha - Satmya: habituation/dietary-lifestyle tolerance (what the patient's body is used to)",
    "ahara": "Dashavidha Pariksha - Ahara: dietary habits and bowel (koshtha) pattern",
}

RED_FLAG_PROMPT_TEXT = "Please stay seated. A staff member is being called to see you right now."
RED_FLAG_TOUCH_OPTIONS = ["Call staff now"]

CLOSING_PROMPT_TEXT = "Thank you. Please wait, the doctor will see you shortly."
CLOSING_TOUCH_OPTIONS = ["Done"]

# Static fallback questions, used only if the Groq call in
# generate_prompt_node fails or returns something unusable. Keeping these
# hardcoded (rather than another LLM call) guarantees the interview can
# always make forward progress even during an LLM outage.
FALLBACK_QUESTIONS = {
    "chief_complaint": {
        "audio_prompt_text": "What is bothering you today?",
        "touch_options": ["Pain", "Fever", "Cough/Cold", "Other/Describe"],
    },
    "site": {
        "audio_prompt_text": "Where exactly do you feel it?",
        "touch_options": ["Head", "Chest", "Stomach", "Other/Describe"],
    },
    "onset": {
        "audio_prompt_text": "When did this start?",
        "touch_options": ["Today", "Few days ago", "Weeks ago", "Other/Describe"],
    },
    "character": {
        "audio_prompt_text": "What does it feel like?",
        "touch_options": ["Sharp", "Dull/Aching", "Burning", "Other/Describe"],
    },
    "radiation": {
        "audio_prompt_text": "Does it spread anywhere else?",
        "touch_options": ["No", "To arm", "To back", "Other/Describe"],
    },
    "associations": {
        "audio_prompt_text": "Any other symptoms with it, like nausea or sweating?",
        "touch_options": ["None", "Nausea", "Sweating", "Other/Describe"],
    },
    "timing": {
        "audio_prompt_text": "Is it constant or does it come and go?",
        "touch_options": ["Constant", "Comes and goes", "Only at night", "Other/Describe"],
    },
    "exacerbating_relieving": {
        "audio_prompt_text": "Does anything make it better or worse?",
        "touch_options": ["Worse with movement", "Better with rest", "No change", "Other/Describe"],
    },
    "severity": {
        "audio_prompt_text": "On a scale of 1 to 10, how bad is it?",
        "touch_options": ["Mild (1-3)", "Moderate (4-7)", "Severe (8-10)", "Other/Describe"],
    },
    "dupshya": {
        "audio_prompt_text": "Which dosha feels most out of balance right now?",
        "touch_options": ["Vata", "Pitta", "Kapha", "Other/Describe"],
    },
    "desha": {
        "audio_prompt_text": "What kind of place do you live in?",
        "touch_options": ["Dry/Cold region", "Hot/Humid region", "Moderate climate", "Other/Describe"],
    },
    "bala": {
        "audio_prompt_text": "How would you describe your physical strength?",
        "touch_options": ["Strong", "Average", "Weak", "Other/Describe"],
    },
    "kala": {
        "audio_prompt_text": "Is there a season when this gets worse?",
        "touch_options": ["Summer", "Monsoon", "Winter", "Other/Describe"],
    },
    "anala_agni": {
        "audio_prompt_text": "Is your digestion regular, weak, or excessive?",
        "touch_options": ["Regular", "Weak", "Excessive/Sharp", "Other/Describe"],
    },
    "prakriti": {
        "audio_prompt_text": "What is your body constitution type?",
        "touch_options": ["Vata", "Pitta", "Kapha", "Other/Describe"],
    },
    "vaya": {
        "audio_prompt_text": "What is your age group?",
        "touch_options": ["Child", "Adult", "Elderly", "Other/Describe"],
    },
    "sattva": {
        "audio_prompt_text": "How would you describe your mental strength?",
        "touch_options": ["Calm", "Anxious", "Variable", "Other/Describe"],
    },
    "satmya": {
        "audio_prompt_text": "Are there foods or habits your body is used to?",
        "touch_options": ["Vegetarian", "Non-vegetarian", "Mixed", "Other/Describe"],
    },
    "ahara": {
        "audio_prompt_text": "How are your dietary habits and bowel movements?",
        "touch_options": ["Regular", "Irregular", "Constipated", "Other/Describe"],
    },
}

EXTRACTION_SYSTEM_PROMPT = """You are a clinical intake data-extraction assistant for PrakritiDesk, an OPD kiosk.

You are NOT a doctor. You must NEVER diagnose, suggest medication, or suggest a treatment plan. Your only job is to read the patient's answer and pull out structured facts that are literally present in it.

You will be given the patient's spoken/typed answer and their selected language. Extract, if present, values for these fields:
- chief_complaint: the patient's main presenting complaint, a few words
- socrates.site, socrates.onset, socrates.character, socrates.radiation, socrates.associations, socrates.timing, socrates.exacerbating_relieving, socrates.severity
- ayush_parameters (the full Dashavidha Pariksha, the ten-fold Ayurvedic clinical examination):
  - dupshya: the dosha(s)/dhatu(s) currently in an imbalanced state
  - desha: habitat/climate (e.g. dry-cold, hot-humid, temperate)
  - bala: overall physical strength/stamina
  - kala: season/time pattern linked to the complaint
  - anala_agni: digestive fire type -- one of Vishamagni (irregular), Tikshnagni (sharp/excessive), Mandagni (weak), or Samagni (balanced)
  - prakriti: baseline constitution -- Vata, Pitta, Kapha, or a combination
  - vaya: age group (child, adult, elderly)
  - sattva: mental temperament/resilience
  - satmya: habituation/dietary-lifestyle tolerance (what the patient's body is used to)
  - ahara: dietary habits and bowel (koshtha) pattern

Rules:
- Only extract what the patient actually said. Do not infer or guess values that are not present; leave those fields as null so the system knows to ask a follow-up question for that slot.
- Summarize each extracted value as a short phrase in English, suitable for a clinical record, regardless of the patient's input language.
- Set "red_flag": true ONLY if the patient's answer describes a medical emergency, such as: severe/crushing chest pain (especially radiating to the arm, jaw, or back), sudden severe breathlessness or inability to breathe, signs of stroke (sudden one-sided weakness, slurred speech, facial droop), or sudden loss of vision. Also set it true for any other clearly life-threatening description (e.g. severe uncontrolled bleeding, loss of consciousness, seizure).
- If "red_flag" is true, set "red_flag_reason" to a short clinical phrase describing the emergency. Otherwise set it to null.
- Respond with STRICT JSON only, no markdown, no extra text, matching exactly this shape:
{"chief_complaint": "..." or null, "socrates": {"site": "..." or null, "onset": "..." or null, "character": "..." or null, "radiation": "..." or null, "associations": "..." or null, "timing": "..." or null, "exacerbating_relieving": "..." or null, "severity": "..." or null}, "ayush_parameters": {"dupshya": "..." or null, "desha": "..." or null, "bala": "..." or null, "kala": "..." or null, "anala_agni": "..." or null, "prakriti": "..." or null, "vaya": "..." or null, "sattva": "..." or null, "satmya": "..." or null, "ahara": "..." or null}, "red_flag": true or false, "red_flag_reason": "..." or null}
"""

GENERATION_SYSTEM_PROMPT = """You are a kiosk dialogue writer for PrakritiDesk, an OPD intake system.

You are NOT a doctor. Never diagnose, suggest medication, or suggest treatment. Your only job is to phrase ONE short question about the exact clinical field you are given, plus 3-4 short kiosk touch-button options for it.

Rules:
- Ask about ONLY the field described to you. Do not introduce any other topic.
- The question must be a single short sentence (max ~15 words), simple enough for text-to-speech in the patient's selected language, and asked in English (a downstream translation layer handles localization).
- Provide exactly 3 or 4 short touch_options (each 1-4 words) that are plausible quick answers for that field, and ALWAYS include one final catch-all option worded like "Other/Describe".
- Respond with STRICT JSON only, no markdown, no extra text, matching exactly this shape:
{"audio_prompt_text": "...", "touch_options": ["...", "...", "...", "Other/Describe"]}
"""


def _empty_socrates() -> Dict[str, Any]:
    return {field: None for field in SOCRATES_FIELDS}


def _empty_ayush() -> Dict[str, Any]:
    return {field: None for field in AYUSH_FIELDS}


def _pending_slot(state: IntakeState) -> Optional[str]:
    """First slot in SLOT_ORDER that hasn't been filled yet."""
    if not state.get("chief_complaint"):
        return "chief_complaint"
    socrates = state.get("socrates") or {}
    for field in SOCRATES_FIELDS:
        if not socrates.get(field):
            return field
    ayush = state.get("ayush_parameters") or {}
    for field in AYUSH_FIELDS:
        if not ayush.get(field):
            return field
    return None


async def _call_groq_json(system_prompt: str, user_prompt: str, temperature: float = 0) -> Optional[dict]:
    try:
        client = get_groq_client()
        completion = await client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content
        return json.loads(raw)
    except Exception:
        logger.exception("Groq call failed")
        return None


# --------------------------------------------------------------------------
# Node 1: extract SOCRATES + AYUSH entities from the patient's answer
# --------------------------------------------------------------------------

async def extract_entities_node(state: IntakeState) -> IntakeState:
    keyword_hit = check_red_flags(state["user_input"])
    if keyword_hit:
        reason, _phrase = keyword_hit
        state["trigger_red_flag"] = True
        state["red_flag_reason"] = reason
        return state

    user_prompt = (
        f"Patient's selected language: {state['selected_language']}\n"
        f"Patient's answer: {state['user_input']}"
    )
    # Low but non-zero temperature: keeps extraction close to deterministic
    # (this is a transcription task, not a creative one) while giving the
    # model enough flexibility to correctly parse the wide variety of ways a
    # patient might phrase any of the ten Dashavidha Pariksha parameters.
    parsed = await _call_groq_json(EXTRACTION_SYSTEM_PROMPT, user_prompt, temperature=0.1)

    if parsed is None:
        # Groq unavailable/malformed response: fall back to treating the raw
        # text as the value for whatever slot is currently pending, so the
        # interview can still make forward progress. The deterministic
        # keyword check above still guards against missing an emergency.
        pending = _pending_slot(state)
        if pending == "chief_complaint":
            state["chief_complaint"] = state["user_input"].strip()
        elif pending in SOCRATES_FIELDS:
            state["socrates"][pending] = state["user_input"].strip()
        elif pending in AYUSH_FIELDS:
            state["ayush_parameters"][pending] = state["user_input"].strip()
        return state

    if parsed.get("red_flag"):
        state["trigger_red_flag"] = True
        state["red_flag_reason"] = parsed.get("red_flag_reason") or "LLM flagged a possible emergency"
        return state

    if not state.get("chief_complaint") and parsed.get("chief_complaint"):
        state["chief_complaint"] = str(parsed["chief_complaint"]).strip()

    extracted_socrates = parsed.get("socrates") or {}
    for field in SOCRATES_FIELDS:
        value = extracted_socrates.get(field)
        if value and not state["socrates"].get(field):
            state["socrates"][field] = str(value).strip()

    extracted_ayush = parsed.get("ayush_parameters") or {}
    for field in AYUSH_FIELDS:
        value = extracted_ayush.get(field)
        if value and not state["ayush_parameters"].get(field):
            state["ayush_parameters"][field] = str(value).strip()

    # If nothing at all was extracted for the currently pending slot, fall
    # back to the raw answer so a vague-but-relevant reply still counts.
    pending = _pending_slot(state)
    if pending == "chief_complaint" and not state.get("chief_complaint"):
        state["chief_complaint"] = state["user_input"].strip()
    elif pending in SOCRATES_FIELDS and not state["socrates"].get(pending):
        state["socrates"][pending] = state["user_input"].strip()
    elif pending in AYUSH_FIELDS and not state["ayush_parameters"].get(pending):
        state["ayush_parameters"][pending] = state["user_input"].strip()

    return state


# --------------------------------------------------------------------------
# Node 2: generate the next spoken question + touch options
# --------------------------------------------------------------------------

async def generate_prompt_node(state: IntakeState) -> IntakeState:
    if state["trigger_red_flag"]:
        state["audio_prompt_text"] = RED_FLAG_PROMPT_TEXT
        state["touch_options"] = RED_FLAG_TOUCH_OPTIONS
        state["is_complete"] = False
        return state

    next_slot = _pending_slot(state)
    if next_slot is None:
        state["audio_prompt_text"] = CLOSING_PROMPT_TEXT
        state["touch_options"] = CLOSING_TOUCH_OPTIONS
        state["is_complete"] = True
        return state

    fallback = FALLBACK_QUESTIONS[next_slot]

    user_prompt = (
        f"Field to ask about: {next_slot}\n"
        f"Field meaning: {SLOT_DESCRIPTIONS[next_slot]}\n"
        f"Patient's selected language: {state['selected_language']}"
    )
    parsed = await _call_groq_json(GENERATION_SYSTEM_PROMPT, user_prompt)

    audio_prompt_text = None
    touch_options: List[str] = []

    if parsed:
        candidate_text = str(parsed.get("audio_prompt_text") or "").strip()
        candidate_options = parsed.get("touch_options")
        if (
            candidate_text
            and isinstance(candidate_options, list)
            and 3 <= len(candidate_options) <= 4
            and all(isinstance(opt, str) and opt.strip() for opt in candidate_options)
        ):
            audio_prompt_text = candidate_text
            touch_options = [opt.strip() for opt in candidate_options]

    if not audio_prompt_text or not touch_options:
        # Groq unavailable or returned something malformed/out-of-spec:
        # use the static fallback so the kiosk always gets a valid question.
        audio_prompt_text = fallback["audio_prompt_text"]
        touch_options = fallback["touch_options"]

    state["audio_prompt_text"] = audio_prompt_text
    state["touch_options"] = touch_options
    state["is_complete"] = False
    return state


# --------------------------------------------------------------------------
# Graph assembly
# --------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(IntakeState)
    graph.add_node("extract_entities_node", extract_entities_node)
    graph.add_node("generate_prompt_node", generate_prompt_node)

    graph.set_entry_point("extract_entities_node")
    graph.add_edge("extract_entities_node", "generate_prompt_node")
    graph.add_edge("generate_prompt_node", END)
    return graph.compile()


_compiled_graph = None


def get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


async def run_turn(payload: dict) -> dict:
    """Entry point for a single conversational turn.

    `payload` is expected to contain: session_id, user_input,
    selected_language, and optionally the clinical state carried over from
    the previous turn (chief_complaint, socrates, ayush_parameters).
    Returns a plain dict matching the kiosk API's response contract.
    """
    initial: IntakeState = {
        "session_id": payload["session_id"],
        "selected_language": payload.get("selected_language", "Hindi"),
        "user_input": payload["user_input"],
        "chief_complaint": payload.get("chief_complaint"),
        "socrates": {**_empty_socrates(), **(payload.get("socrates") or {})},
        "ayush_parameters": {**_empty_ayush(), **(payload.get("ayush_parameters") or {})},
        "audio_prompt_text": None,
        "touch_options": [],
        "trigger_red_flag": False,
        "red_flag_reason": None,
        "is_complete": False,
    }

    result: IntakeState = await get_compiled_graph().ainvoke(initial)

    return {
        "audio_prompt_text": result["audio_prompt_text"],
        "touch_options": result["touch_options"],
        "updated_clinical_state": {
            "chief_complaint": result["chief_complaint"],
            "socrates": result["socrates"],
            "ayush_parameters": result["ayush_parameters"],
        },
        "is_complete": result["is_complete"],
        "trigger_red_flag": result["trigger_red_flag"],
        "red_flag_reason": result["red_flag_reason"],
    }
