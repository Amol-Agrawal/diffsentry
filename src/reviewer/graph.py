"""Review agent graph: prepare -> agent <-> tools -> finalize -> validate."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import ValidationError

from .diff import parse_unified_diff, render_for_llm
from .models import SEVERITY_RANK, FileDiff, ReviewComment, ReviewResult, Severity
from .prompts import FINALIZE_PROMPT, REPAIR_PROMPT, SYSTEM_PROMPT, USER_TEMPLATE
from .repo import RepoSource
from .tools import lint_python, make_tools


@dataclass
class ReviewConfig:
    max_iterations: int = 6
    max_comments: int = 15
    min_severity: Severity = Severity.minor
    run_lint: bool = True
    snap_distance: int = 3


class ReviewState(TypedDict, total=False):
    diff_text: str
    title: str
    description: str
    files: list[FileDiff]
    lint_findings: list[dict]
    messages: Annotated[list[AnyMessage], add_messages]
    iterations: int
    result: ReviewResult
    comments: list[ReviewComment]
    errors: list[str]


@dataclass
class ReviewOutput:
    summary: str
    comments: list[ReviewComment]
    files: list[FileDiff]
    lint_findings: list[dict]
    tool_calls: int
    iterations: int
    errors: list[str] = field(default_factory=list)


def message_text(msg: BaseMessage) -> str:
    content: Any = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text", ""))
        return "".join(parts)
    return str(content)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_review_json(text: str) -> ReviewResult:
    # models sometimes wrap the JSON in ``` fences or add a sentence before it
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text)] + [text]
    last_err: Exception | None = None
    for cand in candidates:
        cand = cand.strip()
        start, end = cand.find("{"), cand.rfind("}")
        if start == -1 or end <= start:
            continue
        try:
            data = json.loads(cand[start : end + 1])
            return ReviewResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = e
    raise ValueError(f"no valid review JSON found: {last_err}")


def _is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{path}"


def build_graph(llm: BaseChatModel, repo: RepoSource, config: ReviewConfig | None = None):
    cfg = config or ReviewConfig()
    tools = make_tools(repo)
    llm_with_tools = llm.bind_tools(tools)

    def prepare(state: ReviewState) -> dict:
        files = parse_unified_diff(state["diff_text"])
        findings: list[dict] = []
        if cfg.run_lint:
            for f in files:
                if not f.path.endswith(".py"):
                    continue
                src = repo.read_file(f.path)
                if src is None:
                    continue
                commentable = f.commentable_lines
                for issue in lint_python(f.path, src):
                    if issue["line"] in commentable:
                        findings.append({"path": f.path, **issue})

        changed_src = [
            f.path for f in files if f.path.endswith(".py") and not _is_test_file(f.path)
        ]
        repo_has_tests = any(_is_test_file(p) for p in repo.list_files())
        test_note = ""
        if changed_src and repo_has_tests and not any(_is_test_file(f.path) for f in files):
            test_note = "Note: source files changed but no test files changed in this PR.\n"

        lint_text = (
            "\n".join(f"- {x['path']}:{x['line']} {x['code']} {x['message']}" for x in findings)
            or "(none)"
        )
        user = USER_TEMPLATE.format(
            title=state.get("title") or "(untitled)",
            description=(state.get("description") or "").strip()[:2000] or "(no description)",
            file_list=", ".join(f.path for f in files) or "(none)",
            test_note=test_note,
            lint=lint_text,
            diff=render_for_llm(files),
        )
        return {
            "files": files,
            "lint_findings": findings,
            "messages": [SystemMessage(SYSTEM_PROMPT), HumanMessage(user)],
            "iterations": 0,
            "errors": [],
        }

    def agent(state: ReviewState) -> dict:
        reply = llm_with_tools.invoke(state["messages"])
        return {"messages": [reply], "iterations": state.get("iterations", 0) + 1}

    def route_after_agent(state: ReviewState) -> str:
        last = state["messages"][-1]
        wants_tools = isinstance(last, AIMessage) and bool(last.tool_calls)
        if wants_tools and state.get("iterations", 0) < cfg.max_iterations:
            return "tools"
        return "finalize"

    def finalize(state: ReviewState) -> dict:
        messages = list(state["messages"])
        errors = list(state.get("errors", []))
        last = messages[-1]
        # out of iterations but it still wants tools -> drop that call, ask for the answer
        if isinstance(last, AIMessage) and last.tool_calls:
            messages = messages[:-1] + [HumanMessage(FINALIZE_PROMPT)]
            last = llm.invoke(messages)
            messages.append(last)
        for attempt in range(2):
            try:
                return {"result": parse_review_json(message_text(last)), "errors": errors}
            except ValueError as e:
                if attempt == 1:
                    errors.append(f"unparseable model output: {e}")
                    break
                messages.append(HumanMessage(REPAIR_PROMPT.format(error=str(e)[:300])))
                last = llm.invoke(messages)
                messages.append(last)
        return {"result": ReviewResult(summary="", comments=[]), "errors": errors}

    def validate(state: ReviewState) -> dict:
        by_path = {f.path: f for f in state.get("files", [])}
        min_rank = SEVERITY_RANK[cfg.min_severity]
        kept: list[ReviewComment] = []
        seen: set[tuple[str, int, str]] = set()
        for c in state["result"].comments:
            f = by_path.get(c.path) or by_path.get(c.path.lstrip("./"))
            if f is None or SEVERITY_RANK[c.severity] > min_rank:
                continue
            line = c.line
            if line not in f.commentable_lines:
                nearby = [n for n in f.added_lines if abs(n - line) <= cfg.snap_distance]
                if not nearby:
                    continue
                line = min(nearby, key=lambda n: abs(n - line))
            key = (f.path, line, c.category.value)
            if key in seen:
                continue
            seen.add(key)
            kept.append(c.model_copy(update={"path": f.path, "line": line}))
        kept.sort(key=lambda c: (SEVERITY_RANK[c.severity], c.path, c.line))
        return {"comments": kept[: cfg.max_comments]}

    g = StateGraph(ReviewState)
    g.add_node("prepare", prepare)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tools))
    g.add_node("finalize", finalize)
    g.add_node("validate", validate)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "agent")
    g.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "finalize": "finalize"})
    g.add_edge("tools", "agent")
    g.add_edge("finalize", "validate")
    g.add_edge("validate", END)
    return g.compile()


def review_diff(
    diff_text: str,
    repo: RepoSource,
    llm: BaseChatModel,
    *,
    title: str = "",
    description: str = "",
    config: ReviewConfig | None = None,
) -> ReviewOutput:
    cfg = config or ReviewConfig()
    graph = build_graph(llm, repo, cfg)
    state = graph.invoke(
        {"diff_text": diff_text, "title": title, "description": description},
        {"recursion_limit": 2 * cfg.max_iterations + 10},
    )
    tool_calls = sum(
        len(m.tool_calls) for m in state.get("messages", []) if isinstance(m, AIMessage)
    )
    return ReviewOutput(
        summary=state["result"].summary,
        comments=state.get("comments", []),
        files=state.get("files", []),
        lint_findings=state.get("lint_findings", []),
        tool_calls=tool_calls,
        iterations=state.get("iterations", 0),
        errors=state.get("errors", []),
    )
