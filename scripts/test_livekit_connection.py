"""Diagnoses and verifies your LiveKit Cloud connection."""

import asyncio
import os
from dotenv import load_dotenv
from livekit import api

load_dotenv()

async def test_livekit():
    url = os.getenv("LIVEKIT_URL")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")

    print("==================================================")
    print("       LIVEKIT CLOUD CONNECTION DIAGNOSTIC        ")
    print("==================================================")
    print(f"LIVEKIT_URL:        {url if url and 'your_' not in url else '❌ MISSING / PLACEHOLDER'}")
    print(f"LIVEKIT_API_KEY:    {api_key[:8] + '...' if api_key and 'your_' not in api_key else '❌ MISSING / PLACEHOLDER'}")
    print(f"LIVEKIT_API_SECRET: {'*' * 10 if api_secret and 'your_' not in api_secret else '❌ MISSING / PLACEHOLDER'}")

    if not url or not api_key or not api_secret or "your_" in url:
        print("\n⚠️ Please update your .env file with real credentials from https://cloud.livekit.io")
        print("See the step-by-step guide in chat.")
        return False

    print("\nAttempting to connect to LiveKit Cloud...")
    try:
        lkapi = api.LiveKitAPI(url, api_key, api_secret)
        rooms = await lkapi.room.list_rooms(api.ListRoomsRequest())
        print("✅ SUCCESS: Successfully connected to LiveKit Cloud!")
        print(f"Active rooms on your project: {len(rooms.rooms)}")
        await lkapi.aclose()
        return True
    except Exception as e:
        print(f"❌ CONNECTION FAILED: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(test_livekit())
