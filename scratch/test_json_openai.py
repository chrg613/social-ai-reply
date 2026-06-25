import asyncio
import os
from app.services.infrastructure.llm.service import LLMService
from app.core.config import get_settings

async def main():
    os.environ["LLM_PROVIDER"] = "openai"
    settings = get_settings()
    settings.llm_provider = "openai"
    llm = LLMService()
    try:
        reply = llm.call_json("Return a JSON object with message='hello'", "Go")
        print("Reply:", reply)
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
