import csv
import io
from collections import defaultdict
from uuid import UUID

from app.models.ambiguity import AmbiguityDetectionResult
from app.models.architecture import ArchitectureRecommendationResult
from app.models.assumptions import AssumptionLedgerResult
from app.models.conflicts import ConflictDetectionResult
from app.models.document import DocumentChunk
from app.models.engineering import EngineeringArtifact, EngineeringTranslationResult
from app.models.requirements import Requirement, RequirementIntelligenceResult
from app.models.traceability import (
    SourceSection,
    TraceabilityArtifact,
    TraceabilityAssumption,
    TraceabilityClarification,
    TraceabilityMatrix,
    TraceabilityRisk,
    TraceabilityRow,
)
from app.services.ambiguity import AmbiguityDetectionService
from app.services.architecture import ArchitectureRecommendationService
from app.services.assumptions import AssumptionLedgerService
from app.services.chunks import ChunkService
from app.services.conflicts import ConflictDetectionService
from app.services.requirements import RequirementIntelligenceService
from app.services.translator import BusinessToEngineeringTranslatorService
from app.core.config import Settings

CSV_COLUMNS = [
    "requirement_id",
    "business_requirement",
    "category",
    "priority",
    "user_stories",
    "apis",
    "database_entities",
    "backend_tasks",
    "acceptance_criteria",
    "assumptions",
    "clarifications",
    "risks",
    "source_chunk",
    "source_page",
    "source_heading",
    "source_section",
]


