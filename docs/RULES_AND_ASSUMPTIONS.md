# Rules and how they were interpreted

Source: [`data/company-rules.md`](../data/company-rules.md). Thresholds live in
[`supplier_checker/config.py`](../supplier_checker/config.py).

## Rule → implementation

| ID | Rule (from company-rules.md) | Implementation | Boundary behaviour |
|---|---|---|---|
| R1 | Unit price > 3% above max → **Reject** | `(price − max) / max × 100 > 3` | exactly +3.00% → H1, not R1 |
| R2 | Advance > 20% → **Reject** | `advance_percent > 20` | 20% → pass |
| R3 | No late-delivery penalty clause → **Reject** | No clause titled *Delay* or mentioning *penalty / late delivery* | – |
| R4 | TIN or BIN missing → **Reject** | Either number not printed | "available on request" = missing |
| R5 | Delivery later than 45 days → **Reject** | `delivery_days > 45` | 45 → H4 |
| H1 | Price above max by ≤ 3% → **Person** | `0 < over% ≤ 3` | exactly max → pass |
| H2 | Quantity differs by > 5% → **Person** | `abs(qty − requested) / requested > 5%` | both over and under |
| H3 | Payment unclear or outside 30–60 days → **Person** | Missing days, a *range* of days, or a fixed term outside 30–60 | 30 and 60 → pass |
| H4 | Delivery 31–45 days → **Person** | `31 ≤ delivery_days ≤ 45` | 30 → pass |
| H5 | VAT not shown separately at 15% → **Person** | No separate VAT line, prices "VAT included", or a rate ≠ 15 | – |
| H6 | Numbers don't add up → **Person** | qty × price = line amount; Σ lines = subtotal; subtotal × 15% = VAT; subtotal + VAT = total (±0.01 BDT) | – |
| H7 | Valid < 30 days → **Person** | `validity_days < 30` | 30 → pass |
| P1 | Penalty ≥ 0.5% of order value / week | see assumption 3 | 0.5 → pass |

Extra checks added by this system (not in the rule list, but needed so it never guesses):

| ID | Check | Result if it fails |
|---|---|---|
| M1 | Quoted item can be matched to a purchase-request line | Person |
| M2 | Item description matches the requested item (similarity ≥ 0.6) | Person |
| M3 | Quote references the right PR number | Person |
| X1 | AI quotes / TIN / BIN actually appear in the PDF | Person |
| X2 | AI and parser agree | Person |
| X3 | AI reader was available (hybrid/ai mode) | Person |
| X4 | PDF has readable text | Person |

## Assumptions (where the rules were not explicit)

1. **"Unclear payment terms" includes ranges.** "Payment within 30 to 90 days as agreed by both parties"
   (pack 09) is not a fixed term, so it counts as unclear. It is also partly outside 30–60 days.
2. **Delivery in weeks is converted to days.** "4 weeks" = 28 days (pack 09).
3. **Penalty below 0.5% → Needs a person, not Reject** *(reviewed and confirmed as a deliberate decision)*. The rules list "no penalty clause" as a Reject reason,
   but put the 0.5% minimum under *Other notes* without saying which outcome applies. Rejecting would be a
   guess, so the system asks a person. The same applies when a penalty does not say it is a percentage of
   *order value* (pack 08: "0.5% per week of delay"). Pack 08 is rejected anyway for missing TIN/BIN.
   *(None of the 10 samples has a penalty below 0.5%, so this choice does not change any sample result.)*
4. **VAT-inclusive prices** (pack 10). The purchase-request maximum is assumed to be **before VAT**. If the
   VAT-inclusive price is already ≤ the maximum, the price check passes. If the price *before VAT* is still
   more than 3% over, it is rejected. Anything in between goes to a person. Separately, H5 flags that VAT is
   not shown on its own line.
5. **Advance stated twice** (pack 05: "40% advance … 40% advance …, balance 60%"). Same number twice → 40%.
   If the two numbers had been different, the parser would leave the field empty → person.
6. **"Payment within N days after delivery"** is taken as the payment term. The advance is checked separately
   under R2.
7. **Reject outranks person.** When a document has both (pack 10: late delivery *and* VAT not separate), the
   answer is Reject, and the person-check items are still listed as "also flagged".
8. **Uncertain is not missing.** If the system is unsure whether a TIN exists (e.g. the readers disagree),
   it does **not** reject for "missing TIN". It asks a person.
9. **Quotation date vs. today** is not checked. Validity is measured in days from the quote date, as written.
   Checking expiry against today's date would be easy to add, but it isn't in the rules.
