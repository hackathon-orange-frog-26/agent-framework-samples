# Copyright (c) Microsoft. All rights reserved.
"""Launch the sandbox-hosted agent for one question, running as its agent identity."""

from __future__ import annotations

import asyncio
import sys

from .config import get_settings
from .host import AgentIdentitySandboxAgent

DEFAULT_QUESTION = "Why should an AI agent have its own identity instead of borrowing a user's?"


async def main() -> int:
    question = " ".join(sys.argv[1:]) or DEFAULT_QUESTION
    result = await AgentIdentitySandboxAgent(get_settings()).run(question)
    print(f"Agent identity: {result.agent_identity}")
    print(f"Blueprint:      {result.blueprint}")
    print(f"User-Agent:     {result.user_agent}")
    print()
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
