# Specification Knowledge Graph Architecture

## Purpose

The Specification Knowledge Graph converts parser-generated semantic chunks
into a typed, queryable internal model. It is deterministic and makes no LLM
calls. Downstream agents can therefore consume one stable representation rather
than independently reinterpreting raw document text.

## Flow

```text
Uploaded specification
        |
        v
Normalized parser blocks
        |
        v
Semantic chunks in ChromaDB
        |
        v
Deterministic knowledge extraction
        |
        +--> Pydantic entities and relationships
        +--> SQLite normalized persistence
        +--> NetworkX MultiDiGraph
        |
        v
JSON model and graph APIs
```

## Entity model

Every entity carries a stable document-scoped ID, `document_id`, title,
description, source chunk IDs, confidence, and extensible metadata. Supported
types are Document, Section, Requirement, BusinessRule, Actor, Workflow,
Integration, Constraint, Validation, Permission, Notification, APIReference,
DataEntity, and GlossaryTerm.

## Relationship model

The graph supports:

- Requirement `belongs_to` Section
- Requirement `depends_on` Requirement
- Requirement `references` BusinessRule
- Workflow `contains` Requirement
- Requirement `uses` DataEntity
- Requirement `integrates_with` Integration
- Requirement `validated_by` Validation
- Requirement `requires` Permission

Explicit IDs and textual references receive the highest confidence.
Relationships inferred from shared section structure are retained with lower
confidence and a `basis` metadata field.

## Persistence

SQLite uses three tables:

- `knowledge_builds`: one build timestamp per document
- `knowledge_entities`: normalized entity records
- `knowledge_relationships`: directed relationship records with foreign keys

A rebuild replaces the graph for that document transactionally, preventing
stale or duplicate nodes.

## NetworkX

Persisted models are reconstructed as a `networkx.MultiDiGraph`. Parallel
relationship types are supported, and future graph algorithms can operate on
the internal graph without changing the API or SQLite schema.

## API

```text
POST /knowledge/build/{document_id}
GET  /knowledge/{document_id}
GET  /knowledge/graph/{document_id}
```

The build endpoint must be called after upload/chunking. The graph endpoint
returns frontend-ready node and edge JSON.

## Deterministic extraction limits

This phase favors precision over recall. It recognizes structural chunk types,
explicit requirement and rule IDs, labeled actors/integrations/entities,
HTTP method-path references, glossary entries, and conservative keyword
patterns. It does not claim semantic equivalence or infer unstated domain
knowledge. A later AI enrichment layer can add candidates while retaining this
deterministic graph as provenance.
