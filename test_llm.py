import asyncio
import os
from app.services.product.copilot.reply import _build_prompts
from app.services.infrastructure.llm.service import LLMService

async def test():
    opportunity = {
        "platform": "linkedin",
        "title": "Targeting High-Intent Shoppers",
        "body_excerpt": "Leveraging SKU and model name searches...",
        "subreddit_name": "linkedin"
    }
    brand = {
        "brand_name": "Myntra",
        "summary": "Fashion ecommerce",
        "voice_notes": "Professional",
        "call_to_action": "Visit our store"
    }
    system_prompt, user_content = _build_prompts(opportunity, brand, "Be helpful", platform="linkedin")
    
    print("System Prompt:", system_prompt)
    print("User Content:", user_content)
    
    llm = LLMService()
    payload = llm.call_json(system_prompt, user_content, temperature=0.4)
    print("Payload:", payload)
    
if __name__ == "__main__":
    asyncio.run(test())
