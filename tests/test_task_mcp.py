"""Tests for TaskCreate/TaskUpdate/TaskList MCP tools."""

from __future__ import annotations

import pytest
from conftest import make_scheduler

from summon_claude.sessions.registry import SessionRegistry
from summon_claude.summon_cli_mcp import create_summon_cli_mcp_tools


@pytest.fixture
async def task_registry(registry: SessionRegistry) -> SessionRegistry:
    await registry.register("task-sid", 1234, "/tmp", authenticated_user_id="U_TASK")
    await registry.update_status("task-sid", "active", authenticated_user_id="U_TASK")
    return registry


@pytest.fixture
def tools(task_registry):
    return {
        t.name: t
        for t in create_summon_cli_mcp_tools(
            registry=task_registry,
            session_id="task-sid",
            authenticated_user_id="U_TASK",
            channel_id="C_TASK",
            cwd="/tmp",
            scheduler=make_scheduler(),
        )
    }


class TestTaskCreate:
    async def test_returns_id(self, tools):
        result = await tools["TaskCreate"].handler({"content": "Build auth", "priority": "high"})
        assert not result.get("is_error")
        assert "Created task" in result["content"][0]["text"]

    async def test_invalid_priority(self, tools):
        result = await tools["TaskCreate"].handler({"content": "test", "priority": "urgent"})
        assert result.get("is_error") is True

    async def test_triggers_canvas_callback(self, task_registry):
        callback_called = []

        async def _cb():
            callback_called.append(True)

        tool_list = create_summon_cli_mcp_tools(
            registry=task_registry,
            session_id="task-sid",
            authenticated_user_id="U_TASK",
            channel_id="C_TASK",
            cwd="/tmp",
            scheduler=make_scheduler(),
            on_task_change=_cb,
        )
        create_tool = next(t for t in tool_list if t.name == "TaskCreate")
        await create_tool.handler({"content": "test", "priority": "medium"})
        assert len(callback_called) == 1

    async def test_empty_content_rejected(self, tools):
        result = await tools["TaskCreate"].handler({"content": "", "priority": "medium"})
        assert result.get("is_error") is True
        assert "empty" in result["content"][0]["text"].lower()

    async def test_whitespace_content_rejected(self, tools):
        result = await tools["TaskCreate"].handler({"content": "   ", "priority": "medium"})
        assert result.get("is_error") is True
        assert "empty" in result["content"][0]["text"].lower()


class TestTaskUpdate:
    async def test_updates_status(self, tools, task_registry):
        # Create a task first
        result = await tools["TaskCreate"].handler({"content": "test task", "priority": "medium"})
        task_id = result["content"][0]["text"].split()[-1].rstrip(".")
        result = await tools["TaskUpdate"].handler({"id": task_id, "status": "in_progress"})
        assert not result.get("is_error")

    async def test_not_found(self, tools):
        result = await tools["TaskUpdate"].handler({"id": "nonexistent", "status": "completed"})
        assert result.get("is_error") is True

    async def test_empty_content_rejected(self, tools, task_registry):
        result = await tools["TaskCreate"].handler({"content": "original", "priority": "medium"})
        task_id = result["content"][0]["text"].split()[-1].rstrip(".")
        result = await tools["TaskUpdate"].handler({"id": task_id, "content": ""})
        assert result.get("is_error") is True
        assert "empty" in result["content"][0]["text"].lower()

    async def test_triggers_canvas_callback(self, task_registry):
        callback_called = []

        async def _cb():
            callback_called.append(True)

        tool_list = create_summon_cli_mcp_tools(
            registry=task_registry,
            session_id="task-sid",
            authenticated_user_id="U_TASK",
            channel_id="C_TASK",
            cwd="/tmp",
            scheduler=make_scheduler(),
            on_task_change=_cb,
        )
        create_tool = next(t for t in tool_list if t.name == "TaskCreate")
        update_tool = next(t for t in tool_list if t.name == "TaskUpdate")
        r = await create_tool.handler({"content": "test", "priority": "medium"})
        task_id = r["content"][0]["text"].split()[-1].rstrip(".")
        callback_called.clear()
        await update_tool.handler({"id": task_id, "status": "completed"})
        assert len(callback_called) == 1


