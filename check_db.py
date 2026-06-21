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

r = httpx.get(f"{url}/rest/v1/projects?id=eq.115", headers=headers)
print("Projects 115:", r.json())

r = httpx.get(f"{url}/rest/v1/monitored_subreddits?project_id=eq.115", headers=headers)
print("Subreddits:", len(r.json()), r.json())
