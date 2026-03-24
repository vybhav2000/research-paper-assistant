# Research Paper Assistant

Import an arXiv paper by title or link, download its PDF, read it in-app, generate a full markdown summary from the PDF text, save highlights, and ask follow-up questions through an agentic chat grounded in the paper.

## Setup

1. Create `.env` from `.env.example` and add `OPENAI_API_KEY`.
2. Add `TAVILY_API_KEY` if you want the agent to search the web for external context.
3. Install dependencies with `uv sync`.
4. Run the app with `uv run uvicorn main:app --reload`.
5. Open `http://127.0.0.1:8000`.

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

## Render

This app is best deployed to Render as a single Docker web service with a persistent disk mounted at `/app/data`.

Recommended setup:

1. Push this repo to GitHub.
2. In Render, create a new Blueprint and point it at this repo.
3. Use the included [`render.yaml`](./render.yaml).
4. Set the secret env vars in the Render dashboard:
   - `OPENAI_API_KEY`
   - `TAVILY_API_KEY` if you want web search enabled
5. Deploy.
