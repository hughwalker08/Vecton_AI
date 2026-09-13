from app.ingest.records import ChunkRecord
from app.ingest.resolve_internal_refs import build_element_id_to_chunk_id, resolve_refs
from tests.ingest.conftest import parse


def test_build_element_id_to_chunk_id_maps_direct_chunk_tags(make_corpus):
    root = parse(
        """
        <ncc-volume>
          <table-reference id="_t1"/>
          <image-reference id="_f1"/>
        </ncc-volume>
        """
    )
    corpus = make_corpus(root)

    mapping = build_element_id_to_chunk_id(corpus)

    assert mapping == {"_t1": "t1", "_f1": "f1"}


def test_build_element_id_to_chunk_id_maps_a_clause_to_its_first_subclause(make_corpus):
    root = parse(
        """
        <ncc-volume>
          <clause id="_c1">
            <subclause id="_s1" num="1"/>
            <subclause id="_s2" num="2"/>
          </clause>
        </ncc-volume>
        """
    )
    corpus = make_corpus(root)

    mapping = build_element_id_to_chunk_id(corpus)

    # The clause root itself isn't a chunk -- it maps to its first subclause.
    assert mapping["_c1"] == "s1"
    assert mapping["_s1"] == "s1"
    assert mapping["_s2"] == "s2"


def test_build_element_id_to_chunk_id_clause_with_only_a_callout_maps_to_it(make_corpus):
    root = parse(
        """
        <clause id="_c1">
          <callout id="_note1"/>
        </clause>
        """
    )
    corpus = make_corpus(root)

    mapping = build_element_id_to_chunk_id(corpus)

    assert mapping["_c1"] == "note1"


def test_build_element_id_to_chunk_id_empty_clause_is_left_unmapped(make_corpus):
    root = parse('<clause id="_c1"/>')
    corpus = make_corpus(root)

    assert build_element_id_to_chunk_id(corpus) == {}


def _chunk(**refs):
    return ChunkRecord(id="x", node_type="subclause", **refs)


def test_resolve_refs_fills_chunk_id_for_internal_refs():
    chunk = _chunk(
        internal_refs=[
            {"clause_id": "H1D4", "chunk_id": None, "_target_guid": "_c1", "_target_corpus": "vol2"}
        ]
    )

    resolved, unresolved, external_by_kind = resolve_refs(
        {"vol2": [chunk]}, {"vol2": {"_c1": "c1"}}
    )

    assert chunk.internal_refs[0]["chunk_id"] == "c1"
    assert resolved == 1
    assert unresolved == 0
    assert external_by_kind == {}


def test_resolve_refs_counts_an_unresolvable_ref():
    chunk = _chunk(
        internal_refs=[
            {
                "clause_id": "H1D4",
                "chunk_id": None,
                "_target_guid": "_missing",
                "_target_corpus": "vol2",
            }
        ]
    )

    resolved, unresolved, _ = resolve_refs({"vol2": [chunk]}, {"vol2": {}})

    assert resolved == 0
    assert unresolved == 1


def test_resolve_refs_tallies_external_refs_by_kind():
    chunk = _chunk(
        external_refs=[
            {
                "kind": "housing",
                "chunk_id": None,
                "_target_guid": "_h1",
                "_target_corpus": "housing",
            },
            {
                "kind": "housing",
                "chunk_id": None,
                "_target_guid": "_missing",
                "_target_corpus": "housing",
            },
        ]
    )

    _, _, external_by_kind = resolve_refs({"vol2": [chunk]}, {"housing": {"_h1": "h1"}})

    assert external_by_kind == {"housing": {"total": 2, "resolved": 1}}
    assert chunk.external_refs[0]["chunk_id"] == "h1"
    assert chunk.external_refs[1]["chunk_id"] is None