class TestTaskList:
    async def test_all_tasks(self, tools, task_registry):
        await tools["TaskCreate"].handler({"content": "task1", "priority": "high"})
        await tools["TaskCreate"].handler({"content": "task2", "priority": "low"})
        result = await tools["TaskList"].handler({})
        text = result["content"][0]["text"]
        assert "task1" in text
        assert "task2" in text

    async def test_filtered(self, tools, task_registry):
        await tools["TaskCreate"].handler({"content": "pending-task", "priority": "medium"})
        result = await tools["TaskList"].handler({"status": "completed"})
        text = result["content"][0]["text"]
        assert "No tasks" in text

    async def test_cap_excludes_completed_tasks(self, tools, task_registry):
        """Completing tasks frees cap space for new ones."""
        from summon_claude.summon_cli_mcp import _MAX_TASKS_PER_SESSION

        # Create tasks up to the cap
        task_ids = []
        for i in range(_MAX_TASKS_PER_SESSION):
            r = await tools["TaskCreate"].handler({"content": f"t-{i}", "priority": "low"})
            assert not r.get("is_error"), f"Failed to create task {i}: {r}"
            task_ids.append(r["content"][0]["text"].split()[-1].rstrip("."))

        # Next create should fail
        r = await tools["TaskCreate"].handler({"content": "overflow", "priority": "low"})
        assert r.get("is_error") is True
        assert "Maximum" in r["content"][0]["text"]

        # Complete one task
        await tools["TaskUpdate"].handler({"id": task_ids[0], "status": "completed"})

        # Now creation should succeed
        r = await tools["TaskCreate"].handler({"content": "after-complete", "priority": "low"})
        assert not r.get("is_error"), f"Should succeed after completing a task: {r}"

    async def test_cross_session_pm_only(self, task_registry):
        non_pm_tools = {
            t.name: t
            for t in create_summon_cli_mcp_tools(
                registry=task_registry,
                session_id="task-sid",
                authenticated_user_id="U_TASK",
                channel_id="C_TASK",
                cwd="/tmp",
                scheduler=make_scheduler(),
                is_pm=False,
            )
        }
        result = await non_pm_tools["TaskList"].handler({"session_ids": "other-sid"})
        assert result.get("is_error") is True
        assert "PM-only" in result["content"][0]["text"]

    async def test_cross_session_user_scope_isolation(self, task_registry):
        """PM calling TaskList with session_ids from another user gets no tasks."""
        # Register a session owned by a different user
        await task_registry.register(
            "other-user-sid", 5678, "/tmp", authenticated_user_id="U_OTHER"
        )
        await task_registry.create_task("other-user-sid", "other-task-1", "Secret task")

        pm_tools = {
            t.name: t
            for t in create_summon_cli_mcp_tools(
                registry=task_registry,
                session_id="task-sid",
                authenticated_user_id="U_TASK",
                channel_id="C_TASK",
                cwd="/tmp",
                scheduler=make_scheduler(),
                is_pm=True,
            )
        }
        result = await pm_tools["TaskList"].handler({"session_ids": "other-user-sid"})
        # Should return no tasks — other user's sessions are filtered out
        assert "No tasks found" in result["content"][0]["text"]

    async def test_cross_session_ids_cap(self, task_registry):
        from summon_claude.summon_cli_mcp import _MAX_CROSS_SESSION_IDS

        pm_tools = {
            t.name: t
            for t in create_summon_cli_mcp_tools(
                registry=task_registry,
                session_id="task-sid",
                authenticated_user_id="U_TASK",
                channel_id="C_TASK",
                cwd="/tmp",
                scheduler=make_scheduler(),
                is_pm=True,
            )
        }
        ids = ",".join(f"sid-{i}" for i in range(_MAX_CROSS_SESSION_IDS + 1))
        result = await pm_tools["TaskList"].handler({"session_ids": ids})
        assert result.get("is_error") is True
        assert "Too many" in result["content"][0]["text"]
