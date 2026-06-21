from app.core.config import get_settings
s = get_settings()
print(repr(s.apify_api_token))
