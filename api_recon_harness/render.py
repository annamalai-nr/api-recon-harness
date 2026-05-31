"""Render: deterministic findings.md / policies.md / report.html.

The LLM supplies judgment (severity, prose, evidence refs) as structured
Finding/Policy objects. This module owns every formatting decision the parity
verifier checks — Major-first sort, canonical ids, `**Parameters**`-last field
order, the scope header, API Available Info, and the dependency banner — so
`verify_report_parity.py` passes by construction.
"""

import html as html_mod
from urllib.parse import urlsplit

from pydantic import BaseModel

from api_recon_harness.models import ApiAvailableInfo, Finding, ParameterSpec, Policy


class RenderContext(BaseModel):
    base_url: str
    endpoint: str
    title_desc: str
    params: list[ParameterSpec]
    run_auth_edges: bool
    downstream: str
    api_info: ApiAvailableInfo
    findings: list[Finding]          # already normalized (ids + sort)
    policies: list[Policy]
    ruled_out: list[str]
    dependency_params: list[str] = []

    @property
    def full_url(self) -> str:
        return f"{self.base_url}{self.endpoint}"

    @property
    def param_names(self) -> list[str]:
        return [p.name for p in self.params]

    @property
    def has_companions(self) -> bool:
        return any(p.pinned_companions for p in self.params)

    @property
    def is_multi(self) -> bool:
        return len(self.params) > 1


def _sev_rank(f: Finding) -> int:
    return 0 if f.severity == "Major" else 1


def normalize_findings(findings: list[Finding], param_order: list[str]) -> list[Finding]:
    """Sort Major-first per section and assign canonical ids (C1.. / name.N)."""
    cross = sorted([f for f in findings if f.scope == "cross_parameter"], key=_sev_rank)
    out: list[Finding] = []
    for i, f in enumerate(cross, 1):
        out.append(f.model_copy(update={"id": f"C{i}"}))

    for pname in param_order:
        group = sorted(
            [f for f in findings if f.scope == "per_parameter" and pname in f.parameters],
            key=_sev_rank,
        )
        for i, f in enumerate(group, 1):
            out.append(f.model_copy(update={"id": f"{pname}.{i}", "parameters": [pname]}))
    return out


# ─── Shared fragments ────────────────────────────────────────────────────

def companions_summary(params: list[ParameterSpec]) -> str:
    bits = []
    for p in params:
        if p.pinned_companions:
            pins = ", ".join(f"{c.name}={c.value}" for c in p.pinned_companions)
            bits.append(f"{p.name} ← {pins}")
    return "; ".join(bits) if bits else "none"


def scope_header_lines(ctx: RenderContext) -> list[str]:
    auth = "run" if ctx.run_auth_edges else "skipped (run_auth_edges=false)"
    return [
        f"Reconnaissance of GET {ctx.full_url} with parameters: {', '.join(ctx.param_names)}.",
        "Each parameter was probed independently (given its pinned companions, if any).",
        "Joint parameter behaviors were not tested.",
        f"Pinned companions: {companions_summary(ctx.params)}.",
        "Other methods, paths, and parameter combinations were not exercised.",
        f"Auth-edge probes: {auth}.",
        f"Downstream assumption: {ctx.downstream}.",
    ]


def _api_info_rows(ctx: RenderContext) -> list[tuple[str, str]]:
    info = ctx.api_info
    params_tested = "; ".join(f"{p.name} ({p.purpose})" if p.purpose else p.name
                              for p in ctx.params)
    rows = [
        ("Service", info.service),
        ("Endpoint", f"`GET {ctx.full_url}`"),
        ("Parameters tested", params_tested),
    ]
    if ctx.has_companions:
        rows.append(("Pinned companions", companions_summary(ctx.params)))
    rows += [
        ("Purpose", info.purpose),
        ("Auth", info.auth),
        ("Documentation", info.documentation),
        ("Documented response shape", info.documented_response_shape),
        ("Documentation gaps", info.documentation_gaps),
    ]
    return rows


def _policy_by_finding(ctx: RenderContext) -> dict[str, Policy]:
    return {p.finding_id: p for p in ctx.policies}


def _title_for(ctx: RenderContext, fid: str) -> str:
    for f in ctx.findings:
        if f.id == fid:
            return f.title
    return fid


# ─── findings.md ─────────────────────────────────────────────────────────

