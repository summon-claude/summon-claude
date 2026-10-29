"""Tests for AskUserQuestion handling in summon_claude.permissions."""

from __future__ import annotations

import asyncio
import contextlib

from claude_agent_sdk import PermissionResultAllow
from conftest import make_test_config

from helpers import make_mock_slack_client
from summon_claude.sessions.permissions import (
    PermissionHandler,
    _build_ask_user_blocks,
)
from summon_claude.slack.router import ThreadRouter


def _make_handler():
    client = make_mock_slack_client()
    router = ThreadRouter(client)
    config = make_test_config(permission_debounce_ms=10)
    return PermissionHandler(router, config, authenticated_user_id="U1"), client, router


def _get_actions_block(blocks: list[dict], idx: int = 0) -> dict:
    """Return the Nth actions block from a list of Slack blocks."""
    return [b for b in blocks if b["type"] == "actions"][idx]


def _extract_request_id(provider) -> str:
    """Extract the request_id from the last posted AskUserQuestion message."""
    for call in provider.post_interactive.call_args_list:
        blocks = call.kwargs.get("blocks")
        if blocks:
            for b in blocks:
                if b["type"] == "actions":
                    return b["elements"][0]["value"].split("|")[0]
    msg = "No ask_user blocks found in posted messages"
    raise AssertionError(msg)


async def _start_ask(handler, provider, questions):
    """Start an AskUserQuestion and return (task, request_id)."""
    task = asyncio.create_task(handler.handle("AskUserQuestion", {"questions": questions}, None))
    await asyncio.sleep(0.05)
    request_id = _extract_request_id(provider)
    return task, request_id


async def _click(handler, request_id, q_idx, opt_val):
    """Simulate a button click."""
    await handler.handle_ask_user_action(
        value=f"{request_id}|{q_idx}|{opt_val}",
        user_id="U1",
    )


# ------------------------------------------------------------------
# Block rendering
# ------------------------------------------------------------------


def _make_many_options(n: int) -> list[dict]:
    """Build a list of n options for testing select-menu threshold."""
    return [{"label": f"Option {i}", "description": ""} for i in range(n)]


