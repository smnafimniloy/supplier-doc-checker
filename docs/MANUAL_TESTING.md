# Manual testing guide

A hands-on checklist for anyone who wants to check the system themselves, beyond the automated tests in
[TESTING.md](TESTING.md). Every expected result below was confirmed by running it.

About 20–30 minutes. Tick each box as you go. Run each test in order: later tests change settings
temporarily, and the last section shows how to put them back.

## 0. Setup (once per Terminal window)

First install the project as described in the [README Quick start](../README.md#quick-start).

```bash
cd supplier-doc-checker              # wherever you cloned it
source .venv/bin/activate          # your prompt now starts with (.venv)
```

- [ ] The prompt shows `(.venv)`

---

## 1. Automated checks first (2 min)

| # | Run | Expected | ✓ |
|---|---|---|---|
| 1.1 | `python -m pytest -q` | `69 passed` | [ ] |
| 1.2 | `python -m supplier_checker.cli evaluate --mode parser` | `RESULT: 10/10 correct in parser mode` | [ ] |
| 1.3 | `python -m supplier_checker.cli evaluate` | `RESULT: 10/10 correct in hybrid mode` (about 30 s; uses AI quota) | [ ] |

If 1.3 shows "AI reader failed" or fewer than 10/10, the free AI quota is probably used up. Check that
the failed documents went to **Needs a person**, not Approve. That's the safety net working. Try again later.

---

## 2. The web app: main flow (10 min)

Start it with `streamlit run app.py`. It opens http://localhost:8501.

### 2.1 Sidebar
- [ ] **Reading mode** shows three options; select **Hybrid**
- [ ] The caption shows `AI chain: gemini-3.5-flash-lite → groq:openai/gpt-oss-120b`
- [ ] The **Purchase request** table shows items A–E with max prices 480 / 38 / 210 / 6.50 / 95
- [ ] **Company rules** expands and shows the rule list

### 2.2 Check all 10 samples → Run all 10
- [ ] A progress bar runs through all 10 files
- [ ] **Correct vs expected = 10 / 10**
- [ ] Counts: **Approve 2**, **Reject 5**, **Needs a person 3**
- [ ] Every row in the table has ✅ in the **Match** column

### 2.3 Check each pack in "Inspect a document"
For each pack, check the decision **and** that the reason quotes the PDF.

| Pack | Supplier | Expected decision | Reason to look for | ✓ |
|---|---|---|---|---|
| 01 | Padma Textile Mills | ✅ Approve | "Every check passed"; the checklist is all green | [ ] |
| 02 | Jamuna Trims | ✅ Approve | All green | [ ] |
| 03 | Karnaphuli Yarn | ⛔ Reject | **R1**: price 229 is 9.05% above max 210 | [ ] |
| 04 | Surma Packaging | 🧑‍💼 Needs a person | **H1**: price 6.65 is 2.31% above max 6.5 | [ ] |
| 05 | Meghna Carton | ⛔ Reject | **R2**: advance 40% > 20% | [ ] |
| 06 | Teesta Fabrics | ⛔ Reject | **R3**: no late-delivery penalty clause | [ ] |
| 07 | Rupsha Zipper | 🧑‍💼 Needs a person | **H2**: quantity 16,500 is −17.5% vs 20,000 | [ ] |
| 08 | Bhairab Thread | ⛔ Reject | **R4**: TIN and BIN missing; quote "available on request" | [ ] |
| 09 | Dhaleshwari Poly Pack | 🧑‍💼 Needs a person | **H3**: payment "30 to 90 days"; **H6**: 322,000 should be 320,000 | [ ] |
| 10 | Kushiyara Box | ⛔ Reject | **R5**: delivery 60 days > 45; also flagged **H5** (VAT not separate) | [ ] |

### 2.4 Detail view (use pack 09)
- [ ] **Read by:** shows the AI model name
- [ ] **Extracted from the document** table: supplier, item D, 50,000 × 6.4, TIN/BIN, payment 30–90, delivery 28 days
- [ ] **Pipeline steps** lists 7 steps with timings
- [ ] **Full checklist** expander: every rule shown, with ✅ / 🟠 / ⛔ icons and quotes
- [ ] **Human review** form: choose Approve, write a note, click **Save review** → "Saved to results/review_log.jsonl"

### 2.5 Check one document tab
- [ ] Pick **supplier-pack-05.pdf** → **Check document** → Reject (R2)
- [ ] Upload a PDF from `data/` (e.g. `supplier-pack-03.pdf`) → Reject (R1)

### 2.6 Parser-only mode
- [ ] Sidebar → **Parser only** → Run all 10 again: still **10 / 10**, almost instantly
- [ ] Open pack 01: **Read by** is not shown (no AI was used)

Stop the app with **Ctrl + C** in Terminal.

---

## 3. "Never guess" tests: try to break it (10 min)

These show the system asks a person instead of guessing.

### 3.1 Unreadable PDF
```bash
echo "this is not a real pdf" > /tmp/fake.pdf
python -m supplier_checker.cli check /tmp/fake.pdf
```
- [ ] Decision: **Needs a person to check**, reason **[X4]** (could not open the PDF)
- [ ] No crash

### 3.2 Both AIs down → never approves
This simulates an outage by pointing both AIs at a model that doesn't exist.
```bash
GEMINI_MODEL=no-such-model GROQ_MODEL=no-such-model \
  python -m supplier_checker.cli check data/supplier-pack-01.pdf
```
- [ ] Pack 01 (normally **Approve**) becomes **Needs a person**, reason **[X3]** "AI reader failed… only the rule-based parser was used"
- [ ] It finishes in seconds (a missing model isn't retried)

### 3.3 Backup AI takes over
Breaks Gemini only, so Groq must read the document.
```bash
GEMINI_MODEL=no-such-model python -m supplier_checker.cli check data/supplier-pack-01.pdf
```
- [ ] Step 2 says **read by groq:openai/gpt-oss-120b (backup: primary AI failed)**
- [ ] An info line **[X5] AI backup used**
- [ ] Decision is still **Approve**

### 3.4 AI-only mode with no AI → rules must not run
```bash
GEMINI_MODEL=no-such-model GROQ_MODEL=no-such-model \
  python -m supplier_checker.cli check data/supplier-pack-07.pdf --mode ai
```
- [ ] Decision: **Needs a person**, reason only **[X3]**
- [ ] It does **not** say "TIN and BIN missing". That was the run 4 bug, now fixed.
- [ ] Steps 5 and 6 are missing from the step list (the rules were skipped)

### 3.5 No API keys at all
```bash
mv .env .env.off
python -m supplier_checker.cli evaluate | tail -3
mv .env.off .env                      # put it back!
```
- [ ] Runs in **parser mode** automatically, **10/10**
- [ ] `.env` is back (`ls -a` shows it)

---

## 4. Live-change drill (practise for the interview, 5 min)

Make a change, see its effect, then undo it.

1. Open `supplier_checker/config.py` and change `ADVANCE_MAX_PCT = 20.0` to `ADVANCE_MAX_PCT = 50.0`. Save.
2. `python -m supplier_checker.cli check data/supplier-pack-05.pdf`
   - [ ] Pack 05 (40% advance) is **no longer rejected** → now **Approve**
3. `python -m pytest -q`
   - [ ] **Some tests fail** (`test_advance`, and pack 05's end-to-end tests). The tests catch the change.
4. Undo: `git checkout supplier_checker/config.py`
5. `python -m pytest -q`
   - [ ] Back to **69 passed**

---

## 5. The online demo (2 min)

Open **https://supplier-doc-checker.streamlit.app/** in a **private/incognito** window.
- [ ] The app loads without asking you to log in (the first load may take about 30 s while it wakes up)
- [ ] The sidebar shows the AI chain (if it says "No Gemini key found", the Streamlit secrets weren't saved)
- [ ] **Run all 10** → **10 / 10**

---

## 6. Clean up after testing

```bash
git status                              # should say "nothing to commit, working tree clean"
rm -f results/review_log.jsonl          # optional: remove test reviews (not tracked by git anyway)
rm -f /tmp/fake.pdf
```
- [ ] `git status` is clean (if not, `git checkout .` undoes any accidental edits)

**If something doesn't match the expected result,** note the test number and what you saw.

Sections 3.2–3.4 need at least one API key in `.env`; section 3.3 needs a Groq key. Section 5 needs the
demo to be running.
