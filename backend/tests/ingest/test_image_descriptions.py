"""
Tests for app.ingest.image_descriptions -- the on-disk store of figure
transcriptions that ingest reads (offline, no API key) to make figure chunks
searchable. describe_missing() is the opt-in path that generates the gaps; it
runs here against a monkeypatched describe_image(), so no Gemini calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.ingest.image_descriptions import DescriptionStore, describe_missing, figure_text, load_store
from app.services import image_description as svc

# --- DescriptionStore ---------------------------------------------------


def test_store_looks_a_figure_up_by_filename_ignoring_directories():
    store = DescriptionStore({"ncc_vol2/part_11/figure_11_2_2.png": "stairs"})

    assert store.get("figure_11_2_2.png") == "stairs"
    assert store.get("some/other/dir/figure_11_2_2.png") == "stairs"


def test_store_falls_back_to_the_filename_stem():
    # The store is built from rasterised PNGs, but the corpus references the
    # original <img src="figure.svg"/> -- the stem is what lines them up.
    store = DescriptionStore({"figure_11_2_2.png": "stairs"})

    assert store.get("figure_11_2_2.svg") == "stairs"


def test_store_prefers_an_exact_filename_over_a_stem_match():
    store = DescriptionStore({"fig.png": "the png", "fig.svg": "the svg"})

    assert store.get("fig.svg") == "the svg"
    assert store.get("fig.png") == "the png"


def test_store_returns_none_for_an_unknown_or_empty_filename():
    store = DescriptionStore({"fig.png": "x"})

    assert store.get("missing.png") is None
    assert store.get("") is None
    assert store.get(None) is None


def test_store_length_and_truthiness_reflect_how_many_figures_it_holds():
    assert len(DescriptionStore()) == 0
    assert not DescriptionStore()

    store = DescriptionStore({"a.png": "x", "b.png": "y"})
    assert len(store) == 2
    assert store


# --- load_store ---------------------------------------------------------


def _jsonl(path, *records):
    path.write_text("\n".join(json.dumps(r) if not isinstance(r, str) else r for r in records) + "\n")


def test_load_store_reads_a_jsonl_store(tmp_path):
    path = tmp_path / "descriptions.jsonl"
    _jsonl(path, {"image": "a.png", "description": "first"}, {"image": "b.png", "description": "second"})

    store = load_store(path)

    assert store.get("a.png") == "first"
    assert store.get("b.png") == "second"


def test_load_store_skips_blank_lines_bad_json_and_incomplete_records(tmp_path):
    path = tmp_path / "descriptions.jsonl"
    _jsonl(
        path,
        {"image": "good.png", "description": "kept"},
        "",
        "{not json",
        {"image": "no-description.png"},
        {"description": "no-image"},
        {"image": "empty-description.png", "description": ""},
    )

    store = load_store(path)

    assert len(store) == 1
    assert store.get("good.png") == "kept"


def test_load_store_reads_the_flat_json_index_and_skips_non_string_or_blank_values(tmp_path):
    path = tmp_path / "descriptions.json"
    path.write_text(json.dumps({"a.png": "kept", "b.png": "   ", "c.png": 123, "d.png": None}))

    store = load_store(path)

    assert len(store) == 1
    assert store.get("a.png") == "kept"


def test_load_store_ignores_a_json_file_that_is_not_an_object(tmp_path):
    path = tmp_path / "descriptions.json"
    path.write_text(json.dumps(["not", "an", "object"]))

    assert len(load_store(path)) == 0


def test_load_store_ignores_an_invalid_json_file(tmp_path):
    path = tmp_path / "descriptions.json"
    path.write_text("{broken")

    assert len(load_store(path)) == 0


def test_load_store_ignores_missing_and_empty_paths(tmp_path):
    # Ingest runs fine with no descriptions at all -- it just writes thinner
    # figure chunks -- so a missing store must not be an error.
    assert len(load_store(tmp_path / "does-not-exist.jsonl", None)) == 0


def test_load_store_lets_later_paths_win_on_conflict(tmp_path):
    first, second = tmp_path / "first.jsonl", tmp_path / "second.jsonl"
    _jsonl(first, {"image": "a.png", "description": "old"})
    _jsonl(second, {"image": "a.png", "description": "new"})

    assert load_store(first, second).get("a.png") == "new"


# --- figure_text --------------------------------------------------------


def test_figure_text_puts_the_title_first_then_the_description():
    assert figure_text("Figure 1: Stairs", "Riser 190 mm") == "Figure 1: Stairs\n\nRiser 190 mm"


def test_figure_text_handles_a_missing_title_or_description():
    assert figure_text("Figure 1", None) == "Figure 1"
    assert figure_text(None, "Riser 190 mm") == "Riser 190 mm"
    assert figure_text("  ", "") == ""


# --- describe_missing ---------------------------------------------------


def _fake_describe(results):
    """A describe_image() stand-in: `results` maps filename -> text or exception."""
    calls = []

    def _describe(path, model=None):
        calls.append(path.name)
        outcome = results[path.name]
        if isinstance(outcome, Exception):
            raise outcome
        return svc.Description(text=outcome, model="fake-model")

    return _describe, calls


def test_describe_missing_does_nothing_when_every_figure_already_has_a_description(tmp_path):
    messages = []
    store = DescriptionStore({"a.png": "x"})

    written = describe_missing(store, tmp_path, ["a.png"], tmp_path / "out.jsonl", progress=messages.append)

    assert written == 0
    assert messages == ["All matched figures already have descriptions."]
    assert not (tmp_path / "out.jsonl").exists()


def test_describe_missing_describes_only_the_gaps_and_appends_jsonl(tmp_path, monkeypatch):
    describe, calls = _fake_describe({"new.png": "a new description"})
    monkeypatch.setattr(svc, "describe_image", describe)
    store = DescriptionStore({"have.png": "already"})
    out = tmp_path / "nested" / "out.jsonl"

    written = describe_missing(
        store, tmp_path, ["have.png", "new.png", "new.png"], out, model=SimpleNamespace(), progress=lambda _m: None
    )

    assert written == 1
    assert calls == ["new.png"]  # the existing figure and the duplicate are skipped
    record = json.loads(out.read_text().strip())
    assert record["image"] == "new.png"
    assert record["description"] == "a new description"
    assert record["model"] == "fake-model"
    assert record["prompt_version"] == svc.PROMPT_VERSION
    assert record["chars"] == len("a new description")
    assert store.get("new.png") == "a new description"  # also added to the live store


def test_describe_missing_carries_on_after_a_failed_figure(tmp_path, monkeypatch):
    describe, _calls = _fake_describe(
        {
            "bad.png": svc.ImageDescriptionError("model returned no text"),
            "unreadable.png": OSError("disk error"),
            "weird.png": RuntimeError("transport fault"),
            "good.png": "described",
        }
    )
    monkeypatch.setattr(svc, "describe_image", describe)
    messages = []
    out = tmp_path / "out.jsonl"

    written = describe_missing(
        DescriptionStore(),
        tmp_path,
        ["bad.png", "unreadable.png", "weird.png", "good.png"],
        out,
        model=SimpleNamespace(),
        progress=messages.append,
    )

    assert written == 1
    assert [json.loads(line)["image"] for line in out.read_text().splitlines()] == ["good.png"]
    assert any("FAILED bad.png: model returned no text" in m for m in messages)
    assert any("FAILED unreadable.png: disk error" in m for m in messages)
    # An unexpected exception type is reported with its class name.
    assert any("FAILED weird.png: RuntimeError: transport fault" in m for m in messages)
    assert messages[-1] == f"Wrote 1 new description(s) to {out}"


def test_describe_missing_builds_a_model_when_none_is_given(tmp_path, monkeypatch):
    describe, _calls = _fake_describe({"new.png": "described"})
    built = []
    monkeypatch.setattr(svc, "describe_image", describe)
    monkeypatch.setattr(svc, "build_model", lambda: built.append(True) or SimpleNamespace())

    describe_missing(DescriptionStore(), tmp_path, ["new.png"], tmp_path / "out.jsonl", progress=lambda _m: None)

    assert built == [True]

