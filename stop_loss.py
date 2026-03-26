# stop_loss.py
# Runs a background thread that polls open positions every STOP_LOSS_INTERVAL seconds.
# If any tracked position is down STOP_LOSS_PCT or more, it is closed automatically.

import threading
import time

from config import STOP_LOSS_PCT, STOP_LOSS_INTERVAL
from trade_logger import get_all_open_positions
from trader import close_options_position, trading_client


def check_stop_losses():
    """
    Checks all open Alpaca positions against Supabase. Closes any position
    whose unrealized loss has reached or exceeded STOP_LOSS_PCT.
    """
    open_positions = get_all_open_positions()  # {occ_symbol: ticker}
    if not open_positions:
        return

    try:
        alpaca_positions = trading_client.get_all_positions()
    except Exception as e:
        print(f"[Stop Loss] Failed to fetch positions from Alpaca: {e}")
        return

    for position in alpaca_positions:
        ticker = open_positions.get(position.symbol)
        if not ticker:
            continue  # Not a position we opened — ignore

        unrealized_pct = float(position.unrealized_plpc)  # e.g. -0.43 for -43%

        if unrealized_pct <= -STOP_LOSS_PCT:
            current_price = float(position.current_price)
            # Extract strike from occ_symbol so multi-position same-ticker exits
            # target the correct contract. OCC format: TICKER + YYMMDD + C/P + 8-digit-strike
            # e.g. SPY260325P00658000 → strike field = "00658000" (chars -8 to end)
            occ = position.symbol
            raw_strike = occ[-8:]  # e.g. "00658000"
            strike = str(int(raw_strike) // 1000)  # e.g. "658"
            print(
                f"[Stop Loss] TRIGGERED for {ticker} ({occ}): "
                f"{unrealized_pct:.1%} loss. Closing at ${current_price:.2f}."
            )
            close_options_position(ticker, "EXIT_STOP_LOSS", current_price, strike)


def _monitor_loop():
    while True:
        check_stop_losses()
        time.sleep(STOP_LOSS_INTERVAL)


def start_stop_loss_monitor():
    """Starts the stop loss monitor as a daemon background thread."""
    thread = threading.Thread(target=_monitor_loop, daemon=True, name="StopLossMonitor")
    thread.start()
    print(
        f"[Stop Loss] Monitor started — "
        f"checking every {STOP_LOSS_INTERVAL}s, threshold: -{STOP_LOSS_PCT:.0%}"
    )
