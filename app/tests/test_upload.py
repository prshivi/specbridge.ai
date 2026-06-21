from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes import upload
from app.core.config import Settings
from app.main import app

client = TestClient(app)


def test_upload_parses_and_stores_document(
    tmp_path: Path,
    samples_dir: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        upload_dir=tmp_path,
        chroma_dir=tmp_path / "chroma",
        chroma_collection="test_upload_success",
        max_upload_size_mb=1,
    )
    monkeypatch.setattr(upload, "get_settings", lambda: settings)

    response = client.post(
        "/upload",
        files={
            "file": (
                "requirements.txt",
                (samples_dir / "sample.txt").read_bytes(),
                "text/plain",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "requirements.txt"
    assert body["document_type"] == "txt"
    assert "validated before storage" in body["extracted_text"]
    assert (tmp_path / body["storage_key"]).read_bytes() == (
        samples_dir / "sample.txt"
    ).read_bytes()


def test_upload_rejects_unsupported_extension(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        chroma_collection="test_upload_extension",
    )
    monkeypatch.setattr(upload, "get_settings", lambda: settings)

    response = client.post(
        "/upload",
        files={"file": ("requirements.exe", b"not allowed", "application/octet-stream")},
    )

    assert response.status_code == 415
    assert "Unsupported file extension" in response.json()["detail"]
    assert not settings.upload_dir.exists()


def test_upload_rejects_empty_file(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        chroma_collection="test_upload_empty",
    )
    monkeypatch.setattr(upload, "get_settings", lambda: settings)

    response = client.post(
        "/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The uploaded file is empty."


def test_upload_rejects_oversized_file(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        chroma_collection="test_upload_large",
        max_upload_size_mb=1,
    )
    monkeypatch.setattr(upload, "get_settings", lambda: settings)

    response = client.post(
        "/upload",
        files={"file": ("large.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
    )

    assert response.status_code == 413
