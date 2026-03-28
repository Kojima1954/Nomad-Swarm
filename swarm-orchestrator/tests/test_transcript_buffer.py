"""Tests for the TranscriptBuffer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.matrix.transcript import TranscriptBuffer


class TestTranscriptBuffer:
    def test_append_and_len(self):
        buf = TranscriptBuffer(max_messages=10, max_minutes=None, max_tokens=10000)
        buf.append("Alice", "Hello world")
        buf.append("Bob", "Hi there")
        assert len(buf) == 2

    def test_clear(self):
        buf = TranscriptBuffer(max_messages=10, max_minutes=None, max_tokens=10000)
        buf.append("Alice", "Hello")
        buf.clear()
        assert len(buf) == 0

    def test_max_messages_truncation(self):
        buf = TranscriptBuffer(max_messages=5, max_minutes=None, max_tokens=10000)
        for i in range(10):
            buf.append("User", f"message {i}")
        assert len(buf) == 5

    def test_oldest_removed_on_overflow(self):
        buf = TranscriptBuffer(max_messages=3, max_minutes=None, max_tokens=10000)
        buf.append("Alice", "first")
        buf.append("Alice", "second")
        buf.append("Alice", "third")
        buf.append("Alice", "fourth")
        text = buf.to_prompt_text()
        assert "first" not in text
        assert "fourth" in text

    def test_time_based_pruning(self):
        buf = TranscriptBuffer(max_messages=100, max_minutes=30, max_tokens=10000)
        old_ts = datetime.now(timezone.utc) - timedelta(minutes=60)
        recent_ts = datetime.now(timezone.utc)
        buf.append("Alice", "old message", timestamp=old_ts)
        buf.append("Bob", "new message", timestamp=recent_ts)
        # Add another fresh message to trigger pruning
        buf.append("Carol", "another new", timestamp=recent_ts)
        text = buf.to_prompt_text()
        assert "old message" not in text
        assert "new message" in text

    def test_token_estimate(self):
        buf = TranscriptBuffer(max_messages=100, max_minutes=None, max_tokens=10000)
        # "hello world" = 2 words => estimate = int(2 * 1.3) = 2
        buf.append("Alice", "hello world")
        estimate = buf.token_estimate()
        assert estimate == int(2 * 1.3)

    def test_token_budget_truncation(self):
        # Very small token budget
        buf = TranscriptBuffer(max_messages=1000, max_minutes=None, max_tokens=10)
        # Each message: "word1 word2 word3 word4 word5" = 5 words => 6 tokens
        for i in range(5):
            buf.append("User", "word1 word2 word3 word4 word5")
        # The buffer should have been pruned to stay within budget
        assert buf.token_estimate() <= 10

    def test_to_prompt_text_labels_human(self):
        buf = TranscriptBuffer(max_messages=10, max_minutes=None, max_tokens=10000)
        buf.append("Alice", "A normal message", is_swarm_signal=False)
        text = buf.to_prompt_text()
        assert "[HUMAN]" in text
        assert "Alice" in text

    def test_to_prompt_text_labels_swarm_signal(self):
        buf = TranscriptBuffer(max_messages=10, max_minutes=None, max_tokens=10000)
        buf.append("SwarmBot", "🐝 SWARM SIGNAL ...", is_swarm_signal=True)
        text = buf.to_prompt_text()
        assert "[SWARM SIGNAL]" in text
