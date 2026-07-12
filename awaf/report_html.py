from __future__ import annotations

import html
import json
from typing import Any

from awaf.db import AssessmentRecord
from awaf.findings import LifecycleResult, finding_signature
from awaf.reportcheck import READINESS_BANDS

# --- theme: copy shown under the overall score, keyed by band label ---------

_BAND_BLURB: dict[str, str] = {
    "Production Ready": "Fully ready. Variance within this band is noise.",
    "Near Ready": "Close to production. Address findings before deploying.",
    "Needs Work": "Notable gaps. Resolve High findings before production use.",
    "High Risk": "Significant control failures. Not suitable for production.",
    "Not Ready": "Critical gaps across multiple pillars. Major rework required.",
}

# (display_name, score_attr, conf_attr, tier, accent_hex)
# tier: 0 Foundation, 1 Cloud-WAF adapted, 2 Agent-native (1.5x weight).
# Kept in sync with cli._PILLAR_ROWS by test_pillars_in_sync_with_cli.
_PILLARS: list[tuple[str, str, str, int, str]] = [
    ("Foundation", "foundation_score", "foundation_confidence", 0, "#3a2154"),
    ("Op. Excellence", "op_excellence_score", "op_excellence_confidence", 1, "#6c6375"),
    ("Security", "security_score", "security_confidence", 1, "#6c6375"),
    ("Reliability", "reliability_score", "reliability_confidence", 1, "#6c6375"),
    ("Performance", "performance_score", "performance_confidence", 1, "#6c6375"),
    ("Cost Optim.", "cost_score", "cost_confidence", 1, "#6c6375"),
    ("Sustainability", "sustainability_score", "sustainability_confidence", 1, "#6c6375"),
    ("Reasoning Integ.", "reasoning_score", "reasoning_confidence", 2, "#ef7d24"),
    ("Controllability", "controllability_score", "controllability_confidence", 2, "#c4407e"),
    (
        "Context Integrity",
        "context_integrity_score",
        "context_integrity_confidence",
        2,
        "#0f8f86",
    ),
]

_TIER_LABELS: dict[int, str] = {
    0: "Tier 0 · Foundation",
    1: "Tier 1 · Cloud WAF Adapted",
    2: "Tier 2 · Agent-Native (1.5x weight)",
}

# severity bucket -> (left_border, tint_background, pill_text_color)
_SEVERITY_STYLE: dict[str, tuple[str, str, str]] = {
    "high": ("#c4407e", "#fbeef3", "#c4407e"),
    "medium": ("#ef7d24", "#fdf4ec", "#c9660f"),
    "low": ("#0f8f86", "#f4faf8", "#0b6b64"),
    "other": ("#6c6375", "#f4f2f6", "#6c6375"),
}

_SEVERITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2, "other": 3}

_FONT_LINK: str = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    "family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400;1,600&amp;"
    "family=Hanken+Grotesk:wght@400;500;600;700&amp;"
    'family=JetBrains+Mono:wght@400;500;700&amp;display=swap" rel="stylesheet">'
)

