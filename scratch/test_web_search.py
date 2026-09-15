import asyncio
import httpx
from bs4 import BeautifulSoup
import urllib.parse
from app.agents.orchestrator import _execute_web_search

async def main():
    res = await _execute_web_search("cm of telangana")
    print("WEB SEARCH RESULT:")
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
