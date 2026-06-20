# SpecBridge AI

SpecBridge AI is a domain-agnostic AI Specification Intelligence Platform that turns messy business requirements into structured, engineering-ready outputs.

This repository currently contains only the initial application scaffold. AI agents, document parsing, vector search, and specification generation are intentionally out of scope for this step.

## Product vision

Teams often receive requirements through incomplete documents, meeting notes, tickets, spreadsheets, and conversations. SpecBridge AI will provide a governed workflow for interpreting those inputs, finding ambiguity and gaps, and producing traceable artifacts that engineering teams can use with confidence.

The platform is designed to remain domain-agnostic while supporting domain-specific prompts, policies, validation rules, and output formats.

## Architecture overview

```text
Streamlit frontend
        |
        v
FastAPI application
  ├── API routes
  ├── Core configuration
  ├── Domain models
  ├── Services
  ├── Future agent orchestration
  ├── Future document parsers
  ├── Future vector store adapters
  └── Future exporters and prompts
```

- `app/api/`: HTTP routes and API composition
- `app/agents/`: future AI agent orchestration
- `app/core/`: application configuration and shared infrastructure
- `app/models/`: typed request, response, and domain models
- `app/services/`: application use cases and business services
- `app/parsers/`: future document parsing adapters
- `app/vectorstore/`: future vector store abstractions
- `app/exporters/`: future engineering artifact exporters
- `app/prompts/`: future versioned prompt assets
- `app/tests/`: backend tests
- `frontend/`: Streamlit user interface
- `samples/`: future example inputs and outputs
- `docs/`: architecture and product documentation

## Setup

Prerequisites:

- Python 3.11 or newer (Python 3.12 recommended)
- Docker and Docker Compose (optional)

Create the local environment:

```bash
cd specbridge-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run locally

Start the API:

```bash
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`, its health endpoint at `http://localhost:8000/health`, and interactive documentation at `http://localhost:8000/docs`.

In another terminal, with the same virtual environment active, start the frontend:

```bash
streamlit run frontend/app.py
```

The frontend is available at `http://localhost:8501`.

## Run with Docker

Create the environment file once, then start both services:

```bash
cp .env.example .env
docker compose up --build
```

Stop the services with:

```bash
docker compose down
```

## Run tests

```bash
pytest
```

## Roadmap

1. Define the core requirement and specification domain models.
2. Add secure document ingestion and pluggable parsing.
3. Introduce provider-independent model and embedding interfaces.
4. Add traceable AI agent workflows for requirement analysis.
5. Add vector retrieval with replaceable storage adapters.
6. Generate engineering artifacts through pluggable exporters.
7. Add evaluation, observability, access control, and audit trails.
8. Evolve the frontend into a guided specification workspace.
