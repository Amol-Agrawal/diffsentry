"""Unified diff parsing."""

from __future__ import annotations

import difflib
import re

from .models import FileDiff, Hunk

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None
    new_line = 0
    hunk_lines: list[str] = []

    def close_hunk() -> None:
        nonlocal hunk, hunk_lines
        if current is not None and hunk is not None:
            hunk.text = "\n".join(hunk_lines)
            current.hunks.append(hunk)
        hunk, hunk_lines = None, []

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            close_hunk()
            current = FileDiff(path="")
            files.append(current)
            continue
        if raw.startswith("--- "):
            close_hunk()
            if current is None:  # plain diff without "diff --git" header
                current = FileDiff(path="")
                files.append(current)
            old = raw[4:].strip()
            current.old_path = None if old == "/dev/null" else _strip_prefix(old)
            current.is_new = old == "/dev/null"
            continue
        if raw.startswith("+++ ") and current is not None and hunk is None:
            new = raw[4:].strip()
            if new == "/dev/null":
                current.is_deleted = True
                current.path = current.old_path or ""
            else:
                current.path = _strip_prefix(new)
            continue
        m = _HUNK_RE.match(raw)
        if m and current is not None:
            close_hunk()
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            hunk = Hunk(new_start=new_start, new_lines=new_count)
            hunk_lines = [raw]
            new_line = new_start
            continue
        if hunk is None:
            continue
        if raw.startswith("+"):
            hunk.added_lines.append(new_line)
            hunk_lines.append(f"{new_line:>5} + {raw[1:]}")
            new_line += 1
        elif raw.startswith("-"):
            hunk_lines.append(f"{'':>5} - {raw[1:]}")
        elif raw.startswith("\\"):
            continue  # "\ No newline at end of file"
        else:
            hunk_lines.append(f"{new_line:>5}   {raw[1:] if raw.startswith(' ') else raw}")
            new_line += 1
    close_hunk()
    return [f for f in files if f.path and not f.is_deleted]


def _strip_prefix(path: str) -> str:
    path = path.split("\t")[0]
    return path[2:] if path[:2] in ("a/", "b/") else path


def render_for_llm(files: list[FileDiff], max_chars: int = 60_000) -> str:
    parts: list[str] = []
    for f in files:
        header = f"### {f.path}" + (" (new file)" if f.is_new else "")
        parts.append(header)
        for h in f.hunks:
            parts.append(h.text)
        parts.append("")
    out = "\n".join(parts)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n... [diff truncated]"
    return out


def make_diff(path: str, before: str | None, after: str) -> str:
    before_lines = [] if before is None else before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    fromfile = "/dev/null" if before is None else f"a/{path}"
    body = "".join(
        difflib.unified_diff(before_lines, after_lines, fromfile=fromfile, tofile=f"b/{path}", n=3)
    )
    return f"diff --git a/{path} b/{path}\n{body}"
