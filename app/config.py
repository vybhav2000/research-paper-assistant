from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"
SUMMARY_DIR = DATA_DIR / "summaries"
VECTOR_INDEX_DIR = DATA_DIR / "vector_indexes"
DB_PATH = DATA_DIR / "assistant.db"
ARXIV_API = "http://export.arxiv.org/api/query"


for directory in (STATIC_DIR, DATA_DIR, PDF_DIR, SUMMARY_DIR, VECTOR_INDEX_DIR):
    directory.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    tavily_api_key: str
    chat_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"


def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
        chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini"),
        embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
    )
