"""Decision Memo renderer tests — faithful, citation-backed projection of state."""

from __future__ import annotations

from pathlib import Path

from spc_state.memo import render_memo, write_memo
from spc_state.store import RunPaths
from tests._demo_helpers import run_demo


def _final(tmp_path: Path):
    _, states = run_demo(tmp_path / "runs")
    return states[-1]


def test_memo_has_expected_sections(tmp_path: Path) -> None:
    md = render_memo(_final(tmp_path), question="Should we adopt the assistant?")
    for section in (
        "# Decision Memo: Should we adopt the assistant?",
        "## Recommendation",
        "## Key findings",
        "## Assumptions this rests on",
        "## Open questions",
        "## Sources",
    ):
        assert section in md


def test_memo_recommendation_is_the_leading_hypothesis(tmp_path: Path) -> None:
    final = _final(tmp_path)
    md = render_memo(final)
    lead = max(final.hypotheses.values(), key=lambda h: h.confidence)
    assert f"**{lead.text}**" in md


def test_every_claim_with_evidence_is_cited(tmp_path: Path) -> None:
    final = _final(tmp_path)
    md = render_memo(final)
    # Each evidence object gets a [E#] label, and it appears in the Sources list.
    assert "[E1]" in md
    for e in final.evidence.values():
        assert e.quote_or_span in md


def test_memo_asserts_nothing_absent_from_state(tmp_path: Path) -> None:
    # The memo is a projection: claim texts in the body must come from state.
    final = _final(tmp_path)
    md = render_memo(final)
    for c in final.claims.values():
        assert c.text in md


def test_weak_claim_surfaces_as_risk(tmp_path: Path) -> None:
    # The demo critic drops claim_001 to 0.62 (< 0.75) — it must show as a risk.
    final = _final(tmp_path)
    md = render_memo(final)
    assert "## Risks and caveats" in md
    assert "Weakly supported" in md


def test_inferred_but_well_supported_claim_is_not_a_risk(tmp_path: Path) -> None:
    # An `inferred` claim with high confidence and high-reliability evidence
    # must NOT be labelled "weakly supported" — only thin support counts.
    import datetime as dt

    from spc_state.models import (
        Claim,
        EpistemicStatus,
        Evidence,
        Reliability,
        StateStatus,
    )
    from spc_state.runtime import bootstrap_state

    now = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)
    base = bootstrap_state(state_id="s", project_id="p", name="n", now=now)
    strong_inference = Claim(
        id="claim_rec",
        text="Officials should act now.",
        epistemic_status=EpistemicStatus.INFERRED,
        confidence=0.8,
        supporting_evidence=["ev_solid"],
    )
    thin = Claim(
        id="claim_thin",
        text="The economy masks reality.",
        epistemic_status=EpistemicStatus.INFERRED,
        confidence=0.6,
        supporting_evidence=["ev_solid"],
    )
    ev = Evidence(
        id="ev_solid",
        source_type="input_document",
        source_id="doc",
        quote_or_span="a solid span",
        reliability=Reliability.HIGH,
    )
    state = base.model_copy(
        update={
            "state_version": 1,
            "status": StateStatus.ACTIVE,
            "claims": {strong_inference.id: strong_inference, thin.id: thin},
            "evidence": {ev.id: ev},
        }
    )
    md = render_memo(state)
    # The low-confidence one is a risk; the high-confidence inference is not.
    assert "The economy masks reality." in md.split("## Risks and caveats")[1].split("##")[0]
    risks = md.split("## Risks and caveats")[1].split("##")[0]
    assert "Officials should act now." not in risks


def test_render_is_deterministic(tmp_path: Path) -> None:
    final = _final(tmp_path)
    assert render_memo(final, question="Q") == render_memo(final, question="Q")


def test_write_memo_creates_file(tmp_path: Path) -> None:
    final = _final(tmp_path)
    paths = RunPaths(root=tmp_path / "out", run_id="r")
    path = write_memo(paths, final, question="Q")
    assert path.exists() and path.name == "memo.md"
    assert "Decision Memo" in path.read_text(encoding="utf-8")
