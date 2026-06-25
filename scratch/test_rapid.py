import asyncio
from app.services.infrastructure.platforms.rapidapi_client import RapidAPIClient

async def test_insta():
    try:
        # RapidAPIClient signature: def __init__(self, api_host: str, *, timeout: float = 12.0)
        client = RapidAPIClient("instagram-cheapest.p.rapidapi.com")
        res = await client.get("/api/v1/instagram/media_comments", params={"code": "DYdeY9UMwZd"})
        print("Insta response:", str(res)[:500])
    except Exception as e:
        print("Insta error:", e)

asyncio.run(test_insta())
