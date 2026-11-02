"""Step: verify what the readers extracted, before any rule is applied.

Two independent safety nets against "the AI made something up":

1. **Grounding** - every quote the AI returns must appear word-for-word in the
   PDF text, and TIN/BIN numbers must literally appear in the PDF. If not, the
   fields that depend on that quote are marked *uncertain*.
2. **Agreement** - in hybrid mode, the AI reader and the rule-based parser read
   the same document independently. Any field where they disagree is marked
   *uncertain*.

Uncertain fields are never used to approve or reject. The rule engine turns
them into "Needs a person to check".
"""
from __future__ import annotations

from typing import Any, Optional

from .documents import normalise, quote_in_text
from .schemas import Extraction, Finding, Severity

# Which extracted fields depend on which quote.
QUOTE_FIELDS = {
    "payment_quote": ["advance_percent", "payment_days_min", "payment_days_max"],
    "delivery_quote": ["delivery_days"],
    "penalty_quote": ["penalty_present", "penalty_percent_per_week", "penalty_basis_order_value"],
    "validity_quote": ["validity_days"],
}

SCALAR_FIELDS = [
    "pr_reference",
    "subtotal", "vat_rate_percent", "vat_amount", "total",
    "tin", "bin",
    "advance_percent", "payment_days_min", "payment_days_max",
    "delivery_days",
    "penalty_present", "penalty_percent_per_week", "penalty_basis_order_value",
    "validity_days",
]
LINE_FIELDS = ["item_code", "quantity", "unit_price", "amount", "price_includes_vat"]

LABELS = {
    "pr_reference": "purchase request reference",
    "subtotal": "subtotal", "vat_rate_percent": "VAT rate", "vat_amount": "VAT amount", "total": "total",
    "tin": "TIN", "bin": "BIN",
    "advance_percent": "advance payment %", "payment_days_min": "payment days",
    "payment_days_max": "payment days (upper)", "delivery_days": "delivery days",
    "penalty_present": "late-delivery penalty clause", "penalty_percent_per_week": "penalty % per week",
    "penalty_basis_order_value": "penalty basis (order value)", "validity_days": "validity days",
    "item_code": "item code", "quantity": "quantity", "unit_price": "unit price", "amount": "line amount",
    "price_includes_vat": "price includes VAT",
}


def label(field: str) -> str:
    base = field.split(".")[-1]
    return LABELS.get(base, base)


def _same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 0.005
    return normalise(str(a)).replace(" ", "") == normalise(str(b)).replace(" ", "")


def ground_check(ex: Extraction, text: str, reader: str = "AI") -> tuple[set[str], list[Finding]]:
    """Check that the reader's quotes and IDs really exist in the document."""
    uncertain: set[str] = set()
    findings: list[Finding] = []

    for quote_field, fields in QUOTE_FIELDS.items():
        quote = getattr(ex, quote_field)
        has_values = any(getattr(ex, f) not in (None, False) for f in fields)
        if quote and not quote_in_text(quote, text):
            uncertain.update(fields)
            findings.append(Finding(
                rule_id="X1", check="Quote is really in the document", severity=Severity.REVIEW,
                message=f"The {reader} reader quoted text that is not in the document for "
                        f"{label(fields[0])}; its values cannot be trusted.",
                evidence=quote,
            ))
        elif has_values and not quote:
            uncertain.update(fields)
            findings.append(Finding(
                rule_id="X1", check="Quote is really in the document", severity=Severity.REVIEW,
                message=f"The {reader} reader gave {label(fields[0])} without quoting where it came from.",
            ))

    for field in ("tin", "bin"):
        value = getattr(ex, field)
        if value and normalise(value) not in normalise(text):
            uncertain.add(field)
            findings.append(Finding(
                rule_id="X1", check="Quote is really in the document", severity=Severity.REVIEW,
                message=f"The {reader} reader returned {field.upper()} '{value}', which does not appear in the document.",
            ))

    if ex.totals_quote:
        for line in ex.totals_quote.splitlines():
            if line.strip() and not quote_in_text(line, text):
                uncertain.update({"subtotal", "vat_rate_percent", "vat_amount", "total"})
                findings.append(Finding(
                    rule_id="X1", check="Quote is really in the document", severity=Severity.REVIEW,
                    message=f"The {reader} reader quoted a totals line that is not in the document.",
                    evidence=line,
                ))
                break

    for i, item in enumerate(ex.line_items):
        if item.quote and not quote_in_text(item.quote, text):
            uncertain.update(f"line_items[{i}].{f}" for f in LINE_FIELDS)
            findings.append(Finding(
                rule_id="X1", check="Quote is really in the document", severity=Severity.REVIEW,
                message=f"The {reader} reader quoted an item line that is not in the document.",
                evidence=item.quote,
            ))
    return uncertain, findings


def reconcile(ai: Extraction, parser: Extraction) -> tuple[Extraction, set[str], list[Finding]]:
    """Merge two readings. Agreeing fields are trusted; disagreeing ones become uncertain.

    The AI reading is the base (it has better quotes/notes); disagreements are
    flagged, never silently resolved.
    """
    merged = ai.model_copy(deep=True)
    uncertain: set[str] = set()
    findings: list[Finding] = []

    def conflict(field: str, a: Any, p: Any, evidence: Optional[str] = None) -> None:
        uncertain.add(field)
        findings.append(Finding(
            rule_id="X2", check="AI and parser agree", severity=Severity.REVIEW,
            message=f"The AI reader and the rule-based parser disagree on {label(field)} "
                    f"(AI: {a!r}, parser: {p!r}). A person should check which is right.",
            evidence=evidence,
        ))

    for field in SCALAR_FIELDS:
        a, p = getattr(ai, field), getattr(parser, field)
        if not _same(a, p):
            conflict(field, a, p, getattr(ai, _quote_for(field), None) or getattr(parser, _quote_for(field), None))
        elif a is None and p is not None:
            setattr(merged, field, p)

    if len(ai.line_items) != len(parser.line_items):
        uncertain.add("line_items")
        findings.append(Finding(
            rule_id="X2", check="AI and parser agree", severity=Severity.REVIEW,
            message=f"The AI reader found {len(ai.line_items)} item line(s) but the parser found "
                    f"{len(parser.line_items)}.",
        ))
    else:
        for i, (a_item, p_item) in enumerate(zip(ai.line_items, parser.line_items)):
            for f in LINE_FIELDS:
                av, pv = getattr(a_item, f), getattr(p_item, f)
                if not _same(av, pv):
                    conflict(f"line_items[{i}].{f}", av, pv, a_item.quote or p_item.quote)

    # Fill missing quotes from the parser so evidence is always shown.
    for q in ("payment_quote", "delivery_quote", "penalty_quote", "validity_quote", "tax_id_quote", "totals_quote"):
        if not getattr(merged, q):
            setattr(merged, q, getattr(parser, q))
    merged.reader_notes = list(dict.fromkeys(ai.reader_notes + parser.reader_notes))
    return merged, uncertain, findings


def _quote_for(field: str) -> str:
    for quote_field, fields in QUOTE_FIELDS.items():
        if field in fields:
            return quote_field
    if field in ("tin", "bin"):
        return "tax_id_quote"
    if field in ("subtotal", "vat_rate_percent", "vat_amount", "total"):
        return "totals_quote"
    return "_none"


