# Binary Object Storage

## Logical model

Blob metadata is stored in catalog-managed relational pages:

- Stable object ID
- Name
- MIME type
- Byte length
- SHA-256 checksum
- Lifecycle state
- Creation timestamp
- JSON-compatible application metadata

Object bytes are stored outside the database page file under a sibling
`.blobs` directory. Bytes are divided into 64 KiB chunks. Chunk metadata
records the object ID, chunk index, byte offset, byte length, and chunk
SHA-256 checksum.

## Lifecycle

1. `begin_blob_upload` creates an `uploading` object.
2. `append_blob_chunk` writes chunk files and updates metadata.
3. `finalize_blob` verifies declared size and every chunk checksum.
4. A successful finalization changes the object to `ready`.
5. `delete_blob` marks the object `deleted`.
6. `reconcile_blobs` removes directories that do not belong to live or
   uploading objects.

## Python API

```python
object_id = engine.begin_blob_upload(
    "image.bin",
    "application/octet-stream",
    {"category": "test"},
)
engine.append_blob_chunk(object_id, chunk)
metadata = engine.finalize_blob(object_id)
data = engine.read_blob_range(object_id, offset=0, length=1024)
for block in engine.stream_blob(object_id):
    consume(block)
```

## Consistency contract

Each appended chunk is written to a temporary file, flushed, and atomically
renamed before its chunk index and blob length are committed together through
the WAL. A crash before that metadata commit can leave an unreferenced chunk;
`reconcile_blobs` removes it. Reconciliation also prunes uncommitted trailing
chunk records left by older versions and refuses to run inside an active SQL
transaction, where deleting files could not be rolled back.

An object is readable only after finalization verifies that its chunks are
present, contiguous, correctly sized, and checksum-valid. The metadata and
filesystem are still separate persistence systems, so this is not a general
distributed transaction guarantee. Keep backups coordinated with writes and
run reconciliation after recovering from an interrupted upload.
