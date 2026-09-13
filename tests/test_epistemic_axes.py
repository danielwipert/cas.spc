"""T20 — one status cannot hold three facts.

`EpistemicStatus` used to carry seven members answering three different
questions: how a claim was acquired, how well it is supported (`VERIFIED`), and
whether anything contradicts it (`CONTRADICTED`). A claim has a value on all
three at once and one field holds one, so every write on a second axis destroyed
the first — T19's corroboration overwrote `REPORTED` with `VERIFIED`, although a
corroborated claim is still reported.

These tests pin the split: acquisition is stored and narrowed to five members,
support and conflict are derived from state that already holds them, and the
bar for `VERIFIED` now requires **independent** sources — the case that could not
be expressed at all before, and the reason its old bar was unsafe rather than
merely low.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spc_state.epistemics import (
    Corroboration,
    corroboration_of,
    is_contested,
    source_lineage,
    sources_are_independent,
)
from spc_state.models import (
    Claim,
    Contradiction,
    ContradictionStatus,
    EpistemicStatus,
    Evidence,
    Reliability,
    SemanticPatch,
    SemanticState,
    StateStatus,
    ValidationSeverity,
)
from spc_state.models.enums import RETIRED_EPISTEMIC_STATUSES
from spc_state.projection.builder import is_strong_claim, is_weak_claim
from spc_state.store import RunPaths, StateStore
from spc_state.validation.l2 import validate_patch

NOW = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _ev(
    eid: str,
    source_id: str,
    reliability: Reliability = Reliability.MEDIUM,
    derives_from: str | None = None,
) -> Evidence:
    return Evidence(
        id=eid,
        source_type="input_document",
        source_id=source_id,
        quote_or_span=f"span for {eid}",
        reliability=reliability,
        derives_from=derives_from,
    )


def _claim(
    cid: str = "claim_001",
    evidence: list[str] | None = None,
    status: EpistemicStatus = EpistemicStatus.REPORTED,
    confidence: float = 0.6,
) -> Claim:
    return Claim(
        id=cid,
        text=f"Claim {cid}.",
        epistemic_status=status,
        confidence=confidence,
        supporting_evidence=evidence or [],
    )


def _state(**kwargs: object) -> SemanticState:
    base: dict[str, object] = {
        "state_id": "state_t20",
        "project_id": "p",
        "name": "t20",
        "state_version": 1,
        "status": StateStatus.ACTIVE,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(kwargs)
    return SemanticState.model_validate(base)


# ---------------------------------------------------------------------------
# Acquisition — the one axis that is still stored
# ---------------------------------------------------------------------------


def test_the_axis_holds_five_mutually_exclusive_answers() -> None:
    """One question, five answers. Support and conflict are not among them."""
    assert {s.value for s in EpistemicStatus} == {
        "observed",
        "reported",
        "inferred",
        "assumed",
        "speculative",
    }


@pytest.mark.parametrize("retired", ["verified", "contradicted"])
def test_a_retired_status_is_not_constructible(retired: str) -> None:
    with pytest.raises(AttributeError):
        getattr(EpistemicStatus, retired.upper())


@pytest.mark.parametrize("retired", sorted(RETIRED_EPISTEMIC_STATUSES))
def test_a_claim_carrying_a_retired_status_loads_as_reported(retired: str) -> None:
    """Both were reached *from* `reported`, so that is what they migrate to."""
    claim = Claim.model_validate(
        {
            "id": "claim_001",
            "text": "A claim stored before T20.",
            "epistemic_status": retired,
            "confidence": 0.9,
            "supporting_evidence": ["ev_001"],
        }
    )
    assert claim.epistemic_status is EpistemicStatus.REPORTED


def test_a_state_file_on_disk_carrying_a_retired_status_round_trips(
    tmp_path: Path,
) -> None:
    """The migration is on the model, so every load path gets it — not just one.

    Written as raw JSON rather than through the models, because a pre-T20 file is
    exactly what no current code path can produce.
    """
    paths = RunPaths(root=tmp_path / "runs", run_id="legacy")
    payload = json.loads(_state().model_dump_json(by_alias=True))
    payload["claims"] = {
        "claim_001": {
            "id": "claim_001",
            "object_type": "claim",
            "text": "Corroborated before T20 retired the label.",
            "claim_type": "factual_claim",
            "epistemic_status": "verified",
            "confidence": 0.9,
            "status": "active",
            "supporting_evidence": ["ev_001"],
            "assumptions": [],
            "contradicted_by": [],
            "derived_from": [],
            "extracted_by": None,
        }
    }
    target = paths.state_file(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    loaded = StateStore(paths).read(1)
    assert loaded.claims["claim_001"].epistemic_status is EpistemicStatus.REPORTED


# ---------------------------------------------------------------------------
# Derived corroboration
# ---------------------------------------------------------------------------


def test_one_source_is_uncorroborated() -> None:
    evidence = {"ev_001": _ev("ev_001", "doc_001")}
    claim = _claim(evidence=["ev_001"])
    assert corroboration_of(claim, evidence) is Corroboration.UNCORROBORATED


def test_two_spans_from_the_same_document_are_uncorroborated() -> None:
    """A document agreeing with itself corroborates nothing."""
    evidence = {
        "ev_001": _ev("ev_001", "doc_001"),
        "ev_002": _ev("ev_002", "doc_001", Reliability.HIGH),
    }
    claim = _claim(evidence=["ev_001", "ev_002"])
    assert corroboration_of(claim, evidence) is Corroboration.UNCORROBORATED


def test_two_independent_interested_sources_are_corroborated_not_verified() -> None:
    """Two press releases agreeing is two interested parties, not verification."""
    evidence = {
        "ev_001": _ev("ev_001", "doc_001", Reliability.LOW),
        "ev_002": _ev("ev_002", "doc_002", Reliability.LOW),
    }
    claim = _claim(evidence=["ev_001", "ev_002"])
    assert corroboration_of(claim, evidence) is Corroboration.CORROBORATED


def test_an_accountable_independent_source_verifies() -> None:
    evidence = {
        "ev_001": _ev("ev_001", "doc_001", Reliability.LOW),
        "ev_002": _ev("ev_002", "doc_002", Reliability.HIGH),
    }
    claim = _claim(evidence=["ev_001", "ev_002"])
    assert corroboration_of(claim, evidence) is Corroboration.VERIFIED


def test_a_derived_source_does_not_corroborate_its_own_origin() -> None:
    """The case T20 exists for, and the one the old bar could not express.

    A wire story republished by an accountable outlet is still the press
    release. Before lineage this pair read as two independent sources with a
    `HIGH` among them — the exact shape that promoted a claim to `verified`.
    """
    evidence = {
        "ev_001": _ev("ev_001", "doc_001", Reliability.LOW),
        "ev_002": _ev("ev_002", "doc_002", Reliability.HIGH, derives_from="doc_001"),
    }
    claim = _claim(evidence=["ev_001", "ev_002"])
    assert corroboration_of(claim, evidence) is Corroboration.UNCORROBORATED


def test_lineage_is_transitive() -> None:
    """A relayed relay is still the original source."""
    lineage = {"doc_001": None, "doc_002": "doc_001", "doc_003": "doc_002"}
    assert not sources_are_independent("doc_001", "doc_003", lineage)
    assert not sources_are_independent("doc_003", "doc_001", lineage)


def test_two_documents_off_one_origin_are_independent_of_each_other() -> None:
    """Deliberate: neither is downstream *of the other*.

    Two reporters each working from the same filing did each read the filing.
    The rule is ancestry, not shared ancestry, and pinning it here makes the
    choice a decision rather than an accident.
    """
    lineage = {"doc_001": None, "doc_002": "doc_001", "doc_003": "doc_001"}
    assert sources_are_independent("doc_002", "doc_003", lineage)


def test_a_lineage_cycle_terminates() -> None:
    lineage = {"doc_001": "doc_002", "doc_002": "doc_001"}
    assert not sources_are_independent("doc_001", "doc_002", lineage)


def test_undeclared_lineage_counts_as_independent() -> None:
    evidence = {
        "ev_001": _ev("ev_001", "doc_001"),
        "ev_002": _ev("ev_002", "doc_002", Reliability.HIGH),
    }
    assert source_lineage(evidence) == {"doc_001": None, "doc_002": None}
    assert sources_are_independent("doc_001", "doc_002", source_lineage(evidence))


def test_one_declared_span_settles_the_lineage_of_its_source() -> None:
    """Several spans share a source id; an unlabelled sibling erases nothing."""
    evidence = {
        "ev_001": _ev("ev_001", "doc_002", derives_from="doc_001"),
        "ev_002": _ev("ev_002", "doc_002"),
    }
    assert source_lineage(evidence)["doc_002"] == "doc_001"


def test_a_claim_citing_a_missing_span_is_not_corroborated_by_it() -> None:
    claim = _claim(evidence=["ev_001", "ev_gone"])
    assert corroboration_of(claim, {"ev_001": _ev("ev_001", "doc_001")}) is (
        Corroboration.UNCORROBORATED
    )


# ---------------------------------------------------------------------------
# Derived conflict
# ---------------------------------------------------------------------------


def _contradiction(status: ContradictionStatus) -> dict[str, Contradiction]:
    return {
        "contra_001": Contradiction(
            id="contra_001",
            claim_a="claim_001",
            claim_b="claim_002",
            status=status,
        )
    }


def test_an_unresolved_contradiction_contests_both_claims() -> None:
    contradictions = _contradiction(ContradictionStatus.UNRESOLVED)
    assert is_contested("claim_001", contradictions)
    assert is_contested("claim_002", contradictions)
    assert not is_contested("claim_003", contradictions)


@pytest.mark.parametrize(
    "status", [ContradictionStatus.RESOLVED, ContradictionStatus.DISMISSED]
)
def test_a_settled_contradiction_does_not_contest(status: ContradictionStatus) -> None:
    assert not is_contested("claim_001", _contradiction(status))


def test_conflict_changes_no_field_on_the_claim() -> None:
    """The whole point: conflict is read from the graph, not written onto it."""
    claim = _claim()
    before = claim.model_dump()
    state = _state(
        claims={"claim_001": claim},
        contradictions=_contradiction(ContradictionStatus.UNRESOLVED),
    )
    assert is_contested("claim_001", state.contradictions)
    assert state.claims["claim_001"].model_dump() == before


# ---------------------------------------------------------------------------
# The subsets the axis replaced — today's behaviour, pinned unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "grounded"),
    [
        (EpistemicStatus.OBSERVED, True),
        (EpistemicStatus.REPORTED, True),
        (EpistemicStatus.INFERRED, False),
        (EpistemicStatus.ASSUMED, False),
        (EpistemicStatus.SPECULATIVE, False),
    ],
)
def test_groundedness_is_a_property_of_the_axis(
    status: EpistemicStatus, grounded: bool
) -> None:
    assert status.is_grounded is grounded


@pytest.mark.parametrize(
    ("status", "needed"),
    [
        (EpistemicStatus.OBSERVED, True),
        (EpistemicStatus.REPORTED, True),
        (EpistemicStatus.INFERRED, True),
        (EpistemicStatus.ASSUMED, False),
        (EpistemicStatus.SPECULATIVE, False),
    ],
)
def test_provenance_need_is_a_property_of_the_axis(
    status: EpistemicStatus, needed: bool
) -> None:
    assert status.needs_provenance is needed


def test_a_reported_claim_is_still_grounded_and_not_weak() -> None:
    """T17's deliberate non-change, which the refactor must not quietly undo."""
    claim = _claim(status=EpistemicStatus.REPORTED, confidence=0.9, evidence=["ev_001"])
    assert not is_weak_claim(claim)
    assert is_strong_claim(claim)


