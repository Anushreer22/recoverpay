"""Script to register RecoverPay with Agentverse Chat and Discovery."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

try:
    from uagents_core.utils.registration import (
        register_chat_agent,
        RegistrationRequestCredentials,
    )
except ImportError as err:
    print(f"Error importing uagents_core: {err}")
    sys.exit(1)


def register():
    api_key = os.getenv("AGENTVERSE_KEY") or os.getenv("AGENTVERSE_API_KEY")
    if not api_key:
        print("\n[!] AGENTVERSE_KEY not found in environment or .env")
        print("Please copy your Agentverse API Key and run:")
        print("  $env:AGENTVERSE_KEY = 'your_agentverse_key_here'")
        print("  python scripts/register_agent.py\n")
        return False

    seed_phrase = (
        os.getenv("AGENT_SEED_PHRASE")
        or os.getenv("ORCHESTRATOR_SEED")
        or "change-me-to-a-long-random-phrase"
    )
    endpoint = os.getenv("AGENT_ENDPOINT", "https://modern-houses-brush.loca.lt/submit")
    if not endpoint.endswith("/submit"):
        endpoint = f"{endpoint.rstrip('/')}/submit"

    print("=" * 60)
    print("  Connecting RecoverPay to Agentverse")
    print("=" * 60)
    print(f"Agent Name : recoverpay")
    print(f"Endpoint   : {endpoint}")
    print(f"Seed       : {seed_phrase[:15]}...")

    try:
        register_chat_agent(
            "recoverpay",
            endpoint,
            active=True,
            credentials=RegistrationRequestCredentials(
                agentverse_api_key=api_key,
                agent_seed_phrase=seed_phrase,
            ),
        )
        print("\n[SUCCESS] Registered successfully with Agentverse!")
        print("Your agent status on Agentverse is now ACTIVE.")
        print("=" * 60)
        return True
    except Exception as exc:
        print(f"\n[ERROR] Registration failed: {exc}")
        return False


if __name__ == "__main__":
    register()

