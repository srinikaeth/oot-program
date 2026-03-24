# Discord-to-Alpaca Automated Trading Desk

An end-to-end, zero-latency algorithmic trading pipeline that automatically scrapes options trading alerts from a Discord channel, parses the unstructured text using a Large Language Model (LLM), and executes dynamic position-sized trades via the Alpaca API.

## 🏗️ Architecture Overview

This project consists of two main components working in tandem:
1. **The Client (Browser):** A JavaScript userscript (`discord_forwarder.js`) injected via ScriptCat that continuously monitors a specific Discord channel's DOM. When a new alert is posted, it instantly beams the raw text to the local Python server.
2. **The Server (Python):** A Waitress-backed Flask server (`server.py`) that receives the payload, authenticates it, uses Google's Gemini LLM to extract actionable trade data (Ticker, Action, Price, Exit Strategy), and routes it to the Alpaca execution module.

## 📂 Repository Structure

### Core Application
* `server.py`: The main entry point. Runs the production WSGI server to listen for webhook payloads from the browser.
* `parser.py`: Handles the Gemini API integration. Translates trader slang into structured JSON trade data.
* `trader.py`: The Alpaca API execution engine. Handles live equity checks, 5% dynamic position sizing, and complex scaling logic (partial/full exits).
* `memory.py`: Manages local state. Reads and writes to `active_trades.json` to keep track of open positions and average costs.
* `config.py`: Centralized configuration management for API keys, secure tokens, and environment variables.

### Web Scraping
* `discord_forwarder.js`: The JavaScript code to be pasted into the ScriptCat browser extension. Features custom CSS console logging for high visibility.

### Data & State
* `active_trades.json`: Real-time ledger of currently open options contracts.
* `trades_logged.txt`: Historical append-only log of all executed trades.

### Testing Suite
* `test_parsing.py`: Unit tests for the Gemini LLM prompt logic using sample data from `discord_messages_example.txt`.
* `test_trading.py`: Unit tests for Alpaca order submissions and position sizing math.
* `test_server_local.py` & `test_server_ngrok.py`: Webhook receiver and network tests.
* `test_e2e_integration.py`: Full end-to-end pipeline verification.
* `Alpaca_Trading_Exploration.ipynb`: Jupyter notebook used for initial API discovery and prototyping.

## 🚀 Getting Started

### Prerequisites
* Python 3.9+
* Google Chrome with the ScriptCat extension installed.
* Active API Keys for Alpaca (Paper/Live) and Google AI Studio (Gemini).

### Installation
1. Clone the repository and navigate to the project directory.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt