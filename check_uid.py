import os
import httpx
from dotenv import load_dotenv

load_dotenv()
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SECRET_KEY"]

headers = {
    "apikey": key,
    "Authorization": f"Bearer {key}"
}

tables = ["account_users", "memberships", "workspaces", "projects"]
for t in tables:
    r = httpx.get(f"{url}/rest/v1/{t}?limit=1", headers=headers)
    if r.status_code == 200 and r.json():
        print(t, r.json()[0].keys())
