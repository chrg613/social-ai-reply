import asyncio
from app.services.infrastructure.llm.service import generate_reply_async

async def main():
    opp = {"title": "Test post", "body_excerpt": "Test body", "subreddit": "test"}
    brand = {"brand_name": "Test Brand", "summary": "A test brand."}
    prompts = [{"prompt_type": "reply", "name": "Default", "instructions": "Be helpful."}]
    try:
        res = await generate_reply_async(opp, brand, prompts)
        print("Reply Success:", res)
    except Exception as e:
        print("Reply Error:", e)

asyncio.run(main())
