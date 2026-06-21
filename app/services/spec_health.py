from collections.abc import Iterable
from statistics import fmean
from uuid import UUID

from app.core.config import Settings
from app.models.ambiguity import AmbiguityIssue, AmbiguityType
from app.models.architecture import ArchitectureRecommendationResult
from app.models.assumptions import AssumptionLedgerResult
from app.models.conflicts import ConflictDetectionResult
from app.models.engineering import EngineeringTranslationResult
from app.models.document import ChunkType, DocumentChunk
from app.models.spec_health import (
    HealthAction,
    HealthMetric,
    HealthStatus,
    SpecHealthDashboard,
    SpecHealthStatistics,
)
from app.models.traceability import TraceabilityMatrix
from app.services.ambiguity import AmbiguityDetectionService
from app.services.architecture import ArchitectureRecommendationService
from app.services.assumptions import AssumptionLedgerService
from app.services.conflicts import ConflictDetectionService
from app.services.chunks import ChunkService
from app.services.traceability import TraceabilityService
from app.services.translator import BusinessToEngineeringTranslatorService

SEVERITY_WEIGHTS = {
    "critical": 32.0,
    "high": 20.0,
    "medium": 10.0,
    "low": 4.0,
}


class SpecHealthService:
    """Calculate deterministic specification readiness from stored analyses."""

    def __init__(
        self,
        settings: Settings,
        *,
        traceability_service: TraceabilityService | None = None,
        ambiguity_service: AmbiguityDetectionService | None = None,
        conflict_service: ConflictDetectionService | None = None,
        assumption_service: AssumptionLedgerService | None = None,
        translator_service: BusinessToEngineeringTranslatorService | None = None,
        architecture_service: ArchitectureRecommendationService | None = None,
        chunk_service: ChunkService | None = None,
    ) -> None:
        self._mock_ai = settings.mock_ai
        self._chunk_service = chunk_service or ChunkService(settings)
        self._traceability_service = traceability_service or TraceabilityService(
            settings
        )
        self._ambiguity_service = ambiguity_service or AmbiguityDetectionService(
            settings
        )
        self._conflict_service = conflict_service or ConflictDetectionService(settings)
        self._assumption_service = assumption_service or AssumptionLedgerService(
            settings
        )
        self._translator_service = translator_service or (
            BusinessToEngineeringTranslatorService(settings)
        )
        self._architecture_service = architecture_service or (
            ArchitectureRecommendationService(settings)
        )

    def generate(self, document_id: UUID) -> SpecHealthDashboard:
        if self._mock_ai:
            return self._generate_mock_dashboard(document_id)

        traceability = self._traceability_service.build(document_id)
        ambiguity = self._ambiguity_service.detect(document_id)
        conflicts = self._conflict_service.detect(document_id)
        assumptions = self._assumption_service.get_ledger(document_id)
        engineering = self._translator_service.translate(document_id)
        architecture = self._architecture_service.recommend(document_id)

        issues = [
            issue
            for assessment in ambiguity.assessments
            for issue in assessment.issues
        ]
        requirement_count = max(traceability.total_requirements, 1)
        metrics = self._calculate_metrics(
            traceability=traceability,
            issues=issues,
            conflicts=conflicts,
            assumptions=assumptions,
            engineering=engineering,
            architecture=architecture,
            requirement_count=requirement_count,
        )
        overall_score = round(
            sum(
                self._metric(metrics, key).score * weight
                for key, weight in {
                    "clarity": 0.15,
                    "completeness": 0.15,
                    "consistency": 0.15,
                    "technical_readiness": 0.15,
                    "architecture_readiness": 0.10,
                    "missing_information": 0.10,
                    "dependencies": 0.10,
                    "edge_cases": 0.10,
                }.items()
            ),
            1,
        )
        overall = self._build_metric(
            "overall_health",
            "Overall Health",
            overall_score,
            "Weighted readiness across specification quality and engineering coverage.",
        )
        actions = self._next_actions(
            traceability,
            issues,
            conflicts,
            assumptions,
            engineering,
            architecture,
        )
        lowest = sorted(metrics, key=lambda metric: metric.score)[:2]
        summary = (
            f"Overall specification health is {overall.score:.1f}/100 "
            f"({overall.status.value}). The strongest next gains are in "
            f"{lowest[0].label.lower()} and {lowest[1].label.lower()}."
        )
        return SpecHealthDashboard(
            document_id=document_id,
            analysis_mode="ai",
            metrics=metrics,
            overall_health=overall,
            summary=summary,
            next_actions=actions,
            statistics=SpecHealthStatistics(
                total_requirements=traceability.total_requirements,
                ambiguity_issues=len(issues),
                conflicts=conflicts.total_conflicts,
                pending_assumptions=assumptions.pending_confirmation,
                blocked_outputs=engineering.blocked_outputs,
                unresolved_architecture_decisions=architecture.unresolved_decisions,
                requirements_needing_clarification=(
                    traceability.requirements_needing_clarification
                ),
                requirements_with_risks=traceability.requirements_with_risks,
            ),
        )

    def _generate_mock_dashboard(self, document_id: UUID) -> SpecHealthDashboard:
        """Build a free local demo dashboard without claiming AI analysis."""
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            from app.core.exceptions import DocumentChunksNotFoundError

            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )

        type_counts = {
            chunk_type: sum(chunk.chunk_type == chunk_type for chunk in chunks)
            for chunk_type in ChunkType
        }
        total = len(chunks)
        structured = sum(
            bool(chunk.heading or chunk.section or chunk.page) for chunk in chunks
        ) / total
        semantic_types = sum(bool(type_counts[item]) for item in ChunkType)
        type_coverage = semantic_types / len(ChunkType)
        requirement_count = (
            type_counts[ChunkType.REQUIREMENT]
            + type_counts[ChunkType.BUSINESS_RULE]
        )
        acceptance_count = type_counts[ChunkType.ACCEPTANCE_CRITERIA]
        workflow_count = type_counts[ChunkType.WORKFLOW]
        table_count = type_counts[ChunkType.TABLE]

        metrics = [
            self._build_metric(
                "clarity",
                "Clarity",
                58 + structured * 30,
                "Mock estimate based on headings, sections, and page metadata.",
            ),
            self._build_metric(
                "completeness",
                "Completeness",
                50 + type_coverage * 35,
                "Mock estimate based on the variety of semantic content blocks.",
            ),
            self._build_metric(
                "consistency",
                "Consistency",
                72,
                "Demo score only; contradiction analysis is disabled in mock mode.",
            ),
            self._build_metric(
                "technical_readiness",
                "Technical Readiness",
                52 + min(requirement_count, 5) * 5 + min(acceptance_count, 3) * 4,
                "Mock estimate from requirement and acceptance-criteria blocks.",
            ),
            self._build_metric(
                "architecture_readiness",
                "Architecture Readiness",
                48 + min(workflow_count, 4) * 6 + min(table_count, 3) * 3,
                "Mock estimate from workflow and structured-data coverage.",
            ),
            self._build_metric(
                "missing_information",
                "Missing Information",
                48 + type_coverage * 32,
                "Mock information-coverage estimate; no semantic gap analysis ran.",
            ),
            self._build_metric(
                "dependencies",
                "Dependencies",
                60 + min(workflow_count, 4) * 5,
                "Mock estimate from workflow coverage; integrations were not analyzed.",
            ),
            self._build_metric(
                "edge_cases",
                "Edge Cases",
                45 + min(acceptance_count, 5) * 8,
                "Mock estimate from acceptance-criteria blocks.",
            ),
        ]
        overall_score = round(fmean(metric.score for metric in metrics), 1)
        overall = self._build_metric(
            "overall_health",
            "Overall Health",
            overall_score,
            "Local mock estimate for UI and workflow testing.",
        )
        lowest = sorted(metrics, key=lambda metric: metric.score)[:2]
        return SpecHealthDashboard(
            document_id=document_id,
            analysis_mode="mock",
            metrics=metrics,
            overall_health=overall,
            summary=(
                f"Mock health is {overall.score:.1f}/100. This validates the local "
                f"workflow only; {lowest[0].label.lower()} and "
                f"{lowest[1].label.lower()} are the lowest structural estimates."
            ),
            next_actions=self._mock_actions(chunks, type_counts),
            statistics=SpecHealthStatistics(
                total_requirements=requirement_count,
                ambiguity_issues=0,
                conflicts=0,
                pending_assumptions=0,
                blocked_outputs=0,
                unresolved_architecture_decisions=0,
                requirements_needing_clarification=0,
                requirements_with_risks=0,
            ),
            scoring_note=(
                "MOCK MODE: no LLM calls were made. Scores are structural demo "
                "estimates for local testing and are not specification analysis."
            ),
        )

    @staticmethod
    def _mock_actions(
        chunks: list[DocumentChunk],
        type_counts: dict[ChunkType, int],
    ) -> list[HealthAction]:
        actions = [
            HealthAction(
                priority="high",
                action="Review these demo scores with real AI mode before development.",
                reason=(
                    "Mock mode validates the product workflow but does not understand "
                    "meaning, ambiguity, conflicts, or architecture."
                ),
            )
        ]
        if not type_counts[ChunkType.ACCEPTANCE_CRITERIA]:
            actions.append(
                HealthAction(
                    priority="medium",
                    action="Add explicit acceptance criteria.",
                    reason="No acceptance-criteria block was detected structurally.",
                )
            )
        if not type_counts[ChunkType.WORKFLOW]:
            actions.append(
                HealthAction(
                    priority="medium",
                    action="Document key workflows and alternate paths.",
                    reason="No workflow block was detected structurally.",
                )
            )
        if any(not chunk.heading and not chunk.section for chunk in chunks):
            actions.append(
                HealthAction(
                    priority="low",
                    action="Improve heading and section structure.",
                    reason="Some chunks have no heading or section metadata.",
                )
            )
        return actions

    def _calculate_metrics(
        self,
        *,
        traceability: TraceabilityMatrix,
        issues: list[AmbiguityIssue],
        conflicts: ConflictDetectionResult,
        assumptions: AssumptionLedgerResult,
        engineering: EngineeringTranslationResult,
        architecture: ArchitectureRecommendationResult,
        requirement_count: int,
    ) -> list[HealthMetric]:
        clarity_types = {AmbiguityType.VAGUE_LANGUAGE, AmbiguityType.MISSING_ACTOR}
        completeness_types = {
            AmbiguityType.MISSING_ACTOR,
            AmbiguityType.MISSING_VALIDATION,
            AmbiguityType.UNDEFINED_BUSINESS_RULE,
            AmbiguityType.UNDEFINED_INTEGRATION,
        }
        edge_types = {
            AmbiguityType.MISSING_EDGE_CASE,
            AmbiguityType.MISSING_ERROR_HANDLING,
        }
        clarity = 100.0 - self._issue_penalty(issues, clarity_types, requirement_count)
        completeness = 100.0 - min(
            100.0,
            self._issue_penalty(issues, completeness_types, requirement_count)
            + engineering.blocked_outputs * 10.0 / requirement_count
            + architecture.unresolved_decisions * 8.0 / requirement_count,
        )
        conflict_penalty = (
            sum(
                SEVERITY_WEIGHTS[conflict.severity.value]
                for conflict in conflicts.conflicts
            )
            / requirement_count
        )
        consistency = 100.0 - min(100.0, conflict_penalty)

        core_coverage = [
            fmean(
                [
                    bool(row.user_stories),
                    bool(row.acceptance_criteria),
                    bool(row.backend_tasks),
                ]
            )
            for row in traceability.rows
        ]
        technical = (
            fmean(core_coverage) * 100.0 if core_coverage else 0.0
        ) - min(30.0, engineering.blocked_outputs * 8.0 / requirement_count)

        architecture_items = self._architecture_confidences(architecture)
        architecture_confidence = (
            fmean(architecture_items) * 100.0 if architecture_items else 0.0
        )
        architecture_score = architecture_confidence - min(
            60.0, architecture.unresolved_decisions * 15.0
        )

        gap_ratio = (
            traceability.requirements_needing_clarification / requirement_count
        )
        missing_information = 100.0 - min(
            100.0,
            gap_ratio * 55.0
            + assumptions.pending_confirmation * 10.0 / requirement_count
            + engineering.blocked_outputs * 12.0 / requirement_count
            + architecture.unresolved_decisions * 8.0 / requirement_count,
        )

        dependency_issues = [
            issue
            for issue in issues
            if issue.issue_type == AmbiguityType.UNDEFINED_INTEGRATION
        ]
        dependency_score = 100.0 - self._issue_penalty(
            dependency_issues,
            {AmbiguityType.UNDEFINED_INTEGRATION},
            requirement_count,
        )
        dependency_requirements = [
            row for row in traceability.rows if row.category == "dependency"
        ]
        if dependency_requirements:
            integration_ids = {
                requirement_id
                for task in engineering.translation.integration_tasks
                for requirement_id in task.requirement_ids
            }
            coverage = sum(
                row.requirement_id in integration_ids for row in dependency_requirements
            ) / len(dependency_requirements)
            dependency_score = min(dependency_score, coverage * 100.0)

        acceptance_coverage = (
            sum(bool(row.acceptance_criteria) for row in traceability.rows)
            / requirement_count
        )
        edge_score = (
            40.0 + acceptance_coverage * 60.0
            - self._issue_penalty(issues, edge_types, requirement_count)
        )

        return [
            self._build_metric(
                "clarity",
                "Clarity",
                clarity,
                "Precision of language and explicit actor identification.",
            ),
            self._build_metric(
                "completeness",
                "Completeness",
                completeness,
                "Coverage of rules, validations, integrations, and required decisions.",
            ),
            self._build_metric(
                "consistency",
                "Consistency",
                consistency,
                "Freedom from contradictory requirements.",
            ),
            self._build_metric(
                "technical_readiness",
                "Technical Readiness",
                technical,
                "Traceable coverage by stories, acceptance criteria, and backend tasks.",
            ),
            self._build_metric(
                "architecture_readiness",
                "Architecture Readiness",
                architecture_score,
                "Confidence in recommendations after unresolved decisions are considered.",
            ),
            self._build_metric(
                "missing_information",
                "Missing Information",
                missing_information,
                "Information coverage after clarifications, assumptions, and blocked outputs.",
            ),
            self._build_metric(
                "dependencies",
                "Dependencies",
                dependency_score,
                "Definition and engineering coverage of dependencies and integrations.",
            ),
            self._build_metric(
                "edge_cases",
                "Edge Cases",
                edge_score,
                "Coverage of acceptance behavior, edge cases, and error handling.",
            ),
        ]

    @staticmethod
    def _issue_penalty(
        issues: Iterable[AmbiguityIssue],
        included_types: set[AmbiguityType],
        requirement_count: int,
    ) -> float:
        return min(
            100.0,
            sum(
                SEVERITY_WEIGHTS[issue.severity.value] * issue.confidence
                for issue in issues
                if issue.issue_type in included_types
            )
            / requirement_count,
        )

    @staticmethod
    def _architecture_confidences(
        result: ArchitectureRecommendationResult,
    ) -> list[float]:
        architecture = result.architecture
        items = [
            architecture.style,
            *architecture.modules,
            *architecture.services,
            architecture.database,
            architecture.caching,
            architecture.messaging,
            architecture.authentication,
            *architecture.external_services,
            architecture.deployment,
        ]
        return [item.confidence for item in items]

    @staticmethod
    def _build_metric(
        key: str,
        label: str,
        score: float,
        summary: str,
    ) -> HealthMetric:
        normalized = round(max(0.0, min(100.0, score)), 1)
        if normalized >= 85:
            status = HealthStatus.EXCELLENT
        elif normalized >= 70:
            status = HealthStatus.GOOD
        elif normalized >= 50:
            status = HealthStatus.CAUTION
        else:
            status = HealthStatus.CRITICAL
        return HealthMetric(
            key=key,
            label=label,
            score=normalized,
            status=status,
            summary=summary,
        )

    @staticmethod
    def _metric(metrics: list[HealthMetric], key: str) -> HealthMetric:
        return next(metric for metric in metrics if metric.key == key)

    @staticmethod
    def _next_actions(
        traceability: TraceabilityMatrix,
        issues: list[AmbiguityIssue],
        conflicts: ConflictDetectionResult,
        assumptions: AssumptionLedgerResult,
        engineering: EngineeringTranslationResult,
        architecture: ArchitectureRecommendationResult,
    ) -> list[HealthAction]:
        actions: list[HealthAction] = []
        severe_issues = [
            issue for issue in issues if issue.severity.value in {"critical", "high"}
        ]
        if severe_issues:
            actions.append(
                HealthAction(
                    priority="high",
                    action="Resolve high-impact clarification questions.",
                    reason=(
                        f"{len(severe_issues)} critical or high ambiguity issues "
                        "can change implementation behavior."
                    ),
                    related_ids=[issue.issue_id for issue in severe_issues],
                )
            )
        if conflicts.conflicts:
            actions.append(
                HealthAction(
                    priority="high",
                    action="Choose the authoritative behavior for each conflict.",
                    reason=(
                        f"{conflicts.total_conflicts} contradictory requirement "
                        "relationships remain unresolved."
                    ),
                    related_ids=[
                        conflict.conflict_id for conflict in conflicts.conflicts
                    ],
                )
            )
        pending = [
            assumption
            for assumption in assumptions.assumptions
            if assumption.needs_confirmation
        ]
        if pending:
            actions.append(
                HealthAction(
                    priority="high",
                    action="Confirm or reject implementation assumptions.",
                    reason=(
                        f"{len(pending)} inferred decisions currently affect "
                        "downstream outputs."
                    ),
                    related_ids=[assumption.assumption_id for assumption in pending],
                )
            )
        if engineering.translation.blocked_outputs:
            actions.append(
                HealthAction(
                    priority="medium",
                    action="Supply information required by blocked engineering outputs.",
                    reason="Some engineering artifacts cannot be generated safely yet.",
                    related_ids=[
                        output.artifact_id
                        for output in engineering.translation.blocked_outputs
                    ],
                )
            )
        if architecture.architecture.unresolved_decisions:
            actions.append(
                HealthAction(
                    priority="medium",
                    action="Close unresolved architecture decisions.",
                    reason="Deployment and technology choices still depend on missing facts.",
                    related_ids=[
                        decision.decision_id
                        for decision in architecture.architecture.unresolved_decisions
                    ],
                )
            )
        missing_acceptance = [
            row.requirement_id
            for row in traceability.rows
            if not row.acceptance_criteria
        ]
        if missing_acceptance:
            actions.append(
                HealthAction(
                    priority="medium",
                    action="Add testable acceptance criteria.",
                    reason=(
                        f"{len(missing_acceptance)} requirements lack traceable "
                        "acceptance behavior."
                    ),
                    related_ids=missing_acceptance,
                )
            )
        if not actions:
            actions.append(
                HealthAction(
                    priority="low",
                    action="Run a final stakeholder review and baseline the specification.",
                    reason="No material readiness blockers were detected.",
                )
            )
        priority_order = {"high": 0, "medium": 1, "low": 2}
        return sorted(actions, key=lambda item: priority_order[item.priority])
