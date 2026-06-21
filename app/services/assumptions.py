import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from app.agents.assumptions import AssumptionModelProvider, OpenAIAssumptionProvider
from app.core.config import Settings
from app.core.exceptions import (
    AssumptionLedgerError,
    AssumptionLedgerNotConfiguredError,
)
from app.models.ambiguity import AmbiguityDetectionResult
from app.models.assumptions import AssumptionLedger, AssumptionLedgerResult
from app.models.conflicts import ConflictDetectionResult
from app.models.document import DocumentChunk
from app.models.requirements import RequirementIntelligenceResult
from app.models.understanding import SpecificationUnderstandingResult
from app.services.ambiguity import AmbiguityDetectionService
from app.services.assumption_store import AssumptionLedgerStore
from app.services.chunks import ChunkService
from app.services.conflicts import ConflictDetectionService
from app.services.requirements import RequirementIntelligenceService
from app.services.understanding import SpecificationUnderstandingService

PROMPT_VERSION = "assumption-ledger-v1"


class AssumptionLedgerService:
    """Audit AI outputs against source chunks and persist provenance."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        understanding_service: SpecificationUnderstandingService | None = None,
        requirement_service: RequirementIntelligenceService | None = None,
        ambiguity_service: AmbiguityDetectionService | None = None,
        conflict_service: ConflictDetectionService | None = None,
        store: AssumptionLedgerStore | None = None,
        provider: AssumptionModelProvider | None = None,
    ) -> None:
        self._settings = settings
        self._model = settings.openai_assumption_model
        self._chunk_service = chunk_service or ChunkService(settings)
        self._understanding_service = understanding_service or (
            SpecificationUnderstandingService(settings)
        )
        self._requirement_service = requirement_service or (
            RequirementIntelligenceService(settings)
        )
        self._ambiguity_service = ambiguity_service or AmbiguityDetectionService(
            settings
        )
        self._conflict_service = conflict_service or ConflictDetectionService(settings)
        self._store = store or AssumptionLedgerStore(
            settings.understanding_cache_db
        )
        self._provider = provider

    def get_ledger(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> AssumptionLedgerResult:
        chunks = self._chunk_service.get_chunks(document_id)
        understanding = self._understanding_service.understand(document_id)
        requirements = self._requirement_service.get_requirements(document_id)
        ambiguities = self._ambiguity_service.detect(document_id)
        conflicts = self._conflict_service.detect(document_id)
        context, output_references = self._assemble_context(
            document_id=document_id,
            chunks=chunks,
            understanding=understanding,
            requirements=requirements,
            ambiguities=ambiguities,
            conflicts=conflicts,
        )
        fingerprint = hashlib.sha256(context.encode("utf-8")).hexdigest()

        if not force_refresh:
            cached = self._store.get(
                document_id=document_id,
                fingerprint=fingerprint,
                model=self._model,
                prompt_version=PROMPT_VERSION,
            )
            if cached:
                ledger, analyzed_at = cached
                return self._response(
                    document_id=document_id,
                    ledger=ledger,
                    cached=True,
                    analyzed_at=analyzed_at,
                )

        try:
            provider = self._provider or self._create_provider(self._settings)
            ledger = provider.analyze(context)
            self._validate_provenance(
                ledger=ledger,
                chunks=chunks,
                output_references=output_references,
            )
        except AssumptionLedgerError:
            raise
        except Exception as error:
            raise AssumptionLedgerError(
                "The assumption ledger model call failed."
            ) from error

        analyzed_at = datetime.now(UTC)
        self._store.set(
            document_id=document_id,
            fingerprint=fingerprint,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            result=ledger,
            analyzed_at=analyzed_at,
        )
        return self._response(
            document_id=document_id,
            ledger=ledger,
            cached=False,
            analyzed_at=analyzed_at,
        )

    def _response(
        self,
        *,
        document_id: UUID,
        ledger: AssumptionLedger,
        cached: bool,
        analyzed_at: datetime,
    ) -> AssumptionLedgerResult:
        return AssumptionLedgerResult(
            document_id=document_id,
            facts=ledger.facts,
            assumptions=ledger.assumptions,
            total_facts=len(ledger.facts),
            total_assumptions=len(ledger.assumptions),
            pending_confirmation=sum(
                item.needs_confirmation for item in ledger.assumptions
            ),
            cached=cached,
            model=self._model,
            prompt_version=PROMPT_VERSION,
            analyzed_at=analyzed_at,
        )

    @classmethod
    def _assemble_context(
        cls,
        *,
        document_id: UUID,
        chunks: list[DocumentChunk],
        understanding: SpecificationUnderstandingResult,
        requirements: RequirementIntelligenceResult,
        ambiguities: AmbiguityDetectionResult,
        conflicts: ConflictDetectionResult,
    ) -> tuple[str, set[str]]:
        outputs: list[dict[str, object]] = []
        references: set[str] = set()

        cls._append_understanding_outputs(outputs, references, understanding)
        for requirement in requirements.requirements:
            prefix = f"requirements.{requirement.requirement_id}"
            for field in (
                "title",
                "description",
                "priority",
                "confidence",
                "category",
            ):
                reference = f"{prefix}.{field}"
                references.add(reference)
                value = getattr(requirement, field)
                outputs.append(
                    {
                        "reference": reference,
                        "value": value.value if hasattr(value, "value") else value,
                        "source_chunk": requirement.source_chunk,
                    }
                )

        for assessment in ambiguities.assessments:
            for issue in assessment.issues:
                prefix = f"ambiguities.{issue.issue_id}"
                for field in (
                    "issue_type",
                    "severity",
                    "confidence",
                    "reason",
                    "clarification_question",
                    "recommended_stakeholder",
                ):
                    reference = f"{prefix}.{field}"
                    references.add(reference)
                    value = getattr(issue, field)
                    outputs.append(
                        {
                            "reference": reference,
                            "value": value.value if hasattr(value, "value") else value,
                            "source_chunk": issue.source_chunk,
                        }
                    )

        for conflict in conflicts.conflicts:
            prefix = f"conflicts.{conflict.conflict_id}"
            source_chunk = conflict.source_chunks[0]
            for field in (
                "conflict",
                "severity",
                "recommendation",
                "confidence",
            ):
                reference = f"{prefix}.{field}"
                references.add(reference)
                value = getattr(conflict, field)
                outputs.append(
                    {
                        "reference": reference,
                        "value": value.value if hasattr(value, "value") else value,
                        "source_chunk": source_chunk,
                    }
                )

        context = "\n\n".join(
            [
                f"DOCUMENT_ID: {document_id}",
                "SOURCE_CHUNKS:",
                json.dumps(
                    [
                        {
                            "chunk_id": chunk.id,
                            "page": chunk.page,
                            "heading": chunk.heading,
                            "section": chunk.section,
                            "text": chunk.text,
                        }
                        for chunk in chunks
                    ],
                    indent=2,
                ),
                "AI_OUTPUTS_TO_AUDIT:",
                json.dumps(outputs, indent=2),
            ]
        )
        return context, references

    @staticmethod
    def _append_understanding_outputs(
        outputs: list[dict[str, object]],
        references: set[str],
        result: SpecificationUnderstandingResult,
    ) -> None:
        understanding = result.understanding
        scalar_fields = ("document_type", "project_summary")
        for field in scalar_fields:
            reference = f"understanding.{field}"
            references.add(reference)
            outputs.append(
                {
                    "reference": reference,
                    "value": getattr(understanding, field),
                    "source_chunk": None,
                }
            )
        list_fields = (
            "business_objectives",
            "business_rules",
            "constraints",
            "explicit_assumptions",
        )
        for field in list_fields:
            for index, value in enumerate(getattr(understanding, field)):
                reference = f"understanding.{field}[{index}]"
                references.add(reference)
                outputs.append(
                    {
                        "reference": reference,
                        "value": value,
                        "source_chunk": None,
                    }
                )
        object_fields = ("stakeholders", "actors", "modules", "workflows", "integrations")
        for field in object_fields:
            for index, value in enumerate(getattr(understanding, field)):
                reference = f"understanding.{field}[{index}]"
                references.add(reference)
                outputs.append(
                    {
                        "reference": reference,
                        "value": value.model_dump(mode="json"),
                        "source_chunk": None,
                    }
                )

    @staticmethod
    def _validate_provenance(
        *,
        ledger: AssumptionLedger,
        chunks: list[DocumentChunk],
        output_references: set[str],
    ) -> None:
        valid_chunks = {chunk.id for chunk in chunks}
        all_ids = [item.fact_id for item in ledger.facts] + [
            item.assumption_id for item in ledger.assumptions
        ]
        if len(all_ids) != len(set(all_ids)):
            raise AssumptionLedgerError(
                "Fact and assumption IDs must be unique within a document."
            )

        records = [*ledger.facts, *ledger.assumptions]
        for record in records:
            if record.source_chunk not in valid_chunks:
                raise AssumptionLedgerError(
                    "Ledger records must reference valid source chunks."
                )
            unknown_outputs = set(record.affected_outputs) - output_references
            if unknown_outputs:
                raise AssumptionLedgerError(
                    "Ledger records referenced unknown affected outputs: "
                    + ", ".join(sorted(unknown_outputs))
                )

    @staticmethod
    def _create_provider(settings: Settings) -> AssumptionModelProvider:
        api_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key is not None
            else ""
        )
        if not api_key:
            raise AssumptionLedgerNotConfiguredError(
                "OPENAI_API_KEY is required to build the assumption ledger."
            )
        return OpenAIAssumptionProvider(
            api_key=api_key,
            model=settings.openai_assumption_model,
        )

