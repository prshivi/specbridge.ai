"""AI agent implementations and provider boundaries."""

from app.agents.ambiguity import OpenAIAmbiguityProvider
from app.agents.architecture import OpenAIArchitectureProvider
from app.agents.assumptions import OpenAIAssumptionProvider
from app.agents.conflicts import OpenAIConflictProvider
from app.agents.copilot import OpenAICopilotProvider
from app.agents.requirements import OpenAIRequirementProvider
from app.agents.translator import OpenAITranslatorProvider
from app.agents.understanding import OpenAIUnderstandingProvider
from app.agents.framework import (
    AgentContext,
    AgentPipeline,
    AgentPipelineEngine,
    AgentRegistry,
    AgentResult,
    BaseAgent,
)
from app.agents.specification_dna import (
    OpenAISpecificationDNAProvider,
    SpecificationUnderstandingAgent,
)
from app.agents.requirement_extraction import (
    OpenAIRequirementExtractionProvider,
    RequirementExtractionAgent,
)
from app.agents.conflict_detection import (
    ConflictDetectionAgent,
    OpenAIFrameworkConflictProvider,
)
from app.agents.missing_requirement_detection import (
    MissingRequirementDetectionAgent,
    OpenAIMissingRequirementProvider,
)

__all__ = [
    "OpenAIAmbiguityProvider",
    "OpenAIArchitectureProvider",
    "OpenAIAssumptionProvider",
    "OpenAIConflictProvider",
    "OpenAICopilotProvider",
    "OpenAIRequirementProvider",
    "OpenAITranslatorProvider",
    "OpenAIUnderstandingProvider",
    "AgentContext",
    "AgentPipeline",
    "AgentPipelineEngine",
    "AgentRegistry",
    "AgentResult",
    "BaseAgent",
    "OpenAISpecificationDNAProvider",
    "SpecificationUnderstandingAgent",
    "OpenAIRequirementExtractionProvider",
    "RequirementExtractionAgent",
    "ConflictDetectionAgent",
    "OpenAIFrameworkConflictProvider",
    "MissingRequirementDetectionAgent",
    "OpenAIMissingRequirementProvider",
]
