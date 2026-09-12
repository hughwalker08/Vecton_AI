"""
CLI entrypoint: parse NCC 2025 Volume Two + the ABCB Housing Provisions
(v1.2 schema) into two local JSON files of chunk records. No embeddings, no
database writes (see the project plan for why this phase stops here).

Both corpora are loaded together (needed so cross-corpus citations resolve
to a real chunk_id) but written to separate output files, one per corpus.

Usage:
    python -m app.ingest.cli \
        [--data-dir /path/containing/both/ncc-2025-*-v1.2/folders] \
        [--volume-two-source /path/to/ncc-2025-volume-two-v1.2] \
        [--housing-source /path/to/ncc-2025-housing-provisions-v1.2] \
        [--out-dir backend/app/ingest/output]
"""

import argparse
import sys
from pathlib import Path

from app.ingest.chunker import RefContext, build_clause_chunks
from app.ingest.corpus import Corpus, load_corpus
from app.ingest.figure_parser import parse_figure_file
from app.ingest.glossary_parser import glossary_term, parse_glossary_file
from app.ingest.guid_index import build_guid_index
from app.ingest.housing_citations import build_number_index, extract_bare_housing_citations
from app.ingest.image_descriptions import DescriptionStore, describe_missing, load_store
from app.ingest.part_spec_parser import parse_part_or_spec, parse_part_variation
from app.ingest.records import IngestReport
from app.ingest.report import build_corpus_report, print_report, write_report_json
from app.ingest.resolve_internal_refs import build_element_id_to_chunk_id, resolve_refs
from app.ingest.serialize import write_chunks
from app.ingest.standards import build_standards_lookup, extract_standard_mentions, normalize_standard_number
from app.ingest.table_parser import parse_table_file

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = Path(__file__).parent / "output"


def ingest_corpus(corpus: Corpus, ctx: RefContext, descriptions: DescriptionStore = None):
    """Returns (chunks, images_matched, images_unmatched, figures_described, figures_undescribed)."""
    chunks = []
    images_matched = 0
    images_unmatched = []
    figures_described = 0
    figures_undescribed = []

    processed_variation_ids = set()
    for clause_el in corpus.root.iter("clause"):
        chunks.extend(build_clause_chunks(clause_el, corpus, ctx))
        for cv in clause_el.findall("clause-variation"):
            processed_variation_ids.add(cv.get("id"))

    for cv in corpus.root.iter("clause-variation"):
        if cv.get("id") in processed_variation_ids:
            continue
        chunks.extend(build_clause_chunks(cv, corpus, ctx, jurisdiction_override=cv.get("state")))

    for pv in corpus.root.iter("part-variation"):
        chunks.append(parse_part_variation(pv, corpus))

    for tr in corpus.root.iter("table-reference"):
        chunks.append(parse_table_file(tr, corpus))

    for ir in corpus.root.iter("image-reference"):
        chunk, matched_filename, described = parse_figure_file(ir, corpus, descriptions)
        chunks.append(chunk)
        if matched_filename:
            images_matched += 1
            if described:
                figures_described += 1
            else:
                figures_undescribed.append(matched_filename)
        else:
            src_el = ir.find("img")
            images_unmatched.append(src_el.get("src") if src_el is not None else ir.get("id"))

    for el in corpus.root.iter("part"):
        chunks.append(parse_part_or_spec(el, corpus))
    for el in corpus.root.iter("specification"):
        chunks.append(parse_part_or_spec(el, corpus))

    for ge in corpus.root.iter("glossentry"):
        chunks.append(parse_glossary_file(ge, corpus))

    return chunks, images_matched, images_unmatched, figures_described, figures_undescribed


