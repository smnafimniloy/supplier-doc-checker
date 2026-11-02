"""Command line: check one PDF, or evaluate all samples against the expected answers.

    python -m supplier_checker.cli evaluate            # all 10 samples, score vs expected
    python -m supplier_checker.cli evaluate --mode parser
    python -m supplier_checker.cli check data/supplier-pack-04.pdf
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from . import config
from .graph import check_document, default_mode
from .schemas import Severity

ICON = {Severity.REJECT: "✗", Severity.REVIEW: "?", Severity.PASS: "✓", Severity.INFO: "i"}


def state_to_dict(state: dict) -> dict:
    ex = state.get("extraction")
    return {
        "document": state["document_name"],
        "mode": state["mode"],
        "ai_provider": state.get("ai_provider"),
        "decision": state["decision"].value,
        "reasons": [f.model_dump(mode="json") for f in state["reasons"]],
        "also_flagged": [f.model_dump(mode="json") for f in also_flagged(state)],
        "findings": [f.model_dump(mode="json") for f in state["findings"]],
        "extraction": ex.model_dump(mode="json") if ex else None,
        "uncertain_fields": state.get("uncertain_fields", []),
        "steps": state["steps"],
    }


def also_flagged(state: dict) -> list:
    """REVIEW findings that did not decide the outcome (e.g. on a rejected document)."""
    return [f for f in state["findings"] if f.severity == Severity.REVIEW and f not in state["reasons"]]


def print_report(state: dict, verbose: bool = True) -> None:
    ex = state.get("extraction")
    print(f"\n=== {state['document_name']}  [{state['mode']} mode]")
    if ex:
        for item in ex.line_items:
            print(f"  Supplier: {ex.supplier_name} | Item {item.item_code}: {item.description} | "
                  f"qty {item.quantity:g} {item.unit} @ {item.unit_price} BDT")
    if verbose:
        for s in state["steps"]:
            print(f"  [{s['status']:>9}] {s['step']} - {s['detail']} ({s['seconds']}s)")
        for f in state["findings"]:
            print(f"   {ICON[f.severity]} {f.rule_id:<3} {f.check}: {f.message}")
    print(f"  DECISION: {state['decision'].value}")
    for r in state["reasons"]:
        print(f"    - [{r.rule_id}] {r.message}")
        if r.evidence:
            print(f'      quote: "{" ".join(r.evidence.split())}"')
    for r in also_flagged(state):
        print(f"    (also flagged) [{r.rule_id}] {r.message}")


def cmd_check(args: argparse.Namespace) -> int:
    state = check_document(args.pdf, mode=args.mode)
    if args.json:
        print(json.dumps(state_to_dict(state), indent=2, ensure_ascii=False))
    else:
        print_report(state)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    mode = args.mode or default_mode()
    with open(config.EXPECTED_CSV, encoding="utf-8") as fh:
        expected = list(csv.DictReader(fh))

    out_dir = config.RESULTS_DIR / mode
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, correct, total_seconds = [], 0, 0.0
    for exp in expected:
        pdf = config.DATA_DIR / exp["file"]
        t = time.perf_counter()
        state = check_document(pdf, mode=mode)
        seconds = time.perf_counter() - t
        total_seconds += seconds
        got = state["decision"].value
        ok = got == exp["expected_decision"]
        correct += ok
        print_report(state, verbose=args.verbose)
        print(f"  EXPECTED: {exp['expected_decision']}  ->  {'CORRECT' if ok else 'WRONG'}  ({seconds:.1f}s)")
        (out_dir / f"{pdf.stem}.json").write_text(
            json.dumps(state_to_dict(state), indent=2, ensure_ascii=False), encoding="utf-8")
        rows.append({
            "file": exp["file"], "expected": exp["expected_decision"], "got": got, "correct": ok,
            "reasons": " | ".join(f"[{r.rule_id}] {r.message}" for r in state["reasons"]),
            "seconds": round(seconds, 2),
        })

    summary = f"{correct}/{len(expected)} correct in {mode} mode ({total_seconds:.1f}s total)"
    print(f"\n{'=' * 70}\nRESULT: {summary}\n{'=' * 70}")
    _write_summary(out_dir, mode, rows, summary)
    print(f"Saved per-document JSON and summary.md to {out_dir.relative_to(config.PROJECT_ROOT)}/")
    return 0 if correct == len(expected) else 1


def _write_summary(out_dir: Path, mode: str, rows: list[dict], summary: str) -> None:
    with open(out_dir / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    lines = [f"# Evaluation results ({mode} mode)", "",
             f"Run at {datetime.now():%Y-%m-%d %H:%M}. **{summary}**", "",
             "| File | Expected | System | OK | Reasons | Time (s) |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['file']} | {r['expected']} | {r['got']} | {'✅' if r['correct'] else '❌'} | "
                     f"{r['reasons'] or '-'} | {r['seconds']} |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(config.PROJECT_ROOT / ".env")
    p = argparse.ArgumentParser(prog="supplier_checker", description="Check supplier quotations against company rules.")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="Check one supplier PDF")
    c.add_argument("pdf", type=Path)
    c.add_argument("--mode", choices=["hybrid", "ai", "parser"])
    c.add_argument("--json", action="store_true", help="Print the full result as JSON")
    c.set_defaults(func=cmd_check)

    e = sub.add_parser("evaluate", help="Run all samples and compare with data/expected-decisions.csv")
    e.add_argument("--mode", choices=["hybrid", "ai", "parser"])
    e.add_argument("-v", "--verbose", action="store_true", help="Show every step and check")
    e.set_defaults(func=cmd_evaluate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
