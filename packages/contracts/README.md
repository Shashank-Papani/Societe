# Contracts

OpenAPI is **generated** from the FastAPI application.

```bash
make openapi          # write packages/contracts/openapi/openapi.json
make openapi-check    # CI drift detection
```

Do not hand-edit `openapi.json`. Change the API, regenerate, and commit.
