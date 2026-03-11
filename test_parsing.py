# File to test edge cases in the trading logic

import requests
import time
from datetime import datetime
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOptionContractsRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, LOG_FILE
# from memory import load_tracker, save_tracker
from trader import execute_trade, close_options_position

