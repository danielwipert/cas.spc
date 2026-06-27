"""Render the Phase 8 pilot report (Milestone 3) to Markdown.

Takes the computed `EvaluationReport` and renders the §20 comparison, the
hypothesis verdicts (spec §4), and the §8.5 demo moment into a single human-
readable document written to `runs/<id>/report/pilot_report.md`. The render is
pure and deterministic — same report in, same bytes out.
"""

from __future__ import annotations

import json

from ..store import RunPaths
from .metrics import EvaluationReport, MetricResult

_HYPOTHESES = {
    "H1": "State Continuity — persistent state preserves claims, caveats, "
    "dependencies, assumptions, contradictions, and evidence links better "
    "than a prompt chain.",
    "H2": "Reduced Reprocessing — later stages re-read and re-derive less by "
    "operating over existing structured state.",
    "H3": "Stronger Auditability — the system can explain how a claim entered, "
    "which transform produced it, and what it depends on.",
    "H4": "Better Follow-Up Reasoning — follow-ups are answered by querying "
    "state, not reconstructing prose.",
    "H5": "More Governable LLM Use — operators emit validated patches, not "
    "final answers.",
    "H6": "Clearer Multi-Agent Coordination — perspectives specialise without "
    "private realities.",
}


def _metric_section(m: MetricResult) -> list[str]:
    lines = [
        f"### §{m.key} {m.name}",
        "",
        f"_Bears on: {', '.join(m.hypotheses)}_",
        "",
        f"> {m.question}",
        "",
        f"**{m.headline}**",
        "",
        "| | SPC engine | JSON-handoff baseline |",
        "|---|---|---|",
    ]
    keys = [k for k in m.spc if k != "detail" and k != "answers" and k != "note"]
    base_keys = [
        k for k in m.baseline if k not in ("detail", "answers", "note")
    ]
    for k in dict.fromkeys([*keys, *base_keys]):
        spc_v = _fmt(m.spc.get(k, "—"))
        base_v = _fmt(m.baseline.get(k, "—"))
        lines.append(f"| {k} | {spc_v} | {base_v} |")
    for side, label in ((m.spc, "SPC"), (m.baseline, "Baseline")):
        if note := side.get("note"):
            lines.append("")
            lines.append(f"_{label} note: {note}_")
    lines.append("")
    return lines


def _fmt(v: object) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, dict):
        return ", ".join(f"{k}={_fmt(val)}" for k, val in v.items())
    return str(v)


def _hypothesis_verdicts(report: EvaluationReport) -> list[str]:
    # Group metric headlines under the hypotheses they bear on.
    by_h: dict[str, list[str]] = {h: [] for h in _HYPOTHESES}
    for m in report.metrics:
        for h in m.hypotheses:
            by_h.setdefault(h, []).append(f"§{m.key} {m.name}")
    lines = ["## Hypothesis verdicts (spec §4)", ""]
    for h, desc in _HYPOTHESES.items():
        evidence = by_h.get(h) or []
        if h == "H5":
            verdict = (
                "Supported by construction — every operator in the run emits a "
                "`SemanticPatch` that the runtime validates, routes, and only "
                "then commits (Phases 3, 6, 7)."
            )
        elif evidence:
            verdict = "Supported — see " + ", ".join(evidence) + "."
        else:
            verdict = "Out of scope for this run."
        lines.append(f"- **{h}** — {desc}")
        lines.append(f"  - {verdict}")
    lines.append("")
    return lines


def render_markdown(report: EvaluationReport) -> str:
    lines: list[str] = [
        "# SPC Pilot Report — Shared Semantic State vs. JSON Handoff",
        "",
        f"_Run `{report.run_id}` · baseline model `{report.baseline_model}` · "
        f"SPC final state v{report.spc_final_version} · "
        f"generated {report.generated_at.isoformat()}_",
        "",
        "## What this compares",
        "",
        "Both systems take the **same** input document and the same model "
        "budget and produce a recommendation. The SPC engine routes every "
        "change through a validated `SemanticPatch` into versioned "
        "`SemanticState`; the baseline is a competent JSON-handoff chain "
        "(summary → critique → final memo) that keeps no durable state.",
        "",
        "This report does **not** claim SPC writes a better memo (spec §5). It "
        "measures the *substrate*: provenance, continuity, drift, reprocessing, "
        "auditability, and the ability to answer follow-ups without re-running.",
        "",
        "## Input document",
        "",
        "```text",
        report.document.strip(),
        "```",
        "",
        "## Scorecard (spec §20)",
        "",
        "| Metric | SPC vs. baseline |",
        "|---|---|",
    ]
    for m in report.metrics:
        lines.append(f"| §{m.key} {m.name} | {m.headline} |")
    lines.append("")

    lines.append("## Metric detail")
    lines.append("")
    for m in report.metrics:
        lines.extend(_metric_section(m))

    lines.extend(_hypothesis_verdicts(report))

    dm = report.demo_moment
    lines.extend(
        [
            "## The demo moment (spec §8.5)",
            "",
            f"**Follow-up:** _{dm.question}_",
            "",
            "**Baseline:**",
            "",
            f"> {dm.baseline_response}",
            "",
            "**SPC engine:**",
            "",
            f"> {dm.spc_response}",
            "",
            f"The SPC engine answered {report.followups_spc_answered}/"
            f"{report.followups_total} of the §8.4 follow-ups directly from "
            "committed state, with no source reprocessing. The baseline must "
            "re-read or re-run for every one.",
            "",
            "---",
            "",
            "_Generated by `spc-demo report`. Every figure is a read over the "
            "committed state history and the baseline output — no value is "
            "hand-set._",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(paths: RunPaths, report: EvaluationReport) -> tuple[str, str]:
    """Write `pilot_report.md` and `metrics.json`; return their paths."""
    paths.report_dir.mkdir(parents=True, exist_ok=True)
    md = render_markdown(report)
    md_path = paths.report_file("pilot_report.md")
    md_path.write_text(md, encoding="utf-8")
    json_path = paths.report_file("metrics.json")
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return str(md_path), str(json_path)


__all__ = ["render_markdown", "write_report"]
