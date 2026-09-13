from app.ingest.glossary_parser import glossary_term, parse_glossary_file
from tests.ingest.conftest import parse


def test_glossary_term_reads_the_glossterm_child():
    el = parse("<glossentry><glossterm>Habitable room</glossterm></glossentry>")

    assert glossary_term(el) == "Habitable room"


def test_parse_glossary_file_builds_a_glossary_chunk(make_corpus):
    root = parse(
        """
        <ncc-volume>
          <glossentry id="_g1" category="general">
            <glossterm>Habitable room</glossterm>
            <glossdef>
              <content>
                <p>A room used for normal domestic activities.</p>
              </content>
            </glossdef>
          </glossentry>
        </ncc-volume>
        """
    )
    glossentry = root.find("glossentry")
    corpus = make_corpus(root)

    chunk = parse_glossary_file(glossentry, corpus)

    assert chunk.id == "g1"  # leading "_" stripped
    assert chunk.node_type == "glossary"
    assert chunk.heading == "Habitable room"
    assert chunk.doc == corpus.doc_label
    assert chunk.text == "A room used for normal domestic activities."
    assert chunk.hierarchy == [corpus.doc_label]


def test_parse_glossary_file_with_no_content_is_empty_text(make_corpus):
    root = parse(
        """
        <glossentry id="_g2">
          <glossterm>Storey</glossterm>
          <glossdef/>
        </glossentry>
        """
    )
    corpus = make_corpus(root)

    chunk = parse_glossary_file(root, corpus)

    assert chunk.text == ""
