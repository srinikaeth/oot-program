# server.py
from flask import Flask, request, jsonify, abort
from waitress import serve
from datetime import datetime
from config import LOG_FILE, API_SECRET_KEY
from parser import parse_discord_signal
from trader import execute_trade, close_options_position, add_to_position
from stop_loss import start_stop_loss_monitor
from eval_logger import log_parse_eval
from trade_logger import get_all_open_positions

app = Flask(__name__)

@app.route('/discord-webhook', methods=['POST'])
def handle_webhook():
    message = "No Message"
    title = "No Title"

    provided_key = request.headers.get('X-Bot-Key')
    
    if provided_key != API_SECRET_KEY:
        print("🚨 SECURITY ALERT: Blocked unauthorized request!")
        abort(401)  # Instantly reject the request

    # Catch both Form Data (MacroDroid) and JSON (Local Testing)
    if request.form:
        title = request.form.get('title', 'No Title')
        message = request.form.get('text', 'No Message')
        print(f'Message received is {message}')
    elif request.is_json:
        data = request.get_json()
        title = data.get('title', 'No Title')
        message = data.get('text', 'No Message')
        print(f'Message received is: \n {message}')
    else:
        return jsonify({"status": "error", "message": "Unsupported payload type"}), 400
        
    print(f"\n--- Signal Received from {title} ---")
    
    # 1. Parse the text, providing open positions as context for the LLM
    open_positions = get_all_open_positions()
    trade_data = parse_discord_signal(message, open_positions=open_positions)
    print(f"Trade data: {trade_data}")
    log_parse_eval(message, title, trade_data)

    # 2. Execute trading logic if a valid signal was found
    if trade_data:
        if trade_data["type"] == "ENTRY":
            execute_trade(trade_data)
        elif trade_data["type"] == "ADD":
            add_to_position(trade_data)
        elif trade_data["type"] in ["EXIT_ALL", "EXIT_PARTIAL"]:
            close_options_position(trade_data["ticker"], trade_data["type"], trade_data.get("price"), trade_data.get("strike"))
    else:
        print("No actionable trade data found in message.")
        
    # 3. Log the raw message to your text file
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {title}: {message}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as file:
        file.write(log_entry)
    
    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    start_stop_loss_monitor()
    print("🚀 Trading Server on port 5001 started and listening for messages...")
    serve(app, host='0.0.0.0', port=5001)