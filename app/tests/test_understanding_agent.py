from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import Settings
from app.models.document import ChunkType, DocumentChunk
from app.models.understanding import (
    Actor,
    Integration,
    SpecificationUnderstanding,
    Stakeholder,
    UnderstandingItem,
    Workflow,
)
from app.services.understanding import SpecificationUnderstandingService
from app.services.understanding_cache import UnderstandingCache


class StubChunkService:
    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self._chunks = chunks

    def get_chunks(self, document_id: UUID) -> list[DocumentChunk]:
        assert all(chunk.document_id == document_id for chunk in self._chunks)
        return self._chunks


class StubProvider:
    def __init__(self, result: SpecificationUnderstanding) -> None:
        self._result = result
        self.calls = 0
        self.context = ""

    def analyze(self, context: str) -> SpecificationUnderstanding:
        self.calls += 1
        self.context = context
        return self._result


def build_understanding() -> SpecificationUnderstanding:
    return SpecificationUnderstanding(
        document_type="Product requirements document",
        project_summary="A customer account registration capability.",
        business_objectives=["Reduce manual account creation."],
        stakeholders=[
            Stakeholder(
                name="Product team",
                description="Owns the registration capability.",
                responsibilities=["Define registration policy."],
            )
        ],
        actors=[
            Actor(
                name="Customer",
                description="Registers for an account.",
                actor_type="human",
            )
        ],
        modules=[
            UnderstandingItem(
                name="Registration",
                description="Validates and creates customer accounts.",
            )
        ],
        workflows=[
            Workflow(
                name="Register account",
                description="Creates a verified customer account.",
                actors=["Customer"],
                steps=["Enter details", "Validate email", "Create account"],
            )
        ],
        integrations=[
            Integration(
                name="Email verification",
                purpose="Verify customer email ownership.",
                external_system="Email provider",
            )
        ],
        business_rules=["One verified email may have one active account."],
        constraints=["Passwords must contain at least 12 characters."],
        explicit_assumptions=["Customers have access to their email inbox."],
    )


def test_understanding_analyzes_all_chunks_and_caches_result(tmp_path: Path) -> None:
    document_id = uuid4()
    chunks = [
        DocumentChunk(
            id=f"{document_id}:1",
            document_id=document_id,
            text="The platform must validate email addresses.",
            page=1,
            heading="Requirements",
            section="1.1",
            chunk_type=ChunkType.REQUIREMENT,
            chunk_number=1,
        ),
        DocumentChunk(
            id=f"{document_id}:2",
            document_id=document_id,
            text="BR-001: One email may have one active account.",
            page=2,
            heading="Business Rules",
            section="1.2",
            chunk_type=ChunkType.BUSINESS_RULE,
            chunk_number=2,
        ),
    ]
    provider = StubProvider(build_understanding())
    settings = Settings(
        understanding_cache_db=tmp_path / "cache.db",
        openai_understanding_model="test-model",
    )
    service = SpecificationUnderstandingService(
        settings,
        chunk_service=StubChunkService(chunks),
        cache=UnderstandingCache(settings.understanding_cache_db),
        provider=provider,
    )

    first = service.understand(document_id)
    second = service.understand(document_id)

    assert first.cached is False
    assert second.cached is True
    assert first.understanding == second.understanding
    assert provider.calls == 1
    assert "TOTAL_CHUNKS: 2" in provider.context
    assert "CHUNK 1" in provider.context
    assert "CHUNK 2" in provider.context
    assert "PAGE: 2" in provider.context


def test_force_refresh_bypasses_understanding_cache(tmp_path: Path) -> None:
    document_id = uuid4()
    chunk = DocumentChunk(
        id=f"{document_id}:1",
        document_id=document_id,
        text="The platform must register customers.",
        chunk_type=ChunkType.REQUIREMENT,
        chunk_number=1,
    )
    provider = StubProvider(build_understanding())
    settings = Settings(
        understanding_cache_db=tmp_path / "cache.db",
        openai_understanding_model="test-model",
    )
    service = SpecificationUnderstandingService(
        settings,
        chunk_service=StubChunkService([chunk]),
        provider=provider,
    )

    service.understand(document_id)
    refreshed = service.understand(document_id, force_refresh=True)

    assert refreshed.cached is False
    assert provider.calls == 2


def test_understanding_schema_does_not_include_downstream_outputs() -> None:
    schema = SpecificationUnderstanding.model_json_schema()
    properties = schema["properties"]

    assert "user_stories" not in properties
    assert "apis" not in properties
    assert "api_design" not in properties
