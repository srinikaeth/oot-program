# trader.py
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY
from memory import load_tracker, save_tracker

# Initialize Trading Client
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

def execute_trade(trade_data):
    """Executes buy orders and saves the OCC symbol to memory."""
    try:
        market_order_data = MarketOrderRequest(
            symbol=trade_data['occ_symbol'],
            qty=trade_data['quantity'],
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )

        market_order = trading_client.submit_order(order_data=market_order_data)
        print(f"Trade Executed! ID: {market_order.id}")
        
        # Save to memory immediately after buying
        tracker = load_tracker()
        tracker[trade_data['ticker']] = trade_data['occ_symbol']
        save_tracker(tracker)
        print(f"Memorized {trade_data['ticker']} active contract: {trade_data['occ_symbol']}")
            
    except Exception as e:
        print(f"Trade Failed: {e}")

def close_options_position(ticker, action_type):
    """Reads memory to find the contract, then sells it via Alpaca."""
    try:
        tracker = load_tracker()
        target_occ = tracker.get(ticker)
        
        if not target_occ:
            print(f"Ignored Exit: I don't remember opening a trade for {ticker}.")
            return

        open_positions = trading_client.get_all_positions()
        target_position = None
        
        for position in open_positions:
            if position.symbol == target_occ:
                target_position = position
                break
                
        if not target_position:
            print(f"Ignored Exit: {target_occ} is no longer in the Alpaca portfolio.")
            del tracker[ticker]
            save_tracker(tracker)
            return
            
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
        
        if action_type == "EXIT_ALL":
            del tracker[ticker]
            save_tracker(tracker)
            print(f"Cleared {ticker} from memory.")
            
    except Exception as e:
        print(f"Error closing position for {ticker}: {e}")