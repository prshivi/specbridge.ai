# Specification Understanding Agent and DNA

## Role

The Specification Understanding Agent is the first production agent built on
the generic Agent Framework. It runs before future downstream business agents
and creates the canonical, evidence-grounded Specification DNA for an uploaded
document.

It does not create user stories, APIs, architecture, implementation tasks, or
unstated information.

## Execution flow

```text
Stored semantic chunks
        |
        +--> deterministic Knowledge Graph
        |
        v
AgentContext
  - chunks
  - knowledge graph
  - configuration
  - Specification DNA provider
        |
        v
AgentPipelineEngine
  - validation
  - retry policy
  - event logging
  - source-fingerprint cache
        |
        v
SpecificationUnderstandingAgent
        |
        v
Evidence validation
        |
        v
SQLite Specification DNA
```

## Evidence model

Every extracted item contains:

- confidence from 0.0 to 1.0
- one or more exact source chunk IDs
- one or more matching document sections

The service rejects unknown chunk IDs, source sections that do not match the
cited chunks, and duplicate named concepts.

## Extracted fields

- project name and summary
- business objectives
- actors and explicitly described user personas
- modules and workflows
- integrations
- business rules and constraints
- explicitly stated assumptions
- glossary entries and key terminology

Unsupported singular values are `null`; unsupported collections are empty.

## Persistence and caching

The canonical result is stored in the `specification_dna` SQLite table.
Framework cache entries use the agent name, agent version, and a fingerprint of
the ordered chunks plus deterministic knowledge graph. If any source content or
graph evidence changes, the agent runs again.

The agent version can be increased to invalidate results after a schema or
prompt change.

## API

```text
GET /specification-dna/{document_id}
GET /specification-dna/{document_id}?force_refresh=true
```

The first request generates and stores the DNA. Later requests reuse the stored
result while the source fingerprint, model, and agent version remain unchanged.

An example response is available at
`samples/specification-dna.example.json`.
