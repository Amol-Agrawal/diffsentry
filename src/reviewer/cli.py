"""CLI. pr-review diff <patch> | pr <url> | action"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .graph import ReviewConfig, ReviewOutput, review_diff
from .llm import get_chat_model
from .models import Severity
from .repo import LocalRepo


def _print(out: ReviewOutput, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "summary": out.summary,
                    "comments": [c.model_dump(mode="json") for c in out.comments],
                    "tool_calls": out.tool_calls,
                    "errors": out.errors,
                },
                indent=2,
            )
        )
        return
    print(out.summary or "(no summary)")
    for c in out.comments:
        print(f"\n{c.path}:{c.line}  [{c.severity.value}] {c.category.value}\n  {c.body}")
    print(f"\n{len(out.comments)} comments, {out.tool_calls} tool calls")
    for e in out.errors:
        print(f"warning: {e}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pr-review")
    p.add_argument("--provider", default=None, help="gemini (default), openai, ollama")
    p.add_argument("--model", default=None)
    p.add_argument("--min-severity", default="minor", choices=[s.value for s in Severity])
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diff", help="review a unified diff file")
    d.add_argument("patch", help="path to .patch/.diff, or '-' for stdin")
    d.add_argument("--repo-dir", default=".", help="checkout at the new revision")
    d.add_argument("--title", default="")

    r = sub.add_parser("pr", help="review a GitHub PR by URL or owner/repo#N")
    r.add_argument("ref")
    r.add_argument("--post", action="store_true", help="post the review to GitHub")

    sub.add_parser("action", help="review the PR that triggered this GitHub Actions run")

    args = p.parse_args(argv)
    config = ReviewConfig(min_severity=Severity(args.min_severity))
    llm = get_chat_model(args.provider, args.model)

    if args.cmd == "diff":
        text = sys.stdin.read() if args.patch == "-" else open(args.patch, encoding="utf-8").read()
        out = review_diff(text, LocalRepo(args.repo_dir), llm, title=args.title, config=config)
        _print(out, args.json)
        return 0

    from .github_client import GitHubClient, TokenAuth
    from .service import PRRef, review_pull_request

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2
    client = GitHubClient(TokenAuth(token))

    if args.cmd == "pr":
        out = review_pull_request(client, PRRef.parse(args.ref), llm, config=config, post=args.post)
    else:  # action
        event = json.load(open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8"))
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
        number = int(event["pull_request"]["number"])
        out = review_pull_request(client, PRRef(owner, repo, number), llm, config=config)
    if out is None:
        print("skipped (draft or too large)")
        return 0
    _print(out, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
