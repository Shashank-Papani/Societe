# Société API

Phase 0 FastAPI modular monolith skeleton.

Local (outside Compose):

```bash
uv run --directory services/api uvicorn app.main:app --reload --port 8000
```

With Compose, the `api` service is started by `make dev-up`.