def _finding_block_md(f: Finding, heading_level: str, params_field: str) -> str:
    return (
        f"{heading_level} Finding {f.id}: {f.title}\n\n"
        f"**Severity**: {f.severity}\n\n"
        f"**Observation**: {f.observation}\n\n"
        f"**Mechanism**: {f.mechanism}\n\n"
        f"**Reliability**: {f.reliability}\n\n"
        f"**Parameters**: {params_field}\n"
    )


def render_findings_md(ctx: RenderContext) -> str:
    lines = ["\n".join(f"> {ln}" for ln in scope_header_lines(ctx)), ""]
    lines.append("## API Available Info\n")
    for label, val in _api_info_rows(ctx):
        lines.append(f"- **{label}**: {val}")
    lines.append("")

    cross = [f for f in ctx.findings if f.scope == "cross_parameter"]
    per = [f for f in ctx.findings if f.scope == "per_parameter"]

    if ctx.is_multi:
        if cross:
            lines.append("## Cross-parameter findings\n")
            for f in cross:
                n = len(f.parameters)
                lines.append(_finding_block_md(f, "###", f"{', '.join(f.parameters)} ({n}/{len(ctx.params)})"))
        lines.append("## Per-parameter findings\n")
        for p in ctx.params:
            purpose = f" ({p.purpose})" if p.purpose else ""
            lines.append(f"### Parameter `{p.name}`{purpose}\n")
            group = [f for f in per if p.name in f.parameters]
            if not group:
                lines.append("No parameter-specific findings beyond the cross-parameter set above.\n")
            for f in group:
                lines.append(_finding_block_md(f, "####", f"{p.name} only"))
    else:
        lines.append("## Findings\n")
        pname = ctx.param_names[0] if ctx.param_names else "parameter"
        for f in ctx.findings:
            lines.append(_finding_block_md(f, "###", f"{pname} only"))

    lines.append("## Ruled-out hypotheses\n")
    if ctx.ruled_out:
        for r in ctx.ruled_out:
            lines.append(f"- {r}")
    else:
        lines.append("- None recorded for this pass.")
    lines.append("")
    return "\n".join(lines)


# ─── policies.md ─────────────────────────────────────────────────────────

def render_policies_md(ctx: RenderContext) -> str:
    lines = ["\n".join(f"> {ln}" for ln in scope_header_lines(ctx)), ""]
    lines.append("## API Available Info\n")
    for label, val in _api_info_rows(ctx):
        lines.append(f"- **{label}**: {val}")
    lines.append("")

    for p in ctx.policies:
        title = _title_for(ctx, p.finding_id)
        lines.append(f"## Policy for Finding {p.finding_id}: {title}\n")
        lines.append("### Detection signal\n")
        lines.append(p.detection_signal + "\n")
        lines.append("### Policy statement\n")
        lines.append(p.policy_statement + "\n")
        lines.append("### Code implication\n")
        lines.append(p.code_implication + "\n")
    return "\n".join(lines)


# ─── report.html ─────────────────────────────────────────────────────────
#
# Aesthetic: a "forensic technical dossier" — warm paper light-mode, an
# editorial serif (Fraunces) for headings and IBM Plex Sans/Mono for body and
# instrument-style labels. Severity is encoded as a crimson (Major) / slate
# (Minor) rule + chip. The CSS is self-contained inline because this HTML is
# generated by a Python string renderer. Every parity-critical string (title,
# "Finding <id>:", "Severity: <level>", field labels, section markers, scope
# header, API-info labels, dependency banner) is preserved verbatim.

_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&'
    'family=IBM+Plex+Mono:wght@400;500;600&'
    'family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">'
)

