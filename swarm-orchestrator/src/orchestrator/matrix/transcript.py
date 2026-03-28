"""Rolling transcript buffer with token counting."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque


@dataclass
class TranscriptEntry:
    """A single message in the transcript."""

    timestamp: datetime
    sender_display_name: str
    body_text: str
    is_swarm_signal: bool = False


class TranscriptBuffer:
    """Rolling buffer of the last N messages (or T minutes).

    Parameters
    ----------
    max_messages:
        Maximum number of messages to keep (default 200).
    max_minutes:
        Maximum age in minutes (messages older than this are dropped on
        the next *append* call).  ``None`` disables time-based pruning.
    max_tokens:
        Approximate token budget.  The buffer is truncated from the oldest
        end when the estimate exceeds this value.
    """

    def __init__(
        self,
        max_messages: int = 200,
        max_minutes: int | None = 30,
        max_tokens: int = 4000,
    ) -> None:
        self._max_messages = max_messages
        self._max_minutes = max_minutes
        self._max_tokens = max_tokens
        self._entries: Deque[TranscriptEntry] = deque()

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def append(
        self,
        sender: str,
        body: str,
        is_swarm_signal: bool = False,
        timestamp: datetime | None = None,
    ) -> None:
        """Add a new message to the buffer."""
        ts = timestamp or datetime.now(timezone.utc)
        self._entries.append(
            TranscriptEntry(
                timestamp=ts,
                sender_display_name=sender,
                body_text=body,
                is_swarm_signal=is_swarm_signal,
            )
        )
        self._prune()

    def clear(self) -> None:
        """Clear all entries from the buffer."""
        self._entries.clear()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def to_prompt_text(self) -> str:
        """Format the transcript for LLM consumption."""
        lines: list[str] = []
        for entry in self._entries:
            ts = entry.timestamp.strftime("%H:%M")
            if entry.is_swarm_signal:
                tag = "[SWARM SIGNAL]"
            else:
                tag = "[HUMAN]"
            lines.append(f"[{ts}] {tag} {entry.sender_display_name}: {entry.body_text}")
        return "\n".join(lines)

    def token_estimate(self) -> int:
        """Return an approximate token count using word-count × 1.3."""
        total_words = sum(
            len(e.body_text.split()) for e in self._entries
        )
        return int(total_words * 1.3)

    def get_human_senders(self) -> set[str]:
        """Return the set of unique human (non-swarm-signal) sender names."""
        return {
            e.sender_display_name
            for e in self._entries
            if not e.is_swarm_signal
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _prune(self) -> None:
        """Drop entries exceeding size / age / token limits."""
        # 1. Hard message cap
        while len(self._entries) > self._max_messages:
            self._entries.popleft()

        # 2. Time-based pruning
        if self._max_minutes is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - self._max_minutes * 60
            while self._entries and self._entries[0].timestamp.timestamp() < cutoff:
                self._entries.popleft()

        # 3. Token budget (drop oldest until within budget)
        while self._entries and self.token_estimate() > self._max_tokens:
            self._entries.popleft()
