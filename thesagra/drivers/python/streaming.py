from typing import Iterator


def iter_blob_chunks(connection, object_id: int,
                     chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    offset = 0
    while True:
        chunk = connection.read_blob(
            object_id,
            start=offset,
            length=chunk_size,
        )
        if not chunk:
            break
        yield chunk
        if len(chunk) < chunk_size:
            break
        offset += len(chunk)