class TraceabilityService:
    """Assemble deterministic end-to-end requirement traceability."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        requirement_service: RequirementIntelligenceService | None = None,
        translator_service: BusinessToEngineeringTranslatorService | None = None,
        assumption_service: AssumptionLedgerService | None = None,
        ambiguity_service: AmbiguityDetectionService | None = None,
        conflict_service: ConflictDetectionService | None = None,
        architecture_service: ArchitectureRecommendationService | None = None,
    ) -> None:
        self._chunk_service = chunk_service or ChunkService(settings)
        self._requirement_service = requirement_service or (
            RequirementIntelligenceService(settings)
        )
        self._translator_service = translator_service or (
            BusinessToEngineeringTranslatorService(settings)
        )
        self._assumption_service = assumption_service or AssumptionLedgerService(
            settings
        )
        self._ambiguity_service = ambiguity_service or AmbiguityDetectionService(
            settings
        )
        self._conflict_service = conflict_service or ConflictDetectionService(settings)
        self._architecture_service = architecture_service or (
            ArchitectureRecommendationService(settings)
        )

    def build(self, document_id: UUID) -> TraceabilityMatrix:
        chunks = self._chunk_service.get_chunks(document_id)
        requirements = self._requirement_service.get_requirements(document_id)
        engineering = self._translator_service.translate(document_id)
        assumptions = self._assumption_service.get_ledger(document_id)
        ambiguities = self._ambiguity_service.detect(document_id)
        conflicts = self._conflict_service.detect(document_id)
        architecture = self._architecture_service.recommend(document_id)

        rows = self._build_rows(
            chunks=chunks,
            requirements=requirements,
            engineering=engineering,
            assumptions=assumptions,
            ambiguities=ambiguities,
            conflicts=conflicts,
            architecture=architecture,
        )
        return TraceabilityMatrix(
            document_id=document_id,
            rows=rows,
            total_requirements=len(rows),
            requirements_with_risks=sum(bool(row.risks) for row in rows),
            requirements_needing_clarification=sum(
                bool(row.clarifications) for row in rows
            ),
        )

    def export_csv(self, document_id: UUID) -> str:
        matrix = self.build(document_id)
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in matrix.rows:
            writer.writerow(self._csv_row(row))
        return output.getvalue()

    @classmethod
    def _build_rows(
        cls,
        *,
        chunks: list[DocumentChunk],
        requirements: RequirementIntelligenceResult,
        engineering: EngineeringTranslationResult,
        assumptions: AssumptionLedgerResult,
        ambiguities: AmbiguityDetectionResult,
        conflicts: ConflictDetectionResult,
        architecture: ArchitectureRecommendationResult,
    ) -> list[TraceabilityRow]:
        chunk_map = {chunk.id: chunk for chunk in chunks}
        translation = engineering.translation
        artifacts = {
            "user_stories": cls._index_artifacts(translation.user_stories),
            "apis": cls._index_artifacts(
                [*translation.rest_apis, *translation.openapi_draft.operations]
            ),
            "database_entities": cls._index_artifacts(
                translation.database_entities
            ),
            "backend_tasks": cls._index_artifacts(translation.backend_tasks),
            "acceptance_criteria": cls._index_artifacts(
                translation.acceptance_criteria
            ),
        }
        assumption_map = {item.assumption_id: item for item in assumptions.assumptions}
        requirement_assumptions = cls._index_assumptions(
            requirements.requirements,
            engineering,
            assumptions,
        )
        ambiguity_map = {
            assessment.requirement_id: assessment
            for assessment in ambiguities.assessments
        }
        conflict_map: dict[str, list[object]] = defaultdict(list)
        for conflict in conflicts.conflicts:
            for evidence in conflict.evidence:
                conflict_map[evidence.requirement_id].append(conflict)

        blocked_map = cls._index_blocked_outputs(translation.blocked_outputs)
        architecture_gaps = cls._index_architecture_gaps(architecture)
        rows: list[TraceabilityRow] = []
        for requirement in requirements.requirements:
            chunk = chunk_map.get(requirement.source_chunk)
            ambiguity = ambiguity_map.get(requirement.requirement_id)
            clarifications = []
            risks = []
            if ambiguity:
                for issue in ambiguity.issues:
                    clarifications.append(
                        TraceabilityClarification(
                            clarification_id=issue.issue_id,
                            question=issue.clarification_question,
                            recommended_stakeholder=issue.recommended_stakeholder,
                        )
                    )
                    risks.append(
                        TraceabilityRisk(
                            risk_id=issue.issue_id,
                            risk_type=issue.issue_type.value,
                            severity=issue.severity.value,
                            description=issue.reason,
                            confidence=issue.confidence,
                        )
                    )
            clarifications.extend(blocked_map[requirement.requirement_id])
            clarifications.extend(architecture_gaps[requirement.requirement_id])
            for conflict in conflict_map[requirement.requirement_id]:
                risks.append(
                    TraceabilityRisk(
                        risk_id=conflict.conflict_id,
                        risk_type="conflict",
                        severity=conflict.severity.value,
                        description=conflict.conflict,
                        confidence=conflict.confidence,
                    )
                )

            rows.append(
                TraceabilityRow(
                    requirement_id=requirement.requirement_id,
                    business_requirement=requirement.description,
                    category=requirement.category.value,
                    priority=requirement.priority.value,
                    user_stories=artifacts["user_stories"][
                        requirement.requirement_id
                    ],
                    apis=artifacts["apis"][requirement.requirement_id],
                    database_entities=artifacts["database_entities"][
                        requirement.requirement_id
                    ],
                    backend_tasks=artifacts["backend_tasks"][
                        requirement.requirement_id
                    ],
                    acceptance_criteria=artifacts["acceptance_criteria"][
                        requirement.requirement_id
                    ],
                    assumptions=[
                        TraceabilityAssumption(
                            assumption_id=assumption_id,
                            assumption=assumption_map[assumption_id].assumption,
                            confidence=assumption_map[assumption_id].confidence,
                            needs_confirmation=assumption_map[
                                assumption_id
                            ].needs_confirmation,
                        )
                        for assumption_id in sorted(
                            requirement_assumptions[requirement.requirement_id]
                        )
                        if assumption_id in assumption_map
                    ],
                    clarifications=cls._deduplicate(clarifications),
                    risks=cls._deduplicate(risks),
                    source_section=SourceSection(
                        source_chunk=requirement.source_chunk,
                        page=chunk.page if chunk else None,
                        heading=chunk.heading if chunk else None,
                        section=chunk.section if chunk else None,
                    ),
                )
            )
        return rows

    @staticmethod
    def _index_artifacts(
        artifacts: list[EngineeringArtifact],
    ) -> dict[str, list[TraceabilityArtifact]]:
        index: dict[str, list[TraceabilityArtifact]] = defaultdict(list)
        for artifact in artifacts:
            summary = TraceabilityService._artifact_summary(artifact)
            reference = TraceabilityArtifact(
                artifact_id=artifact.artifact_id,
                summary=summary,
                inferred=artifact.inferred,
            )
            for requirement_id in artifact.requirement_ids:
                index[requirement_id].append(reference)
        return index

    @staticmethod
    def _artifact_summary(artifact: EngineeringArtifact) -> str:
        for field in ("story", "summary", "name", "title", "description"):
            value = getattr(artifact, field, None)
            if value:
                return str(value)
        return artifact.artifact_id

    @classmethod
    def _index_assumptions(
        cls,
        requirements: list[Requirement],
        engineering: EngineeringTranslationResult,
        assumptions: AssumptionLedgerResult,
    ) -> dict[str, set[str]]:
        index: dict[str, set[str]] = defaultdict(set)
        translation = engineering.translation
        all_artifacts = [
            *translation.user_stories,
            *translation.acceptance_criteria,
            *translation.rest_apis,
            translation.openapi_draft,
            *translation.openapi_draft.operations,
            *translation.openapi_draft.schemas,
            *translation.database_entities,
            *translation.backend_tasks,
            *translation.integration_tasks,
            *translation.validation_rules,
            *translation.permissions,
            *translation.error_codes,
            *translation.event_suggestions,
            *translation.blocked_outputs,
        ]
        for artifact in all_artifacts:
            for requirement_id in artifact.requirement_ids:
                index[requirement_id].update(artifact.assumption_ids)
        for assumption in assumptions.assumptions:
            for requirement in requirements:
                if (
                    requirement.requirement_id in " ".join(assumption.affected_outputs)
                    or assumption.source_chunk == requirement.source_chunk
                ):
                    index[requirement.requirement_id].add(
                        assumption.assumption_id
                    )
        return index

    @staticmethod
    def _index_blocked_outputs(
        blocked_outputs: list[EngineeringArtifact],
    ) -> dict[str, list[TraceabilityClarification]]:
        index: dict[str, list[TraceabilityClarification]] = defaultdict(list)
        for blocked in blocked_outputs:
            clarification = TraceabilityClarification(
                clarification_id=blocked.artifact_id,
                question=blocked.clarification_question,
            )
            for requirement_id in blocked.requirement_ids:
                index[requirement_id].append(clarification)
        return index

    @staticmethod
    def _index_architecture_gaps(
        architecture: ArchitectureRecommendationResult,
    ) -> dict[str, list[TraceabilityClarification]]:
        index: dict[str, list[TraceabilityClarification]] = defaultdict(list)
        for gap in architecture.architecture.unresolved_decisions:
            clarification = TraceabilityClarification(
                clarification_id=gap.decision_id,
                question=gap.clarification_question,
            )
            for requirement_id in gap.requirement_ids:
                index[requirement_id].append(clarification)
        return index

    @staticmethod
    def _deduplicate(items: list[object]) -> list[object]:
        unique: dict[str, object] = {}
        for item in items:
            identifier = getattr(
                item,
                "clarification_id",
                getattr(item, "risk_id", repr(item)),
            )
            unique[str(identifier)] = item
        return list(unique.values())

    @staticmethod
    def _csv_row(row: TraceabilityRow) -> dict[str, str]:
        return {
            "requirement_id": row.requirement_id,
            "business_requirement": row.business_requirement,
            "category": row.category,
            "priority": row.priority,
            "user_stories": TraceabilityService._join_artifacts(row.user_stories),
            "apis": TraceabilityService._join_artifacts(row.apis),
            "database_entities": TraceabilityService._join_artifacts(
                row.database_entities
            ),
            "backend_tasks": TraceabilityService._join_artifacts(row.backend_tasks),
            "acceptance_criteria": TraceabilityService._join_artifacts(
                row.acceptance_criteria
            ),
            "assumptions": " | ".join(
                f"{item.assumption_id}: {item.assumption}"
                for item in row.assumptions
            ),
            "clarifications": " | ".join(
                f"{item.clarification_id}: {item.question}"
                for item in row.clarifications
            ),
            "risks": " | ".join(
                f"{item.risk_id} [{item.severity}]: {item.description}"
                for item in row.risks
            ),
            "source_chunk": row.source_section.source_chunk,
            "source_page": str(row.source_section.page or ""),
            "source_heading": row.source_section.heading or "",
            "source_section": row.source_section.section or "",
        }

    @staticmethod
    def _join_artifacts(items: list[TraceabilityArtifact]) -> str:
        return " | ".join(
            f"{item.artifact_id}: {item.summary}"
            + (" [inferred]" if item.inferred else "")
            for item in items
        )
