# moderation

Not a separate worker. Moderation runs inside `media_processor`, which claims
`moderate` jobs alongside `validate_process` ones — see ADR 0009 and
`services/workers/README.md`.

This directory is kept as a boundary marker in case a provider integration later
needs its own scaling profile.
