"""
Tests for app.services.glossary.

The DB read in load_terms() is replaced by a fake engine; every other test
sets the glossary directly with _set_terms() (tests/conftest.py preloads an
empty one so nothing here ever reaches a real DB).
"""

from __future__ import annotations

from app.services import glossary

TERMS = {
    "Habitable room": "A room used for normal domestic activities.",
    "External wall": "An outer wall of a building which is not a common wall.",
    "Required": "Required by the NCC.",
    "FRL": "Fire Resistance Level",
    "AS": "Australian Standard",
    "C": "Constant for conductance",
}


def _chunk(*defined_terms):
    return {"clause_id": "H1D4", "defined_terms": list(defined_terms)}


def _terms(definitions):
    return [d["term"] for d in definitions]


def test_definitions_for_attaches_each_chunks_defined_terms():
    glossary._set_terms(TERMS)

    definitions = glossary.definitions_for([_chunk("External wall"), _chunk("Habitable room")])

    assert definitions == [
        {"term": "External wall", "definition": TERMS["External wall"]},
        {"term": "Habitable room", "definition": TERMS["Habitable room"]},
    ]


def test_definitions_for_puts_question_matches_before_chunk_terms():
    glossary._set_terms(TERMS)

    definitions = glossary.definitions_for(
        [_chunk("External wall")], "What counts as a habitable room?"
    )

    assert _terms(definitions) == ["Habitable room", "External wall"]


def test_definitions_for_dedupes_across_question_and_chunks():
    glossary._set_terms(TERMS)

    definitions = glossary.definitions_for(
        [_chunk("Habitable room", "External wall"), _chunk("Habitable room")],
        "habitable room ceiling height",
    )

    assert _terms(definitions) == ["Habitable room", "External wall"]


def test_definitions_for_skips_terms_with_no_glossary_entry():
    glossary._set_terms(TERMS)

    assert glossary.definitions_for([_chunk("Not a defined term")]) == []


def test_definitions_for_caps_at_max_definitions(monkeypatch):
    monkeypatch.setattr(glossary, "MAX_DEFINITIONS", 2)
    glossary._set_terms(TERMS)

    definitions = glossary.definitions_for([_chunk("Habitable room", "External wall", "Required")])

    assert _terms(definitions) == ["Habitable room", "External wall"]


def test_definitions_for_handles_chunks_without_defined_terms():
    glossary._set_terms(TERMS)

    assert glossary.definitions_for([{"clause_id": "H1D4"}, _chunk()]) == []


def test_question_matching_is_whole_word_only():
    glossary._set_terms(TERMS)

    # "Required" must not fire inside "requirement".
    assert glossary.definitions_for([], "What is the requirement here?") == []


def test_abbreviations_match_the_question_case_sensitively():
    glossary._set_terms(TERMS)

    assert _terms(glossary.definitions_for([], "What FRL does it need?")) == ["FRL"]
    # "as" is an ordinary word here, not the AS abbreviation.
    assert glossary.definitions_for([], "Is brick as good as timber?") == []


def test_single_character_symbols_never_match_the_question():
    glossary._set_terms(TERMS)

    assert glossary.definitions_for([], "Class C building") == []


def test_definitions_for_returns_nothing_when_glossary_is_empty():
    assert glossary.definitions_for([_chunk("Habitable room")], "habitable room") == []


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _stmt):
        rows = self._rows

        class _Result:
            def all(self):
                return rows

        return _Result()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeEngine:
    def __init__(self, rows=(), error=None):
        self._rows = list(rows)
        self._error = error
        self.connects = 0

    def connect(self):
        self.connects += 1
        if self._error:
            raise self._error
        return _FakeConn(self._rows)


def test_load_terms_reads_the_db_once_and_caches(monkeypatch):
    glossary._terms = None
    engine = _FakeEngine(rows=[("Habitable room", "A room."), ("FRL", "Fire Resistance Level")])
    monkeypatch.setattr(glossary, "engine", engine)

    assert glossary.load_terms() == {"Habitable room": "A room.", "FRL": "Fire Resistance Level"}
    glossary.load_terms()

    assert engine.connects == 1


