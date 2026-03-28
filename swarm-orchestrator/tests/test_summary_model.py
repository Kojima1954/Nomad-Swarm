"""Tests for SwarmSummary model."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from orchestrator.models.summary import SwarmSummary


class TestSwarmSummarySerialization:
    def test_round_trip(self, sample_summary_data):
        summary = SwarmSummary.from_jsonld(sample_summary_data)
        jsonld = summary.to_jsonld()

        restored = SwarmSummary.from_jsonld(jsonld)
        assert restored.round_number == summary.round_number
        assert restored.topic == summary.topic
        assert restored.source_node_id == summary.source_node_id
        assert restored.key_positions == summary.key_positions
        assert restored.emerging_consensus == summary.emerging_consensus

    def test_jsonld_context(self, sample_summary_data):
        summary = SwarmSummary.from_jsonld(sample_summary_data)
        jsonld = summary.to_jsonld()

        assert "@context" in jsonld
        assert "https://www.w3.org/ns/activitystreams" in jsonld["@context"]
        assert jsonld["type"] == "swarm:SwarmSummary"

    def test_jsonld_field_names(self, sample_summary_data):
        summary = SwarmSummary.from_jsonld(sample_summary_data)
        jsonld = summary.to_jsonld()

        assert "swarm:roundNumber" in jsonld
        assert "swarm:topic" in jsonld
        assert "swarm:sourceNodeId" in jsonld
        assert "swarm:keyPositions" in jsonld
        assert "swarm:emergingConsensus" in jsonld
        assert "swarm:dissentingViews" in jsonld
        assert "swarm:openQuestions" in jsonld
        assert "swarm:parentSummaryIds" in jsonld

    def test_published_format(self, sample_summary_data):
        summary = SwarmSummary.from_jsonld(sample_summary_data)
        jsonld = summary.to_jsonld()
        # Should be ISO-8601 UTC
        assert jsonld["published"].endswith("Z")

    def test_json_serializable(self, sample_summary_data):
        summary = SwarmSummary.from_jsonld(sample_summary_data)
        jsonld = summary.to_jsonld()
        # Should not raise
        encoded = json.dumps(jsonld)
        assert encoded


class TestSwarmSummaryValidation:
    def test_requires_key_positions(self):
        with pytest.raises(ValidationError):
            SwarmSummary(
                **{
                    "swarm:roundNumber": 1,
                    "swarm:topic": "test",
                    "swarm:sourceNodeId": "node-a",
                    "swarm:keyPositions": [],  # empty — invalid
                    "swarm:emergingConsensus": "some consensus",
                }
            )

    def test_requires_round_number_ge_1(self):
        with pytest.raises(ValidationError):
            SwarmSummary(
                **{
                    "swarm:roundNumber": 0,
                    "swarm:topic": "test",
                    "swarm:sourceNodeId": "node-a",
                    "swarm:keyPositions": ["position"],
                    "swarm:emergingConsensus": "some consensus",
                }
            )

    def test_defaults_for_optional_fields(self):
        summary = SwarmSummary(
            **{
                "swarm:roundNumber": 1,
                "swarm:topic": "test",
                "swarm:sourceNodeId": "node-a",
                "swarm:keyPositions": ["position"],
                "swarm:emergingConsensus": "some consensus",
            }
        )
        assert summary.dissenting_views == []
        assert summary.open_questions == []
        assert summary.parent_summary_ids == []
        assert summary.participant_count == 0
        assert summary.message_count == 0

    def test_summary_id_property(self, sample_summary_data):
        summary = SwarmSummary.from_jsonld(sample_summary_data)
        assert summary.summary_id == "node-alpha:round-3"

    def test_to_text(self, sample_summary_data):
        summary = SwarmSummary.from_jsonld(sample_summary_data)
        text = summary.to_text()
        assert "node-alpha" in text
        assert "Water purification" in text
        assert "Boiling" in text
        assert "Multi-method" in text
