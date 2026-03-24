from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass
class ParsedPaper:
    title: str
    authors: list[str]
    abstract: str
    source_url: str
    pdf_url: str


class PaperImportRequest(BaseModel):
    query: str


class ChatRequest(BaseModel):
    message: str
    selected_chunk_ids: list[str] = []
    selection_text: str = ""
    mode: str = "agentic"


class HighlightRequest(BaseModel):
    chunk_ids: list[str]
    label: str
    quote: str
    note: str = ""
