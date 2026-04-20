# parser.py
import json
from datetime import datetime
from google import genai
from google.genai import types
from config import GEMINI_API_KEY

# Initialize the new Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

def generate_occ_symbol(ticker, date_str, option_type, strike):
    """Translates standardized data into standard OCC format."""
    current_year = datetime.now().strftime("%y")
    month, day = date_str.split('/')
    date_formatted = f"{current_year}{month}{day}"
    strike_formatted = f"{int(float(strike) * 1000):08d}"
    return f"{ticker.upper()}{date_formatted}{option_type.upper()}{strike_formatted}"


def _decode_occ(occ: str, ticker: str) -> str:
    """Converts an OCC symbol to a short human-readable label, e.g. 'SPY 03/25 658P'."""
    try:
        strike = str(int(occ[-8:]) // 1000)
        opt_type = occ[-9]
        date_str = occ[-15:-9]  # YYMMDD
        month, day = date_str[2:4], date_str[4:6]
        return f"{ticker} {month}/{day} {strike}{opt_type}"
    except Exception:
        return occ


def _build_positions_context(open_positions):
    """Builds the open positions context string injected into prompts."""
    if open_positions:
        positions_lines = "\n".join(
            f"  - {_decode_occ(occ, ticker)} (OCC: {occ})"
            for occ, ticker in open_positions.items()
        )
        return f"""
Currently open positions:
{positions_lines}

Use these open positions to resolve ambiguous messages. For example:
- If a message says "Trim 658 here" and SPY 658P is open, this is EXIT_PARTIAL for SPY with strike 658.
- If a message says "Closed 656" and SPY 656P is open, this is EXIT_ALL for SPY with strike 656.
- If a message mentions a ticker with no strike and only one position for that ticker is open, that is the target contract.
"""
    return "\nNo positions are currently open.\n"


def _call_gemini(prompt):
    """Sends a prompt to Gemini and returns parsed JSON, or None on failure."""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"LLM Parsing Error: {e}")
        return None


def _process_llm_data(llm_data):
    """Shared post-processing: handles IGNORE, generates OCC symbol for ENTRYs."""
    if llm_data is None:
        return None
    if llm_data.get("type") == "IGNORE":
        return None
    if llm_data.get("type") == "ENTRY":
        if all([llm_data.get('ticker'), llm_data.get('exp_date'), llm_data.get('strike'), llm_data.get('opt_type')]):
            llm_data['occ_symbol'] = generate_occ_symbol(
                llm_data['ticker'],
                llm_data['exp_date'],
                llm_data['opt_type'],
                llm_data['strike']
            )
        else:
            print("Gemini missed a required field for the Entry. Ignoring.")
            return None
    return llm_data


def parse_discord_signal(message_text, open_positions=None, last_ticker=None):
    """Passes the raw Discord text to Gemini to extract trading data.

    open_positions — optional dict {occ_symbol: ticker} of currently open positions.
                     When provided, it is injected into the prompt so the LLM can
                     resolve ambiguous exits/adds (e.g. bare strike numbers).
    """
    text = message_text.strip()
    positions_context = _build_positions_context(open_positions)

    prompt = f"""
    You are an expert financial parsing assistant. Read the following day trading options alert and extract the core trade details.

    The trader uses slang.
    - "SPYYY" or "SPXXX" means the ticker is SPY or SPX.
    - Action words such as "trim", "runners", "majority", "half", "trimming" usually indicate a partial exit ("EXIT_PARTIAL").
    - If there is no action word but there is a price increase with a checkmark (e.g. "SPY 2.20 - 3.30 ✅") or percentages like "✅ 50%" treat it as "EXIT_PARTIAL".
    - "Closed", "Stopped out", or "last cons" indicates a full exit ("EXIT_ALL").
    - "Selling" indicates a full exit ("EXIT_ALL"), unless accompanied by a partial qualifier such as "half", "some", "partial", or a percentage — in that case treat it as "EXIT_PARTIAL".
    - Ignore general market chatter (e.g., "Markets cooked", "VIX back over 20").
    - If a message references only a strike number with no explicit ticker (e.g. "Trim 658 here", "Closed 658", "More 658"), use the open positions context below to identify the ticker and contract.
    {positions_context}
    - If a message says "Stop" but with no explicit ticker (eg. "Stopped out of Longs", "Stopped all cons"), this indicates "EXIT_ALL". In this case, for the ticker, use the open positions context above to identify the ticker and contract.
    - If a message is an ENTRY but has no explicit ticker, use the last used ticker: "{last_ticker or 'unknown'}". Only apply this if a ticker cannot be inferred from the message itself.
    - If a message contains language such as "Added to" a specific order or ticker, classify that as IGNORE
    Respond ONLY with a valid JSON object using this exact structure. If the message is chatter and contains no trade, return {{"type": "IGNORE"}}.

    {{
        "type": "ENTRY" | "EXIT_ALL" | "EXIT_PARTIAL" | "IGNORE",
        "ticker": "String (Standardize to SPY, SPX, HOOD, etc.)",
        "exp_date": "String (MM/DD, only include if ENTRY, otherwise null)",
        "strike": "String (e.g., '682'). Always include for ENTRY. Also include for exits and ADDs when the strike is explicitly mentioned in the message (e.g. 'Closed SPY 658', 'Trim 658 here', 'More 658'). Otherwise null.",
        "opt_type": "String ('C' or 'P', only include if ENTRY, otherwise null)",
        "price": "Number (Extract the execution price, e.g., 2.20. If multiple prices are shown like '2.20 - 2.70', use the current/highest one)"
    }}

    Message to parse:
    "{text}"
    """

    llm_data = _call_gemini(prompt)
    return _process_llm_data(llm_data)


