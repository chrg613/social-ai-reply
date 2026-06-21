from app.db.supabase_client import get_supabase

db = next(get_supabase())
res = db.table("monitored_subreddits").select("*").eq("project_id", 115).execute()
print(res.data)
