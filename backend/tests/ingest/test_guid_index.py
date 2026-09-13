from app.ingest.guid_index import build_guid_index, resolve_guid
from tests.ingest.conftest import parse


def _corpus(make_corpus, root, name, publishing_id):
    return make_corpus(root, name=name, publishing_id=publishing_id)


def test_build_guid_index_covers_every_element_with_an_id_across_corpora(make_corpus):
    vol2_root = parse('<ncc-volume><clause id="_c1"><sptc>H1D4</sptc></clause></ncc-volume>')
    housing_root = parse('<ncc-volume><clause id="_h1"><sptc>10.8</sptc></clause></ncc-volume>')
    vol2 = _corpus(make_corpus, vol2_root, "vol2", "vol2")
    housing = _corpus(make_corpus, housing_root, "housing", "housing")

    index = build_guid_index([vol2, housing])

    # Corpus isn't hashable, so compare the (corpus, element) lists directly
    # rather than via a set.
    assert index["_c1"] == [(vol2, vol2_root.find("clause"))]
    assert index["_h1"] == [(housing, housing_root.find("clause"))]


def test_build_guid_index_a_guid_can_map_into_more_than_one_corpus(make_corpus):
    # Documented edge case: shared front-matter boilerplate reuses the same
    # id across both corpora's contents.xml.
    vol2_root = parse('<front-matter id="_shared"/>')
    housing_root = parse('<front-matter id="_shared"/>')
    vol2 = _corpus(make_corpus, vol2_root, "vol2", "vol2")
    housing = _corpus(make_corpus, housing_root, "housing", "housing")

    index = build_guid_index([vol2, housing])

    assert len(index["_shared"]) == 2


def test_resolve_guid_prefers_the_target_publishing_id_when_given(make_corpus):
    vol2_root = parse('<clause id="_shared"><sptc>Vol2 version</sptc></clause>')
    housing_root = parse('<clause id="_shared"><sptc>Housing version</sptc></clause>')
    vol2 = _corpus(make_corpus, vol2_root, "vol2", "vol2")
    housing = _corpus(make_corpus, housing_root, "housing", "housing")
    index = build_guid_index([vol2, housing])

    corpus, el = resolve_guid("_shared", index, owning_corpus=vol2, target_publishing_id="housing")

    assert corpus is housing
    assert el.findtext("sptc") == "Housing version"


def test_resolve_guid_prefers_the_owning_corpus_for_a_local_link(make_corpus):
    vol2_root = parse('<clause id="_shared"><sptc>Vol2 version</sptc></clause>')
    housing_root = parse('<clause id="_shared"><sptc>Housing version</sptc></clause>')
    vol2 = _corpus(make_corpus, vol2_root, "vol2", "vol2")
    housing = _corpus(make_corpus, housing_root, "housing", "housing")
    index = build_guid_index([vol2, housing])

    corpus, el = resolve_guid("_shared", index, owning_corpus=housing)

    assert corpus is housing
    assert el.findtext("sptc") == "Housing version"


def test_resolve_guid_unknown_guid_returns_none(make_corpus):
    root = parse('<clause id="_c1"/>')
    corpus = _corpus(make_corpus, root, "vol2", "vol2")
    index = build_guid_index([corpus])

    assert resolve_guid("_does_not_exist", index, owning_corpus=corpus) is None
