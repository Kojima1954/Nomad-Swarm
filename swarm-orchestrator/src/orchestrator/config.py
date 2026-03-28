"""Pydantic settings model — loads TOML configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import tomli
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class NodeConfig(BaseModel):
    id: str = "node-alpha"
    display_name: str = "Node Alpha"


class MatrixConfig(BaseModel):
    homeserver_url: str = "http://conduit:6167"
    user_id: str = "@orchestrator:localhost"
    password: str = ""
    access_token: str = ""
    room_id: str = "!deliberation:localhost"


class OllamaConfig(BaseModel):
    base_url: str = "http://ollama:11434"
    model: str = "llama3.1:8b"
    temperature: float = 0.3
    max_tokens: int = 2048
    embedding_model: str = "nomic-embed-text"


class QdrantConfig(BaseModel):
    url: str = "http://qdrant:6333"
    collection: str = "swarm_summaries"


class GoToSocialConfig(BaseModel):
    base_url: str = "http://gotosocial:8080"
    access_token: str = ""
    actor_handle: str = ""


class CryptoConfig(BaseModel):
    private_key_path: str = "/data/keys/node.key"
    public_key_path: str = "/data/keys/node.pub"


class RoundsConfig(BaseModel):
    mode: Literal["timer", "message_count", "manual"] = "timer"
    interval_seconds: int = 300
    message_threshold: int = 50
    phases: list[str] = ["DISCUSS", "SUMMARIZE", "PROPAGATE"]


class TopologyConfig(BaseModel):
    topology_file: str = "/etc/orchestrator/topology.toml"


# ---------------------------------------------------------------------------
# Root settings
# ---------------------------------------------------------------------------

class OrchestratorConfig(BaseSettings):
    """Root configuration object loaded from a TOML file."""

    node: NodeConfig = NodeConfig()
    matrix: MatrixConfig = MatrixConfig()
    ollama: OllamaConfig = OllamaConfig()
    qdrant: QdrantConfig = QdrantConfig()
    gotosocial: GoToSocialConfig = GoToSocialConfig()
    crypto: CryptoConfig = CryptoConfig()
    rounds: RoundsConfig = RoundsConfig()
    topology: TopologyConfig = TopologyConfig()

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def load(cls, path: str | None = None) -> "OrchestratorConfig":
        """Load configuration from a TOML file.

        The path is resolved in this order:
        1. The *path* argument (if provided).
        2. The ``ORCHESTRATOR_CONFIG`` environment variable.
        3. The default path ``/etc/orchestrator/config.toml``.
        4. Falls back to all-defaults if the file does not exist.
        """
        config_path = path or os.environ.get(
            "ORCHESTRATOR_CONFIG", "/etc/orchestrator/config.toml"
        )
        file = Path(config_path)
        if not file.exists():
            return cls()

        with file.open("rb") as fh:
            raw = tomli.load(fh)

        return cls.model_validate(raw)
