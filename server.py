from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

@app.route('/discord-webhook', methods=['POST'])
def handle_webhook():
    # 1. Catch Form Data (from MacroDroid)
    if request.form:
        title = request.form.get('title', 'No Title')
        message = request.form.get('text', 'No Message')
        
    # 2. Catch JSON Data (from your test.py script)
    elif request.is_json:
        data = request.get_json()
        title = data.get('title', 'No Title')
        message = data.get('text', 'No Message')
        
    else:
        return jsonify({"status": "error", "message": "Unsupported payload type"}), 400

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {title}: {message}\n"
    
    print(f"Saved to file: {log_entry.strip()}")
    
    with open("discord_messages.txt", "a", encoding="utf-8") as file:
        file.write(log_entry)
    
    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)