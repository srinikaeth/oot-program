# trade_logger.py
# Logs all trade events to Supabase and calculates realized P&L on exits.
# Also serves as the single source of truth for active position tracking,
# replacing the active_trades.json file.
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
#       is_open     BOOLEAN DEFAULT FALSE  -- TRUE while position is active
#   );
#
#   -- If the table already exists, add the new columns:
#   ALTER TABLE trades ADD COLUMN order_id TEXT;
#   ALTER TABLE trades ADD COLUMN is_open BOOLEAN DEFAULT FALSE;

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
# Active position tracker — replaces active_trades.json
# ---------------------------------------------------------------------------

def get_open_position(ticker: str) -> Optional[dict]:
    """
    Returns {'occ_symbol': str, 'order_ids': [str]} for the active position
    on a ticker, or None if no open position exists.
    """
    client = _get_client()
    if not client:
        return None
    try:
        response = (
            client.table("trades")
            .select("occ_symbol, order_id")
            .eq("ticker", ticker)
            .eq("is_open", True)
            .execute()
        )
        rows = response.data
        if not rows:
            return None
        occ_symbol = rows[0]["occ_symbol"]
        order_ids = [r["order_id"] for r in rows if r.get("order_id")]
        return {"occ_symbol": occ_symbol, "order_ids": order_ids}
    except Exception as e:
        print(f"[Supabase] Failed to get open position for {ticker}: {e}")
        return None


def get_all_open_positions() -> dict:
    """
    Returns {ticker: occ_symbol} for all tickers with an open position.
    Used by the stop loss monitor.
    """
    client = _get_client()
    if not client:
        return {}
    try:
        response = (
            client.table("trades")
            .select("ticker, occ_symbol")
            .eq("is_open", True)
            .execute()
        )
        # Multiple open rows per ticker (ENTRY + ADDs) — deduplicate
        result = {}
        for row in response.data:
            result[row["ticker"]] = row["occ_symbol"]
        return result
    except Exception as e:
        print(f"[Supabase] Failed to get all open positions: {e}")
        return {}


def mark_position_closed(ticker: str):
    """Marks all open rows for a ticker as is_open = False."""
    client = _get_client()
    if not client:
        return
    try:
        client.table("trades").update({"is_open": False}).eq("ticker", ticker).eq("is_open", True).execute()
        print(f"[Supabase] Marked {ticker} position as closed.")
    except Exception as e:
        print(f"[Supabase] Failed to mark {ticker} as closed: {e}")


def remove_open_order(ticker: str, order_id: str):
    """
    Marks a specific order row as is_open = False.
    Called when an unfilled buy order is canceled on exit.
    """
    client = _get_client()
    if not client:
        return
    try:
        client.table("trades").update({"is_open": False}).eq("ticker", ticker).eq("order_id", order_id).execute()
        print(f"[Supabase] Removed open order {order_id} for {ticker}.")
    except Exception as e:
        print(f"[Supabase] Failed to remove order {order_id} for {ticker}: {e}")


# ---------------------------------------------------------------------------
# Trade logging
# ---------------------------------------------------------------------------

def _calculate_pnl(client: Client, ticker: str, occ_symbol: str, exit_price: float, exit_qty: int) -> Optional[float]:
    """
    Computes realized P&L for an exit by looking up all prior buys for this
    contract and calculating the weighted average cost basis.

    P&L = (exit_price - avg_cost_basis) * exit_qty * 100
    """
    try:
        response = (
            client.table("trades")
            .select("price, quantity")
            .eq("ticker", ticker)
            .eq("occ_symbol", occ_symbol)
            .in_("type", ["ENTRY", "ADD"])
            .execute()
        )
        rows = response.data
        if not rows:
            print(f"P&L calc: no prior buy records found for {occ_symbol}.")
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

    For ENTRY and ADD rows, pass order_id and is_open=True to keep the position
    tracker up to date. For exits, P&L is calculated automatically.

    trade_data keys: type, ticker, occ_symbol, price, quantity,
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

        total_value = round(price * quantity * 100, 2) if price and quantity else None

        pnl = None
        if trade_type in ("EXIT_ALL", "EXIT_PARTIAL", "EXIT_STOP_LOSS") and price and quantity and occ_symbol:
            pnl = _calculate_pnl(client, ticker, occ_symbol, price, quantity)

        row = {
            "ticker": ticker,
            "occ_symbol": occ_symbol,
            "type": trade_type,
            "price": price,
            "quantity": quantity,
            "total_value": total_value,
            "pnl": pnl,
            "order_id": order_id,
            "is_open": is_open,
        }

        client.table("trades").insert(row).execute()

        pnl_str = f" | P&L: ${pnl:+.2f}" if pnl is not None else ""
        print(f"[Supabase] Logged {trade_type} — {ticker} x{quantity} @ {price}{pnl_str}")

    except Exception as e:
        print(f"[Supabase] Failed to log trade: {e}")
