import requests

test_url = 'https://monte-ulcerous-uneventfully.ngrok-free.dev/discord-webhook'

test_notification = {
    "title": "Ngrok Test Server",
    "text": "Hello from the internet!"
}

print("Sending test notif through internet....")

try:
    response = requests.post(url=test_url, json=test_notification)

    print(f"Success! Server responded with status code: {response.status_code}")
    print(f"Server response: {response.json()}")

except:
    print(f"Error with exception: {requests.exceptions}")