class TestBuildAskUserBlocks:
    def test_single_question_produces_section_and_actions(self):
        questions = [
            {
                "question": "Which DB?",
                "header": "Database",
                "options": [
                    {"label": "PostgreSQL", "description": "Relational DB"},
                    {"label": "MongoDB", "description": "Document DB"},
                ],
                "multiSelect": False,
            }
        ]
        blocks = _build_ask_user_blocks("req-123", questions)
        assert any(b["type"] == "section" for b in blocks)
        actions = _get_actions_block(blocks)
        # 2 options + 1 Other = 3 buttons
        assert len(actions["elements"]) == 3

    def test_other_button_always_present(self):
        questions = [
            {
                "question": "Pick one",
                "header": "Test",
                "options": [{"label": "A", "description": ""}],
                "multiSelect": False,
            }
        ]
        blocks = _build_ask_user_blocks("req-1", questions)
        actions = _get_actions_block(blocks)
        other_btns = [e for e in actions["elements"] if e["text"]["text"] == "Other"]
        assert len(other_btns) == 1

    def test_multi_select_adds_done_button(self):
        questions = [
            {
                "question": "Select features",
                "header": "Features",
                "options": [
                    {"label": "Auth", "description": ""},
                    {"label": "Logging", "description": ""},
                ],
                "multiSelect": True,
            }
        ]
        blocks = _build_ask_user_blocks("req-ms", questions)
        actions = _get_actions_block(blocks)
        done_btns = [e for e in actions["elements"] if e["text"]["text"] == "Done"]
        assert len(done_btns) == 1

    def test_multi_select_hint_in_question_text(self):
        questions = [
            {
                "question": "Select items",
                "header": "Items",
                "options": [{"label": "X", "description": ""}],
                "multiSelect": True,
            }
        ]
        blocks = _build_ask_user_blocks("req-ms2", questions)
        sections = [b for b in blocks if b["type"] == "section" and "Select" in b["text"]["text"]]
        assert any("multiple" in b["text"]["text"] for b in sections)

    def test_markdown_preview_rendered_as_code_block(self):
        questions = [
            {
                "question": "Pick a layout",
                "header": "Layout",
                "options": [
                    {
                        "label": "Grid",
                        "description": "CSS grid layout",
                        "markdown": "+---+---+\n| A | B |\n+---+---+",
                    },
                ],
                "multiSelect": False,
            }
        ]
        blocks = _build_ask_user_blocks("req-md", questions)
        ctx = [b for b in blocks if b["type"] == "context"]
        assert len(ctx) >= 1
        text = ctx[0]["elements"][0]["text"]
        assert "```" in text
        assert "| A | B |" in text

    def test_markdown_preview_escapes_backticks(self):
        """Backticks in preview content must not break the wrapping code block."""
        questions = [
            {
                "question": "Pick",
                "header": "H",
                "options": [
                    {
                        "label": "Code",
                        "description": "",
                        "markdown": "```python\nprint('hi')\n```",
                    },
                ],
                "multiSelect": False,
            }
        ]
        blocks = _build_ask_user_blocks("req-esc", questions)
        ctx = [b for b in blocks if b["type"] == "context"]
        assert len(ctx) >= 1
        text = ctx[0]["elements"][0]["text"]
        # Only the wrapper's ``` should remain as actual backticks.
        assert text.count("```") == 2

    def test_descriptions_rendered_as_context(self):
        questions = [
            {
                "question": "Choose",
                "header": "H",
                "options": [
                    {"label": "A", "description": "Alpha option"},
                    {"label": "B", "description": "Beta option"},
                ],
                "multiSelect": False,
            }
        ]
        blocks = _build_ask_user_blocks("req-d", questions)
        ctx = [b for b in blocks if b["type"] == "context"]
        assert len(ctx) >= 1
        text = ctx[0]["elements"][0]["text"]
        assert "Alpha option" in text
        assert "Beta option" in text

    def test_multiple_questions_produce_multiple_action_blocks(self):
        questions = [
            {
                "question": "Q1?",
                "header": "H1",
                "options": [{"label": "A", "description": ""}],
                "multiSelect": False,
            },
            {
                "question": "Q2?",
                "header": "H2",
                "options": [{"label": "B", "description": ""}],
                "multiSelect": False,
            },
        ]
        blocks = _build_ask_user_blocks("req-mq", questions)
        actions = [b for b in blocks if b["type"] == "actions"]
        assert len(actions) == 2

    def test_button_values_encode_request_id(self):
        questions = [
            {
                "question": "Q?",
                "header": "H",
                "options": [{"label": "X", "description": ""}],
                "multiSelect": False,
            }
        ]
        blocks = _build_ask_user_blocks("abc-def-123", questions)
        actions = _get_actions_block(blocks)
        first_btn = actions["elements"][0]
        assert first_btn["value"].startswith("abc-def-123|")

    # ------------------------------------------------------------------
    # Option count is always rendered as buttons.
    #
    # AskUserQuestion's own tool schema caps `options` at 4, so a real tool
    # call can never carry more. This test exists as a defensive check that
    # the renderer degrades gracefully (buttons, not a crash) if it's ever
    # called directly with more options than the schema allows.
    # ------------------------------------------------------------------

    def test_exactly_four_options_uses_buttons(self):
        """Boundary: exactly 4 options use the button layout."""
        questions = [
            {
                "question": "Pick one",
                "header": "H",
                "options": _make_many_options(4),
                "multiSelect": False,
            }
        ]
        blocks = _build_ask_user_blocks("req-4", questions)
        actions = _get_actions_block(blocks)
        # 4 option buttons + Other button
        assert len(actions["elements"]) == 5

    def test_more_than_four_options_still_uses_buttons(self):
        """Defensive: even a malformed call with 5 options still renders buttons."""
        questions = [
            {
                "question": "Pick one",
                "header": "H",
                "options": _make_many_options(5),
                "multiSelect": False,
            }
        ]
        blocks = _build_ask_user_blocks("req-5", questions)
        actions = _get_actions_block(blocks)
        # 5 option buttons + Other button
        assert len(actions["elements"]) == 6


