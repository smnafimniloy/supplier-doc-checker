"""All numbers from `company-rules.md` live here, in one place.

If the company changes a rule (e.g. the advance limit), change it here only.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"
PURCHASE_REQUEST_CSV = DATA_DIR / "purchase-request.csv"
EXPECTED_CSV = DATA_DIR / "expected-decisions.csv"

# --- Reject rules -----------------------------------------------------------
PRICE_REJECT_OVER_PCT = 3.0        # R1: unit price > 3% above maximum
ADVANCE_MAX_PCT = 20.0             # R2: advance > 20%
# R3: no late-delivery penalty clause
# R4: TIN or BIN missing
DELIVERY_REJECT_OVER_DAYS = 45     # R5: delivery later than 45 days

# --- Needs-a-person rules ---------------------------------------------------
# H1: price above maximum but by no more than 3%
QTY_TOLERANCE_PCT = 5.0            # H2: quantity differs by more than 5%
PAYMENT_DAYS_MIN = 30              # H3: payment outside 30..60 days after delivery
PAYMENT_DAYS_MAX = 60
DELIVERY_REVIEW_FROM_DAYS = 31     # H4: delivery in 31..45 days
VAT_RATE_PCT = 15.0                # H5: VAT not shown separately at 15%
MONEY_TOLERANCE = 0.01             # H6: numbers must add up (BDT, to the paisa)
VALIDITY_MIN_DAYS = 30             # H7: validity < 30 days

# --- Other notes -------------------------------------------------------------
PENALTY_MIN_PCT_PER_WEEK = 0.5     # penalty must be >= 0.5% of order value / week

# Description similarity (0..1) below which an item is treated as "not the item we asked for".
DESCRIPTION_MATCH_MIN = 0.6

# --- AI model ----------------------------------------------------------------
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"   # primary (free tier: 20 requests/day/model)
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"       # backup if Gemini fails (free tier: ~1,000 requests/day)
AI_TIMEOUT_SECONDS = 60            # per AI call; retried up to 3 times (not on daily-quota errors)
