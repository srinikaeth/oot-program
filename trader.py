# trader.py
import requests

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, NTFY_TOPIC
from memory import load_tracker, save_tracker

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
            
    except Exception as e:
        print(f"Trade Failed: {e}")

def close_options_position(ticker, action_type):
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
            
            print(f"\n--- Executing Exit ---")
            print(f"Targeting memorized contract: {target_occ}")
            print(f"Action: Selling {sell_qty} contract(s)...")
            
            market_order_data = MarketOrderRequest(
                symbol=target_occ,
                qty=sell_qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
        
            trading_client.submit_order(order_data=market_order_data)
            print(f"Sell Order Submitted!\n")
            send_push_notification(
            title="Position Closed!", 
            message=f"SOLD {sell_qty} contract(s) of {ticker}.",
            trade_type="EXIT"
            )
        
            if action_type == "EXIT_ALL":
                del tracker[ticker]
                save_tracker(tracker)
                print(f"Cleared {ticker} from memory.")
            
    except Exception as e:
        print(f"Error closing position for {ticker}: {e}")