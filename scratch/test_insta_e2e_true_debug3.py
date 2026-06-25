import asyncio
import os
import json
import logging
from app.services.infrastructure.platforms.dynamic_adapter import DynamicAdapter
from app.core.config import get_settings
from app.services.infrastructure.llm.service import LLMService

logging.basicConfig(level=logging.ERROR)

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
    
    # fetch raw data
    results = await adapter.client.get(config["search_endpoint"], params={config["search_param_name"]: "DYdeY9UMwZd"})
    items = []
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
    items_subset = items[:5]
    
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
    
    try:
        resp = llm._provider._client.chat.completions.create(
            model=llm._provider._model,
            messages=[{"role": "system", "content": fallback_prompt}, {"role": "user", "content": json.dumps(items_subset)}],
            temperature=0.2,
            response_format={"type": "json_object"},
            max_tokens=4000,
        )
        print("Raw OpenRouter output:", resp.choices[0].message.content)
        
        from app.services.infrastructure.llm._json_helpers import parse_json_payload
        parsed = parse_json_payload(resp.choices[0].message.content)
        print("Parsed JSON:", parsed)
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(test())