_CSS: str = """
:root{
  --font-display:'Playfair Display',Georgia,'Times New Roman',serif;
  --font-sans:'Hanken Grotesk',system-ui,-apple-system,'Segoe UI',sans-serif;
  --font-mono:'JetBrains Mono',ui-monospace,'SFMono-Regular',Consolas,monospace;
  --paper:#fdfbfe;--ink:#160f1c;--muted:#6c6375;--hair:#e7e1ea;
}
*{box-sizing:border-box}
body{margin:0;background:#ece7ef;color:var(--ink);font-family:var(--font-sans);
  -webkit-font-smoothing:antialiased;line-height:1.6}
.wrap{max-width:900px;margin:0 auto;padding:32px 20px 64px}
.eyebrow{font-family:var(--font-mono);font-size:12px;letter-spacing:.18em;
  text-transform:uppercase;color:var(--muted)}
h1,h2,h3{font-family:var(--font-display);font-weight:600;letter-spacing:-.02em;margin:0}
section.block{margin-top:34px}
section.block>h2{font-size:26px;color:var(--ink);margin-bottom:16px}
.muted-line{color:var(--muted);font-style:italic}
.masthead{position:relative;overflow:hidden;border-radius:20px;color:#fdfbfe;
  padding:48px 44px;background:linear-gradient(150deg,#271539 0%,#3a2154 55%,#5b3663 100%)}
.masthead .glow-a{position:absolute;top:-120px;right:-80px;width:420px;height:420px;
  border-radius:50%;background:radial-gradient(circle,rgba(239,125,36,.38),rgba(239,125,36,0) 68%)}
.masthead .glow-b{position:absolute;bottom:-140px;left:-70px;width:380px;height:380px;
  border-radius:50%;background:radial-gradient(circle,rgba(15,143,134,.26),rgba(15,143,134,0) 66%)}
.masthead .inner{position:relative}
.masthead .eyebrow{color:#f0a672}
.masthead h1{font-size:46px;color:#fdfbfe;margin:14px 0 6px}
.masthead .meta{font-family:var(--font-mono);font-size:13px;letter-spacing:.06em;
  color:rgba(253,251,254,.7)}
.scoreline{display:flex;align-items:baseline;gap:18px;margin-top:26px;flex-wrap:wrap}
.scoreline .num{font-family:var(--font-display);font-size:74px;line-height:1;color:#fdfbfe}
.pill{display:inline-block;font-family:var(--font-mono);font-size:13px;letter-spacing:.08em;
  text-transform:uppercase;padding:6px 14px;border-radius:999px;background:rgba(253,251,254,.14);
  color:#fdfbfe;border:1px solid rgba(253,251,254,.28)}
.scoreline .blurb{color:rgba(253,251,254,.8);font-size:16px;max-width:420px}
.bands{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
.bandcell{flex:1;min-width:120px;border:1px solid var(--hair);border-radius:12px;
  background:#fff;padding:12px 14px}
.bandcell.here{border-color:#c4407e;box-shadow:0 0 0 2px rgba(196,64,126,.16)}
.bandcell .lab{font-family:var(--font-display);font-weight:600;font-size:16px}
.bandcell .rng{font-family:var(--font-mono);font-size:11px;letter-spacing:.06em;color:var(--muted)}
.action{border:1px solid var(--hair);border-left-width:5px;border-radius:12px;
  padding:16px 20px;margin-top:12px}
.action .top{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px}
.sev{font-family:var(--font-mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;
  font-weight:700;padding:3px 10px;border-radius:6px;background:#fff}
.tag{font-family:var(--font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  padding:2px 8px;border-radius:5px;border:1px solid currentColor}
.action .pillar{font-family:var(--font-mono);font-size:12px;letter-spacing:.08em;
  text-transform:uppercase;font-weight:700}
.action .detail{color:var(--ink);font-size:16px}
.loc{font-family:var(--font-mono);font-size:12px;color:var(--muted);background:#f4f2f6;
  padding:2px 8px;border-radius:6px;margin-top:8px;display:inline-block}
.tier{margin-top:22px}
.tier>.eyebrow{margin-bottom:10px;display:block}
.scorecard .row{display:flex;align-items:center;gap:16px;padding:12px 0;
  border-bottom:1px solid var(--hair)}
.scorecard .row:last-child{border-bottom:none}
.scorecard .pname{flex:0 0 190px;font-family:var(--font-display);font-weight:600;font-size:18px}
.scorecard .barwrap{flex:1;height:10px;border-radius:999px;background:#efeaf2;overflow:hidden}
.scorecard .bar{height:100%;border-radius:999px}
.scorecard .val{flex:0 0 120px;text-align:right;font-family:var(--font-mono);font-size:14px}
.scorecard .val .s{font-size:18px;font-weight:700;color:var(--ink)}
.scorecard .val .c{color:var(--muted)}
.foundfail{margin-top:14px;border-left:5px solid #c4407e;background:#fbeef3;border-radius:12px;
  padding:14px 18px;color:#8a1f4b;font-size:15px}
.rec{border:1px solid var(--hair);border-radius:12px;padding:14px 18px;margin-top:10px}
.rec .pillar{font-family:var(--font-mono);font-size:12px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--muted);font-weight:700;margin-bottom:4px}
.twocol{display:grid;grid-template-columns:1fr 1fr;gap:20px}
ul.plain{margin:0;padding-left:20px}
ul.plain li{margin:6px 0}
.foot{margin-top:44px;padding-top:20px;border-top:1px solid var(--hair);display:flex;
  justify-content:space-between;flex-wrap:wrap;gap:12px;font-family:var(--font-mono);
  font-size:12px;letter-spacing:.06em;color:var(--muted)}
@media (max-width:640px){
  .scorecard .pname{flex-basis:120px;font-size:15px}
  .twocol{grid-template-columns:1fr}
  .masthead h1{font-size:34px}
  .scoreline .num{font-size:56px}
}
@media print{
  body{background:#fff}
  .card,.action,.rec,.bandcell{box-shadow:none}
  .masthead{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""


def _esc(value: object) -> str:
    """HTML-escape any value (including quotes) for safe insertion into markup."""
    return html.escape(str(value), quote=True)


def _load_list(blob: str) -> list[Any]:
    """Parse a JSON string into a list; degrade to [] on any error or non-list."""
    try:
        data = json.loads(blob)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def _band_for(score: float) -> tuple[str, str]:
    """Return (band_label, one_line_blurb) for a numeric overall score."""
    for lower, label in READINESS_BANDS:
        if score >= lower:
            return label, _BAND_BLURB.get(label, "")
    label = READINESS_BANDS[-1][1]
    return label, _BAND_BLURB.get(label, "")


def _severity_bucket(severity: str) -> str:
    """Map a free-text severity to a style bucket: high|medium|low|other."""
    s = severity.strip().lower()
    if s in ("high", "critical"):
        return "high"
    if s in ("medium", "moderate", "med"):
        return "medium"
    if s == "low":
        return "low"
    return "other"


def _text_of(item: Any) -> str:
    """Best-effort human text for an evidence or gap item that may be a str or dict."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("detail", "text", "description", "gap", "name"):
            v = item.get(key)
            if isinstance(v, str) and v:
                return v
        return json.dumps(item, sort_keys=True)
    return str(item)


