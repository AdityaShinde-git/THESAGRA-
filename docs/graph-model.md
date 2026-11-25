# Graph Model and Traversal

## Storage model

Nodes and edges use stable integer identities and are stored in catalog-managed
relational pages:

- Nodes: `node_id`, `label`, and JSON-compatible properties.
- Edges: `edge_id`, source node ID, target node ID, relationship type, and
  JSON-compatible properties.

The graph uses directed edges. A node and edge can be shared with the existing
transaction staging and write-ahead-log behavior.

## Python API

```python
node = engine.create_node("Person", {"name": "Ada"}, node_id=1)
edge = engine.create_edge(1, 2, "KNOWS", {"since": 2020})
paths = engine.traverse(1, depth=2)
```

Traversal is bounded:

- `depth` controls the maximum number of outgoing edge steps.
- `relationship_type` optionally filters each step.
- `max_nodes` caps discovered nodes and prevents unbounded result growth.
- Cycles are not revisited.

Edge creation validates both endpoints. Node deletion is rejected while the
node has incident edges. Edge deletion removes only the selected edge.