def run(
    volume_two_source: Path,
    housing_source: Path,
    out_dir: Path,
    description_stores: dict = None,
) -> IngestReport:
    vol2 = load_corpus(
        "vol2", "NCC 2025 Volume Two", volume_two_source / "contents.xml", volume_two_source / "images"
    )
    housing = load_corpus(
        "housing", "ABCB Housing Provisions", housing_source / "contents.xml", housing_source / "images"
    )
    corpora = [vol2, housing]

    guid_index = build_guid_index(corpora)
    glossary_terms = {
        ge.get("id"): glossary_term(ge) for corpus in corpora for ge in corpus.root.iter("glossentry")
    }

    description_stores = description_stores or {}
    chunks_by_corpus = {}
    images_matched_total = 0
    images_unmatched_total = []
    figures_described_total = 0
    figures_undescribed_total = []
    for corpus in corpora:
        ctx = RefContext(guid_index=guid_index, corpus=corpus, glossary_terms=glossary_terms)
        chunks, matched, unmatched, described, undescribed = ingest_corpus(
            corpus, ctx, description_stores.get(corpus.name)
        )
        chunks_by_corpus[corpus.name] = chunks
        images_matched_total += matched
        images_unmatched_total.extend(unmatched)
        figures_described_total += described
        figures_undescribed_total.extend(undescribed)

    # Standards: merge every "Schedule of referenced documents" table across both corpora.
    standards_lookup = {}
    for corpus in corpora:
        standards_lookup.update(build_standards_lookup(corpus.root))

    standards_matched = 0
    standards_unmatched = set()
    number_index = build_number_index(housing.root)
    all_bare_citations = []  # same dict objects as appended to chunk.external_refs -- mutated in place by resolve_refs

    for chunks in chunks_by_corpus.values():
        for chunk in chunks:
            for mention in extract_standard_mentions(chunk.text):
                entry = standards_lookup.get(normalize_standard_number(mention))
                if entry:
                    standards_matched += 1
                    chunk.external_refs.append(
                        {"kind": "standard", "standard": entry["standard"], "title": entry["title"]}
                    )
                else:
                    standards_unmatched.add(mention)
                    chunk.external_refs.append({"kind": "standard", "standard": mention, "title": None})

            bare_citations = extract_bare_housing_citations(chunk.text, number_index)
            chunk.external_refs.extend(bare_citations)
            all_bare_citations.extend(bare_citations)

    element_maps = {corpus.name: build_element_id_to_chunk_id(corpus) for corpus in corpora}
    internal_resolved, internal_unresolved, external_refs_by_kind = resolve_refs(chunks_by_corpus, element_maps)
    housing_bare_found = len(all_bare_citations)
    housing_bare_resolved = sum(1 for ref in all_bare_citations if ref.get("chunk_id"))

    report = IngestReport(
        corpora={corpus.name: build_corpus_report(corpus.doc_label, chunks_by_corpus[corpus.name]) for corpus in corpora},
        images_matched=images_matched_total,
        images_unmatched=images_unmatched_total,
        figures_described=figures_described_total,
        figures_undescribed=figures_undescribed_total,
        standards_matched=standards_matched,
        standards_unmatched=sorted(standards_unmatched),
        internal_refs_resolved=internal_resolved,
        internal_refs_unresolved=internal_unresolved,
        external_refs_by_kind=external_refs_by_kind,
        housing_bare_citations_found=housing_bare_found,
        housing_bare_citations_resolved=housing_bare_resolved,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    file_names = {"vol2": "ncc_volume_two_chunks.json", "housing": "abcb_housing_provisions_chunks.json"}
    for corpus in corpora:
        write_chunks(chunks_by_corpus[corpus.name], out_dir / file_names[corpus.name])
    write_report_json(report, out_dir / "ingest.report.json")

    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT, help="Directory containing both ncc-2025-*-v1.2 folders")
    parser.add_argument("--volume-two-source", type=Path, default=None)
    parser.add_argument("--housing-source", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--image-descriptions",
        type=Path,
        nargs="*",
        default=None,
        help="Figure description store(s) written by scripts/describe_images.py "
             "(.jsonl or .json). Defaults to <out-dir>/{vol2,housing}_image_descriptions.jsonl "
             "when those exist. Descriptions are folded into figure chunks' text.",
    )
    parser.add_argument(
        "--describe-missing-images",
        action="store_true",
        help="Transcribe any matched figure with no stored description before parsing. "
             "Needs GEMINI_API_KEY and costs one API call per figure.",
    )
    args = parser.parse_args(argv)

    volume_two_source = args.volume_two_source or args.data_dir / "ncc-2025-volume-two-v1.2"
    housing_source = args.housing_source or args.data_dir / "ncc-2025-housing-provisions-v1.2"

    for path in (volume_two_source, housing_source):
        if not (path / "contents.xml").exists():
            print(f"No contents.xml found under {path}", file=sys.stderr)
            return 1

    sources = {"vol2": volume_two_source, "housing": housing_source}

    # Per-corpus stores keep vol2 and housing descriptions apart, since the two
    # corpora reuse figure filenames.
    if args.image_descriptions:
        shared = load_store(*args.image_descriptions)
        description_stores = {name: shared for name in sources}
    else:
        description_stores = {
            name: load_store(
                args.out_dir / f"{name}_image_descriptions.jsonl",
                args.out_dir / f"{name}_image_descriptions.json",
            )
            for name in sources
        }

    if args.describe_missing_images:
        for name, source in sources.items():
            corpus_images = sorted(
                p.name for p in (source / "images").glob("*") if p.is_file()
            ) if (source / "images").is_dir() else []
            if not corpus_images:
                continue
            print(f"[{name}] checking {len(corpus_images)} image file(s) for descriptions")
            try:
                describe_missing(
                    description_stores[name],
                    source / "images",
                    corpus_images,
                    args.out_dir / f"{name}_image_descriptions.jsonl",
                )
            except Exception as exc:  # noqa: BLE001 - missing key/SDK shouldn't sink ingest
                print(f"  Skipping description generation for {name}: {exc}", file=sys.stderr)

    for name, store in description_stores.items():
        if store:
            print(f"[{name}] loaded {len(store)} figure description(s)")

    report = run(volume_two_source, housing_source, args.out_dir, description_stores)
    print_report(report)
    total = sum(sum(cr.chunks_by_node_type.values()) for cr in report.corpora.values())
    print(f"Wrote {total} chunks across {len(report.corpora)} corpora to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
