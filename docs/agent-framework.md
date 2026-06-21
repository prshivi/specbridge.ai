# Generic AI Agent Framework

## Purpose

The agent framework provides one reusable orchestration contract for future
SpecBridge capabilities. It contains no business extraction logic. Business
agents plug in by subclassing `BaseAgent` and can then use the same dependency,
retry, cache, event, and pipeline infrastructure.

## Agent contract

Every agent implements:

```python
class ExampleAgent(BaseAgent):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    def validate(self, context: AgentContext) -> None: ...

    def dependencies(self) -> tuple[str, ...]: ...

    def execute(self, context: AgentContext) -> AgentResult: ...
```

Agents may additionally change `version` to invalidate older cached outputs or
set `cacheable = False`.

## Shared context

`AgentContext` carries the uploaded document, knowledge graph, Specification
DNA, chunks, embeddings, configuration, provider-neutral LLM adapter, cache,
execution history, and prior agent results. Agents communicate through typed
results in `context.results`, not through global state.

## Registry and discovery

`AgentRegistry` accepts explicit registration and recursively discovers
zero-argument `BaseAgent` implementations in a Python package. Existing provider
classes are not automatically treated as framework agents.

## Pipeline engine

`AgentPipelineEngine` currently executes sequentially and provides:

- recursive dependency resolution
- cycle detection
- conditional pipeline steps
- configurable retry with exponential backoff
- result caching
- lifecycle and warning events
- execution duration and attempt tracking

`ExecutionMode.PARALLEL` is reserved in the public pipeline contract so a future
parallel scheduler can be added without changing agent implementations or
pipeline definitions.

## Caching

Agent outputs are stored in SQLite using:

- agent name
- agent version
- document-scoped Specification DNA fingerprint

Unchanged DNA reuses prior output. Changed DNA, a changed agent version, or a
different document causes fresh execution.

## Event logging

The framework records started, completed, failed, warning, cache-hit, and
conditional-skip events. Production composition uses SQLite; tests and local
tools can use the in-memory logger.

## Production composition

```python
runtime = create_agent_runtime(settings)
result = runtime.registry.execute(
    "agent_name",
    context,
    engine=runtime.engine,
)
```

Configuration:

```dotenv
AGENT_FRAMEWORK_DB=data/specbridge.db
AGENT_RETRY_ATTEMPTS=2
AGENT_RETRY_DELAY_SECONDS=0.25
```
