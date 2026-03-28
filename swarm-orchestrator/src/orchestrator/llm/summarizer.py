"""LLM summarizer — calls Ollama to produce SwarmSummary objects."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import structlog

from orchestrator.config import OllamaConfig
from orchestrator.llm.prompts import (
    NATURAL_LANGUAGE_SUMMARY_PROMPT,
    RAG_CONTEXT_SECTION_TEMPLATE,
    STRUCTURE_SUMMARY_PROMPT,
    SUMMARY_JSON_SCHEMA,
    SWARM_SIGNALS_SECTION_TEMPLATE,
    SYSTEM_PROMPT,
)
from orchestrator.models.summary import SwarmSummary

logger = structlog.get_logger(__name__)


class Summarizer:
    """Two-pass LLM summarizer using the Ollama API."""

    def __init__(self, config: OllamaConfig, http_client: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http_client
        self._chat_url = f"{config.base_url.rstrip('/')}/api/chat"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def summarize(
        self,
        transcript: str,
        inbound_summaries: list[SwarmSummary],
        rag_context: str,
        round_number: int,
        source_node_id: str,
        participant_count: int = 0,
        message_count: int = 0,
    ) -> SwarmSummary:
        """Run a two-pass summarization and return a SwarmSummary."""

        # ---- Build context sections ----
        swarm_signals_section = ""
        parent_ids: list[str] = []
        if inbound_summaries:
            signals_text = "\n\n".join(s.to_text() for s in inbound_summaries)
            swarm_signals_section = SWARM_SIGNALS_SECTION_TEMPLATE.format(
                signals=signals_text
            )
            parent_ids = [s.summary_id for s in inbound_summaries]

        rag_context_section = ""
        if rag_context:
            rag_context_section = RAG_CONTEXT_SECTION_TEMPLATE.format(
                rag_context=rag_context
            )

        # ---- Pass 1: natural-language summary ----
        user_prompt_1 = NATURAL_LANGUAGE_SUMMARY_PROMPT.format(
            transcript=transcript,
            swarm_signals_section=swarm_signals_section,
            rag_context_section=rag_context_section,
        )
        natural_language = await self._chat(SYSTEM_PROMPT, user_prompt_1)
        logger.debug("summarizer.pass1", preview=natural_language[:200])

        # ---- Pass 2: structure into JSON ----
        user_prompt_2 = STRUCTURE_SUMMARY_PROMPT.format(
            natural_language_summary=natural_language,
            schema=SUMMARY_JSON_SCHEMA,
            round_number=round_number,
            source_node_id=source_node_id,
            parent_summary_ids=json.dumps(parent_ids),
            participant_count=participant_count,
            message_count=message_count,
        )

        for attempt in range(3):
            raw_json = await self._chat(SYSTEM_PROMPT, user_prompt_2)
            try:
                data = _extract_json(raw_json)
                summary = SwarmSummary.from_jsonld(data)
                logger.info(
                    "summarizer.success",
                    round=round_number,
                    node=source_node_id,
                    attempt=attempt + 1,
                )
                return summary
            except Exception as exc:
                logger.warning(
                    "summarizer.parse_error",
                    attempt=attempt + 1,
                    error=str(exc),
                    raw=raw_json[:300],
                )
                if attempt == 2:
                    raise

        # Should never reach here
        raise RuntimeError("Summarization failed after 3 attempts")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _chat(
        self, system: str, user: str, max_retries: int = 4
    ) -> str:
        """POST to /api/chat with retry/backoff on transient errors."""
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {
                "temperature": self._config.temperature,
                "num_predict": self._config.max_tokens,
            },
            "stream": False,
        }

        for attempt in range(1, max_retries + 1):
            try:
                resp = await self._http.post(
                    self._chat_url,
                    json=payload,
                    timeout=120.0,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["message"]["content"]
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning(
                    "summarizer.ollama_error",
                    attempt=attempt,
                    error=str(exc),
                    retry_in=wait,
                )
                if attempt == max_retries:
                    raise
                await asyncio.sleep(wait)

        raise RuntimeError("Unreachable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict[str, Any]:
    """Extract the first JSON object from *text*, handling markdown fences."""
    import re

    # Strip markdown code fences
    text = re.sub(r"```(?:json)?", "", text).strip()

    # Find the outermost { ... }
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM response")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise ValueError("Unterminated JSON object in LLM response")
