"""Pydantic models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Severity(StrEnum):
    critical = "critical"
    major = "major"
    minor = "minor"
    nit = "nit"


SEVERITY_RANK = {Severity.critical: 0, Severity.major: 1, Severity.minor: 2, Severity.nit: 3}


class Category(StrEnum):
    bug = "bug"
    security = "security"
    performance = "performance"
    error_handling = "error-handling"
    tests = "tests"
    style = "style"


class ReviewComment(BaseModel):
    path: str
    line: int = Field(ge=1)
    severity: Severity = Severity.minor
    category: Category = Category.bug
    body: str = Field(min_length=1)

    @field_validator("severity", mode="before")
    @classmethod
    def _norm_severity(cls, v: object) -> object:
        return v.lower().strip() if isinstance(v, str) else v

    @field_validator("category", mode="before")
    @classmethod
    def _norm_category(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.lower().strip().replace("_", "-").replace(" ", "-")
            aliases = {"error": "error-handling", "test": "tests", "perf": "performance"}
            return aliases.get(v, v)
        return v


class ReviewResult(BaseModel):
    summary: str = ""
    comments: list[ReviewComment] = Field(default_factory=list)


class Hunk(BaseModel):
    new_start: int
    new_lines: int
    added_lines: list[int] = Field(default_factory=list)
    text: str = ""


class FileDiff(BaseModel):
    path: str
    old_path: str | None = None
    is_new: bool = False
    is_deleted: bool = False
    hunks: list[Hunk] = Field(default_factory=list)

    @property
    def commentable_lines(self) -> set[int]:
        # github only accepts review comments on lines inside a hunk
        lines: set[int] = set()
        for h in self.hunks:
            lines.update(range(h.new_start, h.new_start + h.new_lines))
        return lines

    @property
    def added_lines(self) -> set[int]:
        out: set[int] = set()
        for h in self.hunks:
            out.update(h.added_lines)
        return out
