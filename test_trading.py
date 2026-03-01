# test_simulation.py
import requests
import time

# The local address of your Flask server
URL = 'http://127.0.0.1:5001/discord-webhook'

# A chronological sequence of real messages from your example data
simulation_sequence = [
    {
        "title": "Waxui Alerts",
        "text": "OnlyOptionsTrades #🍭│waxui: Waxui Alerts 🍭: ⁨@Premium⁩  *Riskier*\nHOOD here\n02/27 78C\nAvg, 1.50"
    },
    {
        "title": "Waxui Alerts",
        "text": "OnlyOptionsTrades #🍭│waxui: Waxui Alerts 🍭: ⁨@Premium⁩  *Lotto*\nSPY here\n02/27 682P\nAvg.\n2.00"
    },
    {
        "title": "Waxui Alerts",
        "text": "OnlyOptionsTrades #🍭│waxui: Waxui Alerts 🍭: ⁨@Premium⁩  Closed HOOD here"
    },
    {
        "title": "Waxui Alerts",
        "text": "OnlyOptionsTrades #🍭│waxui: Waxui Alerts 🍭: ⁨@Premium⁩  Trim SPY here\n2.00 - 2.45 ✅ 23%\nHolding most."
    }
]

print("🚀 Starting Trading Simulation...\n")

for i, payload in enumerate(simulation_sequence, 1):
    print(f"--- Sending Message {i} of {len(simulation_sequence)} ---")
    print(f"Preview: {payload['text'].splitlines()[1] if len(payload['text'].splitlines()) > 1 else payload['text']}")
    
    try:
        # We send this as standard JSON because we built the Flask server 
        # to accept both JSON (for testing) and Form Data (for MacroDroid)
        response = requests.post(URL, json=payload)
        
        if response.status_code == 200:
            print("Delivery: SUCCESS")
        else:
            print(f"Delivery: FAILED ({response.status_code})")
            
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect. Is server.py running?")
        break
        
    print("-" * 40)
    
    # Wait 5 seconds before sending the next signal to allow Alpaca to process
    if i < len(simulation_sequence):
        print("Waiting 5 seconds...\n")
        time.sleep(5)

print("\n🏁 Simulation Complete!")