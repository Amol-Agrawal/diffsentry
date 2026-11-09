"""Usage: python eval/run_eval.py [--provider lint-only] [--model M] [--min-recall 0.6]

Per-case results are cached in eval/results/cache/<label>/, so if the run stops on a rate
limit you can run the same command again later and it picks up where it left off.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))

from reviewer.evaluation import (  # noqa: E402
    CaseScore,
    lint_only_comments,
    load_cases,
    score_case,
    summarize,
    to_json,
    to_markdown,
)
from reviewer.graph import ReviewConfig, review_diff  # noqa: E402


def is_rate_limit(e: Exception) -> bool:
    text = f"{type(e).__name__} {e}"
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "RateLimit" in text


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default=None, help="gemini | openai | ollama | lint-only")
    p.add_argument("--model", default=None)
    p.add_argument("--cases", default=str(ROOT / "cases"))
    p.add_argument("--only", default=None, help="substring filter on case id")
    p.add_argument("--sleep", type=float, default=0.0, help="seconds between cases (rate limits)")
    p.add_argument("--fresh", action="store_true", help="ignore cached per-case results")
    p.add_argument("--min-recall", type=float, default=None)
    p.add_argument("--min-precision", type=float, default=None)
    p.add_argument("--out", default=str(ROOT / "results"))
    args = p.parse_args()

    cases = [c for c in load_cases(Path(args.cases)) if not args.only or args.only in c.id]
    baseline = args.provider == "lint-only"
    llm = None
    if baseline:
        label = "lint-only"
    else:
        from reviewer.llm import DEFAULT_MODELS, get_chat_model

        provider = args.provider or "gemini"
        llm = get_chat_model(provider, args.model)
        label = args.model or DEFAULT_MODELS.get(provider, provider)

    out_dir = Path(args.out)
    cache = out_dir / "cache" / label
    cache.mkdir(parents=True, exist_ok=True)

    scores: list[CaseScore] = []
    stopped = False
    for i, case in enumerate(cases):
        cached = cache / f"{case.id}.json"
        if cached.exists() and not args.fresh and not baseline:
            score = CaseScore(**json.loads(cached.read_text(encoding="utf-8")))
            print(f"[cached] {case.id}")
        else:
            if baseline:
                score = score_case(case, lint_only_comments(case))
            else:
                try:
                    out = review_diff(
                        case.diff,
                        case.repo,
                        llm,
                        title=case.title,
                        description=case.description,
                        config=ReviewConfig(),
                    )
                except Exception as e:
                    if not is_rate_limit(e):
                        raise
                    print(f"\nRate limited on {case.id}: {str(e)[:200]}")
                    print("Progress is saved. Run the same command later to continue.")
                    stopped = True
                    break
                score = score_case(case, out.comments, out.tool_calls, out.errors)
                cached.write_text(json.dumps(asdict(score)), encoding="utf-8")
                if args.sleep and i < len(cases) - 1:
                    time.sleep(args.sleep)
            status = "ok" if not score.missed and not score.false_positives else "!!"
            print(
                f"[{status}] {case.id}: found {score.found}/{score.bugs}, "
                f"{score.comments} comments, {len(score.false_positives)} FP, "
                f"{score.tool_calls} tool calls"
            )
        scores.append(score)

    if stopped:
        print(f"{len(scores)}/{len(cases)} cases done for {label}; summary not written yet.")
        return 2

    summary = summarize(scores)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{label}.json").write_text(to_json(label, summary, scores), encoding="utf-8")
    md = to_markdown(label, summary, scores)
    (out_dir / f"{label}.md").write_text(md, encoding="utf-8")
    print("\n" + md)

    failed = []
    if args.min_recall is not None and summary.recall < args.min_recall:
        failed.append(f"recall {summary.recall:.2f} < {args.min_recall}")
    if args.min_precision is not None and summary.precision < args.min_precision:
        failed.append(f"precision {summary.precision:.2f} < {args.min_precision}")
    if failed:
        print("EVAL GATE FAILED: " + "; ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
