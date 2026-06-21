import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.agents.copilot import CopilotModelProvider, OpenAICopilotProvider
from app.core.config import Settings
from app.core.exceptions import (
    DeveloperCopilotError,
    DeveloperCopilotNotConfiguredError,
    DocumentChunksNotFoundError,
)
from app.models.architecture import ArchitectureRecommendation, MermaidDiagram
from app.models.copilot import CopilotAnswer, DeveloperCopilotResponse
from app.models.document import DocumentChunk
from app.models.requirements import RequirementIntelligenceResult
from app.services.architecture import ArchitectureRecommendationService
from app.services.chunks import ChunkService
from app.services.copilot_store import DeveloperCopilotStore
from app.services.requirements import RequirementIntelligenceService

PROMPT_VERSION = "developer-copilot-v1"


class DeveloperCopilotService:
    """Answer developer questions using only approved grounded sources."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        requirement_service: RequirementIntelligenceService | None = None,
        architecture_service: ArchitectureRecommendationService | None = None,
        store: DeveloperCopilotStore | None = None,
        provider: CopilotModelProvider | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_copilot_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._requirement_service = requirement_service or (
            RequirementIntelligenceService(settings)
        )
        self._architecture_service = architecture_service or (
            ArchitectureRecommendationService(settings)
        )
        self._store = store or DeveloperCopilotStore(
            settings.understanding_cache_db
        )
        self._provider = provider

    def ask(self, document_id: UUID, question: str) -> DeveloperCopilotResponse:
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )
        requirements = self._requirement_service.get_requirements(document_id)
        architecture = self._architecture_service.recommend(document_id)
        context, architecture_ids = self._assemble_context(
            document_id=document_id,
            question=question,
            chunks=chunks,
            requirements=requirements,
            architecture=architecture.architecture,
        )

        try:
            provider = self._provider or self._create_provider(self._settings)
            answer = provider.answer(context)
            self._validate_citations(
                answer=answer,
                chunks=chunks,
                requirements=requirements,
                architecture_ids=architecture_ids,
            )
        except DeveloperCopilotError:
            raise
        except Exception as error:
            raise DeveloperCopilotError(
                "The developer copilot model call failed."
            ) from error

        response = DeveloperCopilotResponse(
            interaction_id=str(uuid4()),
            document_id=document_id,
            question=question,
            answer=answer.answer,
            available=answer.available,
            clarification_question=answer.clarification_question,
            citations=answer.citations,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            answered_at=datetime.now(UTC),
        )
        self._store.add(response)
        return response

    @classmethod
    def _assemble_context(
        cls,
        *,
        document_id: UUID,
        question: str,
        chunks: list[DocumentChunk],
        requirements: RequirementIntelligenceResult,
        architecture: object,
    ) -> tuple[str, set[str]]:
        architecture_payload: list[dict[str, object]] = []
        architecture_ids: set[str] = set()
        for item in cls._iter_architecture_sources(architecture):
            identifier = (
                item.recommendation_id
                if isinstance(item, ArchitectureRecommendation)
                else item.diagram_id
            )
            architecture_ids.add(identifier)
            architecture_payload.append(
                {
                    "architecture_id": identifier,
                    "content": item.model_dump(mode="json"),
                }
            )
        for decision in architecture.unresolved_decisions:
            architecture_ids.add(decision.decision_id)
            architecture_payload.append(
                {
                    "architecture_id": decision.decision_id,
                    "content": decision.model_dump(mode="json"),
                }
            )

        payload = {
            "document_id": str(document_id),
            "question": question,
            "specification_chunks": [
                chunk.model_dump(mode="json") for chunk in chunks
            ],
            "requirements_and_business_rules": [
                requirement.model_dump(mode="json")
                for requirement in requirements.requirements
            ],
            "architecture_recommendations": architecture_payload,
        }
        return json.dumps(payload, indent=2), architecture_ids

    @staticmethod
    def _iter_architecture_sources(architecture: object) -> list[object]:
        return [
            architecture.style,
            *architecture.modules,
            *architecture.services,
            architecture.database,
            architecture.caching,
            architecture.messaging,
            architecture.authentication,
            *architecture.external_services,
            architecture.deployment,
            architecture.architecture_diagram,
            *architecture.sequence_diagrams,
        ]

    @staticmethod
    def _validate_citations(
        *,
        answer: CopilotAnswer,
        chunks: list[DocumentChunk],
        requirements: RequirementIntelligenceResult,
        architecture_ids: set[str],
    ) -> None:
        valid_chunks = {chunk.id for chunk in chunks}
        valid_requirements = {
            requirement.requirement_id for requirement in requirements.requirements
        }
        for citation in answer.citations:
            if citation.source_chunk not in valid_chunks:
                raise DeveloperCopilotError(
                    "Copilot answers referenced an unknown source chunk."
                )
            if set(citation.requirement_ids) - valid_requirements:
                raise DeveloperCopilotError(
                    "Copilot answers referenced unknown requirements."
                )
            if set(citation.architecture_ids) - architecture_ids:
                raise DeveloperCopilotError(
                    "Copilot answers referenced unknown architecture recommendations."
                )

    @staticmethod
    def _create_provider(settings: Settings) -> CopilotModelProvider:
        api_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise DeveloperCopilotNotConfiguredError(
                "OPENAI_API_KEY is required to use the developer copilot."
            )
        return OpenAICopilotProvider(
            api_key=api_key,
            model=settings.openai_copilot_model,
        )

