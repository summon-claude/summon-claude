"""Debounced permission handler — batches tool approval requests and posts to Slack."""

# pyright: reportArgumentType=false, reportReturnType=false
# claude_agent_sdk doesn't ship type stubs

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

from summon_claude.config import SummonConfig
from summon_claude.sessions.response import get_tool_primary_arg
from summon_claude.slack.client import sanitize_for_mrkdwn
from summon_claude.slack.router import ThreadRouter

logger = logging.getLogger(__name__)

_AUTO_APPROVE_TOOLS = frozenset(
    [
        "Read",
        "Cat",
        "Grep",
        "Glob",
        "WebSearch",
        "WebFetch",
        "LSP",
        "ListFiles",
        "GetSymbolsOverview",
        "FindSymbol",
        "FindReferencingSymbols",
    ]
)

# GitHub MCP tools that are always auto-approved (read-only operations)
_GITHUB_MCP_AUTO_APPROVE = frozenset(
    [
        "mcp__github__pull_request_read",
        "mcp__github__get_file_contents",
    ]
)

# GitHub MCP tool name prefixes that are auto-approved
_GITHUB_MCP_AUTO_APPROVE_PREFIXES = (
    "mcp__github__get_",
    "mcp__github__list_",
    "mcp__github__search_",
)

# GitHub MCP tools that ALWAYS require Slack approval — never auto-approved,
# even if SDK suggestions say "allow". Defense-in-depth against broad
# allowedTools patterns in settings.json bypassing HITL.
# Summon's own MCP tools — always auto-approved.
# These are internal tools provided by the session's own MCP servers
# (summon-cli, summon-slack, summon-canvas) and already scoped to
# the session's permissions.
_SUMMON_MCP_AUTO_APPROVE_PREFIXES = (
    "mcp__summon-cli__",
    "mcp__summon-slack__",
    "mcp__summon-canvas__",
)

_GITHUB_MCP_REQUIRE_APPROVAL = frozenset(
    [
        # Destructive operations
        "mcp__github__merge_pull_request",
        "mcp__github__delete_branch",
        "mcp__github__close_pull_request",
        "mcp__github__close_issue",
        "mcp__github__update_pull_request_branch",
        "mcp__github__push_files",
        "mcp__github__create_or_update_file",
        # Visible-to-others actions (notify reviewers, trigger CI, auto-merge, etc.)
        "mcp__github__pull_request_review_write",
        "mcp__github__create_pull_request",
        "mcp__github__create_issue",
        "mcp__github__add_issue_comment",
    ]
)

_PERMISSION_TIMEOUT_S = 300  # 5 minutes


def _is_in_safe_dir(file_path: str, safe_dirs: list[str], project_root: Path | None) -> bool:
    """Return True if file_path resolves to within any of the safe_dirs.

    Security constraints:
    - project_root must be an absolute path; if missing or relative, returns False (fail-closed).
    - Both file_path and each safe dir are resolved via Path.resolve() before comparison
      to prevent symlink escapes.
    - project_root is used to resolve relative file paths only; it is not itself a safe dir.
    """
    if not project_root or not project_root.is_absolute():
        return False

    if not safe_dirs:
        return False

    try:
        fp = Path(file_path)
        resolved_file = (project_root / fp).resolve() if not fp.is_absolute() else fp.resolve()
    except (ValueError, OSError):
        return False

    for safe_dir in safe_dirs:
        if not safe_dir:
            continue
        try:
            resolved_safe = (project_root / safe_dir).resolve()
            if resolved_file.is_relative_to(resolved_safe):
                return True
        except (ValueError, OSError):
            continue

    return False


@dataclass
class PendingRequest:
    """A single tool use permission request waiting for user approval."""

    request_id: str
    tool_name: str
    input_data: dict[str, Any]
    result_event: asyncio.Event = field(default_factory=asyncio.Event)
    approved: bool = False


