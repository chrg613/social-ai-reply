import asyncio
import httpx
from app.main import app

async def test():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        try:
            response = await ac.post(
                "/v1/auth/register",
                json={"email": "test13@test.com", "password": "password123", "full_name": "Test User 13", "workspace_name": "Test Workspace 13"}
            )
            print("Status:", response.status_code)
            print("Response:", response.text)
        except Exception as e:
            import traceback
            traceback.print_exc()

asyncio.run(test())
