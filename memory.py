# memory.py
import json
import os
from config import TRACKER_FILE

def load_tracker():
    """Reads the active trades memory file."""
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {} # Return empty dict if file is corrupted/empty
    return {}

def save_tracker(data):
    """Saves the active trades to memory."""
    with open(TRACKER_FILE, "w") as f:
        json.dump(data, f, indent=4)