import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from reviewer import app as app_module

SECRET = "s3cret"


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _pr_event(action="opened", sha="abc123", draft=False) -> dict:
    return {
        "action": action,
        "pull_request": {"number": 7, "draft": draft, "head": {"sha": sha}},
        "repository": {"name": "demo", "full_name": "amol/demo", "owner": {"login": "amol"}},
        "installation": {"id": 42},
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    calls = []
    monkeypatch.setattr(app_module, "run_review", lambda pr, inst: calls.append((pr, inst)))
    app_module._seen.clear()
    c = TestClient(app_module.app)
    c.calls = calls
    return c


def _post(client, event, payload):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhook",
        content=body,
        headers={"X-GitHub-Event": event, "X-Hub-Signature-256": _sig(body)},
    )


def test_rejects_bad_signature(client):
    r = client.post(
        "/webhook", content=b"{}", headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": "x"}
    )
    assert r.status_code == 401


def test_ping(client):
    assert _post(client, "ping", {"zen": "hi"}).json() == {"status": "pong"}


def test_queues_review_for_opened_pr(client):
    r = _post(client, "pull_request", _pr_event())
    assert r.status_code == 202 and r.json()["status"] == "queued"
    pr, inst = client.calls[0]
    assert (pr.owner, pr.repo, pr.number, inst) == ("amol", "demo", 7, 42)


def test_ignores_drafts_and_other_actions(client):
    assert _post(client, "pull_request", _pr_event(draft=True)).json()["status"] == "ignored"
    assert _post(client, "pull_request", _pr_event("closed")).json()["status"] == "ignored"
    assert client.calls == []


def test_deduplicates_redelivery(client):
    _post(client, "pull_request", _pr_event())
    assert _post(client, "pull_request", _pr_event()).json()["status"] == "duplicate"
    assert _post(client, "pull_request", _pr_event("synchronize", sha="def456")).status_code == 202
    assert len(client.calls) == 2


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_dashboard_token(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", "t0k")
    assert client.get("/dashboard").status_code == 401
    assert client.get("/dashboard?token=t0k").status_code == 200
