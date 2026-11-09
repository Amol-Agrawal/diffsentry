"""HTML dashboard: latest eval run vs the lint-only baseline, plus recent live reviews."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

BAR_H = 14
GAP = 2


def load_runs(results_dir: Path) -> list[dict]:
    runs = []
    for p in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "summary" in data and "cases" in data:
            runs.append(data)
    return runs


def pick_runs(runs: list[dict]) -> tuple[dict | None, dict | None]:
    def latest(rs: list[dict]) -> dict | None:
        return max(rs, key=lambda r: r.get("created_at", ""), default=None)

    baseline = latest([r for r in runs if r.get("label") == "lint-only"])
    agent = latest([r for r in runs if r.get("label") != "lint-only"])
    return agent, baseline


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _bar_path(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    # square at the baseline (left), rounded at the data end (right)
    if w <= 0:
        return ""
    r = min(r, w / 2, h / 2)
    return (
        f"M{x:.1f},{y:.1f}H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}"
        f"V{y + h - r:.1f}Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f}H{x:.1f}Z"
    )


def _hbar_chart(rows: list[tuple[str, list[tuple[str, float, str, str]]]], width: int = 560) -> str:
    """rows: [(row label, [(series key, value 0..1, label at tip, tooltip), ...])]"""
    left, right, top = 96, 56, 8
    plot_w = width - left - right
    n_series = max((len(s) for _, s in rows), default=1)
    row_h = n_series * BAR_H + (n_series - 1) * GAP + 18
    height = top + len(rows) * row_h + 22
    out = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="bar chart" class="chart">'
    ]
    for t in (0, 0.25, 0.5, 0.75, 1):
        x = left + t * plot_w
        out.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height - 20}" class="grid"/>'
            f'<text x="{x:.1f}" y="{height - 6}" class="tick" text-anchor="middle">{_pct(t)}</text>'
        )
    for i, (label, series) in enumerate(rows):
        y0 = top + i * row_h + 9
        mid = y0 + (len(series) * (BAR_H + GAP) - GAP) / 2
        out.append(
            f'<text x="{left - 10}" y="{mid + 4:.1f}" class="rowlabel" text-anchor="end">'
            f"{escape(label)}</text>"
        )
        for j, (key, value, tip_label, tooltip) in enumerate(series):
            y = y0 + j * (BAR_H + GAP)
            w = max(0.0, min(1.0, value)) * plot_w
            out.append(
                f'<g class="mark" tabindex="0" data-tip="{escape(tooltip)}">'
                f'<rect x="{left}" y="{y - 3}" width="{plot_w}" height="{BAR_H + 6}" class="hit"/>'
                f'<path d="{_bar_path(left, y, w, BAR_H)}" class="bar {key}"/>'
                f'<text x="{left + w + 6:.1f}" y="{y + BAR_H - 3}" class="value">'
                f"{escape(tip_label)}</text></g>"
            )
    out.append("</svg>")
    return "".join(out)


def _tile(label: str, value: str, note: str = "") -> str:
    note_html = f'<div class="note">{escape(note)}</div>' if note else ""
    return (
        f'<div class="tile"><div class="label">{escape(label)}</div>'
        f'<div class="tvalue">{escape(value)}</div>{note_html}</div>'
    )


def _compare_section(agent: dict | None, baseline: dict | None) -> str:
    metrics = [("Recall", "recall"), ("Precision", "precision"), ("F1", "f1")]
    series = []
    if agent:
        series.append(("agent", agent["label"], agent["summary"]))
    if baseline:
        series.append(("baseline", "ruff only", baseline["summary"]))
    if not series:
        return ""
    rows = []
    for name, key in metrics:
        rows.append(
            (
                name,
                [
                    (cls, s[key], _pct(s[key]), f"{label} | {name}: {_pct(s[key])}")
                    for cls, label, s in series
                ],
            )
        )
    legend = "".join(
        f'<span class="key"><span class="swatch {cls}"></span>{escape(label)}</span>'
        for cls, label, _ in series
    )
    table_rows = "".join(
        f"<tr><td>{escape(label)}</td><td>{_pct(s['recall'])}</td><td>{_pct(s['precision'])}</td>"
        f"<td>{s['f1']:.2f}</td><td>{s['found']}/{s['bugs']}</td><td>{s['comments']}</td></tr>"
        for _, label, s in series
    )
    return (
        '<figure class="card"><figcaption><h2>Agent vs lint-only baseline</h2>'
        f'<div class="legend">{legend}</div></figcaption>'
        f"{_hbar_chart(rows)}"
        "<details><summary>Table view</summary><table><thead><tr><th>Reviewer</th>"
        "<th>Recall</th><th>Precision</th><th>F1</th><th>Bugs found</th><th>Comments</th>"
        f"</tr></thead><tbody>{table_rows}</tbody></table></details></figure>"
    )


def _category_section(run: dict) -> str:
    totals: dict[str, list[int]] = {}
    for c in run["cases"]:
        for cat in c.get("categories", []):
            totals.setdefault(cat, [0, 0])[1] += 1
        for cat in c.get("found_categories", []):
            totals.setdefault(cat, [0, 0])[0] += 1
    if not totals:
        return ""
    ordered = sorted(totals.items(), key=lambda kv: (-kv[1][1], kv[0]))
    rows = [
        (
            cat,
            [("agent", f / t if t else 0, f"{f}/{t}", f"{cat}: {f} of {t} found ({_pct(f / t)})")],
        )
        for cat, (f, t) in ordered
    ]
    table_rows = "".join(
        f"<tr><td>{escape(cat)}</td><td>{f}/{t}</td><td>{_pct(f / t)}</td></tr>"
        for cat, (f, t) in ordered
    )
    title = "Recall by bug type" + (
        " (ruff only)" if run.get("label") == "lint-only" else f" ({run['label']})"
    )
    return (
        f'<figure class="card"><figcaption><h2>{escape(title)}</h2></figcaption>'
        f"{_hbar_chart(rows)}"
        "<details><summary>Table view</summary><table><thead><tr><th>Type</th><th>Found</th>"
        f"<th>Recall</th></tr></thead><tbody>{table_rows}</tbody></table></details></figure>"
    )


def _cases_section(run: dict) -> str:
    rows = []
    for c in run["cases"]:
        if c["bugs"] == 0:
            status = ("good", "clean, no comments") if c["comments"] == 0 else ("serious", "noisy")
        elif c["found"] == c["bugs"]:
            status = ("good", "found")
        else:
            status = ("critical", "missed")
        details = "; ".join(c.get("false_positives", []))[:300]
        rows.append(
            f"<tr><td>{escape(c['id'])}</td>"
            f"<td>{escape(', '.join(c.get('categories', [])) or '-')}</td>"
            f'<td><span class="dot {status[0]}"></span>{status[1]}</td>'
            f"<td class='num'>{c['comments']}</td><td class='num'>{len(c['false_positives'])}</td>"
            f"<td class='num'>{c.get('tool_calls', 0)}</td>"
            f'<td class="muted">{escape(details)}</td></tr>'
        )
    return (
        f'<section class="card"><h2>Cases ({escape(run["label"])})</h2>'
        '<div class="scroll"><table><thead><tr><th>Case</th><th>Bug type</th><th>Result</th>'
        "<th>Comments</th><th>False positives</th><th>Tool calls</th><th>False positive detail</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>"
    )


def _reviews_section(reviews: list[dict]) -> str:
    if not reviews:
        body = '<p class="muted">No PRs reviewed since the service started.</p>'
    else:
        rows = []
        for r in reversed(reviews):
            sev = r.get("by_severity", {})
            sev_txt = ", ".join(f"{n} {s}" for s, n in sev.items()) or "-"
            ok = r.get("status") == "posted"
            rows.append(
                f"<tr><td>{escape(r.get('time', ''))}</td><td>{escape(r.get('pr', ''))}</td>"
                f'<td><span class="dot {"good" if ok else "critical"}"></span>'
                f"{escape(r.get('status', ''))}</td>"
                f"<td class='num'>{r.get('comments', 0)}</td><td>{escape(sev_txt)}</td>"
                f"<td class='num'>{r.get('tool_calls', 0)}</td>"
                f"<td class='num'>{r.get('duration_s', 0):.1f}s</td></tr>"
            )
        body = (
            '<div class="scroll"><table><thead><tr><th>Time (UTC)</th><th>PR</th><th>Status</th>'
            "<th>Comments</th><th>Severity</th><th>Tool calls</th><th>Duration</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    return f'<section class="card"><h2>Recent reviews</h2>{body}</section>'


CSS = """
.viz-root{color-scheme:light;--surface-0:#f4f3f0;--surface-1:#fcfcfb;--line:#e4e3de;
--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#76756f;
--series-1:#2a78d6;--series-2:#eb6834;--good:#0ca30c;--serious:#ec835a;--critical:#d03b3b}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{
color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;--line:#383835;--text-primary:#f0efec;
--text-secondary:#c3c2b7;--text-muted:#9a998f;--series-1:#3987e5;--series-2:#d95926}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface-0:#121211;--surface-1:#1a1a19;
--line:#383835;--text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#9a998f;
--series-1:#3987e5;--series-2:#d95926}
*{box-sizing:border-box}body{margin:0}
.viz-root{background:var(--surface-0);color:var(--text-primary);min-height:100vh;
font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:24px 16px}
.wrap{max-width:1100px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:0 0 10px;font-weight:600}
.sub,.muted,.note{color:var(--text-secondary)}.note{font-size:12px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}
.tile,.card{background:var(--surface-1);border:1px solid var(--line);border-radius:10px;
padding:14px 16px}
.label{color:var(--text-secondary);font-size:12px}.tvalue{font-size:26px;font-weight:600;margin-top:2px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
.card{margin-bottom:12px}figure{margin:0 0 12px}
figcaption{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;
gap:8px}
.legend{display:flex;gap:14px;font-size:12px;color:var(--text-secondary)}
.key{display:inline-flex;align-items:center;gap:6px}
.swatch{width:10px;height:10px;border-radius:2px;display:inline-block}
.swatch.agent,.bar.agent{background:var(--series-1);fill:var(--series-1)}
.swatch.baseline,.bar.baseline{background:var(--series-2);fill:var(--series-2)}
.chart .grid{stroke:var(--line);stroke-width:1}.chart .tick{fill:var(--text-muted);font-size:11px}
.chart .rowlabel{fill:var(--text-secondary);font-size:12px}
.chart .value{fill:var(--text-primary);font-size:11px;font-variant-numeric:tabular-nums}
.chart .hit{fill:transparent}.chart .mark:hover .bar,.chart .mark:focus .bar{opacity:.8}
.chart .mark:focus{outline:none}
details{margin-top:8px;font-size:13px}summary{cursor:pointer;color:var(--text-secondary)}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
.scroll table{min-width:640px}.scroll td,.scroll th{white-space:nowrap}
.scroll td.muted{white-space:normal}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--text-secondary);font-weight:500}td.num{font-variant-numeric:tabular-nums}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.dot.good{background:var(--good)}.dot.serious{background:var(--serious)}
.dot.critical{background:var(--critical)}
#tip{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--text-primary);
border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12px;display:none;
box-shadow:0 2px 8px rgba(0,0,0,.12)}
"""

JS = """
const tip=document.getElementById('tip');
function show(el,x,y){const [a,b]=el.dataset.tip.split(': ');tip.textContent='';
const s=document.createElement('strong');s.textContent=b||a;tip.appendChild(s);
if(b){tip.appendChild(document.createTextNode('  '+a));}
tip.style.display='block';tip.style.left=(x+12)+'px';tip.style.top=(y+12)+'px';}
document.querySelectorAll('.mark').forEach(el=>{
el.addEventListener('pointermove',e=>show(el,e.clientX,e.clientY));
el.addEventListener('pointerleave',()=>tip.style.display='none');
el.addEventListener('focus',()=>{const r=el.getBoundingClientRect();show(el,r.left,r.top);});
el.addEventListener('blur',()=>tip.style.display='none');});
"""


def render_dashboard(runs: list[dict], reviews: list[dict] | None = None) -> str:
    agent, baseline = pick_runs(runs)
    main = agent or baseline
    parts = []
    if main:
        s = main["summary"]
        b = baseline["summary"] if baseline else None
        recall_note = f"ruff only: {_pct(b['recall'])}" if b and main is agent else ""
        parts.append(
            '<div class="tiles">'
            + _tile("Recall", _pct(s["recall"]), recall_note)
            + _tile("Precision", _pct(s["precision"]))
            + _tile("Bugs found", f"{s['found']}/{s['bugs']}")
            + _tile(
                "Clean PRs flagged",
                f"{s['clean_cases_with_comments']}/{s['clean_cases']}",
                "lower is better",
            )
            + _tile("Avg tool calls", f"{s['avg_tool_calls']:.1f}", "per PR")
            + "</div>"
        )
        parts.append(
            '<div class="grid2">'
            + _compare_section(agent, baseline)
            + _category_section(main)
            + "</div>"
        )
        parts.append(_cases_section(main))
    else:
        parts.append(
            '<section class="card"><p class="muted">No eval results yet. Run '
            "<code>python eval/run_eval.py</code>.</p></section>"
        )
    if reviews is not None:
        parts.append(_reviews_section(reviews))

    run_line = ""
    if main:
        run_line = f"Eval run: {escape(main['label'])} | {escape(main.get('created_at', ''))}"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>pr-review-agent dashboard</title><style>{CSS}</style></head>"
        '<body><div class="viz-root"><div class="wrap"><h1>pr-review-agent</h1>'
        f'<div class="sub">{run_line}</div>{"".join(parts)}</div></div>'
        f'<div id="tip" role="tooltip"></div><script>{JS}</script></body></html>'
    )
