"""Steps: compare with the purchase request, check company rules, decide.

Everything here is plain, deterministic Python: same input -> same answer.
Rule IDs follow `company-rules.md`:
  R1..R5  -> Reject rules
  H1..H7  -> Needs-a-person-to-check rules
  P1      -> "penalty must be at least 0.5% of order value per week" (Other notes)
  M1..M3  -> matching the quote to the purchase request
  X*      -> extraction / verification problems (see verify.py)

Golden rule: if a value needed by a rule is missing or uncertain, the rule
returns REVIEW ("Needs a person to check"). It never assumes a value.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional

from . import config
from .documents import PurchaseLine
from .schemas import Decision, Extraction, Finding, LineItem, Severity
from .verify import label


def _fmt(n: Optional[float]) -> str:
    if n is None:
        return "not stated"
    return f"{n:,.2f}".rstrip("0").rstrip(".") if n % 1 else f"{n:,.0f}"


def _uncertain_review(rule_id: str, check: str, fields: list[str], uncertain: set[str],
                      evidence: Optional[str] = None) -> Optional[Finding]:
    hit = [f for f in fields if f in uncertain or f.split(".")[0] in uncertain]
    if not hit:
        return None
    names = ", ".join(sorted({label(f) for f in hit}))
    return Finding(rule_id=rule_id, check=check, severity=Severity.REVIEW,
                   message=f"Cannot check this reliably because the {names} could not be read with confidence.",
                   evidence=evidence)


# --------------------------------------------------------------------------- #
# Step: compare with purchase request
# --------------------------------------------------------------------------- #
def match_item(item: LineItem, pr: dict[str, PurchaseLine]) -> tuple[Optional[PurchaseLine], list[Finding]]:
    findings: list[Finding] = []
    code = (item.item_code or "").strip().upper()
    line = pr.get(code)

    def similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    if line is None and item.description:
        best = max(pr.values(), key=lambda l: similarity(item.description or "", l.description))
        if similarity(item.description, best.description) >= config.DESCRIPTION_MATCH_MIN:
            line = best
            findings.append(Finding(
                rule_id="M1", check="Item matches purchase request", severity=Severity.INFO,
                message=f"No item code on the quote; matched to item {best.item} by description.",
                evidence=item.quote))
    if line is None:
        findings.append(Finding(
            rule_id="M1", check="Item matches purchase request", severity=Severity.REVIEW,
            message=f"Could not match quoted item '{item.item_code or ''} {item.description or ''}'"
                    " to any line of the purchase request.",
            evidence=item.quote))
        return None, findings

    sim = similarity(item.description or "", line.description)
    if sim < config.DESCRIPTION_MATCH_MIN:
        findings.append(Finding(
            rule_id="M2", check="Item matches purchase request", severity=Severity.REVIEW,
            message=f"Item code {line.item} matches, but the description '{item.description}' does not look "
                    f"like the requested '{line.description}'.",
            evidence=item.quote))
    else:
        findings.append(Finding(
            rule_id="M1", check="Item matches purchase request", severity=Severity.PASS,
            message=f"Item {line.item} ({line.description}) is on purchase request {line.pr_number}.",
            evidence=item.quote))
    return line, findings


def check_against_request(ex: Extraction, pr: dict[str, PurchaseLine], uncertain: set[str]) -> list[Finding]:
    findings: list[Finding] = []

    pr_numbers = {l.pr_number for l in pr.values()}
    if "pr_reference" in uncertain:
        pass  # already reported by verify step
    elif ex.pr_reference and ex.pr_reference not in pr_numbers:
        findings.append(Finding(
            rule_id="M3", check="Purchase request reference", severity=Severity.REVIEW,
            message=f"Quote refers to {ex.pr_reference}, not to {', '.join(sorted(pr_numbers))}."))

    if "line_items" in uncertain:
        findings.append(Finding(
            rule_id="M1", check="Item matches purchase request", severity=Severity.REVIEW,
            message="The item lines could not be read with confidence, so price and quantity cannot be checked."))
        return findings
    if not ex.line_items:
        findings.append(Finding(
            rule_id="M1", check="Item matches purchase request", severity=Severity.REVIEW,
            message="No item lines were found in the quotation."))
        return findings

    for i, item in enumerate(ex.line_items):
        f = lambda name: f"line_items[{i}].{name}"  # noqa: E731
        line, match_findings = match_item(item, pr)
        findings += match_findings
        if line is None:
            continue

        # ---- Price: R1 / H1 -------------------------------------------------
        if u := _uncertain_review("R1", "Unit price vs maximum", [f("unit_price"), f("price_includes_vat"), f("item_code")], uncertain, item.quote):
            findings.append(u)
        elif item.unit_price is None:
            findings.append(Finding(rule_id="R1", check="Unit price vs maximum", severity=Severity.REVIEW,
                                    message="Unit price is not stated.", evidence=item.quote))
        else:
            findings.append(_price_finding(item, line))

        # ---- Quantity: H2 ---------------------------------------------------
        if u := _uncertain_review("H2", "Quantity vs request", [f("quantity"), f("item_code")], uncertain, item.quote):
            findings.append(u)
        elif item.quantity is None:
            findings.append(Finding(rule_id="H2", check="Quantity vs request", severity=Severity.REVIEW,
                                    message="Quantity is not stated.", evidence=item.quote))
        else:
            diff_pct = (item.quantity - line.quantity) / line.quantity * 100
            if abs(diff_pct) > config.QTY_TOLERANCE_PCT:
                findings.append(Finding(
                    rule_id="H2", check="Quantity vs request", severity=Severity.REVIEW,
                    message=f"Quantity {_fmt(item.quantity)} {line.unit} differs from the requested "
                            f"{_fmt(line.quantity)} by {diff_pct:+.1f}% (limit ±{config.QTY_TOLERANCE_PCT:g}%).",
                    evidence=item.quote))
            else:
                extra = "" if diff_pct == 0 else f" ({diff_pct:+.1f}%, within ±{config.QTY_TOLERANCE_PCT:g}%)"
                findings.append(Finding(
                    rule_id="H2", check="Quantity vs request", severity=Severity.PASS,
                    message=f"Quantity {_fmt(item.quantity)} matches the requested {_fmt(line.quantity)}{extra}.",
                    evidence=item.quote))
    return findings


def _price_finding(item: LineItem, line: PurchaseLine) -> Finding:
    price, maximum = item.unit_price, line.max_unit_price
    over_pct = (price - maximum) / maximum * 100
    base = dict(check="Unit price vs maximum", evidence=item.quote)

    if item.price_includes_vat:
        # The maximum in the purchase request is assumed to be before VAT.
        ex_vat = price / (1 + config.VAT_RATE_PCT / 100)
        if price <= maximum:
            return Finding(rule_id="R1", severity=Severity.PASS, **base,
                           message=f"Unit price {_fmt(price)} (VAT included) is within the maximum {_fmt(maximum)}, "
                                   "even before taking VAT out.")
        if ex_vat > maximum * (1 + config.PRICE_REJECT_OVER_PCT / 100):
            return Finding(rule_id="R1", severity=Severity.REJECT, **base,
                           message=f"Even without VAT ({_fmt(round(ex_vat, 2))}), the unit price is more than "
                                   f"{config.PRICE_REJECT_OVER_PCT:g}% above the maximum {_fmt(maximum)}.")
        return Finding(rule_id="H1", severity=Severity.REVIEW, **base,
                       message=f"Unit price {_fmt(price)} includes VAT and is above the maximum {_fmt(maximum)}; "
                               "a person must confirm the price before VAT.")

    if over_pct > config.PRICE_REJECT_OVER_PCT:
        return Finding(rule_id="R1", severity=Severity.REJECT, **base,
                       message=f"Unit price {_fmt(price)} is {over_pct:.2f}% above the maximum {_fmt(maximum)} "
                               f"(reject above {config.PRICE_REJECT_OVER_PCT:g}%).")
    if over_pct > 0:
        return Finding(rule_id="H1", severity=Severity.REVIEW, **base,
                       message=f"Unit price {_fmt(price)} is {over_pct:.2f}% above the maximum {_fmt(maximum)} "
                               f"(within the {config.PRICE_REJECT_OVER_PCT:g}% band a person must approve).")
    return Finding(rule_id="R1", severity=Severity.PASS, **base,
                   message=f"Unit price {_fmt(price)} is within the maximum {_fmt(maximum)}.")


# --------------------------------------------------------------------------- #
# Step: check company rules on the terms and conditions
# --------------------------------------------------------------------------- #
def check_company_rules(ex: Extraction, uncertain: set[str]) -> list[Finding]:
    out: list[Finding] = []
    out.append(_advance(ex, uncertain))
    out.append(_payment_days(ex, uncertain))
    out += _penalty(ex, uncertain)
    out.append(_tax_ids(ex, uncertain))
    out.append(_delivery(ex, uncertain))
    out.append(_vat(ex, uncertain))
    out += _arithmetic(ex, uncertain)
    out.append(_validity(ex, uncertain))
    for note in ex.reader_notes:
        out.append(Finding(rule_id="N", check="Reader note", severity=Severity.INFO, message=note))
    return out


def _advance(ex: Extraction, uncertain: set[str]) -> Finding:
    check, q = "Advance payment", ex.payment_quote
    if u := _uncertain_review("R2", check, ["advance_percent"], uncertain, q):
        return u
    if ex.advance_percent is None:
        return Finding(rule_id="H3", check=check, severity=Severity.REVIEW, evidence=q,
                       message="The advance payment percentage is not clear from the payment terms.")
    if ex.advance_percent > config.ADVANCE_MAX_PCT:
        return Finding(rule_id="R2", check=check, severity=Severity.REJECT, evidence=q,
                       message=f"Advance payment is {_fmt(ex.advance_percent)}%, more than the "
                               f"{config.ADVANCE_MAX_PCT:g}% allowed.")
    return Finding(rule_id="R2", check=check, severity=Severity.PASS, evidence=q,
                   message=f"Advance payment is {_fmt(ex.advance_percent)}% (limit {config.ADVANCE_MAX_PCT:g}%).")


def _payment_days(ex: Extraction, uncertain: set[str]) -> Finding:
    check, q = "Payment terms (days after delivery)", ex.payment_quote
    if u := _uncertain_review("H3", check, ["payment_days_min", "payment_days_max"], uncertain, q):
        return u
    lo, hi = ex.payment_days_min, ex.payment_days_max
    window = f"{config.PAYMENT_DAYS_MIN} to {config.PAYMENT_DAYS_MAX} days"
    if lo is None and hi is None:
        return Finding(rule_id="H3", check=check, severity=Severity.REVIEW, evidence=q,
                       message="The number of days to pay after delivery is not stated.")
    lo, hi = lo if lo is not None else hi, hi if hi is not None else lo
    if lo != hi:
        outside = lo < config.PAYMENT_DAYS_MIN or hi > config.PAYMENT_DAYS_MAX
        return Finding(rule_id="H3", check=check, severity=Severity.REVIEW, evidence=q,
                       message=f"Payment terms are unclear: a range of {lo} to {hi} days instead of a fixed term"
                               + (f", and part of it is outside {window}." if outside else "."))
    if not config.PAYMENT_DAYS_MIN <= lo <= config.PAYMENT_DAYS_MAX:
        return Finding(rule_id="H3", check=check, severity=Severity.REVIEW, evidence=q,
                       message=f"Payment is due {lo} days after delivery, outside {window}.")
    return Finding(rule_id="H3", check=check, severity=Severity.PASS, evidence=q,
                   message=f"Payment is due {lo} days after delivery (allowed: {window}).")


def _penalty(ex: Extraction, uncertain: set[str]) -> list[Finding]:
    check, q = "Late-delivery penalty", ex.penalty_quote
    if u := _uncertain_review("R3", check, ["penalty_present"], uncertain, q):
        return [u]
    if ex.penalty_present is False:
        return [Finding(rule_id="R3", check=check, severity=Severity.REJECT,
                        message="The contract has no late-delivery penalty clause.")]
    if ex.penalty_present is None:
        return [Finding(rule_id="R3", check=check, severity=Severity.REVIEW,
                        message="Could not tell whether there is a late-delivery penalty clause.")]

    out = [Finding(rule_id="R3", check=check, severity=Severity.PASS, evidence=q,
                   message="A late-delivery penalty clause is present.")]
    if u := _uncertain_review("P1", "Penalty size", ["penalty_percent_per_week", "penalty_basis_order_value"], uncertain, q):
        return out + [u]
    pct = ex.penalty_percent_per_week
    if pct is None:
        out.append(Finding(rule_id="P1", check="Penalty size", severity=Severity.REVIEW, evidence=q,
                           message="The penalty clause does not state a clear percentage per week."))
    elif pct < config.PENALTY_MIN_PCT_PER_WEEK:
        out.append(Finding(rule_id="P1", check="Penalty size", severity=Severity.REVIEW, evidence=q,
                           message=f"Penalty is {_fmt(pct)}% per week, below the required "
                                   f"{config.PENALTY_MIN_PCT_PER_WEEK:g}%."))
    elif not ex.penalty_basis_order_value:
        out.append(Finding(rule_id="P1", check="Penalty size", severity=Severity.REVIEW, evidence=q,
                           message=f"Penalty is {_fmt(pct)}% per week, but the clause does not say it is a "
                                   "percentage of order value."))
    else:
        out.append(Finding(rule_id="P1", check="Penalty size", severity=Severity.PASS, evidence=q,
                           message=f"Penalty is {_fmt(pct)}% of order value per week "
                                   f"(minimum {config.PENALTY_MIN_PCT_PER_WEEK:g}%)."))
    return out


def _tax_ids(ex: Extraction, uncertain: set[str]) -> Finding:
    check, q = "Supplier TIN and BIN", ex.tax_id_quote
    if u := _uncertain_review("R4", check, ["tin", "bin"], uncertain, q):
        return u
    missing = [n for n, v in (("TIN", ex.tin), ("BIN", ex.bin)) if not v]
    if missing:
        return Finding(rule_id="R4", check=check, severity=Severity.REJECT, evidence=q,
                       message=f"Supplier {' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} missing.")
    return Finding(rule_id="R4", check=check, severity=Severity.PASS, evidence=q,
                   message=f"TIN {ex.tin} and BIN {ex.bin} are shown.")


def _delivery(ex: Extraction, uncertain: set[str]) -> Finding:
    check, q = "Delivery time", ex.delivery_quote
    if u := _uncertain_review("R5", check, ["delivery_days"], uncertain, q):
        return u
    d = ex.delivery_days
    if d is None:
        return Finding(rule_id="H4", check=check, severity=Severity.REVIEW, evidence=q,
                       message="The delivery time is not stated clearly.")
    if d > config.DELIVERY_REJECT_OVER_DAYS:
        return Finding(rule_id="R5", check=check, severity=Severity.REJECT, evidence=q,
                       message=f"Delivery in {d} days is later than the {config.DELIVERY_REJECT_OVER_DAYS}-day limit.")
    if d >= config.DELIVERY_REVIEW_FROM_DAYS:
        return Finding(rule_id="H4", check=check, severity=Severity.REVIEW, evidence=q,
                       message=f"Delivery in {d} days falls in the "
                               f"{config.DELIVERY_REVIEW_FROM_DAYS}-{config.DELIVERY_REJECT_OVER_DAYS} day band.")
    return Finding(rule_id="R5", check=check, severity=Severity.PASS, evidence=q,
                   message=f"Delivery in {d} days (within 30 days).")


def _vat(ex: Extraction, uncertain: set[str]) -> Finding:
    check, q = "VAT shown separately at 15%", ex.totals_quote
    if u := _uncertain_review("H5", check, ["vat_rate_percent", "vat_amount"], uncertain, q):
        return u
    if any(i.price_includes_vat for i in ex.line_items) or ex.vat_rate_percent is None or ex.vat_amount is None:
        return Finding(rule_id="H5", check=check, severity=Severity.REVIEW, evidence=q,
                       message="VAT is not shown as a separate line (prices are VAT-inclusive or VAT is missing).")
    if abs(ex.vat_rate_percent - config.VAT_RATE_PCT) > 1e-9:
        return Finding(rule_id="H5", check=check, severity=Severity.REVIEW, evidence=q,
                       message=f"VAT is shown at {_fmt(ex.vat_rate_percent)}%, not {config.VAT_RATE_PCT:g}%.")
    return Finding(rule_id="H5", check=check, severity=Severity.PASS, evidence=q,
                   message=f"VAT is shown separately at {config.VAT_RATE_PCT:g}%.")


def _arithmetic(ex: Extraction, uncertain: set[str]) -> list[Finding]:
    check = "Numbers add up"
    fields = ["subtotal", "vat_amount", "total", "line_items"] + [
        f"line_items[{i}].{n}" for i in range(len(ex.line_items)) for n in ("quantity", "unit_price", "amount")]
    if u := _uncertain_review("H6", check, fields, uncertain, ex.totals_quote):
        return [u]

    tol = config.MONEY_TOLERANCE
    problems: list[tuple[str, Optional[str]]] = []
    for item in ex.line_items:
        if None in (item.quantity, item.unit_price, item.amount):
            problems.append(("An item line is missing its quantity, price or amount, so it cannot be checked.", item.quote))
            continue
        expected = round(item.quantity * item.unit_price, 2)
        if abs(expected - item.amount) > tol:
            problems.append((f"Line amount {_fmt(item.amount)} should be {_fmt(item.quantity)} × "
                             f"{_fmt(item.unit_price)} = {_fmt(expected)} (difference {_fmt(round(item.amount - expected, 2))}).",
                             item.quote))
    line_sum = round(sum(i.amount or 0 for i in ex.line_items), 2)
    vat_inclusive = any(i.price_includes_vat for i in ex.line_items)

    if vat_inclusive and ex.subtotal is None and ex.vat_amount is None:
        if ex.total is None or abs(ex.total - line_sum) > tol:
            problems.append((f"Total {_fmt(ex.total)} does not equal the sum of lines {_fmt(line_sum)}.", ex.totals_quote))
    else:
        if ex.subtotal is None:
            problems.append(("No subtotal is shown, so the totals cannot be checked.", ex.totals_quote))
        else:
            if abs(ex.subtotal - line_sum) > tol:
                problems.append((f"Subtotal {_fmt(ex.subtotal)} does not equal the sum of lines {_fmt(line_sum)}.", ex.totals_quote))
            if ex.vat_amount is not None and ex.vat_rate_percent is not None:
                exp_vat = round(ex.subtotal * ex.vat_rate_percent / 100, 2)
                if abs(exp_vat - ex.vat_amount) > tol:
                    problems.append((f"VAT {_fmt(ex.vat_amount)} should be {_fmt(ex.vat_rate_percent)}% of "
                                     f"{_fmt(ex.subtotal)} = {_fmt(exp_vat)}.", ex.totals_quote))
            exp_total = round(ex.subtotal + (ex.vat_amount or 0), 2)
            if ex.total is None or abs(exp_total - ex.total) > tol:
                problems.append((f"Total {_fmt(ex.total)} should be {_fmt(exp_total)}.", ex.totals_quote))

    if problems:
        return [Finding(rule_id="H6", check=check, severity=Severity.REVIEW, message=m, evidence=e)
                for m, e in problems]
    return [Finding(rule_id="H6", check=check, severity=Severity.PASS, evidence=ex.totals_quote,
                    message="Line amounts, subtotal, VAT and total all add up.")]


def _validity(ex: Extraction, uncertain: set[str]) -> Finding:
    check, q = "Quotation validity", ex.validity_quote
    if u := _uncertain_review("H7", check, ["validity_days"], uncertain, q):
        return u
    if ex.validity_days is None:
        return Finding(rule_id="H7", check=check, severity=Severity.REVIEW, evidence=q,
                       message="The quotation validity period is not stated.")
    if ex.validity_days < config.VALIDITY_MIN_DAYS:
        return Finding(rule_id="H7", check=check, severity=Severity.REVIEW, evidence=q,
                       message=f"Quotation is valid for only {ex.validity_days} days (minimum {config.VALIDITY_MIN_DAYS}).")
    return Finding(rule_id="H7", check=check, severity=Severity.PASS, evidence=q,
                   message=f"Quotation is valid for {ex.validity_days} days.")


# --------------------------------------------------------------------------- #
# Step: decide
# --------------------------------------------------------------------------- #
def decide(findings: list[Finding]) -> tuple[Decision, list[Finding]]:
    """Reject beats Needs-a-person beats Approve. Returns the decision and the findings that caused it."""
    rejects = [f for f in findings if f.severity == Severity.REJECT]
    reviews = [f for f in findings if f.severity == Severity.REVIEW]
    if rejects:
        return Decision.REJECT, rejects
    if reviews:
        return Decision.REVIEW, reviews
    return Decision.APPROVE, []
