# Evaluation log (every live run, including the failures)

All runs: the 10 sample packs, scored against `data/expected-decisions.csv`.
Raw output for each run is kept in `results/`.

| # | Date | Mode | Model | Score | Time | Folder |
|---|---|---|---|---|---|---|
| 0 | 2026-11-02 | parser | – | **10/10** | 0.1 s total | `results/parser/` |
| 1 | 2026-11-02 | hybrid | gemini-3.5-flash | 7/10 | 197 s (≈20 s/doc) | `results/hybrid-run1-before-fix/` |
| 2 | 2026-11-02 | hybrid | gemini-3.5-flash | 8/10 *(AI quota exhausted)* | 79 s | `results/hybrid-run2-quota-exhausted/` |
| 3 | 2026-11-02 | hybrid | gemini-3.5-flash-lite | **10/10** | 29.7 s (≈3 s/doc) | *(superseded by run 10)* |
| 4 | 2026-11-02 | ai | gemini-3.5-flash-lite | 8/10 *(rate limit hit after 6 docs; the 6 that ran were all correct)* | 18.5 s | `results/ai-run1-quota-exhausted-bug/` |
| 5 | 2026-11-02 | hybrid | **Groq** gpt-oss-120b only | 10/10, but Groq failed on 5 docs *(rate limit)*; parser + safety rules carried them | 63 s | *(not kept)* |
| 6 | 2026-11-02 | hybrid | forced fallback Gemini ✗ → Groq | 8/10 *(Groq rate-limited)* | 143 s | *(not kept)* |
| 7 | 2026-11-02 | hybrid | Groq only, after rate-limit fix | 10/10; Groq read all 10 but left out the item code on 5 | 168 s | `results/hybrid-groq-only-run1/` |
| 8 | 2026-11-02 | hybrid | forced fallback Gemini ✗ → Groq, after fix | **10/10**; all 10 read by Groq | 155 s | `results/hybrid-fallback-live-test/` |
| 9 | 2026-11-02 | hybrid | Groq only, after prompt fix | **10/10**; full agreement on 9/10 (pack 08: Groq misread penalty basis, caught) | 166 s (≈17 s/doc, rate-limited) | `results/hybrid-groq-only/` |
| 10 | 2026-11-02 | hybrid | gemini-3.5-flash-lite, after prompt fix | **10/10**; full agreement on 10/10 | 32 s (≈3 s/doc) | `results/hybrid/` |

## Run 1: a false alarm in the cross-check (fixed)
- **What happened:** packs 01 and 02 (Approve) and 03 (Reject) all came out as *Needs a person*.
- **Cause:** for "does the price include VAT?", Gemini answered `null` and the parser answered `false`. Both
  mean "the document does not say the price includes VAT", but the cross-check counted them as a
  disagreement. The price became *uncertain*, and the price rule refused to run.
- **Good news:** the safety net worked. There was no wrong Approve and no wrong Reject, only extra work for a
  person.
- **Fix:** the prompt now asks for true/false only, and `ai_reader.normalise_flags()` applies the schema's
  definition (for "true only if the document says so" flags, null means false). There is a regression
  test for it.

## Run 2: free-tier quota exhausted
- Gemini's free tier allows **20 requests per day per model**. Development, the smoke test and run 1 used
  them up, so every AI call returned `429 RESOURCE_EXHAUSTED`.
- Hybrid mode fell back to the parser and, as designed, refused to approve anything without the
  cross-check. The 2 Approve packs went to a person (8/10). No document was wrongly approved or rejected.
- **Fix:** the reader used to retry 3× even on a daily-quota error, which wasted time. It now stops at once.

## Run 3: hybrid on gemini-3.5-flash-lite → 10/10
- Switched to the lite model, which has its own quota. AI and parser agreed on **every field of every
  pack**: no X1 (invented quote) and no X2 (disagreement) findings.
- About 3 s per document, compared with about 20 s on gemini-3.5-flash.
- Gemini also spotted the pack 09 arithmetic error by itself, in a reader note.

## Run 4: AI-only exposed a real safety bug (fixed)
- The lite model's quota ran out after 6 documents. Those 6 were all correct.
- **Bug:** for packs 07–10 nothing was extracted, yet the system ran the rules on empty data and
  **rejected** them for "TIN and BIN missing". It had not read anything, so this was a guess, which the
  brief forbids.
- **Fix:** a second safety branch in the graph. If no reader extracted anything, the rule steps are skipped
  and the document goes straight to *Needs a person*. There is a regression test for it.
- **Still to do:** re-run AI-only mode once the quota resets, to get a full 10-document score.

## Runs 5–10: adding Groq as a backup AI
**Why:** Gemini's free tier is small, and runs 2 and 4 showed that an AI outage sends everything to a person.
Groq (a different company from xAI's *Grok*) has a free tier with far higher daily limits.
The reader now tries **Gemini → Groq → (person)**. Whichever AI answers goes through exactly the same checks.

- **Run 5: Groq's per-minute limit.** The free tier allows 8,000 tokens/minute, and each document used
  about 3–4k. Groq failed on 5/10. The score still showed 10/10, because the parser and the "no cross-check →
  never approve" rule covered for it. **That score did not measure Groq**, which is why I checked which
  provider actually read each document.
- **Fix:** (a) on a rate limit, wait as long as the provider asks ("try again in 7.5s"), not a fixed 2–4 s;
  (b) never retry errors that cannot succeed (404 unknown model, 401 bad key); (c) treat Gemini's
  `RESOURCE_EXHAUSTED` as daily or per-minute depending on the quota id (in run 4 I had wrongly assumed
  daily); (d) `reasoning_effort="low"` and a compact schema to cut Groq to about 3k tokens/document.
- **Run 8: a real fallback test.** I pointed Gemini at a model that is closed to new users, so every
  Gemini call failed for real. Groq took over all 10 documents → 10/10. Each result records the provider
  that read it (finding X5).
- **Run 7 → 9: Groq left out the item code** ("A", "C", "E" at the start of the item line) on 5/10 packs. The
  cross-check flagged every case. The final answers were still right, but on a clean document it would have
  meant an unnecessary review. A one-line prompt clarification fixed it (run 9), and Gemini was re-checked
  for regressions (run 10: 10/10, full agreement).
- **A remaining Groq misreading (pack 08):** "0.5% per week of delay" → Groq says the penalty is "of
  order value", which the document never says. **The cross-check caught it.** This is exactly the kind of
  error the two-reader design exists for.

## Model comparison on these 10 samples
| | Gemini 3.5 Flash-Lite | Groq gpt-oss-120b |
|---|---|---|
| Correct decisions (hybrid) | 10/10 | 10/10 |
| Fields matching the parser | all fields, 10/10 docs | all fields on 9/10 docs (1 misread caught) |
| Speed (free tier) | ≈3 s/doc | ≈4 s/call, but ≈17 s/doc averaged over a batch because of rate-limit waits |
| Free-tier limit | 20 requests/day/model | ≈1,000 requests/day, 8,000 tokens/minute |
| Role | Primary | Backup |

## What the runs taught me
1. Testing with a *simulated* AI (unit tests) did not catch the `null` vs `false` problem. Only the live
   model did. Live evaluation is not optional.
2. Free-tier limits are a real operational constraint. A reviewer with a free key can do about 2 full runs
   per day per model.
3. Failure paths need live testing too. The AI-only bug only appeared when the AI actually failed mid-run.
4. A headline score can hide a failure. Run 5 scored 10/10 while the AI under test failed on half the
   documents. Always check *who* produced each answer, not just the final count.