def _render_masthead(rec: AssessmentRecord, project_name: str) -> str:
    name = _esc(rec.project_name or project_name)
    date = _esc(rec.created_at.strftime("%Y-%m-%d"))
    provider_model = _esc(f"{rec.provider} / {rec.model}")
    score = int(rec.overall_score)
    band_label, band_blurb = _band_for(rec.overall_score)
    return (
        '<header class="masthead">'
        '<div class="glow-a"></div><div class="glow-b"></div>'
        '<div class="inner">'
        '<div class="eyebrow">AWAF v1.4 · Assessment</div>'
        f"<h1>{name}</h1>"
        f'<div class="meta">{date} · {provider_model}</div>'
        '<div class="scoreline">'
        f'<div class="num">{score}</div>'
        f'<div class="pill">{_esc(band_label)}</div>'
        f'<div class="blurb">{_esc(band_blurb)}</div>'
        "</div></div></header>"
    )


def _render_bands(score: float) -> str:
    label_now, _ = _band_for(score)
    bands = list(READINESS_BANDS)  # highest-first: [(85, 'Production Ready'), ...]
    cells: list[str] = []
    for i, (lower, label) in enumerate(bands):
        upper = 100 if i == 0 else bands[i - 1][0] - 1
        here = " here" if label == label_now else ""
        cells.append(
            f'<div class="bandcell{here}">'
            f'<div class="lab">{_esc(label)}</div>'
            f'<div class="rng">{lower}–{upper}</div>'
            "</div>"
        )
    return (
        '<section class="block"><div class="eyebrow">Readiness bands</div>'
        f'<div class="bands">{"".join(cells)}</div></section>'
    )


def _scorecard_row(name: str, score: object, conf: object, accent: str) -> str:
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        pct = max(0, min(100, int(score)))
        conf_txt = _esc(conf) if isinstance(conf, str) and conf else "unrated"
        val = f'<span class="s">{int(score)}</span><span class="c"> · {conf_txt}</span>'
        bar = f'<div class="bar" style="width:{pct}%;background:{accent}"></div>'
    else:
        val = '<span class="c">not scored</span>'
        bar = ""
    return (
        '<div class="row">'
        f'<div class="pname">{_esc(name)}</div>'
        f'<div class="barwrap">{bar}</div>'
        f'<div class="val">{val}</div>'
        "</div>"
    )


def _render_scorecard(rec: AssessmentRecord) -> str:
    parts: list[str] = ['<section class="block"><h2>Pillar scores</h2>']
    found = getattr(rec, "foundation_score", None)
    if isinstance(found, (int, float)) and not isinstance(found, bool) and found < 40:
        parts.append(
            '<div class="foundfail">Foundation scored below 40: the Foundation gate '
            "failed, so the other pillars are advisory only until it is resolved.</div>"
        )
    for tier in (0, 1, 2):
        rows = [
            _scorecard_row(name, getattr(rec, s_attr, None), getattr(rec, c_attr, None), accent)
            for name, s_attr, c_attr, ptier, accent in _PILLARS
            if ptier == tier
        ]
        parts.append(
            f'<div class="tier"><span class="eyebrow">{_esc(_TIER_LABELS[tier])}</span>'
            f'<div class="scorecard">{"".join(rows)}</div></div>'
        )
    parts.append("</section>")
    return "".join(parts)


