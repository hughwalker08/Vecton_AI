"""
Tests for the pure, Gemini-call-free parts of app.services.generation:
multi-turn history handling, and prompt-assembly (how the attachment and
jurisdiction addenda get folded into the content sent to the model).

Gemini-calling behaviour (retries, key rotation) is covered separately in
test_generation_key_rotation.py.
"""

from app.services import generation as gen
from app.services.generation import MAX_HISTORY_MESSAGES, _history_contents


def test_history_contents_maps_user_and_assistant_to_gemini_roles():
    history = [
        {"role": "user", "text": "What ceiling height do we need in bedrooms?"},
        {"role": "assistant", "text": "Minimum 2.4m per H1D4."},
    ]

    contents = _history_contents(history)

    assert [c.role for c in contents] == ["user", "model"]
    assert [c.parts[0].text for c in contents] == [
        "What ceiling height do we need in bedrooms?",
        "Minimum 2.4m per H1D4.",
    ]


def test_history_contents_trims_to_the_most_recent_max_history_messages():
    history = [{"role": "user", "text": f"turn {i}"} for i in range(MAX_HISTORY_MESSAGES + 10)]

    contents = _history_contents(history)

    assert len(contents) == MAX_HISTORY_MESSAGES
    # The trailing (most recent) turns are kept, not the earliest ones.
    assert contents[-1].parts[0].text == f"turn {MAX_HISTORY_MESSAGES + 9}"


def test_history_contents_skips_turns_with_empty_or_missing_text():
    history = [
        {"role": "user", "text": "A real question."},
        {"role": "assistant", "text": ""},
        {"role": "user"},
    ]

    contents = _history_contents(history)

    assert len(contents) == 1
    assert contents[0].parts[0].text == "A real question."


def test_history_contents_empty_or_none_returns_no_content():
    assert _history_contents([]) == []
    assert _history_contents(None) == []


def _chunk(**overrides):
    base = {"clause_id": "H1D4", "doc": "NCC 2025 Volume Two", "text": "Footings must comply."}
    return {**base, **overrides}


def test_build_user_content_without_attachment_has_no_attachment_block():
    content = gen._build_user_content("What about footings?", [_chunk()])

    assert "ATTACHED DOCUMENT" not in content
    assert "CONTEXT:" in content
    assert "QUESTION: What about footings?" in content


def test_build_user_content_includes_named_attachment():
    content = gen._build_user_content(
        "Does my plan comply?", [_chunk()], "site-plan.pdf", "All footings are 300mm deep."
    )

    assert "ATTACHED DOCUMENT (site-plan.pdf):" in content
    assert "All footings are 300mm deep." in content


def test_build_user_content_with_no_chunks_says_none_retrieved():
    content = gen._build_user_content("A question", [])

    assert "(none retrieved)" in content


def test_build_system_instruction_without_extras_is_the_base_instruction():
    instruction = gen._build_system_instruction(None)

    assert instruction == gen.SYSTEM_INSTRUCTION


def test_build_system_instruction_adds_jurisdiction_addendum():
    instruction = gen._build_system_instruction("NSW")

    assert "jurisdiction: NSW" in instruction


def test_build_system_instruction_adds_attachment_addendum_naming_the_document():
    instruction = gen._build_system_instruction(None, "site-plan.pdf")

    assert 'named "site-plan.pdf"' in instruction
    assert "never as a code citation" in instruction
