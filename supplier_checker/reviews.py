"""Human review: record what a person decided, and work out each document's final decision.

Every review is appended to a JSON-lines file and never edited or deleted, so the
full history of who decided what, and any later change of mind, is kept.

Final decision rules:
  * No review          -> the system's decision stands ("decided by: system").
  * Reviewed           -> the reviewer's latest decision for that document.
  * A review only applies to the system result it was made for. If the document is
    re-checked and the system now answers differently, the old review is kept in the
    history but no longer overrides anything, and the new result needs its own review.
    This stops a stale human decision from silently overriding new evidence.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from . import config
from .schemas import Decision

REVIEW_LOG = config.RESULTS_DIR / "review_log.jsonl"


@dataclass(frozen=True)
class Review:
    time: str              # ISO timestamp, e.g. 2026-11-03T10:15:00
    document: str          # file name, e.g. supplier-pack-09.pdf
    system: str            # system decision the review was made for, e.g. "Needs a person to check"
    reviewer: str          # reviewer's decision: "Approve" or "Reject"
    reviewer_name: str     # who decided
    note: str = ""

    @property
    def decision(self) -> Decision:
        return Decision(self.reviewer)


def add_review(document: str, system: Decision, decision: Decision, reviewer_name: str, note: str = "",
               path: Path = REVIEW_LOG, now: Optional[datetime] = None) -> Review:
    """Append one review. Raises ValueError for an empty name or a decision a person cannot make."""
    if decision not in (Decision.APPROVE, Decision.REJECT):
        raise ValueError("A reviewer can only Approve or Reject.")
    if not reviewer_name.strip():
        raise ValueError("Enter the reviewer's name.")
    review = Review(time=(now or datetime.now()).isoformat(timespec="seconds"), document=document,
                    system=system.value, reviewer=decision.value, reviewer_name=reviewer_name.strip(),
                    note=note.strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(review), ensure_ascii=False) + "\n")
    return review


def load_reviews(path: Path = REVIEW_LOG) -> list[Review]:
    """All reviews, oldest first. Unreadable lines are skipped, not fatal."""
    if not path.exists():
        return []
    reviews: list[Review] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            reviews.append(Review(time=d["time"], document=d["document"], system=d["system"],
                                  reviewer=d["reviewer"], reviewer_name=d.get("reviewer_name", "unknown"),
                                  note=d.get("note", "")))
        except (ValueError, KeyError, TypeError):
            continue
    return reviews


def latest_review(document: str, system: Decision, reviews: Iterable[Review]) -> Optional[Review]:
    """The most recent review of `document` that was made for this same system result."""
    matching = [r for r in reviews if r.document == document and r.system == system.value]
    return matching[-1] if matching else None


@dataclass(frozen=True)
class FinalDecision:
    decision: Decision
    decided_by: str                 # "system" or the reviewer's name
    system: Decision
    review: Optional[Review] = None

    @property
    def by_person(self) -> bool:
        return self.review is not None


def final_decision(document: str, system: Decision, reviews: Iterable[Review]) -> FinalDecision:
    review = latest_review(document, system, reviews)
    if review is None:
        return FinalDecision(decision=system, decided_by="system", system=system)
    return FinalDecision(decision=review.decision, decided_by=review.reviewer_name, system=system, review=review)