def _render_footer(rec: AssessmentRecord) -> str:
    tin = f"{rec.total_input_tokens:,}"
    tout = f"{rec.total_output_tokens:,}"
    cost = f"${rec.estimated_cost_usd:.4f}"
    return (
        '<footer class="foot">'
        f"<span>{_esc(tin)} in / {_esc(tout)} out · {_esc(cost)} (subject rate)</span>"
        "<span>Generated by awaf · awaf.ai</span>"
        "</footer>"
    )


def _render_action_items(findings: list[Any], life: LifecycleResult | None) -> str:
    header = '<section class="block"><h2>Action items</h2>'
    dicts = [f for f in findings if isinstance(f, dict)]
    if not dicts:
        return header + '<div class="muted-line">No action items recorded.</div></section>'

    def _key(f: dict[str, Any]) -> int:
        return _SEVERITY_ORDER[_severity_bucket(str(f.get("severity") or ""))]

    rows: list[str] = []
    for f in sorted(dicts, key=_key):
        bucket = _severity_bucket(str(f.get("severity") or ""))
        border, tint, sev_col = _SEVERITY_STYLE[bucket]
        severity_txt = _esc(f.get("severity") or bucket)
        pillar = _esc(f.get("pillar") or "")
        detail = _esc(f.get("detail") or f.get("title") or "")
        loc = ""
        file_ = f.get("file")
        if isinstance(file_, str) and file_.strip():
            line = f.get("line")
            suffix = (
                f":{line}"
                if isinstance(line, int) and not isinstance(line, bool) and line > 0
                else ""
            )
            loc = f'<div class="loc">{_esc(file_ + suffix)}</div>'
        tag = ""
        if life is not None:
            status = life.statuses.get(finding_signature(f), "")
            if status:
                tag = f'<span class="tag" style="color:{sev_col}">{_esc(status)}</span>'
        rows.append(
            f'<div class="action" style="border-left-color:{border};background:{tint}">'
            '<div class="top">'
            f'<span class="sev" style="color:{sev_col}">{severity_txt}</span>'
            f'<span class="pillar" style="color:{border}">{pillar}</span>'
            f"{tag}</div>"
            f'<div class="detail">{detail}</div>'
            f"{loc}</div>"
        )
    return header + "".join(rows) + "</section>"


def _render_recommendations(recs: list[Any]) -> str:
    header = '<section class="block"><h2>Recommendations</h2>'
    dicts = [r for r in recs if isinstance(r, dict)]
    if not dicts:
        return header + '<div class="muted-line">No recommendations recorded.</div></section>'
    rows = [
        f'<div class="rec"><div class="pillar">{_esc(r.get("pillar") or "")}</div>'
        f'<div class="detail">{_esc(r.get("detail") or "")}</div></div>'
        for r in dicts
    ]
    return header + "".join(rows) + "</section>"


def _list_items(items: list[Any]) -> str:
    vals = [_esc(_text_of(x)) for x in items if _text_of(x)]
    if not vals:
        return '<div class="muted-line">None recorded.</div>'
    lis = "".join(f"<li>{v}</li>" for v in vals)
    return f'<ul class="plain">{lis}</ul>'


def _render_evidence(evidence: list[Any], gaps: list[Any]) -> str:
    return (
        '<section class="block"><h2>Evidence</h2><div class="twocol">'
        f'<div><div class="eyebrow">Reviewed</div>{_list_items(evidence)}</div>'
        f'<div><div class="eyebrow">Gaps</div>{_list_items(gaps)}</div>'
        "</div></section>"
    )


def _render_improvements(items: list[Any]) -> str:
    return (
        f'<section class="block"><h2>To improve this assessment</h2>{_list_items(items)}</section>'
    )


def render_html(
    rec: AssessmentRecord,
    life: LifecycleResult | None,
    *,
    project_name: str,
) -> str:
    """Return a complete self-contained HTML document for one assessment."""
    title_name = _esc(rec.project_name or project_name)
    body = "".join(
        [
            _render_masthead(rec, project_name),
            _render_bands(rec.overall_score),
            _render_action_items(_load_list(rec.findings), life),
            _render_scorecard(rec),
            _render_recommendations(_load_list(rec.recommendations)),
            _render_evidence(_load_list(rec.evidence_reviewed), _load_list(rec.evidence_gaps)),
            _render_improvements(_load_list(rec.improve_suggestions)),
            _render_footer(rec),
        ]
    )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>AWAF · {title_name}</title>\n"
        f"{_FONT_LINK}\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        f'<div class="wrap">\n{body}\n</div>\n'
        "</body>\n</html>\n"
    )