@dataclass
class _BatchState:
    """Tracks in-flight permission batches awaiting user resolution."""

    events: dict[str, asyncio.Event] = field(default_factory=dict)
    decisions: dict[str, bool] = field(default_factory=dict)
    message_ts: dict[str, str] = field(default_factory=dict)
    # Tool names per batch — used to populate session-approve cache on approval
    tool_names: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class _AskUserState:
    """Tracks in-flight AskUserQuestion requests awaiting user answers."""

    events: dict[str, asyncio.Event] = field(default_factory=dict)
    questions: dict[str, list[dict]] = field(default_factory=dict)
    answers: dict[str, dict[str, str]] = field(default_factory=dict)
    expected: dict[str, int] = field(default_factory=dict)
    # For "Other" free-text input: (request_id, question_index)
    pending_other: tuple[str, int] | None = None
    # For multi-select: toggled selections per question keyed by (request_id, question_idx)
    multi_selections: dict[tuple[str, int], list[str]] = field(default_factory=dict)
    # ts of the interactive question message (for deletion on completion)
    message_ts: dict[str, str] = field(default_factory=dict)


class PermissionHandler:
    """Handles tool permission requests with 500ms debouncing and Slack interactive buttons.

    Safe tools (Read, Grep, Glob, WebSearch, WebFetch) are auto-approved.
    Risky tools (Write, Edit, Bash, etc.) are batched into a single Slack
    message per debounce window and wait for user approval.

    Permission messages are posted with reply_broadcast=True (when in a thread)
    and <!channel> to notify all channel members. The 500ms debounce window
    batches rapid permission requests into a single message, so <!channel>
    fires once per batch — not once per individual tool request.
    """

    def __init__(
        self,
        router: ThreadRouter,
        config: SummonConfig,
        authenticated_user_id: str,
    ) -> None:
        self._router = router
        self._authenticated_user_id = authenticated_user_id
        self._debounce_ms = config.permission_debounce_ms

        # Pending requests waiting for batched approval
        self._pending: dict[str, PendingRequest] = {}
        self._batch_task: asyncio.Task | None = None
        self._batch_lock = asyncio.Lock()

        # Per-batch tracking (events, decisions)
        self._batch = _BatchState()

        # Session-lifetime per-tool approval cache
        self._session_approved_tools: set[str] = set()

        # AskUserQuestion tracking
        self._ask_user = _AskUserState()

    async def handle(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext | None,
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Main entry point for the can_use_tool callback."""
        # 0. Intercept AskUserQuestion — route to Slack interactive UI
        if tool_name == "AskUserQuestion":
            return await self._handle_ask_user_question(input_data)

        # 1. Check SDK suggestions for deny — always honor denials unconditionally
        if context is not None:
            for suggestion in getattr(context, "suggestions", []) or []:
                if getattr(suggestion, "behavior", None) == "deny":
                    logger.info("SDK suggestion: denying %s", tool_name)
                    return PermissionResultDeny(message="Denied by permission rules")

        # 2. Static auto-approve list is the primary gate for allowing tools
        if tool_name in _AUTO_APPROVE_TOOLS:
            logger.debug("Auto-approving tool: %s", tool_name)
            return PermissionResultAllow()

        # 2b. Restricted GitHub MCP tools always require Slack approval —
        # checked before auto-approve so deny-list takes precedence over prefixes
        if tool_name in _GITHUB_MCP_REQUIRE_APPROVAL:
            logger.info("Restricted GitHub MCP tool requires approval: %s", tool_name)
            return await self._request_approval(tool_name, input_data, context)

        # 2c. GitHub MCP auto-approve: exact names and prefix matches
        if tool_name in _GITHUB_MCP_AUTO_APPROVE or tool_name.startswith(
            _GITHUB_MCP_AUTO_APPROVE_PREFIXES
        ):
            logger.debug("Auto-approving GitHub MCP tool: %s", tool_name)
            return PermissionResultAllow()

        # 2d. Summon's own MCP tools — always auto-approved.
        # These are internal tools provided by the session's own MCP servers
        # (summon-cli, summon-slack, summon-canvas) and already scoped to
        # the session's permissions.
        if tool_name.startswith(_SUMMON_MCP_AUTO_APPROVE_PREFIXES):
            logger.debug("Auto-approving summon MCP tool: %s", tool_name)
            return PermissionResultAllow()

        # 2e. Session-lifetime cached approvals (SC-2/SEC-D-001: defense-in-depth
        # check ensures GitHub require-approval tools are never session-cached)
        if (
            tool_name in self._session_approved_tools
            and tool_name not in _GITHUB_MCP_REQUIRE_APPROVAL
        ):
            logger.debug("Session-approved tool: %s", tool_name)
            return PermissionResultAllow()

        # 3. Check SDK suggestions for allow — secondary, after static allowlist
        if context is not None:
            for suggestion in getattr(context, "suggestions", []) or []:
                if getattr(suggestion, "behavior", None) == "allow":
                    logger.info("SDK suggestion: approving %s", tool_name)
                    return PermissionResultAllow()
                # behavior == "ask" or None falls through to Slack buttons

        # 4. Request user approval via Slack
        logger.info("Permission required for tool: %s", tool_name)
        return await self._request_approval(tool_name, input_data, context)

    async def _request_approval(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext | None,
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Queue a permission request and wait for user approval."""
        request_id = str(uuid.uuid4())
        req = PendingRequest(
            request_id=request_id,
            tool_name=tool_name,
            input_data=input_data,
        )

        async with self._batch_lock:
            self._pending[request_id] = req

            # Start or reset the debounce timer
            if self._batch_task and not self._batch_task.done():
                self._batch_task.cancel()
            self._batch_task = asyncio.create_task(self._debounce_and_post())

        # Wait for this specific request to be resolved
        try:
            async with asyncio.timeout(_PERMISSION_TIMEOUT_S):
                await req.result_event.wait()
        except TimeoutError:
            logger.warning("Permission request timed out for tool %s", tool_name)
            await self._post_timeout_message()
            return PermissionResultDeny(message="Permission request timed out (5 minutes)")

        if req.approved:
            return PermissionResultAllow()
        return PermissionResultDeny(message="Denied by user in Slack")

    async def _debounce_and_post(self) -> None:
        """Wait for the debounce window, then post a single batch message."""
        await asyncio.sleep(self._debounce_ms / 1000.0)

        async with self._batch_lock:
            if not self._pending:
                return
            batch = dict(self._pending)
            self._pending.clear()

        batch_id = str(uuid.uuid4())
        batch_event = asyncio.Event()
        self._batch.events[batch_id] = batch_event
        self._batch.tool_names[batch_id] = [req.tool_name for req in batch.values()]

        await self._post_approval_message(batch_id, batch)

        # Wait for user response
        try:
            async with asyncio.timeout(_PERMISSION_TIMEOUT_S):
                await batch_event.wait()
        except TimeoutError:
            approved = False
            msg_ts = self._batch.message_ts.pop(batch_id, None)
            if msg_ts:
                await self._router.client.delete_message(msg_ts)
        else:
            approved = self._batch.decisions.get(batch_id, False)

        # Resolve all requests in this batch
        for req in batch.values():
            req.approved = approved
            req.result_event.set()

        # Cleanup
        self._batch.events.pop(batch_id, None)
        self._batch.decisions.pop(batch_id, None)
        self._batch.message_ts.pop(batch_id, None)
        self._batch.tool_names.pop(batch_id, None)

    async def _post_approval_message(self, batch_id: str, batch: dict[str, PendingRequest]) -> None:
        """Post the Slack interactive approval message for a batch of requests."""
        requests = list(batch.values())

        if len(requests) == 1:
            req = requests[0]
            summary = _format_request_summary(req)
            header_text = f"Claude wants to run:\n{summary}"
        else:
            summaries = "\n".join(
                f"{i + 1}. {_format_request_summary(r)}" for i, r in enumerate(requests)
            )
            header_text = f"Claude wants to perform {len(requests)} actions:\n{summaries}"

        approve_value = f"approve:{batch_id}"
        approve_session_value = f"approve_session:{batch_id}"
        deny_value = f"deny:{batch_id}"

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": header_text},
            },
            {
                "type": "actions",
                "block_id": f"permission_{batch_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "permission_approve",
                        "value": approve_value,
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Approve for session",
                        },
                        "action_id": "permission_approve_session",
                        "value": approve_session_value,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Deny"},
                        "style": "danger",
                        "action_id": "permission_deny",
                        "value": deny_value,
                    },
                ],
            },
        ]

        try:
            ref = await self._router.client.post_interactive(
                f"Permission required: {header_text[:100]}",
                blocks=blocks,
            )
            self._batch.message_ts[batch_id] = ref.ts
        except Exception as e:
            logger.error("Failed to post permission message: %s", e)
            # Auto-deny if we can't post
            self._batch.decisions[batch_id] = False
            if batch_id in self._batch.events:
                self._batch.events[batch_id].set()

    async def handle_action(
        self,
        value: str,
        user_id: str,
        response_url: str = "",
    ) -> None:
        """Handle a Slack interactive button click for permission approval/denial.

        Must be called AFTER ack() (the 3-second deadline is the caller's responsibility).
        Channel routing is handled by ``EventDispatcher.dispatch_action``.
        """
        if user_id != self._authenticated_user_id:
            logger.warning(
                "Permission action from unauthorized user %s (expected %s)",
                user_id,
                self._authenticated_user_id,
            )
            return

        if value.startswith("approve:"):
            batch_id = value[len("approve:") :]
            approved = True
        elif value.startswith("approve_session:"):
            batch_id = value[len("approve_session:") :]
            approved = True
            # Cache tool names for session lifetime
            # (except GitHub require-approval — those always need HITL)
            for name in self._batch.tool_names.get(batch_id, []):
                if name not in _GITHUB_MCP_REQUIRE_APPROVAL:
                    self._session_approved_tools.add(name)
        elif value.startswith("deny:"):
            batch_id = value[len("deny:") :]
            approved = False
        else:
            logger.warning("Unknown permission action value: %r", value)
            return

        self._batch.decisions[batch_id] = approved

        # Delete the interactive message (replaces ephemeral dismiss)
        msg_ts = self._batch.message_ts.pop(batch_id, None)
        if msg_ts:
            await self._router.client.delete_message(msg_ts)

        # Post a persistent confirmation to the turn thread (SC-3/SEC-D-007:
        # include tool names since the interactive message is now deleted)
        tool_names = self._batch.tool_names.get(batch_id, [])
        tool_list = ", ".join(f"`{t}`" for t in tool_names) if tool_names else "tools"
        session_suffix = " for session" if value.startswith("approve_session:") else ""
        status_text = ":white_check_mark: Approved" if approved else ":x: Denied"
        try:
            msg = f"{status_text}{session_suffix}: {tool_list}"
            await self._router.post_to_active_thread(msg)
        except Exception as e:
            logger.warning("Failed to post permission confirmation: %s", e)

        # Signal the waiting batch
        if batch_id in self._batch.events:
            self._batch.events[batch_id].set()

    async def _post_timeout_message(self) -> None:
        """Post a message indicating permission timed out."""
        try:
            await self._router.post_to_active_thread(
                ":hourglass: Permission request timed out after 5 minutes. Denied.",
            )
        except Exception as e:
            logger.warning("Failed to post timeout message: %s", e)

    # ------------------------------------------------------------------
    # AskUserQuestion handling
    # ------------------------------------------------------------------

    async def _handle_ask_user_question(
        self, input_data: dict[str, Any]
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Render AskUserQuestion as Slack interactive buttons and wait for answers."""
        questions = input_data.get("questions", [])
        if not questions:
            return PermissionResultAllow(updated_input=input_data)

        request_id = str(uuid.uuid4())
        event = asyncio.Event()

        self._ask_user.events[request_id] = event
        self._ask_user.questions[request_id] = questions
        self._ask_user.answers[request_id] = {}
        self._ask_user.expected[request_id] = len(questions)

        blocks = _build_ask_user_blocks(request_id, questions)
        try:
            # Ping user in main channel FIRST so the notification arrives
            if self._authenticated_user_id:
                try:
                    await self._router.post_to_main(
                        f"<@{self._authenticated_user_id}> Question from Claude",
                    )
                except Exception as e:
                    logger.warning("Failed to post ask-user ping to main channel: %s", e)
            ref = await self._router.client.post_interactive(
                "Claude has a question for you",
                blocks=blocks,
            )
            self._ask_user.message_ts[request_id] = ref.ts
        except Exception as e:
            logger.error("Failed to post AskUserQuestion message: %s", e)
            self._cleanup_ask_user(request_id)
            return PermissionResultDeny(message="Failed to display question")

        try:
            async with asyncio.timeout(_PERMISSION_TIMEOUT_S):
                await event.wait()
        except TimeoutError:
            logger.warning("AskUserQuestion timed out")
            # Delete the question message on timeout
            msg_ts = self._ask_user.message_ts.get(request_id)
            if msg_ts:
                await self._router.client.delete_message(msg_ts)
            self._cleanup_ask_user(request_id)
            return PermissionResultDeny(message="Question timed out (5 minutes)")

        answers = dict(self._ask_user.answers.get(request_id, {}))
        self._cleanup_ask_user(request_id)

        return PermissionResultAllow(
            updated_input={
                "questions": questions,
                "answers": answers,
            }
        )

    async def handle_ask_user_action(
        self,
        value: str,
        user_id: str,
        response_url: str = "",
    ) -> None:
        """Handle a Slack button click for an AskUserQuestion option.

        Value format: ``{request_id}|{question_idx}|{option_idx_or_other_or_done}``
        """
        if user_id != self._authenticated_user_id:
            logger.warning(
                "Ask user action from unauthorized user %s (expected %s)",
                user_id,
                self._authenticated_user_id,
            )
            return

        parsed = _parse_ask_user_value(value)
        if parsed is None:
            return

        request_id, q_idx, opt_val = parsed

        if request_id not in self._ask_user.events:
            return

        questions = self._ask_user.questions.get(request_id, [])
        if q_idx >= len(questions):
            return

        question = questions[q_idx]

        if opt_val == "other":
            await self._handle_ask_other(request_id, q_idx, question)
        elif opt_val == "done":
            await self._handle_ask_done(request_id, q_idx, question)
        else:
            await self._handle_ask_option(request_id, q_idx, question, opt_val)

    async def _handle_ask_other(self, request_id: str, q_idx: int, question: dict) -> None:
        """Handle 'Other' button — set pending flag for free-text capture."""
        self._ask_user.pending_other = (request_id, q_idx)
        q_text = sanitize_for_mrkdwn(question.get("question", ""))
        await _post_quietly(
            self._router,
            f":pencil: Type your answer for: _{q_text}_",
        )

    async def _handle_ask_done(self, request_id: str, q_idx: int, question: dict) -> None:
        """Handle 'Done' button for multi-select — finalize toggled selections."""
        key = (request_id, q_idx)
        selections = self._ask_user.multi_selections.pop(key, [])
        answer = ", ".join(selections) if selections else ""
        q_text = question.get("question", "")
        header = sanitize_for_mrkdwn(question.get("header", ""))
        self._ask_user.answers[request_id][q_text] = answer
        await _post_quietly(
            self._router,
            f":white_check_mark: *{header}*: {sanitize_for_mrkdwn(answer)}",
        )
        await self._check_ask_user_complete(request_id)

    async def _handle_ask_option(
        self, request_id: str, q_idx: int, question: dict, opt_val: str
    ) -> None:
        """Handle a numbered option button click."""
        try:
            opt_idx = int(opt_val)
        except ValueError:
            return

        options = question.get("options", [])
        if opt_idx >= len(options):
            return

        label = options[opt_idx].get("label", "")
        q_text = question.get("question", "")
        header = sanitize_for_mrkdwn(question.get("header", ""))

        if question.get("multiSelect", False):
            await self._toggle_multi_select(request_id, q_idx, label, header)
        else:
            self._ask_user.answers[request_id][q_text] = label
            await _post_quietly(
                self._router,
                f":white_check_mark: *{header}*: {sanitize_for_mrkdwn(label)}",
            )
            await self._check_ask_user_complete(request_id)

    async def _toggle_multi_select(
        self, request_id: str, q_idx: int, label: str, header: str
    ) -> None:
        """Toggle a multi-select option and post feedback."""
        key = (request_id, q_idx)
        selections = self._ask_user.multi_selections.setdefault(key, [])
        safe_label = sanitize_for_mrkdwn(label)
        if label in selections:
            selections.remove(label)
            await _post_quietly(
                self._router,
                f":heavy_minus_sign: *{header}*: deselected _{safe_label}_",
            )
        else:
            selections.append(label)
            await _post_quietly(
                self._router,
                f":heavy_plus_sign: *{header}*: selected _{safe_label}_",
            )

    def has_pending_text_input(self) -> bool:
        """Return True if we're waiting for free-text input from the user (Other)."""
        return self._ask_user.pending_other is not None

    async def receive_text_input(self, text: str, *, user_id: str) -> None:
        """Receive free-text input from the user for an 'Other' answer.

        Args:
            text: The free-text answer.
            user_id: Slack user ID of the sender. Verified against session owner.
                     Required — callers must always provide identity context.
        """
        if not self._ask_user.pending_other:
            return

        if user_id != self._authenticated_user_id:
            logger.warning(
                "Free-text input from unauthorized user %s (expected %s)",
                user_id,
                self._authenticated_user_id,
            )
            return

        request_id, q_idx = self._ask_user.pending_other
        self._ask_user.pending_other = None

        questions = self._ask_user.questions.get(request_id, [])
        if q_idx >= len(questions):
            return

        question = questions[q_idx]
        question_text = question.get("question", "")
        header = question.get("header", "")

        self._ask_user.answers[request_id][question_text] = text
        safe_header = sanitize_for_mrkdwn(header)
        await _post_quietly(
            self._router,
            f":white_check_mark: *{safe_header}*: {sanitize_for_mrkdwn(text)}",
        )

        await self._check_ask_user_complete(request_id)

    async def _check_ask_user_complete(self, request_id: str) -> None:
        """If all questions for a request are answered, delete message and signal."""
        answers = self._ask_user.answers.get(request_id, {})
        expected = self._ask_user.expected.get(request_id, 0)
        if len(answers) >= expected:
            # Delete the interactive question message
            msg_ts = self._ask_user.message_ts.get(request_id)
            if msg_ts:
                await self._router.client.delete_message(msg_ts)
            event = self._ask_user.events.get(request_id)
            if event:
                event.set()

    def _cleanup_ask_user(self, request_id: str) -> None:
        """Remove all state for a completed or timed-out ask_user request."""
        self._ask_user.events.pop(request_id, None)
        questions = self._ask_user.questions.pop(request_id, [])
        self._ask_user.answers.pop(request_id, None)
        self._ask_user.expected.pop(request_id, None)
        self._ask_user.message_ts.pop(request_id, None)
        if self._ask_user.pending_other and self._ask_user.pending_other[0] == request_id:
            self._ask_user.pending_other = None
        # Clean up multi-select state for all questions in this request
        for i in range(len(questions)):
            self._ask_user.multi_selections.pop((request_id, i), None)


def _parse_ask_user_value(value: str) -> tuple[str, int, str] | None:
    """Parse an ask_user action value into (request_id, question_idx, opt_val)."""
    parts = value.split("|")
    if len(parts) != 3:
        logger.warning("Invalid ask_user action value: %r", value)
        return None
    request_id, q_idx_str, opt_val = parts
    try:
        q_idx = int(q_idx_str)
    except ValueError:
        return None
    return request_id, q_idx, opt_val


async def _post_quietly(router: ThreadRouter, text: str) -> None:
    """Post to the turn thread, swallowing errors."""
    try:
        await router.post_to_active_thread(text)
    except Exception as e:
        logger.warning("Failed to post ask_user feedback: %s", e)


def _build_ask_user_blocks(request_id: str, questions: list[dict]) -> list[dict]:
    """Build Slack Block Kit blocks for AskUserQuestion rendering."""
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":question: *Claude has a question for you*"},
        },
        {"type": "divider"},
    ]

    for i, q in enumerate(questions):
        header = q.get("header", "")
        question_text = q.get("question", "")
        options = q.get("options", [])
        multi_select = q.get("multiSelect", False)

        # Question text (with multi-select hint)
        q_text = f"*{sanitize_for_mrkdwn(header)}*\n{sanitize_for_mrkdwn(question_text)}"
        if multi_select:
            q_text += "\n_Select multiple, then click Done_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": q_text}})

        # Option descriptions + markdown previews as context
        desc_parts = []
        for opt in options:
            label = opt.get("label", "")
            desc = opt.get("description", "")
            md_preview = opt.get("markdown", "")
            if desc:
                desc_parts.append(
                    f"\u2022 *{sanitize_for_mrkdwn(label)}*: {sanitize_for_mrkdwn(desc)}"
                )
            if md_preview:
                # Render markdown preview as a code block (monospace)
                # Escape backticks to prevent breaking out of the code block
                safe_preview = md_preview.strip().replace("`", "\u2019")
                preview_lines = safe_preview.splitlines()
                # Truncate long previews to keep Slack message manageable
                if len(preview_lines) > 8:
                    preview_lines = [*preview_lines[:8], "..."]
                preview_text = "\n".join(preview_lines)
                desc_parts.append(f"```{preview_text}```")
        if desc_parts:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "\n".join(desc_parts)}],
                }
            )

        # Option buttons
        elements = []
        for j, opt in enumerate(options):
            label = opt.get("label", f"Option {j + 1}")
            elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": label[:75]},
                    "action_id": f"ask_user_{i}_{j}",
                    "value": f"{request_id}|{i}|{j}",
                }
            )

        # "Other" button
        elements.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Other"},
                "action_id": f"ask_user_{i}_other",
                "value": f"{request_id}|{i}|other",
            }
        )

        # "Done" button for multi-select
        if multi_select:
            elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Done"},
                    "style": "primary",
                    "action_id": f"ask_user_{i}_done",
                    "value": f"{request_id}|{i}|done",
                }
            )

        blocks.append(
            {
                "type": "actions",
                "block_id": f"ask_user_{request_id[:8]}_{i}",
                "elements": elements,
            }
        )

    return blocks


def _format_request_summary(req: PendingRequest) -> str:
    """Create a human-readable summary of a permission request."""
    tool = req.tool_name
    data = req.input_data

    arg = get_tool_primary_arg(tool, data)
    if arg:
        safe_arg = sanitize_for_mrkdwn(arg)
        return f"`{tool}`: `{safe_arg}`"

    # Generic fallback
    keys = list(data.keys())[:2]
    params = ", ".join(f"{k}={sanitize_for_mrkdwn(str(data[k]), 40)!r}" for k in keys)
    return f"`{tool}`({params})"
