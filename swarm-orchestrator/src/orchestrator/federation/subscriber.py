"""Inbound federation — poll GoToSocial and decrypt incoming summaries."""

from __future__ import annotations

import asyncio
import base64
import json
import re
from collections.abc import Callable, Awaitable

import httpx
import structlog
from nacl.public import PrivateKey

from orchestrator.config import GoToSocialConfig
from orchestrator.federation.crypto import decrypt_from_node
from orchestrator.models.summary import SwarmSummary
from orchestrator.models.topology import SwarmNode

logger = structlog.get_logger(__name__)

_SWARM_PATTERN = re.compile(
    r"<!--SWARM:(?P<payload>[A-Za-z0-9+/=]+):SWARM-->"
)


class Subscriber:
    """Poll GoToSocial for incoming encrypted SwarmSummary messages."""

    def __init__(
        self,
        config: GoToSocialConfig,
        private_key: PrivateKey,
        adjacent_nodes: list[SwarmNode],
        http_client: httpx.AsyncClient,
        on_summary: Callable[[SwarmSummary], Awaitable[None]] | None = None,
        poll_interval: float = 15.0,
    ) -> None:
        self._config = config
        self._private_key = private_key
        self._adjacent_node_ids = {n.node_id for n in adjacent_nodes}
        self._http = http_client
        self._on_summary = on_summary
        self._poll_interval = poll_interval
        self._base = config.base_url.rstrip("/")
        self._running = False
        self._seen_ids: set[str] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Poll forever until stopped."""
        self._running = True
        logger.info("subscriber.start", poll_interval=self._poll_interval)
        while self._running:
            try:
                await self._poll()
            except Exception as exc:
                logger.error("subscriber.poll_error", error=str(exc))
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        """Signal the polling loop to stop."""
        self._running = False

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll(self) -> None:
        """Fetch new notifications/mentions and process swarm payloads."""
        headers = {"Authorization": f"Bearer {self._config.access_token}"}
        url = f"{self._base}/api/v1/notifications"
        params = {"types[]": "mention", "limit": "40"}

        resp = await self._http.get(
            url, headers=headers, params=params, timeout=30.0
        )
        resp.raise_for_status()
        notifications = resp.json()

        for notif in notifications:
            notif_id = notif.get("id", "")
            if notif_id in self._seen_ids:
                continue
            self._seen_ids.add(notif_id)

            status = notif.get("status")
            if not status:
                continue

            content = status.get("content", "") or status.get("text", "")
            await self._process_content(content)

    async def _process_content(self, content: str) -> None:
        """Extract, decrypt, and validate a swarm payload from *content*."""
        match = _SWARM_PATTERN.search(content)
        if not match:
            return

        payload_b64 = match.group("payload")
        try:
            ciphertext = base64.b64decode(payload_b64)
            plaintext = decrypt_from_node(ciphertext, self._private_key)
        except Exception as exc:
            logger.warning("subscriber.decrypt_error", error=str(exc))
            return

        try:
            data = json.loads(plaintext)
            summary = SwarmSummary.from_jsonld(data)
        except Exception as exc:
            logger.warning("subscriber.parse_error", error=str(exc))
            return

        # Validate sender is a known adjacent node
        if summary.source_node_id not in self._adjacent_node_ids:
            logger.warning(
                "subscriber.unknown_sender",
                source_node_id=summary.source_node_id,
            )
            return

        logger.info(
            "subscriber.received",
            from_node=summary.source_node_id,
            round=summary.round_number,
        )

        if self._on_summary:
            await self._on_summary(summary)
