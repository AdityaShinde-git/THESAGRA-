from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class GraphNode:
    node_id: int
    label: str
    properties: Dict


@dataclass(frozen=True)
class GraphEdge:
    edge_id: int
    source_node_id: int
    target_node_id: int
    relationship_type: str
    properties: Dict


class GraphError(Exception):
    pass
