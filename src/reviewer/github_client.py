"""Small GitHub REST client."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import httpx
import jwt

from .models import ReviewComment

API = "https://api.github.com"
MAX_FILE_BYTES = 300_000


@dataclass
class TokenAuth:
    token: str

    def get_token(self) -> str:
        return self.token


class AppAuth:
    def __init__(self, app_id: str, private_key: str, installation_id: int) -> None:
        self.app_id = app_id
        self.private_key = private_key.replace("\\n", "\n")
        self.installation_id = installation_id
        self._token: str | None = None
        self._expires = 0.0

    def _app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": self.app_id}
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    def get_token(self) -> str:
        if self._token and time.time() < self._expires - 120:
            return self._token
        r = httpx.post(
            f"{API}/app/installations/{self.installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {self._app_jwt()}",
                "Accept": "application/vnd.github+json",
            },
            timeout=20,
        )
        r.raise_for_status()
        self._token = r.json()["token"]
        self._expires = time.time() + 3600
        return self._token


class GitHubClient:
    def __init__(
        self,
        auth: TokenAuth | AppAuth,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.auth = auth
        self.http = httpx.Client(base_url=API, timeout=timeout, transport=transport)

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth.get_token()}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pr-review-agent",
        }

    def get_pull(self, owner: str, repo: str, number: int) -> dict:
        r = self.http.get(f"/repos/{owner}/{repo}/pulls/{number}", headers=self._headers())
        r.raise_for_status()
        return r.json()

    def get_pull_diff(self, owner: str, repo: str, number: int) -> str:
        r = self.http.get(
            f"/repos/{owner}/{repo}/pulls/{number}",
            headers=self._headers("application/vnd.github.diff"),
        )
        r.raise_for_status()
        return r.text

    def get_file(self, owner: str, repo: str, path: str, ref: str) -> str | None:
        r = self.http.get(
            f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref}, headers=self._headers()
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or data.get("type") != "file":
            return None
        if data.get("size", 0) > MAX_FILE_BYTES or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def list_tree(self, owner: str, repo: str, ref: str) -> list[str]:
        r = self.http.get(
            f"/repos/{owner}/{repo}/git/trees/{ref}",
            params={"recursive": "1"},
            headers=self._headers(),
        )
        r.raise_for_status()
        return [
            t["path"]
            for t in r.json().get("tree", [])
            if t.get("type") == "blob" and t.get("size", 0) <= MAX_FILE_BYTES
        ]

    def create_review(
        self,
        owner: str,
        repo: str,
        number: int,
        commit_id: str,
        body: str,
        comments: list[ReviewComment],
    ) -> dict:
        payload = {
            "commit_id": commit_id,
            "event": "COMMENT",
            "body": body,
            "comments": [
                {"path": c.path, "line": c.line, "side": "RIGHT", "body": format_comment(c)}
                for c in comments
            ],
        }
        url = f"/repos/{owner}/{repo}/pulls/{number}/reviews"
        r = self.http.post(url, json=payload, headers=self._headers())
        # 422 = some comment line isn't in the diff. post everything in the body instead
        if r.status_code == 422 and comments:
            listed = "\n".join(f"- `{c.path}:{c.line}` {format_comment(c)}" for c in comments)
            payload = {"commit_id": commit_id, "event": "COMMENT", "body": f"{body}\n\n{listed}"}
            r = self.http.post(url, json=payload, headers=self._headers())
        r.raise_for_status()
        return r.json()


def format_comment(c: ReviewComment) -> str:
    return f"**[{c.severity.value}] {c.category.value}:** {c.body}"


class GitHubRepo:
    def __init__(self, client: GitHubClient, owner: str, repo: str, ref: str) -> None:
        self.client, self.owner, self.repo, self.ref = client, owner, repo, ref
        self._files: dict[str, str | None] = {}
        self._tree: list[str] | None = None

    def read_file(self, path: str) -> str | None:
        if path not in self._files:
            self._files[path] = self.client.get_file(self.owner, self.repo, path, self.ref)
        return self._files[path]

    def list_files(self) -> list[str]:
        if self._tree is None:
            try:
                self._tree = self.client.list_tree(self.owner, self.repo, self.ref)
            except httpx.HTTPError:
                self._tree = []
        return self._tree
