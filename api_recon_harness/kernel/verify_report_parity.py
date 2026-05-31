#!/usr/bin/env python3
"""
verify_report_parity.py — Check that report.html faithfully reproduces
content from findings.md and policies.md.

Checks performed:
  - Professional title and heading
  - Finding count parity (Markdown vs HTML)
  - Policy count parity
  - Severity label parity and Major-before-Minor sort order
  - Per-section severity sort (per-param and cross-param groups in HTML)
  - Finding titles and substantive content (Observation, Mechanism, Reliability)
  - Policy titles and substantive content
  - API Available Info fields (Service, Endpoint, Purpose, Auth, etc.)
  - "Parameters tested" label
  - Scope header (reconnaissance of GET)
  - Auth-edge status mention
  - Ruled-out hypotheses mention
  - Endpoint URL / domain presence
  - Docs reference or "no public documentation" note
  - Reliability section count
  - Per-parameter section presence and finding counts (multi-param)
  - Cross-parameter section presence (multi-param)
  - Pinned-companion documentation (when companions are configured)
  - Dependency banner phrasing (pinned-companion bullet when applicable)

USAGE
  python scripts/verify_report_parity.py \\
    --findings outputs/api_recon/search/findings.md \\
    --policies outputs/api_recon/search/policies.md \\
    --html outputs/api_recon/search/report.html \\
    [--config outputs/api_recon/search/probe_config.json]

EXIT CODES
  0  all checks pass
  1  one or more checks failed
"""

import argparse
import html as html_mod
import json
import re
import sys


def read_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def normalize_text(text: str) -> str:
    """Strip Markdown/HTML markup and collapse whitespace for fuzzy comparison.

    Designed so Markdown and the corresponding rendered HTML produce identical
    normalized strings for the same substantive content.
    """
    t = html_mod.unescape(text)
    t = re.sub(r"```[a-zA-Z0-9_+-]*", "", t)
    for tag in ("code", "strong", "em", "b", "i", "span"):
        t = re.sub(rf"</?{tag}(?:\s[^>]*)?>", "", t, flags=re.IGNORECASE)
    t = re.sub(r"<[a-zA-Z!/][^>]*>", " ", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^[-*]\s+", " ", t, flags=re.MULTILINE)
    t = re.sub(r"^#+\s+", " ", t, flags=re.MULTILINE)
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def extract_finding_titles(md: str) -> list[str]:
    """Match ### Finding N: and #### Finding prefix.N: formats."""
    return re.findall(
        r"^#{3,4}\s+Finding\s+(?:C?\d+|[\w.:-]+\.\d+):\s*(.+)$", md, re.MULTILINE
    )


def extract_policy_titles(md: str) -> list[str]:
    return re.findall(
        r"^##\s+Policy\s+for\s+Finding\s+(?:C?\d+|[\w.:-]+\.\d+):\s*(.+)$",
        md, re.MULTILINE,
    )


_FINDING_FIELDS = ("Severity", "Observation", "Mechanism", "Reliability")
_EXTRA_FINDING_FIELDS = ("Parameters",)


def extract_finding_sections(md: str) -> list[dict]:
    """Extract field content per finding."""
    all_fields = _FINDING_FIELDS + _EXTRA_FINDING_FIELDS
    findings = []
    blocks = re.split(r"^#{3,4}\s+Finding\s+(?:C?\d+|[\w.:-]+\.\d+):", md, flags=re.MULTILINE)
    for block in blocks[1:]:
        entry = {}
        for idx, field in enumerate(all_fields):
            later = "|".join(
                rf"\*\*{all_fields[j]}\*\*:"
                for j in range(idx + 1, len(all_fields))
            )
            if later:
                end_pat = rf"(?=\n(?:{later})|\n#{{2,4}}\s|\n---|\Z)"
            else:
                end_pat = r"(?=\n#{2,4}\s|\n---|\Z)"
            match = re.search(
                rf"\*\*{field}\*\*:\s*(.*?){end_pat}",
                block,
                re.DOTALL,
            )
            if match:
                entry[field] = match.group(1).strip()
        findings.append(entry)
    return findings


def extract_policy_sections(md: str) -> list[dict]:
    policies = []
    blocks = re.split(
        r"^##\s+Policy\s+for\s+Finding\s+(?:C?\d+|[\w.:-]+\.\d+):",
        md, flags=re.MULTILINE,
    )
    for block in blocks[1:]:
        entry = {}
        for field in ("Detection signal", "Policy statement", "Code implication"):
            match = re.search(
                rf"###\s+{field}\s*\n(.*?)(?=\n###|\n##|\n---|\Z)",
                block,
                re.DOTALL,
            )
            if match:
                entry[field] = match.group(1).strip()
        policies.append(entry)
    return policies


def count_pattern(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text, re.MULTILINE | re.IGNORECASE))


