# Flask server setup for receiving notifs from Android

from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/discord-webhook', methods=['POST'])
def handle_webhook():
    # Ensure the incoming request is JSON
    if request.is_json:
        data = request.get_json()
        
        # Extract the notification title (usually sender/server name)
        title = data.get('title', 'No Title')
        
        # Extract the notification text (the actual message)
        message = data.get('text', 'No Message')
        
        print("\n--- New Discord Notification ---")
        print(f"From: {title}")
        print(f"Message: {message}")
        print("--------------------------------\n")
        
        # You can add your custom processing logic here!
        
        return jsonify({"status": "success"}), 200
    else:
        return jsonify({"status": "error", "message": "Payload must be JSON"}), 400

if __name__ == '__main__':
    # Run the server on port 5001
    app.run(host='0.0.0.0', port=5001)