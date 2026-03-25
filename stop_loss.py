# stop_loss.py
# Runs a background thread that polls open positions every STOP_LOSS_INTERVAL seconds.
# If any tracked position is down STOP_LOSS_PCT or more, it is closed automatically.

import threading
import time

from config import STOP_LOSS_PCT, STOP_LOSS_INTERVAL
from memory import load_tracker
from trader import close_options_position, trading_client


def _find_ticker(tracker: dict, occ_symbol: str) -> str | None:
    """Returns the ticker key for a given OCC symbol, or None if not tracked."""
    for ticker, data in tracker.items():
        if data.get("occ_symbol") == occ_symbol:
            return ticker
    return None


def check_stop_losses():
    """
    Checks all open Alpaca positions against the tracker. Closes any position
    whose unrealized loss has reached or exceeded STOP_LOSS_PCT.
    """
    tracker = load_tracker()
    if not tracker:
        return

    try:
        positions = trading_client.get_all_positions()
    except Exception as e:
        print(f"[Stop Loss] Failed to fetch positions: {e}")
        return

    for position in positions:
        ticker = _find_ticker(tracker, position.symbol)
        if not ticker:
            continue  # Position not in our tracker — ignore

        unrealized_pct = float(position.unrealized_plpc)  # e.g. -0.43 for -43%

        if unrealized_pct <= -STOP_LOSS_PCT:
            current_price = float(position.current_price)
            print(
                f"[Stop Loss] TRIGGERED for {ticker} ({position.symbol}): "
                f"{unrealized_pct:.1%} loss. Closing at ${current_price:.2f}."
            )
            close_options_position(ticker, "EXIT_STOP_LOSS", current_price)


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
