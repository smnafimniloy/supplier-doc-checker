# One-page note — Supplier Document Checker

**What I built.** A system that checks each supplier quotation and answers **Approve**, **Reject** or **Needs a
person to check**, naming the company rule behind the answer and quoting the document. It is a fixed 7-step
LangGraph workflow: read PDF → AI extraction (Gemini, Groq as backup) → independent rule-based extraction →
verify → compare with purchase request → check company rules → decide. The AI only *reads*; every decision
is plain, tested Python. There is a Streamlit app (steps, quotes, and a Decisions tab where a person's review becomes the final
decision, with who/when/why and full history) and a CLI that scores all
samples.

**How "never guess" works.**
- Every AI value must come with a quote found word-for-word in the PDF.
- A non-AI parser reads the same PDF; any field where the two readers disagree becomes *uncertain*.
- A rule whose input is uncertain or missing returns *Needs a person*, never Approve or Reject.
- An unreadable PDF, or an AI outage, also goes to a person.

**How I tested it.** I worked out the correct answer for all 10 packs by hand first
(`data/expected-decisions.csv`). The 75 offline tests cover:
- all 10 samples end-to-end;
- every rule at its exact boundary (e.g. +3.00% vs +3.01%);
- the failure paths: an invented quote, an invented TIN, a misread price, an AI outage, a corrupt PDF.

I also ran 10 logged live evaluations against the real AI services (`docs/EVALUATION_LOG.md`).

**Results.**

| Setup | Correct | Time / doc |
|---|---|---|
| **Hybrid: Gemini 3.5 Flash-Lite + parser** | **10 / 10** (readers agreed on every field) | ≈ 3 s |
| Backup only: Groq gpt-oss-120b + parser | 10 / 10 | ≈ 17 s (free-tier limit) |
| Live fallback (Gemini forced to fail → Groq) | 10 / 10 | ≈ 15 s |
| Parser only, no AI | 10 / 10 | < 0.05 s |

Split: 2 Approve, 5 Reject, 3 Needs a person.

Live testing found bugs my unit tests missed. All are fixed and covered by regression tests:
- **First run: 7/10.** The AI said "not stated" where the parser said "no", and the cross-check counted that
  as a disagreement. It failed safely: three documents went to a person instead of being decided.
- **Quota outage.** The system ran the rules on *empty* data and rejected documents for "missing TIN", which
  was a guess. Now nothing is checked unless something was read.
- **A misleading "10/10".** One run scored 10/10 while the backup AI had failed on half the documents. I now
  record which AI produced each answer.
- **A misread caught.** Groq misread pack 08's penalty clause, and the cross-check flagged it.

**What does not work well.**
- **One template.** All 10 samples share one layout, so 10/10 doesn't prove other formats work. The parser
  would miss other layouts, which would send those documents to a person (safe, but slow).
- **No OCR.** Scanned quotes go straight to a person.
- **Judgement calls.** A penalty below 0.5%, or one not tied to order value, goes to a person, because the
  rules don't say which outcome applies. VAT-inclusive prices assume the purchase-request maximum excludes
  VAT. Both are documented in `docs/RULES_AND_ASSUMPTIONS.md`.
- **Over-caution.** Harmless formatting differences between the readers can still trigger a review.
- **Free tiers.** Gemini allows 20 requests a day per model, and Groq about 2–3 documents a minute.
  Production needs paid keys.
- **One purchase request.** Only one PR is loaded at a time.

**Next.**
1. Test on 50+ anonymised real quotes in varied layouts.
2. Add OCR for scanned documents.
3. Get the purchasing team to settle the ambiguous rules.
4. Turn reviewer decisions (`review_log.jsonl`) into new test cases.
5. Check quote expiry and validate TIN/BIN against a vendor master.
