# How I used AI tools

The brief says: "Use any AI tools you like … We want to see how you use them." This is the log.

## Tools
| Tool | Used for |
|---|---|
| **Claude Code** (Claude Opus, in the terminal) | Comparing the two tasks, reading the sample PDFs, scaffolding the project, writing code, tests and docs, running the evaluation |
| **Google Gemini** (`gemini-3.5-flash-lite`, API) | Inside the product: reading each supplier PDF into structured JSON (primary) |
| **Groq** (`openai/gpt-oss-120b`, API) | Inside the product: backup reader when Gemini fails |
| **graphify** (knowledge-graph skill for Claude Code) | Mapping the finished codebase and docs into a graph, to trace how rules, safeguards and AI fallback connect |

## Workflow
1. **Choosing the task.** I asked Claude Code to analyse both tasks against a 2-day budget. It recommended
   Task 1: the rules are deterministic, so a high and reliable score is realistic, while small offline models
   are weak in Bangla/Banglish.
2. **Ground truth first.** Before any code, all 10 PDFs were read and every rule applied by hand. That produced
   `data/expected-decisions.csv`, so the system is measured against an answer key written independently of
   the code.
3. **Decisions I made and gave to the AI as constraints:**
   - Gemini as the LLM (free tier, so reviewers can run it).
   - Streamlit + CLI for the demo.
   - All dependencies in a project virtual environment, nothing installed globally.
4. **Architecture.** "AI reads, Python decides", plus a second independent reader, was a deliberate design so
   that AI mistakes become visible *Needs a person* results rather than wrong answers.
5. **Verification.** Every generated module was run against the samples and covered by tests (75 offline
   tests), including tests that simulate AI hallucinations and outages.
6. **Live runs found what tests missed.** Two bugs only appeared against the real Gemini API: a null-vs-false
   false alarm, and rules running on empty data during a quota outage. Both were fixed with regression
   tests. See [EVALUATION_LOG.md](EVALUATION_LOG.md).
7. **Adding a backup AI.** After Gemini's free quota ran out, I asked whether a free backup was possible.
   xAI's Grok has no dependable free API tier; **Groq** (a different company) does, so it became the
   backup. Live testing it found a misleading 10/10 (Groq had failed on half the documents and the parser
   covered for it), a rate-limit problem, and a missing-item-code problem. All were fixed and logged.
8. **Checking the design with a knowledge graph.** I used graphify to map the code and docs (286 nodes) and
   traced three paths: rule → code → test, the never-guess safeguards, and AI failure handling. It confirmed
   that every rule check calls the `_uncertain_review()` guard first. It also showed the graph's blind
   spots: links that pass through dictionaries (`PipelineState`, the `PROVIDERS` lookup) are invisible to
   it. So I documented those paths by hand, checked against the code.
9. **Shipping.** The fresh-install test (a clean copy with no `.venv` or `.env`) exposed a README trap:
   stock macOS Python 3.9 can't install LangGraph, so I added a `uv` route. A secret scan was run before the
   first push. The app is deployed on Streamlit Cloud with keys kept in its secrets, never in the repo.

## What I checked myself
- The expected decision for every sample, against `company-rules.md`.
- Every rule boundary (3%, 5%, 20%, 30/31/45 days, 30–60 days).
- Ambiguous rules: I made the calls and documented them in `RULES_AND_ASSUMPTIONS.md`. The penalty-below-0.5%
  case (→ Needs a person) was reviewed and confirmed as a deliberate decision.
- Every "never guess" path, by hand: see [MANUAL_TESTING.md](MANUAL_TESTING.md).
