import asyncio
from backend.crawler import fetch_model_spec
import json

async def test_crawler():
    model_name = "KQ65QNC85AFXKR"
    print(f"Testing Danawa crawler for model: {model_name}...")
    result = await fetch_model_spec(model_name)
    
    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print("Success! Data retrieved:")
        # Indent for better readability
        print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(test_crawler())
