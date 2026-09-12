"""Validation report the CLI prints after a run."""

import collections
import json
from pathlib import Path

from app.ingest.records import CorpusReport, IngestReport


def build_corpus_report(doc_label: str, chunks: list) -> CorpusReport:
    counts = collections.Counter(c.node_type for c in chunks)
    clauses_total = len({c.clause_id for c in chunks if c.clause_id and c.node_type in ("subclause", "note")})
    return CorpusReport(
        doc_label=doc_label,
        chunks_by_node_type=dict(sorted(counts.items())),
        clauses_total=clauses_total,
    )


def print_report(report: IngestReport) -> None:
    print("\n=== Ingest report ===")
    for name, corpus_report in report.corpora.items():
        print(f"\n[{name}] {corpus_report.doc_label} -- {corpus_report.clauses_total} distinct clause_ids")
        for node_type, count in corpus_report.chunks_by_node_type.items():
            print(f"  {node_type:15s} {count}")

    print(f"\nImages: {report.images_matched} matched, {len(report.images_unmatched)} unmatched")
    if report.images_unmatched:
        for f in report.images_unmatched[:10]:
            print(f"    - {f}")

    undescribed = len(report.figures_undescribed)
    print(
        f"Figure descriptions: {report.figures_described} of "
        f"{report.images_matched} matched figures"
    )
    if undescribed:
        print(f"    {undescribed} matched figure(s) have no description -- those chunks")
        print("    carry only the caption, so the drawing's dimensions are not searchable.")
        print("    Generate them:  python scripts/describe_images.py <source>/images \\")
        print("                        --out app/ingest/output/<corpus>_image_descriptions.jsonl")
        for f in report.figures_undescribed[:10]:
            print(f"    - {f}")

    print(f"\nStandards: {report.standards_matched} matched, {len(report.standards_unmatched)} unmatched")
    if report.standards_unmatched:
        for s in sorted(report.standards_unmatched)[:15]:
            print(f"    - {s}")

    print(f"\nInternal refs: {report.internal_refs_resolved} resolved, {report.internal_refs_unresolved} unresolved")

    print("\nExternal refs by kind (total / resolved to a chunk_id):")
    for kind, stats in sorted(report.external_refs_by_kind.items()):
        print(f"  {kind:12s} {stats['total']:5d} / {stats['resolved']}")

    print(
        f"\nBare-prose Housing Provisions citations (no <a> tag at all): "
        f"{report.housing_bare_citations_found} found, {report.housing_bare_citations_resolved} resolved"
    )
    print()


def write_report_json(report: IngestReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
