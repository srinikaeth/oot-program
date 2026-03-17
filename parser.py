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

def parse_discord_signal(message_text):
    """Passes the raw Discord text to Gemini to extract trading data."""
    text = message_text.strip()
    
    prompt = f"""
    You are an expert financial parsing assistant. Read the following day trading options alert and extract the core trade details. 
    
    The trader uses slang. 
    - "SPYYY" or "SPXXX" means the ticker is SPY or SPX.
    - "runners", "majority", "half", or percentages like "✅ 50%" usually indicate a partial exit ("EXIT_PARTIAL").
    - "Closed", "Stopped out", or "last cons" indicates a full exit ("EXIT_ALL").
    - "More" or "Added" indicates adding to a position ("ADD").
    - If there is no action word but there is a price increase with a checkmark (e.g. "SPY 2.20 - 3.30 ✅"), treat it as "EXIT_PARTIAL".
    - Ignore general market chatter (e.g., "Markets cooked", "VIX back over 20").

    Respond ONLY with a valid JSON object using this exact structure. If the message is chatter and contains no trade, return {{"type": "IGNORE"}}.
    
    {{
        "type": "ENTRY" | "EXIT_ALL" | "EXIT_PARTIAL" | "ADD" | "IGNORE",
        "ticker": "String (Standardize to SPY, SPX, HOOD, etc.)",
        "exp_date": "String (MM/DD, only include if ENTRY, otherwise null)",
        "strike": "String (e.g., '682', only include if ENTRY, otherwise null)",
        "opt_type": "String ('C' or 'P', only include if ENTRY, otherwise null)",
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
                # llm_data['quantity'] = 4 
            else:
                print("Gemini missed a required field for the Entry. Ignoring.")
                return None
                
        return llm_data
        
    except Exception as e:
        print(f"LLM Parsing Error: {e}")
        return None