from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.logging_utils import get_logger


logger = get_logger("app.agent.tavily")
TAVILY_API = "https://api.tavily.com/search"


def tavily_search(query: str, max_results: int = 5) -> dict[str, Any]:
    settings = get_settings()
    if not settings.tavily_api_key:
        logger.info("tavily_search_skipped | reason=missing_api_key | query=%s", query)
        return {
            "available": False,
            "query": query,
            "results": [],
            "error": "TAVILY_API_KEY is missing in .env",
        }

    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "search_depth": "advanced",
        "include_answer": True,
        "include_raw_content": False,
        "max_results": max_results,
    }
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.post(TAVILY_API, json=payload)
        response.raise_for_status()
        data = response.json()

    results = [
        {
            "title": item.get("title", "").strip(),
            "url": item.get("url", "").strip(),
            "content": item.get("content", "").strip(),
            "score": item.get("score"),
        }
        for item in data.get("results", [])
        if item.get("url")
    ]
    logger.info("tavily_search_complete | query=%s | results=%s", query, len(results))
    return {
        "available": True,
        "query": query,
        "answer": (data.get("answer") or "").strip(),
        "results": results,
    }
