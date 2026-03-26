# Discord-to-Alpaca Automated Trading Desk

An end-to-end algorithmic trading pipeline that automatically captures options trading alerts from a Discord channel, parses the unstructured text using a Large Language Model (LLM), and executes dynamic position-sized trades via the Alpaca API. All trades are logged to Supabase with full P&L tracking and a live Streamlit dashboard.

## 🏗️ Architecture Overview

```
Discord Channel
      │
      ▼
discord_forwarder.js   ← ScriptCat userscript monitors DOM, POSTs new messages
      │
      ▼
server.py (Flask/Waitress on :5001)
      │
      ├── parser.py          ← Gemini LLM extracts structured trade data
      │        └── open positions context injected into every prompt
      │
      ├── trader.py          ← Alpaca order execution (limit buys, market sells)
      │        └── 2% dynamic position sizing per trade
      │
      ├── trade_logger.py    ← Supabase: single source of truth for positions & P&L
      │
      ├── eval_logger.py     ← Supabase: logs every parse for accuracy tracking
      │
      └── stop_loss.py       ← Background thread: auto-closes positions at -50%
```

## 📂 File Reference

### Core Application
| File | Purpose |
|------|---------|
| `server.py` | Flask webhook server. Receives Discord messages, coordinates parsing → execution → logging. |
| `parser.py` | Gemini 2.5 Flash integration. Translates trader slang into structured JSON. Receives currently open positions as context on every call to improve accuracy on ambiguous messages (bare strikes, ticker-less exits). |
| `trader.py` | Alpaca execution engine. Places limit buy orders and market sell orders. Handles ENTRY, ADD, EXIT_PARTIAL, EXIT_ALL, and EXIT_STOP_LOSS flows. |
| `trade_logger.py` | Supabase client. Single source of truth for active position tracking (`is_open` flag) and trade history. Calculates weighted-average cost basis and realized P&L on every exit. |
| `stop_loss.py` | Background daemon thread. Polls all open positions every 30 seconds and closes any contract down 50% or more. Correctly handles multiple simultaneous positions on the same ticker. |
| `eval_logger.py` | Logs every incoming message and its parsed output to the `parser_evals` Supabase table for accuracy tracking. |
| `dashboard.py` | Streamlit dashboard with two tabs: **Trading** (equity curve, trade history, open P&L) and **Parser Accuracy** (metrics, per-field accuracy, human labeling UI). |
| `config.py` | Centralized configuration for API keys, stop loss settings, and file paths. |
| `discord_forwarder.js` | ScriptCat userscript injected into the browser. Monitors the Discord DOM and POSTs new messages to the local server. |

### Testing Suite
| File | Purpose |
|------|---------|
| `test_parsing.py` | Unit tests for the Gemini parser prompt. Mocks the LLM and verifies correct JSON extraction for 15+ real Discord message patterns (ENTRY, EXIT, ADD, slang, chatter). |
| `test_e2e_integration.py` | End-to-end integration tests. Requires the Flask server and Alpaca paper trading to be running. Verifies the full pipeline from signal → order. |
| `test_trading.py` | Unit tests for Alpaca order submission and position sizing math. |
| `test_server_local.py` | Webhook connectivity tests against the local server. |

### Data & Supabase Schema
Two tables are required in Supabase:

**`trades`** — trade log and active position tracker
```sql
CREATE TABLE trades (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ DEFAULT NOW(),
    ticker      TEXT NOT NULL,
    occ_symbol  TEXT,
    type        TEXT NOT NULL,   -- ENTRY | ADD | EXIT_PARTIAL | EXIT_ALL | EXIT_STOP_LOSS
    price       NUMERIC,
    quantity    INT,
    total_value NUMERIC,         -- price * qty * 100 (cost / proceeds in dollars)
    pnl         NUMERIC,         -- realized P&L in dollars, populated on exits
    order_id    TEXT,            -- Alpaca order ID
    is_open     BOOLEAN DEFAULT FALSE
);
```

**`parser_evals`** — parser accuracy log
```sql
CREATE TABLE parser_evals (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ DEFAULT NOW(),
    source          TEXT,
    raw_message     TEXT NOT NULL,
    parsed_type     TEXT,
    parsed_ticker   TEXT,
    parsed_exp_date TEXT,
    parsed_strike   TEXT,
    parsed_opt_type TEXT,
    parsed_price    NUMERIC,
    human_type      TEXT,
    human_ticker    TEXT,
    human_exp_date  TEXT,
    human_strike    TEXT,
    human_opt_type  TEXT,
    human_price     NUMERIC,
    is_correct      BOOLEAN,
    notes           TEXT
);
```

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- Google Chrome with the ScriptCat extension installed
- API keys for: Alpaca (paper or live), Google AI Studio (Gemini), Supabase

### Installation
1. Clone the repository and navigate to the project directory.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Populate `config.py` with your API keys and credentials.
4. Run the two SQL migrations above in the Supabase SQL editor.

### Running the Server
```bash
python server.py
```
The server starts on port 5001 and also launches the stop loss monitor as a background thread.

### Running the Dashboard
```bash
streamlit run dashboard.py
```

### Running Tests
```bash
# Unit tests (no server needed)
python -m pytest test_parsing.py -v

# End-to-end tests (requires server running)
python server.py &
python -m pytest test_e2e_integration.py -v -s
```

## ⚙️ Key Behaviours

### Dynamic Position Sizing
Every buy order targets **2% of current portfolio value**. The number of contracts is calculated as:
```
qty = floor((portfolio_value * 0.02) / (price * 100))
```
Minimum of 1 contract.

### Multi-Position Same-Ticker Support
Two simultaneous positions on the same ticker (e.g. SPY 656P and SPY 658P) are tracked and closed independently. Exit messages that mention a specific strike (e.g. "Closed 658") will target only that contract. The parser receives the full list of open positions as context on every call, enabling correct resolution of bare-strike and ticker-less messages.

### Automatic Stop Loss
The stop loss monitor runs every 30 seconds. Any position with unrealized P&L at or below **-50%** is closed automatically via a market sell order. The threshold is configurable via `STOP_LOSS_PCT` in `config.py`.

### Parser Accuracy Tracking
Every incoming Discord message and its parsed output are logged to `parser_evals`. The dashboard's **Parser Accuracy** tab shows overall accuracy, per-type and per-field breakdowns, and a labeling UI to add human ground-truth labels to unlabeled messages.

### OCC Symbol Format
Option contracts are identified using the OCC format:
```
{TICKER}{YYMMDD}{C|P}{8-digit-strike}
e.g. SPY260328P00658000  →  SPY, exp 03/28/26, Put, strike $658
```
Strike encoding: `int(strike * 1000)` zero-padded to 8 digits.
