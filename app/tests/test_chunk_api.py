from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes import chunks as chunks_route
from app.api.routes import upload as upload_route
from app.core.config import Settings
from app.main import app

client = TestClient(app)


def test_upload_returns_statistics_and_visualization(
    tmp_path: Path,
    samples_dir: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        chroma_collection="test_semantic_chunks",
    )
    monkeypatch.setattr(upload_route, "get_settings", lambda: settings)
    monkeypatch.setattr(chunks_route, "get_settings", lambda: settings)

    upload_response = client.post(
        "/upload",
        files={
            "file": (
                "semantic_requirements.md",
                (samples_dir / "semantic_requirements.md").read_bytes(),
                "text/markdown",
            )
        },
    )

    assert upload_response.status_code == 201
    uploaded = upload_response.json()
    document_id = uploaded["id"]
    assert uploaded["chunk_statistics"]["total_chunks"] >= 6
    assert uploaded["chunk_statistics"]["chunks_by_type"]["requirement"] >= 1
    assert uploaded["chunk_statistics"]["chunks_by_type"]["table"] == 1

    statistics_response = client.get(
        f"/documents/{document_id}/chunks/statistics"
    )
    assert statistics_response.status_code == 200
    assert statistics_response.json() == uploaded["chunk_statistics"]

    visualization_response = client.get(
        f"/documents/{document_id}/chunks/visualization"
    )
    assert visualization_response.status_code == 200
    visualization = visualization_response.json()
    assert visualization["statistics"]["total_chunks"] >= 6
    assert len(visualization["nodes"]) == visualization["statistics"]["total_chunks"] + 1
    assert any(edge["relationship"] == "next" for edge in visualization["edges"])


def test_chunk_endpoints_return_not_found_for_unknown_document(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        chroma_dir=tmp_path / "chroma",
        chroma_collection="test_empty_chunks",
    )
    monkeypatch.setattr(chunks_route, "get_settings", lambda: settings)

    response = client.get(
        "/documents/00000000-0000-0000-0000-000000000000/chunks/statistics"
    )

    assert response.status_code == 404

