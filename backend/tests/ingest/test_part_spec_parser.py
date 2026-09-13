from app.ingest.part_spec_parser import parse_part_or_spec, parse_part_variation
from tests.ingest.conftest import parse


def test_parse_part_or_spec_reads_intro_content(make_corpus):
    root = parse(
        """
        <part num="H1" state="">
          <title>Structure</title>
          <intro-part>
            <content>
              <p>This Part sets out structural requirements.</p>
            </content>
          </intro-part>
        </part>
        """
    )
    corpus = make_corpus(root)

    chunk = parse_part_or_spec(root, corpus)

    assert chunk.node_type == "part"
    assert chunk.clause_id == "H1"
    assert chunk.heading == "H1 Structure"
    assert chunk.text == "This Part sets out structural requirements."
    assert chunk.jurisdictions is None  # state="" -> national


def test_parse_part_or_spec_falls_back_to_title_with_no_intro(make_corpus):
    root = parse('<specification num="10"><title>Fire hazard properties</title></specification>')
    corpus = make_corpus(root)

    chunk = parse_part_or_spec(root, corpus)

    assert chunk.node_type == "specification"
    assert chunk.text == "Fire hazard properties"


def test_parse_part_or_spec_carries_a_jurisdiction(make_corpus):
    root = parse('<part num="H1" state="TAS"><title>Structure</title></part>')
    corpus = make_corpus(root)

    chunk = parse_part_or_spec(root, corpus)

    assert chunk.jurisdictions == ["TAS"]


def test_parse_part_variation_builds_a_note_chunk(make_corpus):
    root = parse(
        """
        <part-variation id="_pv1" num="H1" state="TAS" type="DELETE">
          <content><p>This Part does not apply in Tasmania.</p></content>
        </part-variation>
        """
    )
    corpus = make_corpus(root)

    chunk = parse_part_variation(root, corpus)

    assert chunk.id == "pv1"
    assert chunk.node_type == "note"
    assert chunk.clause_id == "H1"
    assert chunk.heading == "Part H1 variation (TAS)"
    assert chunk.text == "This Part does not apply in Tasmania."
    assert chunk.jurisdictions == ["TAS"]
    assert chunk.applicability_note == "DELETE"


def test_parse_part_variation_with_no_num_uses_generic_heading(make_corpus):
    root = parse('<part-variation id="_pv2" state="NT" type="REPLACE"><content/></part-variation>')
    corpus = make_corpus(root)

    chunk = parse_part_variation(root, corpus)

    assert chunk.heading == "Part variation (NT)"
