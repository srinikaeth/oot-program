# eval_logger.py
# Logs every incoming Discord message alongside what the parser returned.
# Human labels are added later via the dashboard labeling UI.
#
# Run this migration once in the Supabase SQL editor:
#
#   CREATE TABLE parser_evals (
#       id              SERIAL PRIMARY KEY,
#       timestamp       TIMESTAMPTZ DEFAULT NOW(),
#       source          TEXT,            -- Discord chat title (e.g. "Waxui Alerts")
#       raw_message     TEXT NOT NULL,
#       -- LLM parser output
#       parsed_type     TEXT,            -- ENTRY | ADD | EXIT_ALL | EXIT_PARTIAL | EXIT_STOP_LOSS | IGNORE
#       parsed_ticker   TEXT,
#       parsed_exp_date TEXT,
#       parsed_strike   TEXT,
#       parsed_opt_type TEXT,
#       parsed_price    NUMERIC,
#       -- Human labels (filled via the dashboard)
#       human_type      TEXT,
#       human_ticker    TEXT,
#       human_exp_date  TEXT,
#       human_strike    TEXT,
#       human_opt_type  TEXT,
#       human_price     NUMERIC,
#       -- Accuracy verdict
#       is_correct      BOOLEAN,         -- set automatically when human label is submitted
#       notes           TEXT             -- optional free-text comment from labeler
#   );

from typing import Optional
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

_client: Optional[Client] = None


def _get_client() -> Optional[Client]:
    global _client
    if _client:
        return _client
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def log_parse_eval(raw_message: str, source: str, trade_data: Optional[dict]):
    """
    Inserts one row per incoming message recording the raw text and
    whatever the LLM parser returned (or IGNORE if it returned None).
    """
    client = _get_client()
    if not client:
        return

    try:
        row = {
            "source":          source,
            "raw_message":     raw_message,
            "parsed_type":     trade_data.get("type")     if trade_data else "IGNORE",
            "parsed_ticker":   trade_data.get("ticker")   if trade_data else None,
            "parsed_exp_date": trade_data.get("exp_date") if trade_data else None,
            "parsed_strike":   trade_data.get("strike")   if trade_data else None,
            "parsed_opt_type": trade_data.get("opt_type") if trade_data else None,
            "parsed_price":    trade_data.get("price")    if trade_data else None,
        }
        client.table("parser_evals").insert(row).execute()
    except Exception as e:
        print(f"[Eval Logger] Failed to log parse eval: {e}")


def submit_label(row_id: int, human_fields: dict, parsed_fields: dict, notes: str):
    """
    Saves human labels for a given eval row and computes is_correct.

    human_fields / parsed_fields are dicts with keys:
    type, ticker, exp_date, strike, opt_type, price
    """
    client = _get_client()
    if not client:
        return

    try:
        is_correct = _compute_is_correct(human_fields, parsed_fields)

        client.table("parser_evals").update({
            "human_type":     human_fields.get("type"),
            "human_ticker":   human_fields.get("ticker"),
            "human_exp_date": human_fields.get("exp_date"),
            "human_strike":   human_fields.get("strike"),
            "human_opt_type": human_fields.get("opt_type"),
            "human_price":    human_fields.get("price"),
            "is_correct":     is_correct,
            "notes":          notes or None,
        }).eq("id", row_id).execute()

    except Exception as e:
        print(f"[Eval Logger] Failed to submit label for row {row_id}: {e}")


def _compute_is_correct(human: dict, parsed: dict) -> bool:
    """
    Returns True if the human label agrees with the parsed output on all
    relevant fields. Price is compared within a $0.01 tolerance.
    """
    if _norm(human.get("type")) != _norm(parsed.get("type")):
        return False

    trade_type = _norm(human.get("type"))

    if trade_type == "ignore":
        return True  # Only field that matters for IGNORE is type

    if _norm(human.get("ticker")) != _norm(parsed.get("ticker")):
        return False

    if trade_type == "entry":
        if _norm(human.get("exp_date")) != _norm(parsed.get("exp_date")):
            return False
        if _norm(human.get("strike")) != _norm(parsed.get("strike")):
            return False
        if _norm(human.get("opt_type")) != _norm(parsed.get("opt_type")):
            return False

    # Price comparison — allow $0.01 tolerance for float imprecision
    h_price = human.get("price")
    p_price = parsed.get("price")
    if h_price is not None and p_price is not None:
        if abs(float(h_price) - float(p_price)) > 0.01:
            return False

    return True


def _norm(val) -> Optional[str]:
    """Normalise a field value to lowercase string for comparison, or None."""
    if val is None or str(val).strip() == "":
        return None
    return str(val).strip().lower()
