# How I used AI tools

The brief says: "Use any AI tools you like … We want to see how you use them." This is the log.

## Tools
| Tool | Used for |
|---|---|
| **Claude Code** (Claude Opus, in the terminal) | Comparing the two tasks, reading the sample PDFs, scaffolding the project, writing code, tests and docs, running the evaluation |
| **Google Gemini** (`gemini-3.5-flash-lite`, API) | Inside the product: reading each supplier PDF into structured JSON (primary) |
| **Groq** (`openai/gpt-oss-120b`, API) | Inside the product: backup reader when Gemini fails |

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
5. **Verification.** Every generated module was run against the samples and covered by tests (69 offline
   tests), including tests that simulate AI hallucinations and outages.
6. **Live runs found what tests missed.** Two bugs only appeared against the real Gemini API: a null-vs-false
   false alarm, and rules running on empty data during a quota outage. Both were fixed with regression
   tests. See [EVALUATION_LOG.md](EVALUATION_LOG.md).

## What I checked myself
- The expected decision for every sample, against `company-rules.md`.
- Every rule boundary (3%, 5%, 20%, 30/31/45 days, 30–60 days).
- Ambiguous rules: I made the calls and documented them in `RULES_AND_ASSUMPTIONS.md`.
