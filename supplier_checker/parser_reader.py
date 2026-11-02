"""Reader #2: a rule-based (regular expression) parser.

Why have it at all, when Gemini reads the document?
  * It is an independent second opinion. If the AI and the parser disagree on a
    number that matters, the pipeline does not pick one -- it asks a person.
  * It lets the project run with no API key (``--mode parser``), so reviewers
    can reproduce results offline.

It is deliberately strict: if a phrase does not match a pattern it knows, the
field is left empty (None) rather than guessed.
"""
from __future__ import annotations

import re
from typing import Optional

from .schemas import Extraction, LineItem

NUM = r"[\d,]+(?:\.\d+)?"


def _f(value: Optional[str]) -> Optional[float]:
    return float(value.replace(",", "")) if value else None


def _search(pattern: str, text: str, flags: int = 0) -> Optional[re.Match]:
    return re.search(pattern, text, flags)


def _clauses(text: str) -> dict[str, str]:
    """Split the 'TERMS AND CONDITIONS' section into {title_lower: clause_text}."""
    terms = text.split("TERMS AND CONDITIONS", 1)
    body = terms[1] if len(terms) == 2 else text
    body = re.split(r"\n(?:For |Authorised signatory)", body)[0]
    clauses: dict[str, str] = {}
    for m in re.finditer(r"^\d+\.\s+([A-Za-z ]+)\.\s+(.*?)(?=^\d+\.\s+[A-Za-z ]+\.|\Z)", body, re.M | re.S):
        clause = re.sub(r"\s+", " ", f"{m.group(1)}. {m.group(2)}").strip()
        clauses[m.group(1).strip().lower()] = clause
    return clauses


def _find_clause(clauses: dict[str, str], *keywords: str) -> Optional[str]:
    for title, clause in clauses.items():
        if any(k in title for k in keywords):
            return clause
    for clause in clauses.values():  # fall back to searching clause bodies
        if any(k in clause.lower() for k in keywords):
            return clause
    return None


def parse(text: str) -> Extraction:
    ex = Extraction()
    notes: list[str] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # --- Header ---------------------------------------------------------------
    ex.supplier_name = lines[0] if lines else None
    if m := _search(r"Quotation no\.\s*(\S+)", text):
        ex.quotation_no = m.group(1)
    if m := _search(r"\bDate\s+(\d{4}-\d{2}-\d{2})", text):
        ex.quotation_date = m.group(1)
    if m := _search(r"Reference\s+(PR-[\w-]+)", text):
        ex.pr_reference = m.group(1)

    # --- Line items -------------------------------------------------------------
    header = _search(r"^Item\s+Description.*$", text, re.M)
    vat_included = bool(header and re.search(r"VAT included|incl", header.group(0), re.I))
    item_re = re.compile(
        rf"^([A-Z])\s+(.+?)\s+({NUM})\s+([A-Za-z]+)\s+({NUM})\s+({NUM})\s*$", re.M
    )
    for m in item_re.finditer(text):
        ex.line_items.append(
            LineItem(
                item_code=m.group(1),
                description=m.group(2).strip(),
                quantity=_f(m.group(3)),
                unit=m.group(4),
                unit_price=_f(m.group(5)),
                amount=_f(m.group(6)),
                price_includes_vat=vat_included,
                quote=m.group(0).strip(),
            )
        )
    if not ex.line_items:
        notes.append("Parser could not find any item line in the price table.")

    # --- Totals ---------------------------------------------------------------
    totals_lines = []
    if m := _search(rf"^Subtotal\s+({NUM})\s*$", text, re.M):
        ex.subtotal = _f(m.group(1))
        totals_lines.append(m.group(0).strip())
    if m := _search(rf"^VAT\s+({NUM})\s*%\s+({NUM})\s*$", text, re.M):
        ex.vat_rate_percent = _f(m.group(1))
        ex.vat_amount = _f(m.group(2))
        totals_lines.append(m.group(0).strip())
    if m := _search(rf"^Total\b.*?({NUM})\s*$", text, re.M):
        ex.total = _f(m.group(1))
        totals_lines.append(m.group(0).strip())
    ex.totals_quote = "\n".join(totals_lines) or None

    # --- Tax registration -------------------------------------------------------
    if m := _search(r"\bTIN\s*:?\s*([\d][\d-]{5,})", text):
        ex.tin = m.group(1)
    if m := _search(r"\bBIN\s*:?\s*([\d][\d-]{5,})", text):
        ex.bin = m.group(1)
    if m := _search(r"^.*\b(?:TIN|BIN|registration)\b.*$", text, re.M | re.I):
        ex.tax_id_quote = m.group(0).strip()

    # --- Terms and conditions -----------------------------------------------------
    clauses = _clauses(text)

    payment = _find_clause(clauses, "payment")
    ex.payment_quote = payment
    if payment:
        if re.search(r"\bno advance\b", payment, re.I):
            ex.advance_percent = 0.0
        advances = {float(a) for a in re.findall(r"(\d+(?:\.\d+)?)\s*%\s*advance", payment, re.I)}
        if len(advances) == 1:
            ex.advance_percent = advances.pop()
        elif len(advances) > 1:
            notes.append(f"Payment clause states different advance percentages: {sorted(advances)}.")
        if m := re.search(r"(\d+)\s*(?:to|-|–)\s*(\d+)\s*days", payment, re.I):
            ex.payment_days_min, ex.payment_days_max = int(m.group(1)), int(m.group(2))
        else:
            days = {int(d) for d in re.findall(r"(\d+)\s*days", payment, re.I)}
            if len(days) == 1:
                ex.payment_days_min = ex.payment_days_max = days.pop()
            elif len(days) > 1:
                notes.append(f"Payment clause mentions several day counts: {sorted(days)}.")

    delivery = _find_clause(clauses, "delivery")
    # The 'Delay' clause also mentions delivery; prefer a clause titled Delivery.
    if "delivery" in clauses:
        delivery = clauses["delivery"]
    ex.delivery_quote = delivery
    if delivery:
        if m := re.search(r"(\d+)\s*(days?|weeks?)", delivery, re.I):
            n = int(m.group(1))
            ex.delivery_days = n * 7 if m.group(2).lower().startswith("week") else n

    penalty = clauses.get("delay") or next(
        (c for c in clauses.values() if re.search(r"penalt|late delivery", c, re.I)), None
    )
    ex.penalty_quote = penalty
    ex.penalty_present = penalty is not None
    if penalty:
        if m := re.search(r"(\d+(?:\.\d+)?)\s*%", penalty):
            ex.penalty_percent_per_week = float(m.group(1))
        ex.penalty_basis_order_value = bool(re.search(r"order value", penalty, re.I))

    validity = _find_clause(clauses, "validity", "valid")
    ex.validity_quote = validity
    if validity and (m := re.search(r"valid for\s+(\d+)\s*days", validity, re.I)):
        ex.validity_days = int(m.group(1))

    ex.reader_notes = notes
    return ex
