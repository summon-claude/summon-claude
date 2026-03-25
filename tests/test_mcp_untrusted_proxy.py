"""Tests for summon_claude.mcp_untrusted_proxy."""

from summon_claude.mcp_untrusted_proxy import _mark_tool_result
from summon_claude.security import UNTRUSTED_BEGIN


class TestMarkToolResult:
    def test_marks_text_content(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "email body"}]},
        }
        result = _mark_tool_result(msg, "Gmail")
        text = result["result"]["content"][0]["text"]
        assert UNTRUSTED_BEGIN in text
        assert "email body" in text
        assert "[Source: Gmail]" in text

    def test_passes_through_non_content_responses(self):
        msg = {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}
        assert _mark_tool_result(msg, "Gmail") == msg

    def test_passes_through_error_responses(self):
        msg = {"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "fail"}}
        assert _mark_tool_result(msg, "Gmail") == msg

    def test_passes_through_notifications(self):
        msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        assert _mark_tool_result(msg, "Gmail") == msg

    def test_marks_multiple_text_items(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {"type": "text", "text": "item 1"},
                    {"type": "image", "data": "base64..."},
                    {"type": "text", "text": "item 2"},
                ]
            },
        }
        result = _mark_tool_result(msg, "Drive")
        assert UNTRUSTED_BEGIN in result["result"]["content"][0]["text"]
        assert result["result"]["content"][1] == {"type": "image", "data": "base64..."}
        assert UNTRUSTED_BEGIN in result["result"]["content"][2]["text"]

    def test_preserves_message_id(self):
        msg = {"jsonrpc": "2.0", "id": 42, "result": {"content": [{"type": "text", "text": "x"}]}}
        assert _mark_tool_result(msg, "Test")["id"] == 42

    def test_handles_none_text_value(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": None}]},
        }
        result = _mark_tool_result(msg, "Test")
        assert result["result"]["content"][0]["text"] is not None
