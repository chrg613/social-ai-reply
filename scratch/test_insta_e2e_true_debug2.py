import asyncio
import os
import json
from app.services.infrastructure.platforms.dynamic_adapter import DynamicAdapter
from app.core.config import get_settings
from app.services.infrastructure.llm.service import LLMService

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
    print("Testing Insta search_posts fallback manually...")
    
    # fetch raw data
    results = await adapter.client.get(config["search_endpoint"], params={config["search_param_name"]: "DYdeY9UMwZd"})
    items = []
    # parse path
    def _extract_from_path(data, path_parts):
        current = data
        for part in path_parts:
            if isinstance(current, dict):
                current = current.get(part, {})
            elif isinstance(current, list):
                if not current: return []
                current = current[0].get(part, {}) if isinstance(current[0], dict) else []
            else:
                return []
        return current
        
    items = _extract_from_path(results, config["items_json_path"].split("."))
    items_subset = items[:10]
    
    llm = LLMService()
    fallback_prompt = (
        "You are an API parsing assistant. You will be provided with a raw JSON array of items "
        "extracted from a social media scraper.\n\n"
        "Extract the relevant data and return a JSON object with a single key 'posts', which is an "
        "array of objects matching this schema:\n"
        "- external_id: string (unique ID)\n"
        "- author_username: string\n"
        "- author_id: string\n"
        "- title: string\n"
        "- body: string\n"
        "- profile_url: string\n"
        "- hashtags: array of strings\n"
        "- upvotes: integer\n"
        "- comments_count: integer\n\n"
        "Return only the raw JSON."
    )
    payload = llm.call_json(fallback_prompt, json.dumps(items_subset), temperature=0.2)
    print("PAYLOAD RETURNED:", payload)

asyncio.run(test())
