# Research Paper Assistant

Research Paper Assistant is a FastAPI app for importing arXiv papers, reading PDFs in-app, generating concise markdown summaries on demand, saving highlights, and chatting with an agent grounded in the paper.

Live app: [https://research-paper-assistant-bhfx.onrender.com/](https://research-paper-assistant-bhfx.onrender.com/)

## What It Does

- Import a paper from an arXiv title query or direct arXiv URL
- Download and store the PDF locally
- Read the paper inside the app with a built-in PDF viewer
- Generate a concise markdown summary only when `Create summary` is pressed
- Render LaTeX formulas in summaries and chat responses
- Chat with an agentic paper assistant grounded in the imported paper
- Save highlights and use them as focused chat context
- Use ChromaDB as the local open-source vector store for retrieval
- Optionally use Tavily for external web search when broader context is needed

## Live Deployment

The hosted app is available here:

- [research-paper-assistant-bhfx.onrender.com](https://research-paper-assistant-bhfx.onrender.com/)

## Stack

- FastAPI
- SQLite for app data
- ChromaDB for vector retrieval
- OpenAI for chat, summary generation, and embeddings
- Tavily for optional external search
- Vanilla HTML, CSS, and JavaScript frontend
- Docker for deployment

## Current Workflow

1. Search for a paper by title or paste an arXiv link.
2. The app finds the arXiv entry, downloads the PDF, extracts text, chunks it, embeds it, and stores retrieval data.
3. Open the imported paper workspace with:
   - PDF viewer
   - paper chat
   - saved highlights
4. Press `Create summary` only when you want a summary.
5. Ask follow-up questions grounded in the paper.

## Setup

1. Create `.env` from `.env.example`.
2. Set `OPENAI_API_KEY`.
3. Set `TAVILY_API_KEY` if you want external search enabled.
4. Install dependencies:

```bash
uv sync
```

5. Run the app locally:

```bash
uv run uvicorn main:app --reload
```

6. Open:

- `http://127.0.0.1:8000`

## Environment Variables

- `OPENAI_API_KEY`: required
- `OPENAI_CHAT_MODEL`: optional, defaults in deployment config
- `OPENAI_EMBEDDING_MODEL`: optional, defaults in deployment config
- `TAVILY_API_KEY`: optional, enables web search
- `LOG_LEVEL`: optional

## API Docs

FastAPI exposes:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

Health endpoint:

- `GET /api/healthz`

## Common Commands

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

The Compose stack mounts persistent storage for `/app/data`, so imported PDFs, SQLite data, summaries, and vector indexes survive container restarts.

## Render Deployment

This project is set up for Render as a Docker web service with a persistent disk mounted at `/app/data`.

Recommended flow:

1. Push the repo to GitHub.
2. Create a new Render Blueprint.
3. Point it at this repo.
4. Use the included [`render.yaml`](./render.yaml).
5. Set these environment variables in Render:
   - `OPENAI_API_KEY`
   - `TAVILY_API_KEY` if needed
6. Deploy.

Hosted URL:

- [https://research-paper-assistant-bhfx.onrender.com/](https://research-paper-assistant-bhfx.onrender.com/)
