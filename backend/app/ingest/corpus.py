"""
Corpus loading for the v1.2 schema.

Both NCC 2025 Volume Two and the ABCB Housing Provisions are now exported as
a single `contents.xml` per document (a real nested tree: ncc-volume/
ncc-standard -> ncc-section -> part/specification/page -> subtopic -> clause
-> subclause -> content), with a sibling `images/` folder referenced by
direct filename (`<img src="...svg"/>`, no GUID indirection). This replaced
the old ~2360-file-per-clause DITA export entirely -- different schema, not
an incremental change.
"""

from dataclasses import dataclass
from pathlib import Path

import lxml.etree as ET


@dataclass
class Corpus:
    name: str  # short key, e.g. "vol2" / "housing"
    doc_label: str  # e.g. "NCC 2025 Volume Two"
    publishing_id: str  # root's own publishing-id, e.g. "vol2" / "housing"
    root: object  # lxml root element
    images_dir: Path


def load_corpus(name: str, doc_label: str, contents_xml: Path, images_dir: Path) -> Corpus:
    tree = ET.parse(str(contents_xml))
    root = tree.getroot()
    return Corpus(
        name=name,
        doc_label=doc_label,
        publishing_id=root.get("publishing-id"),
        root=root,
        images_dir=images_dir,
    )
