from __future__ import annotations

import json
from typing import Any, TypedDict

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.logging_utils import get_logger
from app.openai_client import get_openai_client
from app.repositories import get_paper_or_404
from app.services.chat import generate_answer, retrieve_relevant_chunks


logger = get_logger("app.agent.chat")


class AgentState(TypedDict, total=False):
    paper_id: str
    message: str
    selection_text: str
    selected_chunk_ids: list[str]
    paper: Any
    conversation_history: list[dict[str, str]]
    highlight_summary: str
    plan: dict[str, Any]
    relevant_chunks: list[dict[str, Any]]
    secondary_chunks: list[dict[str, Any]]
    requires_second_pass: bool
    retrieval_query: str
    second_pass_query: str
    answer: str
    cited_chunk_ids: list[str]
    follow_up: str
    agent_steps: list[str]


def _parse_json(payload: str) -> dict[str, Any]:
    try:
        return json.loads(payload)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail=f"Agent returned invalid JSON: {error}") from error


def _append_step(state: AgentState, message: str) -> list[str]:
    steps = list(state.get("agent_steps", []))
    steps.append(message)
    logger.info("chat_agent_step | paper_id=%s | %s", state.get("paper_id", "unknown"), message)
    return steps


def plan_question(state: AgentState) -> AgentState:
    paper = state["paper"]
    system_prompt = (
        "You are planning a research assistant workflow for a single paper. "
        "Return valid JSON with keys: retrieval_query, analysis_goal, needs_second_pass, second_pass_query, user_intent. "
        "Keep retrieval_query concise and optimized for semantic retrieval over the paper text. "
        "Only request a second pass when the question likely requires extra context from distant parts of the paper."
    )
    user_prompt = f"""
Paper title: {paper.title}
Abstract: {paper.abstract}
User selection:
{state["selection_text"] or "No explicit selection."}

User question:
{state["message"]}
""".strip()

    completion = get_openai_client().chat.completions.create(
        model=get_settings().chat_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    plan = _parse_json(completion.choices[0].message.content or "{}")
    plan.setdefault("retrieval_query", state["message"])
    plan.setdefault("analysis_goal", "Answer the user precisely using the paper.")
    plan.setdefault("needs_second_pass", False)
    plan.setdefault("second_pass_query", state["message"])
    plan.setdefault("user_intent", "paper_qa")

    return {
        "plan": plan,
        "retrieval_query": f"{state['selection_text']}\n{plan['retrieval_query']}".strip(),
        "requires_second_pass": bool(plan["needs_second_pass"]),
        "second_pass_query": plan["second_pass_query"],
        "agent_steps": _append_step(
            state,
            f"Planned workflow for intent '{plan['user_intent']}' with goal: {plan['analysis_goal']}",
        ),
    }


def retrieve_primary_context(state: AgentState) -> AgentState:
    chunks = retrieve_relevant_chunks(
        state["paper_id"],
        state["retrieval_query"],
        state["selected_chunk_ids"],
        top_k=8,
    )
    return {
        "relevant_chunks": chunks,
        "agent_steps": _append_step(state, f"Retrieved {len(chunks)} primary context chunks."),
    }


def evaluate_context(state: AgentState) -> AgentState:
    if not state.get("requires_second_pass"):
        return {"agent_steps": _append_step(state, "Primary context judged sufficient for synthesis.")}

    system_prompt = (
        "You are checking whether a second retrieval pass is useful for answering a paper question. "
        "Return valid JSON with keys: second_pass_needed, refined_query, rationale. "
        "Prefer false unless the current context obviously misses comparison, limitations, setup, or results details."
    )
    joined_context = "\n\n".join(chunk["content"] for chunk in state.get("relevant_chunks", []))
    user_prompt = f"""
User question:
{state["message"]}

Current retrieval plan:
{json.dumps(state["plan"])}

Current context:
{joined_context[:6000]}
""".strip()
    completion = get_openai_client().chat.completions.create(
        model=get_settings().chat_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    review = _parse_json(completion.choices[0].message.content or "{}")
    review.setdefault("second_pass_needed", False)
    review.setdefault("refined_query", state.get("second_pass_query", state["message"]))
    review.setdefault("rationale", "No extra retrieval needed.")

    return {
        "requires_second_pass": bool(review["second_pass_needed"]),
        "second_pass_query": review["refined_query"],
        "agent_steps": _append_step(state, f"Reviewed context sufficiency: {review['rationale']}"),
    }


def retrieve_secondary_context(state: AgentState) -> AgentState:
    chunks = retrieve_relevant_chunks(
        state["paper_id"],
        f"{state['selection_text']}\n{state['second_pass_query']}".strip(),
        state["selected_chunk_ids"],
        top_k=6,
    )
    primary_ids = {chunk["id"] for chunk in state.get("relevant_chunks", [])}
    secondary = [chunk for chunk in chunks if chunk["id"] not in primary_ids]
    merged = list(state.get("relevant_chunks", [])) + secondary
    return {
        "secondary_chunks": secondary,
        "relevant_chunks": merged[:12],
        "agent_steps": _append_step(state, f"Ran secondary retrieval and added {len(secondary)} new chunks."),
    }


def synthesize_answer(state: AgentState) -> AgentState:
    result = generate_answer(
        paper=state["paper"],
        conversation_history=state["conversation_history"],
        message=state["message"],
        relevant_chunks=state["relevant_chunks"],
        selection_text=state["selection_text"],
        highlight_summary=state["highlight_summary"],
    )
    cited_chunk_ids = [
        chunk_id
        for chunk_id in result["cited_chunk_ids"]
        if any(chunk["id"] == chunk_id for chunk in state["relevant_chunks"])
    ]
    return {
        "answer": result["answer"],
        "cited_chunk_ids": cited_chunk_ids,
        "follow_up": result["follow_up"],
        "agent_steps": _append_step(
            state,
            f"Synthesized final answer from {len(state['relevant_chunks'])} supporting chunks.",
        ),
    }


def should_run_second_pass(state: AgentState) -> str:
    return "second_pass" if state.get("requires_second_pass") else "synthesize"


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("plan", plan_question)
    graph.add_node("retrieve_primary", retrieve_primary_context)
    graph.add_node("evaluate", evaluate_context)
    graph.add_node("second_pass", retrieve_secondary_context)
    graph.add_node("synthesize", synthesize_answer)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "retrieve_primary")
    graph.add_edge("retrieve_primary", "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        should_run_second_pass,
        {
            "second_pass": "second_pass",
            "synthesize": "synthesize",
        },
    )
    graph.add_edge("second_pass", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


AGENT_GRAPH = build_agent_graph()


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
    final_state = AGENT_GRAPH.invoke(
        {
            "paper_id": paper_id,
            "message": message,
            "selection_text": selection_text,
            "selected_chunk_ids": selected_chunk_ids,
            "paper": paper,
            "conversation_history": conversation_history,
            "highlight_summary": highlight_summary,
            "agent_steps": [],
        }
    )
    logger.info(
        "chat_agent_complete | paper_id=%s | citations=%s | follow_up=%s",
        paper_id,
        len(final_state["cited_chunk_ids"]),
        bool(final_state["follow_up"]),
    )
    return {
        "answer": final_state["answer"],
        "citations": final_state["cited_chunk_ids"],
        "follow_up": final_state["follow_up"],
        "context": final_state["relevant_chunks"],
        "agent_steps": final_state.get("agent_steps", []),
    }
