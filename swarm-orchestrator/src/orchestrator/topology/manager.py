"""Topology manager — loads topology.toml and resolves adjacent nodes."""

from __future__ import annotations

from pathlib import Path

import tomli
import structlog

from orchestrator.models.topology import SwarmNode, Topology

logger = structlog.get_logger(__name__)


class TopologyManager:
    """Loads and validates the swarm topology graph."""

    def __init__(self, topology_file: str, self_node_id: str) -> None:
        self._topology_file = topology_file
        self._self_node_id = self_node_id
        self._topology: Topology | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self) -> Topology:
        """Parse the topology TOML file and return a Topology object."""
        path = Path(self._topology_file)
        if not path.exists():
            raise FileNotFoundError(
                f"Topology file not found: {self._topology_file}"
            )

        with path.open("rb") as fh:
            raw = tomli.load(fh)

        nodes_raw = raw.get("nodes", [])
        edges_raw = raw.get("edges", [])

        nodes_by_id: dict[str, SwarmNode] = {}
        for n in nodes_raw:
            node = SwarmNode(**n)
            nodes_by_id[node.node_id] = node

        if self._self_node_id not in nodes_by_id:
            raise ValueError(
                f"self_node_id '{self._self_node_id}' not found in topology"
            )

        self_node = nodes_by_id[self._self_node_id]
        adjacent = self._resolve_adjacent(self._self_node_id, nodes_by_id, edges_raw)

        self._topology = Topology(self_node=self_node, adjacent_nodes=adjacent)
        logger.info(
            "topology.loaded",
            self_node=self._self_node_id,
            adjacent_count=len(adjacent),
        )
        return self._topology

    @property
    def topology(self) -> Topology:
        """Return the loaded topology (raises if not yet loaded)."""
        if self._topology is None:
            raise RuntimeError("Topology not loaded — call load() first")
        return self._topology

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_adjacent_nodes(self, self_node_id: str | None = None) -> list[SwarmNode]:
        """Return the adjacent nodes for *self_node_id* (default: configured)."""
        return self.topology.adjacent_nodes

    @staticmethod
    def _resolve_adjacent(
        self_id: str,
        nodes: dict[str, SwarmNode],
        edges: list[dict],
    ) -> list[SwarmNode]:
        """Derive the set of neighbours from the edge list."""
        neighbour_ids: set[str] = set()
        for edge in edges:
            frm = edge.get("from", "")
            to = edge.get("to", "")
            bidirectional = edge.get("bidirectional", False)
            if frm == self_id:
                neighbour_ids.add(to)
            if to == self_id and bidirectional:
                neighbour_ids.add(frm)

        result: list[SwarmNode] = []
        for nid in neighbour_ids:
            if nid in nodes:
                result.append(nodes[nid])
            else:
                logger.warning("topology.missing_node", node_id=nid)
        return result
