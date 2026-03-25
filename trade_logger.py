# trade_logger.py
# Logs all trade events to Supabase and calculates realized P&L on exits.
#
# Required Supabase table (run once in the Supabase SQL editor):
#
#   CREATE TABLE trades (
#       id          SERIAL PRIMARY KEY,
#       timestamp   TIMESTAMPTZ DEFAULT NOW(),
#       ticker      TEXT NOT NULL,
#       occ_symbol  TEXT,
#       type        TEXT NOT NULL,   -- ENTRY | ADD | EXIT_PARTIAL | EXIT_ALL
#       price       NUMERIC,
#       quantity    INT,
#       total_value NUMERIC,         -- price * qty * 100 (cost / proceeds in dollars)
#       pnl         NUMERIC          -- realized P&L in dollars, populated on exits
#   );

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

    For exits, automatically calculates and stores realized P&L.
    trade_data must include: type, ticker, occ_symbol, price, quantity
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
        }

        client.table("trades").insert(row).execute()

        pnl_str = f" | P&L: ${pnl:+.2f}" if pnl is not None else ""
        print(f"[Supabase] Logged {trade_type} — {ticker} x{quantity} @ {price}{pnl_str}")

    except Exception as e:
        print(f"[Supabase] Failed to log trade: {e}")
