"""Round lifecycle controller — DISCUSS → SUMMARIZE → PROPAGATE."""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Callable, Awaitable

import structlog

from orchestrator.config import RoundsConfig
from orchestrator.llm.summarizer import Summarizer
from orchestrator.matrix.client import MatrixClient
from orchestrator.matrix.transcript import TranscriptBuffer
from orchestrator.models.summary import SwarmSummary
from orchestrator.models.topology import SwarmNode
from orchestrator.rag.store import RAGStore

logger = structlog.get_logger(__name__)


class Phase(str, Enum):
    DISCUSS = "DISCUSS"
    SUMMARIZE = "SUMMARIZE"
    PROPAGATE = "PROPAGATE"


class RoundController:
    """Async state machine driving the DISCUSS → SUMMARIZE → PROPAGATE cycle."""

    def __init__(
        self,
        config: RoundsConfig,
        matrix_client: MatrixClient,
        transcript: TranscriptBuffer,
        summarizer: Summarizer,
        rag_store: RAGStore,
        room_id: str,
        source_node_id: str,
        adjacent_nodes: list[SwarmNode],
        on_propagate: Callable[[SwarmSummary, list[SwarmNode]], Awaitable[None]],
    ) -> None:
        self._config = config
        self._matrix = matrix_client
        self._transcript = transcript
        self._summarizer = summarizer
        self._rag = rag_store
        self._room_id = room_id
        self._source_node_id = source_node_id
        self._adjacent_nodes = adjacent_nodes
        self._on_propagate = on_propagate

        self._phase: Phase = Phase.DISCUSS
        self._round_number: int = 1
        self._inbound_summaries: list[SwarmSummary] = []
        self._current_summary: SwarmSummary | None = None
        self._running = False
        self._trigger_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def round_number(self) -> int:
        return self._round_number

    # ------------------------------------------------------------------
    # External API
    # ------------------------------------------------------------------

    def receive_inbound_summary(self, summary: SwarmSummary) -> None:
        """Accept an inbound SwarmSummary during the DISCUSS phase."""
        self._inbound_summaries.append(summary)
        logger.info(
            "controller.inbound_summary",
            from_node=summary.source_node_id,
            round=self._round_number,
        )

    def trigger_summarize(self) -> None:
        """Manually trigger the SUMMARIZE phase (e.g., via !summarize command)."""
        logger.info("controller.manual_trigger", round=self._round_number)
        self._trigger_event.set()

    def receive_message(self, sender: str, body: str) -> None:
        """Called when a new message arrives — may trigger message_count mode."""
        if self._config.mode == "message_count":
            count = len(self._transcript)
            if count >= self._config.message_threshold:
                self.trigger_summarize()

        # Check for manual !summarize command
        if body.strip().lower() == "!summarize":
            self.trigger_summarize()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the round loop forever."""
        self._running = True
        logger.info("controller.start", mode=self._config.mode)

        while self._running:
            await self._discuss_phase()
            if not self._running:
                break
            await self._summarize_phase()
            if not self._running:
                break
            await self._propagate_phase()

    def stop(self) -> None:
        """Stop the run loop."""
        self._running = False
        self._trigger_event.set()

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------

    async def _discuss_phase(self) -> None:
        """Wait for the trigger condition."""
        self._phase = Phase.DISCUSS
        self._trigger_event.clear()
        logger.info(
            "controller.phase",
            phase=Phase.DISCUSS,
            round=self._round_number,
        )

        if self._config.mode == "timer":
            try:
                await asyncio.wait_for(
                    self._trigger_event.wait(),
                    timeout=float(self._config.interval_seconds),
                )
            except asyncio.TimeoutError:
                pass  # Normal timer expiry
        else:
            # message_count or manual — wait for the event
            await self._trigger_event.wait()

    async def _summarize_phase(self) -> None:
        """Generate the SwarmSummary and store it."""
        self._phase = Phase.SUMMARIZE
        logger.info(
            "controller.phase",
            phase=Phase.SUMMARIZE,
            round=self._round_number,
        )

        transcript_text = self._transcript.to_prompt_text()
        message_count = len(self._transcript)
        participant_count = self._count_participants()

        rag_context = ""
        try:
            rag_context = await self._rag.retrieve_context(
                query=transcript_text[:500]
            )
        except Exception as exc:
            logger.warning("controller.rag_error", error=str(exc))

        try:
            summary = await self._summarizer.summarize(
                transcript=transcript_text,
                inbound_summaries=self._inbound_summaries,
                rag_context=rag_context,
                round_number=self._round_number,
                source_node_id=self._source_node_id,
                participant_count=participant_count,
                message_count=message_count,
            )
        except Exception as exc:
            logger.error("controller.summarize_error", error=str(exc))
            return

        # Store in Qdrant
        try:
            await self._rag.store_summary(summary)
        except Exception as exc:
            logger.warning("controller.rag_store_error", error=str(exc))

        # Post summary to the local Matrix room
        try:
            await self._matrix.send_swarm_signal(
                room_id=self._room_id,
                from_node=f"{self._source_node_id} (local summary)",
                round_number=self._round_number,
                key_positions=summary.key_positions,
                emerging_consensus=summary.emerging_consensus,
                dissenting_views=summary.dissenting_views,
                open_questions=summary.open_questions,
            )
        except Exception as exc:
            logger.warning("controller.matrix_send_error", error=str(exc))

        self._current_summary = summary
        logger.info(
            "controller.summarized",
            round=self._round_number,
            topic=summary.topic,
        )

    async def _propagate_phase(self) -> None:
        """Send the summary to adjacent nodes, clear buffer, advance round."""
        self._phase = Phase.PROPAGATE
        logger.info(
            "controller.phase",
            phase=Phase.PROPAGATE,
            round=self._round_number,
        )

        summary = getattr(self, "_current_summary", None)
        if summary is not None:
            try:
                await self._on_propagate(summary, self._adjacent_nodes)
            except Exception as exc:
                logger.error("controller.propagate_error", error=str(exc))

        # Clean up for next round
        self._transcript.clear()
        self._inbound_summaries.clear()
        self._current_summary = None
        self._round_number += 1
        logger.info("controller.round_complete", next_round=self._round_number)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _count_participants(self) -> int:
        """Count unique human senders in the transcript buffer."""
        return len(self._transcript.get_human_senders())
