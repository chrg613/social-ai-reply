import asyncio
import os
import json
from app.services.infrastructure.platforms.dynamic_adapter import DynamicAdapter
from app.core.config import get_settings

async def test():
    os.environ["LLM_PROVIDER"] = "openai"
    settings = get_settings()
    settings.llm_provider = "openai"
    config = {
        "platform": "instagram",
        "api_host": "instagram-cheapest.p.rapidapi.com",
        "search_endpoint": "/api/v1/instagram/media_comments",
        "search_param_name": "code",
        "items_json_path": "data.xdt_api__v1__media__media_id__comments__connection.edges",
    }
    adapter = DynamicAdapter(config)
    print("Testing Insta search_posts...")
    
    # We will override the LLM call inside adapter to print the exact exception
    import logging
    logging.basicConfig(level=logging.ERROR)
    
    posts = await adapter.search_posts(["DYdeY9UMwZd"])
    print("Posts found:", len(posts))

asyncio.run(test())
