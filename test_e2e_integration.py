# test_e2e_integration.py
#
# End-to-end integration tests. Requires:
#   - The Flask server running locally:  python server.py
#   - Paper trading enabled in Alpaca
#
# Run with:  python -m pytest test_e2e_integration.py -v -s

import time
import unittest
from datetime import datetime, timedelta, timezone

import requests
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderStatus, QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, API_SECRET_KEY
from trade_logger import mark_position_closed, get_all_open_positions

URL = "http://127.0.0.1:5001/discord-webhook"
HEADERS = {"X-Bot-Key": API_SECRET_KEY}
WAIT_SECONDS = 7  # Time to allow LLM parsing + Alpaca order submission

trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_friday() -> str:
    """Returns the next Friday as MM/DD, used for expiry dates in test signals."""
    today = datetime.now()
    days_ahead = (4 - today.weekday()) % 7 or 7  # 4 = Friday
    return (today + timedelta(days=days_ahead)).strftime("%m/%d")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def send_signal(text: str, title: str = "Waxui Alerts") -> requests.Response:
    return requests.post(URL, json={"title": title, "text": text}, headers=HEADERS)


def find_orders_since(ticker: str, side: OrderSide, since: datetime) -> list:
    """Returns orders for a ticker/side placed after `since`. Uses timestamp
    filtering instead of a fixed limit so accumulated history never blocks detection."""
    req = GetOrdersRequest(status=QueryOrderStatus.ALL, after=since, limit=100)
    orders = trading_client.get_orders(req)
    return [o for o in orders if o.symbol.startswith(ticker) and o.side == side]


def find_exit_actions_since(ticker: str, since: datetime) -> list:
    """Returns actions that represent an exit after `since`:
    - A SELL order (position was filled and sold), OR
    - A canceled BUY order (unfilled limit order was canceled on exit).
    Both are valid exit outcomes in paper trading."""
    req = GetOrdersRequest(status=QueryOrderStatus.ALL, after=since, limit=100)
    orders = trading_client.get_orders(req)
    sells = [o for o in orders if o.symbol.startswith(ticker) and o.side == OrderSide.SELL]
    canceled_buys = [o for o in orders if o.symbol.startswith(ticker)
                     and o.side == OrderSide.BUY and o.status == OrderStatus.CANCELED]
    return sells + canceled_buys


def cancel_open_orders(ticker: str):
    """Cancels all open orders for a ticker."""
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
    for order in trading_client.get_orders(req):
        if order.symbol.startswith(ticker):
            try:
                trading_client.cancel_order_by_id(order.id)
            except Exception:
                pass


def reset_tracker():
    """Closes all open positions in Supabase between tests."""
    open_positions = get_all_open_positions()  # {occ_symbol: ticker}
    for occ_symbol in open_positions:
        mark_position_closed(occ_symbol)


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------

