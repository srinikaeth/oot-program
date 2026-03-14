# Tests for trading logic and edge cases

import requests
import time
from datetime import datetime
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOptionContractsRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, LOG_FILE
# from memory import load_tracker, save_tracker
from trader import execute_trade, close_options_position

# Initialize Trading Client
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

# def test_simple_trade_execution():

# Simplified testing after trade data parsing 
simulation_sequence = [
  {'type': 'ENTRY', 'ticker': 'SPY', 'occ_symbol': 'SPY260318C00668000', 'price': 20.0, 'quantity': 4},
  # {'type': 'ENTRY', 'ticker': 'HOOD', 'occ_symbol': 'HOOD260320C00078000', 'price': 2.0, 'quantity': 4},
  {'type': 'EXIT_ALL', 'ticker': 'SPY', 'occ_symbol': 'SPY260318C00668000', 'price': 2.0, 'quantity': 4},
  # {'type': 'EXIT_PARTIAL', 'ticker': 'SPY', 'occ_symbol': 'SPY260312P00661000', 'price': 2.0, 'quantity': 4},
]

print("🚀 Starting Trading Simulation...\n")

for i, trade_data in enumerate(simulation_sequence, 1):
    print(f"--- Sending Message {i} of {len(simulation_sequence)} ---")
    print(f"Preview: {trade_data}")
    
    try:
      # 2. Execute trading logic if a valid signal was found
      if trade_data:
          if trade_data["type"] == "ENTRY":
              execute_trade(trade_data)
          elif trade_data["type"] in ["EXIT_ALL", "EXIT_PARTIAL"]:
              close_options_position(trade_data["ticker"], trade_data["type"])
      else:
          print("No actionable trade data found in message.")
          
      # 3. Log the raw message to your text file
      timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
      log_entry = f"[{timestamp}] Testing: {trade_data}\n"
      with open(LOG_FILE, "a", encoding="utf-8") as file:
        file.write(log_entry)

        print("-" * 40)
    
      # Wait 5 seconds before sending the next signal to allow Alpaca to process
      if i < len(simulation_sequence):
          print("Waiting 5 seconds...\n")
          time.sleep(5)

      print("\n🏁 Simulation Complete!")

    except:
        print("Error: Could not execute trades. Check Alpaca connection")
        break


# def test_multiple_orders_same_ticker():
#   # Test for several orders linked to the same ticker

#   simulation_sequence = [
#     {'type': 'ENTRY', 'ticker': 'SPY', 'occ_symbol': 'SPY260310P00661000', 'price': 2.0, 'quantity': 4},
#     {'type': 'ENTRY', 'ticker': 'SPY', 'occ_symbol': 'SPY260310P00661000', 'price': 3.0, 'quantity': 2},
#     {'type': 'EXIT_ALL', 'ticker': 'SPY', 'occ_symbol': 'SPY260310P00661000', 'price': 4.0, 'quantity': 6},
#   ]

#   print("🚀 Starting Trading Simulation...\n")

#   for i, trade_data in enumerate(simulation_sequence, 1):
#       print(f"--- Sending Message {i} of {len(simulation_sequence)} ---")
#       print(f"Preview: {trade_data}")
      
#       try:
#         # 2. Execute trading logic if a valid signal was found
#         if trade_data:
#             if trade_data["type"] == "ENTRY":
#                 execute_trade(trade_data)
#             elif trade_data["type"] in ["EXIT_ALL", "EXIT_PARTIAL"]:
#                 close_options_position(trade_data["ticker"], trade_data["type"])
#         else:
#             print("No actionable trade data found in message.")
            
#         # 3. Log the raw message to your text file
#         timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         log_entry = f"[{timestamp}] Testing: {trade_data}\n"
#         with open(LOG_FILE, "a", encoding="utf-8") as file:
#           file.write(log_entry)

#           print("-" * 40)
      
#         # Wait 5 seconds before sending the next signal to allow Alpaca to process
#         if i < len(simulation_sequence):
#             print("Waiting 5 seconds...\n")
#             time.sleep(5)

#         print("\n🏁 Simulation Complete!")

#       except:
#           print("Error: Could not execute trades. Check Alpaca connection")
#           break