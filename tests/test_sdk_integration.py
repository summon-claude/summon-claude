"""Real SDK integration tests — require a live Claude session.

All tests are marked @pytest.mark.slow and are skipped by default.
Run with: uv run pytest tests/test_sdk_integration.py -m slow -v
"""

from __future__ import annotations

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

# Real session ID from an existing Claude Code session (for --resume).
# The session does NOT need to be running; --resume re-uses the conversation history.
_TEST_SESSION_ID = "349dfa76-5047-4d36-a05c-ea26ef17ce9b"


@pytest.mark.slow
async def test_basic_query_and_response():
    """Send a simple query and verify we get AssistantMessage + ResultMessage."""
    options = ClaudeAgentOptions(
        cwd="/tmp",
        resume=_TEST_SESSION_ID,
        max_turns=1,
    )
    async with ClaudeSDKClient(options) as client:
        await client.query("Reply with exactly: SUMMON_TEST_OK")
        messages = []
        async for msg in client.receive_response():
            messages.append(msg)

    assert any(isinstance(m, AssistantMessage) for m in messages), "Expected AssistantMessage"
    assert any(isinstance(m, ResultMessage) for m in messages), "Expected ResultMessage"


@pytest.mark.slow
async def test_result_message_has_cost():
    """ResultMessage should expose total_cost_usd and num_turns."""
    options = ClaudeAgentOptions(
        cwd="/tmp",
        resume=_TEST_SESSION_ID,
        max_turns=1,
    )
    async with ClaudeSDKClient(options) as client:
        await client.query("What is 2 + 2?")
        result_msg = None
        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                result_msg = msg

    assert result_msg is not None
    assert hasattr(result_msg, "total_cost_usd"), "ResultMessage should have total_cost_usd"
    assert hasattr(result_msg, "num_turns"), "ResultMessage should have num_turns"
    assert isinstance(result_msg.total_cost_usd, float | int)
    assert isinstance(result_msg.num_turns, int)


@pytest.mark.slow
async def test_text_block_content():
    """AssistantMessage should contain at least one TextBlock with non-empty text."""
    options = ClaudeAgentOptions(
        cwd="/tmp",
        resume=_TEST_SESSION_ID,
        max_turns=1,
    )
    async with ClaudeSDKClient(options) as client:
        await client.query("Say hello.")
        assistant_msg = None
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                assistant_msg = msg

    assert assistant_msg is not None
    text_blocks = [b for b in assistant_msg.content if isinstance(b, TextBlock)]
    assert len(text_blocks) > 0, "AssistantMessage should have at least one TextBlock"
    assert any(b.text.strip() for b in text_blocks), "TextBlock should have non-empty text"


@pytest.mark.slow
async def test_can_use_tool_callback():
    """can_use_tool callback should be invoked when Claude reads a file."""
    invoked_tools: list[str] = []

    async def _auto_approve(tool_name: str, input_data: dict, context):
        from claude_agent_sdk import PermissionResultAllow

        invoked_tools.append(tool_name)
        return PermissionResultAllow()

    options = ClaudeAgentOptions(
        cwd="/tmp",
        resume=_TEST_SESSION_ID,
        max_turns=2,
        can_use_tool=_auto_approve,
    )
    async with ClaudeSDKClient(options) as client:
        await client.query("Please read /etc/hostname and tell me its content.")
        async for _ in client.receive_response():
            pass

    # The callback should have been invoked for at least one tool
    assert len(invoked_tools) >= 1, (
        f"Expected can_use_tool callback to be invoked, got: {invoked_tools}"
    )