def content_present(needle_text: str, html: str, min_words: int = 4) -> bool:
    """Check that substantive phrases from needle_text appear in the HTML.

    Uses a sliding window of 5-word phrases with stride 1, requiring 95%
    match rate.
    """
    norm_needle = normalize_text(needle_text)
    norm_html = normalize_text(html)

    words = norm_needle.split()
    if len(words) < min_words:
        return norm_needle in norm_html

    window = max(min_words, 5)
    phrases = [
        " ".join(words[i : i + window])
        for i in range(len(words) - window + 1)
    ]

    if not phrases:
        return norm_needle in norm_html

    hits = sum(1 for p in phrases if p in norm_html)
    return hits / len(phrases) >= 0.95


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return condition


def check_severity_sort_within(severity_labels: list[str], section_name: str) -> bool:
    """Verify Major-before-Minor ordering within a sequence of severity labels."""
    seen_minor = False
    for label in severity_labels:
        if label == "Minor":
            seen_minor = True
        elif label == "Major" and seen_minor:
            return check(f"Severity sort in {section_name}", False,
                         "Major found after Minor")
    return check(f"Severity sort in {section_name}", True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify Markdown/HTML report parity"
    )
    parser.add_argument("--findings", required=True, help="Path to findings.md")
    parser.add_argument("--policies", required=True, help="Path to policies.md")
    parser.add_argument("--html", required=True, help="Path to report.html")
    parser.add_argument("--config", default=None,
                        help="Path to probe_config.json (enables per-parameter checks)")
    args = parser.parse_args()

    findings_md = read_file(args.findings)
    policies_md = read_file(args.policies)
    html = read_file(args.html)
    norm_html_full = normalize_text(html)

    cfg_params = []
    has_pinned_companions = False
    if args.config:
        with open(args.config) as f:
            cfg = json.load(f)
        if "parameters" in cfg:
            cfg_params = cfg["parameters"]
        elif "param_name" in cfg:
            cfg_params = [{"name": cfg["param_name"]}]
        # Check whether any parameter declares pinned companions
        for p in cfg_params:
            if p.get("pinned_companions"):
                has_pinned_companions = True
                break

    is_multi_param = len(cfg_params) > 1

    print("Report parity verification")
    print("=" * 50)

    all_pass = True

    # ── Report title ────────────────────────────────────────────────────
    has_title = bool(re.search(
        r"<title>\s*API Reconnaissance Report", html, re.IGNORECASE
    ))
    all_pass &= check("Professional <title> tag", has_title)
    has_h1 = bool(re.search(
        r"API Reconnaissance Report", html, re.IGNORECASE
    ))
    all_pass &= check("Professional heading in HTML", has_h1)

    # ── Finding counts ──────────────────────────────────────────────────
    md_findings = extract_finding_titles(findings_md)
    html_finding_re = r"Finding\s+(?:C?\d+|[\w.:-]+\.\d+):"
    html_finding_count = count_pattern(html, html_finding_re)
    all_pass &= check(
        "Finding count",
        html_finding_count >= len(md_findings),
        f"Markdown={len(md_findings)}, HTML={html_finding_count}",
    )

    # ── Policy counts ───────────────────────────────────────────────────
    md_policies = extract_policy_titles(policies_md)
    html_policy_re = r"Policy\s+for\s+Finding\s+(?:C?\d+|[\w.:-]+\.\d+):"
    html_policy_count = count_pattern(html, html_policy_re)
    all_pass &= check(
        "Policy count",
        html_policy_count >= len(md_policies),
        f"Markdown={len(md_policies)}, HTML={html_policy_count}",
    )

    # ── Severity labels ─────────────────────────────────────────────────
    md_major = count_pattern(findings_md, r"\*\*Severity\*\*:\s*Major")
    md_minor = count_pattern(findings_md, r"\*\*Severity\*\*:\s*Minor")
    all_pass &= check(
        "Severity labels in Markdown",
        md_major + md_minor == len(md_findings),
        f"Major={md_major}, Minor={md_minor}, Findings={len(md_findings)}",
    )
    html_major = count_pattern(html, r"Severity.*Major")
    html_minor = count_pattern(html, r"Severity.*Minor")
    all_pass &= check(
        "Severity labels in HTML",
        html_major + html_minor >= md_major + md_minor,
        f"Major={html_major}, Minor={html_minor}",
    )

    # ── Per-section severity sort ───────────────────────────────────────
    if is_multi_param:
        # Cross-parameter section
        cross_match = re.search(
            r"## Cross-parameter findings\s*\n(.*?)(?=\n## Per-parameter|\n## Ruled|\Z)",
            findings_md, re.DOTALL,
        )
        if cross_match:
            cross_sev = re.findall(r"\*\*Severity\*\*:\s*(Major|Minor)", cross_match.group(1))
            all_pass &= check_severity_sort_within(cross_sev, "cross-parameter section")

        # Each per-parameter section
        per_param_blocks = re.split(r"^### Parameter `([^`]+)`", findings_md, flags=re.MULTILINE)
        for i in range(1, len(per_param_blocks), 2):
            pname = per_param_blocks[i]
            block = per_param_blocks[i + 1] if i + 1 < len(per_param_blocks) else ""
            sev = re.findall(r"\*\*Severity\*\*:\s*(Major|Minor)", block)
            all_pass &= check_severity_sort_within(sev, f"parameter '{pname}'")
    else:
        # Single-parameter: flat list
        all_sev = re.findall(r"\*\*Severity\*\*:\s*(Major|Minor)", findings_md)
        all_pass &= check_severity_sort_within(all_sev, "findings")

    # ── Severity sort in HTML ──────────────────────────────────────────
    if is_multi_param:
        cross_html = re.search(
            r"(?i)(cross.?param.*?)(?=<[^>]*id\s*=\s*[\"']param-|$)",
            html, re.DOTALL,
        )
        if cross_html:
            cross_sev_html = re.findall(
                r"Severity[^<]*?(Major|Minor)", cross_html.group(1), re.IGNORECASE
            )
            all_pass &= check_severity_sort_within(
                [s.capitalize() for s in cross_sev_html],
                "HTML cross-parameter section"
            )
        for p in cfg_params:
            pname = p["name"]
            pat = rf'id\s*=\s*["\']param-{re.escape(pname)}["\']'
            anchor = re.search(pat, html, re.IGNORECASE)
            if anchor:
                rest = html[anchor.start():]
                next_param = re.search(
                    r'id\s*=\s*["\']param-(?!' + re.escape(pname) + r')[^"\']+["\']',
                    rest[1:], re.IGNORECASE,
                )
                section = rest[:next_param.start() + 1] if next_param else rest
                param_sev = re.findall(
                    r"Severity[^<]*?(Major|Minor)", section, re.IGNORECASE
                )
                all_pass &= check_severity_sort_within(
                    [s.capitalize() for s in param_sev],
                    f"HTML parameter '{pname}'"
                )
    else:
        html_severity_labels = re.findall(
            r"Severity[^<]*?(Major|Minor)", html, re.IGNORECASE
        )
        all_pass &= check_severity_sort_within(
            [s.capitalize() for s in html_severity_labels],
            "HTML findings"
        )

    # ── Finding titles in HTML ──────────────────────────────────────────
    for title in md_findings:
        clean = title.strip()
        present = normalize_text(clean) in norm_html_full
        all_pass &= check(f"Finding title in HTML: {clean[:60]}", present)

    # ── Finding substantive content in HTML ─────────────────────────────
    finding_sections = extract_finding_sections(findings_md)
    for i, entry in enumerate(finding_sections, 1):
        for field, text in entry.items():
            if field == "Severity":
                ok = text.lower() in html.lower()
                all_pass &= check(
                    f"Finding {i} Severity '{text}' in HTML", ok)
                continue
            if field == "Parameters":
                ok = normalize_text(text) in norm_html_full
                all_pass &= check(
                    f"Finding {i} Parameters in HTML", ok,
                    f"'{text[:40]}'" if not ok else "")
                continue
            ok = content_present(text, html)
            all_pass &= check(
                f"Finding {i} {field} content in HTML",
                ok,
                f"{len(text)} chars" if not ok else "",
            )

    # ── Policy titles in HTML ───────────────────────────────────────────
    for title in md_policies:
        clean = title.strip()
        present = normalize_text(clean) in norm_html_full
        all_pass &= check(f"Policy title in HTML: {clean[:60]}", present)

    # ── Policy substantive content in HTML ──────────────────────────────
    policy_sections = extract_policy_sections(policies_md)
    for i, entry in enumerate(policy_sections, 1):
        for field, text in entry.items():
            ok = content_present(text, html)
            all_pass &= check(
                f"Policy {i} {field} content in HTML",
                ok,
                f"{len(text)} chars" if not ok else "",
            )

    # ── API Available Info fields ───────────────────────────────────────
    api_info_labels = [
        "Service",
        "Endpoint",
        "Purpose",
        "Auth",
        "Documentation",
        "Documented response shape",
        "Documentation gaps",
    ]
    has_param_label_md = (
        "primary parameter tested" in findings_md.lower()
        or "parameters tested" in findings_md.lower()
    )
    all_pass &= check("API Available Info — param label in Markdown", has_param_label_md)
    has_param_label_html = (
        "primary parameter tested" in html.lower()
        or "parameters tested" in html.lower()
    )
    all_pass &= check("API Available Info — param label in HTML", has_param_label_html)

    for label in api_info_labels:
        all_pass &= check(
            f"API Available Info — '{label}' in Markdown",
            label.lower() in findings_md.lower(),
        )
        all_pass &= check(
            f"API Available Info — '{label}' in HTML",
            label.lower() in html.lower(),
        )

    # ── Scope header ────────────────────────────────────────────────────
    all_pass &= check(
        "Scope header in Markdown",
        "reconnaissance of get" in findings_md.lower()
        or "other methods" in findings_md.lower(),
    )
    all_pass &= check(
        "Scope header in HTML",
        "reconnaissance of get" in html.lower()
        or "other methods" in html.lower(),
    )

    # ── Auth-edge status ────────────────────────────────────────────────
    auth_in_md = (
        "auth-edge probes" in findings_md.lower()
        or "auth-edge probes were skipped" in findings_md.lower()
        or "run_auth_edges" in findings_md.lower()
    )
    all_pass &= check("Auth-edge status in Markdown", auth_in_md)
    auth_in_html = (
        "auth-edge probes" in html.lower()
        or "auth-edge probes were skipped" in html.lower()
        or "run_auth_edges" in html.lower()
    )
    all_pass &= check("Auth-edge status in HTML", auth_in_html)

    # ── Ruled-out hypotheses ────────────────────────────────────────────
    all_pass &= check(
        "Ruled-out hypotheses in Markdown",
        "ruled-out hypotheses" in findings_md.lower()
        or "ruled out" in findings_md.lower(),
    )
    all_pass &= check(
        "Ruled-out hypotheses in HTML",
        "ruled-out hypotheses" in html.lower()
        or "ruled out" in html.lower(),
    )

    # ── Endpoint URL in both ────────────────────────────────────────────
    url_match = re.search(r"https?://\S+", findings_md)
    if url_match:
        endpoint_url = url_match.group(0).rstrip("`>).,;")
        domain = re.search(r"https?://([^/\s?]+)", endpoint_url)
        if domain:
            all_pass &= check(
                "Endpoint domain in HTML",
                domain.group(1).lower() in html.lower(),
                domain.group(1),
            )

    # ── Docs link or "No public documentation" ──────────────────────────
    def _has_docs_url(text: str) -> bool:
        # Match any URL after **Documentation**: label, or any URL with "doc" in path
        return bool(
            re.search(r"\*\*Documentation\*\*:.*https?://\S+", text, re.IGNORECASE)
            or re.search(r"https?://\S+doc", text, re.IGNORECASE)
        )

    has_docs_link = _has_docs_url(findings_md)
    has_no_docs = "no public documentation found" in findings_md.lower()
    all_pass &= check(
        "Docs reference in Markdown",
        has_docs_link or has_no_docs,
        "docs link found"
        if has_docs_link
        else ("no-docs note found" if has_no_docs else "neither found"),
    )
    has_docs_link_html = _has_docs_url(html)
    has_no_docs_html = "no public documentation found" in html.lower()
    all_pass &= check(
        "Docs reference in HTML",
        has_docs_link_html or has_no_docs_html,
        "docs link found"
        if has_docs_link_html
        else ("no-docs note found" if has_no_docs_html else "neither found"),
    )

    # ── Reliability sections ────────────────────────────────────────────
    md_reliability_count = count_pattern(findings_md, r"\*\*Reliability\*\*:")
    html_reliability_count = count_pattern(html, r"Reliability")
    all_pass &= check(
        "Reliability sections",
        html_reliability_count >= md_reliability_count,
        f"Markdown={md_reliability_count}, HTML>={html_reliability_count}",
    )

    # ── Per-parameter checks (when config is provided) ─────────────────
    if cfg_params and is_multi_param:
        # Cross-parameter section
        has_cross = bool(re.search(
            r"Cross-parameter findings", findings_md, re.IGNORECASE
        ))
        c_findings = re.findall(r"Finding\s+C\d+:", findings_md)
        if c_findings:
            all_pass &= check("Cross-parameter section in Markdown", has_cross)
            all_pass &= check(
                "Cross-parameter section in HTML",
                "cross-parameter" in html.lower(),
            )

        # Per-parameter sections
        for p in cfg_params:
            pname = p["name"]
            # Section heading in Markdown
            has_section_md = bool(re.search(
                rf"### Parameter `{re.escape(pname)}`", findings_md
            ))
            all_pass &= check(f"Per-param section '{pname}' in Markdown", has_section_md)

            # Section or anchor in HTML
            has_section_html = (
                pname.lower() in html.lower()
                and bool(re.search(
                    rf"(param-{re.escape(pname)}|Parameter.*{re.escape(pname)})",
                    html, re.IGNORECASE,
                ))
            )
            all_pass &= check(f"Per-param section '{pname}' in HTML", has_section_html)

            # Per-param finding count
            md_pp_count = len(re.findall(
                rf"Finding\s+{re.escape(pname)}\.\d+:", findings_md
            ))
            html_pp_count = len(re.findall(
                rf"Finding\s+{re.escape(pname)}\.\d+:", html, re.IGNORECASE
            ))
            all_pass &= check(
                f"Finding count for '{pname}'",
                html_pp_count >= md_pp_count,
                f"MD={md_pp_count}, HTML={html_pp_count}",
            )

    # ── Pinned-companion documentation check ───────────────────────────
    if has_pinned_companions:
        companion_in_md = "pinned companion" in findings_md.lower()
        all_pass &= check(
            "Pinned companion documentation in findings.md",
            companion_in_md,
        )
        companion_in_html = "pinned companion" in html.lower()
        all_pass &= check(
            "Pinned companion documentation in HTML",
            companion_in_html,
        )

    # ── Dependency banner phrasing check ───────────────────────────────
    # If the HTML contains a dependency warning/banner AND companions are
    # configured, the banner must include a "pinned companion values" bullet.
    html_lower = html.lower()
    has_dependency_banner = (
        "dependency" in html_lower
        and ("warning" in html_lower or "banner" in html_lower or "validity" in html_lower
             or "populated responses" in html_lower)
    )
    if has_dependency_banner and has_pinned_companions:
        banner_mentions_companions = (
            "pinned companion" in html_lower
            or "companion values" in html_lower
        )
        all_pass &= check(
            "Dependency banner includes pinned-companion bullet",
            banner_mentions_companions,
        )

    # ── Summary ─────────────────────────────────────────────────────────
    print("=" * 50)
    if all_pass:
        print("  All checks passed.")
    else:
        print("  Some checks FAILED. Fix the HTML before reporting completion.")
        sys.exit(1)


if __name__ == "__main__":
    main()
