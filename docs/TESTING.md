# Testing

## 1. Ground truth
Before writing any code, I read all 10 packs and applied `company-rules.md` by hand. The answers are in
[`data/expected-decisions.csv`](../data/expected-decisions.csv), with the rule IDs and the reasoning.

| Pack | Key facts | Expected |
|---|---|---|
| 01 | 472 ≤ 480, qty OK, 10% adv, 45 d pay, 24 d delivery, 1% penalty, VAT 15%, sums OK, valid 45 d | Approve |
| 02 | 36 ≤ 38, qty OK, no adv, 30 d, 21 d, 0.75%, VAT OK, valid 30 d | Approve |
| 03 | 229 vs 210 → +9.05% | Reject (R1) |
| 04 | 6.65 vs 6.50 → +2.31% | Person (H1) |
| 05 | 40% advance | Reject (R2) |
| 06 | No *Delay* clause | Reject (R3) |
| 07 | 16,500 vs 20,000 → −17.5% | Person (H2) |
| 08 | "Supplier registration details available on request" | Reject (R4) |
| 09 | "30 to 90 days as agreed"; 50,000 × 6.40 = 320,000 ≠ 322,000 | Person (H3, H6) |
| 10 | Delivery 60 days; VAT included | Reject (R5) (+ H5) |

Split: 2 Approve, 5 Reject, 3 Needs a person.

## 2. Automated tests (`tests/test_pipeline.py`, 69 tests, offline)

```bash
python -m pytest -q
```

| Group | What it proves |
|---|---|
| End-to-end, parser mode (10) | Each sample gets the expected decision **and** the expected rule ID |
| End-to-end, hybrid mode with a simulated AI (10) | The hybrid path (verify + reconcile) gives the same answers when the AI reads correctly |
| AI failure | Hybrid: if Gemini is down, the document is never approved → person (X3). AI-only: if nothing is extracted, **no rule runs** → person (regression test from live run 4) |
| Backup AI | Gemini down → Groq reads it → same result, provider recorded (X5). All AIs down → person |
| Error handling | Daily vs per-minute quota, retry-after parsing ("try again in 7.5s"), fatal 404 → no retry |
| AI null-vs-false flags | Gemini's `null` for "price includes VAT" is not a fake disagreement (regression test from live run 1) |
| Unreadable PDF | Corrupt/scanned file → person (X4), no crash |
| Parser | Weeks → days, ranges, missing TIN/BIN stays empty, VAT-inclusive detected |
| Rule boundaries (27) | Price at max / +0.01 / +3% / >3%; qty ±5%; advance 20 / 20.5 / missing; delivery 30/31/45/46; payment 29/30/60/61/range; validity 29; wrong VAT rate; wrong total; unknown item; missing BIN; weak penalty |
| Never guess | Uncertain BIN → person, not reject. Invented quote caught. Invented TIN caught. AI misread price (427 vs 472) → disagreement → person |

## 3. Live evaluation against Gemini

Results of every run, including failures: [EVALUATION_LOG.md](EVALUATION_LOG.md).

```bash
python -m supplier_checker.cli evaluate --mode hybrid
python -m supplier_checker.cli evaluate --mode ai
python -m supplier_checker.cli evaluate --mode parser
```

Each run writes `results/<mode>/summary.md`, `summary.csv` and one JSON per document (all findings,
extracted fields, quotes, step timings).

## 4. Limits of this testing (honest)
- 10 samples, all from the same template. 10/10 on these does **not** prove the system handles other layouts.
  The parser in particular was written while looking at these files.
- The ground truth is my reading of the rules. Where the rules are ambiguous, my choice is documented in
  [RULES_AND_ASSUMPTIONS.md](RULES_AND_ASSUMPTIONS.md).
- Gemini output can vary slightly between runs, even at temperature 0. Disagreements are caught by the
  cross-check (they become *person* decisions, not wrong approvals), but they could lower the score.
