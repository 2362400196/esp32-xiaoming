import httpx
async def f():
    async with httpx.AsyncClient() as c:
        await c.get('https://x.com')
