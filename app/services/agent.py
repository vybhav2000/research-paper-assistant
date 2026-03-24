from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.config import get_settings
from app.logging_utils import get_logger
from app.repositories import get_paper_or_404
from app.services.chat import retrieve_relevant_chunks
from app.services.tavily import tavily_search


logger = get_logger("app.agent.chat")


def _parse_json(payload: str) -> dict[str, Any]:
    try:
        return json.loads(payload)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=500, detail=f"Agent returned invalid JSON: {error}"
        ) from error


def _extract_final_json(messages: list[Any]) -> dict[str, Any]:
    for message in reversed(messages):
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.strip():
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                continue
    raise HTTPException(status_code=500, detail="Chat agent did not return valid JSON.")


def run_agentic_research_chat(
    paper_id: str,
    message: str,
    selection_text: str,
    selected_chunk_ids: list[str],
    conversation_history: list[dict[str, str]],
    highlight_summary: str,
) -> dict[str, Any]:
    logger.info(
        "chat_agent_start | paper_id=%s | selected_chunks=%s | message=%s",
        paper_id,
        len(selected_chunk_ids),
        message,
    )
    paper = get_paper_or_404(paper_id)
    seen_chunks: dict[str, dict[str, Any]] = {}
    external_sources: list[dict[str, str]] = []
    agent_steps: list[str] = []

    def log_step(step: str) -> None:
        agent_steps.append(step)
        logger.info("chat_agent_step | paper_id=%s | %s", paper_id, step)

    @tool
    def retrieve_paper_context(query_text: str) -> str:
        """Retrieve the most relevant chunks from the imported paper for a focused question."""
        chunks = retrieve_relevant_chunks(
            paper_id,
            f"{selection_text}\n{query_text}".strip(),
            selected_chunk_ids,
            top_k=8,
        )
        for chunk in chunks:
            seen_chunks[chunk["id"]] = chunk
        log_step(f"Retrieved {len(chunks)} paper chunks for query: {query_text}")
        return json.dumps(chunks)

    @tool
    def read_chunk(chunk_id: str) -> str:
        """Read one previously retrieved chunk in full by its chunk id."""
        chunk = seen_chunks.get(chunk_id)
        if chunk is None:
            return json.dumps({"found": False, "chunk_id": chunk_id})
        log_step(f"Reviewed chunk {chunk_id} on pages {chunk['page_start']}-{chunk['page_end']}")
        return json.dumps({"found": True, "chunk": chunk})

    @tool
    def search_web(query_text: str) -> str:
        """Search the web with Tavily when the user asks for external context, comparisons, or broader background."""
        result = tavily_search(query_text)
        results = result.get("results", [])
        external_sources[:] = [
            {"title": item.get("title", ""), "url": item.get("url", "")} for item in results
        ]
        if result.get("available"):
            log_step(f"Ran Tavily search for external context: {query_text}")
        else:
            log_step("Skipped Tavily search because TAVILY_API_KEY is not configured.")
        return json.dumps(result)

    model = ChatOpenAI(
        model=get_settings().chat_model,
        api_key=get_settings().openai_api_key,
        temperature=0,
    )
    agent = create_react_agent(
        model=model,
        tools=[retrieve_paper_context, read_chunk, search_web],
        prompt=(
            "You are an agentic research-paper assistant for one imported paper. "
            "You must call retrieve_paper_context before answering any paper question. "
            "Call read_chunk when you need to inspect a specific chunk more closely. "
            "Use search_web only when the user asks for external comparisons, background, related work, or web search. "
            "Prefer the paper itself whenever possible. "
            "Return final output as valid JSON with keys: answer_markdown, cited_chunk_ids, follow_up, used_external_search. "
            "The answer_markdown field must be markdown, concise but complete, and grounded in the tool results. "
            "The cited_chunk_ids array must only include ids from retrieved paper chunks."
        ),
    )
    message_history = [(item["role"], item["content"]) for item in conversation_history]
    user_prompt = (
        f"Paper title: {paper.title}\n"
        f"Authors: {', '.join(paper.authors)}\n"
        f"Abstract: {paper.abstract}\n\n"
        f"Saved highlights:\n{highlight_summary}\n\n"
        f"Selected text:\n{selection_text or 'No explicit selection.'}\n\n"
        f"User request:\n{message}"
    )
    result = agent.invoke({"messages": [*message_history, ("user", user_prompt)]})
    for item in result["messages"]:
        message_type = getattr(item, "type", item.__class__.__name__)
        content = getattr(item, "content", "")
        preview = content if isinstance(content, str) else json.dumps(content)
        logger.info("chat_agent_message | type=%s | content=%s", message_type, preview[:1200])

    payload = _extract_final_json(result["messages"])
    cited_chunk_ids = [
        chunk_id for chunk_id in payload.get("cited_chunk_ids", []) if chunk_id in seen_chunks
    ]
    context = [seen_chunks[chunk_id] for chunk_id in cited_chunk_ids]
    logger.info(
        "chat_agent_complete | paper_id=%s | citations=%s | external=%s",
        paper_id,
        len(cited_chunk_ids),
        bool(payload.get("used_external_search")),
    )
    return {
        "answer": payload.get("answer_markdown", "I could not produce an answer."),
        "citations": cited_chunk_ids,
        "follow_up": payload.get("follow_up", ""),
        "context": context,
        "agent_steps": agent_steps,
        "external_sources": external_sources,
    }
