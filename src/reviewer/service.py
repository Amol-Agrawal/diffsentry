"""Fetch a PR, run the review, post comments."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from .diff import parse_unified_diff
from .github_client import GitHubClient, GitHubRepo
from .graph import ReviewConfig, ReviewOutput, review_diff

log = logging.getLogger(__name__)

MAX_FILES = 50
MAX_DIFF_CHARS = 200_000


@dataclass
class PRRef:
    owner: str
    repo: str
    number: int

    @classmethod
    def parse(cls, url_or_ref: str) -> PRRef:
        # https://github.com/o/r/pull/12 or o/r#12
        s = url_or_ref.strip().rstrip("/")
        if "github.com/" in s:
            parts = s.split("github.com/", 1)[1].split("/")
            return cls(parts[0], parts[1], int(parts[3]))
        repo_part, num = s.split("#")
        owner, repo = repo_part.split("/")
        return cls(owner, repo, int(num))


def summary_body(out: ReviewOutput) -> str:
    counts: dict[str, int] = {}
    for c in out.comments:
        counts[c.severity.value] = counts.get(c.severity.value, 0) + 1
    tally = ", ".join(f"{n} {s}" for s, n in counts.items()) or "no issues flagged"
    text = out.summary.strip() or "Automated review complete."
    return f"### AI review\n{text}\n\n_{tally}_"


def review_pull_request(
    client: GitHubClient,
    pr: PRRef,
    llm: BaseChatModel,
    *,
    config: ReviewConfig | None = None,
    post: bool = True,
) -> ReviewOutput | None:
    meta = client.get_pull(pr.owner, pr.repo, pr.number)
    if meta.get("draft"):
        log.info("skipping draft PR %s/%s#%s", pr.owner, pr.repo, pr.number)
        return None
    head_sha = meta["head"]["sha"]
    diff = client.get_pull_diff(pr.owner, pr.repo, pr.number)
    if len(diff) > MAX_DIFF_CHARS or len(parse_unified_diff(diff)) > MAX_FILES:
        log.info("diff too large, skipping %s/%s#%s", pr.owner, pr.repo, pr.number)
        return None

    repo = GitHubRepo(client, pr.owner, pr.repo, head_sha)
    out = review_diff(
        diff,
        repo,
        llm,
        title=meta.get("title", ""),
        description=meta.get("body") or "",
        config=config,
    )
    log.info(
        "reviewed %s/%s#%s: %d comments, %d tool calls, errors=%s",
        pr.owner,
        pr.repo,
        pr.number,
        len(out.comments),
        out.tool_calls,
        out.errors,
    )
    if post:
        client.create_review(
            pr.owner, pr.repo, pr.number, head_sha, summary_body(out), out.comments
        )
    return out
