# Copyright (c) Microsoft. All rights reserved.
"""Launch the sandbox-hosted agent for one question, running as its agent identity."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .config import get_settings
from .host import AgentIdentitySandboxAgent

DEFAULT_QUESTION = "Find architecture guidance in my Microsoft 365 documents and summarize it with source links."


async def main() -> int:
    question = " ".join(sys.argv[1:]) or DEFAULT_QUESTION
    settings = get_settings()
    if not settings.user_assertion_file:
        raise RuntimeError("AGENT_USER_ASSERTION_FILE is required. Run python -m app.sign_in first.")
    user_assertion = Path(settings.user_assertion_file).read_text(encoding="utf-8").strip()
    result = await AgentIdentitySandboxAgent(settings).run(question, user_assertion=user_assertion)
    print(f"Agent identity: {result.agent_identity}")
    print(f"Blueprint:      {result.blueprint}")
    print(f"User-Agent:     {result.user_agent}")
    print()
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
