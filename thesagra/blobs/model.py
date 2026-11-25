from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class BlobMetadata:
    object_id: int
    name: str
    mime_type: str
    byte_length: int
    checksum: str
    state: str
    created_at: str
    application_metadata: Dict


class BlobError(Exception):
    pass
