"""End-to-end: fake GitHub API + scripted LLM -> review_pull_request posts inline comments."""

import base64
import json

import httpx
from langchain_core.messages import AIMessage

from reviewer.diff import make_diff
from reviewer.fakes import ScriptedChatModel
from reviewer.github_client import GitHubClient, TokenAuth
from reviewer.service import PRRef, review_pull_request

AFTER = """import yaml


def load(path):
    with open(path) as f:
        return yaml.load(f, Loader=yaml.Loader)
"""
DIFF = make_diff("app/load.py", None, AFTER)


def fake_github(posted: list) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "GET" and path == "/repos/o/r/pulls/5":
            if "diff" in req.headers.get("accept", ""):
                return httpx.Response(200, text=DIFF)
            return httpx.Response(
                200, json={"title": "Load YAML", "body": "", "draft": False, "head": {"sha": "s1"}}
            )
        if path == "/repos/o/r/contents/app/load.py":
            content = base64.b64encode(AFTER.encode()).decode()
            return httpx.Response(
                200, json={"type": "file", "encoding": "base64", "size": 90, "content": content}
            )
        if path.startswith("/repos/o/r/git/trees/"):
            return httpx.Response(200, json={"tree": [{"path": "app/load.py", "type": "blob"}]})
        if req.method == "POST" and path == "/repos/o/r/pulls/5/reviews":
            posted.append(json.loads(req.content))
            return httpx.Response(200, json={"id": 99})
        return httpx.Response(404, json={"message": "not found"})

    return httpx.MockTransport(handler)


def test_review_pull_request_end_to_end():
    posted: list = []
    client = GitHubClient(TokenAuth("t"), transport=fake_github(posted))
    llm = ScriptedChatModel(
        script=[
            AIMessage(
                content="",
                tool_calls=[{"name": "run_linter", "args": {"path": "app/load.py"}, "id": "x"}],
            ),
            AIMessage(
                content=json.dumps(
                    {
                        "summary": "Loads YAML with the unsafe loader.",
                        "comments": [
                            {
                                "path": "app/load.py",
                                "line": 6,
                                "severity": "critical",
                                "category": "security",
                                "body": "yaml.Loader can run arbitrary code; use yaml.safe_load.",
                            }
                        ],
                    }
                )
            ),
        ]
    )
    out = review_pull_request(client, PRRef("o", "r", 5), llm)
    assert out is not None and len(out.comments) == 1
    # the linter tool really ran on the file fetched from the API
    tool_msg = llm.calls[1][-1]
    assert "S506" in tool_msg.content
    review = posted[0]
    assert review["commit_id"] == "s1" and review["event"] == "COMMENT"
    assert review["comments"][0] == {
        "path": "app/load.py",
        "line": 6,
        "side": "RIGHT",
        "body": "**[critical] security:** yaml.Loader can run arbitrary code; use yaml.safe_load.",
    }
    assert "1 critical" in review["body"]
