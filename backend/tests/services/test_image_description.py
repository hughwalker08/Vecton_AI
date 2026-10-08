"""
Tests for app.services.image_description -- Gemini vision transcription of
NCC/ABCB figures.

No real Gemini calls: describe_image_bytes() is run against a fake model
handle with google.generativeai.configure patched out. SVG rasterisation
runs against the real PyMuPDF (a hard requirement of requirements.txt), with
cairosvg/pymupdf swapped via sys.modules only for the branches that need a
missing-dependency or failing renderer. Key rotation resets between tests via
tests/services/conftest.py.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import google.generativeai as genai
import pytest
from google.api_core.exceptions import ResourceExhausted, TooManyRequests

from app.services import image_description as idesc
from app.services.image_description import ImageDescriptionError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
    b'<rect width="40" height="20" fill="red"/></svg>'
)


# --- mime_type_for ------------------------------------------------------


def test_mime_type_for_known_image_extensions():
    assert idesc.mime_type_for("figure.png") == "image/png"
    assert idesc.mime_type_for("figure.jpg") == "image/jpeg"


def test_mime_type_for_falls_back_when_mimetypes_does_not_know_the_extension(monkeypatch):
    # mimetypes misses .webp on some Windows/WSL setups -- see the source.
    monkeypatch.setattr(idesc.mimetypes, "guess_type", lambda name: (None, None))

    assert idesc.mime_type_for("figure.webp") == "image/webp"
    assert idesc.mime_type_for("figure.BMP") == "image/bmp"


def test_mime_type_for_defaults_to_png_for_an_unknown_extension(monkeypatch):
    monkeypatch.setattr(idesc.mimetypes, "guess_type", lambda name: (None, None))

    assert idesc.mime_type_for("figure.xyz") == "image/png"


def test_mime_type_for_ignores_a_non_image_guess():
    assert idesc.mime_type_for("notes.txt") == "image/png"


# --- rasterise_svg ------------------------------------------------------


def test_rasterise_svg_renders_a_real_svg_to_png_at_the_requested_width(monkeypatch):
    monkeypatch.setitem(sys.modules, "cairosvg", None)  # force the PyMuPDF path

    png = idesc.rasterise_svg(SVG, width=200)

    assert png.startswith(PNG_SIGNATURE)


def test_rasterise_svg_prefers_cairosvg_when_it_is_installed(monkeypatch):
    seen = {}

    def _svg2png(bytestring, output_width):
        seen.update(bytestring=bytestring, output_width=output_width)
        return b"cairo-png"

    monkeypatch.setitem(sys.modules, "cairosvg", SimpleNamespace(svg2png=_svg2png))

    assert idesc.rasterise_svg(SVG, width=321) == b"cairo-png"
    assert seen == {"bytestring": SVG, "output_width": 321}


def test_rasterise_svg_wraps_a_cairosvg_failure(monkeypatch):
    def _boom(**kwargs):
        raise ValueError("bad svg")

    monkeypatch.setitem(sys.modules, "cairosvg", SimpleNamespace(svg2png=_boom))

    with pytest.raises(ImageDescriptionError, match="could not rasterise SVG: bad svg"):
        idesc.rasterise_svg(SVG)


def test_rasterise_svg_falls_back_to_the_older_fitz_module_name(monkeypatch):
    import pymupdf

    monkeypatch.setitem(sys.modules, "cairosvg", None)
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    monkeypatch.setitem(sys.modules, "fitz", pymupdf)

    assert idesc.rasterise_svg(SVG, width=100).startswith(PNG_SIGNATURE)


def test_rasterise_svg_explains_what_to_install_when_no_renderer_exists(monkeypatch):
    monkeypatch.setitem(sys.modules, "cairosvg", None)
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    monkeypatch.setitem(sys.modules, "fitz", None)

    with pytest.raises(ImageDescriptionError, match="pip install pymupdf"):
        idesc.rasterise_svg(SVG)


def test_rasterise_svg_wraps_a_malformed_svg(monkeypatch):
    monkeypatch.setitem(sys.modules, "cairosvg", None)

    with pytest.raises(ImageDescriptionError, match="could not rasterise SVG"):
        idesc.rasterise_svg(b"this is not an svg")


def test_rasterise_svg_rejects_an_svg_with_no_drawable_area(monkeypatch):
    class _Doc:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def __getitem__(self, _index):
            return SimpleNamespace(rect=SimpleNamespace(width=0))

    monkeypatch.setitem(sys.modules, "cairosvg", None)
    monkeypatch.setitem(sys.modules, "pymupdf", SimpleNamespace(open=lambda **kwargs: _Doc()))

    with pytest.raises(ImageDescriptionError, match="no drawable area"):
        idesc.rasterise_svg(SVG)


# --- prepare_payload ----------------------------------------------------


def test_prepare_payload_rejects_empty_data():
    with pytest.raises(ImageDescriptionError, match="image is empty"):
        idesc.prepare_payload(b"", "figure.png")


def test_prepare_payload_passes_a_raster_image_through_with_its_mime_type():
    assert idesc.prepare_payload(b"raw-bytes", "figure.png") == (b"raw-bytes", "image/png")
    assert idesc.prepare_payload(b"raw-bytes", "figure.jpg")[1] == "image/jpeg"


def test_prepare_payload_rasterises_svg_and_reports_it_as_png(monkeypatch):
    monkeypatch.setattr(idesc, "rasterise_svg", lambda data: b"rendered")

    assert idesc.prepare_payload(b"<svg/>", "figure.SVG") == (b"rendered", "image/png")


def test_prepare_payload_rejects_an_image_over_the_inline_limit(monkeypatch):
    monkeypatch.setattr(idesc, "MAX_IMAGE_BYTES", 10)

    with pytest.raises(ImageDescriptionError, match="over the .* MB inline limit"):
        idesc.prepare_payload(b"x" * 11, "figure.png")


# --- with_caption -------------------------------------------------------


@pytest.mark.parametrize("caption", [None, "", "   \n"])
def test_with_caption_leaves_the_prompt_alone_for_a_missing_or_blank_caption(caption):
    assert idesc.with_caption("PROMPT", caption) == "PROMPT"


def test_with_caption_fences_the_caption_as_external_context():
    result = idesc.with_caption("PROMPT", "  Figure 12: Subfloor detail  ")

    assert result.startswith("PROMPT")
    assert "Figure 12: Subfloor detail" in result
    assert "NOT text printed on the" in result


def test_with_caption_treats_an_in_image_caption_as_printed_text():
    result = idesc.with_caption("PROMPT", "Figure 12", caption_in_image=True)

    assert "printed at the top of the image" in result
    assert "NOT text printed" not in result


# --- build_model --------------------------------------------------------


def test_build_model_requires_a_gemini_key(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEY", "")

    with pytest.raises(ImageDescriptionError, match="GEMINI_API_KEY is not set"):
        idesc.build_model()


def test_build_model_uses_the_configured_vision_model_by_default(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    monkeypatch.setattr(genai, "GenerativeModel", lambda name: SimpleNamespace(model_name=name))

    assert idesc.build_model().model_name == backend_settings.VISION_MODEL_NAME


def test_build_model_honours_an_explicit_model_name(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    monkeypatch.setattr(genai, "GenerativeModel", lambda name: SimpleNamespace(model_name=name))

    assert idesc.build_model("gemini-custom").model_name == "gemini-custom"


# --- _is_quota_error ----------------------------------------------------


def test_is_quota_error_recognises_both_google_quota_exceptions():
    assert idesc._is_quota_error(ResourceExhausted("quota")) is True
    assert idesc._is_quota_error(TooManyRequests("slow down")) is True


def test_is_quota_error_is_false_for_anything_else():
    assert idesc._is_quota_error(RuntimeError("boom")) is False


# --- describe_image_bytes ----------------------------------------------


class _FakeModel:
    """Stands in for genai.GenerativeModel. `behaviour` maps the key that was
    configured when generate_content ran to a response or an exception."""

    model_name = "fake-vision-model"

    def __init__(self, behaviour, configured):
        self._behaviour = behaviour
        self._configured = configured
        self.contents = []

    def generate_content(self, contents):
        self.contents.append(contents)
        result = self._behaviour[self._configured[-1]]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture()
def configured(monkeypatch):
    """Record every genai.configure(api_key=...) call, in order."""
    keys = []
    monkeypatch.setattr(genai, "configure", lambda api_key: keys.append(api_key))
    return keys


def _model(behaviour, configured):
    return _FakeModel(behaviour, configured)


def test_describe_image_bytes_returns_the_stripped_text_and_model_name(
    monkeypatch, backend_settings, configured
):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    model = _model({"key1": SimpleNamespace(text="  ## Figure\nFooting detail \n")}, configured)

    result = idesc.describe_image_bytes(b"png-bytes", "figure.png", model=model)

    assert result.text == "## Figure\nFooting detail"
    assert result.model == "fake-vision-model"
    assert result.prompt_version == idesc.PROMPT_VERSION
    assert configured == ["key1"]


def test_describe_image_bytes_sends_the_prompt_and_the_image_payload(
    monkeypatch, backend_settings, configured
):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    model = _model({"key1": SimpleNamespace(text="ok")}, configured)

    idesc.describe_image_bytes(b"png-bytes", "figure.png", model=model, prompt="MY PROMPT")

    prompt, image = model.contents[0]
    assert prompt == "MY PROMPT"
    assert image == {"mime_type": "image/png", "data": b"png-bytes"}


def test_describe_image_bytes_appends_the_caption_to_the_prompt(
    monkeypatch, backend_settings, configured
):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    model = _model({"key1": SimpleNamespace(text="ok")}, configured)

    idesc.describe_image_bytes(
        b"png-bytes", "figure.png", model=model, prompt="MY PROMPT", caption="Figure 12"
    )

    assert model.contents[0][0].startswith("MY PROMPT")
    assert "Figure 12" in model.contents[0][0]


def test_describe_image_bytes_honours_caption_in_image(monkeypatch, backend_settings, configured):
    # describe_image_bytes() accepts caption_in_image but used to drop it on
    # the floor, so the "caption is printed in the image" template was never
    # used and the model got the cautious "NOT text printed on the image"
    # fencing for figures where the caption *is* printed on the image.
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    model = _model({"key1": SimpleNamespace(text="ok")}, configured)

    idesc.describe_image_bytes(
        b"png-bytes", "figure.png", model=model, caption="Figure 12", caption_in_image=True
    )

    sent_prompt = model.contents[0][0]
    assert "printed at the top of the image" in sent_prompt
    assert "NOT text printed" not in sent_prompt


def test_describe_image_bytes_builds_its_own_model_when_none_is_given(
    monkeypatch, backend_settings, configured
):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    built = _model({"key1": SimpleNamespace(text="ok")}, configured)
    monkeypatch.setattr(idesc, "build_model", lambda name: built)

    assert idesc.describe_image_bytes(b"png-bytes", "figure.png").text == "ok"


def test_describe_image_bytes_rotates_to_the_next_key_after_a_quota_error(
    monkeypatch, backend_settings, configured
):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    model = _model(
        {"key1": ResourceExhausted("quota"), "key2": SimpleNamespace(text="from key2")}, configured
    )

    result = idesc.describe_image_bytes(b"png-bytes", "figure.png", model=model)

    assert result.text == "from key2"
    assert configured == ["key1", "key2"]


def test_describe_image_bytes_reports_a_clear_error_once_every_key_is_out(
    monkeypatch, backend_settings, configured
):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    model = _model({"key1": ResourceExhausted("quota"), "key2": ResourceExhausted("quota")}, configured)

    with pytest.raises(ImageDescriptionError, match="usage limit has been reached"):
        idesc.describe_image_bytes(b"png-bytes", "figure.png", model=model)


def test_describe_image_bytes_does_not_retry_a_non_quota_error(
    monkeypatch, backend_settings, configured
):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    model = _model({"key1": RuntimeError("network blew up")}, configured)

    with pytest.raises(ImageDescriptionError, match="Gemini request failed: network blew up"):
        idesc.describe_image_bytes(b"png-bytes", "figure.png", model=model)

    assert configured == ["key1"]  # never tried key2


@pytest.mark.parametrize("text", ["", "   ", None])
def test_describe_image_bytes_raises_when_the_model_returns_no_text(
    monkeypatch, backend_settings, configured, text
):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    response = SimpleNamespace(text=text, prompt_feedback="BLOCKED_BY_SAFETY")
    model = _model({"key1": response}, configured)

    with pytest.raises(ImageDescriptionError, match="no text .*BLOCKED_BY_SAFETY"):
        idesc.describe_image_bytes(b"png-bytes", "figure.png", model=model)


def test_describe_image_bytes_rejects_empty_image_data_before_calling_the_model(configured):
    with pytest.raises(ImageDescriptionError, match="image is empty"):
        idesc.describe_image_bytes(b"", "figure.png", model=_model({}, configured))

    assert configured == []


# --- describe_image -----------------------------------------------------


def test_describe_image_reads_the_file_and_uses_its_name_for_the_mime_type(
    monkeypatch, backend_settings, configured, tmp_path
):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    path = tmp_path / "figure.jpg"
    path.write_bytes(b"jpeg-bytes")
    model = _model({"key1": SimpleNamespace(text="described")}, configured)

    result = idesc.describe_image(path, model=model)

    assert result.text == "described"
    assert model.contents[0][1] == {"mime_type": "image/jpeg", "data": b"jpeg-bytes"}
