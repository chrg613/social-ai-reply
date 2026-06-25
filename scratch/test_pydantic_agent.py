import asyncio
import os
import json
from app.services.infrastructure.platforms.dynamic_adapter import dynamic_parser_agent
from app.core.config import get_settings

async def main():
    os.environ["LLM_PROVIDER"] = "openai"
    settings = get_settings()
    settings.llm_provider = "openai"
    
    test_data = [{"node": {"id": "1", "text": "hello"}}]
    try:
        res = await dynamic_parser_agent.run(json.dumps(test_data))
        print("Success:", res.data)
    except Exception as e:
        print("Agent Error:", e)

asyncio.run(main())
