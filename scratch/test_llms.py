import asyncio
import os
from app.services.infrastructure.llm.service import LLMService
from app.core.config import get_settings

async def main():
    settings = get_settings()
    print("LLM_PROVIDER:", settings.llm_provider)
    print("OPENAI_BASE_URL:", settings.openai_base_url)
    llm = LLMService()
    print("Configured Provider:", llm._provider.name)
    try:
        reply = llm.call_text("Say hello.")
        print("Reply:", reply)
    except Exception as e:
        print("Error calling text:", e)

asyncio.run(main())
