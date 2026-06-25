import asyncio
import os
from app.services.infrastructure.llm.service import generate_reply_async
from app.core.config import get_settings

async def main():
    os.environ["LLM_PROVIDER"] = "openai"
    # Ensure OPENAI_BASE_URL is set in environment since app might not reload automatically
    settings = get_settings()
    settings.llm_provider = "openai"
    
    opp = {"title": "Test post", "body_excerpt": "Test body", "subreddit": "test"}
    brand = {"brand_name": "Test Brand", "summary": "A test brand."}
    prompts = [{"prompt_type": "reply", "name": "Default", "instructions": "Be helpful."}]
    try:
        res = await generate_reply_async(opp, brand, prompts)
        print("Reply Success:", res)
    except Exception as e:
        print("Reply Error:", e)

asyncio.run(main())