_STYLE = """
:root{
  --paper:#FBFAF6; --panel:#FFFFFF; --ink:#1C1B18; --ink-soft:#5C574E;
  --rule:#E8E2D5; --rule-strong:#D7CFBE;
  --major:#A31B12; --major-soft:#FBEDEA; --major-line:#E7BDB6;
  --minor:#4F5A6B; --minor-soft:#EEF1F5; --minor-line:#CBD4E0;
  --accent:#1F6F5C; --accent-soft:#E7F1ED;
  --amber:#8A5A00; --amber-soft:#FBF1D6; --amber-line:#E6CF93;
  --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:'IBM Plex Sans',system-ui,-apple-system,Segoe UI,sans-serif;
  --display:'Fraunces','Iowan Old Style',Georgia,serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;color:var(--ink);background:var(--paper);font-family:var(--sans);
  font-size:16px;line-height:1.6;
  background-image:
    radial-gradient(120% 60% at 100% 0%, #FFFDF8 0%, rgba(255,253,248,0) 60%),
    repeating-linear-gradient(0deg, rgba(28,27,24,0.022) 0 1px, transparent 1px 28px);
}
.wrap{max-width:1000px;margin:0 auto;padding:clamp(1.5rem,4vw,3.5rem) clamp(1rem,4vw,2rem) 5rem}
a{color:var(--accent);text-underline-offset:2px}
.eyebrow{font-family:var(--mono);font-size:.72rem;letter-spacing:.18em;text-transform:uppercase;
  color:var(--ink-soft);display:flex;align-items:center;gap:.6rem;margin:0 0 .5rem}
.eyebrow::after{content:"";flex:1;height:1px;background:var(--rule-strong)}
.masthead{border-bottom:2px solid var(--ink);padding-bottom:1.4rem;margin-bottom:2rem}
.masthead h1{font-family:var(--display);font-optical-sizing:auto;font-weight:600;
  font-size:clamp(2rem,5.5vw,3.3rem);line-height:1.04;letter-spacing:-.015em;margin:.2rem 0 .6rem}
.masthead .meta{font-family:var(--mono);font-size:.8rem;color:var(--ink-soft);
  display:flex;flex-wrap:wrap;gap:.4rem 1.2rem}
h2{font-family:var(--display);font-weight:600;font-size:1.6rem;letter-spacing:-.01em;
  margin:2.6rem 0 1rem;padding-top:1.2rem;border-top:1px solid var(--rule)}
h3{font-family:var(--display);font-weight:500;font-size:1.18rem;margin:1.6rem 0 .6rem}
.scope{position:relative;background:var(--panel);border:1px solid var(--rule);
  border-radius:12px;padding:1.2rem 1.3rem 1.2rem 1.5rem;margin:1.5rem 0 0;
  box-shadow:0 1px 0 var(--rule),0 14px 30px -26px rgba(28,27,24,.5)}
.scope::before{content:"";position:absolute;left:0;top:14px;bottom:14px;width:3px;
  border-radius:3px;background:linear-gradient(var(--ink),var(--ink-soft))}
.scope p{margin:.2rem 0;font-size:.93rem;color:var(--ink)}
.scope p:first-of-type{font-weight:500}
.infogrid{list-style:none;padding:0;margin:1rem 0 0;display:grid;
  grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:.1rem 2rem}
.infogrid li{display:grid;grid-template-columns:1fr;gap:.05rem;padding:.55rem 0;
  border-bottom:1px solid var(--rule)}
.infogrid .k{font-family:var(--mono);font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-soft)}
.infogrid .v{font-size:.92rem}
.infogrid code{font-family:var(--mono);font-size:.82rem;background:var(--minor-soft);
  padding:.08rem .35rem;border-radius:5px}
.toolbar{display:flex;gap:.5rem;align-items:center;margin:.5rem 0 .25rem}
.btn{font-family:var(--mono);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;
  background:var(--panel);border:1px solid var(--rule-strong);color:var(--ink-soft);
  padding:.4rem .7rem;border-radius:7px;cursor:pointer;transition:.15s}
.btn:hover{border-color:var(--ink);color:var(--ink)}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:12px;margin:.85rem 0;
  overflow:hidden;box-shadow:0 14px 30px -28px rgba(28,27,24,.55);transition:.18s}
.card[open]{box-shadow:0 18px 40px -26px rgba(28,27,24,.55)}
.card.sev-major{border-left:3px solid var(--major)}
.card.sev-minor{border-left:3px solid var(--minor)}
.card>summary{list-style:none;cursor:pointer;display:flex;gap:.8rem;align-items:baseline;
  padding:1rem 1.2rem;outline:none}
.card>summary::-webkit-details-marker{display:none}
.card>summary::before{content:"›";font-family:var(--mono);color:var(--ink-soft);
  transform:rotate(0);transition:.2s;font-size:1.1rem;line-height:1}
.card[open]>summary::before{transform:rotate(90deg)}
.fid{font-family:var(--mono);font-size:.74rem;font-weight:600;letter-spacing:.04em;
  background:var(--ink);color:var(--paper);padding:.2rem .5rem;border-radius:6px;white-space:nowrap}
.ftitle{font-family:var(--display);font-weight:500;font-size:1.1rem;line-height:1.25;flex:1}
.chip{margin-left:auto;font-family:var(--mono);font-size:.66rem;font-weight:600;
  letter-spacing:.08em;text-transform:uppercase;padding:.28rem .55rem;border-radius:999px;
  white-space:nowrap;align-self:center}
.chip-major{background:var(--major-soft);color:var(--major);border:1px solid var(--major-line)}
.chip-minor{background:var(--minor-soft);color:var(--minor);border:1px solid var(--minor-line)}
.body{padding:0 1.2rem 1.1rem 1.2rem;border-top:1px solid var(--rule)}
.field{padding:.7rem 0;border-bottom:1px solid var(--rule)}
.field:last-child{border-bottom:none}
.field .k{font-family:var(--mono);font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-soft);margin-bottom:.2rem}
.field .v{font-size:.94rem}
.policy{margin:.9rem 0 .2rem;background:var(--accent-soft);border:1px solid #CDE3DB;
  border-radius:10px;padding:.9rem 1rem}
.policy .phead{font-family:var(--mono);font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;
  color:var(--accent);margin-bottom:.5rem;font-weight:600}
.policy .field{border-bottom:1px solid #D6E7E0}
.policy .field:last-child{border-bottom:none}
.banner{background:var(--amber-soft);border:1px solid var(--amber-line);border-left:3px solid var(--amber);
  border-radius:10px;padding:.95rem 1.1rem;margin:1rem 0}
.banner strong{font-family:var(--display);font-weight:600;color:var(--amber)}
.banner ul{margin:.5rem 0 0;padding-left:1.1rem}.banner li{margin:.2rem 0;font-size:.9rem}
.param-sec{scroll-margin-top:1rem}
.ruled{list-style:none;padding:0;margin:1rem 0 0}
.ruled li{position:relative;padding:.55rem 0 .55rem 1.6rem;border-bottom:1px solid var(--rule);font-size:.93rem}
.ruled li::before{content:"✕";position:absolute;left:0;color:var(--minor);font-family:var(--mono);font-size:.8rem}
footer{margin-top:3rem;padding-top:1.2rem;border-top:1px solid var(--rule);
  font-family:var(--mono);font-size:.72rem;color:var(--ink-soft)}
@media print{body{background:#fff}.card,.scope{box-shadow:none}.card{break-inside:avoid}}
"""

