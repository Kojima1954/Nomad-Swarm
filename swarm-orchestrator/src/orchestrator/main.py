"""Entrypoint — wires all components together and runs the orchestrator."""

from __future__ import annotations

import asyncio
import signal

import httpx
import structlog
import structlog.stdlib

from orchestrator.config import OrchestratorConfig
from orchestrator.federation.crypto import load_or_create_keypair
from orchestrator.federation.publisher import Publisher
from orchestrator.federation.subscriber import Subscriber
from orchestrator.llm.summarizer import Summarizer
from orchestrator.matrix.client import MatrixClient
from orchestrator.matrix.transcript import TranscriptBuffer
from orchestrator.models.summary import SwarmSummary
from orchestrator.models.topology import SwarmNode
from orchestrator.rag.store import RAGStore
from orchestrator.rounds.controller import RoundController
from orchestrator.topology.manager import TopologyManager

# Configure structured JSON logging
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger(__name__)


async def main() -> None:
    """Initialise and run the swarm orchestrator."""
    config = OrchestratorConfig.load()

    logger.info(
        "orchestrator.start",
        node_id=config.node.id,
        display_name=config.node.display_name,
    )

    # ------------------------------------------------------------------
    # Load / create encryption keypair
    # ------------------------------------------------------------------
    private_key, public_key = load_or_create_keypair(
        config.crypto.private_key_path,
        config.crypto.public_key_path,
    )
    logger.info("crypto.keypair_loaded", public_key_path=config.crypto.public_key_path)

    # ------------------------------------------------------------------
    # Load topology
    # ------------------------------------------------------------------
    topo_manager = TopologyManager(
        topology_file=config.topology.topology_file,
        self_node_id=config.node.id,
    )
    try:
        topology = topo_manager.load()
        adjacent_nodes: list[SwarmNode] = topology.adjacent_nodes
    except FileNotFoundError:
        logger.warning(
            "topology.file_missing",
            path=config.topology.topology_file,
        )
        adjacent_nodes = []

    # ------------------------------------------------------------------
    # HTTP client (shared)
    # ------------------------------------------------------------------
    http_client = httpx.AsyncClient()

    # ------------------------------------------------------------------
    # Core components
    # ------------------------------------------------------------------
    transcript = TranscriptBuffer(
        max_messages=200,
        max_minutes=30,
        max_tokens=4000,
    )

    rag_store = RAGStore(
        qdrant_config=config.qdrant,
        ollama_config=config.ollama,
        http_client=http_client,
    )

    summarizer = Summarizer(
        config=config.ollama,
        http_client=http_client,
    )

    publisher = Publisher(
        config=config.gotosocial,
        private_key=private_key,
        http_client=http_client,
    )

    # ------------------------------------------------------------------
    # Matrix client
    # ------------------------------------------------------------------

    async def _on_matrix_message(
        timestamp: str, sender: str, body: str, is_signal: bool
    ) -> None:
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc)
        transcript.append(sender, body, is_swarm_signal=is_signal, timestamp=ts)
        round_controller.receive_message(sender, body)

    matrix_client = MatrixClient(
        config=config.matrix,
        store_path="/data/nio-store",
        message_callback=_on_matrix_message,
    )

    # ------------------------------------------------------------------
    # Round controller
    # ------------------------------------------------------------------

    async def _on_propagate(
        summary: SwarmSummary, nodes: list[SwarmNode]
    ) -> None:
        await publisher.publish(summary, nodes)

    round_controller = RoundController(
        config=config.rounds,
        matrix_client=matrix_client,
        transcript=transcript,
        summarizer=summarizer,
        rag_store=rag_store,
        room_id=config.matrix.room_id,
        source_node_id=config.node.id,
        adjacent_nodes=adjacent_nodes,
        on_propagate=_on_propagate,
    )

    # ------------------------------------------------------------------
    # Federation subscriber
    # ------------------------------------------------------------------

    async def _on_inbound_summary(summary: SwarmSummary) -> None:
        round_controller.receive_inbound_summary(summary)
        try:
            await matrix_client.send_swarm_signal(
                room_id=config.matrix.room_id,
                from_node=summary.source_node_id,
                round_number=summary.round_number,
                key_positions=summary.key_positions,
                emerging_consensus=summary.emerging_consensus,
                dissenting_views=summary.dissenting_views,
                open_questions=summary.open_questions,
            )
        except Exception as exc:
            logger.warning("main.swarm_signal_send_error", error=str(exc))

    subscriber = Subscriber(
        config=config.gotosocial,
        private_key=private_key,
        adjacent_nodes=adjacent_nodes,
        http_client=http_client,
        on_summary=_on_inbound_summary,
        poll_interval=15.0,
    )

    # ------------------------------------------------------------------
    # Ensure Qdrant collection exists
    # ------------------------------------------------------------------
    try:
        await rag_store.ensure_collection()
    except Exception as exc:
        logger.warning("main.qdrant_init_error", error=str(exc))

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("orchestrator.shutdown_signal")
        shutdown_event.set()
        round_controller.stop()
        subscriber.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    # ------------------------------------------------------------------
    # Start everything
    # ------------------------------------------------------------------
    await matrix_client.start()

    tasks = [
        asyncio.create_task(matrix_client.sync_forever(), name="matrix-sync"),
        asyncio.create_task(round_controller.run(), name="round-controller"),
        asyncio.create_task(subscriber.run(), name="federation-subscriber"),
        asyncio.create_task(shutdown_event.wait(), name="shutdown-watcher"),
    ]

    try:
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )
        # If the shutdown watcher finishes, cancel everything else
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        await matrix_client.stop()
        await http_client.aclose()
        logger.info("orchestrator.stopped")


if __name__ == "__main__":
    asyncio.run(main())
