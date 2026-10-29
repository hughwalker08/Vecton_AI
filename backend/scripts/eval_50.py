"""
50-question retrieval/answer evaluation (40 in scope, 10 out of scope), run
through the real chat endpoint (FastAPI TestClient: live DB, Gemini, the
configured reranker). The question list and expected sources are in
retrieval-eval-50-questions.md at the repo root.

    cd backend && python scripts/eval_50.py out.json [--model NAME] [--resume] [--timeout SECONDS]

Writes every reply verbatim plus automatic screening checks (expected clause or
definition chip present, expected phrases in the answer, abstained or not).
These are a screen, not a verdict: "answer correct" and "cited text supports
it" still need a human read of the verbatim answers.

--resume skips questions already recorded with status 200, so a crash or a
quota error does not force a rerun of everything.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from eval_15 import ask  # noqa: E402

# id, question, jurisdiction, follow-up of (id of the question whose answer is
# sent as history), expected chip ids (any one), phrases the answer must contain
IN_SCOPE = [
    ("1", "What is the maximum riser height and minimum going for a standard (non-spiral) stair?", "NSW", None, ["11.2.2"], ["190", "240"]),
    ("2", "Are the stair dimension limits any different for a stair that only serves an attic or storeroom used occasionally?", "NSW", None, ["11.2.2"], ["225", "215"]),
    ("3", "How do the smoke alarm location requirements differ between a Class 1a and a Class 1b building?", "NSW", None, ["9.5.2", "9.5.3", "H3D6"], ["bedroom"]),
    ("4", "Which Australian Standards does the NCC refer to for smoke alarms?", "NSW", None, ["9.5.1", "H3D6"], ["3786"]),
    ("5", "How far from the shower rose must a waterstop be installed for an unenclosed shower?", "NSW", None, ["10.2.18"], ["1500"]),
    ("6", "What bushfire attack level applies in a medium bushfire risk area?", "SA", None, ["H7D4"], ["12.5"]),
    ("6b", "What bushfire attack level applies in a medium bushfire risk area?", "NSW", None, [], []),
    ("7", 'What does the NCC mean by a "habitable room"?', "NSW", None, ["Habitable room"], ["domestic activities"]),
    ("8", "What is the performance requirement for ventilation of a space used by occupants?", "NSW", None, ["H4P5"], ["air quality"]),
    ("9", "What is the maximum number of risers in a single flight of stairs?", "NSW", None, ["11.2.2"], ["18"]),
    ("10a", "What is the maximum riser height for stairs?", "NSW", None, [], ["190"]),
    ("10", "What about for a spiral stair?", "NSW", "10a", ["11.2.2"], ["220"]),
    ("11", "What is the minimum height of a handrail above the stair nosings?", "NSW", None, ["11.3.5"], ["865"]),
    ("12", "How high must a barrier be on a landing or balcony compared with along a stair?", "NSW", None, ["11.3.4"], ["865"]),
    ("13", "What size of opening must a barrier not allow to pass through?", "NSW", None, ["11.3.4"], ["125"]),
    ("14", "What is the minimum landing length for a stair that only serves an attic or storeroom?", "NSW", None, ["11.2.5"], ["600"]),
    ("15", "What is the minimum ceiling height for a habitable room, and is it different for a kitchen?", "NSW", None, ["10.3.1"], ["2.4", "2.1"]),
    ("16", "And for a corridor?", "NSW", "15", ["10.3.1"], ["2.1"]),
    ("17", "How much natural light must a habitable room get, as a share of its floor area?", "NSW", None, ["10.5.1"], ["10%"]),
    ("18", "How much ventilating opening area does a room need if it relies on natural ventilation?", "NSW", None, ["10.6.2"], ["5%"]),
    ("19", "How high must the walls of a shower area be waterproofed?", "NSW", None, ["10.2.2"], ["1800"]),
    ("20", "How far above the lip of an inserted bath must the walls be waterproofed?", "NSW", None, ["10.2.4"], ["150"]),
    ("21", "Which Australian Standards can be used to design footings and slabs?", "NSW", None, ["H1D4"], ["2870", "3600"]),
    ("22", "Which part of the Housing Provisions deals with termite risk management?", "NSW", None, ["H1D3"], ["3.4"]),
    ("23", "Which Australian Standard covers residential timber-framed construction in non-cyclonic areas?", "NSW", None, ["H1D6"], ["1684"]),
    ("24", "What is the maximum height of a cavity masonry wall under the Housing Provisions?", "NSW", None, ["5.3.2"], ["8.5"]),
    ("25", "Which Australian Standards apply to glass and windows at risk of human impact?", "NSW", None, ["H1D8"], ["1288", "2047"]),
    ("26", "Do smoke alarms in a house have to be connected to mains power?", "NSW", None, ["9.5.1"], ["mains"]),
    ("27", "And do they have to be interconnected?", "NSW", "26", ["9.5.1"], ["interconnect"]),
    ("28", "Which class of building needs a lighting system to help evacuation, triggered by the smoke alarm?", "NSW", None, ["9.5.5"], ["1b"]),
    ("29", "What is the performance requirement for smoke alarms?", "NSW", None, ["H3P2"], ["warning"]),
    ("30", "What heat flux must external walls withstand under the fire-spread verification method if less than 1.8 m from another building?", "NSW", None, ["H3V1"], ["92.6"]),
    ("31", "What bushfire attack level applies in a general bushfire risk area?", "SA", None, ["H7D4"], ["Low"]),
    ("32", "Which Australian Standard is used to assess the bushfire attack level for a high bushfire risk area?", "SA", None, ["H7D4"], ["3959"]),
    ("33", "Which standard applies if eaves gutters are installed with a fall less than 1:500?", "WA", None, ["7.4.4"], ["3500.3"]),
    ("34", 'What does the NCC mean by an "accredited testing laboratory"?', "NSW", None, ["Accredited Testing Laboratory"], ["NATA"]),
    ("35", 'What is the NCC definition of "storey"?', "NSW", None, ["Storey"], ["floor level"]),
    ("36", 'What is a "flight" of stairs?', "NSW", None, ["Flight"], ["risers"]),
    ("37", "Is a detached sleepout on the same allotment as a house part of the Class 1 building?", "NSW", None, ["A6G11"], ["Class 1"]),
    ("38", "How is a small toolshed on the same allotment as a house classified?", "NSW", None, ["A6G11"], ["Class 10"]),
    ("39", "What climate zone is Canberra in for thermal design?", "ACT", None, [], ["7"]),
    ("40", "Is Thredbo listed as an alpine area where snow loads are significant?", "NSW", None, [], ["Thredbo"]),
]
OUT_OF_SCOPE = [
    ("41", "What is the maximum building height allowed for a house under the Brisbane City Plan?"),
    ("42", "What fire resistance level is required for the structural frame of a Class 9a hospital?"),
    ("43", "What does clause H9Z7 of the NCC say?"),
    ("44", "How much will it cost to pour footings for a 200 sqm house in Sydney?"),
    ("45", "What's the best way to cook a medium-rare steak?"),
    ("46", "What does the New Zealand Building Code say about maximum stair riser heights?"),
    ("47", "What are the fire safety requirements for a 12-storey apartment building?"),
    ("48", "How do I appeal a council's refusal of my building application?"),
    ("49", "What is the current price of structural steel per tonne?"),
    ("50", "What licence do I need to work as a builder in NSW?"),
]


class _Timeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise _Timeout()


def main(out_path: str, resume: bool = False, timeout: int = 240) -> None:
    signal.signal(signal.SIGALRM, _on_alarm)
    client = TestClient(app)
    path = Path(out_path)
    results = json.loads(path.read_text()) if resume and path.exists() else {}

    def record(qid, question, jurisdiction, follow_of=None, expect_chips=(), expect_text=(), expect_abstain=None):
        if qid in results and results[qid].get("status") == 200:
            print(qid, "already recorded, skipping", flush=True)
            return
        history = []
        if follow_of:
            prev = results.get(follow_of)
            if not prev or prev.get("status") != 200:
                print(qid, "SKIPPED: its first message (%s) has no good answer yet" % follow_of, flush=True)
                return
            history = [{"role": "user", "text": prev["q"]}, {"role": "assistant", "text": prev["answer"]}]
        t0 = time.time()
        signal.alarm(timeout)  # a hung model call is recorded as a timeout, not a frozen run
        try:
            status, body = ask(client, question, jurisdiction, history)
        except _Timeout:
            status, body = 599, {"detail": "timed out after %d s" % timeout}
        finally:
            signal.alarm(0)
        answer = body.get("answer") or ""
        chips = [c.get("clause_id") for c in body.get("citations", [])]
        entry = {
            "q": question, "jurisdiction": jurisdiction, "history": history, "status": status,
            "model": settings.LLM_MODEL_NAME, "reranker": settings.RERANKER_BACKEND, "secs": round(time.time() - t0, 1),
            "abstained": body.get("abstained"), "answer": answer, "chips": chips, "detail": body.get("detail"),
        }
        if expect_chips:
            entry["chip_hit"] = any(c in chips for c in expect_chips)
        if expect_text:
            entry["text_missing"] = [t for t in expect_text if t.lower() not in answer.lower()]
        if expect_abstain is not None:
            entry["abstain_ok"] = bool(body.get("abstained")) and not chips
        results[qid] = entry
        path.write_text(json.dumps(results, indent=2))  # keep finished answers if a later call fails
        print(qid, status, "abst=%s" % entry["abstained"], "chips=%s" % chips[:6],
              "chip_hit=%s" % entry.get("chip_hit"), "missing=%s" % entry.get("text_missing"),
              "abstain_ok=%s" % entry.get("abstain_ok"), flush=True)

    for qid, q, j, follow, chips, texts in IN_SCOPE:
        record(qid, q, j, follow, chips, texts)
    for qid, q in OUT_OF_SCOPE:
        record(qid, q, "NSW", expect_abstain=True)


if __name__ == "__main__":
    if "--model" in sys.argv:
        settings.LLM_MODEL_NAME = sys.argv[sys.argv.index("--model") + 1]
    timeout = int(sys.argv[sys.argv.index("--timeout") + 1]) if "--timeout" in sys.argv else 240
    main(sys.argv[1], resume="--resume" in sys.argv, timeout=timeout)
