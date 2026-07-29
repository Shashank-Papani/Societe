"""HTTP surface for Phase 8A Stories and official content."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

USER_UPLOADS = "/v1/stories/uploads"
OFFICIAL_STORY = "/v1/venues/{venue_id}/official-stories/uploads"
OFFICIAL_POSTS = "/v1/venues/{venue_id}/official-posts"


def auth_header(client: TestClient) -> dict[str, str]:
    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_phase_eight_routes_are_wired(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        USER_UPLOADS,
        "/v1/story-uploads/{upload_id}/complete",
        "/v1/story-uploads/{upload_id}",
        "/v1/venues/{venue_id}/official-stories/uploads",
        "/v1/official-story-uploads/{upload_id}/complete",
        "/v1/experience/stories",
        "/v1/story-groups/{group_key}",
        "/v1/stories/{story_id}/views",
        "/v1/stories/{story_id}/reports",
        "/v1/stories/{story_id}",
        "/v1/venues/{venue_id}/official-posts",
        "/v1/official-posts/{post_id}",
        "/v1/official-posts/{post_id}/archive",
    ):
        assert path in paths, path


def test_story_contracts_exist_in_openapi(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in (
        "CreateUserStoryUploadRequest",
        "CreateOfficialStoryUploadRequest",
        "CompleteStoryUploadRequest",
        "StoryUploadResponse",
        "StoryGroupSummary",
        "StoryGroupDetail",
        "StorySlide",
        "RecordStoryViewResponse",
        "CreateStoryReportRequest",
        "CreateStoryReportResponse",
        "DeleteStoryResponse",
        "CreateOfficialPostRequest",
        "OfficialPostSummary",
        "OfficialPostDetail",
        "OfficialPostCreateResponse",
    ):
        assert name in schemas, name


def test_story_openapi_never_exposes_object_keys(client: TestClient) -> None:
    body = client.get("/openapi.json").text
    assert "object_key" not in body
    assert "quarantine_object_key" not in body


def test_story_write_routes_require_auth(client: TestClient) -> None:
    venue_id = uuid4()
    story_id = uuid4()
    upload_id = uuid4()
    unauthenticated = (
        client.post(
            USER_UPLOADS,
            json={
                "venue_id": str(venue_id),
                "device_id": str(uuid4()),
                "media_type": "image",
                "mime_type": "image/jpeg",
                "byte_size": 1000,
                "attribution_mode": "attributed",
            },
            headers={"Idempotency-Key": str(uuid4())},
        ),
        client.post(
            f"/v1/story-uploads/{upload_id}/complete",
            json={"device_id": str(uuid4())},
            headers={"Idempotency-Key": str(uuid4())},
        ),
        client.get("/v1/experience/stories"),
        client.post(f"/v1/stories/{story_id}/views"),
        client.post(
            f"/v1/stories/{story_id}/reports",
            json={"reason": "spam"},
            headers={"Idempotency-Key": str(uuid4())},
        ),
        client.delete(f"/v1/stories/{story_id}"),
        client.post(
            OFFICIAL_STORY.format(venue_id=venue_id),
            json={"media_type": "image", "mime_type": "image/jpeg", "byte_size": 1000},
            headers={"Idempotency-Key": str(uuid4())},
        ),
        client.post(
            OFFICIAL_POSTS.format(venue_id=venue_id),
            json={"post_type": "announcement", "body": "Hello"},
            headers={"Idempotency-Key": str(uuid4())},
        ),
    )
    for response in unauthenticated:
        assert response.status_code == 401, response.text


def test_user_story_upload_requires_idempotency_key(client: TestClient) -> None:
    response = client.post(
        USER_UPLOADS,
        json={
            "venue_id": str(uuid4()),
            "device_id": str(uuid4()),
            "media_type": "image",
            "mime_type": "image/jpeg",
            "byte_size": 1000,
            "attribution_mode": "attributed",
        },
        headers=auth_header(client),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
