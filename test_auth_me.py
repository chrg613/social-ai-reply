import os
import requests
from dotenv import load_dotenv
load_dotenv()
from app.services.product.supabase_auth import sign_up
email = "sam+test2@gmail.com"
password = "password123!"
print("Signing up...")
try:
    res = sign_up(email, password, "Sam Test")
    print("Signup success")
except Exception as e:
    print("Signup failed:", e)

# Use HTTP requests to call the auth/register API
print("Calling /v1/auth/register API directly to provision workspace...")
try:
    resp = requests.post("http://localhost:8000/v1/auth/register", json={
        "email": "sam+test3@gmail.com",
        "password": password,
        "full_name": "Sam Test",
        "workspace_name": "Sam Workspace"
    })
    print("Register API response:", resp.status_code)
    print(resp.json())
    token = resp.json().get("access_token")
    if token:
        print("Calling /v1/auth/me...")
        me_resp = requests.get("http://localhost:8000/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        print("Me API response:", me_resp.status_code)
        print(me_resp.json())
except Exception as e:
    print("API failed:", e)