_EXPAND_JS = (
    "<script>function reconToggle(open){"
    "document.querySelectorAll('details.card').forEach(function(d){d.open=open})}"
    "</script>"
)


def _esc(s: str) -> str:
    return html_mod.escape(s, quote=False)


def _finding_card_html(f: Finding, params_field: str, expanded: bool,
                       policy: Policy | None) -> str:
    open_attr = " open" if expanded else ""
    chip = f"chip-{f.severity.lower()}"
    fields = (
        f'<div class="field"><div class="k">Observation</div>'
        f'<div class="v">{_esc(f.observation)}</div></div>'
        f'<div class="field"><div class="k">Mechanism</div>'
        f'<div class="v">{_esc(f.mechanism)}</div></div>'
        f'<div class="field"><div class="k">Reliability</div>'
        f'<div class="v">{_esc(f.reliability)}</div></div>'
        f'<div class="field"><div class="k">Parameters</div>'
        f'<div class="v">{_esc(params_field)}</div></div>'
    )
    policy_html = _policy_panel_html(f, policy) if policy else ""
    # "Severity: <level>" is kept as one contiguous text run (no tag between the
    # word and the level) so the parity verifier's severity regex matches.
    return (
        f'<details class="card sev-{f.severity.lower()}"{open_attr}>\n'
        f'  <summary><span class="fid">Finding {f.id}</span>'
        f'<span class="ftitle">{_esc(f.title)}</span>'
        f'<span class="chip {chip}">Severity: {f.severity}</span></summary>\n'
        f'  <div class="body">{fields}{policy_html}</div>\n'
        f"</details>\n"
    )


def _policy_panel_html(f: Finding, p: Policy) -> str:
    return (
        f'<div class="policy">'
        f'<div class="phead">Policy for Finding {p.finding_id}: {_esc(f.title)}</div>'
        f'<div class="field"><div class="k">Detection signal</div>'
        f'<div class="v">{_esc(p.detection_signal)}</div></div>'
        f'<div class="field"><div class="k">Policy statement</div>'
        f'<div class="v">{_esc(p.policy_statement)}</div></div>'
        f'<div class="field"><div class="k">Code implication</div>'
        f'<div class="v">{_esc(p.code_implication)}</div></div>'
        f"</div>"
    )


