import asyncio
import os
import json
from app.services.infrastructure.llm.service import LLMService
from app.core.config import get_settings
from app.services.infrastructure.platforms.dynamic_adapter import DynamicAdapter

async def test():
    os.environ["LLM_PROVIDER"] = "openai"
    settings = get_settings()
    settings.llm_provider = "openai"
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
    # create dummy items since fetching takes a while
    items = [{"node": {"pk": "123", "text": "hello insta", "user": {"username": "bob"}}}]
    
    print("Testing call_json...")
    res = llm.call_json(fallback_prompt, json.dumps(items), temperature=0.2)
    print("Call json result:", res)

asyncio.run(test())
