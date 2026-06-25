import asyncio
import os
from pydantic_ai import Agent
from app.services.infrastructure.llm.agents import _build_model
from app.core.config import get_settings

async def main():
    os.environ["LLM_PROVIDER"] = "openai"
    settings = get_settings()
    settings.llm_provider = "openai"
    model = _build_model("openai")
    agent = Agent(model, model_settings={"max_tokens": 1000})
    try:
        res = await agent.run("Say hello.")
        print("Pydantic AI Reply:", res.data)
    except Exception as e:
        print("Pydantic AI Error:", e)

asyncio.run(main())
