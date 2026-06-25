import requests
import json

url = "http://localhost:8000/v1/scrapers/chat"
headers = {"Content-Type": "application/json"}
data = {
    "message": "test",
    "history": []
}

try:
    response = requests.post(url, headers=headers, json=data)
    print("Status:", response.status_code)
    print("Body:", response.text)
except Exception as e:
    print("Error:", e)
