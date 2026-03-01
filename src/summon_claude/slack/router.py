"""ThreadRouter — thread management for Slack message routing (Layer 2)."""

from __future__ import annotations

from typing import Any

from summon_claude.slack.client import MessageRef, SlackClient

_MAX_SUBAGENT_THREADS = 100


class _LegacyProviderClient:
    """Adapter: wraps old ChatProvider + channel_id to expose SlackClient-like API.

    Used ONLY by the ThreadRouter backward-compat shim until Task 2.5 refactors
    session.py to pass a real SlackClient. Deleted along with providers/ in Task 2.5.
    """

    def __init__(self, provider: Any, channel_id: str) -> None:
        self._provider = provider
        self.channel_id = channel_id

    async def post(
        self,
        text: str,
        *,
        thread_ts: str | None = None,
        blocks: list | None = None,
        raw: bool = False,  # noqa: ARG002
    ) -> MessageRef:
        return await self._provider.post_message(
            self.channel_id, text, blocks=blocks, thread_ts=thread_ts
        )

    async def post_ephemeral(self, user_id: str, text: str, *, blocks: list | None = None) -> None:
        await self._provider.post_ephemeral(self.channel_id, user_id, text, blocks=blocks)

    async def update(self, ts: str, text: str, *, blocks: list | None = None) -> None:
        await self._provider.update_message(self.channel_id, ts, text, blocks=blocks)

    async def react(self, ts: str, emoji: str) -> None:
        await self._provider.add_reaction(self.channel_id, ts, emoji)

    async def upload(
        self, content: str, filename: str, *, title: str = "", thread_ts: str | None = None
    ) -> None:
        await self._provider.upload_file(
            self.channel_id, content, filename, title=title or filename, thread_ts=thread_ts
        )

    async def set_topic(self, topic: str) -> None:
        await self._provider.set_topic(self.channel_id, topic)


