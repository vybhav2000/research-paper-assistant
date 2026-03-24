from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.config import PDF_DIR, SUMMARY_DIR
from app.db import get_db
from app.models import Conversation, Highlight, Message, Paper, PaperChunk
from app.schemas import ParsedPaper
from app.services.vector_store import delete_vector_index


def _format_timestamp(value: Any) -> str | None:
    return None if value is None else value.isoformat(sep=" ", timespec="seconds")


def _serialize_message(message: Message) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "citations": message.citations,
        "selection_text": message.selection_text,
        "created_at": _format_timestamp(message.created_at),
    }


def _serialize_highlight(highlight: Highlight) -> dict[str, Any]:
    return {
        "id": highlight.id,
        "chunk_ids": highlight.chunk_ids,
        "label": highlight.label,
        "quote": highlight.quote,
        "note": highlight.note,
        "created_at": _format_timestamp(highlight.created_at),
    }


def get_paper_or_404(paper_id: str) -> Paper:
    with get_db() as session:
        paper = session.get(Paper, paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="Paper not found.")
        session.expunge(paper)
        return paper


def list_papers() -> list[dict[str, Any]]:
    with get_db() as session:
        rows = session.execute(
            select(Paper, func.count(PaperChunk.id).label("chunk_count"))
            .outerjoin(PaperChunk, PaperChunk.paper_id == Paper.id)
            .group_by(Paper.id)
            .order_by(Paper.created_at.desc())
        ).all()
        return [
            {
                "id": paper.id,
                "title": paper.title,
                "authors": paper.authors,
                "abstract": paper.abstract,
                "source_url": paper.source_url,
                "created_at": _format_timestamp(paper.created_at),
                "chunk_count": chunk_count,
            }
            for paper, chunk_count in rows
        ]


def find_existing_paper_id(source_url: str, title: str) -> str | None:
    with get_db() as session:
        paper_id = session.execute(
            select(Paper.id).where((Paper.source_url == source_url) | (Paper.title == title))
        ).scalar_one_or_none()
    return paper_id


def persist_paper(
    parsed: ParsedPaper,
    pdf_path: Path,
    page_texts: list[tuple[int, str]],
    embeddings: list[list[float]],
    chunks: list[dict[str, Any]],
    paper_id: str,
    conversation_id: str,
) -> None:
    full_text = "\n\n".join(text for _, text in page_texts)
    with get_db() as session:
        paper = Paper(
            id=paper_id,
            title=parsed.title,
            authors=parsed.authors,
            abstract=parsed.abstract,
            source_url=parsed.source_url,
            pdf_url=parsed.pdf_url,
            pdf_path=str(pdf_path),
            raw_text=full_text,
        )
        paper.chunks = [
            PaperChunk(
                id=chunk["id"],
                chunk_index=chunk["chunk_index"],
                page_start=chunk["page_start"],
                page_end=chunk["page_end"],
                content=chunk["content"],
                embedding=embedding,
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]
        paper.conversation = Conversation(
            id=conversation_id,
            paper_id=paper_id,
            title=f"{parsed.title} discussion",
        )
        session.add(paper)


def update_paper_pdf_path(paper_id: str, pdf_path: Path) -> None:
    with get_db() as session:
        paper = session.get(Paper, paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="Paper not found.")
        paper.pdf_path = str(pdf_path)


def get_conversation_id(session: Session, paper_id: str) -> str:
    conversation_id = session.execute(
        select(Conversation.id).where(Conversation.paper_id == paper_id)
    ).scalar_one_or_none()
    if conversation_id is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation_id


def fetch_chunks(session: Session, paper_id: str) -> list[PaperChunk]:
    return list(
        session.execute(
            select(PaperChunk)
            .where(PaperChunk.paper_id == paper_id)
            .order_by(PaperChunk.chunk_index.asc())
        ).scalars()
    )


def fetch_recent_messages(
    session: Session, conversation_id: str, limit: int = 10
) -> list[dict[str, str]]:
    messages = list(
        session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        ).scalars()
    )
    return [{"role": message.role, "content": message.content} for message in reversed(messages)]


def summarize_highlights(session: Session, paper_id: str, limit: int = 8) -> str:
    highlights = list(
        session.execute(
            select(Highlight)
            .where(Highlight.paper_id == paper_id)
            .order_by(Highlight.created_at.desc())
            .limit(limit)
        ).scalars()
    )
    if not highlights:
        return "No saved highlights yet."
    return "\n".join(
        f"- {highlight.label}: {highlight.quote[:240]} Note: {highlight.note or 'No note'}"
        for highlight in highlights
    )


def store_message(
    session: Session,
    conversation_id: str,
    role: str,
    content: str,
    citations: list[str] | None = None,
    selection_text: str = "",
) -> None:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    session.add(
        Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            citations=citations or [],
            selection_text=selection_text,
        )
    )
    conversation.updated_at = func.current_timestamp()


def clear_conversation_messages(paper_id: str) -> None:
    with get_db() as session:
        conversation_id = get_conversation_id(session, paper_id)
        session.execute(delete(Message).where(Message.conversation_id == conversation_id))
        conversation = session.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = func.current_timestamp()


def clear_library() -> None:
    paper_ids: list[str]
    with get_db() as session:
        paper_ids = list(session.execute(select(Paper.id)).scalars())
        session.execute(delete(Paper))

    for paper_id in paper_ids:
        delete_vector_index(paper_id)

    for directory in (PDF_DIR, SUMMARY_DIR):
        for path in directory.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)


def save_highlight(paper_id: str, highlight: dict[str, Any]) -> None:
    with get_db() as session:
        session.add(
            Highlight(
                id=highlight["id"],
                paper_id=paper_id,
                chunk_ids=highlight["chunk_ids"],
                label=highlight["label"],
                quote=highlight["quote"],
                note=highlight["note"],
            )
        )


def serialize_paper_detail(paper_id: str) -> dict[str, Any]:
    with get_db() as session:
        paper = session.execute(
            select(Paper)
            .where(Paper.id == paper_id)
            .options(
                selectinload(Paper.chunks),
                selectinload(Paper.highlights),
                selectinload(Paper.conversation).selectinload(Conversation.messages),
            )
        ).scalar_one_or_none()
        if paper is None:
            raise HTTPException(status_code=404, detail="Paper not found.")
        conversation = paper.conversation

        return {
            "id": paper.id,
            "title": paper.title,
            "authors": paper.authors,
            "abstract": paper.abstract,
            "source_url": paper.source_url,
            "pdf_url": f"/api/papers/{paper_id}/pdf",
            "chunks": [
                {
                    "id": chunk.id,
                    "chunk_index": chunk.chunk_index,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "content": chunk.content,
                }
                for chunk in paper.chunks
            ],
            "messages": []
            if conversation is None
            else [_serialize_message(message) for message in conversation.messages],
            "highlights": [_serialize_highlight(highlight) for highlight in paper.highlights],
        }
