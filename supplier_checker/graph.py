"""The pipeline, built as a fixed LangGraph workflow (no free-running agent).

    read_document ─┬─(no text)────────────────────────────────────────────────────┐
                   └─> extract_with_ai ─> extract_with_parser ─> verify_extraction ─┤
                         (nothing extracted)──────────────────────────────────────┤
                         ─> compare_with_purchase_request ─> check_company_rules ─> decide ─> END

Every step is a plain function that reads the shared state and adds to it. There
are only two branches, both safety exits: "could the PDF be read at all?" and
"did any reader extract anything?". If not, the document goes straight to
`decide` and becomes "Needs a person to check" -- no rule is run on empty data.

Modes:
  hybrid  - Gemini + rule-based parser, cross-checked (default when a key is set)
  ai      - Gemini only (quotes still verified against the PDF)
  parser  - rule-based parser only (no API key needed)
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, BinaryIO, Literal, Optional, TypedDict, Union

from langgraph.graph import END, START, StateGraph

from . import ai_reader, parser_reader
from .documents import DocumentReadError, PurchaseLine, load_purchase_request, read_pdf_text
from .rules import check_against_request, check_company_rules, decide
from .schemas import Decision, Extraction, Finding, Severity
from .verify import ground_check, reconcile

Mode = Literal["hybrid", "ai", "parser"]


class StepLog(TypedDict):
    step: str
    status: str
    detail: str
    seconds: float


class PipelineState(TypedDict, total=False):
    # inputs
    source: Any
    document_name: str
    mode: Mode
    purchase_request: dict[str, PurchaseLine]
    # produced by steps
    text: str
    read_error: Optional[str]
    ai_extraction: Optional[Extraction]
    ai_error: Optional[str]
    ai_provider: Optional[str]          # which AI actually read the document
    ai_fallbacks: list[str]             # providers that failed before it
    parser_extraction: Optional[Extraction]
    extraction: Optional[Extraction]
    uncertain_fields: list[str]
    findings: list[Finding]
    decision: Decision
    reasons: list[Finding]
    steps: list[StepLog]


def _log(state: PipelineState, step: str, status: str, detail: str, started: float) -> list[StepLog]:
    return state.get("steps", []) + [StepLog(step=step, status=status, detail=detail,
                                             seconds=round(time.perf_counter() - started, 3))]


# ----------------------------------------------------------------------------- steps
def read_document(state: PipelineState) -> PipelineState:
    t = time.perf_counter()
    try:
        text = read_pdf_text(state["source"])
        return {"text": text, "read_error": None,
                "steps": _log(state, "1. Read document", "ok", f"{len(text)} characters of text", t)}
    except DocumentReadError as exc:
        return {"text": "", "read_error": str(exc),
                "steps": _log(state, "1. Read document", "failed", str(exc), t)}


def extract_with_ai(state: PipelineState) -> PipelineState:
    t = time.perf_counter()
    if state["mode"] == "parser":
        return {"ai_extraction": None, "ai_error": None,
                "steps": _log(state, "2. Extract with AI", "skipped", "parser-only mode", t)}
    try:
        res = ai_reader.extract(state["text"])
        detail = f"read by {res.provider}" + (" (backup: primary AI failed)" if res.failures else "")
        return {"ai_extraction": res.extraction, "ai_error": None, "ai_provider": res.provider,
                "ai_fallbacks": res.failures,
                "steps": _log(state, "2. Extract with AI", "ok", detail, t)}
    except ai_reader.AIReaderError as exc:
        return {"ai_extraction": None, "ai_error": str(exc), "ai_provider": None, "ai_fallbacks": [],
                "steps": _log(state, "2. Extract with AI", "failed", str(exc), t)}


def extract_with_parser(state: PipelineState) -> PipelineState:
    t = time.perf_counter()
    if state["mode"] == "ai":
        return {"parser_extraction": None,
                "steps": _log(state, "3. Extract with parser", "skipped", "AI-only mode", t)}
    ex = parser_reader.parse(state["text"])
    return {"parser_extraction": ex,
            "steps": _log(state, "3. Extract with parser", "ok", f"{len(ex.line_items)} item line(s)", t)}


def verify_extraction(state: PipelineState) -> PipelineState:
    t = time.perf_counter()
    mode, text = state["mode"], state["text"]
    ai, parser = state.get("ai_extraction"), state.get("parser_extraction")
    findings: list[Finding] = []
    uncertain: set[str] = set()

    if mode == "hybrid" and ai and parser:
        g_unc, g_find = ground_check(ai, text, "AI")
        merged, r_unc, r_find = reconcile(ai, parser)
        uncertain |= g_unc | r_unc
        findings += g_find + r_find
        detail = "AI and parser compared"
    elif mode in ("hybrid", "ai") and ai:
        merged = ai
        g_unc, g_find = ground_check(ai, text, "AI")
        uncertain |= g_unc
        findings += g_find
        detail = "AI quotes checked against the document"
    elif parser:
        merged = parser
        if mode != "parser":
            findings.append(Finding(
                rule_id="X3", check="AI reader available", severity=Severity.REVIEW,
                message=f"The AI reader failed ({state.get('ai_error')}), so the result could not be "
                        "cross-checked. Only the rule-based parser was used."))
        detail = "parser result used"
    else:
        # Nothing was read. Running the rules on an empty extraction would "find" a missing
        # TIN/BIN and reject -- a guess. Instead we skip the rule steps (see _after_verify).
        findings.append(Finding(rule_id="X3", check="AI reader available", severity=Severity.REVIEW,
                                message=f"No reader could extract the document ({state.get('ai_error')}). "
                                        "No rules were checked; a person must review it."))
        return {"extraction": None, "uncertain_fields": [], "findings": findings,
                "steps": _log(state, "4. Verify extraction", "failed", "nothing extracted; skipping rule checks", t)}

    for failure in state.get("ai_fallbacks") or []:
        findings.append(Finding(rule_id="X5", check="AI backup used", severity=Severity.INFO,
                                message=f"Primary AI failed, so {state.get('ai_provider')} read this document "
                                        f"instead ({failure[:160]}). Its output was verified the same way."))
    if not any(f.severity in (Severity.REVIEW, Severity.REJECT) for f in findings) and not any(
            f.rule_id == "X0" for f in findings):
        findings.append(Finding(rule_id="X0", check="Extraction verified", severity=Severity.PASS,
                                message="All extracted values are supported by the document text"
                                        + (" and both readers agree." if mode == "hybrid" else ".")))
    status = "uncertain" if uncertain or any(f.severity == Severity.REVIEW for f in findings) else "ok"
    return {"extraction": merged, "uncertain_fields": sorted(uncertain), "findings": findings,
            "steps": _log(state, "4. Verify extraction", status,
                          detail + (f"; uncertain: {', '.join(sorted(uncertain))}" if uncertain else ""), t)}


def compare_with_purchase_request(state: PipelineState) -> PipelineState:
    t = time.perf_counter()
    new = check_against_request(state["extraction"], state["purchase_request"], set(state["uncertain_fields"]))
    return {"findings": state["findings"] + new,
            "steps": _log(state, "5. Compare with purchase request", _worst(new), f"{len(new)} checks", t)}


def check_rules(state: PipelineState) -> PipelineState:
    t = time.perf_counter()
    new = check_company_rules(state["extraction"], set(state["uncertain_fields"]))
    return {"findings": state["findings"] + new,
            "steps": _log(state, "6. Check company rules", _worst(new), f"{len(new)} checks", t)}


def make_decision(state: PipelineState) -> PipelineState:
    t = time.perf_counter()
    if state.get("read_error"):
        f = Finding(rule_id="X4", check="Document readable", severity=Severity.REVIEW, message=state["read_error"])
        return {"findings": [f], "decision": Decision.REVIEW, "reasons": [f], "extraction": None,
                "uncertain_fields": [], "steps": _log(state, "7. Decide", "review", "document unreadable", t)}
    decision, reasons = decide(state["findings"])
    return {"decision": decision, "reasons": reasons,
            "steps": _log(state, "7. Decide", decision.value, f"{len(reasons)} reason(s)", t)}


def _worst(findings: list[Finding]) -> str:
    sev = {f.severity for f in findings}
    return "reject" if Severity.REJECT in sev else "review" if Severity.REVIEW in sev else "ok"


def _after_read(state: PipelineState) -> str:
    return "decide" if state.get("read_error") else "extract_with_ai"


def _after_verify(state: PipelineState) -> str:
    return "compare_with_purchase_request" if state.get("extraction") else "decide"


# ----------------------------------------------------------------------------- graph
def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("read_document", read_document)
    g.add_node("extract_with_ai", extract_with_ai)
    g.add_node("extract_with_parser", extract_with_parser)
    g.add_node("verify_extraction", verify_extraction)
    g.add_node("compare_with_purchase_request", compare_with_purchase_request)
    g.add_node("check_company_rules", check_rules)
    g.add_node("decide", make_decision)

    g.add_edge(START, "read_document")
    g.add_conditional_edges("read_document", _after_read,
                            {"extract_with_ai": "extract_with_ai", "decide": "decide"})
    g.add_edge("extract_with_ai", "extract_with_parser")
    g.add_edge("extract_with_parser", "verify_extraction")
    g.add_conditional_edges("verify_extraction", _after_verify,
                            {"compare_with_purchase_request": "compare_with_purchase_request", "decide": "decide"})
    g.add_edge("compare_with_purchase_request", "check_company_rules")
    g.add_edge("check_company_rules", "decide")
    g.add_edge("decide", END)
    return g.compile()


_GRAPH = None


def default_mode() -> Mode:
    return "hybrid" if ai_reader.is_configured() else "parser"


def check_document(source: Union[str, Path, BinaryIO], name: Optional[str] = None, mode: Optional[Mode] = None,
                   purchase_request: Optional[dict[str, PurchaseLine]] = None) -> PipelineState:
    """Run one supplier pack through the pipeline and return the final state."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH.invoke({
        "source": source,
        "document_name": name or (Path(source).name if isinstance(source, (str, Path)) else "uploaded.pdf"),
        "mode": mode or default_mode(),
        "purchase_request": purchase_request or load_purchase_request(),
        "steps": [],
        "findings": [],
    })
