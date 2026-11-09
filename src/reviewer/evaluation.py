"""Eval harness: load seeded-bug PRs, score review comments, write reports."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .diff import make_diff
from .models import Category, ReviewComment, Severity
from .repo import InMemoryRepo
from .tools import lint_python

LINE_TOLERANCE = 2


@dataclass
class ExpectedBug:
    path: str
    line: int
    category: str
    match: str


@dataclass
class Case:
    id: str
    title: str
    description: str
    before: dict[str, str]
    after: dict[str, str]
    bugs: list[ExpectedBug]

    @property
    def diff(self) -> str:
        parts = []
        for path in sorted(self.after):
            old = self.before.get(path)
            if old != self.after[path]:
                parts.append(make_diff(path, old, self.after[path]))
        return "".join(parts)

    @property
    def repo(self) -> InMemoryRepo:
        return InMemoryRepo(self.after)


@dataclass
class CaseScore:
    id: str
    bugs: int
    found: int
    comments: int
    true_positive_comments: int
    missed: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    tool_calls: int = 0
    errors: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    found_categories: list[str] = field(default_factory=list)


def _read_tree(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def load_case(case_dir: Path) -> Case:
    meta = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    after = _read_tree(case_dir / "after")
    bugs = []
    for b in meta.get("bugs", []):
        text = after.get(b["path"])
        if text is None:
            raise ValueError(f"{case_dir.name}: no after-file {b['path']}")
        lines = [n for n, line in enumerate(text.splitlines(), 1) if b["match"] in line]
        if len(lines) != 1:
            raise ValueError(f"{case_dir.name}: match {b['match']!r} hit {len(lines)} lines")
        bugs.append(ExpectedBug(b["path"], lines[0], b.get("category", "bug"), b["match"]))
    return Case(
        id=case_dir.name,
        title=meta.get("title", case_dir.name),
        description=meta.get("description", ""),
        before=_read_tree(case_dir / "before"),
        after=after,
        bugs=bugs,
    )


def load_cases(root: Path) -> list[Case]:
    return [load_case(d) for d in sorted(root.iterdir()) if (d / "case.json").is_file()]


def score_case(
    case: Case, comments: list[ReviewComment], tool_calls: int = 0, errors: list[str] | None = None
) -> CaseScore:
    unmatched = list(range(len(case.bugs)))
    tp_comments = 0
    fps: list[str] = []
    for c in comments:
        hit = next(
            (
                i
                for i in unmatched
                if case.bugs[i].path == c.path and abs(case.bugs[i].line - c.line) <= LINE_TOLERANCE
            ),
            None,
        )
        if hit is not None:
            unmatched.remove(hit)
            tp_comments += 1
        elif any(b.path == c.path and abs(b.line - c.line) <= LINE_TOLERANCE for b in case.bugs):
            tp_comments += 1  # 2nd comment on a bug already found, not a FP
        else:
            fps.append(f"{c.path}:{c.line} {c.body[:80]}")
    return CaseScore(
        id=case.id,
        bugs=len(case.bugs),
        found=len(case.bugs) - len(unmatched),
        comments=len(comments),
        true_positive_comments=tp_comments,
        missed=[f"{case.bugs[i].path}:{case.bugs[i].line}" for i in unmatched],
        false_positives=fps,
        tool_calls=tool_calls,
        errors=errors or [],
        categories=[b.category for b in case.bugs],
        found_categories=[b.category for i, b in enumerate(case.bugs) if i not in unmatched],
    )


def lint_only_comments(case: Case) -> list[ReviewComment]:
    # baseline: ruff on added lines, no LLM
    from .diff import parse_unified_diff

    out = []
    for f in parse_unified_diff(case.diff):
        src = case.after.get(f.path)
        if src is None:
            continue
        for issue in lint_python(f.path, src):
            if issue["line"] in f.added_lines:
                out.append(
                    ReviewComment(
                        path=f.path,
                        line=issue["line"],
                        severity=Severity.major,
                        category=Category.security
                        if str(issue["code"]).startswith("S")
                        else Category.bug,
                        body=f"{issue['code']} {issue['message']}",
                    )
                )
    return out


@dataclass
class Summary:
    cases: int
    bugs: int
    found: int
    comments: int
    true_positive_comments: int
    clean_cases: int
    clean_cases_with_comments: int
    precision: float
    recall: float
    f1: float
    avg_tool_calls: float


def summarize(scores: list[CaseScore]) -> Summary:
    bugs = sum(s.bugs for s in scores)
    found = sum(s.found for s in scores)
    comments = sum(s.comments for s in scores)
    tp = sum(s.true_positive_comments for s in scores)
    precision = tp / comments if comments else 1.0
    recall = found / bugs if bugs else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    clean = [s for s in scores if s.bugs == 0]
    return Summary(
        cases=len(scores),
        bugs=bugs,
        found=found,
        comments=comments,
        true_positive_comments=tp,
        clean_cases=len(clean),
        clean_cases_with_comments=sum(1 for s in clean if s.comments),
        precision=round(precision, 3),
        recall=round(recall, 3),
        f1=round(f1, 3),
        avg_tool_calls=round(sum(s.tool_calls for s in scores) / len(scores), 2) if scores else 0,
    )


def to_markdown(label: str, summary: Summary, scores: list[CaseScore]) -> str:
    lines = [
        f"## Eval: {label}",
        "",
        f"- precision **{summary.precision:.0%}**, recall **{summary.recall:.0%}**, "
        f"F1 **{summary.f1:.2f}**",
        f"- {summary.found}/{summary.bugs} seeded bugs found, {summary.comments} comments, "
        f"{summary.clean_cases_with_comments}/{summary.clean_cases} clean PRs got comments",
        f"- avg tool calls per PR: {summary.avg_tool_calls}",
        "",
        "| case | bugs | found | comments | false positives |",
        "|---|---|---|---|---|",
    ]
    for s in scores:
        lines.append(f"| {s.id} | {s.bugs} | {s.found} | {s.comments} | {len(s.false_positives)} |")
    return "\n".join(lines) + "\n"


def to_json(label: str, summary: Summary, scores: list[CaseScore]) -> str:
    return json.dumps(
        {
            "label": label,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "summary": asdict(summary),
            "cases": [asdict(s) for s in scores],
        },
        indent=2,
    )