# ------------------------------------------------------------------
# Single-select flow
# ------------------------------------------------------------------


class TestSingleSelect:
    async def test_single_select_returns_answer(self):
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Which DB?",
                "header": "Database",
                "options": [
                    {"label": "PostgreSQL", "description": ""},
                    {"label": "MongoDB", "description": ""},
                ],
                "multiSelect": False,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        await _click(handler, req_id, 0, 0)

        result = await asyncio.wait_for(task, timeout=2.0)
        assert isinstance(result, PermissionResultAllow)
        assert result.updated_input["answers"]["Which DB?"] == "PostgreSQL"

    async def test_empty_questions_returns_allow(self):
        handler, _, _ = _make_handler()
        result = await handler.handle("AskUserQuestion", {"questions": []}, None)
        assert isinstance(result, PermissionResultAllow)

    async def test_two_questions_requires_both_answers(self):
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Q1?",
                "header": "H1",
                "options": [{"label": "A", "description": ""}],
                "multiSelect": False,
            },
            {
                "question": "Q2?",
                "header": "H2",
                "options": [{"label": "B", "description": ""}],
                "multiSelect": False,
            },
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        await _click(handler, req_id, 0, 0)
        assert not task.done()

        await _click(handler, req_id, 1, 0)

        result = await asyncio.wait_for(task, timeout=2.0)
        assert isinstance(result, PermissionResultAllow)
        assert result.updated_input["answers"]["Q1?"] == "A"
        assert result.updated_input["answers"]["Q2?"] == "B"


# ------------------------------------------------------------------
# Other (modal) flow
# ------------------------------------------------------------------


class TestOtherModal:
    async def test_other_with_trigger_id_opens_modal(self):
        """'Other' button with trigger_id calls views_open with correct modal structure."""
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Pick one",
                "header": "Test",
                "options": [{"label": "A", "description": ""}],
                "multiSelect": False,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        await handler.handle_ask_user_action(
            value=f"{req_id}|0|other",
            user_id="U1",
            trigger_id="trigger-abc",
        )

        provider.views_open.assert_awaited_once()
        call_args = provider.views_open.call_args
        trigger_id_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("trigger_id")
        view_arg = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("view")
        assert trigger_id_arg == "trigger-abc"
        assert view_arg["callback_id"] == "ask_user_other"
        assert view_arg["type"] == "modal"
        # private_metadata contains channel_id, request_id, q_idx
        import json

        meta = json.loads(view_arg["private_metadata"])
        assert meta["request_id"] == req_id
        assert meta["q_idx"] == 0
        assert "channel_id" in meta
        # Modal has an input block
        blocks = view_arg["blocks"]
        assert any(b["type"] == "input" for b in blocks)

        # Clean up task
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def test_other_without_trigger_id_logs_warning_no_crash(self):
        """'Other' button without trigger_id logs a warning and returns cleanly."""
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Pick one",
                "header": "Test",
                "options": [{"label": "A", "description": ""}],
                "multiSelect": False,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        # No trigger_id — should not crash and should not call views_open
        await handler.handle_ask_user_action(
            value=f"{req_id}|0|other",
            user_id="U1",
            trigger_id=None,
        )
        provider.views_open.assert_not_awaited()

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def test_view_submission_completes_question(self):
        """handle_ask_user_view_submission extracts answer and completes the request."""
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Pick one",
                "header": "Test",
                "options": [{"label": "A", "description": ""}],
                "multiSelect": False,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        import json

        view = {
            "private_metadata": json.dumps(
                {"channel_id": "C123", "request_id": req_id, "q_idx": 0}
            ),
            "state": {"values": {"other_input": {"other_value": {"value": "My custom answer"}}}},
        }
        await handler.handle_ask_user_view_submission(view=view, user_id="U1")

        result = await asyncio.wait_for(task, timeout=2.0)
        assert isinstance(result, PermissionResultAllow)
        assert result.updated_input["answers"]["Pick one"] == "My custom answer"

    async def test_view_submission_malformed_metadata_no_crash(self):
        """Malformed private_metadata in view submission returns cleanly."""
        handler, _, _ = _make_handler()

        view = {"private_metadata": "not-json", "state": {}}
        await handler.handle_ask_user_view_submission(view=view, user_id="U1")
        # No exception raised

    async def test_view_submission_missing_request_id_no_crash(self):
        """Missing request_id in metadata returns cleanly (no matching event)."""
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Q?",
                "header": "H",
                "options": [{"label": "A", "description": ""}],
                "multiSelect": False,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        import json

        view = {
            "private_metadata": json.dumps(
                {"channel_id": "C123", "request_id": "no-such-id", "q_idx": 0}
            ),
            "state": {"values": {"other_input": {"other_value": {"value": "answer"}}}},
        }
        # Request ID doesn't match any active event — must return without crash
        await handler.handle_ask_user_view_submission(view=view, user_id="U1")
        assert not task.done()

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def test_view_submission_missing_state_keys_no_crash(self):
        """Missing state keys in view submission returns cleanly."""
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Q?",
                "header": "H",
                "options": [{"label": "A", "description": ""}],
                "multiSelect": False,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        import json

        view = {
            "private_metadata": json.dumps(
                {"channel_id": "C123", "request_id": req_id, "q_idx": 0}
            ),
            "state": {"values": {}},  # missing other_input block
        }
        await handler.handle_ask_user_view_submission(view=view, user_id="U1")
        assert not task.done()

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def test_old_has_pending_text_input_removed(self):
        """has_pending_text_input no longer exists on PermissionHandler."""
        handler, _, _ = _make_handler()
        assert not hasattr(handler, "has_pending_text_input")

    async def test_old_receive_text_input_removed(self):
        """receive_text_input no longer exists on PermissionHandler."""
        handler, _, _ = _make_handler()
        assert not hasattr(handler, "receive_text_input")