def _patch_adding(claim: dict[str, object]) -> SemanticPatch:
    return SemanticPatch.model_validate(
        {
            "patch_id": "patch_test",
            "patch_version": "0.1.0",
            "base_state_id": "state_t20",
            "base_state_version": 1,
            "proposed_by": "test_op@0.1.0",
            "created_at": NOW.isoformat(),
            "read_set": [],
            "add_objects": {"claims": [claim]},
            "update_objects": [],
            "add_relations": [],
            "archive_objects": [],
            "transform_record": {
                "id": "transform_test",
                "transform_type": "extract",
                "operator": "test_op",
                "operator_version": "test_op@0.1.0",
                "input_state_version": 1,
                "output_state_version": None,
                "read_set": [],
                "write_set": ["claim_001"],
                "confidence_changes": [],
            },
            "status": "proposed",
        }
    )


@pytest.mark.parametrize(
    "status", ["observed", "reported", "inferred"]
)
def test_l2_still_requires_provenance_where_the_status_claims_some(
    status: str,
) -> None:
    """`needs_provenance` drives the L2 gate now; the gate itself is unmoved."""
    patch = _patch_adding(
        {
            "id": "claim_001",
            "text": "Confident and unsupported.",
            "epistemic_status": status,
            "confidence": 0.9,
        }
    )
    errors = [
        i
        for i in validate_patch(_state(state_version=1), patch)
        if i.severity is ValidationSeverity.ERROR
    ]
    assert any(i.code == "L2.CLAIM_MISSING_PROVENANCE" for i in errors)


