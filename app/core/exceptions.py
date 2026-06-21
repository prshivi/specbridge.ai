class DocumentError(Exception):
    """Base exception for document upload and parsing failures."""


class DocumentValidationError(DocumentError):
    """Raised when an uploaded document fails validation."""


class UnsupportedDocumentTypeError(DocumentValidationError):
    """Raised when a document format is not supported."""


class DocumentTooLargeError(DocumentValidationError):
    """Raised when an uploaded document exceeds the size limit."""


class DocumentParsingError(DocumentError):
    """Raised when text cannot be extracted from a supported document."""


class UnderstandingAgentError(Exception):
    """Raised when specification understanding cannot be completed."""


class UnderstandingAgentNotConfiguredError(UnderstandingAgentError):
    """Raised when no model provider credentials are configured."""


class DocumentChunksNotFoundError(UnderstandingAgentError):
    """Raised when an understanding run has no source chunks."""


class KnowledgeGraphNotFoundError(Exception):
    """Raised when a document knowledge graph has not been built."""


class RequirementIntelligenceError(Exception):
    """Raised when requirement intelligence cannot be completed."""


class RequirementIntelligenceNotConfiguredError(RequirementIntelligenceError):
    """Raised when no model provider credentials are configured."""


class RequirementExtractionError(Exception):
    """Raised when framework requirement extraction cannot be completed."""


class RequirementExtractionNotConfiguredError(RequirementExtractionError):
    """Raised when no provider credentials are configured."""


class ExtractedRequirementsNotFoundError(RequirementExtractionError):
    """Raised when framework requirements have not been extracted."""


class AmbiguityDetectionError(Exception):
    """Raised when ambiguity detection cannot be completed."""


class AmbiguityDetectionNotConfiguredError(AmbiguityDetectionError):
    """Raised when no model provider credentials are configured."""


class ConflictDetectionError(Exception):
    """Raised when conflict detection cannot be completed."""


class ConflictDetectionNotConfiguredError(ConflictDetectionError):
    """Raised when no model provider credentials are configured."""


class FrameworkConflictDetectionError(Exception):
    """Raised when framework conflict detection cannot be completed."""


class FrameworkConflictNotConfiguredError(FrameworkConflictDetectionError):
    """Raised when no framework conflict provider is configured."""


class DetectedConflictsNotFoundError(FrameworkConflictDetectionError):
    """Raised when framework conflicts have not been analyzed."""


class MissingRequirementDetectionError(Exception):
    """Raised when contextual missing requirement detection fails."""


class MissingRequirementNotConfiguredError(MissingRequirementDetectionError):
    """Raised when no missing requirement provider is configured."""


class MissingRequirementIssuesNotFoundError(MissingRequirementDetectionError):
    """Raised when missing requirement analysis has not been run."""


class AssumptionLedgerError(Exception):
    """Raised when the assumption ledger cannot be completed."""


class AssumptionLedgerNotConfiguredError(AssumptionLedgerError):
    """Raised when no model provider credentials are configured."""


class AssumptionLedgerNotFoundError(AssumptionLedgerError):
    """Raised when a framework assumption ledger or item does not exist."""


class EngineeringTranslationError(Exception):
    """Raised when business-to-engineering translation cannot be completed."""


class EngineeringTranslationNotConfiguredError(EngineeringTranslationError):
    """Raised when no model provider credentials are configured."""


class EngineeringBlueprintNotFoundError(EngineeringTranslationError):
    """Raised when a framework engineering blueprint does not exist."""


class ArchitectureRecommendationError(Exception):
    """Raised when architecture recommendations cannot be completed."""


class ArchitectureRecommendationNotConfiguredError(ArchitectureRecommendationError):
    """Raised when no model provider credentials are configured."""


class ArchitectureBlueprintNotFoundError(ArchitectureRecommendationError):
    """Raised when a framework Architecture Blueprint does not exist."""


class DeveloperCopilotError(Exception):
    """Raised when developer copilot cannot answer safely."""


class DeveloperCopilotNotConfiguredError(DeveloperCopilotError):
    """Raised when no model provider credentials are configured."""