# ------------------------------------------------------------------
# Multi-select flow
# ------------------------------------------------------------------


class TestMultiSelect:
    async def test_multi_select_toggle_and_done(self):
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Select features",
                "header": "Features",
                "options": [
                    {"label": "Auth", "description": ""},
                    {"label": "Logging", "description": ""},
                    {"label": "Metrics", "description": ""},
                ],
                "multiSelect": True,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        await _click(handler, req_id, 0, 0)  # Auth
        await _click(handler, req_id, 0, 2)  # Metrics
        assert not task.done()

        await _click(handler, req_id, 0, "done")

        result = await asyncio.wait_for(task, timeout=2.0)
        assert isinstance(result, PermissionResultAllow)
        assert result.updated_input["answers"]["Select features"] == "Auth, Metrics"

    async def test_multi_select_toggle_deselect(self):
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Q?",
                "header": "H",
                "options": [
                    {"label": "A", "description": ""},
                    {"label": "B", "description": ""},
                ],
                "multiSelect": True,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        # Select A, deselect A, select B, done
        await _click(handler, req_id, 0, 0)
        await _click(handler, req_id, 0, 0)
        await _click(handler, req_id, 0, 1)
        await _click(handler, req_id, 0, "done")

        result = await asyncio.wait_for(task, timeout=2.0)
        assert isinstance(result, PermissionResultAllow)
        assert result.updated_input["answers"]["Q?"] == "B"


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


class TestEdgeCases:
    async def test_unknown_request_id_ignored(self):
        handler, _, _ = _make_handler()
        await _click(handler, "nonexistent", 0, 0)

    async def test_invalid_value_format_ignored(self):
        handler, _, _ = _make_handler()
        await handler.handle_ask_user_action(
            value="bad-format",
            user_id="U1",
        )

    async def test_view_submission_stray_request_id_is_noop(self):
        """View submission for a request_id with no active event is a no-op."""
        handler, _, _ = _make_handler()
        import json

        view = {
            "private_metadata": json.dumps(
                {"channel_id": "C123", "request_id": "stray-req", "q_idx": 0}
            ),
            "state": {"values": {"other_input": {"other_value": {"value": "answer"}}}},
        }
        await handler.handle_ask_user_view_submission(view=view, user_id="U1")
        # No crash, no state changes

    async def test_ask_user_not_auto_approved(self):
        """AskUserQuestion should not go through auto-approve flow."""
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Q?",
                "header": "H",
                "options": [{"label": "A", "description": ""}],
                "multiSelect": False,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        # Verify it posted question blocks via post_interactive
        posted = False
        for call in provider.post_interactive.call_args_list:
            blocks = call.kwargs.get("blocks")
            if blocks and any(
                b.get("type") == "section"
                and "question" in b.get("text", {}).get("text", "").lower()
                for b in blocks
            ):
                posted = True
                break
        assert posted, "Expected AskUserQuestion blocks"

        # Clean up
        await _click(handler, req_id, 0, 0)
        await asyncio.wait_for(task, timeout=2.0)


