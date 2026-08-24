"""Unit tests for app/red_flags.py -- the deterministic, keyword-based
emergency detector that runs before any LLM call in the intake flow.

Pure-function tests: no HTTP client, no database, no network. These should
run in milliseconds and never flake.
"""
import pytest

from app.red_flags import check_red_flags


class TestEmergencySymptomsTriggerRedFlag:
    """One case per RED_FLAG_PATTERNS category in app/red_flags.py."""

    @pytest.mark.parametrize(
        "patient_text,expected_reason_keyword",
        [
            ("I have chest pain radiating to my arm", "coronary"),
            ("Sudden crushing chest pain since this morning", "coronary"),
            ("I can't breathe properly", "breathlessness"),
            ("Suddenly breathless and gasping for air", "breathlessness"),
            ("I have slurred speech and face drooping since an hour ago", "stroke"),
            ("Sudden weakness on one side of my body", "stroke"),
            ("I had sudden loss of vision in my left eye", "vision"),
            ("The wound won't stop bleeding", "bleeding"),
            ("I fainted and lost consciousness for a minute", "consciousness"),
            ("He had a seizure just now", "consciousness"),
        ],
    )
    def test_known_emergency_phrase_triggers_red_flag(self, patient_text, expected_reason_keyword):
        result = check_red_flags(patient_text)
        assert result is not None, f"Expected a red flag for: {patient_text!r}"
        reason, matched_phrase = result
        assert expected_reason_keyword.lower() in reason.lower()
        assert matched_phrase in patient_text.lower()

    def test_matching_is_case_insensitive(self):
        result = check_red_flags("CHEST PAIN RADIATING TO MY ARM, please help")
        assert result is not None

    def test_matching_tolerates_extra_whitespace(self):
        result = check_red_flags("chest   pain    radiating   to   my   arm")
        assert result is not None

    def test_phrase_embedded_in_a_longer_sentence_still_matches(self):
        result = check_red_flags(
            "Since about an hour ago I have had crushing chest pain and I feel very unwell"
        )
        assert result is not None


class TestNormalSymptomsDoNotTriggerRedFlag:
    @pytest.mark.parametrize(
        "patient_text",
        [
            "I have a mild headache since this morning",
            "My stomach hurts a little after eating spicy food",
            "I have a runny nose and a cough",
            "I feel a bit tired and weak today",  # "weak" alone must NOT match "sudden weakness"
            "I have some back pain when I bend down",
            "I feel nauseous but haven't vomited",
            "My knee has been aching for a few days",
        ],
    )
    def test_ordinary_complaint_does_not_trigger_red_flag(self, patient_text):
        assert check_red_flags(patient_text) is None

    def test_empty_string_does_not_crash_and_returns_none(self):
        assert check_red_flags("") is None

    def test_whitespace_only_string_returns_none(self):
        assert check_red_flags("   \n\t  ") is None

    def test_unrelated_use_of_a_similar_word_does_not_false_positive(self):
        # "breathless with excitement" is a common English idiom that must
        # NOT be conflated with a medical emergency -- this specific phrase
        # isn't a listed pattern, only "suddenly breathless" is.
        assert check_red_flags("I was breathless with excitement at the news") is None
