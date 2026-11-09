"""Usage: python eval/dashboard.py  (writes eval/results/dashboard.html)"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))

from reviewer.dashboard import load_runs, render_dashboard  # noqa: E402


def main() -> int:
    results = ROOT / "results"
    runs = load_runs(results)
    # older result files have no per-case bug types; fill them in from the case files
    cases = {d.name: d for d in (ROOT / "cases").iterdir() if (d / "case.json").is_file()}
    for run in runs:
        for c in run["cases"]:
            if "categories" not in c and c["id"] in cases:
                bugs = json.loads((cases[c["id"]] / "case.json").read_text())["bugs"]
                c["categories"] = [b.get("category", "bug") for b in bugs]
                c["found_categories"] = c["categories"] if c["found"] == c["bugs"] else []
    if not runs:
        print("no results yet, run: python eval/run_eval.py --provider lint-only")
        return 1
    out = results / "dashboard.html"
    out.write_text(render_dashboard(runs), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
