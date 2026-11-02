"""Data models shared by every step of the pipeline.

`Extraction` is what a "reader" (the Gemini model or the rule-based parser)
returns after reading one supplier pack. It holds raw facts plus the exact text
each fact came from. It never holds decisions: decisions are made later in
plain Python by `rules.py`, so they are predictable and testable.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    item_code: Optional[str] = Field(None, description="Item letter/code in the 'Item' column, e.g. 'A'.")
    description: Optional[str] = Field(None, description="Item description exactly as written.")
    quantity: Optional[float] = Field(None, description="Quantity as a number, without thousands separators.")
    unit: Optional[str] = Field(None, description="Unit of measure, e.g. 'metre', 'piece', 'cone'.")
    unit_price: Optional[float] = Field(None, description="Unit price in BDT as written in the document.")
    amount: Optional[float] = Field(None, description="Line amount/total in BDT as written in the document.")
    price_includes_vat: Optional[bool] = Field(
        None, description="True only if the document says the unit price already includes VAT/taxes."
    )
    quote: Optional[str] = Field(None, description="The exact line of text this item was read from.")


class Extraction(BaseModel):
    """Facts read from one supplier pack. Use null for anything not stated."""

    supplier_name: Optional[str] = Field(None, description="Name of the supplier company issuing the quotation.")
    quotation_no: Optional[str] = None
    quotation_date: Optional[str] = Field(None, description="Quotation date as written, e.g. 2026-10-21.")
    pr_reference: Optional[str] = Field(None, description="Purchase request reference, e.g. PR-2026-114.")
    line_items: list[LineItem] = Field(default_factory=list)

    subtotal: Optional[float] = Field(None, description="Subtotal before VAT, if shown.")
    vat_rate_percent: Optional[float] = Field(None, description="VAT rate shown as a separate line, e.g. 15. Null if VAT is not shown separately.")
    vat_amount: Optional[float] = Field(None, description="VAT amount shown as a separate line. Null if not shown separately.")
    total: Optional[float] = Field(None, description="Grand total.")
    totals_quote: Optional[str] = Field(None, description="Exact text of the subtotal/VAT/total lines.")

    tin: Optional[str] = Field(None, description="Supplier TIN number. Null if not printed in the document.")
    bin: Optional[str] = Field(None, description="Supplier BIN number. Null if not printed in the document.")
    tax_id_quote: Optional[str] = Field(None, description="Exact text showing the TIN/BIN, or the text that refers to them.")

    advance_percent: Optional[float] = Field(None, description="Advance payment percent. 0 if the document says no advance. Null if not stated.")
    payment_days_min: Optional[int] = Field(None, description="Days after delivery the balance is due. If a range like '30 to 90 days', the lower number.")
    payment_days_max: Optional[int] = Field(None, description="Same as payment_days_min for a single number; the upper number for a range.")
    payment_quote: Optional[str] = Field(None, description="Exact text of the payment clause.")

    delivery_days: Optional[int] = Field(None, description="Days from purchase order to delivery. Convert weeks to days (1 week = 7 days).")
    delivery_quote: Optional[str] = Field(None, description="Exact text of the delivery clause.")

    penalty_present: Optional[bool] = Field(None, description="True if there is a late-delivery penalty clause, False if there is none.")
    penalty_percent_per_week: Optional[float] = Field(None, description="Penalty percent per week of delay.")
    penalty_basis_order_value: Optional[bool] = Field(None, description="True if the penalty is stated as a percent of order value.")
    penalty_quote: Optional[str] = Field(None, description="Exact text of the late-delivery penalty clause.")

    validity_days: Optional[int] = Field(None, description="Number of days the quotation is valid.")
    validity_quote: Optional[str] = Field(None, description="Exact text of the validity clause.")

    reader_notes: list[str] = Field(
        default_factory=list,
        description="Anything ambiguous, contradictory or unreadable that a human should know about.",
    )


class Severity(str, Enum):
    REJECT = "REJECT"
    REVIEW = "REVIEW"  # needs a person to check
    PASS = "PASS"
    INFO = "INFO"  # shown to the reviewer, never changes the decision


class Decision(str, Enum):
    APPROVE = "Approve"
    REJECT = "Reject"
    REVIEW = "Needs a person to check"


class Finding(BaseModel):
    """One check result, always tied to a rule and to the text that supports it."""

    rule_id: str  # e.g. "R1" (reject rule 1), "H3" (human-check rule 3), "X2" (extraction check)
    check: str  # short name, e.g. "Unit price vs maximum"
    severity: Severity
    message: str
    evidence: Optional[str] = None  # exact quote from the document
