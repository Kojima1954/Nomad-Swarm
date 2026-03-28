"""Tests for the RoundController state machine."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.config import RoundsConfig
from orchestrator.models.summary import SwarmSummary
from orchestrator.models.topology import SwarmNode
from orchestrator.rounds.controller import Phase, RoundController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_summary(round_number: int = 1, node_id: str = "node-alpha") -> SwarmSummary:
    return SwarmSummary(
        **{
            "swarm:roundNumber": round_number,
            "swarm:topic": "Test topic",
            "swarm:sourceNodeId": node_id,
            "swarm:keyPositions": ["Position A"],
            "swarm:emergingConsensus": "Some consensus",
        }
    )


def _make_controller(
    mode: str = "manual",
    interval_seconds: int = 1,
    message_threshold: int = 3,
    on_propagate: AsyncMock | None = None,
) -> RoundController:
    config = RoundsConfig(
        mode=mode,
        interval_seconds=interval_seconds,
        message_threshold=message_threshold,
    )
    mock_matrix = MagicMock()
    mock_matrix.send_swarm_signal = AsyncMock()

    mock_transcript = MagicMock()
    mock_transcript.to_prompt_text.return_value = "Alice: Hello\nBob: World"
    mock_transcript.__len__ = MagicMock(return_value=2)
    mock_transcript.clear = MagicMock()
    mock_transcript._entries = []

    mock_summarizer = MagicMock()
    mock_summarizer.summarize = AsyncMock(return_value=_make_summary())

    mock_rag = MagicMock()
    mock_rag.retrieve_context = AsyncMock(return_value="")
    mock_rag.store_summary = AsyncMock()

    return RoundController(
        config=config,
        matrix_client=mock_matrix,
        transcript=mock_transcript,
        summarizer=mock_summarizer,
        rag_store=mock_rag,
        room_id="!room:localhost",
        source_node_id="node-alpha",
        adjacent_nodes=[],
        on_propagate=on_propagate or AsyncMock(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPhaseTransitions:
    @pytest.mark.asyncio
    async def test_initial_phase_is_discuss(self):
        controller = _make_controller()
        assert controller.phase == Phase.DISCUSS

    @pytest.mark.asyncio
    async def test_manual_trigger_advances_to_summarize(self):
        controller = _make_controller(mode="manual")

        async def run_one_cycle():
            # Run controller but cancel after the first propagate
            task = asyncio.create_task(controller.run())
            await asyncio.sleep(0)  # Let the discuss phase start
            controller.trigger_summarize()
            await asyncio.sleep(0.1)  # Let summarize + propagate complete
            controller.stop()
            await task

        await run_one_cycle()
        # After one full cycle the round number should have advanced
        assert controller.round_number == 2

    @pytest.mark.asyncio
    async def test_round_number_increments(self):
        controller = _make_controller(mode="manual")

        task = asyncio.create_task(controller.run())
        await asyncio.sleep(0)

        controller.trigger_summarize()
        await asyncio.sleep(0.1)
        controller.trigger_summarize()
        await asyncio.sleep(0.1)
        controller.stop()
        await task

        assert controller.round_number >= 2

    @pytest.mark.asyncio
    async def test_timer_mode_triggers_on_timeout(self):
        controller = _make_controller(mode="timer", interval_seconds=1)

        task = asyncio.create_task(controller.run())
        # Wait for the timer to expire (1 second + buffer)
        await asyncio.sleep(1.3)
        controller.stop()
        await task

        # Should have completed at least one full cycle
        assert controller.round_number >= 2

    @pytest.mark.asyncio
    async def test_message_count_triggers(self):
        controller = _make_controller(mode="message_count", message_threshold=3)

        task = asyncio.create_task(controller.run())
        await asyncio.sleep(0)

        # Simulate message count threshold reached
        controller._transcript.__len__ = MagicMock(return_value=5)
        controller.receive_message("Alice", "hello")
        await asyncio.sleep(0.1)
        controller.stop()
        await task

        assert controller.round_number >= 2

    @pytest.mark.asyncio
    async def test_summarize_command_triggers(self):
        controller = _make_controller(mode="manual")

        task = asyncio.create_task(controller.run())
        await asyncio.sleep(0)

        controller.receive_message("Alice", "!summarize")
        await asyncio.sleep(0.1)
        controller.stop()
        await task

        assert controller.round_number >= 2

    @pytest.mark.asyncio
    async def test_propagate_calls_on_propagate(self):
        on_propagate = AsyncMock()
        controller = _make_controller(mode="manual", on_propagate=on_propagate)

        task = asyncio.create_task(controller.run())
        await asyncio.sleep(0)

        controller.trigger_summarize()
        await asyncio.sleep(0.1)
        controller.stop()
        await task

        on_propagate.assert_called_once()

    def test_receive_inbound_summary(self):
        controller = _make_controller()
        summary = _make_summary(round_number=2, node_id="node-beta")
        controller.receive_inbound_summary(summary)
        assert summary in controller._inbound_summaries
