from datetime import UTC, datetime
from decimal import Decimal

from app.journal import GENESIS, compute_hash, verify_entries
from app.models import JournalEntry


def chain(n: int) -> list[JournalEntry]:
    rows, prev = [], GENESIS
    for i in range(1, n + 1):
        e = JournalEntry(
            org_id=1, seq=i, created_at=datetime(2026, 11, 9, 10, i, tzinfo=UTC), procurement_id=1,
            actor_kind="agent", actor_user_id=None, action="status", input_ref=None, decision="ok", rule_code=None,
            model=None, prompt_version=None, tokens=None, cost_rub=Decimal("1.5"), evidence_sha256=None,
            details={"i": i}, prev_hash=prev,
        )
        e.hash = compute_hash(e)
        rows.append(e)
        prev = e.hash
    return rows


def test_intact_chain_verifies() -> None:
    assert verify_entries(chain(5)).ok


def test_changed_content_is_detected() -> None:
    rows = chain(5)
    rows[2].details = {"i": 999}
    res = verify_entries(rows)
    assert not res.ok and res.broken_seq == 3 and res.reason == "Содержимое записи изменено"


def test_changed_evidence_hash_is_detected() -> None:
    rows = chain(3)
    rows[1].evidence_sha256 = "f" * 64
    assert verify_entries(rows).broken_seq == 2


def test_removed_entry_is_detected() -> None:
    rows = chain(5)
    del rows[1]
    assert verify_entries(rows).broken_seq == 3
