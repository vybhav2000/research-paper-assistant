from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.config import SUMMARY_DIR, get_settings
from app.openai_client import get_openai_client
from app.repositories import get_paper_or_404


def _summary_cache_path(paper_id: str) -> Path:
    return SUMMARY_DIR / f"{paper_id}.md"


def summary_exists(paper_id: str) -> bool:
    return _summary_cache_path(paper_id).exists()


def get_cached_summary_markdown(paper_id: str) -> str | None:
    cache_path = _summary_cache_path(paper_id)
    if not cache_path.exists():
        return None
    return cache_path.read_text(encoding="utf-8")


def _trim_source_text(raw_text: str, max_chars: int = 12000) -> str:
    cleaned = " ".join(raw_text.split())
    return cleaned[:max_chars]


def _generate_concise_summary(title: str, authors: list[str], abstract: str, raw_text: str) -> str:
    completion = get_openai_client().chat.completions.create(
        model=get_settings().chat_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are writing a very concise markdown summary of a research paper. "
                    "Keep it short to save cost and reading time. "
                    "Return markdown only with this exact structure: "
                    "# Title, ## TL;DR, ## Core Idea, ## Key Results, ## Limitations. "
                    "Each section must be brief. Use flat bullet points where possible. "
                    "Preserve any mathematical expressions as LaTeX delimited with $$...$$ for display math "
                    "or \\(...\\) for inline math. Do not invent formulas."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Title: {title}\n"
                    f"Authors: {', '.join(authors)}\n"
                    f"Abstract: {abstract}\n\n"
                    "Extracted PDF text excerpt:\n"
                    f"{_trim_source_text(raw_text)}"
                ),
            },
        ],
    )
    return (completion.choices[0].message.content or "").strip()


def generate_paper_summary_markdown(paper_id: str, force: bool = False) -> str:
    cache_path = _summary_cache_path(paper_id)
    if cache_path.exists() and not force:
        return cache_path.read_text(encoding="utf-8")

    paper = get_paper_or_404(paper_id)
    if not paper.raw_text.strip():
        raise HTTPException(
            status_code=400, detail="No extracted PDF text is available for this paper."
        )

    summary_markdown = _generate_concise_summary(
        title=paper.title,
        authors=paper.authors,
        abstract=paper.abstract,
        raw_text=paper.raw_text,
    )
    if not summary_markdown:
        raise HTTPException(status_code=500, detail="Failed to generate the paper summary.")

    cache_path.write_text(summary_markdown, encoding="utf-8")
    return summary_markdown
