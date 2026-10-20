from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from uagents import Agent

ROOT = Path(__file__).resolve().parent.parent


def require_env(name: str) -> str:
    load_dotenv(ROOT / ".env")
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name}. Set it in .env (see .env.example).")
    return value


def make_agent(name: str, seed_env: str, port: int, description: str) -> Agent:
    load_dotenv(ROOT / ".env")
    return Agent(
        name=name,
        seed=require_env(seed_env),
        port=int(os.getenv(f"{seed_env.replace('_SEED', '_PORT')}", str(port))),
        mailbox=True,
        publish_agent_details=True,
        description=description,
        readme_path=str(ROOT / "README.md"),
    )
