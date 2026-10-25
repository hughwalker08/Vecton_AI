"""
15-question retrieval/answer evaluation, run through the real chat endpoint
(FastAPI TestClient: live DB, Gemini, configured reranker).

    cd backend && python scripts/eval_15.py out.json [--model NAME] [--resume]

Writes every reply verbatim to out.json plus automatic checks: whether the
expected clause appears among the citation chips, and whether the expected
figures/phrases appear in the answer. Those checks are a screen, not a verdict
-- "answer correct" and "cited text supports it" still need a human read of
the verbatim answers.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402

Q10A = "What is the maximum riser height for stairs?"

# id, question, jurisdiction, expected clause ids in chips, phrases that must
# appear in the answer, history question (for the follow-up).
IN_SCOPE = [
    ("1", "What is the maximum riser height and minimum going for a standard (non-spiral) stair?", "NSW", ["11.2.2"], ["190", "240"]),
    ("2", "Are the stair dimension limits any different for a stair that only serves an attic or storeroom used occasionally?", "NSW", ["11.2.2"], ["225", "215"]),
    ("3", "How do the smoke alarm location requirements differ between a Class 1a and a Class 1b building?", "NSW", ["9.5.2", "9.5.3", "H3D6"], ["bedroom"]),
    ("4", "Which Australian Standards does the NCC refer to for smoke alarms?", "NSW", ["H3D6", "9.5.1"], ["3786"]),
    ("5", "How far from the shower rose must a waterstop be installed for an unenclosed shower?", "NSW", ["10.2.18"], ["1500"]),
    ("6", "What bushfire attack level applies in a medium bushfire risk area?", "SA", ["H7D4"], ["12.5"]),
    ("6b", "What bushfire attack level applies in a medium bushfire risk area?", "NSW", [], []),
    ("7", 'What does the NCC mean by a "habitable room"?', "NSW", [], ["domestic activities"]),
    ("8", "What is the performance requirement for ventilation of a space used by occupants?", "NSW", ["H4P5"], ["air quality"]),
    ("9", "What is the maximum number of risers in a single flight of stairs?", "NSW", ["11.2.2"], ["18"]),
]
OUT_OF_SCOPE = [
    ("11", "What is the maximum building height allowed for a house under the Brisbane City Plan?"),
    ("12", "What fire resistance level is required for the structural frame of a Class 9a hospital?"),
    ("13", "What does clause H9Z7 of the NCC say?"),
    ("14", "How much will it cost to pour footings for a 200 sqm house in Sydney?"),
    ("15", "What's the best way to cook a medium-rare steak?"),
]


def ask(client, question, jurisdiction, history=None, tries=6):
    for attempt in range(tries):
        try:
            r = client.post("/api/chat/", json={"question": question, "jurisdiction": jurisdiction, "history": history or []})
        except Exception as exc:  # a dropped DB connection etc.: retry, don't lose the run
            print("  request raised %s, retrying" % type(exc).__name__, flush=True)
            if attempt == tries - 1:
                raise
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code in (502, 503) and attempt < tries - 1:
            time.sleep(15 * (attempt + 1))
            continue
        break
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return r.status_code, body


def main(out_path: str, resume: bool = False) -> None:
    client = TestClient(app)
    results = json.loads(Path(out_path).read_text()) if resume and Path(out_path).exists() else {}

    def record(qid, question, jurisdiction, history=None, expect_clauses=(), expect_text=()):
        if qid in results and results[qid].get("status") == 200:
            print(qid, "already recorded, skipping", flush=True)
            return results[qid]["answer"]
        t0 = time.time()
        status, body = ask(client, question, jurisdiction, history)
        answer = body.get("answer") or ""
        chips = [c.get("clause_id") for c in body.get("citations", [])]
        entry = {
            "q": question, "jurisdiction": jurisdiction, "history": history or [],
            "status": status, "model": settings.LLM_MODEL_NAME, "secs": round(time.time() - t0, 1),
            "abstained": body.get("abstained"), "answer": answer, "chips": chips,
            "detail": body.get("detail"),
        }
        if expect_clauses:
            entry["clause_hit"] = any(c in chips for c in expect_clauses)
        if expect_text:
            entry["text_hit"] = [t for t in expect_text if t.lower() in answer.lower()]
            entry["text_missing"] = [t for t in expect_text if t.lower() not in answer.lower()]
        results[qid] = entry
        Path(out_path).write_text(json.dumps(results, indent=2))  # keep finished answers if a later call fails
        print(qid, status, "abstained=%s" % entry["abstained"], "chips=%s" % chips[:8],
              "clause_hit=%s" % entry.get("clause_hit"), "missing=%s" % entry.get("text_missing"), flush=True)
        return answer

    for qid, q, j, clauses, texts in IN_SCOPE:
        record(qid, q, j, expect_clauses=clauses, expect_text=texts)

    first = record("10a", Q10A, "NSW", expect_text=["190"])
    history = [{"role": "user", "text": Q10A}, {"role": "assistant", "text": first}]
    record("10", "What about for a spiral stair?", "NSW", history=history,
           expect_clauses=["11.2.2"], expect_text=["220"])

    for qid, q in OUT_OF_SCOPE:
        record(qid, q, "NSW")

    Path(out_path).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    if "--model" in sys.argv:
        settings.LLM_MODEL_NAME = sys.argv[sys.argv.index("--model") + 1]
    main(sys.argv[1], resume="--resume" in sys.argv)