class ThreadRouter:
    """Thread management for Slack message routing (Layer 2).

    Tracks active thread and subagent threads. _client is PRIVATE.
    Knows about threads, NOT about turns.

    Constructor accepts either the new form (client: SlackClient) or the old
    form (provider, channel_id) for backward compatibility until Task 2.5
    refactors session.py to construct SlackClient directly.
    """

    def __init__(
        self, client_or_provider: SlackClient | Any, channel_id: str | None = None
    ) -> None:
        if isinstance(client_or_provider, SlackClient):
            self._client: SlackClient | _LegacyProviderClient = client_or_provider
        else:
            # Backward-compat shim: old ThreadRouter(provider, channel_id) call form.
            # Wraps the old ChatProvider behind a SlackClient-compatible adapter.
            self._client = _LegacyProviderClient(client_or_provider, channel_id or "")
        self.active_thread_ts: str | None = None
        self.active_thread_ref: MessageRef | None = None
        self.subagent_threads: dict[str, str] = {}  # tool_use_id → thread_ts
        # Turn state — retained here until Task 2.3 moves it to ResponseStreamer
        self._current_turn_number: int = 0
        self._tool_call_count: int = 0
        self._files_touched: list[str] = []

    @property
    def channel_id(self) -> str:
        return self._client.channel_id

    # --- Thread lifecycle ---

    def set_active_thread(self, ts: str, ref: MessageRef) -> None:
        """Record the active thread ts and ref."""
        self.active_thread_ts = ts
        self.active_thread_ref = ref

    def clear_active_thread(self) -> None:
        """Clear the active thread state."""
        self.active_thread_ts = None
        self.active_thread_ref = None

    # --- Turn lifecycle (moved to ResponseStreamer in Task 2.3) ---

    async def start_turn(self, turn_number: int) -> str:
        """Create turn thread starter message, return thread_ts."""
        self._current_turn_number = turn_number
        self._tool_call_count = 0
        self._files_touched = []
        ref = await self._client.post(
            f"\U0001f527 Turn {turn_number}: Processing...",
            raw=True,
        )
        self.active_thread_ts = ref.ts
        self.active_thread_ref = ref
        return ref.ts

    async def update_turn_summary(self, summary: str) -> None:
        """Update the current turn's thread starter message with a summary."""
        if self.active_thread_ref:
            await self._client.update(
                self.active_thread_ref.ts,
                f"\U0001f527 Turn {self._current_turn_number}: {summary}",
            )

    def record_tool_call(self, _tool_name: str, tool_input: dict[str, Any]) -> None:
        """Track tool calls for turn summary generation."""
        self._tool_call_count += 1
        for key in ("file_path", "path", "command"):
            if key in tool_input and isinstance(tool_input[key], str):
                path = tool_input[key]
                if "/" in path and path not in self._files_touched:
                    self._files_touched.append(path)

    def generate_turn_summary(self) -> str:
        """Build a concise summary string for the turn starter message."""
        parts: list[str] = []
        if self._tool_call_count:
            suffix = "s" if self._tool_call_count != 1 else ""
            parts.append(f"{self._tool_call_count} tool call{suffix}")
        if self._files_touched:
            short_names = [p.rsplit("/", 1)[-1] for p in self._files_touched[:3]]
            if len(self._files_touched) > 3:
                short_names.append(f"+{len(self._files_touched) - 3} more")
            parts.append(", ".join(short_names))
        return " \u00b7 ".join(parts) if parts else "Processing..."

    # --- Thread-aware posting (delegates to _client) ---

    async def post_to_main(
        self,
        text: str,
        *,
        thread_ts: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        raw: bool = False,
    ) -> MessageRef:
        """Post directly to the main channel, optionally into a thread."""
        return await self._client.post(text, thread_ts=thread_ts, blocks=blocks, raw=raw)

    async def post_to_active_thread(
        self, text: str, *, blocks: list[dict[str, Any]] | None = None, raw: bool = False
    ) -> MessageRef:
        """Post to the current active thread; falls back to main if no active thread."""
        if not self.active_thread_ts:
            return await self.post_to_main(text, blocks=blocks, raw=raw)
        return await self._client.post(
            text, blocks=blocks, thread_ts=self.active_thread_ts, raw=raw
        )

    # Backward-compatible alias — remove when session.py is refactored in Task 2.5
    async def post_to_turn_thread(
        self, text: str, *, blocks: list[dict[str, Any]] | None = None
    ) -> MessageRef:
        """Alias for post_to_active_thread (deprecated — use post_to_active_thread)."""
        return await self.post_to_active_thread(text, blocks=blocks)

    async def post_to_subagent_thread(
        self,
        tool_use_id: str,
        text: str,
        *,
        blocks: list[dict[str, Any]] | None = None,
    ) -> MessageRef:
        """Post to a subagent's dedicated thread."""
        thread_ts = self.subagent_threads.get(tool_use_id)
        if not thread_ts:
            return await self.post_to_active_thread(text, blocks=blocks)
        return await self._client.post(text, blocks=blocks, thread_ts=thread_ts)

    async def upload_to_active_thread(
        self,
        content: str,
        filename: str,
        *,
        title: str | None = None,
    ) -> None:
        """Upload a file to the current active thread."""
        await self._client.upload(
            content,
            filename,
            title=title or filename,
            thread_ts=self.active_thread_ts,
        )

    # Backward-compatible alias — remove when mcp_tools.py is refactored in Task 1.4
    async def upload_to_turn_thread(
        self,
        content: str,
        filename: str,
        *,
        title: str | None = None,
    ) -> None:
        """Alias for upload_to_active_thread (deprecated — use upload_to_active_thread)."""
        return await self.upload_to_active_thread(content, filename, title=title)

    async def update_message(self, ts: str, text: str, **kw: Any) -> None:
        """Update a message. Used by ResponseStreamer for turn summary updates.

        Note: signature is (ts, text) — channel is implicit (bound to _client.channel_id).
        """
        await self._client.update(ts, text, **kw)

    async def react(self, ts: str, emoji: str) -> None:
        """Add a reaction. Used by ResponseStreamer for turn completion checkmark."""
        await self._client.react(ts, emoji)

    # --- Subagent management ---

    async def start_subagent_thread(self, tool_use_id: str, description: str) -> str:
        """Create a dedicated subagent thread, return thread_ts."""
        # Evict oldest entries if we've hit the cap to prevent unbounded growth
        if len(self.subagent_threads) >= _MAX_SUBAGENT_THREADS:
            # dict preserves insertion order (Python 3.7+); drop oldest half
            keys = list(self.subagent_threads)
            for key in keys[: len(keys) // 2]:
                del self.subagent_threads[key]

        ref = await self._client.post(
            f"\U0001f916 Subagent: {description}",
            raw=True,
        )
        self.subagent_threads[tool_use_id] = ref.ts
        return ref.ts

    # --- Permission posting ---

    async def post_permission_ephemeral(
        self,
        user_id: str,
        text: str,
        blocks: list[dict[str, Any]],
    ) -> None:
        """Post an ephemeral permission/question prompt visible only to user_id."""
        await self._client.post_ephemeral(user_id, text, blocks=blocks)
