"""
Tests for POST /api/upload/ and GET /api/upload/supported-types.

app.services.document_images.describe_document_images and
app.services.document_text.extract_text are both imported by name into
app.api.routes.upload's own namespace, so they're monkeypatched there -- no
real image extraction, text extraction, or vision-model calls happen in this
file. See tests/services/test_document_text.py for real extraction coverage.
"""

import pytest

from app.api.routes import upload
from app.services.document_images import DocumentImageReport, ImageFinding

_PDF_BYTES = b"%PDF-1.4 ..."


@pytest.fixture(autouse=True)
def _stub_text_extraction(monkeypatch):
    """Every test in this file cares about the image pipeline or the upload
    plumbing, not real text extraction -- default it to a stub so the fake
    `_PDF_BYTES` above (not a real PDF) doesn't fail extraction and mask
    what each test is actually checking. Tests exercising extraction itself
    override this with their own monkeypatch.setattr call."""
    monkeypatch.setattr(upload, "extract_text", lambda *a, **k: "extracted text")


def _upload(client, filename="plan.pdf", data=_PDF_BYTES, **params):
    return client.post(
        "/api/upload/", params=params, files={"file": (filename, data, "application/pdf")}
    )


def _report(**overrides):
    base = dict(
        filename="plan.pdf",
        images_found=0,
        images_skipped=0,
        described=0,
        failed=0,
        captioned=0,
        findings=[],
    )
    base.update(overrides)
    return DocumentImageReport(**base)


def test_upload_rejects_an_empty_file(client):
    response = _upload(client, data=b"")

    assert response.status_code == 400


def test_upload_reports_extracted_text(client, monkeypatch):
    monkeypatch.setattr(upload, "describe_document_images", lambda *a, **k: _report())
    monkeypatch.setattr(upload, "extract_text", lambda data, filename: "Extracted body text.")

    response = _upload(client)

    assert response.status_code == 200
    assert response.json()["text_extraction"] == "Extracted body text."


def test_upload_text_extraction_failure_maps_to_400(client, monkeypatch):
    def _raise(*a, **k):
        raise ValueError("could not read PDF: not a PDF")

    monkeypatch.setattr(upload, "extract_text", _raise)

    response = _upload(client)

    assert response.status_code == 400
    assert "could not read PDF" in response.json()["detail"]


def test_upload_skips_image_transcription_when_disabled(client, monkeypatch):
    called = []
    monkeypatch.setattr(upload, "describe_document_images", lambda *a, **k: called.append(1))

    response = _upload(client, describe_images="false")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received - image transcription skipped"
    assert called == []


def test_upload_reports_described_images(client, monkeypatch):
    findings = [
        ImageFinding(name="fig1.svg", source="plan.pdf#1", description="A stair section."),
        ImageFinding(name="fig2.svg", source="plan.pdf#2", error="unreadable image"),
    ]
    report = _report(images_found=2, described=1, failed=1, findings=findings)
    monkeypatch.setattr(upload, "describe_document_images", lambda *a, **k: report)

    response = _upload(client)

    body = response.json()
    assert response.status_code == 200
    assert body["images_found"] == 2
    assert body["images_described"] == 1
    assert body["images_failed"] == 1
    assert body["status"] == "processed 1 image(s) from plan.pdf"
    assert body["images"] == [
        {
            "name": "fig1.svg",
            "source": "plan.pdf#1",
            "description": "A stair section.",
            "error": None,
            "caption": None,
            "caption_source": None,
        },
        {
            "name": "fig2.svg",
            "source": "plan.pdf#2",
            "description": None,
            "error": "unreadable image",
            "caption": None,
            "caption_source": None,
        },
    ]


def test_upload_reports_captions_and_their_source(client, monkeypatch):
    """A caption and how it was found both reach the caller.

    caption_source is the difference between a label the document's author
    wrote and one inferred from where text sat on the page, which is what a
    reviewer needs to know before trusting the association.
    """
    findings = [
        ImageFinding(
            name="img1.png",
            source="word/media/image1.png",
            description="A subfloor vent detail.",
            caption="Figure 12: Subfloor ventilation detail",
            caption_source="caption-style",
        ),
        ImageFinding(name="img2.png", source="word/media/image2.png", description="A logo."),
    ]
    report = _report(images_found=2, described=2, captioned=1, findings=findings)
    monkeypatch.setattr(upload, "describe_document_images", lambda *a, **k: report)

    body = _upload(client).json()

    assert body["images_captioned"] == 1
    assert body["images"][0]["caption"] == "Figure 12: Subfloor ventilation detail"
    assert body["images"][0]["caption_source"] == "caption-style"
    assert body["images"][1]["caption"] is None
    assert body["images"][1]["caption_source"] is None


def test_upload_status_when_no_images_are_transcribable(client, monkeypatch):
    monkeypatch.setattr(upload, "describe_document_images", lambda *a, **k: _report())

    response = _upload(client)

    assert response.json()["status"] == "no transcribable images found in plan.pdf"


def test_upload_truncated_flag_when_findings_were_capped(client, monkeypatch):
    # 3 matched images (5 found, 2 skipped as decorative) but only 1 finding
    # -- describe_document_images() hit max_images and stopped early.
    report = _report(
        images_found=5, images_skipped=2, described=1,
        findings=[ImageFinding(name="fig1.svg", source="plan.pdf#1", description="ok")],
    )
    monkeypatch.setattr(upload, "describe_document_images", lambda *a, **k: report)

    response = _upload(client)

    assert response.json()["truncated"] is True


def test_upload_document_image_error_maps_to_400(client, monkeypatch):
    def _raise(*a, **k):
        raise upload.DocumentImageError("not a valid PDF/DOCX")

    monkeypatch.setattr(upload, "describe_document_images", _raise)

    response = _upload(client, data=b"garbage")

    assert response.status_code == 400
    assert "not a valid PDF/DOCX" in response.json()["detail"]


def test_upload_image_description_error_maps_to_503(client, monkeypatch):
    def _raise(*a, **k):
        raise upload.ImageDescriptionError("GEMINI_API_KEY is not set")

    monkeypatch.setattr(upload, "describe_document_images", _raise)

    response = _upload(client)

    assert response.status_code == 503
    assert "Image transcription unavailable" in response.json()["detail"]


def test_supported_types_lists_pdf_and_docx(client):
    response = client.get("/api/upload/supported-types")

    assert response.status_code == 200
    types = response.json()["document_types"]
    assert ".pdf" in types
    assert ".docx" in types
