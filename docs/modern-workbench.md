# THESAGRA Modern Desktop Workbench

## Launch

Start a THESAGRA server, then launch the desktop workbench:

```powershell
python -m thesagra.cli sample.db --serve --host 127.0.0.1 --port 5439
python -m thesagra.cli --gui
```

Use `admin` / `change-me` unless custom credentials or password hashes are
configured.

## Workbench sections

### SQL Console

- Multi-statement SQL editor
- Choose an existing database from the connection-bar picker, or use Create DB
  when connected as the system administrator
- Connect with an empty database selection to browse accessible databases
- Execute with the button, `F5`, or `Ctrl+Enter`
- Select a named database in the connection bar when using hosted mode
- BEGIN/COMMIT/ROLLBACK controls
- Tabular result grid
- Query history
- CSV export

### Catalog

- Browse tables and columns in a database-object tree
- Inspect column types, nullability, keys, and defaults
- Open a table's Data Preview tab to read up to 100 rows in place
- Send a sample SELECT to the SQL Console
- Refresh after schema changes

### Graph

- Use the graph canvas to drag nodes, pan by dragging the background, and zoom
  with the mouse wheel; Fit Graph recenters the current layout
- Select a node or relationship to expand its details and properties in the
  inspector
- Run the supported Cypher-like `MATCH` pattern in the editor with Ctrl+Enter
  or Run Cypher; results appear below the editor
- The current query subset matches one directed, labeled relationship, for
  example `MATCH (p:Person)-[:KNOWS]->(q:Person);`; it is not full Cypher and
  does not support `RETURN`
- Create nodes, relationships, and bounded traversals in the Quick Actions tab

### Blobs

- Upload local files in 64 KiB chunks
- Refresh blob metadata
- Select a blob to inspect its metadata, including its checksum
- Text and JSON blobs show decoded text; other binary blobs show a hex preview
- PDFs up to 32 MiB render in the preview canvas with page navigation, zoom,
  and pan; larger files can be downloaded for external viewing
- Image preview fits the available space and supports mouse-wheel zoom around
  the pointer, mouse-drag panning, plus Fit, 100%, and button zoom controls
- Open a blob with the system viewer for full-resolution inspection
- Mark selected blobs deleted
- Download finalized blobs as local files; a missing extension is inferred
  from the blob MIME type where possible

### SQL scripts

- The SQL workbench accepts semicolon-separated statements and strips
  `--` and `/* ... */` comments when splitting a script
- Named-database servers support `CREATE DATABASE name` and `USE name`;
  database creation requires the system administrator
- The relational SQL subset includes foreign keys, composite primary keys,
  multi-row inserts, joins, aggregates, filters, subqueries, indexes, and
  transactions; `ALTER TABLE` supports add/drop/rename operations. See
  [query-features.md](./query-features.md) for the exact support matrix and
  missing features; this is not PostgreSQL compatibility.
- `DROP TABLE` uses RESTRICT by default and refuses to drop a table still
  referenced by foreign keys; add `CASCADE` to remove those constraints, or
  drop dependent tables first

### Workers

- View worker running state
- Inspect queued, completed, failed, and dead task counts
- Inspect claimed-task metrics
- Review recent task IDs, attempts, timestamps, and errors
- Enqueue blob reconciliation or integrity-check tasks
