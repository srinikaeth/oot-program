# trader.py
import requests
import time

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, NTFY_TOPIC
from memory import load_tracker, save_tracker
from trade_logger import log_trade

# Initialize Trading Client
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

def send_push_notification(title, message, trade_type):
    """Sends a real-time push notification to your phone via ntfy.sh"""
    # Replace this with your secret topic name!
    topic = NTFY_TOPIC 
    
    # Assign the correct emojis based on the action
    if trade_type == "ENTRY":
        tags = "arrow_up, chart_with_upwards_trend" # ⬆️ 📈
    else:
        tags = "arrow_down, moneybag" # ⬇️ 💰
        
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
    """Executes buy orders and saves the OCC symbol to memory."""
    try:

        # Getting quantity to execute trade
        alert_price = trade_data.get("price")
        
        if alert_price:
            dynamic_qty = calculate_buy_position_size(alert_price)
            trade_data["quantity"] = dynamic_qty
        else:
            print("No price found in alert. Defaulting to 1 contract.")
            trade_data["quantity"] = 1

        print(f"Action: Buying {trade_data['quantity']} contract(s) of {trade_data['occ_symbol']}...")

        market_order_data = LimitOrderRequest(
            symbol=trade_data['occ_symbol'],
            qty=trade_data['quantity'],
            side=OrderSide.BUY,
            limit_price=trade_data['price'],
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
        
        # Save to memory immediately after buying
        tracker = load_tracker()
        if not tracker or not trade_data['ticker'] in tracker:  # If it doesn't exist already
            tracker[trade_data['ticker']] = {"occ_symbol": trade_data['occ_symbol'], "ids": [str(market_order.id)]}
        else:
            tracker[trade_data['ticker']]['ids'].append(str(market_order.id))

        save_tracker(tracker)
        print(f"Memorized {trade_data['ticker']} active contract: {trade_data['occ_symbol']} with id: {market_order.id}")

        log_trade({**trade_data, "type": "ENTRY"})

    except Exception as e:
        print(f"Trade Failed: {e}")

def close_options_position(ticker, action_type, exit_price=None):
    """Reads memory to find the contract, then sells it via Alpaca."""
    try:
        tracker = load_tracker()
        
        if not tracker or not ticker in tracker:
            print(f"Ignored Exit: No trades for {ticker} or any trades available.")
            return

        target_occ = tracker.get(ticker)['occ_symbol']
        market_order_ids = tracker.get(ticker)['ids']
        
        if not market_order_ids:
            print(f"Ignored Exit: I don't remember opening a trade for {ticker}.")
            return

        # Check if any unfilled orders need to be canceled
        orders_to_filter = GetOrdersRequest(symbols=[target_occ], status=QueryOrderStatus.OPEN)
        target_positions = trading_client.get_orders(orders_to_filter)

        for target_position in target_positions:
            if not target_position.filled_at:
                print(f"Order {target_occ} with id {target_position.id} is not filled yet, so order will be cancelled")
                trading_client.cancel_order_by_id(target_position.id)
                
                # Remove id entry after canceling
                tracker[ticker]['ids'].remove(str(target_position.id)) 
                save_tracker(tracker)

        # Now get active positions to sell
        target_positions = trading_client.get_all_positions()

        if not target_positions:
            print(f"Ignored Exit: {target_occ} is no longer in the Alpaca portfolio.")
            del tracker[ticker]
            save_tracker(tracker)
            return

        for target_position in target_positions:
            total_qty = float(target_position.qty)
            sell_qty = max(1, int(total_qty / 2)) if action_type == "EXIT_PARTIAL" else int(total_qty)
            is_full_exit = action_type in ("EXIT_ALL", "EXIT_STOP_LOSS")
            
            print(f"\n--- Executing Exit ---")
            print(f"Targeting memorized contract: {target_occ}")
            print(f"Action: Selling {sell_qty} contract(s)...")
            
            market_order_data = MarketOrderRequest(
                symbol=target_occ,
                qty=sell_qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
        
            sell_order = trading_client.submit_order(order_data=market_order_data)
            print(f"Sell Order Submitted! ID: {sell_order.id}\n")

            # Poll for the actual fill price (market orders fill within seconds in paper trading).
            # Falls back to the alert price from the Discord message if polling times out.
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

            log_trade({"type": action_type, "ticker": ticker, "occ_symbol": target_occ, "price": actual_exit_price, "quantity": sell_qty})

            if is_full_exit:
                del tracker[ticker]
                save_tracker(tracker)
                print(f"Cleared {ticker} from memory.")
            
    except Exception as e:
        print(f"Error closing position for {ticker}: {e}")

def add_to_position(trade_data):
    """Buys additional contracts for an existing position using the ticker from memory."""
    try:
        tracker = load_tracker()

        ticker = trade_data.get("ticker")
        if not ticker or ticker not in tracker:
            print(f"Ignored ADD: No existing position found in memory for {ticker}.")
            return

        occ_symbol = tracker[ticker]["occ_symbol"]
        alert_price = trade_data.get("price")

        if alert_price:
            add_qty = calculate_buy_position_size(alert_price)
        else:
            print("No price found in ADD alert. Defaulting to 1 contract.")
            add_qty = 1

        print(f"\n--- Adding to Position ---")
        print(f"Ticker: {ticker} | Contract: {occ_symbol} | Adding {add_qty} contract(s) at {alert_price}...")

        order_data = LimitOrderRequest(
            symbol=occ_symbol,
            qty=add_qty,
            side=OrderSide.BUY,
            limit_price=alert_price,
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

        tracker[ticker]["ids"].append(str(order.id))
        save_tracker(tracker)
        print(f"Updated memory for {ticker}: added order id {order.id}")

        log_trade({"type": "ADD", "ticker": ticker, "occ_symbol": occ_symbol, "price": alert_price, "quantity": add_qty})

    except Exception as e:
        print(f"ADD Trade Failed for {trade_data.get('ticker')}: {e}")


def calculate_buy_position_size(entry_price):
    """
    Calculates how many contracts to buy so the total cost 
    is approximately 2% of the total portfolio value.
    """
    try:
        # 1. Get current portfolio value from Alpaca
        account = trading_client.get_account()
        portfolio_value = float(account.portfolio_value)
        
        # 2. Calculate our max spend (2%)
        target_spend = portfolio_value * 0.02
        
        # 3. Calculate the actual cost of 1 contract (Price * 100 shares)
        contract_cost = float(entry_price) * 100
        
        if contract_cost <= 0:
            print("Warning: Contract price is 0. Defaulting to 1 contract.")
            return 1
            
        # 4. Calculate how many whole contracts we can buy
        qty = int(target_spend // contract_cost)
        
        # 5. Safety check: What if 2% isn't enough to buy even 1 contract?
        if qty < 1:
            print(f"Warning: 2% of portfolio (${target_spend:.2f}) cannot afford a $({contract_cost:.2f}) contract.")
            print("Defaulting to 1 contract to stay in the trade.")
            return 1
            
        print(f"Position Sizing: Portfolio=${portfolio_value:.2f} | 2%=${target_spend:.2f} | Buying {qty} contract(s).")
        return qty
        
    except Exception as e:
        print(f"Error calculating position size: {e}. Defaulting to 1 contract.")
        return 1