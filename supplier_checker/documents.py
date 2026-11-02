"""Loading inputs: supplier PDFs and the purchase request CSV."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Union

import pdfplumber

from . import config


class DocumentReadError(Exception):
    """The PDF could not be opened or contains no readable text (e.g. a scan)."""


def read_pdf_text(source: Union[str, Path, BinaryIO]) -> str:
    """Return the text of every page. Raises DocumentReadError if there is none."""
    try:
        with pdfplumber.open(source) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:  # corrupt / not a PDF / encrypted
        raise DocumentReadError(f"Could not open PDF: {exc}") from exc
    text = "\n".join(pages).strip()
    if len(text) < 50:
        raise DocumentReadError(
            "The PDF has no readable text (it may be a scanned image). A person must read it."
        )
    return text


def normalise(text: str) -> str:
    """Lower-case and collapse whitespace so quotes can be matched across line breaks."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def quote_in_text(quote: str | None, text: str) -> bool:
    """True if `quote` appears word-for-word (ignoring spacing/case) in the document."""
    if not quote:
        return False
    return normalise(quote) in normalise(text)


@dataclass(frozen=True)
class PurchaseLine:
    pr_number: str
    item: str
    description: str
    unit: str
    quantity: float
    max_unit_price: float


def _num(value: str) -> float:
    return float(value.replace(",", "").strip())


def load_purchase_request(path: Path = config.PURCHASE_REQUEST_CSV) -> dict[str, PurchaseLine]:
    """Map item code -> purchase request line."""
    lines: dict[str, PurchaseLine] = {}
    # utf-8-sig strips the BOM the sample CSV starts with.
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            line = PurchaseLine(
                pr_number=row["PR number"].strip(),
                item=row["Item"].strip().upper(),
                description=row["Description"].strip(),
                unit=row["Unit"].strip(),
                quantity=_num(row["Quantity requested"]),
                max_unit_price=_num(row["Maximum unit price (BDT)"]),
            )
            lines[line.item] = line
    return lines
