import requests
import time
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus, OrderSide, OrderStatus
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY

# The local address of your Flask server
URL = 'http://127.0.0.1:5001/discord-webhook'

# Initialize the Alpaca client specifically for verifying the test results
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

# 1. Define the simulation sequence using exact examples with emojis and slang
simulation_sequence = [
    {
        "title": "Waxui Alerts",
        "text": "@Premium  LOTTO\nSPY here\n03/12 672C\nAvg, 2.20 \nStops under lows." 
    },
    {
        "title": "Waxui Alerts",
        "text": "@Premium  SPY\n2.20 - 4.45 ✅ 102%\nHolding last cons." 
    }
]

def check_order(ticker, expected_side):
    """
    Helper function to ask Alpaca if an order exists for a specific ticker and side (BUY/SELL).
    We check ALL orders (filled, open, canceled, etc.) from the recent history.
    """
    # Fetch the 10 most recent orders of any status
    req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=10)
    recent_orders = trading_client.get_orders(req)
    
    for order in recent_orders:
        # Check if the OCC symbol starts with the ticker (e.g., SPY) and the side matches
        if order.symbol.startswith(ticker) and order.status == expected_side:
            return order
            
    return None

print("🚀 Starting End-to-End Trade Verification...\n")

# --- STEP 1: TEST THE ENTRY ---
print("--- Sending ENTRY Signal ---")
requests.post(URL, json=simulation_sequence[0])

print("Waiting 6 seconds for LLM parsing and Alpaca execution...")
time.sleep(6)

# Verify the ENTRY order was submitted
spy_buy_order = check_order("SPY", OrderStatus.ACCEPTED)
if spy_buy_order:
    print(f"✅ ENTRY VERIFIED: Found BUY order for {spy_buy_order.qty} contract(s) of {spy_buy_order.symbol}.")
    print(f"   Order Status: {spy_buy_order.status}")
else:
    print("❌ ENTRY FAILED: No SPY BUY order found in Alpaca.")


# --- STEP 2: TEST THE EXIT ---
print("\n--- Sending EXIT Signal (with checkmark and sell price) ---")
requests.post(URL, json=simulation_sequence[1])

print("Waiting 6 seconds for LLM parsing and Alpaca execution...")
time.sleep(6)

# Verify the EXIT order was submitted
spy_sell_order = check_order("SPY", OrderStatus.CANCELED)
if spy_sell_order:
    print(f"✅ EXIT VERIFIED: Found SELL order for {spy_sell_order.qty} contract(s) of {spy_sell_order.symbol}.")
    print(f"   Order Status: {spy_sell_order.status}")
else:
    print("❌ EXIT FAILED: No SPY SELL order found in Alpaca.")
    
print("\n🏁 End-to-End Test Complete!")

# TODO: Add test to include partial sells and multiple buy sell messages