def test_load_terms_keeps_the_first_entry_for_a_repeated_term(monkeypatch):
    glossary._terms = None
    monkeypatch.setattr(glossary, "engine", _FakeEngine(rows=[("Window", "first"), ("Window", "second")]))

    assert glossary.load_terms() == {"Window": "first"}


def test_load_terms_failure_returns_empty_and_retries_next_call(monkeypatch):
    glossary._terms = None
    failing = _FakeEngine(error=RuntimeError("db down"))
    monkeypatch.setattr(glossary, "engine", failing)

    assert glossary.load_terms() == {}
    assert glossary.definitions_for([_chunk("Habitable room")]) == []

    monkeypatch.setattr(glossary, "engine", _FakeEngine(rows=[("Habitable room", "A room.")]))
    assert glossary.load_terms() == {"Habitable room": "A room."}


REQUEST_TERMS = {
    "Accredited Testing Laboratory": "One of the following: (a) a NATA-accredited organisation.",
    "Flashover": "The sudden spread of fire.",
    "Going": "The horizontal dimension of a tread.",
    "NATA": "National Association of Testing Authorities.",
    "NCC": "National Construction Code.",
    "Performance Requirement": "A requirement that states the level of performance.",
}


def test_ordinary_multi_word_terms_match_in_any_case():
    glossary._set_terms(REQUEST_TERMS)

    # The NCC capitalises every word; people type it in lowercase.
    assert _terms(glossary.definitions_for([], "an accredited testing laboratory")) == ["Accredited Testing Laboratory"]
    assert _terms(glossary.definitions_for([], "performance requirement")) == ["Performance Requirement"]


def test_all_caps_terms_stay_case_sensitive():
    glossary._set_terms(REQUEST_TERMS)

    assert _terms(glossary.definitions_for([], "Who is NATA?")) == ["NATA"]
    assert glossary.definitions_for([], "the nata of the matter") == []


def test_is_abbreviation_separates_acronyms_from_capitalised_wording():
    assert glossary._is_abbreviation("FRL")
    assert glossary._is_abbreviation("AS")
    assert glossary._is_abbreviation("NATA")
    assert glossary._is_abbreviation("NCC")
    assert not glossary._is_abbreviation("Accredited Testing Laboratory")
    assert not glossary._is_abbreviation("Habitable room")
    assert not glossary._is_abbreviation("U-Value")


def test_definitions_for_request_answers_direct_definition_requests():
    glossary._set_terms(REQUEST_TERMS)

    for question in [
        'What does the NCC mean by an "accredited testing laboratory"?',
        "What is the definition of an accredited testing laboratory?",
        "Define flashover.",
        "What does flashover mean?",
        "what is a flashover",
        "What does 'performance requirement' mean?",
    ]:
        assert glossary.definitions_for_request(question), question


def test_definitions_for_request_names_the_term_not_the_ncc():
    glossary._set_terms(REQUEST_TERMS)

    found = glossary.definitions_for_request('What does the NCC mean by an "accredited testing laboratory"?')

    # "the NCC mean by ..." makes NCC the subject of "mean", not the term being defined.
    assert _terms(found) == ["Accredited Testing Laboratory"]
    assert _terms(glossary.definitions_for_request("What does NCC mean?")) == ["NCC"]


def test_definitions_for_request_ignores_glossary_words_that_are_not_being_defined():
    glossary._set_terms(REQUEST_TERMS)

    for question in [
        "What does clause H9Z7 of the NCC say?",
        "What is the going rate for a builder in Sydney?",
        "What does the going rate mean for builders?",
        "Who is the Accredited Testing Laboratory for my windows?",
        "What is the best way to cook a medium-rare steak?",
        "Tell me about the Brisbane City Plan.",
    ]:
        assert glossary.definitions_for_request(question) == [], question


def test_definitions_for_request_returns_nothing_when_glossary_is_empty():
    assert glossary.definitions_for_request("What does flashover mean?") == []
