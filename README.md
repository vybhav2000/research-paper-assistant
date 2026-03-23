# Research Paper Assistant

Import an arXiv paper by title or link, download its PDF, read it in-app, select context chunks, save highlights, and ask questions grounded in the paper with OpenAI.

The chat UI supports two modes:

- `Standard` for direct retrieval-backed paper Q&A
- `Agentic` for a LangGraph workflow that plans the question, retrieves context in one or two passes, and then synthesizes an answer

## Setup

1. Create `.env` from `.env.example` and add `OPENAI_API_KEY`.
2. Install dependencies with `uv sync`.
3. Run the app with `uv run uvicorn main:app --reload`.
4. Open `http://127.0.0.1:8000`.

## Auto Documentation

FastAPI generates the API documentation automatically:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

There is also a deployment health endpoint:

- `GET /api/healthz`

## Makefile

Common commands:

- `make install`
- `make dev`
- `make run`
- `make docs`
- `make health`
- `make check`
- `make docker-build`
- `make docker-up`
- `make docker-down`
- `make docker-logs`

## Docker

Build and run with Docker Compose:

1. `docker compose up --build -d`
2. Open `http://127.0.0.1:8000`
3. Stop with `docker compose down`

The Compose stack mounts a named volume for `/app/data`, so imported PDFs and SQLite data persist across container restarts.
