from __future__ import annotations

import json
from typing import Any
from xml.etree import ElementTree

import httpx
from fastapi import HTTPException
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.config import ARXIV_API, get_settings
from app.logging_utils import get_logger
from app.schemas import ParsedPaper


logger = get_logger("app.agent.paper_search")


def _normalize_search_query(query: str) -> str:
    cleaned = " ".join(query.strip().split())
    lowered = cleaned.lower()
    prefixes = ("all:", "ti:", "au:", "abs:", "cat:")
    if lowered.startswith(prefixes):
        return cleaned.split(":", 1)[1].strip().strip('"')
    return cleaned.strip('"')


def _entry_to_candidate(entry: ElementTree.Element, namespace: dict[str, str]) -> dict[str, Any]:
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
    return {
        "title": title,
        "authors": [author for author in authors if author],
        "abstract": abstract,
        "source_url": source_url,
        "pdf_url": pdf_url,
    }


def _search_candidates(query: str, max_results: int = 6) -> list[dict[str, Any]]:
    normalized_query = _normalize_search_query(query)
    search_queries = [
        {"search_query": f'ti:"{normalized_query}"', "start": 0, "max_results": max_results},
        {"search_query": f'all:"{normalized_query}"', "start": 0, "max_results": max_results},
        {"search_query": normalized_query, "start": 0, "max_results": max_results},
    ]
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    deduped: dict[str, dict[str, Any]] = {}

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for params in search_queries:
            response = client.get(ARXIV_API, params=params)
            if response.status_code >= 400:
                logger.warning(
                    "paper_search_query_failed | query=%s | search_query=%s | status=%s",
                    query,
                    params["search_query"],
                    response.status_code,
                )
                continue
            xml_root = ElementTree.fromstring(response.text)
            for entry in xml_root.findall("atom:entry", namespace):
                candidate = _entry_to_candidate(entry, namespace)
                if candidate["source_url"]:
                    deduped[candidate["source_url"]] = candidate
    return list(deduped.values())[:max_results]


def _extract_final_json(messages: list[Any]) -> dict[str, Any]:
    for message in reversed(messages):
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.strip():
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                continue
    raise HTTPException(status_code=500, detail="Search agent did not return valid JSON.")


def search_arxiv_with_agent(query: str) -> ParsedPaper:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is missing in .env")

    logger.info("paper_search_agent_start | query=%s", query)
    seen_candidates: dict[str, dict[str, Any]] = {}

    @tool
    def search_arxiv(query_text: str) -> str:
        """Search arXiv for candidate papers matching a user request. Use this repeatedly with refined queries."""
        logger.info("paper_search_tool_call | tool=search_arxiv | query=%s", query_text)
        candidates = _search_candidates(query_text)
        for candidate in candidates:
            seen_candidates[candidate["source_url"]] = candidate
        logger.info(
            "paper_search_tool_result | tool=search_arxiv | query=%s | candidates=%s",
            query_text,
            len(candidates),
        )
        return json.dumps(candidates)

    @tool
    def get_candidate_by_url(source_url: str) -> str:
        """Fetch a previously seen candidate by its source_url so you can confirm the exact final selection."""
        logger.info(
            "paper_search_tool_call | tool=get_candidate_by_url | source_url=%s", source_url
        )
        candidate = seen_candidates.get(source_url)
        if candidate is None:
            logger.info("paper_search_tool_result | tool=get_candidate_by_url | found=false")
            return json.dumps({"found": False, "source_url": source_url})
        logger.info(
            "paper_search_tool_result | tool=get_candidate_by_url | found=true | title=%s",
            candidate["title"],
        )
        return json.dumps({"found": True, "candidate": candidate})

    model = ChatOpenAI(
        model=settings.chat_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )
    agent = create_react_agent(
        model=model,
        tools=[search_arxiv, get_candidate_by_url],
        prompt=(
            "You are a ReAct paper-search agent. "
            "Your job is to find the exact arXiv paper the user asked for. "
            "You must use the search_arxiv tool first. "
            "If results look wrong, refine the query yourself and call search_arxiv again. "
            "When you believe you found the correct paper, call get_candidate_by_url to confirm it. "
            "Be strict about exactness. If you are not confident, do not guess. "
            "Your final answer must be valid JSON with keys: "
            "match_found, source_url, reason. "
            "Set match_found to true only when the paper clearly matches the user's request."
        ),
    )

    result = agent.invoke({"messages": [("user", f"Find this paper on arXiv: {query}")]})
    for message in result["messages"]:
        message_type = getattr(message, "type", message.__class__.__name__)
        content = getattr(message, "content", "")
        preview = content if isinstance(content, str) else json.dumps(content)
        logger.info(
            "paper_search_agent_message | type=%s | content=%s", message_type, preview[:1200]
        )
    final_payload = _extract_final_json(result["messages"])
    if not final_payload.get("match_found"):
        reason = final_payload.get("reason") or "No confident paper match was found."
        logger.warning("paper_search_agent_no_match | query=%s | reason=%s", query, reason)
        raise HTTPException(
            status_code=404, detail=f"{reason} Try a more exact title or a direct arXiv URL."
        )
    source_url = final_payload.get("source_url", "").strip()
    candidate = seen_candidates.get(source_url)
    if not candidate:
        logger.error(
            "paper_search_agent_invalid_selection | query=%s | source_url=%s", query, source_url
        )
        raise HTTPException(
            status_code=500,
            detail="Search agent selected a paper that was not present in tool results.",
        )

    logger.info(
        "paper_search_agent_complete | query=%s | title=%s | source_url=%s",
        query,
        candidate["title"],
        candidate["source_url"],
    )
    return ParsedPaper(
        title=candidate["title"],
        authors=candidate["authors"],
        abstract=candidate["abstract"],
        source_url=candidate["source_url"],
        pdf_url=candidate["pdf_url"],
    )
