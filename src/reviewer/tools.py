"""Agent tools and the ruff wrapper."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

from langchain_core.tools import BaseTool, tool

from .repo import RepoSource

# bug/security rules only, no style. S101 (assert) is too noisy
LINT_SELECT = "E9,F,B,S"
LINT_IGNORE = "S101"
MAX_READ_LINES = 200
MAX_SEARCH_HITS = 30


def _ruff_cmd() -> list[str]:
    exe = shutil.which("ruff")
    return [exe] if exe else [sys.executable, "-m", "ruff"]


def lint_python(path: str, source: str, timeout: float = 20.0) -> list[dict]:
    if not path.endswith(".py"):
        return []
    cmd = _ruff_cmd() + [
        "check",
        "--no-cache",
        "--isolated",
        "--output-format",
        "json",
        "--select",
        LINT_SELECT,
        "--ignore",
        LINT_IGNORE,
        "--stdin-filename",
        path,
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd, input=source, capture_output=True, text=True, timeout=timeout, check=False
        )
        issues = json.loads(proc.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []
    return [
        {
            "line": i.get("location", {}).get("row"),
            "code": i.get("code"),
            "message": i.get("message"),
        }
        for i in issues
        if i.get("location", {}).get("row")
    ]


def number_lines(text: str, start: int = 1, end: int | None = None) -> str:
    lines = text.splitlines()
    end = len(lines) if end is None else min(end, len(lines))
    start = max(1, start)
    if end - start + 1 > MAX_READ_LINES:
        end = start + MAX_READ_LINES - 1
    return "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(start, end + 1))


def make_tools(repo: RepoSource) -> list[BaseTool]:
    @tool
    def read_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
        """Read a file from the PR head commit with line numbers.

        Use it to see code around a change (callers, definitions, imports). Max 200 lines/call.
        """
        text = repo.read_file(path)
        if text is None:
            return f"ERROR: file not found: {path}"
        return number_lines(text, start_line, end_line) or "(empty file)"

    @tool
    def search_code(pattern: str, path_glob: str = "") -> str:
        """Regex search across repository files. Returns up to 30 'path:line: text' hits.

        Use it to find where a function or variable is defined or used.
        """
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"ERROR: bad regex: {e}"
        hits: list[str] = []
        for path in repo.list_files():
            if path_glob and path_glob not in path:
                continue
            text = repo.read_file(path)
            if not text or "\x00" in text[:1024]:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{path}:{n}: {line.strip()[:160]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return "\n".join(hits) + "\n... [more hits truncated]"
        return "\n".join(hits) or "no matches"

    @tool
    def run_linter(path: str) -> str:
        """Run the ruff linter (pyflakes, bugbear, bandit security rules) on a Python file."""
        text = repo.read_file(path)
        if text is None:
            return f"ERROR: file not found: {path}"
        issues = lint_python(path, text)
        if not issues:
            return "no issues"
        return "\n".join(f"{path}:{i['line']}: {i['code']} {i['message']}" for i in issues[:50])

    return [read_file, search_code, run_linter]
