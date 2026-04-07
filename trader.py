# trader.py
import requests
import time

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, NTFY_TOPIC
from trade_logger import log_trade, get_open_position, mark_position_closed, remove_open_order

# Initialize Trading Client
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

def send_push_notification(title, message, trade_type):
    """Sends a real-time push notification to your phone via ntfy.sh"""
    topic = NTFY_TOPIC

    if trade_type == "ENTRY":
        tags = "arrow_up, chart_with_upwards_trend"
    else:
        tags = "arrow_down, moneybag"

    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode(encoding='utf-8'),
            headers={
                "Title": title,
                "Tags": tags
            }
        )
    except Exception as e:
        print(f"Failed to send push notification: {e}")

def execute_trade(trade_data):
    """Executes buy orders and saves the OCC symbol to Supabase."""
    try:
        alert_price = trade_data.get("price")

        if alert_price:
            dynamic_qty = calculate_buy_position_size(alert_price)
            trade_data["quantity"] = dynamic_qty
        else:
            print("No price found in alert. Defaulting to 1 contract.")
            trade_data["quantity"] = 1

        print(f"Action: Buying {trade_data['quantity']} contract(s) of {trade_data['occ_symbol']}...")

        limit_price = round(trade_data['price'] * 1.15, 2)
        market_order_data = LimitOrderRequest(
            symbol=trade_data['occ_symbol'],
            qty=trade_data['quantity'],
            side=OrderSide.BUY,
            limit_price=limit_price,
            time_in_force=TimeInForce.DAY
        )

        market_order = trading_client.submit_order(order_data=market_order_data)
        print(f"Trade Executed! ID: {market_order.id}")
        total_spend = trade_data['quantity'] * trade_data['price'] * 100.0
        send_push_notification(
            title="Trade Executed!",
            message=f"BOUGHT {trade_data['quantity']} {trade_data['ticker']} contract(s) at {trade_data['price']}. Total spend: {total_spend}",
            trade_type="ENTRY"
        )

        log_trade({**trade_data, "type": "ENTRY", "order_id": str(market_order.id), "is_open": True})
        print(f"Logged {trade_data['ticker']} entry: {trade_data['occ_symbol']} | order {market_order.id}")

    except Exception as e:
        print(f"Trade Failed: {e}")

def close_options_position(ticker, action_type, exit_price=None, strike=None, source=None):
    """Looks up the open position from Supabase for a specific source, then sells it via Alpaca.

    source — "waxui" or "zabes". Scopes the lookup so only that trader's position
             is closed, leaving the other source's position untouched.
    strike — when provided, targets the specific contract matching that strike,
             allowing independent exits on two simultaneous same-ticker positions.
    """
    try:
        position = get_open_position(ticker, source=source, strike=strike)

        if not position:
            desc = f"{ticker} {strike}" if strike else ticker
            src_str = f" [{source}]" if source else ""
            print(f"Ignored Exit: No open position found in Supabase for {desc}{src_str}.")
            return

        target_occ = position["occ_symbol"]
        is_full_exit = action_type in ("EXIT_ALL", "EXIT_STOP_LOSS")

        # Cancel any unfilled buy orders before selling
        orders_to_filter = GetOrdersRequest(symbols=[target_occ], status=QueryOrderStatus.OPEN)
        open_orders = trading_client.get_orders(orders_to_filter)

        for open_order in open_orders:
            if not open_order.filled_at:
                print(f"Order {target_occ} id {open_order.id} is unfilled — canceling.")
                trading_client.cancel_order_by_id(open_order.id)
                remove_open_order(ticker, str(open_order.id), source=source)

        # Now get active positions to sell
        all_positions = trading_client.get_all_positions()
        active = [p for p in all_positions if p.symbol == target_occ]

        if not active:
            print(f"Ignored Exit: {target_occ} is no longer in the Alpaca portfolio.")
            mark_position_closed(target_occ, source=source)
            return

        for target_position in active:
            total_qty = float(target_position.qty)
            sell_qty = max(1, int(total_qty / 2)) if action_type == "EXIT_PARTIAL" else int(total_qty)

            print(f"\n--- Executing Exit ---")
            print(f"Contract: {target_occ} | Action: Selling {sell_qty} contract(s)...")

            market_order_data = MarketOrderRequest(
                symbol=target_occ,
                qty=sell_qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )

            sell_order = trading_client.submit_order(order_data=market_order_data)
            print(f"Sell Order Submitted! ID: {sell_order.id}\n")

            # Poll for the actual fill price
            actual_exit_price = exit_price
            for _ in range(10):
                time.sleep(0.5)
                filled = trading_client.get_order_by_id(sell_order.id)
                if filled.filled_avg_price is not None:
                    actual_exit_price = float(filled.filled_avg_price)
                    print(f"Sell filled at ${actual_exit_price:.2f}")
                    break
            else:
                print(f"Fill price not available within timeout, falling back to alert price: {exit_price}")

            total_proceeds = sell_qty * (actual_exit_price or 0) * 100
            title = "Stop Loss Triggered!" if action_type == "EXIT_STOP_LOSS" else "Position Closed!"
            send_push_notification(
                title=title,
                message=f"SOLD {sell_qty} contract(s) of {ticker} at ${actual_exit_price} | Total: ${total_proceeds:,.2f}",
                trade_type="EXIT"
            )

            log_trade({
                "type": action_type, "ticker": ticker, "occ_symbol": target_occ,
                "price": actual_exit_price, "quantity": sell_qty,
                "order_id": str(sell_order.id), "source": source,
            })

            if is_full_exit:
                mark_position_closed(target_occ, source=source)
                print(f"Marked {target_occ} as closed in Supabase.")

    except Exception as e:
        print(f"Error closing position for {ticker}: {e}")

