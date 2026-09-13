from app.ingest.housing_citations import build_number_index, extract_bare_housing_citations
from tests.ingest.conftest import parse


def test_build_number_index_covers_part_clause_table_figure():
    root = parse(
        """
        <ncc-volume>
          <part num="9.6" id="_p1"/>
          <clause id="_c1"><sptc>10.8</sptc></clause>
          <table-reference num="3.1" id="_t1"/>
          <image-reference num="11.2" id="_i1"/>
        </ncc-volume>
        """
    )

    index = build_number_index(root)

    assert index["part"]["9.6"].get("id") == "_p1"
    assert index["clause"]["10.8"].get("id") == "_c1"
    assert index["table"]["3.1"].get("id") == "_t1"
    assert index["figure"]["11.2"].get("id") == "_i1"


def test_build_number_index_drops_ambiguous_duplicate_numbers():
    # Documented edge case: a Part number reused between the national
    # provisions and the state-schedule appendix -- resolving to either
    # would be a guess, so neither is kept.
    root = parse('<ncc-volume><part num="4" id="_p1"/><part num="4" id="_p2"/></ncc-volume>')

    index = build_number_index(root)

    assert index["part"] == {}


def test_extract_bare_housing_citations_matches_part_and_table_mentions():
    text = (
        "Compliance with WA Part 9.6 of the ABCB Housing Provisions satisfies this "
        "clause. See also Table 3.1(a) of the Housing Provisions."
    )
    index = build_number_index(
        parse(
            '<ncc-volume><part num="9.6" id="_p1"/>'
            '<table-reference num="3.1" id="_t1"/></ncc-volume>'
        )
    )

    citations = extract_bare_housing_citations(text, index)

    assert citations == [
        {
            "kind": "housing",
            "clause_id": "Part 9.6",
            "raw_text": "WA Part 9.6 of the ABCB Housing Provisions",
            "chunk_id": None,
            "_target_guid": "_p1",
            "_target_corpus": "housing",
        },
        {
            "kind": "housing",
            "clause_id": "Table 3.1(a)",
            "raw_text": "Table 3.1(a) of the Housing Provisions",
            "chunk_id": None,
            "_target_guid": "_t1",
            "_target_corpus": "housing",
        },
    ]


def test_extract_bare_housing_citations_unresolvable_number_still_returned_with_null_guid():
    text = "See Part 99 of the Housing Provisions."
    index = build_number_index(parse("<ncc-volume/>"))

    citations = extract_bare_housing_citations(text, index)

    assert citations[0]["_target_guid"] is None


def test_extract_bare_housing_citations_deduplicates_identical_mentions():
    text = "See Part 9.6 of the Housing Provisions. Also see Part 9.6 of the Housing Provisions."
    index = build_number_index(parse("<ncc-volume/>"))

    citations = extract_bare_housing_citations(text, index)

    assert len(citations) == 1


def test_extract_bare_housing_citations_ignores_bare_section_mentions():
    # "section" is deliberately excluded from _LABEL_TO_INDEX_KEY (not a
    # unique, resolvable number) -- still captured, but never resolved.
    text = "See Section 4 of the ABCB Housing Provisions."
    index = build_number_index(parse("<ncc-volume/>"))

    citations = extract_bare_housing_citations(text, index)

    assert citations[0]["clause_id"] == "Section 4"
    assert citations[0]["_target_guid"] is None
