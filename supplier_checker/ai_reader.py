"""Reader #1: an LLM reads the document and returns structured JSON.

The model is only asked to *read and copy facts* (with the exact supporting
text). It is never asked to approve or reject anything -- that is done by
plain Python in `rules.py`, so the decision logic can be audited and tested.

Providers are tried in order (default: Gemini, then Groq as backup):

    Gemini ──fails (quota / outage / timeout)──► Groq ──fails──► AIReaderError
                                                                 (pipeline then asks a person)

A provider is skipped if its API key is not set. Whichever provider answers,
its output goes through exactly the same verification (quotes must exist in
the PDF, must agree with the parser).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from . import config
from .schemas import Extraction

PROMPT = """You are a careful data-entry clerk for a garment company's purchasing team.
Read the supplier quotation below and fill in the JSON schema.

Strict rules:
1. Copy facts only. Do NOT judge, approve, reject or fix anything.
2. If a value is not clearly written in the document, return null. Never guess or calculate a missing value.
3. Copy numbers exactly as printed (remove thousands separators). Do not recalculate amounts or totals, even if they look wrong.
4. Every *_quote field must be an exact, word-for-word copy of the text in the document (you may join wrapped lines with a space).
5. VAT: only fill vat_rate_percent / vat_amount if VAT is shown as its own separate line. price_includes_vat must always be true or false (never null): true only if the document says prices include VAT/taxes, otherwise false. If true, leave the VAT fields null.
6. TIN/BIN: only fill them if the actual numbers are printed. Phrases like "available on request" mean null.
7. Payment: advance_percent = 0 if the document says there is no advance. For a range like "30 to 90 days", payment_days_min=30 and payment_days_max=90.
8. Delivery: convert weeks to days (1 week = 7 days).
9. Late-delivery penalty: penalty_present=false if there is no such clause. penalty_basis_order_value=true only if it says "of order value" (or equivalent).
10. Items: item_code is the short code in the 'Item' column, i.e. the first token of the item line (e.g. in "E Carton box, 5-ply 3,000 piece ..." the item_code is "E"). Always fill it if present.
11. Put anything ambiguous, contradictory or repeated (e.g. the same term stated twice) into reader_notes.

