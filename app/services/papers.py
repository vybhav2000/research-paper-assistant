from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx
from fastapi import HTTPException
from pypdf import PdfReader

from app.config import ARXIV_API, PDF_DIR, get_settings
from app.openai_client import get_openai_client
from app.repositories import (
    find_existing_paper_id,
    persist_paper,
    serialize_paper_detail,
    update_paper_pdf_path,
)
from app.schemas import ParsedPaper
from app.services.paper_search_agent import search_arxiv_with_agent
from app.services.vector_store import build_vector_index


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip())


def is_arxiv_reference(query: str) -> bool:
    lowered = query.lower()
    return "arxiv.org" in lowered or lowered.startswith("arxiv:")


def extract_arxiv_id(query: str) -> str:
    cleaned = query.strip()
    patterns = [
        r"arxiv\.org\/abs\/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)",
        r"arxiv\.org\/pdf\/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)",
        r"arxiv:([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            return match.group(1)
    return cleaned


def search_arxiv(query: str) -> ParsedPaper:
    if is_arxiv_reference(query):
        params = {"search_query": f"id:{extract_arxiv_id(query)}", "start": 0, "max_results": 1}
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(ARXIV_API, params=params)
            response.raise_for_status()
        xml_root = ElementTree.fromstring(response.text)
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        entry = xml_root.find("atom:entry", namespace)
        if entry is None:
            raise HTTPException(status_code=404, detail="No matching paper found on arXiv.")
        title = (entry.findtext("atom:title", default="", namespaces=namespace) or "").strip()
        abstract = (entry.findtext("atom:summary", default="", namespaces=namespace) or "").strip()
        authors = [
            author.findtext("atom:name", default="", namespaces=namespace).strip()
            for author in entry.findall("atom:author", namespace)
        ]
        source_url = entry.findtext("atom:id", default="", namespaces=namespace).strip()
        pdf_url = ""
        for link in entry.findall("atom:link", namespace):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href", "").strip()
                break
        if not pdf_url and source_url:
            pdf_url = source_url.replace("/abs/", "/pdf/") + ".pdf"
        return ParsedPaper(
            title=title,
            authors=[author for author in authors if author],
            abstract=abstract,
            source_url=source_url,
            pdf_url=pdf_url,
        )
    return search_arxiv_with_agent(query)


def download_pdf(pdf_url: str, paper_id: str) -> Path:
    target = PDF_DIR / f"{paper_id}.pdf"
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(pdf_url)
        response.raise_for_status()
        target.write_bytes(response.content)
    return target


def extract_pdf_text(pdf_path: Path) -> list[tuple[int, str]]:
    reader = PdfReader(str(pdf_path))
    page_texts: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            page_texts.append((index, text))
    if not page_texts:
        raise HTTPException(status_code=400, detail="The PDF text could not be extracted.")
    return page_texts


def chunk_paper_text(
    page_texts: list[tuple[int, str]], size: int = 1700, overlap: int = 250
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    buffer = ""
    buffer_pages: list[int] = []
    chunk_index = 0

    def flush_buffer() -> None:
        nonlocal buffer, buffer_pages, chunk_index
        content = buffer.strip()
        if not content:
            return
        pages = sorted(set(buffer_pages))
        chunks.append(
            {
                "id": str(uuid.uuid4()),
                "chunk_index": chunk_index,
                "page_start": pages[0] if pages else None,
                "page_end": pages[-1] if pages else None,
                "content": content,
            }
        )
        chunk_index += 1

    for page_number, text in page_texts:
        sanitized = re.sub(r"\s+", " ", text or "").strip()
        if not sanitized:
            continue
        paragraphs = [
            segment.strip() for segment in re.split(r"(?<=[.!?])\s+", sanitized) if segment.strip()
        ]
        for paragraph in paragraphs:
            candidate = f"{buffer} {paragraph}".strip() if buffer else paragraph
            if len(candidate) <= size:
                buffer = candidate
                buffer_pages.append(page_number)
                continue
            flush_buffer()
            if overlap and buffer:
                buffer = f"{buffer[-overlap:]} {paragraph}".strip()
            else:
                buffer = paragraph
            buffer_pages = [page_number]
    flush_buffer()
    return chunks


def embed_texts(texts: list[str]) -> list[list[float]]:
    client = get_openai_client()
    response = client.embeddings.create(model=get_settings().embedding_model, input=texts)
    return [item.embedding for item in response.data]


def import_paper(query: str) -> dict[str, Any]:
    normalized = normalize_query(query)
    if not normalized:
        raise HTTPException(status_code=400, detail="A paper title or arXiv link is required.")

    parsed = search_arxiv(normalized)
    existing_paper_id = find_existing_paper_id(parsed.source_url, parsed.title)
    if existing_paper_id:
        return serialize_paper_detail(existing_paper_id)

    temp_id = str(uuid.uuid4())
    pdf_path = download_pdf(parsed.pdf_url, temp_id)
    page_texts = extract_pdf_text(pdf_path)
    chunks = chunk_paper_text(page_texts)
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="The PDF was fetched, but no readable text chunks were produced.",
        )

    paper_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    embeddings = embed_texts([chunk["content"] for chunk in chunks])
    persist_paper(
        parsed,
        pdf_path,
        page_texts,
        embeddings,
        chunks,
        paper_id,
        conversation_id,
    )
    build_vector_index(
        paper_id,
        chunks,
        embeddings,
    )

    final_path = PDF_DIR / f"{paper_id}.pdf"
    if pdf_path != final_path:
        pdf_path.replace(final_path)
        update_paper_pdf_path(paper_id, final_path)

    return serialize_paper_detail(paper_id)
