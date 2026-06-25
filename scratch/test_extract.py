import json
import asyncio
from app.services.infrastructure.platforms.rapidapi_client import RapidAPIClient
from app.services.infrastructure.platforms.dynamic_adapter import extract_json_path

async def test():
    client = RapidAPIClient("instagram-cheapest.p.rapidapi.com")
    res = await client.get("/api/v1/instagram/media_comments", params={"code": "DYdeY9UMwZd"})
    print("Keys in response:", res.keys())
    items = extract_json_path(res, "data.xdt_api__v1__media__media_id__comments__connection.edges")
    print("Extracted type:", type(items))
    if isinstance(items, list):
        print("Count:", len(items))
    else:
        print("Failed to extract:", str(items)[:100])

asyncio.run(test())
