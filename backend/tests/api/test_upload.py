"""
Tests for POST /api/upload/ and GET /api/upload/supported-types.

app.services.document_images.describe_document_images is imported by name
into app.api.routes.upload's own namespace, so it's monkeypatched there --
no real image extraction or vision-model calls happen in this file.

Text extraction (LlamaParse for PDF / python-docx for DOCX) is documented
as not yet implemented (see the module docstring) -- the "not implemented"
stub value it reports is itself locked in by a test below, so this becomes
a real regression test the day that pipeline is actually wired up.
"""

from app.api.routes import upload
from app.services.document_images import DocumentImageReport, ImageFinding

_PDF_BYTES = b"%PDF-1.4 ..."


def _upload(client, filename="plan.pdf", data=_PDF_BYTES, **params):
    return client.post(
        "/api/upload/", params=params, files={"file": (filename, data, "application/pdf")}
    )


def _report(**overrides):
    base = dict(
        filename="plan.pdf", images_found=0, images_skipped=0, described=0, failed=0, findings=[]
    )
    base.update(overrides)
    return DocumentImageReport(**base)


def test_upload_rejects_an_empty_file(client):
    response = _upload(client, data=b"")

    assert response.status_code == 400


def test_upload_reports_text_extraction_is_not_yet_implemented(client, monkeypatch):
    """Locks in the documented stub -- becomes a real assertion on the actual
    extracted text once PDF/DOCX text parsing is wired up (see module docstring)."""
    monkeypatch.setattr(upload, "describe_document_images", lambda *a, **k: _report())

    response = _upload(client)

    assert response.status_code == 200
    assert response.json()["text_extraction"] == (
        "not implemented (LlamaParse for PDF / python-docx for DOCX)"
    )


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
        },
        {
            "name": "fig2.svg",
            "source": "plan.pdf#2",
            "description": None,
            "error": "unreadable image",
        },
    ]


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
