import json
from pathlib import Path

import httpx

from reviewer.evaluation import lint_only_comments, load_cases, score_case, summarize
from reviewer.github_client import GitHubClient, TokenAuth
from reviewer.models import ReviewComment
from reviewer.service import PRRef

CASES = Path(__file__).resolve().parent.parent / "eval" / "cases"


def test_prref_parse():
    assert PRRef.parse("https://github.com/a/b/pull/12") == PRRef("a", "b", 12)
    assert PRRef.parse("a/b#3") == PRRef("a", "b", 3)


def test_create_review_falls_back_to_body_on_422():
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        posted.append(payload)
        if payload.get("comments"):
            return httpx.Response(422, json={"message": "line must be part of the diff"})
        return httpx.Response(200, json={"id": 1})

    gh = GitHubClient(TokenAuth("t"), transport=httpx.MockTransport(handler))
    c = ReviewComment(path="a.py", line=3, severity="major", category="bug", body="boom")
    assert gh.create_review("o", "r", 1, "sha", "summary", [c]) == {"id": 1}
    assert len(posted) == 2 and "`a.py:3`" in posted[1]["body"]


def test_eval_cases_load():
    cases = load_cases(CASES)
    assert len(cases) == 20
    assert sum(len(c.bugs) for c in cases) == 17
    assert all(c.diff for c in cases)


def test_scoring():
    case = next(c for c in load_cases(CASES) if c.id.startswith("02_"))
    bug = case.bugs[0]
    good = ReviewComment(path=bug.path, line=bug.line + 1, body="sql injection")
    dupe = ReviewComment(path=bug.path, line=bug.line, body="again")
    bad = ReviewComment(path=bug.path, line=1, body="nitpick")
    s = score_case(case, [good, dupe, bad])
    assert (s.found, s.true_positive_comments, len(s.false_positives)) == (1, 2, 1)


def test_lint_baseline_is_a_floor():
    scores = [score_case(c, lint_only_comments(c)) for c in load_cases(CASES)]
    summary = summarize(scores)
    assert summary.found >= 5 and summary.precision == 1.0


def test_dashboard_renders_baseline_and_reviews():
    from reviewer.dashboard import render_dashboard
    from reviewer.evaluation import to_json

    scores = [score_case(c, lint_only_comments(c)) for c in load_cases(CASES)]
    run = json.loads(to_json("lint-only", summarize(scores), scores))
    reviews = [
        {
            "time": "t",
            "pr": "o/r#1",
            "status": "posted",
            "comments": 1,
            "by_severity": {"major": 1},
            "tool_calls": 2,
            "duration_s": 3.2,
        }
    ]
    html = render_dashboard([run], reviews)
    assert "Recall by bug type" in html and "o/r#1" in html and "29%" in html
    assert "<script>alert" not in render_dashboard([run], [{**reviews[0], "pr": "<script>alert"}])
