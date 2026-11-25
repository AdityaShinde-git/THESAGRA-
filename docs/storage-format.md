# Initial Storage Format

The initial prototype uses 4096-byte fixed-size pages.

## Page layout

```text
20-byte header
payload
zero padding to 4096 bytes
```

The header is a big-endian structure:

```text
4-byte magic: "TSG1"
2-byte format version
2-byte page kind
4-byte page ID
4-byte payload length
4-byte CRC32 payload checksum
```

Page 0 is reserved for the database header. Other pages are currently data
pages.

## Record encoding

Each data page starts with a 32-bit record count. Records contain a 32-bit
value count followed by length-prefixed typed values.

Supported values:

- Null
- Boolean
- Signed 64-bit integer
- 64-bit float
- UTF-8 text
- Byte string

The format is versioned independently from the application protocol. Any
change requires a format migration or new format version.
