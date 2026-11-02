"""Tests. None of them call the Gemini API, so they run offline and for free.

    .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import csv

import pytest

from supplier_checker import ai_reader, config
from supplier_checker.documents import load_purchase_request, read_pdf_text
from supplier_checker.graph import check_document
from supplier_checker.parser_reader import parse
from supplier_checker.rules import check_against_request, check_company_rules, decide
from supplier_checker.schemas import Decision, Extraction, LineItem, Severity
from supplier_checker.verify import ground_check, reconcile

PR = load_purchase_request()
EXPECTED = list(csv.DictReader(open(config.EXPECTED_CSV, encoding="utf-8")))
SAMPLES = [config.DATA_DIR / row["file"] for row in EXPECTED]


# ----------------------------------------------------------------------------- helpers
def good_extraction(**overrides) -> Extraction:
    """A quote for item A that passes every rule. Override fields to break one rule at a time."""
    qty, price = overrides.pop("quantity", 12000), overrides.pop("unit_price", 470.0)
    amount = overrides.pop("amount", round(qty * price, 2))
    vat = round(amount * 0.15, 2)
    base = dict(
        supplier_name="Test Supplier", pr_reference="PR-2026-114",
        line_items=[LineItem(item_code="A", description="Cotton twill fabric, 280 gsm", quantity=qty,
                             unit="metre", unit_price=price, amount=amount, price_includes_vat=False)],
        subtotal=amount, vat_rate_percent=15.0, vat_amount=vat, total=round(amount + vat, 2),
        tin="123456789012", bin="000123456-0101",
        advance_percent=10.0, payment_days_min=45, payment_days_max=45,
        delivery_days=25, penalty_present=True, penalty_percent_per_week=1.0,
        penalty_basis_order_value=True, validity_days=30,
    )
    base.update(overrides)
    return Extraction(**base)


def run_rules(ex: Extraction, uncertain: set[str] | None = None) -> tuple[Decision, list]:
    uncertain = uncertain or set()
    findings = check_against_request(ex, PR, uncertain) + check_company_rules(ex, uncertain)
    return decide(findings)


def rule_ids(reasons) -> set[str]:
    return {r.rule_id for r in reasons}


# ----------------------------------------------------------------------------- end-to-end
@pytest.mark.parametrize("row", EXPECTED, ids=[r["file"] for r in EXPECTED])
def test_samples_parser_mode(row):
    state = check_document(config.DATA_DIR / row["file"], mode="parser")
    assert state["decision"].value == row["expected_decision"]
    if row["main_rules"]:
        assert set(row["main_rules"].split(";")) <= rule_ids(state["reasons"])


@pytest.mark.parametrize("row", EXPECTED, ids=[r["file"] for r in EXPECTED])
def test_samples_hybrid_mode_with_agreeing_ai(row, monkeypatch):
    """Simulate a perfect AI reader (returns what the parser reads): hybrid must give the same answers."""
    monkeypatch.setattr(ai_reader, "extract", lambda text: ai_reader.AIResult(parse(text), "fake"))
    state = check_document(config.DATA_DIR / row["file"], mode="hybrid")
    assert state["decision"].value == row["expected_decision"]


def test_ai_failure_never_approves(monkeypatch):
    def boom(text):
        raise ai_reader.AIReaderError("quota exceeded")
    monkeypatch.setattr(ai_reader, "extract", boom)
    state = check_document(config.DATA_DIR / "supplier-pack-01.pdf", mode="hybrid")
    assert state["decision"] == Decision.REVIEW
    assert "X3" in rule_ids(state["reasons"])


def test_unreadable_pdf_goes_to_person(tmp_path):
    bad = tmp_path / "scan.pdf"
    bad.write_bytes(b"not really a pdf")
    state = check_document(bad, mode="parser")
    assert state["decision"] == Decision.REVIEW
    assert "X4" in rule_ids(state["reasons"])


# ----------------------------------------------------------------------------- parser
def test_parser_reads_week_based_delivery_and_ranges():
    ex = parse(read_pdf_text(config.DATA_DIR / "supplier-pack-09.pdf"))
    assert ex.delivery_days == 28            # "4 weeks"
    assert (ex.payment_days_min, ex.payment_days_max) == (30, 90)


def test_parser_does_not_invent_tax_ids():
    ex = parse(read_pdf_text(config.DATA_DIR / "supplier-pack-08.pdf"))
    assert ex.tin is None and ex.bin is None


def test_parser_detects_vat_inclusive_price():
    ex = parse(read_pdf_text(config.DATA_DIR / "supplier-pack-10.pdf"))
    assert ex.line_items[0].price_includes_vat is True
    assert ex.vat_rate_percent is None


# ----------------------------------------------------------------------------- rule boundaries
def test_clean_quote_is_approved():
    decision, reasons = run_rules(good_extraction())
    assert decision == Decision.APPROVE, reasons


@pytest.mark.parametrize("price,expected", [
    (480.00, Decision.APPROVE),   # exactly the maximum
    (480.01, Decision.REVIEW),    # just above
    (494.40, Decision.REVIEW),    # exactly +3%
    (494.50, Decision.REJECT),    # above +3%
])
def test_price_bands(price, expected):
    assert run_rules(good_extraction(unit_price=price))[0] == expected


@pytest.mark.parametrize("qty,expected", [(12600, Decision.APPROVE), (12601, Decision.REVIEW), (11399, Decision.REVIEW)])
def test_quantity_tolerance(qty, expected):
    assert run_rules(good_extraction(quantity=qty))[0] == expected


@pytest.mark.parametrize("adv,expected", [(20, Decision.APPROVE), (20.5, Decision.REJECT), (None, Decision.REVIEW)])
def test_advance(adv, expected):
    assert run_rules(good_extraction(advance_percent=adv))[0] == expected


@pytest.mark.parametrize("days,expected", [(30, Decision.APPROVE), (31, Decision.REVIEW), (45, Decision.REVIEW),
                                           (46, Decision.REJECT), (None, Decision.REVIEW)])
def test_delivery_bands(days, expected):
    assert run_rules(good_extraction(delivery_days=days))[0] == expected


@pytest.mark.parametrize("lo,hi,expected", [(30, 30, Decision.APPROVE), (60, 60, Decision.APPROVE),
                                            (29, 29, Decision.REVIEW), (61, 61, Decision.REVIEW),
                                            (30, 45, Decision.REVIEW), (None, None, Decision.REVIEW)])
def test_payment_days(lo, hi, expected):
    assert run_rules(good_extraction(payment_days_min=lo, payment_days_max=hi))[0] == expected


def test_validity_below_30_days():
    assert run_rules(good_extraction(validity_days=29))[0] == Decision.REVIEW


def test_missing_bin_rejects():
    decision, reasons = run_rules(good_extraction(bin=None))
    assert decision == Decision.REJECT and "R4" in rule_ids(reasons)


def test_no_penalty_rejects_and_weak_penalty_needs_person():
    assert run_rules(good_extraction(penalty_present=False, penalty_percent_per_week=None))[0] == Decision.REJECT
    assert run_rules(good_extraction(penalty_percent_per_week=0.25))[0] == Decision.REVIEW


def test_vat_wrong_rate_needs_person():
    ex = good_extraction()
    ex.vat_rate_percent, ex.vat_amount = 10.0, round(ex.subtotal * 0.10, 2)
    ex.total = ex.subtotal + ex.vat_amount
    decision, reasons = run_rules(ex)
    assert decision == Decision.REVIEW and "H5" in rule_ids(reasons)


def test_wrong_total_needs_person():
    ex = good_extraction()
    ex.total += 100
    decision, reasons = run_rules(ex)
    assert decision == Decision.REVIEW and "H6" in rule_ids(reasons)


def test_unknown_item_needs_person():
    ex = good_extraction()
    ex.line_items[0].item_code, ex.line_items[0].description = "Z", "Steel buttons"
    assert run_rules(ex)[0] == Decision.REVIEW


def test_reject_beats_review():
    decision, reasons = run_rules(good_extraction(unit_price=481, advance_percent=50))
    assert decision == Decision.REJECT and rule_ids(reasons) == {"R2"}


# ----------------------------------------------------------------------------- never guess
def test_uncertain_tax_id_is_not_rejected_but_sent_to_person():
    """If we are not sure the BIN is missing, we must not reject -- we ask a person."""
    decision, reasons = run_rules(good_extraction(bin=None), uncertain={"bin"})
    assert decision == Decision.REVIEW


def test_hallucinated_quote_is_caught():
    text = read_pdf_text(config.DATA_DIR / "supplier-pack-01.pdf")
    ex = parse(text)
    ex.payment_quote = "Payment. 10% advance. Balance within 45 days."  # not in the PDF
    uncertain, findings = ground_check(ex, text)
    assert {"advance_percent", "payment_days_min"} <= uncertain
    assert any(f.rule_id == "X1" for f in findings)


def test_hallucinated_tin_is_caught():
    text = read_pdf_text(config.DATA_DIR / "supplier-pack-08.pdf")  # has no TIN/BIN
    ex = parse(text)
    ex.tin, ex.bin = "999999999999", "000999999-0101"
    uncertain, _ = ground_check(ex, text)
    assert {"tin", "bin"} <= uncertain


def test_disagreement_between_readers_goes_to_person():
    text = read_pdf_text(config.DATA_DIR / "supplier-pack-01.pdf")
    parser = parse(text)
    ai = parser.model_copy(deep=True)
    ai.line_items[0].unit_price = 427.0  # AI misread 472 as 427
    merged, uncertain, findings = reconcile(ai, parser)
    assert "line_items[0].unit_price" in uncertain
    decision, _ = decide(findings + check_against_request(merged, PR, uncertain)
                         + check_company_rules(merged, uncertain))
    assert decision == Decision.REVIEW


def test_ai_null_flags_are_normalised_so_they_do_not_fake_a_disagreement():
    """Regression: first live hybrid run, Gemini returned price_includes_vat=None where the
    parser said False. Both mean 'not stated as VAT-inclusive' -> must not be a conflict."""
    text = read_pdf_text(config.DATA_DIR / "supplier-pack-01.pdf")
    parser = parse(text)
    ai = parser.model_copy(deep=True)
    ai.line_items[0].price_includes_vat = None
    _, uncertain, _ = reconcile(ai_reader.normalise_flags(ai), parser)
    assert not uncertain


def test_ai_only_mode_with_ai_down_never_rejects_on_empty_data(monkeypatch):
    """Regression: live AI-only run with quota exhausted rejected packs for 'missing TIN/BIN'
    although nothing had been read. With no extraction, no rule may run -> person."""
    def boom(text):
        raise ai_reader.AIReaderError("quota exhausted")
    monkeypatch.setattr(ai_reader, "extract", boom)
    for name in ("supplier-pack-01.pdf", "supplier-pack-07.pdf"):
        state = check_document(config.DATA_DIR / name, mode="ai")
        assert state["decision"] == Decision.REVIEW
        assert rule_ids(state["reasons"]) == {"X3"}
        assert not any(s["step"].startswith("6.") for s in state["steps"])  # rules were skipped


def test_backup_provider_is_used_when_primary_fails(monkeypatch):
    """Gemini quota exhausted -> Groq reads the document -> same verified result, provider recorded."""
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("GROQ_API_KEY", "y")
    monkeypatch.delenv("AI_PROVIDERS", raising=False)

    def gemini_down(text):
        raise RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    monkeypatch.setitem(ai_reader.PROVIDERS, "gemini", (gemini_down, lambda: "gemini-test"))
    monkeypatch.setitem(ai_reader.PROVIDERS, "groq", (parse, lambda: "groq:test"))

    state = check_document(config.DATA_DIR / "supplier-pack-01.pdf", mode="hybrid")
    assert state["decision"] == Decision.APPROVE
    assert state["ai_provider"] == "groq:test"
    assert any(f.rule_id == "X5" for f in state["findings"])


def test_all_providers_down_goes_to_person(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("GROQ_API_KEY", "y")
    monkeypatch.delenv("AI_PROVIDERS", raising=False)

    def down(text):
        raise RuntimeError("503 UNAVAILABLE")
    monkeypatch.setitem(ai_reader.PROVIDERS, "gemini", (down, lambda: "gemini-test"))
    monkeypatch.setitem(ai_reader.PROVIDERS, "groq", (down, lambda: "groq:test"))
    monkeypatch.setattr(ai_reader.time, "sleep", lambda s: None)  # skip backoff in tests

    state = check_document(config.DATA_DIR / "supplier-pack-01.pdf", mode="hybrid")
    assert state["decision"] == Decision.REVIEW and "X3" in rule_ids(state["reasons"])


@pytest.mark.parametrize("message,kind", [
    ("429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier", "daily"),
    ("429 RESOURCE_EXHAUSTED. Please retry in 12.5s.", "rate"),
    ("Error code: 429 - Rate limit reached ... tokens per minute (TPM). Please try again in 7.48s.", "rate"),
    ("Error code: 429 - Rate limit reached ... requests per day (RPD). Please try again in 1m30s.", "daily"),
    ("404 NOT_FOUND. This model is no longer available", "fatal"),
    ("503 UNAVAILABLE high demand", "transient"),
])
def test_error_classification(message, kind):
    assert ai_reader._classify(RuntimeError(message))[0] == kind


def test_rate_limit_wait_uses_the_providers_retry_after():
    kind, wait = ai_reader._classify(RuntimeError("Rate limit reached (TPM). Please try again in 7.5s."))
    assert kind == "rate" and 8 <= wait <= 9


# ----------------------------------------------------------------------------- human review
from datetime import datetime as _dt  # noqa: E402

from supplier_checker import reviews  # noqa: E402

REVIEW = Decision.REVIEW


def test_unreviewed_document_keeps_system_decision(tmp_path):
    fd = reviews.final_decision("supplier-pack-04.pdf", REVIEW, reviews.load_reviews(tmp_path / "log.jsonl"))
    assert fd.decision == REVIEW and fd.decided_by == "system" and not fd.by_person


def test_reviewer_decision_becomes_final_and_is_attributed(tmp_path):
    log = tmp_path / "log.jsonl"
    reviews.add_review("supplier-pack-04.pdf", REVIEW, Decision.APPROVE, "Rahim", "2.3% over is fine", path=log)
    fd = reviews.final_decision("supplier-pack-04.pdf", REVIEW, reviews.load_reviews(log))
    assert fd.decision == Decision.APPROVE and fd.decided_by == "Rahim" and fd.system == REVIEW
    assert fd.review.note == "2.3% over is fine"


def test_changed_review_keeps_history_and_latest_wins(tmp_path):
    log = tmp_path / "log.jsonl"
    reviews.add_review("supplier-pack-09.pdf", REVIEW, Decision.APPROVE, "Rahim", path=log, now=_dt(2026, 11, 3, 9))
    reviews.add_review("supplier-pack-09.pdf", REVIEW, Decision.REJECT, "Karim", "line total wrong", path=log,
                       now=_dt(2026, 11, 3, 10))
    history = reviews.load_reviews(log)
    assert len(history) == 2                                   # nothing is overwritten
    fd = reviews.final_decision("supplier-pack-09.pdf", REVIEW, history)
    assert fd.decision == Decision.REJECT and fd.decided_by == "Karim"


def test_review_does_not_override_a_different_system_result(tmp_path):
    """A review made when the system said 'Needs a person' must not silently override a later
    re-check where the system says Reject: new evidence needs a new review."""
    log = tmp_path / "log.jsonl"
    reviews.add_review("supplier-pack-04.pdf", REVIEW, Decision.APPROVE, "Rahim", path=log)
    fd = reviews.final_decision("supplier-pack-04.pdf", Decision.REJECT, reviews.load_reviews(log))
    assert fd.decision == Decision.REJECT and fd.decided_by == "system"


def test_review_requires_name_and_a_real_decision(tmp_path):
    with pytest.raises(ValueError):
        reviews.add_review("x.pdf", REVIEW, Decision.APPROVE, "   ", path=tmp_path / "l.jsonl")
    with pytest.raises(ValueError):
        reviews.add_review("x.pdf", REVIEW, Decision.REVIEW, "Rahim", path=tmp_path / "l.jsonl")


def test_old_or_broken_log_lines_do_not_crash(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text('{"time":"2026-11-02T21:00:00","document":"a.pdf","system":"Needs a person to check",'
                   '"reviewer":"Approve","note":""}\nnot json\n', encoding="utf-8")
    history = reviews.load_reviews(log)
    assert len(history) == 1 and history[0].reviewer_name == "unknown"
