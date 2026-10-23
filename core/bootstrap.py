from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from uagents import Agent

ROOT = Path(__file__).resolve().parent.parent


def require_env(name: str, fallback_names: list[str] | None = None) -> str:
    load_dotenv(ROOT / ".env")
    value = os.getenv(name)
    if not value and fallback_names:
        for fb in fallback_names:
            value = os.getenv(fb)
            if value:
                break
    if not value:
        raise RuntimeError(f"Missing {name}. Set it in .env (see .env.example).")
    return value


def make_agent(
    name: str,
    seed_env: str,
    port: int,
    description: str,
    fallback_seed_envs: list[str] | None = None,
) -> Agent:
    load_dotenv(ROOT / ".env")
    seed = require_env(seed_env, fallback_seed_envs)
    port_env = seed_env.replace("_SEED", "_PORT")
    env_port = os.getenv(port_env)
    if not env_port and fallback_seed_envs:
        for fb in fallback_seed_envs:
            env_port = os.getenv(fb.replace("_SEED", "_PORT"))
            if env_port:
                break
    return Agent(
        name=name,
        seed=seed,
        port=int(env_port or port),
        mailbox=True,
        publish_agent_details=True,
        description=description,
        readme_path=str(ROOT / "README.md"),
    )
