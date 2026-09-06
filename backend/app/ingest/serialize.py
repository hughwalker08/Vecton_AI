"""Write the parsed chunk list to a local JSON file (this phase's only output -- no DB writes)."""

import json
from pathlib import Path


def write_chunks(chunks: list, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump([c.to_dict() for c in chunks], f, ensure_ascii=False, indent=2)
