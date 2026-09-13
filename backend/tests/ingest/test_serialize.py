import json

from app.ingest.records import ChunkRecord
from app.ingest.serialize import write_chunks


def test_write_chunks_writes_a_json_list_of_chunk_dicts(tmp_path):
    chunks = [
        ChunkRecord(id="c1", node_type="subclause", text="Riser height must not exceed 190mm."),
        ChunkRecord(id="c2", node_type="note", text="See also Part 9.6."),
    ]
    out_path = tmp_path / "out" / "chunks.json"

    write_chunks(chunks, out_path)

    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert [c["id"] for c in written] == ["c1", "c2"]
    assert written[0]["text"] == "Riser height must not exceed 190mm."


def test_write_chunks_creates_missing_parent_directories(tmp_path):
    out_path = tmp_path / "a" / "b" / "c" / "chunks.json"

    write_chunks([], out_path)

    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8")) == []
