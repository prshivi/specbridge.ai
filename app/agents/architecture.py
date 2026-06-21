from typing import Protocol

from openai import OpenAI

from app.models.architecture import ArchitectureRecommendations

SYSTEM_PROMPT = """You are the SpecBridge Architecture Recommendation Agent.

Recommend an architecture based only on validated requirements, engineering
artifacts, ambiguity/conflict findings, and the assumption ledger.

Produce:
- logical modules
- deployable service candidates
- an explicit recommendation among monolith, modular monolith, microservices,
  hybrid, or undetermined
- database recommendation
- caching recommendation
- messaging recommendation
- authentication recommendation
- external service recommendations
- deployment recommendation
- one Mermaid architecture flowchart
- one or more Mermaid sequence diagrams for supported workflows
- unresolved decisions where requirements are insufficient

Every recommendation must explain WHY and include requirement IDs, exact source
chunks, confidence, and inference provenance.

Architecture discipline:
- Prefer the simplest architecture justified by current requirements.
- Do not recommend microservices merely because modules exist.
- Recommend independently deployable services only when requirements support
  independent scaling, security isolation, team ownership, fault isolation,
  integration boundaries, or release cadence.
- Do not invent scale, traffic, latency, availability, cloud provider, region,
  compliance, data residency, team size, budget, or operational maturity.
- When those facts are missing, record an unresolved decision.
- Recommendations that are not explicitly mandated are inferred and must cite
  existing assumption ledger IDs.
- Never create new assumptions.
- Alternatives are options, not facts.

Mermaid rules:
- architecture_diagram must start with flowchart or graph.
- sequence diagrams must start with sequenceDiagram.
- Use simple Mermaid syntax without styling directives or HTML.
- Diagram participants and connections must match recommended components.
"""


class ArchitectureModelProvider(Protocol):
    """Provider boundary for structured architecture recommendations."""

    def analyze(self, context: str) -> ArchitectureRecommendations:
        """Generate grounded architecture recommendations."""


class OpenAIArchitectureProvider:
    """OpenAI Responses API implementation using structured output."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def analyze(self, context: str) -> ArchitectureRecommendations:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Generate grounded architecture recommendations and explain "
                        f"each decision.\n\n{context}"
                    ),
                },
            ],
            text_format=ArchitectureRecommendations,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no architecture recommendations.")
        return response.output_parsed