DOCUMENT TEXT:
<<<
{text}
>>>"""


class AIReaderError(Exception):
    pass


@dataclass
class AIResult:
    extraction: Extraction
    provider: str                                       # e.g. "groq:openai/gpt-oss-120b"
    failures: list[str] = field(default_factory=list)   # providers that failed before this one


# ----------------------------------------------------------------------------- configuration
def _gemini_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _groq_key() -> str | None:
    return os.getenv("GROQ_API_KEY")


def gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", config.DEFAULT_GEMINI_MODEL)


def groq_model() -> str:
    return os.getenv("GROQ_MODEL", config.DEFAULT_GROQ_MODEL)


def provider_order() -> list[str]:
    """Providers to try, in order, that have a key. Override with AI_PROVIDERS=groq,gemini."""
    wanted = [p.strip().lower() for p in os.getenv("AI_PROVIDERS", "gemini,groq").split(",") if p.strip()]
    keys = {"gemini": _gemini_key(), "groq": _groq_key()}
    return [p for p in wanted if keys.get(p)]


def is_configured() -> bool:
    return bool(provider_order())


def model_name() -> str:
    """Human-readable description of the provider chain, e.g. 'gemini-3.5-flash-lite → groq:openai/gpt-oss-120b'."""
    labels = {"gemini": gemini_model(), "groq": f"groq:{groq_model()}"}
    return " → ".join(labels[p] for p in provider_order()) or "none"


# ----------------------------------------------------------------------------- post-processing
def normalise_flags(ex: Extraction) -> Extraction:
    """Apply the schema's own definition to "true only if the document says so" flags.

    For these flags, "not stated" *means* False. The model sometimes returns null
    instead, which the cross-check would otherwise report as a disagreement with the
    parser (False). Found in the first hybrid run: 3/10 packs were wrongly sent to a
    person because of this. Flags where null genuinely means "unknown"
    (e.g. penalty_present) are NOT touched.
    """
    for item in ex.line_items:
        if item.price_includes_vat is None:
            item.price_includes_vat = False
    if ex.penalty_present and ex.penalty_basis_order_value is None:
        ex.penalty_basis_order_value = False
    return ex


MAX_RATE_LIMIT_WAIT = 65  # seconds; free tiers reset per-minute limits within a minute


def _classify(exc: Exception) -> tuple[str, float]:
    """Return (kind, wait_seconds). kind is one of: 'daily', 'rate', 'fatal', 'transient'.

    Learned from live runs:
      * Gemini returns RESOURCE_EXHAUSTED for BOTH per-minute and per-day limits; only
        the quota id tells them apart ("...PerDay...").
      * Groq's free tier hits "tokens per minute (TPM)" after ~2 documents and says
        "Please try again in 7.5s" -- waiting that long works, a fixed 2-4 s backoff does not.
      * 400/401/403/404 (bad request, bad key, unknown model) never succeed on retry.
    """
    msg = str(exc)
    low = msg.lower()
    if "perday" in low.replace(" ", "") or "per day" in low or "(rpd)" in low or "(tpd)" in low:
        return "daily", 0
    if "resource_exhausted" in low or "429" in msg or "rate limit" in low:
        m = re.search(r"(?:try again|retry) in (?:(\d+)m)?([\d.]+)s", msg, re.I) or \
            re.search(r"retryDelay'?\"?:\s*'?\"?(\d+(?:\.\d+)?)s", msg)
        if m and m.lastindex == 2:
            wait = float(m.group(1) or 0) * 60 + float(m.group(2))
        elif m:
            wait = float(m.group(1))
        else:
            wait = 20.0
        return ("rate", wait + 1) if wait <= MAX_RATE_LIMIT_WAIT else ("daily", 0)
    if re.search(r"\b(400|401|403|404)\b", msg) or "not_found" in low or "invalid api key" in low:
        return "fatal", 0
    return "transient", 0


def _with_retries(name: str, call: Callable[[], Extraction], retries: int) -> Extraction:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return call()
        except Exception as exc:  # network, rate limit, invalid JSON ...
            last = exc
            kind, wait = _classify(exc)
            if kind in ("daily", "fatal"):
                # Retrying cannot help today / ever -> move straight to the next provider.
                raise AIReaderError(f"{name} unavailable ({kind}): {str(exc)[:200]}") from exc
            if attempt < retries:
                time.sleep(wait if kind == "rate" else 2 ** attempt)
    raise AIReaderError(f"{name} failed after {retries} attempts: {str(last)[:200]}")


# ----------------------------------------------------------------------------- providers
def _gemini(text: str) -> Extraction:
    from google import genai  # imported lazily so parser-only mode needs no AI libraries
    from google.genai import types

    client = genai.Client(
        api_key=_gemini_key(),
        # Never hang: a stalled call fails after this many ms and is retried.
        http_options=types.HttpOptions(timeout=config.AI_TIMEOUT_SECONDS * 1000),
    )
    response = client.models.generate_content(
        model=gemini_model(),
        contents=PROMPT.format(text=text),
        config={"response_mime_type": "application/json", "response_schema": Extraction, "temperature": 0},
    )
    parsed = response.parsed
    if not isinstance(parsed, Extraction):
        if not response.text:
            raise AIReaderError("Empty response from Gemini.")
        parsed = Extraction.model_validate_json(response.text)  # validate raw JSON ourselves
    return parsed


def _groq(text: str) -> Extraction:
    from groq import Groq

    client = Groq(api_key=_groq_key(), timeout=config.AI_TIMEOUT_SECONDS, max_retries=0)
    schema = json.dumps(Extraction.model_json_schema(), separators=(",", ":"))
    response = client.chat.completions.create(
        model=groq_model(),
        temperature=0,
        # gpt-oss models "think" before answering; low effort keeps a document at ~3k tokens,
        # which matters on the free tier (8,000 tokens/minute).
        **({"reasoning_effort": "low"} if "gpt-oss" in groq_model() else {}),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Return ONLY a JSON object that matches this JSON schema "
                                          f"(use null for unknown values):\n{schema}"},
            {"role": "user", "content": PROMPT.format(text=text)},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise AIReaderError("Empty response from Groq.")
    return Extraction.model_validate_json(content)  # Pydantic rejects anything off-schema


PROVIDERS: dict[str, tuple[Callable[[str], Extraction], Callable[[], str]]] = {
    "gemini": (_gemini, gemini_model),
    "groq": (_groq, lambda: f"groq:{groq_model()}"),
}


def extract(text: str, retries: int = 3) -> AIResult:
    """Try each configured provider in order. Raises AIReaderError only if all of them fail."""
    order = provider_order()
    if not order:
        raise AIReaderError("No AI API key set (GEMINI_API_KEY or GROQ_API_KEY).")
    failures: list[str] = []
    for name in order:
        call, label = PROVIDERS[name]
        try:
            ex = _with_retries(label(), lambda: call(text), retries)
            return AIResult(extraction=normalise_flags(ex), provider=label(), failures=failures)
        except AIReaderError as exc:
            failures.append(str(exc))
    raise AIReaderError("All AI providers failed: " + " | ".join(failures))
