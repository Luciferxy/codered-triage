"""Test OpenRouter API key and model inference."""

import asyncio
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

async def test_openrouter():
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")

    print(f"Connecting to OpenRouter ({base_url}) with model '{model}'...")
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an emergency clinical assistant. Reply in one short sentence."},
                {"role": "user", "content": "Patient in ventricular fibrillation, what is the immediate action?"}
            ],
            max_tokens=60
        )
        answer = response.choices[0].message.content
        print("✅ OpenRouter Response:", answer)
        return True
    except Exception as e:
        print("❌ OpenRouter Error:", e)
        return False

if __name__ == "__main__":
    asyncio.run(test_openrouter())
