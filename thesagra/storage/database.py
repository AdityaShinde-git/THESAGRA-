import os
from typing import Iterable

from .page import (
    MAGIC,
    PAGE_SIZE,
    PAGE_KIND_DATABASE,
    PAGE_KIND_DATA,
    PageError,
    decode_data_payload,
    decode_page,
    encode_data_payload,
    encode_page,
)


class DatabaseFile:
    """A minimal persistent file containing fixed-size pages."""

    def __init__(self, path: str):
        self.path = os.fspath(path)

    @classmethod
    def create(cls, path: str):
        self = cls(path)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "wb+") as file:
            file.write(encode_page(0, PAGE_KIND_DATABASE, MAGIC))
            file.write(encode_page(1, PAGE_KIND_DATA, b"\x00\x00\x00\x00"))
            file.flush()
            os.fsync(file.fileno())
        return self

    @classmethod
    def open(cls, path: str):
        self = cls(path)
        self._validate_file()
        return self

    def _validate_file(self):
        with open(self.path, "rb") as file:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            if size < PAGE_SIZE:
                raise PageError("Database file is truncated")
            if size % PAGE_SIZE != 0:
                raise PageError("Database file size is not page-aligned")
            file.seek(0)
            first_page = file.read(PAGE_SIZE)

        kind, payload = decode_page(first_page, 0)
        if kind != PAGE_KIND_DATABASE:
            raise PageError("Page 0 is not a database header page")
        if payload != MAGIC:
            raise PageError("Invalid database header")

    def page_count(self) -> int:
        size = os.path.getsize(self.path)
        return size // PAGE_SIZE

    def allocate_page(self) -> int:
        page_id = self.page_count()
        with open(self.path, "rb+") as file:
            file.seek(page_id * PAGE_SIZE)
            file.write(encode_page(page_id, PAGE_KIND_DATA, b"\x00\x00\x00\x00"))
            file.truncate((page_id + 1) * PAGE_SIZE)
            file.flush()
            os.fsync(file.fileno())
        return page_id

    def write_records(self, page_id: int, records: Iterable[Iterable]):
        payload = encode_data_payload(records)
        page = encode_page(page_id, PAGE_KIND_DATA, payload)
        self._write_page(page_id, page)

    def read_records(self, page_id: int):
        page = self._read_page(page_id)
        kind, payload = decode_page(page, page_id)
        if kind != PAGE_KIND_DATA:
            raise PageError(f"Page {page_id} is not a data page")
        return decode_data_payload(payload)

    def _read_page(self, page_id: int) -> bytes:
        if page_id < 0 or page_id >= self.page_count():
            raise PageError(f"Page {page_id} does not exist")
        with open(self.path, "rb") as file:
            file.seek(page_id * PAGE_SIZE)
            page = file.read(PAGE_SIZE)
        if len(page) != PAGE_SIZE:
            raise PageError(f"Page {page_id} is truncated")
        return page

    def _write_page(self, page_id: int, page: bytes):
        if page_id < 0:
            raise PageError("Page ID cannot be negative")
        if page_id * PAGE_SIZE > os.path.getsize(self.path):
            raise PageError(f"Page {page_id} has not been allocated")
        if page_id == 0:
            raise PageError("Page 0 is reserved")
        with open(self.path, "rb+") as file:
            file.seek(page_id * PAGE_SIZE)
            file.write(page)
            file.flush()
            os.fsync(file.fileno())
