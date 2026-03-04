import requests

# Test data
data = {
    "age": 25,
    "weight": 70,
    "height": 175,
    "goal": "Build muscle",
    "activity_level": "Moderate"
}

# The server should be running locally
BASE_URL = "http://127.0.0.1:8000"

def test_generate():
    try:
        # Note: This will hit the real API and might fail if quota is still out.
        # If it returns 429, we verify our message.
        response = requests.post(f"{BASE_URL}/generate", data=data, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_generate()