def parse_luigi_signal(message_text, open_positions=None, last_ticker=None):
    """Parses Luigi's structured OPEN / UPDATE / CLOSE format."""
    text = message_text.strip()
    positions_context = _build_positions_context(open_positions)
    last_ticker_rule = (
        f'- If a message is an ENTRY but has no explicit ticker, use the last used ticker: "{last_ticker}". '
        f'Only apply this if a ticker cannot be inferred from the message itself.'
        if last_ticker else ""
    )

    prompt = f"""
    You are an expert financial parsing assistant. Read the following options trade alert
    from a trader named Luigi and extract the core trade details.

    Luigi uses a structured format. Every actionable message starts with one of three
    headers: OPEN, UPDATE, or CLOSE.

    OPEN = ENTRY:
    - The contract is on a line like "$SPY 3/11 $685c" or "$QQQ 3/11 $609p".
      Strip the "$" prefix from both the ticker and the strike.
    - The entry price is always on the "🏁 ENTRY" line (e.g. "🏁 ENTRY = $1.35" or "🏁 ENTRY: $1.35").
    - Ignore the 🛑 SL and 💰 TP lines entirely — do not use those prices.

    CLOSE = EXIT_ALL:
    - Extract the exit price from the message body (e.g. "Closing runners @ $2.00", "Out @ $0.50").
    - If the only prices present are inside a "TRADE RECAP" block (e.g. "$1.15 ➡️ $2.30 (100%)"),
      set price to null — those are recap summaries, not the exit price.
    - "No hold. I am out.", "Stopped out." with no price → EXIT_ALL, price null.

    UPDATE — check the body:
    - Contains "Trimming" or "Trimmed" → EXIT_PARTIAL.
      Extract the trim price: from "Trimmed 1/2 @ 100% $2.30" use 2.30;
      from "$1.65 ➡️ $2.25 ... Trimming" use the right-hand price (2.25).
    - Contains "Stopped out" → EXIT_ALL.
    - Contains "Selling" without a partial qualifier (e.g. "half", "some", "partial", or a percentage) → EXIT_ALL. With a partial qualifier → EXIT_PARTIAL.
    - Contains "Closing this @" or "Closing here @" with a price → EXIT_ALL with that price.
    - All other UPDATE messages (SL adjustments, price targets, commentary) → IGNORE.

    Always IGNORE:
    - Weekly or monthly recap messages (e.g. "WEEK 12 TRADING RECAP", "MARCH RECAP").
    - Messages that are pure commentary, image posts, or social media links.
    - Messages about adding to a position.
    {positions_context}
    {last_ticker_rule}
    Respond ONLY with a valid JSON object. If the message has no trade action, return {{"type": "IGNORE"}}.

    {{
        "type": "ENTRY" | "EXIT_ALL" | "EXIT_PARTIAL" | "IGNORE",
        "ticker": "String (e.g. SPY, QQQ, IWM. Strip any $ prefix and standardize)",
        "exp_date": "String (MM/DD, only if ENTRY, otherwise null)",
        "strike": "String (e.g. '685'. Strip any $ prefix. Always include for ENTRY. Include for exits only if explicitly mentioned)",
        "opt_type": "String ('C' or 'P', only if ENTRY, otherwise null)",
        "price": "Number (execution price. null if not stated)"
    }}

    Message to parse:
    "{text}"
    """

    llm_data = _call_gemini(prompt)
    return _process_llm_data(llm_data)


def parse_signal(message_text, source, open_positions=None, last_ticker=None):
    """Routes to the correct source-specific parser."""
    if source == "luigi":
        return parse_luigi_signal(message_text, open_positions, last_ticker)
    return parse_discord_signal(message_text, open_positions, last_ticker)
