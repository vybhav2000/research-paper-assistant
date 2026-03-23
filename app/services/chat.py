from __future__ import annotations

import json
import math
import uuid
from typing import Any

from fastapi import HTTPException

from app.config import get_settings
from app.db import get_db
from app.models import Paper, PaperChunk
from app.openai_client import get_openai_client
from app.repositories import fetch_chunks, fetch_recent_messages, get_conversation_id, store_message, summarize_highlights


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def row_to_chunk(row: PaperChunk) -> dict[str, Any]:
    return {
        "id": row.id,
        "chunk_index": row.chunk_index,
        "page_start": row.page_start,
        "page_end": row.page_end,
        "content": row.content,
    }


def retrieve_relevant_chunks(paper_id: str, message: str, selected_chunk_ids: list[str], top_k: int = 6) -> list[dict[str, Any]]:
    client = get_openai_client()
    with get_db() as connection:
        chunks = fetch_chunks(connection, paper_id)

    selected_set = set(selected_chunk_ids)
    selected_chunks = [chunk for chunk in chunks if chunk.id in selected_set]
    non_selected_chunks = [chunk for chunk in chunks if chunk.id not in selected_set]
    if selected_chunks and len(selected_chunks) >= top_k:
        return [row_to_chunk(chunk) for chunk in selected_chunks[:top_k]]

    query_embedding = client.embeddings.create(model=get_settings().embedding_model, input=[message]).data[0].embedding
    scored = [
        (cosine_similarity(query_embedding, chunk.embedding), chunk)
        for chunk in non_selected_chunks
    ]
    scored.sort(key=lambda item: item[0], reverse=True)

    merged = [row_to_chunk(chunk) for chunk in selected_chunks]
    merged.extend(row_to_chunk(chunk) for _, chunk in scored[: max(0, top_k - len(merged))])
    return merged


def generate_answer(
    paper: Paper,
    conversation_history: list[dict[str, str]],
    message: str,
    relevant_chunks: list[dict[str, Any]],
    selection_text: str,
    highlight_summary: str,
) -> dict[str, Any]:
    context_blocks = []
    for chunk in relevant_chunks:
        if chunk["page_start"] == chunk["page_end"]:
            pages = f"page {chunk['page_start']}"
        else:
            pages = f"pages {chunk['page_start']}-{chunk['page_end']}"
        context_blocks.append(f"[chunk:{chunk['id']}] ({pages}) {chunk['content']}")

    user_prompt = f"""
Paper title: {paper.title}
Authors: {", ".join(paper.authors)}
Abstract: {paper.abstract}

Saved highlights memory:
{highlight_summary}

User selection:
{selection_text or "No explicit selection."}

Relevant paper context:
{chr(10).join(context_blocks)}

User question:
{message}
""".strip()

    completion = get_openai_client().chat.completions.create(
        model=get_settings().chat_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a research paper assistant. Answer only using the supplied paper context and chat memory. "
                    "Return valid JSON with keys: answer, cited_chunk_ids, follow_up. "
                    "The cited_chunk_ids array must contain only chunk ids that directly support the answer."
                ),
            },
            *conversation_history,
            {"role": "user", "content": user_prompt},
        ],
    )
    payload = completion.choices[0].message.content or "{}"
    try:
        result = json.loads(payload)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail=f"Model returned invalid JSON: {error}") from error
    result.setdefault("answer", "I could not produce an answer.")
    result.setdefault("cited_chunk_ids", [])
    result.setdefault("follow_up", "")
    return result


def save_chat_exchange(paper_id: str, user_message: str, selection_text: str, selected_chunk_ids: list[str], answer: str, cited_chunk_ids: list[str]) -> None:
    with get_db() as connection:
        conversation_id = get_conversation_id(connection, paper_id)
        store_message(connection, conversation_id, "user", user_message, selected_chunk_ids, selection_text)
        store_message(connection, conversation_id, "assistant", answer, cited_chunk_ids, selection_text)


def build_chat_context(paper_id: str) -> tuple[list[dict[str, str]], str]:
    with get_db() as connection:
        conversation_id = get_conversation_id(connection, paper_id)
        return fetch_recent_messages(connection, conversation_id), summarize_highlights(connection, paper_id)


def build_highlight(payload: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "chunk_ids": payload.chunk_ids,
        "label": payload.label.strip(),
        "quote": payload.quote.strip(),
        "note": payload.note.strip(),
    }
