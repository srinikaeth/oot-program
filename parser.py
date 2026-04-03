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


def parse_discord_signal(message_text, open_positions=None, last_ticker=None):
    """Passes the raw Discord text to Gemini to extract trading data.

    open_positions — optional dict {occ_symbol: ticker} of currently open positions.
                     When provided, it is injected into the prompt so the LLM can
                     resolve ambiguous exits/adds (e.g. bare strike numbers).
    """
    text = message_text.strip()

    if open_positions:
        positions_lines = "\n".join(
            f"  - {_decode_occ(occ, ticker)} (OCC: {occ})"
            for occ, ticker in open_positions.items()
        )
        positions_context = f"""
Currently open positions:
{positions_lines}

Use these open positions to resolve ambiguous messages. For example:
- If a message says "Trim 658 here" and SPY 658P is open, this is EXIT_PARTIAL for SPY with strike 658.
- If a message says "Closed 656" and SPY 656P is open, this is EXIT_ALL for SPY with strike 656.
- If a message mentions a ticker with no strike and only one position for that ticker is open, that is the target contract.
"""
    else:
        positions_context = "\nNo positions are currently open.\n"

    prompt = f"""
    You are an expert financial parsing assistant. Read the following day trading options alert and extract the core trade details.

    The trader uses slang.
    - "SPYYY" or "SPXXX" means the ticker is SPY or SPX.
    - Action words such as "trim", "runners", "majority", "half", "trimming" usually indicate a partial exit ("EXIT_PARTIAL").
    - If there is no action word but there is a price increase with a checkmark (e.g. "SPY 2.20 - 3.30 ✅") or percentages like "✅ 50%" treat it as "EXIT_PARTIAL".
    - "Closed", "Stopped out", or "last cons" indicates a full exit ("EXIT_ALL").
    - Ignore general market chatter (e.g., "Markets cooked", "VIX back over 20").
    - If a message references only a strike number with no explicit ticker (e.g. "Trim 658 here", "Closed 658", "More 658"), use the open positions context below to identify the ticker and contract.
    {positions_context}
    - If a message says "Stop" but with no explicit ticker (eg. "Stopped out of Longs", "Stopped all cons"), this indicates "EXIT_ALL". In this case, for the ticker, use the open positions context below to identify the ticker and contract.
    {positions_context}
    - If a message is an ENTRY but has no explicit ticker, use the last used ticker: "{last_ticker or 'unknown'}". Only apply this if a ticker cannot be inferred from the message itself.
    - If a message contains language such as "Added to" a specific order or ticker, classify that as IGNORE
    Respond ONLY with a valid JSON object using this exact structure. If the message is chatter and contains no trade, return {{"type": "IGNORE"}}.

    {{
        "type": "ENTRY" | "EXIT_ALL" | "EXIT_PARTIAL" | "IGNORE",
        "ticker": "String (Standardize to SPY, SPX, HOOD, etc.)",
        "exp_date": "String (MM/DD, only include if ENTRY, otherwise null)",
        "strike": "String (e.g., '682'). Always include for ENTRY. Also include for exits and ADDs when the strike is explicitly mentioned in the message (e.g. 'Closed SPY 658', 'Trim 658 here', 'More 658'). Otherwise null.",
        "opt_type": "String ('C' or 'P', only include if ExxNTRY, otherwise null)",
        "price": "Number (Extract the execution price, e.g., 2.20. If multiple prices are shown like '2.20 - 2.70', use the current/highest one)"
    }}

    Message to parse:
    "{text}"
    """

    try:
        # Call the Gemini API using the new google.genai syntax
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0, # Forces deterministic, highly structured outputs
            )
        )

        # Parse the JSON response back into a Python dictionary
        llm_data = json.loads(response.text)

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

    except Exception as e:
        print(f"LLM Parsing Error: {e}")
        return None
