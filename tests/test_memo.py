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


def test_render_is_deterministic(tmp_path: Path) -> None:
    final = _final(tmp_path)
    assert render_memo(final, question="Q") == render_memo(final, question="Q")


def test_write_memo_creates_file(tmp_path: Path) -> None:
    final = _final(tmp_path)
    paths = RunPaths(root=tmp_path / "out", run_id="r")
    path = write_memo(paths, final, question="Q")
    assert path.exists() and path.name == "memo.md"
    assert "Decision Memo" in path.read_text(encoding="utf-8")
