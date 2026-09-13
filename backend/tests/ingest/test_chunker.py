"""
Tests for app.ingest.chunker.

render_content / extract_refs are exercised directly (the trickiest,
highest-value logic in the module), then build_clause_chunks is exercised
end-to-end on one small fixture clause covering every shape it handles:
plain subclauses, a jurisdiction-qualified subclause, a subclause-variation,
a callout note, and a clause-variation.
"""

from app.ingest.chunker import RefContext, build_clause_chunks, extract_refs, render_content
from app.ingest.corpus import Corpus
from app.ingest.guid_index import build_guid_index
from tests.ingest.conftest import parse

# ---------------------------------------------------------------------------
# render_content
# ---------------------------------------------------------------------------


def test_render_content_renders_paragraphs_and_an_alpha_list():
    content = parse(
        """
        <content>
          <num>(1)</num>
          <p>Footings must comply with the following:</p>
          <ol class="alpha">
            <li>the soil classification;</li>
            <li>the footing depth.</li>
          </ol>
        </content>
        """
    )

    text = render_content(content)

    assert text == (
        "(1) Footings must comply with the following:\n"
        "(a) the soil classification;\n"
        "(b) the footing depth."
    )


def test_render_content_numbered_and_roman_nested_lists():
    content = parse(
        """
        <content>
          <ol class="numbered">
            <li>Top level
              <ol>
                <li>Nested one</li>
                <li>Nested two</li>
              </ol>
            </li>
          </ol>
        </content>
        """
    )

    text = render_content(content)

    assert text == "(1) Top level\n  (i) Nested one\n  (ii) Nested two"


def test_render_content_renders_equation_tokens_not_the_mathml_blob():
    content = parse(
        "<content><equation-block><mi>A</mi><mo>=</mo><mi>b</mi><mi>h</mi>"
        "</equation-block></content>"
    )

    assert render_content(content) == "A=bh"


def test_render_content_renders_a_titled_section():
    content = parse(
        """
        <content>
          <section>
            <title>Exemptions</title>
            <p>None apply.</p>
          </section>
        </content>
        """
    )

    assert render_content(content) == "Exemptions:\nNone apply."


def test_render_content_renders_inline_link_text_and_its_tail():
    content = parse(
        '<content><p>See <a href="#_x1">Table 1</a> for details.</p></content>'
    )

    assert render_content(content) == "See Table 1 for details."


def test_render_content_empty_content_is_empty_string():
    assert render_content(parse("<content/>")) == ""


def test_render_content_equation_inline_within_a_paragraph():
    content = parse(
        "<content><p>The area is <equation-inline><mi>A</mi><mo>=</mo><mi>b</mi><mi>h</mi>"
        "</equation-inline> square metres.</p></content>"
    )

    assert render_content(content) == "The area is A=bh square metres."


# ---------------------------------------------------------------------------
# extract_refs
# ---------------------------------------------------------------------------


def _ref_ctx(root, corpus, glossary_terms=None):
    guid_index = build_guid_index([corpus])
    return RefContext(guid_index=guid_index, corpus=corpus, glossary_terms=glossary_terms or {})


def test_extract_refs_handles_every_ref_kind_in_one_pass(make_corpus):
    root = parse(
        """
        <ncc-volume>
          <table-reference id="_tbl1" num="1"/>
          <glossentry id="_g1"><glossterm>Habitable room</glossterm></glossentry>
          <image-reference id="_img1"><img src="fig1.svg"/></image-reference>
          <content>
            <p>
              See <a href="#_tbl1" type="table-reference">Table 1</a> and the definition of
              <a href="#_g1" type="abcb-glossentry">habitable room</a>. See
              <a href="#_img1" type="image-reference">Figure 1</a>. Also see
              <a href="#_ext1" type="clause" publishing-id="housing">Part 9.6</a>. Visit
              <a href="https://www.abcb.gov.au">the ABCB website</a>.
            </p>
          </content>
        </ncc-volume>
        """
    )
    corpus = make_corpus(root)
    (corpus.images_dir / "fig1.svg").write_text("<svg/>")
    ctx = _ref_ctx(root, corpus, glossary_terms={"_g1": "Habitable room"})
    content = root.find("content")

    cross_refs, defined_terms, image_refs, external_refs, internal_refs = extract_refs(content, ctx)

    # Plain http(s) links with no "#" href are silently skipped.
    assert cross_refs == ["Table 1", "habitable room", "Figure 1", "Part 9.6"]
    assert defined_terms == ["Habitable room"]
    assert image_refs == [{"image_id": "img1", "filename": "fig1.svg", "caption": "Figure 1"}]
    assert internal_refs == [
        {
            "clause_id": "Table 1",
            "chunk_id": None,
            "_target_guid": "_tbl1",
            "_target_corpus": "vol2",
        }
    ]
    # publishing-id differs from the owning corpus -> external; unresolved
    # (the target lives in a corpus this test didn't load) -> no _target_guid.
    assert external_refs == [
        {"kind": "housing", "clause_id": "Part 9.6", "raw_text": "Part 9.6", "chunk_id": None}
    ]


