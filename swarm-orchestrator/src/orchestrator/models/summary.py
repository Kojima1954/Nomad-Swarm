"""SwarmSummary — JSON-LD compatible Pydantic model for inter-node summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


# JSON-LD context used for all SwarmSummary objects
_JSONLD_CONTEXT: list[Any] = [
    "https://www.w3.org/ns/activitystreams",
    {"swarm": "https://nomad-swarm.org/ns#"},
]


class SwarmSummary(BaseModel):
    """A structured summary produced at the end of each deliberation round.

    Serialises to / deserialises from the JSON-LD shape defined in the spec.
    """

    round_number: int = Field(..., alias="swarm:roundNumber", ge=1)
    topic: str = Field(..., alias="swarm:topic")
    source_node_id: str = Field(..., alias="swarm:sourceNodeId")
    published: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        alias="published",
    )
    participant_count: int = Field(default=0, alias="swarm:participantCount", ge=0)
    message_count: int = Field(default=0, alias="swarm:messageCount", ge=0)
    key_positions: list[str] = Field(..., alias="swarm:keyPositions", min_length=1)
    emerging_consensus: str = Field(..., alias="swarm:emergingConsensus")
    dissenting_views: list[str] = Field(
        default_factory=list, alias="swarm:dissentingViews"
    )
    open_questions: list[str] = Field(
        default_factory=list, alias="swarm:openQuestions"
    )
    parent_summary_ids: list[str] = Field(
        default_factory=list, alias="swarm:parentSummaryIds"
    )

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
    }

    @field_validator("key_positions", mode="before")
    @classmethod
    def _key_positions_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("key_positions must contain at least one entry")
        return v

    @field_validator("round_number", mode="before")
    @classmethod
    def _round_number_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("round_number must be >= 1")
        return v

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_jsonld(self) -> dict[str, Any]:
        """Return a JSON-LD compatible dictionary."""
        return {
            "@context": _JSONLD_CONTEXT,
            "type": "swarm:SwarmSummary",
            "swarm:roundNumber": self.round_number,
            "swarm:topic": self.topic,
            "swarm:sourceNodeId": self.source_node_id,
            "published": self.published.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "swarm:participantCount": self.participant_count,
            "swarm:messageCount": self.message_count,
            "swarm:keyPositions": self.key_positions,
            "swarm:emergingConsensus": self.emerging_consensus,
            "swarm:dissentingViews": self.dissenting_views,
            "swarm:openQuestions": self.open_questions,
            "swarm:parentSummaryIds": self.parent_summary_ids,
        }

    @classmethod
    def from_jsonld(cls, data: dict[str, Any]) -> "SwarmSummary":
        """Parse a JSON-LD dictionary into a SwarmSummary."""
        # Strip @context and type before validation
        payload = {k: v for k, v in data.items() if k not in ("@context", "type")}
        return cls.model_validate(payload)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def summary_id(self) -> str:
        """A unique identifier in the form ``{node_id}:round-{n}``."""
        return f"{self.source_node_id}:round-{self.round_number}"

    def to_text(self) -> str:
        """Return a plain-text representation suitable for embedding / prompts."""
        lines = [
            f"[Round {self.round_number} | {self.source_node_id}]",
            f"Topic: {self.topic}",
            f"Published: {self.published.isoformat()}",
            "",
            "Key Positions:",
        ]
        for kp in self.key_positions:
            lines.append(f"  • {kp}")
        lines += [
            "",
            f"Emerging Consensus: {self.emerging_consensus}",
        ]
        if self.dissenting_views:
            lines.append("")
            lines.append("Dissenting Views:")
            for dv in self.dissenting_views:
                lines.append(f"  • {dv}")
        if self.open_questions:
            lines.append("")
            lines.append("Open Questions:")
            for oq in self.open_questions:
                lines.append(f"  • {oq}")
        return "\n".join(lines)
