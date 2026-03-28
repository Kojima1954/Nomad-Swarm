"""Matrix client — matrix-nio wrapper for Conduit homeserver."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from nio import (
    AsyncClient,
    AsyncClientConfig,
    LoginError,
    MatrixRoom,
    RoomMessageText,
    SyncError,
)

from orchestrator.config import MatrixConfig

logger = structlog.get_logger(__name__)

# Delimiter used to identify Swarm Signal messages so they can be
# flagged in the transcript buffer.
SWARM_SIGNAL_MARKER = "🐝 SWARM SIGNAL"


class MatrixClient:
    """Async wrapper around matrix-nio for the Conduit homeserver."""

    def __init__(
        self,
        config: MatrixConfig,
        store_path: str = "/data/nio-store",
        message_callback: Callable[[str, str, str, bool], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._store_path = store_path
        self._message_callback = message_callback
        self._client: AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Log in, join the configured room, and begin syncing."""
        nio_config = AsyncClientConfig(store_sync_tokens=True)
        self._client = AsyncClient(
            homeserver=self._config.homeserver_url,
            user=self._config.user_id,
            store_path=self._store_path,
            config=nio_config,
        )

        # Register message event callback
        self._client.add_event_callback(self._on_message, RoomMessageText)  # type: ignore[arg-type]

        await self._login_with_retry()
        await self._join_room_with_retry()

    async def _login_with_retry(self, max_attempts: int = 5) -> None:
        """Attempt login, retrying with backoff on failure."""
        assert self._client is not None
        for attempt in range(1, max_attempts + 1):
            try:
                if self._config.access_token:
                    self._client.access_token = self._config.access_token
                    self._client.user_id = self._config.user_id
                    logger.info("matrix.login", method="access_token")
                    return

                resp = await self._client.login(password=self._config.password)
                if isinstance(resp, LoginError):
                    raise RuntimeError(f"Matrix login failed: {resp.message}")
                logger.info("matrix.login", method="password", user_id=self._config.user_id)
                return
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning(
                    "matrix.login.retry",
                    attempt=attempt,
                    error=str(exc),
                    retry_in=wait,
                )
                await asyncio.sleep(wait)
        raise RuntimeError("Matrix login failed after all retries")

    async def _join_room_with_retry(self, max_attempts: int = 10) -> None:
        """Join the configured room, retrying if it doesn't exist yet."""
        assert self._client is not None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await self._client.join(self._config.room_id)
                if hasattr(resp, "room_id"):
                    logger.info("matrix.room.joined", room_id=self._config.room_id)
                    return
                raise RuntimeError(f"Unexpected join response: {resp}")
            except Exception as exc:
                wait = min(2 ** attempt, 60)
                logger.warning(
                    "matrix.room.retry",
                    attempt=attempt,
                    error=str(exc),
                    retry_in=wait,
                )
                await asyncio.sleep(wait)
        raise RuntimeError(f"Could not join room {self._config.room_id} after retries")

    async def sync_forever(self) -> None:
        """Run the sync loop; call after start()."""
        assert self._client is not None
        logger.info("matrix.sync.start")
        await self._client.sync_forever(timeout=30000, full_state=True)

    async def stop(self) -> None:
        """Close the Matrix client connection."""
        if self._client:
            await self._client.close()
            logger.info("matrix.client.closed")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send_message(self, room_id: str, html_body: str) -> None:
        """Send an HTML message to *room_id*."""
        assert self._client is not None
        plain = _strip_html(html_body)
        content: dict[str, Any] = {
            "msgtype": "m.text",
            "body": plain,
            "format": "org.matrix.custom.html",
            "formatted_body": html_body,
        }
        await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )
        logger.debug("matrix.send", room_id=room_id, length=len(plain))

    async def send_swarm_signal(
        self,
        room_id: str,
        from_node: str,
        round_number: int,
        key_positions: list[str],
        emerging_consensus: str,
        dissenting_views: list[str],
        open_questions: list[str],
    ) -> None:
        """Send a formatted Swarm Signal into the room."""
        kp_lines = "\n".join(f"  • {p}" for p in key_positions)
        dv_lines = "\n".join(f"  • {v}" for v in dissenting_views) if dissenting_views else "  (none)"
        oq_lines = "\n".join(f"  • {q}" for q in open_questions) if open_questions else "  (none)"
        sep = "━" * 34
        body = (
            f"🐝 SWARM SIGNAL from {from_node} (Round {round_number}):\n"
            f"{sep}\n"
            f"📌 Key Positions:\n{kp_lines}\n\n"
            f"🤝 Emerging Consensus:\n  {emerging_consensus}\n\n"
            f"⚡ Dissenting Views:\n{dv_lines}\n\n"
            f"❓ Open Questions:\n{oq_lines}\n"
            f"{sep}"
        )
        html = body.replace("\n", "<br>")
        await self.send_message(room_id, html)

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        """Handle incoming room messages."""
        sender = room.user_name(event.sender) or event.sender
        body = event.body
        is_signal = body.startswith(SWARM_SIGNAL_MARKER)
        logger.debug(
            "matrix.message",
            sender=sender,
            is_swarm_signal=is_signal,
            preview=body[:80],
        )
        if self._message_callback:
            await self._message_callback(
                event.server_timestamp
                if hasattr(event, "server_timestamp")
                else "",
                sender,
                body,
                is_signal,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    """Very basic HTML tag stripper for plain-text fallback."""
    import re
    return re.sub(r"<[^>]+>", "", text).replace("<br>", "\n")
