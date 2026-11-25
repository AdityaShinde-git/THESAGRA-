# Security Hardening

## Password configuration

Generate a PBKDF2-SHA256 password hash:

```powershell
python -m thesagra.cli --hash-password change-me
```

Pass the hash to the TCP or Web server:

```powershell
$env:THESAGRA_USERNAME="admin"
$env:THESAGRA_PASSWORD_HASH="<generated-hash>"
python -m thesagra.cli sample.db --serve
```

For environment-only plaintext configuration, `THESAGRA_PASSWORD` remains
available for development:

```powershell
$env:THESAGRA_PASSWORD="change-me"
```

The hash configuration is preferred. Hashes use PBKDF2-SHA256 with a random
salt. The server never records a plaintext password in audit logs.

## Authentication throttling

Both TCP and Web servers lock an IP address after repeated authentication
failures for one minute. The lock threshold is five failures within sixty
seconds.

## Audit log

The server writes JSON Lines audit events beside the database:

```text
<database>.audit.jsonl
```

Events include authentication success, authentication failure, lockout,
and session disconnection. Credentials and SQL payloads are not logged.

## TLS

TLS 1.2 or newer can be enabled for TCP or Web servers:

```powershell
python -m thesagra.cli sample.db --serve --tls-cert cert.pem --tls-key key.pem
python -m thesagra.cli sample.db --web --tls-cert cert.pem --tls-key key.pem
```
