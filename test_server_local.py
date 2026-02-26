import requests

test_url = 'http://127.0.0.1:5001/discord-webhook'

test_notification = {
    "title": "My Private Server",
    "text": "This is a test message"
}

print("Sending test notif to server....")

try:
    response = requests.post(url=test_url, json=test_notification)

    print(f"Success! Server responded with status code: {response.status_code}")
    print(f"Server response: {response.json()}")

except:
    print(f"Error with exception: {requests.exceptions}")
