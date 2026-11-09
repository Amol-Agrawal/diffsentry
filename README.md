# DiffSentry

DiffSentry is a bot that reviews GitHub pull requests. It reads the diff, looks at surrounding
code when it needs to, runs ruff, and leaves inline comments on bugs and security problems.

I built this to learn LangGraph properly and to see how far a small model gets on code review when
you give it tools and actually measure it.

## How it works

```
prepare -> agent <-> tools (read_file, search_code, run_linter)
             |
          finalize -> validate -> post review
```

- **prepare**: parse the diff, run ruff on changed .py files, build the prompt. The diff is shown
  to the model with new-file line numbers so it can point at exact lines.
- **agent**: LLM with tools. Loops until it stops calling tools or hits 6 iterations.
- **finalize**: parse the JSON answer. If the JSON is broken, ask once more.
- **validate**: throw away comments GitHub won't accept (line not in the diff, file not in the PR),
  duplicates, and anything below the severity threshold. Max 15 comments.

I used plain JSON output instead of each provider's structured-output API so the same code works
with Gemini, OpenAI and Ollama.

If GitHub rejects an inline comment (422, usually a line outside the diff), the review is posted
again with everything in the body.

## Eval

`eval/cases/` has 20 small PRs: 17 with one planted bug each (SQL injection, shell injection,
unsafe yaml.load, hardcoded key, password in logs, inverted admin check, off-by-one, missing
await, mutable default, `is` vs `==`, divide by zero, floor division on money, removing from a
list while looping over it, infinite retry, swallowed exception, no input validation, N+1 query)
and 3 clean PRs to catch false positives.

A comment counts if it lands within 2 lines of the bug.

```
python eval/run_eval.py --provider lint-only   # ruff only
python eval/run_eval.py --sleep 4              # the agent, needs GOOGLE_API_KEY
```

CI can run the agent eval on PRs (when the `GOOGLE_API_KEY` secret is set) and fail the build
if recall or precision drops below a threshold.

## Dashboard

`python eval/dashboard.py` builds a local HTML report from your eval runs: recall and precision
vs the ruff baseline, recall by bug type, and per-case misses and false positives. Results stay
local (`eval/results/` is gitignored). The webhook service also serves it at `/dashboard`, plus
the last 100 PRs it reviewed (status, comments by severity, tool calls, duration). Set
`DASHBOARD_TOKEN` to require `?token=...` when it's deployed.

## Setup

```
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export GOOGLE_API_KEY=...
pytest -q
```

Review local changes:

```
git diff main | pr-review diff - --repo-dir .
```

Review a PR (add `--post` to actually comment):

```
export GITHUB_TOKEN=...
pr-review pr https://github.com/OWNER/REPO/pull/1
```

Other models: `--provider openai`, or a local open-weight model with Ollama:
`ollama pull qwen3:8b` then `--provider ollama` (install the matching extra). No API key or quota.

## Running it on a repo

**GitHub Action**: add a `GOOGLE_API_KEY` secret and `.github/workflows/ai-review.yml` reviews
every PR with the built-in `GITHUB_TOKEN`. Easiest option.

**GitHub App on Cloud Run**:

1. Create a GitHub App with Pull requests (read/write) and Contents (read), subscribed to pull
   request events, with a webhook secret and a private key.
2. Put `google-api-key`, `github-app-private-key`, `github-webhook-secret` in Secret Manager.
3. Set repo variables `GCP_PROJECT_ID`, `GITHUB_APP_ID` and secret `GCP_SA_KEY`. Pushes to main
   deploy after CI passes.
4. Set the App's webhook URL to `https://<service-url>/webhook`.

The webhook checks the HMAC signature, returns 202 right away (GitHub gives you 10s) and does the
review in the background, so the service runs with `--no-cpu-throttling`. Redelivered events for
the same head commit are ignored.

Env vars are listed in `.env.example`.

## Layout

```
src/reviewer/   graph.py tools.py diff.py prompts.py llm.py github_client.py service.py app.py cli.py
                dashboard.py
eval/           cases/, run_eval.py, dashboard.py
tests/          no network, uses a scripted fake LLM
```

## TODO

- ruff only covers Python, other languages get LLM-only review
- eval set is small and synthetic, want to add real bug-fix commits from open source repos
- cost/latency per review
