"""Webhook server for the GitHub App."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from collections import OrderedDict, deque
from datetime import UTC, datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from .dashboard import load_runs, render_dashboard
from .github_client import AppAuth, GitHubClient, TokenAuth
from .llm import get_chat_model
from .service import PRRef, review_pull_request

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("reviewer.app")

REVIEW_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}

app = FastAPI(title="pr-review-agent")
_seen: OrderedDict[str, None] = OrderedDict()
_reviews: deque[dict] = deque(maxlen=100)  # recent reviews for the dashboard
EVAL_DIR = Path(os.getenv("EVAL_RESULTS_DIR", "eval/results"))


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _remember(key: str, limit: int = 1000) -> bool:
    # github sometimes redelivers the same event
    if key in _seen:
        return False
    _seen[key] = None
    while len(_seen) > limit:
        _seen.popitem(last=False)
    return True


def _client_for(installation_id: int | None) -> GitHubClient:
    app_id, key = os.getenv("GITHUB_APP_ID"), os.getenv("GITHUB_APP_PRIVATE_KEY")
    if app_id and key and installation_id:
        return GitHubClient(AppAuth(app_id, key, installation_id))
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("no GitHub credentials configured")
    return GitHubClient(TokenAuth(token))


def run_review(pr: PRRef, installation_id: int | None) -> None:
    start = time.monotonic()
    rec = {
        "time": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "pr": f"{pr.owner}/{pr.repo}#{pr.number}",
    }
    try:
        out = review_pull_request(_client_for(installation_id), pr, get_chat_model())
        if out is None:
            rec["status"] = "skipped"
        else:
            sev: dict[str, int] = {}
            for c in out.comments:
                sev[c.severity.value] = sev.get(c.severity.value, 0) + 1
            rec.update(
                status="posted",
                comments=len(out.comments),
                by_severity=sev,
                tool_calls=out.tool_calls,
            )
    except Exception:
        rec["status"] = "error"
        log.exception("review failed for %s/%s#%s", pr.owner, pr.repo, pr.number)
    rec["duration_s"] = time.monotonic() - start
    _reviews.append(rec)


def _check_dashboard_token(token: str | None) -> None:
    expected = os.getenv("DASHBOARD_TOKEN")
    if expected and not hmac.compare_digest(expected, token or ""):
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(token: str | None = None) -> str:
    _check_dashboard_token(token)
    return render_dashboard(load_runs(EVAL_DIR) if EVAL_DIR.is_dir() else [], list(_reviews))


@app.get("/api/reviews")
def api_reviews(token: str | None = None) -> list[dict]:
    _check_dashboard_token(token)
    return list(_reviews)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/webhook", status_code=202)
async def webhook(
    request: Request,
    background: BackgroundTasks,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        if not verify_signature(secret, body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="bad signature")
    elif os.getenv("ALLOW_UNSIGNED_WEBHOOKS") != "1":
        raise HTTPException(status_code=500, detail="GITHUB_WEBHOOK_SECRET not configured")

    if x_github_event == "ping":
        return {"status": "pong"}
    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"event {x_github_event}"}

    payload = json.loads(body or b"{}")
    action = payload.get("action")
    pr = payload.get("pull_request") or {}
    if action not in REVIEW_ACTIONS or pr.get("draft"):
        return {"status": "ignored", "reason": f"action {action}"}

    repo = payload["repository"]
    ref = PRRef(repo["owner"]["login"], repo["name"], int(pr["number"]))
    if not _remember(f"{repo['full_name']}#{ref.number}@{pr['head']['sha']}"):
        return {"status": "duplicate"}
    installation_id = (payload.get("installation") or {}).get("id")
    background.add_task(run_review, ref, installation_id)
    return {"status": "queued", "pr": f"{repo['full_name']}#{ref.number}"}
