from __future__ import annotations

import pytest

from app.core.auth.cognito_provider import CognitoIdentityProvider
from app.core.config import Settings
from app.core.errors import AppError


def _settings(**overrides: object) -> Settings:
    base = {
        "app_env": "test",
        "auth_provider": "cognito",
        "jwt_secret": "test-secret-not-for-production-0123456789abcdef",
        "cursor_hmac_secret": "test-cursor-hmac-secret-0123456789abcdef01234567",
        "cognito_region": "us-west-2",
        "cognito_user_pool_id": "us-west-2_Example",
        "cognito_app_client_id": "exampleclientid",
        "cognito_accept_id_tokens": False,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_rejects_refresh_and_unknown_token_use(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CognitoIdentityProvider(_settings())

    def fake_header(_token: str) -> dict[str, str]:
        return {"kid": "abc", "alg": "RS256"}

    def fake_claims(_token: str) -> dict[str, str]:
        return {"token_use": "refresh", "sub": "x"}

    monkeypatch.setattr("app.core.auth.cognito_provider.jwt.get_unverified_header", fake_header)
    monkeypatch.setattr("app.core.auth.cognito_provider.jwt.get_unverified_claims", fake_claims)

    with pytest.raises(AppError) as exc:
        await provider.verify_token("tok")
    assert exc.value.code == "UNAUTHORIZED"
    assert "Refresh" in exc.value.message

    def fake_unknown(_token: str) -> dict[str, str]:
        return {"token_use": "something", "sub": "x"}

    monkeypatch.setattr("app.core.auth.cognito_provider.jwt.get_unverified_claims", fake_unknown)
    with pytest.raises(AppError):
        await provider.verify_token("tok")


@pytest.mark.asyncio
async def test_rejects_id_token_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CognitoIdentityProvider(_settings(cognito_accept_id_tokens=False))

    monkeypatch.setattr(
        "app.core.auth.cognito_provider.jwt.get_unverified_header",
        lambda _t: {"kid": "abc", "alg": "RS256"},
    )
    monkeypatch.setattr(
        "app.core.auth.cognito_provider.jwt.get_unverified_claims",
        lambda _t: {"token_use": "id", "sub": "x"},
    )
    with pytest.raises(AppError) as exc:
        await provider.verify_token("tok")
    assert "ID tokens" in exc.value.message


def test_access_vs_id_claim_rules_documented_in_provider() -> None:
    """Guard: access uses client_id; id uses aud — not both on the same path."""
    import inspect

    source = inspect.getsource(CognitoIdentityProvider.verify_token)
    assert 'token_use == "access"' in source
    assert "client_id" in source
    assert 'token_use == "id"' in source
    assert "aud" in source
