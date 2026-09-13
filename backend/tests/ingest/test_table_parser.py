from app.ingest.table_parser import parse_table_file
from tests.ingest.conftest import parse


def test_parse_table_file_renders_header_and_body_rows(make_corpus):
    root = parse(
        """
        <table-reference id="_t1" num="10.8.1" sptc="10.8">
          <title>Minimum riser and going dimensions</title>
          <table>
            <thead>
              <tr><th>Item</th><th>Minimum (mm)</th></tr>
            </thead>
            <tbody>
              <tr><td>Riser</td><td>115</td></tr>
              <tr><td>Going</td><td>250</td></tr>
            </tbody>
          </table>
        </table-reference>
        """
    )
    corpus = make_corpus(root)

    chunk = parse_table_file(root, corpus)

    assert chunk.id == "t1"
    assert chunk.node_type == "table"
    assert chunk.clause_id == "10.8"
    assert chunk.heading == "Table 10.8.1: Minimum riser and going dimensions"
    assert chunk.text == (
        "Minimum riser and going dimensions\n"
        "Item | Minimum (mm)\n"
        "Riser | 115\n"
        "Going | 250"
    )


def test_parse_table_file_skips_empty_rows_and_collapses_cell_whitespace(make_corpus):
    root = parse(
        """
        <table-reference id="_t2">
          <table>
            <tbody>
              <tr><td>  Riser   height  </td><td></td></tr>
              <tr></tr>
            </tbody>
          </table>
        </table-reference>
        """
    )
    corpus = make_corpus(root)

    chunk = parse_table_file(root, corpus)

    # An empty second cell drops out of the " | " join; the fully-empty
    # second row contributes no line at all.
    assert chunk.text == "Riser height"


def test_parse_table_file_with_no_table_element_falls_back_to_title(make_corpus):
    root = parse(
        '<table-reference id="_t3" num="3"><title>Placeholder table</title></table-reference>'
    )
    corpus = make_corpus(root)

    chunk = parse_table_file(root, corpus)

    assert chunk.text == "Placeholder table"
