import pytest

from app.pipeline import ALLOWED, FINAL, HUMAN_ONLY, Status, TransitionError, check

S = Status


def test_happy_path_is_allowed() -> None:
    path = [S.DRAFT, S.SPEC_REVIEW, S.SOURCING, S.COLLECTING, S.ANALYSIS, S.JUSTIFICATION_REVIEW, S.APPROVED, S.CLOSED]
    for frm, to in zip(path, path[1:], strict=False):
        actor, role = ("human", "contract_manager") if (frm, to) in HUMAN_ONLY else ("agent", None)
        check(frm, to, actor, role)


def test_agent_cannot_confirm_spec_or_approve() -> None:
    with pytest.raises(TransitionError):
        check(S.SPEC_REVIEW, S.SOURCING, "agent", None)
    with pytest.raises(TransitionError):
        check(S.JUSTIFICATION_REVIEW, S.APPROVED, "agent", None)


def test_only_contract_manager_approves() -> None:
    with pytest.raises(TransitionError):
        check(S.JUSTIFICATION_REVIEW, S.APPROVED, "human", "initiator")
    check(S.JUSTIFICATION_REVIEW, S.APPROVED, "human", "contract_manager")


def test_initiator_can_confirm_spec() -> None:
    check(S.SPEC_REVIEW, S.SOURCING, "human", "initiator")


def test_no_skipping_steps() -> None:
    with pytest.raises(TransitionError):
        check(S.DRAFT, S.APPROVED, "human", "contract_manager")
    with pytest.raises(TransitionError):
        check(S.SOURCING, S.JUSTIFICATION_REVIEW, "agent", None)


def test_escalation_and_cancel() -> None:
    for st in S:
        if st in FINAL or st in (S.NEEDS_HUMAN,):
            continue
        check(st, S.NEEDS_HUMAN, "agent", None)
        check(st, S.CANCELLED, "human", "initiator")
        with pytest.raises(TransitionError):
            check(st, S.CANCELLED, "agent", None)
    for st in FINAL:
        with pytest.raises(TransitionError):
            check(st, S.NEEDS_HUMAN, "agent", None)


def test_every_status_has_rules() -> None:
    assert set(ALLOWED) == set(S)