# ------------------------------------------------------------------
# comp-6: _check_ask_user_complete — answer summary posting
# ------------------------------------------------------------------


class TestAnswerSummaryPosting:
    """Tests that _check_ask_user_complete posts a summary of all answers."""

    async def test_summary_posted_on_completion(self):
        """Completing all questions posts a summary message."""
        handler, provider, router = _make_handler()
        questions = [
            {
                "question": "Pick one",
                "header": "My Header",
                "options": [{"label": "Alpha", "description": ""}],
                "multiSelect": False,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        # Record the post count before answering (the question message itself)
        posts_before = provider.post.call_count

        await _click(handler, req_id, 0, 0)
        await asyncio.wait_for(task, timeout=2.0)

        # At least one additional post should have been made (the summary)
        assert provider.post.call_count > posts_before

    async def test_summary_contains_header_and_answer(self):
        """The posted summary includes the question header and the chosen answer."""
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "What framework?",
                "header": "Framework",
                "options": [{"label": "FastAPI", "description": ""}],
                "multiSelect": False,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        await _click(handler, req_id, 0, 0)
        await asyncio.wait_for(task, timeout=2.0)

        # Collect all post() call texts
        post_texts = [
            call.args[0] if call.args else call.kwargs.get("text", "")
            for call in provider.post.call_args_list
        ]
        summary_posts = [t for t in post_texts if "Framework" in t or "FastAPI" in t]
        assert summary_posts, f"No summary post found. Posts: {post_texts}"

    async def test_summary_contains_all_question_answers(self):
        """Summary includes an entry for every answered question."""
        handler, provider, _ = _make_handler()
        questions = [
            {
                "question": "Q1?",
                "header": "H1",
                "options": [{"label": "Ans1", "description": ""}],
                "multiSelect": False,
            },
            {
                "question": "Q2?",
                "header": "H2",
                "options": [{"label": "Ans2", "description": ""}],
                "multiSelect": False,
            },
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        await _click(handler, req_id, 0, 0)
        await _click(handler, req_id, 1, 0)
        await asyncio.wait_for(task, timeout=2.0)

        post_texts = [
            call.args[0] if call.args else call.kwargs.get("text", "")
            for call in provider.post.call_args_list
        ]
        combined = "\n".join(post_texts)
        assert "H1" in combined
        assert "H2" in combined
        assert "Ans1" in combined
        assert "Ans2" in combined

    async def test_summary_posted_before_event_set(self):
        """Summary is posted before the event is set (task completes after summary)."""
        handler, provider, _ = _make_handler()
        post_order: list[str] = []

        async def track_post(*args, **kwargs):
            post_order.append("post")
            from summon_claude.slack.client import MessageRef

            return MessageRef(channel_id="C123", ts="1.0")

        provider.post.side_effect = track_post

        questions = [
            {
                "question": "Pick one",
                "header": "H",
                "options": [{"label": "A", "description": ""}],
                "multiSelect": False,
            }
        ]
        task, req_id = await _start_ask(handler, provider, questions)

        # Reset tracker — only care about posts after answering
        post_order.clear()
        await _click(handler, req_id, 0, 0)
        result = await asyncio.wait_for(task, timeout=2.0)

        assert isinstance(result, PermissionResultAllow)
        # At least one post call made after the click (the summary)
        assert "post" in post_order
