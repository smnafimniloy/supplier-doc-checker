# Architecture

## The problem in one sentence
Turn a supplier PDF into a decision a purchasing manager can trust, and when the system can't be sure,
hand it to a person instead of guessing.

## Why a fixed workflow and not an agent
The brief asks for "clear fixed steps, one after another". There are also practical reasons:

- **Auditability** — every document passes through the same 7 steps, and each step is logged with its status
  and timing. A reviewer can see exactly where a decision came from.
- **Predictability** — an agent can skip a check or invent a new one. A fixed graph cannot.
- **Testability** — each step is a plain function with typed inputs and outputs, so it can be unit-tested.

## The graph (`supplier_checker/graph.py`)

```
START
  └─► read_document ──(no readable text)──────────────────────────────────┐
          │                                                                │
          ▼                                                                │
      extract_with_ai ─► extract_with_parser ─► verify_extraction ─(nothing extracted)─┤
                                                      │                    │
                                                      ▼                    │
                          compare_with_purchase_request ─► check_company_rules
                                                                 │         │
                                                                 ▼         ▼
                                                                decide ◄───┘
                                                                  │
                                                                 END
```

State is a single `PipelineState` (TypedDict). Each node returns only the keys it adds. Every node appends to
`steps` (`step`, `status`, `detail`, `seconds`), which the CLI and the app show as a timeline.

| # | Node | Input | Output | Can it fail? |
|---|---|---|---|---|
| 1 | `read_document` | PDF path / upload | `text` | Yes: corrupt/scanned → `read_error` → jump to `decide` → *Needs a person* |
| 2 | `extract_with_ai` | `text` | `ai_extraction`, `ai_provider` | Yes: tries Gemini then Groq. Per call: 60 s timeout; rate limits wait the provider's retry-after; daily-quota/fatal errors skip to the next provider. If all fail, sets `ai_error` and continues |
| 3 | `extract_with_parser` | `text` | `parser_extraction` | No (unmatched fields are left empty) |
| 4 | `verify_extraction` | both extractions | `extraction`, `uncertain_fields`, findings X0–X3 | Yes: no reader extracted anything → skip rules → `decide` → *Needs a person* |
| 5 | `compare_with_purchase_request` | extraction + PR | findings M1–M3, R1/H1 (price), H2 (qty) | – |
| 6 | `check_company_rules` | extraction | findings R2–R5, H3–H7, P1, notes | – |
| 7 | `decide` | all findings | `decision`, `reasons` | – |

## Data model (`supplier_checker/schemas.py`)
- **`Extraction`** — raw facts plus the exact quote for each group of facts (payment, delivery, penalty,
  validity, totals, tax IDs, each item line). It holds **no judgements**. The same model is the Gemini
  `response_schema` and the parser's output, so the two readers can be compared field by field.
- **`Finding`** — one check: `rule_id`, `check`, `severity` (`PASS` / `REVIEW` / `REJECT` / `INFO`),
  `message`, `evidence` (quote).
- **`Decision`** — `Approve` / `Reject` / `Needs a person to check`.

## The two readers
| | AI reader (`ai_reader.py`) | Parser (`parser_reader.py`) |
|---|---|---|
| How | Gemini (`temperature=0`, JSON mode with the Pydantic schema); backup Groq `gpt-oss-120b` (JSON mode, schema in prompt, validated by Pydantic) | Regular expressions over the PDF text |
| Strength | Understands varied wording and layouts | Exact, deterministic, free, offline |
| Weakness | Can misread or invent values | Only knows the layouts and phrasings it was written for |
| Told to | Copy facts and quotes only. Null if unsure. Never calculate or fix. | Leave a field empty if no pattern matches |

## Verification (`verify.py`)
1. **Grounding** (`ground_check`): each AI quote must be a substring of the PDF text (case and whitespace
   ignored). TIN/BIN values must appear in the text. If a check fails, the dependent fields become *uncertain*
   (finding X1).
2. **Agreement** (`reconcile`, hybrid mode only): all scalar fields and every item-line field are compared.
   If they differ, the field becomes *uncertain* (X2) and both values are shown to the reviewer. The AI value
   is never silently preferred.
3. **AI unavailable** (X3): parser result is used, but the document cannot be approved without a person.
4. **Backup AI used** (X5, info only): records that Gemini failed and which provider read the document.

## Rule engine (`rules.py`)
Each rule is a small function returning a `Finding`. Before evaluating, each rule asks
`_uncertain_review(...)`: *are any of my input fields uncertain?* If yes, it returns REVIEW and does not
evaluate. This one helper is what stops an uncertain reading from ever producing an Approve or a Reject.

Decision precedence (`decide`): REJECT > REVIEW > APPROVE, matching `company-rules.md` ("Needs a person …
if nothing above applies").

## Human review (`reviews.py`)
The pipeline's answer is the **system decision**. When it is *Needs a person to check*, a reviewer records
Approve or Reject, with their name and a note, in the app. Each review is appended to
`results/review_log.jsonl` and never edited, so the history of who decided what (including changes of mind)
is kept.

`final_decision(document, system_decision, reviews)` gives each document's final answer:
- no review → the system decision, "decided by system";
- reviewed → the **latest** review for that document, attributed to the reviewer;
- a review only counts for the **same system result** it was made for. If a re-check gives a different
  answer, the old review stays in the history but no longer applies, so a stale human decision can never
  silently override new evidence.

The app's **Decisions** tab groups documents by final decision (Approved / Rejected / Needs a person) and
lists the review history.

## Extending it
- **New rule** → add a threshold to `config.py`, a function in `rules.py`, a test in `tests/`.
- **New document layout** → the AI reader handles it already. Add parser patterns, or run in `ai` mode.
- **Scanned PDFs** → add an OCR step (e.g. Tesseract, or send the page image to Gemini) inside `read_document`.
- **Multiple items per quote** → already supported: every line is matched and checked separately.
