from app.agents.framework import AgentContext, AgentResult, BaseAgent


class DiscoveredFixtureAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "discovered_fixture"

    @property
    def description(self) -> str:
        return "Framework discovery fixture."

    def execute(self, context: AgentContext) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            output={"dna": context.specification_dna},
            confidence=1.0,
        )

    def validate(self, context: AgentContext) -> None:
        del context

    def dependencies(self) -> tuple[str, ...]:
        return ()
