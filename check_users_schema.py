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

r = httpx.get(f"{url}/rest/v1/account_users?limit=1", headers=headers)
if r.status_code == 200 and r.json():
    print(r.json()[0].keys())
else:
    print(r.status_code, r.text)
