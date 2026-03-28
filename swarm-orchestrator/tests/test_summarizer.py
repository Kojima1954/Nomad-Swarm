"""Tests for the LLM summarizer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.config import OllamaConfig
from orchestrator.llm.summarizer import Summarizer, _extract_json
from orchestrator.models.summary import SwarmSummary


VALID_SUMMARY_JSON = {
    "swarm:roundNumber": 1,
    "swarm:topic": "Water purification",
    "swarm:sourceNodeId": "node-alpha",
    "published": "2026-03-26T14:30:00Z",
    "swarm:participantCount": 3,
    "swarm:messageCount": 10,
    "swarm:keyPositions": ["Boiling works", "Solar viable"],
    "swarm:emergingConsensus": "Multi-method approach",
    "swarm:dissentingViews": [],
    "swarm:openQuestions": [],
    "swarm:parentSummaryIds": [],
}


@pytest.fixture
def ollama_config() -> OllamaConfig:
    return OllamaConfig(
        base_url="http://ollama:11434",
        model="llama3.1:8b",
        temperature=0.3,
        max_tokens=2048,
    )


class TestExtractJson:
    def test_plain_json(self):
        text = json.dumps(VALID_SUMMARY_JSON)
        result = _extract_json(text)
        assert result["swarm:roundNumber"] == 1

    def test_json_in_markdown_fence(self):
        text = f"```json\n{json.dumps(VALID_SUMMARY_JSON)}\n```"
        result = _extract_json(text)
        assert result["swarm:roundNumber"] == 1

    def test_json_with_surrounding_text(self):
        text = f"Here is the result:\n{json.dumps(VALID_SUMMARY_JSON)}\nEnd."
        result = _extract_json(text)
        assert result["swarm:roundNumber"] == 1

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="No JSON object found"):
            _extract_json("There is no JSON here.")


class TestSummarizer:
    @pytest.mark.asyncio
    async def test_successful_summarization(self, ollama_config):
        mock_http = MagicMock()
        # Pass 1 returns natural language; pass 2 returns structured JSON
        natural_lang_resp = MagicMock()
        natural_lang_resp.json.return_value = {
            "message": {"content": "This is a natural language summary."}
        }
        natural_lang_resp.raise_for_status = MagicMock()

        json_resp = MagicMock()
        json_resp.json.return_value = {
            "message": {"content": json.dumps(VALID_SUMMARY_JSON)}
        }
        json_resp.raise_for_status = MagicMock()

        mock_http.post = AsyncMock(
            side_effect=[natural_lang_resp, json_resp]
        )

        summarizer = Summarizer(config=ollama_config, http_client=mock_http)
        result = await summarizer.summarize(
            transcript="Alice: Hello\nBob: World",
            inbound_summaries=[],
            rag_context="",
            round_number=1,
            source_node_id="node-alpha",
            participant_count=2,
            message_count=2,
        )
        assert isinstance(result, SwarmSummary)
        assert result.round_number == 1
        assert result.source_node_id == "node-alpha"

    @pytest.mark.asyncio
    async def test_retry_on_malformed_json(self, ollama_config):
        """Summarizer retries up to 2 times on parse failure, then succeeds."""
        mock_http = MagicMock()

        natural_lang_resp = MagicMock()
        natural_lang_resp.json.return_value = {
            "message": {"content": "Natural language summary."}
        }
        natural_lang_resp.raise_for_status = MagicMock()

        bad_json_resp = MagicMock()
        bad_json_resp.json.return_value = {
            "message": {"content": "not valid json {{{{"}
        }
        bad_json_resp.raise_for_status = MagicMock()

        good_json_resp = MagicMock()
        good_json_resp.json.return_value = {
            "message": {"content": json.dumps(VALID_SUMMARY_JSON)}
        }
        good_json_resp.raise_for_status = MagicMock()

        # Pass 1: natural language; Pass 2: bad JSON; Pass 2 retry: good JSON
        mock_http.post = AsyncMock(
            side_effect=[natural_lang_resp, bad_json_resp, good_json_resp]
        )

        summarizer = Summarizer(config=ollama_config, http_client=mock_http)
        result = await summarizer.summarize(
            transcript="Alice: Hello",
            inbound_summaries=[],
            rag_context="",
            round_number=1,
            source_node_id="node-alpha",
        )
        assert isinstance(result, SwarmSummary)

    @pytest.mark.asyncio
    async def test_ollama_unavailable_raises(self, ollama_config):
        """Raises after exhausting retries when Ollama is unavailable."""
        mock_http = MagicMock()
        mock_http.post = AsyncMock(side_effect=Exception("Connection refused"))

        summarizer = Summarizer(config=ollama_config, http_client=mock_http)

        with pytest.raises(Exception):
            await summarizer.summarize(
                transcript="Alice: test",
                inbound_summaries=[],
                rag_context="",
                round_number=1,
                source_node_id="node-alpha",
            )
