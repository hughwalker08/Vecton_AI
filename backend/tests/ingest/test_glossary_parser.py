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


def test_parse_glossary_file_keeps_the_list_from_a_later_content_block(make_corpus):
    root = parse(
        """
        <glossentry id="_g3">
          <glossterm>Habitable room</glossterm>
          <glossdef>
            <content><p>A room used for normal domestic activities, and\u2014</p></content>
            <content>
              <ol class="alpha">
                <li>includes a bedroom and a kitchen; but</li>
                <li>excludes a bathroom and a laundry.</li>
              </ol>
            </content>
          </glossdef>
        </glossentry>
        """
    )
    corpus = make_corpus(root)

    chunk = parse_glossary_file(root, corpus)

    lines = chunk.text.split("\n")
    assert lines[0] == "A room used for normal domestic activities, and\u2014"
    assert any("includes a bedroom and a kitchen" in line for line in lines[1:])
    assert any("excludes a bathroom and a laundry" in line for line in lines[1:])