def test_extract_refs_image_reference_not_matched_when_file_is_missing(make_corpus):
    root = parse(
        """
        <ncc-volume>
          <image-reference id="_img1"><img src="missing.svg"/></image-reference>
          <content><p>See <a href="#_img1" type="image-reference">Figure 1</a>.</p></content>
        </ncc-volume>
        """
    )
    corpus = make_corpus(root)  # no fig file written -- doesn't exist on disk
    ctx = _ref_ctx(root, corpus)

    _, _, image_refs, _, _ = extract_refs(root.find("content"), ctx)

    assert image_refs == []


def test_extract_refs_deduplicates_repeated_glossary_terms(make_corpus):
    root = parse(
        """
        <ncc-volume>
          <glossentry id="_g1"><glossterm>Storey</glossterm></glossentry>
          <content>
            <p>
              A <a href="#_g1" type="abcb-glossentry">storey</a> is defined. Each
              <a href="#_g1" type="abcb-glossentry">storey</a> must comply.
            </p>
          </content>
        </ncc-volume>
        """
    )
    corpus = make_corpus(root)
    ctx = _ref_ctx(root, corpus, glossary_terms={"_g1": "Storey"})

    _, defined_terms, _, _, _ = extract_refs(root.find("content"), ctx)

    assert defined_terms == ["Storey"]


def test_extract_refs_resolved_external_ref_uses_the_targets_own_number(make_corpus):
    """When a cross-corpus link DOES resolve (the target corpus was loaded),
    clause_id is overwritten with the target's own number rather than
    whatever display text the source clause happened to use."""
    vol2_root = parse(
        '<content><p>See <a href="#_h1" type="clause" publishing-id="housing">'
        "the Housing Provisions</a>.</p></content>"
    )
    housing_root = parse('<clause id="_h1"><sptc>9.6</sptc></clause>')
    vol2 = make_corpus(vol2_root, name="vol2", publishing_id="vol2")
    housing = make_corpus(housing_root, name="housing", publishing_id="housing")
    guid_index = build_guid_index([vol2, housing])
    ctx = RefContext(guid_index=guid_index, corpus=vol2, glossary_terms={})

    _, _, _, external_refs, _ = extract_refs(vol2_root, ctx)

    assert external_refs == [
        {
            "kind": "housing",
            "clause_id": "9.6",  # overwritten from "the Housing Provisions"
            "raw_text": "the Housing Provisions",
            "chunk_id": None,
            "_target_guid": "_h1",
            "_target_corpus": "housing",
        }
    ]


def test_extract_refs_local_link_with_no_recognised_type_is_only_a_cross_ref(make_corpus):
    root = parse('<content><p>See <a href="#_x1" type="something-else">it</a>.</p></content>')
    corpus = make_corpus(root)
    ctx = _ref_ctx(root, corpus)

    cross_refs, defined_terms, image_refs, external_refs, internal_refs = extract_refs(root, ctx)

    assert cross_refs == ["it"]
    assert defined_terms == image_refs == external_refs == internal_refs == []


# ---------------------------------------------------------------------------
# build_clause_chunks (end-to-end)
# ---------------------------------------------------------------------------


