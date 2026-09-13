"""
Shared fixtures for the ingest test suite.

The v1.2 corpus schema (see app/ingest/corpus.py) is a real nested XML tree,
so every test here builds a tiny inline fragment with lxml rather than
loading one of the real NCC/ABCB files -- fast, and each fixture only needs
to carry the handful of tags/attributes the module under test actually
reads.
"""

import lxml.etree as ET
import pytest

from app.ingest.corpus import Corpus


def parse(xml: str):
    """Parse an XML fragment (given as a plain string) into its root element."""
    return ET.fromstring(xml)


@pytest.fixture
def make_corpus(tmp_path):
    """Factory for a Corpus pointed at a real (empty by default) images_dir,
    so `(corpus.images_dir / src).exists()` checks used by figure_parser.py
    and chunker.py behave like they would against a real corpus."""

    def _make(root, *, name="vol2", doc_label="NCC 2025 Volume Two", publishing_id="vol2"):
        images_dir = tmp_path / name / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        return Corpus(
            name=name,
            doc_label=doc_label,
            publishing_id=publishing_id,
            root=root,
            images_dir=images_dir,
        )

    return _make
