"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_summary_data() -> dict:
    return {
        "swarm:roundNumber": 3,
        "swarm:topic": "Water purification strategies",
        "swarm:sourceNodeId": "node-alpha",
        "published": "2026-03-26T14:30:00Z",
        "swarm:participantCount": 7,
        "swarm:messageCount": 43,
        "swarm:keyPositions": [
            "Boiling is most reliable but fuel-intensive",
            "Solar disinfection viable in equatorial regions",
        ],
        "swarm:emergingConsensus": "Multi-method approach preferred",
        "swarm:dissentingViews": ["Chlorine tablets dismissed too quickly"],
        "swarm:openQuestions": ["Shelf life of ceramic filters?"],
        "swarm:parentSummaryIds": ["node-beta:round-2", "node-gamma:round-2"],
    }
