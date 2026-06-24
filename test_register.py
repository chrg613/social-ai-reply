import asyncio
from httpx import AsyncClient
from app.main import app

async def test():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/v1/auth/register",
            json={"email": "test@test.com", "password": "password123", "full_name": "Test User", "workspace_name": "Test Workspace"}
        )
        print(response.status_code)
        print(response.text)

asyncio.run(test())