@pytest.mark.parametrize("status", ["assumed", "speculative"])
def test_l2_still_exempts_a_claim_that_says_it_rests_on_nothing(status: str) -> None:
    patch = _patch_adding(
        {
            "id": "claim_001",
            "text": "Says out loud that nothing supports it.",
            "epistemic_status": status,
            "confidence": 0.9,
        }
    )
    codes = {i.code for i in validate_patch(_state(state_version=1), patch)}
    assert "L2.CLAIM_MISSING_PROVENANCE" not in codes


# ---------------------------------------------------------------------------
# Declared lineage reaches committed state — on both routes in
# ---------------------------------------------------------------------------

_DOCUMENT = (
    "Reuters reports that TitanCorp announced record quarterly results. "
    "Revenue grew 41% year over year."
)
_QUOTE = "Revenue grew 41% year over year"


def _assembled_payload() -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "text": "TitanCorp's revenue grew sharply.",
                    "claim_type": "factual_claim",
                    "confidence": 0.9,
                    "evidence_quote": _QUOTE,
                    "assumption": None,
                }
            ]
        }
    )


def _passthrough_payload(derives_from: str | None) -> str:
    """The other way in: a full patch the model wrote, declaring its own lineage.

    It claims independence (or someone else's parent). The operator must
    overwrite it with what the caller declared, exactly as it does reliability —
    otherwise a patch buys back the independence the flag was passed to deny.
    """
    now = "2026-09-13T00:00:00Z"
    return json.dumps(
        {
            "patch_id": "patch_001",
            "base_state_id": "sr_x",
            "base_state_version": 0,
            "proposed_by": "llm_extract_transform@0.1.0",
            "created_at": now,
            "read_set": [],
            "add_objects": {
                "claims": [
                    {
                        "id": "claim_001",
                        "object_type": "claim",
                        "text": "TitanCorp's revenue grew sharply.",
                        "claim_type": "factual_claim",
                        "epistemic_status": "reported",
                        "confidence": 0.9,
                        "status": "active",
                        "supporting_evidence": ["ev_001"],
                        "assumptions": [],
                        "extracted_by": "transform_extract_001",
                    }
                ],
                "evidence": [
                    {
                        "id": "ev_001",
                        "object_type": "evidence",
                        "source_type": "input_document",
                        "source_id": "doc_001",
                        "quote_or_span": _QUOTE,
                        "reliability": "high",
                        "status": "active",
                        "derives_from": derives_from,
                        "extracted_by": "transform_extract_001",
                    }
                ],
            },
            "transform_record": {
                "id": "transform_extract_001",
                "transform_type": "extract",
                "operator": "llm_extract_transform",
                "operator_version": "llm_extract_transform@0.1.0",
                "input_state_version": 0,
                "output_state_version": None,
                "read_set": [],
                "write_set": ["claim_001", "ev_001"],
                "confidence_changes": [],
                "started_at": now,
                "finished_at": now,
            },
            "status": "proposed",
        }
    )


