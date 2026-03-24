from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app.repositories import (
    clear_library,
    clear_conversation_messages,
    get_paper_or_404,
    list_papers,
    save_highlight,
    serialize_paper_detail,
)
from app.schemas import ChatRequest, HighlightRequest, PaperImportRequest
from app.services.agent import run_agentic_research_chat
from app.services.chat import (
    build_chat_context,
    build_highlight,
    save_chat_exchange,
)
from app.services.papers import import_paper, normalize_query
from app.services.summary import (
    generate_paper_summary_markdown,
    get_cached_summary_markdown,
    summary_exists,
)


router = APIRouter()


@router.get("/healthz", tags=["system"], summary="Health check")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/papers", tags=["papers"], summary="List imported papers")
def api_list_papers() -> list[dict]:
    return list_papers()


@router.delete("/papers", tags=["papers"], summary="Clear the entire paper library")
def api_clear_library() -> dict[str, str]:
    clear_library()
    return {"status": "cleared"}


@router.post("/papers/import", tags=["papers"], summary="Import a paper from a title or arXiv link")
def api_import_paper(payload: PaperImportRequest) -> dict:
    return import_paper(payload.query)


@router.get("/papers/{paper_id}", tags=["papers"], summary="Get full paper workspace state")
def api_get_paper(paper_id: str) -> dict:
    return serialize_paper_detail(paper_id)


@router.get("/papers/{paper_id}/summary", tags=["papers"], summary="Fetch the cached paper summary")
def api_get_paper_summary(paper_id: str) -> dict[str, str | bool]:
    get_paper_or_404(paper_id)
    return {
        "summary_exists": summary_exists(paper_id),
        "summary_markdown": get_cached_summary_markdown(paper_id) or "",
    }


@router.post("/papers/{paper_id}/summary", tags=["papers"], summary="Create the paper summary")
def api_create_paper_summary(paper_id: str) -> dict[str, str | bool]:
    get_paper_or_404(paper_id)
    return {
        "summary_exists": True,
        "summary_markdown": generate_paper_summary_markdown(paper_id),
    }


@router.get("/papers/{paper_id}/pdf", tags=["papers"], summary="Download or stream the stored PDF")
def api_get_pdf(paper_id: str) -> FileResponse:
    paper = get_paper_or_404(paper_id)
    pdf_path = Path(paper.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk.")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"{paper.title}.pdf",
        content_disposition_type="inline",
    )


@router.post("/papers/{paper_id}/chat", tags=["chat"], summary="Ask a question about the paper")
def api_chat(paper_id: str, payload: ChatRequest) -> JSONResponse:
    message = normalize_query(payload.message)
    if not message:
        raise HTTPException(status_code=400, detail="A question is required.")

    conversation_history, highlight_summary = build_chat_context(paper_id)
    result = run_agentic_research_chat(
        paper_id=paper_id,
        message=message,
        selection_text=payload.selection_text,
        selected_chunk_ids=payload.selected_chunk_ids,
        conversation_history=conversation_history,
        highlight_summary=highlight_summary,
    )
    save_chat_exchange(
        paper_id,
        message,
        payload.selection_text,
        payload.selected_chunk_ids,
        result["answer"],
        result["citations"],
    )
    return JSONResponse(result)


@router.delete("/papers/{paper_id}/chat", tags=["chat"], summary="Clear chat history for a paper")
def api_clear_chat(paper_id: str) -> dict[str, str]:
    get_paper_or_404(paper_id)
    clear_conversation_messages(paper_id)
    return {"status": "cleared"}


@router.post(
    "/papers/{paper_id}/highlights", tags=["highlights"], summary="Save a highlight and note"
)
def api_save_highlight(paper_id: str, payload: HighlightRequest) -> dict:
    get_paper_or_404(paper_id)
    if not payload.chunk_ids or not payload.quote.strip() or not payload.label.strip():
        raise HTTPException(
            status_code=400, detail="Highlight label, quote, and chunk ids are required."
        )
    highlight = build_highlight(payload)
    save_highlight(paper_id, highlight)
    return highlight
