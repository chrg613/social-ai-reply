import asyncio
from app.api.v1.routes.scrapers import ChatRequest, scrapers_chat_endpoint
from app.schemas.v1.scrapers import CustomScraperCreateRequest

async def test():
    req = ChatRequest(
        message="I am using Instagram Cheapest API. Host: instagram-cheapest.p.rapidapi.com. Endpoint: /api/v1/instagram/media_comments. What should my JSON paths be?",
        history=[]
    )
    # The endpoint is synchronous!
    res = scrapers_chat_endpoint(req)
    print("AI Reply:")
    print(res.reply)

if __name__ == "__main__":
    asyncio.run(test())