def _dependency_banner_html(ctx: RenderContext) -> str:
    causes = ["Your Tier-1 values may be too niche for this parameter's domain.",
              "An additional, undeclared parameter dependency may exist."]
    if ctx.has_companions:
        causes.insert(0, "Your pinned companion values may not be valid for the inputs you "
                         "are probing — try different canonical values for the companions and re-run.")
    items = "".join(f"<li>{_esc(c)}</li>" for c in causes)
    return (
        '<div class="banner"><strong>Suspected parameter dependency / low validity</strong>'
        f" for: {_esc(', '.join(ctx.dependency_params))}. Possible causes:<ul>{items}</ul></div>\n"
    )


def render_report_html(ctx: RenderContext) -> str:
    title = f"API Reconnaissance Report — {ctx.title_desc}"
    policy_by = _policy_by_finding(ctx)
    cross = [f for f in ctx.findings if f.scope == "cross_parameter"]
    per = [f for f in ctx.findings if f.scope == "per_parameter"]

    parts: list[str] = [
        "<!DOCTYPE html>", '<html lang="en">', "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_esc(title)}</title>",
        _FONTS,
        f"<style>{_STYLE}</style>",
        "</head>", "<body>", '<div class="wrap">',
        '<p class="eyebrow">API Reconnaissance · Findings &amp; Policies Dossier</p>',
        f'<header class="masthead"><h1>{_esc(title)}</h1>',
        f'<div class="meta"><span>{_esc(ctx.api_info.endpoint)}</span>'
        f'<span>Downstream: {_esc(ctx.downstream)}</span></div></header>',
        '<p class="eyebrow">Scope</p>',
        '<section class="scope">',
        "".join(f"<p>{_esc(ln)}</p>" for ln in scope_header_lines(ctx)),
        "</section>",
        '<h2>API Available Info</h2><ul class="infogrid">',
    ]
    for label, val in _api_info_rows(ctx):
        v = val if label == "Endpoint" else _esc(val)  # Endpoint already wraps `GET ...` in backticks
        if label == "Endpoint":
            v = f"<code>{_esc(val.strip('`'))}</code>"
        parts.append(f'<li><span class="k">{label}</span><span class="v">{v}</span></li>')
    parts.append("</ul>")

    def card(f: Finding, params_field: str, expanded: bool) -> str:
        return _finding_card_html(f, params_field, expanded, policy_by.get(f.id))

    if ctx.is_multi:
        if cross:
            parts.append('<section id="cross-parameter"><h2>Cross-parameter findings</h2>')
            parts.append('<div class="toolbar"><button class="btn" onclick="reconToggle(true)">'
                         'Expand all</button><button class="btn" onclick="reconToggle(false)">'
                         'Collapse all</button></div>')
            for f in cross:
                parts.append(card(f, f"{', '.join(f.parameters)} ({len(f.parameters)}/{len(ctx.params)})", True))
            parts.append("</section>")
        parts.append("<section><h2>Per-parameter findings</h2>")
        if ctx.dependency_params:
            parts.append(_dependency_banner_html(ctx))
        for p in ctx.params:
            purpose = f" — {_esc(p.purpose)}" if p.purpose else ""
            parts.append(f'<section class="param-sec" id="param-{_esc(p.name)}">'
                         f"<h3>Parameter {_esc(p.name)}{purpose}</h3>")
            group = [f for f in per if p.name in f.parameters]
            if not group:
                parts.append("<p>No parameter-specific findings beyond the cross-parameter set above.</p>")
            for f in group:
                parts.append(card(f, f"{p.name} only", False))
            parts.append("</section>")
        parts.append("</section>")
    else:
        parts.append("<section><h2>Findings</h2>")
        parts.append('<div class="toolbar"><button class="btn" onclick="reconToggle(true)">'
                     'Expand all</button><button class="btn" onclick="reconToggle(false)">'
                     'Collapse all</button></div>')
        if ctx.dependency_params:
            parts.append(_dependency_banner_html(ctx))
        pname = ctx.param_names[0] if ctx.param_names else "parameter"
        for f in ctx.findings:
            parts.append(card(f, f"{pname} only", True))
        parts.append("</section>")

    parts.append("<h2>Ruled-out hypotheses</h2>")
    parts.append('<ul class="ruled">')
    if ctx.ruled_out:
        for r in ctx.ruled_out:
            parts.append(f"<li>{_esc(r)}</li>")
    else:
        parts.append("<li>None recorded for this pass.</li>")
    parts.append("</ul>")
    parts.append("<footer>Generated by the API-recon harness · deterministic render · "
                 "report parity verified.</footer>")
    parts.append("</div>")
    parts.append(_EXPAND_JS)
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"