def test_build_clause_chunks_end_to_end(make_corpus):
    root = parse(
        """
        <ncc-volume>
          <ncc-section num="Section H"><title>Housing provisions</title>
            <part num="H1"><title>Structure</title>
              <subtopic>
                <clause id="_c1" building="Class 1a,Class 10a"
                        climate="Climate zone 1,Climate zone 2">
                  <sptc>H1D4</sptc>
                  <title>Footings</title>
                  <subclause id="_s1" num="1">
                    <content><p>Footings must be designed to support the loads.</p></content>
                  </subclause>
                  <subclause id="_s2" num="2" state="NSW">
                    <content>
                      <p>In NSW, footings must also comply with local conditions.</p>
                    </content>
                  </subclause>
                  <subclause id="_s3" num="3">
                    <content><p>Base footing text.</p></content>
                    <subclause-variation id="_s3v" num="3" state="TAS">
                      <content><p>Varied footing text for Tasmania.</p></content>
                    </subclause-variation>
                  </subclause>
                  <callout id="_note1" callout-type="Note">
                    <content><p>General note about footings.</p></content>
                  </callout>
                  <clause-variation id="_cv1" state="WA" type="REPLACE">
                    <sptc>H1D4</sptc>
                    <subclause id="_cvs1" num="1">
                      <content><p>WA-specific footing text.</p></content>
                    </subclause>
                  </clause-variation>
                </clause>
              </subtopic>
            </part>
          </ncc-section>
        </ncc-volume>
        """
    )
    corpus = make_corpus(root)
    ctx = _ref_ctx(root, corpus)
    clause = root.find(".//clause")

    chunks = build_clause_chunks(clause, corpus, ctx)

    assert [c.id for c in chunks] == ["s1", "s2", "s3", "s3v", "note1", "cvs1"]
    assert [c.node_type for c in chunks] == [
        "subclause", "subclause", "subclause", "subclause", "note", "subclause",
    ]

    base_hierarchy = [corpus.doc_label, "Section H Housing provisions", "H1 Structure", "H1D4"]

    s1, s2, s3, s3v, note1, cvs1 = chunks

    # Plain national subclause: no jurisdictions, hierarchy carries its own
    # citable number.
    assert s1.hierarchy == base_hierarchy + ["H1D4(1)"]
    assert s1.jurisdictions is None
    assert s1.text == "Footings must be designed to support the loads."
    assert s1.building_classes == ["1a", "10a"]
    assert s1.climate_zones == [1, 2]

    # A subclause with its own state="" attribute is jurisdiction-qualified.
    assert s2.jurisdictions == ["NSW"]
    assert s2.hierarchy == base_hierarchy + ["H1D4(2)"]

    # subclause-variation shares its parent subclause's number in the
    # hierarchy, but carries the variation's own state.
    assert s3.jurisdictions is None
    assert s3v.hierarchy == base_hierarchy + ["H1D4(3)"]
    assert s3v.jurisdictions == ["TAS"]
    assert s3v.text == "Varied footing text for Tasmania."

    # A callout is a "note" chunk, not tied to a specific subclause number.
    assert note1.heading == "Note (Note)"
    assert note1.hierarchy == base_hierarchy

    # clause-variation recurses as if it were its own clause; its subclause
    # inherits the variation's state as its jurisdiction.
    assert cvs1.jurisdictions == ["WA"]
    assert cvs1.text == "WA-specific footing text."


def test_build_clause_chunks_subclause_variation_as_a_direct_child_of_clause(make_corpus):
    """A <subclause-variation> can sit directly under <clause> (not nested
    inside a <subclause>) -- a whole extra jurisdiction-specific subclause,
    rather than a variation of an existing one."""
    root = parse(
        """
        <clause id="_c1">
          <sptc>H1D4</sptc>
          <subclause id="_s1" num="1"><content><p>National text.</p></content></subclause>
          <subclause-variation id="_scv1" num="2" state="QLD">
            <content><p>QLD-only additional requirement.</p></content>
          </subclause-variation>
        </clause>
        """
    )
    corpus = make_corpus(root)
    ctx = _ref_ctx(root, corpus)

    chunks = build_clause_chunks(root, corpus, ctx)

    assert [c.id for c in chunks] == ["s1", "scv1"]
    assert chunks[1].jurisdictions == ["QLD"]
    assert chunks[1].text == "QLD-only additional requirement."


def test_build_clause_chunks_clause_variation_with_no_subclauses_becomes_a_note(make_corpus):
    """A DELETE/REPLACE clause-variation with only bare <content> (no
    <subclause>) renders that content directly as a single "note" chunk."""
    root = parse(
        """
        <clause id="_c1">
          <sptc>H1D4</sptc>
          <clause-variation id="_cv1" state="TAS" type="DELETE">
            <sptc>H1D4</sptc>
            <content><p>This clause does not apply in Tasmania.</p></content>
          </clause-variation>
        </clause>
        """
    )
    corpus = Corpus(
        name="vol2",
        doc_label="NCC 2025 Volume Two",
        publishing_id="vol2",
        root=root,
        images_dir=None,
    )
    ctx = RefContext(guid_index={}, corpus=corpus, glossary_terms={})

    chunks = build_clause_chunks(root, corpus, ctx)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.node_type == "note"
    assert chunk.jurisdictions == ["TAS"]
    assert chunk.text == "This clause does not apply in Tasmania."
