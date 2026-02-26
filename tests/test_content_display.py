"""Tests for summon_claude.content_display."""

from __future__ import annotations

from summon_claude.content_display import ContentDisplay, _split_text


def make_display(max_inline: int = 2500) -> ContentDisplay:
    return ContentDisplay(max_inline_chars=max_inline)


class TestFormatDiff:
    def test_no_change_returns_no_changes_message(self):
        display = make_display()
        blocks = display.format_diff("same", "same", "file.py")
        assert len(blocks) == 1
        assert "No changes" in blocks[0]["text"]["text"]

    def test_change_returns_diff_block(self):
        display = make_display()
        blocks = display.format_diff("old line\n", "new line\n", "file.py")
        assert len(blocks) >= 1
        # First block should have the filename
        assert "file.py" in blocks[0]["text"]["text"]

    def test_diff_contains_code_fence(self):
        display = make_display()
        blocks = display.format_diff("a\n", "b\n", "test.txt")
        text = blocks[0]["text"]["text"]
        assert "```" in text

    def test_large_diff_splits_into_multiple_blocks(self):
        display = make_display()
        old = "\n".join(f"line {i}" for i in range(500))
        new = "\n".join(f"changed {i}" for i in range(500))
        blocks = display.format_diff(old, new, "big.py")
        assert len(blocks) >= 1
        for block in blocks:
            assert len(block["text"]["text"]) <= 3000

    def test_first_block_has_filename_header(self):
        display = make_display()
        blocks = display.format_diff("a", "b", "myfile.rs")
        assert "myfile.rs" in blocks[0]["text"]["text"]


class TestSplitText:
    def test_short_text_not_split(self):
        chunks = _split_text("hello", 3000)
        assert chunks == ["hello"]

    def test_long_text_split_at_newline(self):
        text = "line1\n" * 1000  # ~6000 chars
        chunks = _split_text(text, 3000)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 3000

    def test_no_newline_split_at_limit(self):
        text = "x" * 6000
        chunks = _split_text(text, 3000)
        assert len(chunks) == 2
        assert len(chunks[0]) == 3000
        assert len(chunks[1]) == 3000

    def test_exactly_at_limit_not_split(self):
        text = "x" * 3000
        chunks = _split_text(text, 3000)
        assert len(chunks) == 1

    def test_all_chunks_within_limit(self):
        import random

        text = "".join(random.choice("abcde\n") for _ in range(10000))
        chunks = _split_text(text, 3000)
        for chunk in chunks:
            assert len(chunk) <= 3000

    def test_code_block_split_closes_and_reopens(self):
        """When splitting inside a ``` code block, close it and reopen in next chunk."""
        text = "before\n```\n" + "x\n" * 500 + "```\nafter"
        chunks = _split_text(text, 200)
        # The first chunk that opens ``` should also close it
        for chunk in chunks[:-1]:
            fence_count = chunk.count("```")
            assert fence_count % 2 == 0, (
                f"Chunk has unclosed code fence ({fence_count} fences): {chunk[:80]}..."
            )

    def test_code_block_not_broken_when_no_split_needed(self):
        """Short text with code blocks should not be modified."""
        text = "hello\n```\ncode\n```\nbye"
        chunks = _split_text(text, 3000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_even_fence_count_not_modified(self):
        """Chunks with even fence counts (closed blocks) should not be touched."""
        text = "```a```\n" * 50 + "\n" + "```b```\n" * 50
        chunks = _split_text(text, 200)
        for chunk in chunks:
            fence_count = chunk.count("```")
            assert fence_count % 2 == 0
