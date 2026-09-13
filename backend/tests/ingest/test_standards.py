from app.ingest.standards import (
    build_standards_lookup,
    extract_standard_mentions,
    normalize_standard_number,
)
from tests.ingest.conftest import parse


def test_extract_standard_mentions_finds_as_and_as_nzs_forms():
    text = (
        "Smoke alarms must comply with AS 3786 and be wired in accordance with "
        "AS/NZS 3000. See also AS1684.2 for framing."
    )

    assert extract_standard_mentions(text) == ["AS 3786", "AS/NZS 3000", "AS1684.2"]


def test_extract_standard_mentions_deduplicates_repeated_mentions():
    text = "Comply with AS 1530.4. Testing to AS 1530.4 is required."

    assert extract_standard_mentions(text) == ["AS 1530.4"]


def test_extract_standard_mentions_with_no_mentions_is_empty():
    assert extract_standard_mentions("No standards mentioned here.") == []


def test_normalize_standard_number_converts_part_wording_to_a_dot():
    # Note: the substitution only swallows "Part 2" itself, not the space
    # before it, so this doesn't come out matching the no-space form
    # extract_standard_mentions() would produce for the same standard
    # ("AS1684.2") -- documenting current behaviour, not asserting it's right.
    assert normalize_standard_number("AS 1684 Part 2") == "AS 1684 .2"


def test_normalize_standard_number_collapses_spaces_around_the_slash():
    assert normalize_standard_number("AS / NZS 3000") == "AS/NZS 3000"


def test_build_standards_lookup_only_reads_schedule_of_referenced_documents_tables():
    root = parse(
        """
        <ncc-volume>
          <table-reference>
            <title>Schedule of referenced documents</title>
            <table>
              <tbody>
                <tr>
                  <td>AS 1684.2</td><td>2010</td><td>Residential timber-framed construction</td>
                </tr>
              </tbody>
            </table>
          </table-reference>
          <table-reference>
            <title>Some other table</title>
            <table>
              <tbody>
                <tr><td>Not a standard</td><td>2020</td><td>Ignore me</td></tr>
              </tbody>
            </table>
          </table-reference>
        </ncc-volume>
        """
    )

    lookup = build_standards_lookup(root)

    assert list(lookup.keys()) == ["AS 1684.2"]
    assert lookup["AS 1684.2"] == {
        "standard": "AS 1684.2",
        "date": "2010",
        "title": "Residential timber-framed construction",
    }


def test_build_standards_lookup_skips_rows_with_too_few_cells():
    root = parse(
        """
        <table-reference>
          <title>Schedule of referenced documents</title>
          <table>
            <tbody>
              <tr><td>AS 1684.2</td><td>2010</td></tr>
            </tbody>
          </table>
        </table-reference>
        """
    )

    assert build_standards_lookup(root) == {}
