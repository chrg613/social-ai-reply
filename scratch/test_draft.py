import asyncio
from app.services.product.copilot.reply import generate_reply_async

async def main():
    opp = {
        "subreddit_name": "test",
        "title": "Need a scheduling tool",
        "author": "bob",
        "permalink": "http://test",
        "platform": "reddit"
    }
    brand = {
        "name": "SocialReply",
        "description": "We are an AI tool."
    }
    prompts = [{"content": "Draft a helpful reply."}]
    res = await generate_reply_async(opp, brand, prompts)
    print("Result:", res)

asyncio.run(main())