class TestE2ETrading(unittest.TestCase):

    def setUp(self):
        """Cancel open orders and wipe memory before each test."""
        for ticker in ["SPY", "HOOD", "SPX"]:
            cancel_open_orders(ticker)
        reset_tracker()
        time.sleep(1)

    # --- Auth ---

    def test_unauthorized_request_returns_401(self):
        """Requests without the correct API key must be rejected."""
        response = requests.post(URL, json={"title": "Test", "text": "SPY here"})
        self.assertEqual(response.status_code, 401)

    def test_authorized_request_returns_200(self):
        """A valid request with the correct key should always return 200."""
        response = send_signal("@Premium  VIX back over 20. Bears reclaim control.")
        self.assertEqual(response.status_code, 200)

    # --- IGNORE ---

    def test_ignore_market_chatter_creates_no_order(self):
        """Pure market commentary should not trigger any new orders."""
        t0 = now_utc()
        send_signal("@Premium  VIX back over 20. Markets cooked. Bears reclaim control.")
        time.sleep(WAIT_SECONDS)

        req = GetOrdersRequest(status=QueryOrderStatus.ALL, after=t0, limit=100)
        new_orders = trading_client.get_orders(req)
        self.assertEqual(len(new_orders), 0, f"Expected no new orders for market chatter, got {len(new_orders)}")

    # --- ENTRY / EXIT_ALL ---

    def test_entry_then_exit_all(self):
        """Full cycle: ENTRY creates a BUY order, EXIT_ALL creates an exit action."""
        exp = _next_friday()
        t0 = now_utc()

        send_signal(f"@Premium  LOTTO\nSPY here\n{exp} 582C\nAvg, 2.20\nStops under lows.")
        time.sleep(WAIT_SECONDS)

        buys = find_orders_since("SPY", OrderSide.BUY, t0)
        self.assertTrue(buys, "Expected a BUY order after ENTRY signal")

        t1 = now_utc()
        send_signal("@Premium  Closed SPY here")
        time.sleep(WAIT_SECONDS)

        exits = find_exit_actions_since("SPY", t1)
        self.assertTrue(exits, "Expected a SELL or canceled BUY after EXIT_ALL signal")

    def test_entry_stopped_out(self):
        """'Stopped out' phrasing should trigger an exit action."""
        exp = _next_friday()
        t0 = now_utc()

        send_signal(f"@Premium  SPY here\n{exp} 580P\nAvg, 1.50")
        time.sleep(WAIT_SECONDS)

        buys = find_orders_since("SPY", OrderSide.BUY, t0)
        self.assertTrue(buys, "Expected a BUY order after ENTRY signal")

        t1 = now_utc()
        send_signal("@Premium  Stopped out of SPY 🔻\n2026 is the year of the balance")
        time.sleep(WAIT_SECONDS)

        exits = find_exit_actions_since("SPY", t1)
        self.assertTrue(exits, "Expected a SELL or canceled BUY after 'Stopped out' signal")

    # --- EXIT_PARTIAL ---

    def test_entry_then_exit_partial(self):
        """EXIT_PARTIAL should sell fewer contracts than were originally bought."""
        exp = _next_friday()
        t0 = now_utc()

        send_signal(f"@Premium  SPY here\n{exp} 580P\nAvg, 1.50")
        time.sleep(WAIT_SECONDS)

        buys = find_orders_since("SPY", OrderSide.BUY, t0)
        self.assertTrue(buys, "Expected a BUY order after ENTRY signal")
        buy_qty = int(buys[0].qty)

        t1 = now_utc()
        send_signal("@Premium  Trim SPY here\n1.50 - 2.80 ✅ 40%\nHolding most.")
        time.sleep(WAIT_SECONDS)

        sells = find_orders_since("SPY", OrderSide.SELL, t1)
        self.assertTrue(sells, "Expected a SELL order after EXIT_PARTIAL signal")
        sell_qty = int(sells[0].qty)
        self.assertLess(sell_qty, buy_qty, f"Partial exit qty ({sell_qty}) should be less than entry qty ({buy_qty})")

    # --- ADD ---

    def test_entry_then_add_then_exit_all(self):
        """ADD signal should place a second BUY, EXIT_ALL should then close everything."""
        exp = _next_friday()
        t0 = now_utc()

        send_signal(f"@Premium  SPY here\n{exp} 582C\nAvg, 2.20")
        time.sleep(WAIT_SECONDS)

        buys_after_entry = find_orders_since("SPY", OrderSide.BUY, t0)
        self.assertTrue(buys_after_entry, "Expected a BUY order after ENTRY")

        t1 = now_utc()
        send_signal("@Premium  Added to SPY @1.90\nNew Avg, is 2.05")
        time.sleep(WAIT_SECONDS)

        buys_after_add = find_orders_since("SPY", OrderSide.BUY, t1)
        self.assertTrue(buys_after_add, "Expected a second BUY order after ADD signal")

        t2 = now_utc()
        send_signal("@Premium  Stopped out of SPY 🔻")
        time.sleep(WAIT_SECONDS)

        exits = find_exit_actions_since("SPY", t2)
        self.assertTrue(exits, "Expected an exit action after EXIT_ALL following ADD")

    def test_add_without_open_position_is_ignored(self):
        """ADD signal with no existing position in memory should not place any order."""
        t0 = now_utc()
        send_signal("@Premium  Added to SPY @1.90\nNew Avg, is 2.05")
        time.sleep(WAIT_SECONDS)

        buys = find_orders_since("SPY", OrderSide.BUY, t0)
        self.assertEqual(len(buys), 0, "ADD with no open position should not create a BUY order")

    # --- Stale exit ignored ---

    def test_exit_with_no_open_position_is_ignored(self):
        """EXIT signal for a ticker not in memory should not crash and return 200."""
        t0 = now_utc()
        response = send_signal("@Premium  Closed HOOD here")
        self.assertEqual(response.status_code, 200)

        time.sleep(WAIT_SECONDS)
        exits = find_exit_actions_since("HOOD", t0)
        self.assertEqual(len(exits), 0, "No exit action should occur if HOOD was never bought")

    # --- Non-SPY ticker ---

    def test_hood_full_cycle(self):
        """Verify non-SPY tickers are handled correctly end-to-end."""
        exp = _next_friday()
        t0 = now_utc()

        send_signal(f"@Premium  *Riskier*\nHOOD here\n{exp} 78C\nAvg, 1.50")
        time.sleep(WAIT_SECONDS)

        buys = find_orders_since("HOOD", OrderSide.BUY, t0)
        self.assertTrue(buys, "Expected a BUY order for HOOD")

        t1 = now_utc()
        send_signal("@Premium  Closed HOOD here")
        time.sleep(WAIT_SECONDS)

        exits = find_exit_actions_since("HOOD", t1)
        self.assertTrue(exits, "Expected a SELL or canceled BUY for HOOD after closing")

    # --- Slang normalization ---

    def test_spyyy_slang_is_parsed_as_spy(self):
        """Ticker slang like 'SPYYY' should be normalized to 'SPY'."""
        exp = _next_friday()
        t0 = now_utc()

        send_signal(f"@Premium  SPYYY here\n{exp} 582C\nAvg, 2.20")
        time.sleep(WAIT_SECONDS)

        buys = find_orders_since("SPY", OrderSide.BUY, t0)
        self.assertTrue(buys, "Expected SPYYY to be normalized to SPY and placed as a BUY order")


if __name__ == "__main__":
    unittest.main(verbosity=2)