def add_to_position(trade_data):
    """Buys additional contracts for an existing open position looked up from Supabase."""
    try:
        ticker = trade_data.get("ticker")
        source = trade_data.get("source")
        position = get_open_position(ticker, source=source, strike=trade_data.get("strike")) if ticker else None
        if not position:
            src_str = f" [{source}]" if source else ""
            print(f"Ignored ADD: No open position found in Supabase for {ticker}{src_str}.")
            return

        occ_symbol = position["occ_symbol"]
        alert_price = trade_data.get("price")

        if alert_price:
            add_qty = calculate_buy_position_size(alert_price)
        else:
            print("No price found in ADD alert. Defaulting to 1 contract.")
            add_qty = 1

        print(f"\n--- Adding to Position ---")
        print(f"Ticker: {ticker} | Contract: {occ_symbol} | Adding {add_qty} contract(s) at {alert_price}...")

        limit_price = round(alert_price * 1.15, 2)
        order_data = LimitOrderRequest(
            symbol=occ_symbol,
            qty=add_qty,
            side=OrderSide.BUY,
            limit_price=limit_price,
            time_in_force=TimeInForce.DAY
        )

        order = trading_client.submit_order(order_data=order_data)
        print(f"ADD Order Executed! ID: {order.id}")

        total_spend = add_qty * alert_price * 100.0
        send_push_notification(
            title="Added to Position!",
            message=f"BOUGHT {add_qty} more {ticker} contract(s) at {alert_price}. Total spend: ${total_spend:.2f}",
            trade_type="ENTRY"
        )

        log_trade({**trade_data, "type": "ADD", "occ_symbol": occ_symbol,
                   "quantity": add_qty, "order_id": str(order.id), "is_open": True})
        print(f"Logged ADD for {ticker}: order {order.id}")

    except Exception as e:
        print(f"ADD Trade Failed for {trade_data.get('ticker')}: {e}")


def calculate_buy_position_size(entry_price):
    """
    Calculates how many contracts to buy so the total cost
    is approximately 2% of the total portfolio value.
    """
    try:
        account = trading_client.get_account()
        portfolio_value = float(account.portfolio_value)

        target_spend = portfolio_value * 0.02
        contract_cost = float(entry_price) * 100

        if contract_cost <= 0:
            print("Warning: Contract price is 0. Defaulting to 1 contract.")
            return 1

        qty = int(target_spend // contract_cost)

        if qty < 1:
            print(f"Warning: 2% of portfolio (${target_spend:.2f}) cannot afford a $({contract_cost:.2f}) contract.")
            print("Defaulting to 1 contract to stay in the trade.")
            return 1

        print(f"Position Sizing: Portfolio=${portfolio_value:.2f} | 2%=${target_spend:.2f} | Buying {qty} contract(s).")
        return qty

    except Exception as e:
        print(f"Error calculating position size: {e}. Defaulting to 1 contract.")
        return 1
