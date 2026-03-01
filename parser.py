# parser.py
import re
from datetime import datetime

def generate_occ_symbol(ticker, date_str, option_type, strike):
    """Translates Discord text into standard OCC format."""
    current_year = datetime.now().strftime("%y")
    month, day = date_str.split('/')
    date_formatted = f"{current_year}{month}{day}"
    strike_formatted = f"{int(float(strike) * 1000):08d}"
    return f"{ticker.upper()}{date_formatted}{option_type.upper()}{strike_formatted}"

def parse_discord_signal(message_text):
    """Uses Regex to extract trade details from the alert text."""
    text = message_text.strip()
    
    # 1. HUNT FOR ENTRY SIGNALS
    entry_pattern = r"([A-Z]+)\s+here.*?(\d{2}/\d{2})\s+(\d+\.?\d*)([CP]).*?Avg[.,]?\s*(\d+\.?\d*)"
    entry_match = re.search(entry_pattern, text, re.DOTALL | re.IGNORECASE)
    
    if entry_match:
        ticker = entry_match.group(1).upper()
        exp_date = entry_match.group(2)
        strike = entry_match.group(3)
        opt_type = entry_match.group(4).upper()
        price = float(entry_match.group(5))
        
        return {
            "type": "ENTRY",
            "ticker": ticker,
            "occ_symbol": generate_occ_symbol(ticker, exp_date, opt_type, strike),
            "price": price,
            "quantity": 4 # Defaulting to 4 contracts for buy
        }
        
    # 2. HUNT FOR EXIT / TRIM SIGNALS
    exit_pattern = r"(Closed|Stopped out of|Trim|More|Added to)\s+([A-Z]+)"
    exit_match = re.search(exit_pattern, text, re.IGNORECASE)
    
    if exit_match:
        action_word = exit_match.group(1).lower()
        ticker = exit_match.group(2).upper()
        
        if "closed" in action_word or "stopped" in action_word:
            action_type = "EXIT_ALL"
        elif "trim" in action_word:
            action_type = "EXIT_PARTIAL"
        else:
            action_type = "ADD"
            
        return {
            "type": action_type,
            "ticker": ticker,
        }
        
    return None