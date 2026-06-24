from app.services.product.supabase_auth import sign_up
import os
from dotenv import load_dotenv

load_dotenv()

try:
    res = sign_up("test123456@example.com", "password123", "Test User")
    print("SUCCESS", res.keys())
except Exception as e:
    import traceback
    traceback.print_exc()
