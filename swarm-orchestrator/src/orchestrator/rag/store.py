"""Qdrant vector store — embed and retrieve SwarmSummary objects."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import structlog

from orchestrator.config import OllamaConfig, QdrantConfig
from orchestrator.models.summary import SwarmSummary

logger = structlog.get_logger(__name__)

_VECTOR_SIZE_DEFAULT = 768  # nomic-embed-text default


class RAGStore:
    """Interface to the Qdrant vector database."""

    def __init__(
        self,
        qdrant_config: QdrantConfig,
        ollama_config: OllamaConfig,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._qcfg = qdrant_config
        self._ocfg = ollama_config
        self._http = http_client
        self._qdrant_base = qdrant_config.url.rstrip("/")
        self._embedding_model = ollama_config.embedding_model
        self._embed_url = f"{ollama_config.base_url.rstrip('/')}/api/embeddings"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def ensure_collection(self, vector_size: int = _VECTOR_SIZE_DEFAULT) -> None:
        """Create the Qdrant collection if it does not already exist."""
        url = f"{self._qdrant_base}/collections/{self._qcfg.collection}"
        resp = await self._http.get(url)
        if resp.status_code == 200:
            logger.debug("rag.collection.exists", collection=self._qcfg.collection)
            return

        # Create it
        body: dict[str, Any] = {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine",
            }
        }
        resp = await self._http.put(url, json=body)
        resp.raise_for_status()
        logger.info(
            "rag.collection.created",
            collection=self._qcfg.collection,
            vector_size=vector_size,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def store_summary(self, summary: SwarmSummary) -> None:
        """Embed *summary* and upsert it into Qdrant."""
        text = summary.to_text()
        vector = await self._embed(text)

        point_id = _stable_id(summary.summary_id)
        payload: dict[str, Any] = {
            "summary_id": summary.summary_id,
            "source_node_id": summary.source_node_id,
            "round_number": summary.round_number,
            "topic": summary.topic,
            "text": text,
        }

        upsert_url = (
            f"{self._qdrant_base}/collections/{self._qcfg.collection}/points"
        )
        body: dict[str, Any] = {
            "points": [
                {"id": point_id, "vector": vector, "payload": payload}
            ]
        }
        resp = await self._http.put(upsert_url, json=body)
        resp.raise_for_status()
        logger.info(
            "rag.store_summary",
            summary_id=summary.summary_id,
            point_id=point_id,
        )

    async def retrieve_context(self, query: str, top_k: int = 5) -> str:
        """Embed *query* and return formatted context from the top-k results."""
        vector = await self._embed(query)

        search_url = (
            f"{self._qdrant_base}/collections/{self._qcfg.collection}/points/search"
        )
        body: dict[str, Any] = {
            "vector": vector,
            "limit": top_k,
            "with_payload": True,
        }
        resp = await self._http.post(search_url, json=body)
        resp.raise_for_status()
        results = resp.json().get("result", [])

        if not results:
            return ""

        parts: list[str] = []
        for hit in results:
            p = hit.get("payload", {})
            score = hit.get("score", 0.0)
            parts.append(
                f"[{p.get('summary_id', '?')} | score={score:.3f}]\n{p.get('text', '')}"
            )

        return "\n\n---\n\n".join(parts)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _embed(self, text: str) -> list[float]:
        """Call Ollama /api/embeddings and return the embedding vector."""
        payload = {"model": self._embedding_model, "prompt": text}
        resp = await self._http.post(self._embed_url, json=payload, timeout=60.0)
        resp.raise_for_status()
        return resp.json()["embedding"]


def _stable_id(summary_id: str) -> int:
    """Convert a string ID to a stable positive integer for Qdrant."""
    digest = hashlib.sha256(summary_id.encode()).hexdigest()
    # Use lower 63 bits so it fits in a signed 64-bit integer
    return int(digest[:16], 16) & 0x7FFFFFFFFFFFFFFF
