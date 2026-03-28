"""Topology models — Node and Topology."""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class SwarmNode(BaseModel):
    """Represents a single node in the swarm graph."""

    node_id: str
    actor_uri: str
    encryption_public_key: str  # Base64-encoded X25519 public key

    @field_validator("node_id", "actor_uri", "encryption_public_key", mode="before")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field must not be empty")
        return v


class Topology(BaseModel):
    """The swarm graph as seen from this node."""

    self_node: SwarmNode
    adjacent_nodes: list[SwarmNode] = []
