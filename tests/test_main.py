import pytest
import os
from unittest.mock import patch, AsyncMock

# Use httpx's AsyncClient AND ASGIAppTransport for testing
# Requires httpx version that supports ASGI transport (like 0.2x)
from httpx import AsyncClient, ASGITransport # <-- Import ASGITransport

# Import the FastAPI app instance and necessary components
from app.main import app, API_SECRET_KEY, MODEL_NAME
from app.models import CommitMessageOutput
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
# Import the specific handler for the assertion
from slowapi import _rate_limit_exceeded_handler # <-- Import handler

# --- Test Configuration ---
TEST_API_SECRET_KEY = "test_secret_key_123"
TEST_MODEL_NAME = "test_model"

# --- Pytest Fixture Setup (using monkeypatch for env vars) ---

@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Sets environment variables for the test session."""
    monkeypatch.setenv("API_SECRET_KEY", TEST_API_SECRET_KEY)
    monkeypatch.setenv("OLLAMA_MODEL", TEST_MODEL_NAME)
    monkeypatch.setattr("app.main.API_SECRET_KEY", TEST_API_SECRET_KEY)
    monkeypatch.setattr("app.main.MODEL_NAME", TEST_MODEL_NAME)


# --- Fixtures ---

@pytest.fixture(scope="function")
async def test_client():
    """Creates an httpx AsyncClient configured for the FastAPI app."""
    # For httpx versions that support ASGI testing via transport (like 0.28.1):
    # Use ASGITransport pointing to the FastAPI 'app' instance.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.fixture(autouse=True)
def mock_llm():
    """Mocks the generate_commit_message_from_diff function."""
    with patch("app.main.generate_commit_message_from_diff", new_callable=AsyncMock) as mock_func:
        yield mock_func

# --- Test Cases ---
# Calls to test_client.get/post etc. are now async with httpx.AsyncClient

@pytest.mark.asyncio
async def test_read_root(test_client: AsyncClient): # Type hint correct for httpx
    """Tests the health check endpoint."""
    # Use await for httpx.AsyncClient calls
    response = await test_client.get("/")
    assert response.status_code == 200
    expected_data = {"status": "ok", "ollama_model": TEST_MODEL_NAME}
    assert response.json() == expected_data

# -- Authentication Tests --

@pytest.mark.asyncio
async def test_generate_commit_no_auth(test_client: AsyncClient):
    """Tests the commit endpoint without any authentication header."""
    response = await test_client.post("/generate_commit_message", json={"diff_text": "some diff"})
    assert response.status_code == 403
    assert "Not authenticated" in response.json()["detail"]

      
@pytest.mark.asyncio
async def test_generate_commit_wrong_scheme(test_client: AsyncClient):
    """Tests the commit endpoint with incorrect auth scheme."""
    response = await test_client.post(
        "/generate_commit_message",
        json={"diff_text": "some diff"},
        headers={"Authorization": f"Basic {TEST_API_SECRET_KEY}"} # Wrong scheme
    )
    # Expect 403 because HTTPBearer(auto_error=True) rejects non-Bearer schemes
    assert response.status_code == 403
    assert "Invalid authentication credentials" in response.json()["detail"]

@pytest.mark.asyncio
async def test_generate_commit_wrong_token(test_client: AsyncClient):
    """Tests the commit endpoint with an incorrect token."""
    response = await test_client.post(
        "/generate_commit_message",
        json={"diff_text": "some diff"},
        headers={"Authorization": "Bearer wrong_token"}
    )
    assert response.status_code == 403
    assert "Invalid or expired token" in response.json()["detail"]
    assert response.headers.get("www-authenticate") == "Bearer"


# -- Commit Generation Logic Tests --

@pytest.mark.asyncio
async def test_generate_commit_success(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests successful commit message generation."""
    mock_diff = "diff --git a/file.txt b/file.txt\n--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-hello\n+world"
    expected_message = "feat: update file.txt"

    mock_llm.return_value = expected_message

    response = await test_client.post(
        "/generate_commit_message",
        json={"diff_text": mock_diff},
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )

    assert response.status_code == 200
    response_data = CommitMessageOutput(**response.json())
    assert response_data.commit_message == expected_message
    mock_llm.assert_awaited_once_with(mock_diff)

@pytest.mark.asyncio
async def test_generate_commit_empty_diff(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests sending an empty diff string."""
    response = await test_client.post(
        "/generate_commit_message",
        json={"diff_text": "  "},
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )
    assert response.status_code == 400
    assert "diff_text cannot be empty" in response.json()["detail"]
    mock_llm.assert_not_awaited()

@pytest.mark.asyncio
async def test_generate_commit_missing_diff_field(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests sending invalid JSON (missing 'diff_text')."""
    response = await test_client.post(
        "/generate_commit_message",
        json={"other_field": "value"},
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )
    assert response.status_code == 422
    assert any("diff_text" in error["loc"] and "Field required" in error["msg"] for error in response.json()["detail"])
    mock_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_commit_llm_error(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests the case where the LLM client raises an exception."""
    mock_diff = "valid diff"
    error_instance = ConnectionError("Ollama connection failed")
    error_message = str(error_instance)

    mock_llm.side_effect = error_instance

    response = await test_client.post(
        "/generate_commit_message",
        json={"diff_text": mock_diff},
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )

    assert response.status_code == 503
    assert "Failed to generate commit message due to an internal error" in response.json()["detail"]
    assert error_message in response.json()["detail"]
    mock_llm.assert_awaited_once_with(mock_diff)

# --- Rate Limiting (Basic Check) ---

def test_rate_limit_middleware_registered():
    """Checks if the SlowAPIMiddleware is present in the app's user-added middleware stack."""
    # Iterate through app.user_middleware, which contains middleware added via app.add_middleware
    found = False
    if hasattr(app, 'user_middleware'):
        # Middleware added via add_middleware are often wrapped in Middleware objects
        found = any(hasattr(m, 'cls') and m.cls == SlowAPIMiddleware for m in app.user_middleware)

    assert found, "SlowAPIMiddleware not found in app.user_middleware stack."


def test_rate_limit_exception_handler_registered():
    """Checks if the RateLimitExceeded handler is registered."""
    assert RateLimitExceeded in app.exception_handlers
    # Assert the correct handler is registered
    assert app.exception_handlers[RateLimitExceeded] == _rate_limit_exceeded_handler