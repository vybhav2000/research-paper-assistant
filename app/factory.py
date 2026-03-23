from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR
from app.db import init_db
from app.logging_utils import configure_logging, get_logger
from app.routes import router


def create_app() -> FastAPI:
    configure_logging()
    logger = get_logger("app.factory")
    app = FastAPI(
        title="Research Paper Assistant",
        summary="Import arXiv papers, read PDFs, save highlights, and ask grounded questions with OpenAI.",
        description=(
            "Research Paper Assistant provides a paper ingestion pipeline, PDF serving, "
            "selection-aware chat, persistent highlights, and retrieval-backed answers over "
            "arXiv papers."
        ),
        version="0.1.0",
        contact={"name": "Research Paper Assistant"},
        license_info={"name": "MIT"},
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {
                "name": "system",
                "description": "Operational endpoints for health checks and service metadata.",
            },
            {
                "name": "papers",
                "description": "Paper import, paper listing, paper detail, and PDF serving endpoints.",
            },
            {
                "name": "chat",
                "description": "Selection-aware and whole-paper question answering endpoints.",
            },
            {
                "name": "agentic",
                "description": "LangGraph-powered multi-step research workflows over imported papers.",
            },
            {
                "name": "highlights",
                "description": "Persistent highlight and note management for paper memory.",
            },
        ],
    )
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router, prefix="/api")

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()
        logger.info("Application startup complete")

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
