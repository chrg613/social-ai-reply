import asyncio
from app.services.infrastructure.platforms.dynamic_adapter import DynamicAdapter

async def test():
    config = {
        "platform": "instagram",
        "api_host": "instagram-cheapest.p.rapidapi.com",
        "search_endpoint": "/api/v1/instagram/media_comments",
        "search_param_name": "code",
        "items_json_path": "data.xdt_api__v1__media__media_id__comments__connection.edges",
        # The API key comes from .env RAPIDAPI_KEY if not specified
    }
    adapter = DynamicAdapter(config)
    print("Testing Insta search_posts with keyword 'DYdeY9UMwZd'...")
    posts = await adapter.search_posts(["DYdeY9UMwZd"])
    print("Posts found:", len(posts))
    if posts:
        print("First post:", posts[0].dict())

asyncio.run(test())
