# trade_logger.py
# Logs all trade events to Supabase and calculates realized P&L on exits.
# Also serves as the single source of truth for active position tracking.
#
# Run these migrations once in the Supabase SQL editor before using:
#
#   CREATE TABLE trades (
#       id          SERIAL PRIMARY KEY,
#       timestamp   TIMESTAMPTZ DEFAULT NOW(),
#       ticker      TEXT NOT NULL,
#       occ_symbol  TEXT,
#       type        TEXT NOT NULL,   -- ENTRY | ADD | EXIT_PARTIAL | EXIT_ALL | EXIT_STOP_LOSS
#       price       NUMERIC,
#       quantity    INT,
#       total_value NUMERIC,         -- price * qty * 100 (cost / proceeds in dollars)
#       pnl         NUMERIC,         -- realized P&L in dollars, populated on exits
#       order_id    TEXT,            -- Alpaca order ID
#       is_open     BOOLEAN DEFAULT FALSE,
#       source      TEXT             -- "waxui" | "zabes" — identifies which trader's signal
#   );
#
#   -- If the table already exists, add the new column:
#   ALTER TABLE trades ADD COLUMN source TEXT;

from typing import Optional
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

_client: Optional[Client] = None


def _get_client() -> Optional[Client]:
    """Returns a cached Supabase client, or None if credentials are not configured."""
    global _client
    if _client:
        return _client
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase credentials not configured. Skipping DB logging.")
        return None
    _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ---------------------------------------------------------------------------
# Active position tracker
# ---------------------------------------------------------------------------

def get_open_position(ticker: str, source: str, strike: Optional[str] = None) -> Optional[dict]:
    """
    Returns {'occ_symbol': str, 'order_ids': [str]} for the active position
    on a ticker for a specific source, or None if no open position exists.

    source — "waxui" or "zabes". Scopes the lookup so each trader's positions
             are tracked independently.

    strike — when provided, only rows whose occ_symbol contains that strike are
             considered, allowing two simultaneous same-ticker positions to be
             addressed independently.
    """
    client = _get_client()
    if not client:
        return None
    try:
        response = (
            client.table("trades")
            .select("occ_symbol, order_id")
            .eq("ticker", ticker)
            .eq("source", source)
            .eq("is_open", True)
            .execute()
        )
        rows = response.data
        if not rows:
            return None

        if strike:
            strike_padded = f"{int(float(strike)) * 1000:08d}"
            rows = [r for r in rows if strike_padded in (r.get("occ_symbol") or "")]
            if not rows:
                return None

        occ_symbol = rows[-1]["occ_symbol"]
        order_ids = [r["order_id"] for r in rows
                     if r.get("order_id") and r["occ_symbol"] == occ_symbol]
        return {"occ_symbol": occ_symbol, "order_ids": order_ids}
    except Exception as e:
        print(f"[Supabase] Failed to get open position for {ticker} ({source}): {e}")
        return None


def get_all_open_positions(source: Optional[str] = None) -> dict:
    """
    Returns {occ_symbol: {"ticker": str, "source": str}} for every open contract.

    source — when provided, filters to only that trader's positions. Pass None
             to get all open positions across sources (used by the stop loss monitor).
    """
    client = _get_client()
    if not client:
        return {}
    try:
        query = (
            client.table("trades")
            .select("ticker, occ_symbol, source")
            .eq("is_open", True)
        )
        if source:
            query = query.eq("source", source)
        response = query.execute()
        result = {}
        for row in response.data:
            result[row["occ_symbol"]] = {"ticker": row["ticker"], "source": row["source"]}
        return result
    except Exception as e:
        print(f"[Supabase] Failed to get all open positions: {e}")
        return {}


