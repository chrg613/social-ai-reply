import os
from dotenv import load_dotenv
load_dotenv()

from app.db.supabase_client import get_supabase_client
supabase = get_supabase_client()
try:
    res = supabase.table("projects").select("*").limit(1).execute()
    print("Columns in projects:", list(res.data[0].keys()) if res.data else "No rows")
except Exception as e:
    print("Error querying projects:", e)
