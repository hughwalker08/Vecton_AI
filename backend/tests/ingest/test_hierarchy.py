from app.ingest.hierarchy import ancestor_path
from tests.ingest.conftest import parse


def test_ancestor_path_walks_section_and_part_ancestors_in_document_order():
    root = parse(
        """
        <ncc-volume>
          <ncc-section num="Section H">
            <title>Housing provisions</title>
            <part num="H1">
              <title>Structure</title>
              <subtopic>
                <clause id="_c1">
                  <sptc>H1D4</sptc>
                </clause>
              </subtopic>
            </part>
          </ncc-section>
        </ncc-volume>
        """
    )
    clause = root.find(".//clause")

    path = ancestor_path("NCC 2025 Volume Two", clause)

    assert path == [
        "NCC 2025 Volume Two",
        "Section H Housing provisions",
        "H1 Structure",
    ]


def test_ancestor_path_skips_ancestors_with_no_num_or_title():
    root = parse(
        """
        <ncc-volume>
          <part>
            <subtopic>
              <clause id="_c1"/>
            </subtopic>
          </part>
        </ncc-volume>
        """
    )
    clause = root.find(".//clause")

    # A <part> with neither num nor title contributes no label -- only the
    # doc label itself should come back.
    assert ancestor_path("NCC 2025 Volume Two", clause) == ["NCC 2025 Volume Two"]


def test_ancestor_path_for_specification_ancestor():
    root = parse(
        """
        <ncc-volume>
          <specification num="10">
            <title>Fire hazard properties</title>
            <clause id="_c1"/>
          </specification>
        </ncc-volume>
        """
    )
    clause = root.find(".//clause")

    assert ancestor_path("NCC 2025 Volume Two", clause) == [
        "NCC 2025 Volume Two",
        "10 Fire hazard properties",
    ]


def test_ancestor_path_with_no_matching_ancestors_is_just_the_doc_label():
    root = parse("<ncc-volume><subtopic><clause id='_c1'/></subtopic></ncc-volume>")
    clause = root.find(".//clause")

    assert ancestor_path("NCC 2025 Volume Two", clause) == ["NCC 2025 Volume Two"]
