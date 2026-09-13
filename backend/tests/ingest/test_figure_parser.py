from app.ingest.figure_parser import parse_figure_file
from tests.ingest.conftest import parse


def test_parse_figure_file_matched_image_with_no_description(make_corpus):
    root = parse(
        """
        <image-reference id="_f1" num="11.2.2">
          <title>Stair riser and going</title>
          <img src="fig-11-2-2.svg"/>
        </image-reference>
        """
    )
    corpus = make_corpus(root)
    (corpus.images_dir / "fig-11-2-2.svg").write_text("<svg/>")

    chunk, matched_src, described = parse_figure_file(root, corpus)

    assert chunk.id == "f1"
    assert chunk.node_type == "figure"
    assert chunk.heading == "Figure 11.2.2: Stair riser and going"
    assert chunk.image_refs == [
        {
            "image_id": "f1",
            "filename": "fig-11-2-2.svg",
            "caption": "Figure 11.2.2: Stair riser and going",
            "described": False,
        }
    ]
    assert matched_src == "fig-11-2-2.svg"
    assert described is False


def test_parse_figure_file_folds_in_a_matching_description(make_corpus):
    root = parse(
        """
        <image-reference id="_f2" num="11.2.2">
          <title>Stair riser and going</title>
          <img src="fig-11-2-2.svg"/>
        </image-reference>
        """
    )
    corpus = make_corpus(root)
    (corpus.images_dir / "fig-11-2-2.svg").write_text("<svg/>")

    class _Descriptions:
        def get(self, filename):
            return "A stair section showing riser 175mm, going 250mm." if filename else None

    chunk, matched_src, described = parse_figure_file(root, corpus, descriptions=_Descriptions())

    assert "175mm" in chunk.text
    assert described is True
    assert chunk.image_refs[0]["described"] is True


def test_parse_figure_file_unmatched_image_has_no_image_refs(make_corpus):
    root = parse(
        """
        <image-reference id="_f3" num="3">
          <title>Missing figure</title>
          <img src="does-not-exist.svg"/>
        </image-reference>
        """
    )
    corpus = make_corpus(root)

    chunk, matched_src, described = parse_figure_file(root, corpus)

    assert chunk.image_refs == []
    assert matched_src is None
    assert described is False


def test_parse_figure_file_with_no_title_or_num_has_no_heading(make_corpus):
    root = parse('<image-reference id="_f4"><img src="x.svg"/></image-reference>')
    corpus = make_corpus(root)

    chunk, _, _ = parse_figure_file(root, corpus)

    assert chunk.heading is None
