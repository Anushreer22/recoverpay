from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from uagents import Agent

import asyncio
import sys

ROOT = Path(__file__).resolve().parent.parent


DEFAULT_SEEDS = {
    "ORCHESTRATOR_SEED": "change-me-to-a-long-random-phrase",
    "VERIFIER_SEED": "change-me-verifier",
    "FALLBACK_SEED": "change-me-fallback",
    "DRAFTER_SEED": "change-me-drafter",
    "RECONCILER_SEED": "change-me-verifier",
    "RECONCILER_LITE_SEED": "change-me-fallback",
}


def require_env(name: str, fallback_names: list[str] | None = None) -> str:
    load_dotenv(ROOT / ".env")
    value = os.getenv(name)
    if not value and fallback_names:
        for fb in fallback_names:
            value = os.getenv(fb)
            if value:
                break
    if not value:
        value = DEFAULT_SEEDS.get(name)
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
    is_test = (
        "pytest" in sys.modules
        or "_pytest" in sys.modules
        or bool(os.getenv("PYTEST_CURRENT_TEST"))
        or any("pytest" in a for a in sys.argv)
    )
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    actual_port = int(env_port or port)
    public_endpoint = os.getenv("AGENT_ENDPOINT") or os.getenv(f"{name.upper().replace('-', '_')}_ENDPOINT")
    endpoints = [public_endpoint] if public_endpoint else [f"http://127.0.0.1:{actual_port}/submit"]

    use_mailbox = (
        not is_test
        and os.getenv("USE_MAILBOX", "false").lower() in {"1", "true", "yes"}
    )
    return Agent(
        name=name,
        seed=seed,
        port=actual_port,
        endpoint=endpoints,
        loop=loop,
        network="testnet",
        mailbox=use_mailbox,
        publish_agent_details=False if is_test else True,
        description=description,
        readme_path=None,
    )
