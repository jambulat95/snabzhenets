from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.methodology.engine import ItemIn, QuoteIn, check_quote, evaluate, profile, stats

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
ITEM = ItemIn(id=1, line_no=1, name="Картридж HP CF259A", quantity=Decimal("20"))


def q(i: int, price: str, **kw: object) -> QuoteIn:
    base: dict[str, object] = dict(
        id=i, item_id=1, channel="email", source=f"S{i}", unit_price=Decimal(price), vat_mode="with",
        captured_at=NOW - timedelta(days=1), status="ok", evidence_ok=True, source_verdict="allow",
        source_reason=None, delivery_included=True, human_decision=None, human_reason=None,
    )
    base.update(kw)
    return QuoteIn(**base)  # type: ignore[arg-type]


def test_stats_sample_std() -> None:
    mean, cv = stats([Decimal(10), Decimal(12), Decimal(14)])
    assert mean == 12
    assert cv is not None and abs(cv - Decimal("0.1666666666")) < Decimal("0.0000001")  # σ=2 (n−1)


def test_three_prices_give_nmck() -> None:
    res = evaluate([ITEM], [q(1, "13250"), q(2, "13532"), q(3, "12369")], requests_sent=5, now=NOW)
    it = res["items"][0]
    assert it["admitted"] == 3 and it["ok"] and res["ready"]
    assert it["mean"] == "13050.33"
    assert it["nmck"] == "261006.67"  # 20 × 13050,333…, округление — до копеек, ROUND_HALF_UP
    assert res["total_nmck"] == "261006.67"


def test_two_prices_are_not_enough() -> None:
    res = evaluate([ITEM], [q(1, "100"), q(2, "110")], requests_sent=5, now=NOW)
    assert not res["ready"] and res["items"][0]["verdicts"][0]["code"] == "М-02"
    assert res["total_nmck"] is None


def test_stale_price_is_excluded_and_human_cannot_include_it() -> None:
    old = q(4, "13000", captured_at=datetime(2026, 3, 12, tzinfo=UTC), human_decision="include", human_reason="хочу")
    r = check_quote(old, NOW, profile())
    assert not r.admitted and any(v.code == "М-03" for v in r.verdicts)


def test_review_needs_human_and_human_can_include() -> None:
    assert not check_quote(q(5, "100", status="review"), NOW, profile()).admitted
    assert check_quote(q(5, "100", status="review", human_decision="include", human_reason="сверено"),
                       NOW, profile()).admitted


def test_cv_above_33_percent_blocks_until_outlier_excluded() -> None:
    projector = ItemIn(2, 2, "Проектор", Decimal(2))
    prices = ["33670", "28254", "33744", "35690", "70710"]
    quotes = [q(n, p, item_id=2) for n, p in enumerate(prices, start=1)]
    it = evaluate([projector], quotes, requests_sent=5, now=NOW)["items"][0]
    assert not it["ok"] and any(v["code"] == "М-07" for v in it["verdicts"])
    quotes[4] = q(5, "70710", item_id=2, human_decision="exclude", human_reason="другой класс проектора")
    res = evaluate([projector], quotes, requests_sent=5, now=NOW)
    assert res["items"][0]["ok"] and res["ready"] and res["items"][0]["admitted"] == 4


def test_site_price_warns_but_counts() -> None:
    r = check_quote(q(6, "550", channel="site", delivery_included=False), NOW, profile())
    assert r.admitted and {v.code for v in r.verdicts} == {"М-05", "М-08"}


def test_missing_evidence_or_bad_source_excludes() -> None:
    assert not check_quote(q(7, "1", evidence_ok=False), NOW, profile()).admitted
    assert not check_quote(q(8, "1", source_verdict="deny", source_reason="ликвидация"), NOW, profile()).admitted


def test_few_requests_is_warning() -> None:
    res = evaluate([ITEM], [q(1, "1"), q(2, "1"), q(3, "1")], requests_sent=3, now=NOW)
    assert res["general"][0]["code"] == "М-01" and res["general"][0]["verdict"] == "warn" and res["ready"]
