"""Outbound federation — encrypt and publish SwarmSummary objects."""

from __future__ import annotations

import asyncio
import base64
import json
from collections import deque
from typing import Deque

import httpx
import structlog
from nacl.public import PrivateKey

from orchestrator.config import GoToSocialConfig
from orchestrator.federation.crypto import encrypt_for_nodes
from orchestrator.models.summary import SwarmSummary
from orchestrator.models.topology import SwarmNode

logger = structlog.get_logger(__name__)

_SWARM_DELIM_START = "<!--SWARM:"
_SWARM_DELIM_END = ":SWARM-->"


class Publisher:
    """Encrypt and publish summaries to adjacent nodes via GoToSocial."""

    def __init__(
        self,
        config: GoToSocialConfig,
        private_key: PrivateKey,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._private_key = private_key
        self._http = http_client
        self._base = config.base_url.rstrip("/")
        self._outbox: Deque[tuple[SwarmSummary, list[SwarmNode]]] = deque()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish(
        self, summary: SwarmSummary, adjacent_nodes: list[SwarmNode]
    ) -> None:
        """Encrypt *summary* and post it to each adjacent node.

        Failed deliveries are queued for retry on the next call.
        """
        # Re-attempt any queued items first
        await self._flush_queue()

        await self._send_to_nodes(summary, adjacent_nodes)

    async def _flush_queue(self) -> None:
        """Retry previously queued (failed) summaries."""
        pending = list(self._outbox)
        self._outbox.clear()
        for queued_summary, nodes in pending:
            await self._send_to_nodes(queued_summary, nodes)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _send_to_nodes(
        self, summary: SwarmSummary, nodes: list[SwarmNode]
    ) -> None:
        """Encrypt and post *summary* to each node in *nodes*."""
        if not nodes:
            logger.info("publisher.no_recipients", round=summary.round_number)
            return

        plaintext = json.dumps(summary.to_jsonld()).encode()

        # Build recipient key map
        recipient_keys: dict[str, bytes] = {}
        for node in nodes:
            try:
                recipient_keys[node.node_id] = base64.b64decode(
                    node.encryption_public_key
                )
            except Exception as exc:
                logger.error(
                    "publisher.bad_key",
                    node_id=node.node_id,
                    error=str(exc),
                )

        if not recipient_keys:
            logger.warning("publisher.no_valid_keys")
            return

        encrypted_map = encrypt_for_nodes(plaintext, recipient_keys)

        for node in nodes:
            node_ciphertext = encrypted_map.get(node.node_id)
            if node_ciphertext is None:
                continue

            teaser = (
                f"🐝 Swarm Summary Round {summary.round_number} from "
                f"{summary.source_node_id} — [encrypted payload attached] "
                f"@{node.actor_uri}"
            )
            status_body = (
                f"{teaser}\n"
                f"{_SWARM_DELIM_START}{node_ciphertext}{_SWARM_DELIM_END}"
            )

            try:
                await self._post_status(
                    body=status_body,
                    visibility="direct",
                )
                logger.info(
                    "publisher.sent",
                    to_node=node.node_id,
                    round=summary.round_number,
                )
            except Exception as exc:
                logger.error(
                    "publisher.send_error",
                    to_node=node.node_id,
                    error=str(exc),
                )
                # Queue for retry
                self._outbox.append((summary, [node]))

    async def _post_status(self, body: str, visibility: str = "direct") -> None:
        """POST to GoToSocial /api/v1/statuses."""
        headers = {"Authorization": f"Bearer {self._config.access_token}"}
        payload = {"status": body, "visibility": visibility}
        resp = await self._http.post(
            f"{self._base}/api/v1/statuses",
            json=payload,
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
