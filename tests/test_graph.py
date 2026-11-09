import json

from langchain_core.messages import AIMessage, ToolMessage

from reviewer.diff import make_diff
from reviewer.fakes import ScriptedChatModel
from reviewer.graph import ReviewConfig, parse_review_json, review_diff
from reviewer.models import Severity
from reviewer.repo import InMemoryRepo

AFTER = """import subprocess


def avg(xs):
    return sum(xs) // len(xs)


def run(cmd):
    return subprocess.run(cmd, shell=True)
"""
BEFORE = """def avg(xs):
    return sum(xs) / len(xs)
"""
DIFF = make_diff("app/stats.py", BEFORE, AFTER)


def _final(comments, summary="ok"):
    return AIMessage(content=json.dumps({"summary": summary, "comments": comments}))


def _repo():
    return InMemoryRepo({"app/stats.py": AFTER})


def test_tool_loop_then_final_answer():
    llm = ScriptedChatModel(
        script=[
            AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {"path": "app/stats.py"}, "id": "t1"}],
            ),
            _final(
                [
                    {
                        "path": "app/stats.py",
                        "line": 5,
                        "severity": "major",
                        "category": "bug",
                        "body": "floor division truncates the mean",
                    }
                ]
            ),
        ]
    )
    out = review_diff(DIFF, _repo(), llm)
    assert out.tool_calls == 1 and out.iterations == 2
    assert [(c.line, c.severity) for c in out.comments] == [(5, Severity.major)]
    # the tool result was fed back to the model
    assert any(isinstance(m, ToolMessage) and "floor" not in m.content for m in llm.calls[1])


def test_lint_findings_reach_the_prompt():
    llm = ScriptedChatModel(script=[_final([])])
    out = review_diff(DIFF, _repo(), llm)
    assert any(f["code"] == "S602" for f in out.lint_findings)
    assert "S602" in llm.calls[0][1].content


def test_validate_drops_and_snaps_comments():
    llm = ScriptedChatModel(
        script=[
            _final(
                [
                    {
                        "path": "app/stats.py",
                        "line": 9,
                        "severity": "critical",
                        "category": "security",
                        "body": "shell=True with caller input",
                    },
                    {
                        "path": "app/stats.py",
                        "line": 9,
                        "severity": "critical",
                        "category": "security",
                        "body": "duplicate",
                    },
                    {"path": "app/stats.py", "line": 500, "severity": "major", "body": "far away"},
                    {"path": "other.py", "line": 1, "severity": "major", "body": "not in diff"},
                    {"path": "app/stats.py", "line": 5, "severity": "nit", "body": "too minor"},
                ]
            )
        ]
    )
    out = review_diff(DIFF, _repo(), llm, config=ReviewConfig(min_severity=Severity.minor))
    assert [(c.line, c.body) for c in out.comments] == [(9, "shell=True with caller input")]


def test_repairs_invalid_json_once():
    llm = ScriptedChatModel(
        script=[
            AIMessage(content="Looks fine to me!"),
            _final([{"path": "app/stats.py", "line": 5, "body": "floor division"}]),
        ]
    )
    out = review_diff(DIFF, _repo(), llm)
    assert len(out.comments) == 1 and not out.errors


def test_gives_up_cleanly_on_garbage():
    llm = ScriptedChatModel(script=[AIMessage(content="no json here")])
    out = review_diff(DIFF, _repo(), llm)
    assert out.comments == [] and out.errors


def test_iteration_budget_forces_final_answer():
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "search_code", "args": {"pattern": "avg"}, "id": "t"}],
    )
    llm = ScriptedChatModel(script=[tool_call, tool_call, _final([])])
    out = review_diff(DIFF, _repo(), llm, config=ReviewConfig(max_iterations=2))
    assert out.iterations == 2 and out.comments == [] and not out.errors


def test_parse_review_json_handles_fences_and_prose():
    text = 'Here you go:\n```json\n{"summary": "s", "comments": []}\n```'
    assert parse_review_json(text).summary == "s"