def _extract_evidence(tmp_path: Path, payload: str, declared: str | None) -> Evidence:
    import datetime as _dt

    from spc_state.operators import LLMExtractOperator
    from spc_state.providers.mock import MockProvider
    from spc_state.runtime import FixedClock, Runtime, bootstrap_state
    from spc_state.source_types import SourceType

    clock = FixedClock(
        [NOW + _dt.timedelta(seconds=10 * i) for i in range(20)]
    )
    operator = LLMExtractOperator(
        MockProvider([payload], provider="fake", model="fake-extract-v0"),
        input_text=_DOCUMENT,
        clock=clock,
        source_type=SourceType.NEWS_REPORT,
        derives_from=declared,
    )
    runtime = Runtime(paths=RunPaths(root=tmp_path, run_id="lineage"), clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr_x", project_id="p", name="TitanCorp", now=clock.now()
        ),
        operators=[operator],
        input_text=_DOCUMENT,
    )
    assert result.final_state.state_version == 1, "the extraction must have committed"
    return next(iter(result.final_state.evidence.values()))


def test_declared_lineage_reaches_committed_state_on_the_assembled_route(
    tmp_path: Path,
) -> None:
    item = _extract_evidence(tmp_path, _assembled_payload(), "doc_000")
    assert item.derives_from == "doc_000"


@pytest.mark.parametrize("model_says", [None, "doc_999"])
def test_declared_lineage_overrides_the_model_on_the_passthrough_route(
    tmp_path: Path, model_says: str | None
) -> None:
    """The second way in that T8, T11, T14 and T17 each had to close separately.

    A patch asserting `derives_from: null` is asserting its own independence,
    which is the one thing corroboration must not take a model's word for.
    """
    item = _extract_evidence(tmp_path, _passthrough_payload(model_says), "doc_000")
    assert item.derives_from == "doc_000"


def test_an_undeclared_document_commits_no_lineage(tmp_path: Path) -> None:
    item = _extract_evidence(tmp_path, _assembled_payload(), None)
    assert item.derives_from is None
