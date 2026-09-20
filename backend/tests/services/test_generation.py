"""
Tests for the pure prompt-assembly helpers in app.services.generation.

Gemini-calling behaviour (retries, key rotation) is covered separately in
test_generation_key_rotation.py; this file only checks how the attachment
and jurisdiction addenda get folded into the content sent to the model.
"""

from app.services import generation as gen


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