def mark_position_closed(occ_symbol: str, source: Optional[str] = None):
    """
    Marks all open rows for a specific contract as is_open = False.

    source — when provided, adds a filter so only that trader's rows are closed,
             preventing a Waxui exit from closing a Zabes position on the same
             contract. When None (e.g. test teardown), closes all matching rows.
    """
    client = _get_client()
    if not client:
        return
    try:
        query = (
            client.table("trades")
            .update({"is_open": False})
            .eq("occ_symbol", occ_symbol)
            .eq("is_open", True)
        )
        if source:
            query = query.eq("source", source)
        query.execute()
        src_str = f" [{source}]" if source else ""
        print(f"[Supabase] Marked {occ_symbol}{src_str} as closed.")
    except Exception as e:
        print(f"[Supabase] Failed to mark {occ_symbol} as closed: {e}")


def remove_open_order(ticker: str, order_id: str, source: Optional[str] = None):
    """
    Marks a specific order row as is_open = False.
    Called when an unfilled buy order is canceled on exit.
    """
    client = _get_client()
    if not client:
        return
    try:
        query = (
            client.table("trades")
            .update({"is_open": False})
            .eq("ticker", ticker)
            .eq("order_id", order_id)
        )
        if source:
            query = query.eq("source", source)
        query.execute()
        print(f"[Supabase] Removed open order {order_id} for {ticker}.")
    except Exception as e:
        print(f"[Supabase] Failed to remove order {order_id} for {ticker}: {e}")


# ---------------------------------------------------------------------------
# Trade logging
# ---------------------------------------------------------------------------

def _calculate_pnl(client: Client, ticker: str, occ_symbol: str, source: str,
                   exit_price: float, exit_qty: int) -> Optional[float]:
    """
    Computes realized P&L by looking up all prior buys for this contract and
    source, then calculating the weighted average cost basis.

    Filtering by source ensures Zabes' buy prices don't affect Waxui's P&L.

    P&L = (exit_price - avg_cost_basis) * exit_qty * 100
    """
    try:
        response = (
            client.table("trades")
            .select("price, quantity")
            .eq("ticker", ticker)
            .eq("occ_symbol", occ_symbol)
            .eq("source", source)
            .in_("type", ["ENTRY", "ADD"])
            .execute()
        )
        rows = response.data
        if not rows:
            print(f"P&L calc: no prior buy records found for {occ_symbol} ({source}).")
            return None

        total_qty = sum(r["quantity"] for r in rows)
        total_cost = sum(r["price"] * r["quantity"] for r in rows)
        avg_cost = total_cost / total_qty if total_qty > 0 else 0

        pnl = (exit_price - avg_cost) * exit_qty * 100
        return round(pnl, 2)

    except Exception as e:
        print(f"P&L calculation failed: {e}")
        return None


def log_trade(trade_data: dict):
    """
    Inserts a trade event into Supabase.

    trade_data keys: type, ticker, occ_symbol, price, quantity, source,
                     order_id (optional), is_open (optional, default False)
    """
    client = _get_client()
    if not client:
        return

    try:
        trade_type = trade_data.get("type")
        ticker = trade_data.get("ticker")
        occ_symbol = trade_data.get("occ_symbol")
        price = trade_data.get("price")
        quantity = trade_data.get("quantity")
        order_id = trade_data.get("order_id")
        is_open = trade_data.get("is_open", False)
        source = trade_data.get("source")

        total_value = round(price * quantity * 100, 2) if price and quantity else None

        pnl = None
        if trade_type in ("EXIT_ALL", "EXIT_PARTIAL", "EXIT_STOP_LOSS") and price and quantity and occ_symbol and source:
            pnl = _calculate_pnl(client, ticker, occ_symbol, source, price, quantity)

        row = {
            "ticker":      ticker,
            "occ_symbol":  occ_symbol,
            "type":        trade_type,
            "price":       price,
            "quantity":    quantity,
            "total_value": total_value,
            "pnl":         pnl,
            "order_id":    order_id,
            "is_open":     is_open,
            "source":      source,
        }

        client.table("trades").insert(row).execute()

        pnl_str = f" | P&L: ${pnl:+.2f}" if pnl is not None else ""
        src_str = f" [{source}]" if source else ""
        print(f"[Supabase] Logged {trade_type}{src_str} — {ticker} x{quantity} @ {price}{pnl_str}")

    except Exception as e:
        print(f"[Supabase] Failed to log trade: {e}")
