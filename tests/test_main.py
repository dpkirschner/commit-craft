import pytest
import os
from unittest.mock import patch, AsyncMock # Use AsyncMock for async functions

# Use httpx's AsyncClient for testing async FastAPI apps
from httpx import AsyncClient

# Import the FastAPI app instance from your main module
# Adjust the import path based on your project structure
# Assuming 'app' is a package in your project root
from app.main import app
from app.models import CommitMessageOutput # For asserting response structure

# --- Test Configuration ---
# Use a fixed secret key for testing
TEST_API_SECRET_KEY = "test_secret_key_123"
# Use a known model name for testing consistency
TEST_MODEL_NAME = "test_model"

# Set environment variables BEFORE the app is imported by pytest fixtures
# Note: Pytest fixtures load modules, so set env vars early
# Alternatively, use pytest-dotenv or monkeypatch fixture in tests.
os.environ["API_SECRET_KEY"] = TEST_API_SECRET_KEY
os.environ["OLLAMA_MODEL"] = TEST_MODEL_NAME # Ensure llm_client sees this too if needed


# --- Fixtures ---

@pytest.fixture(scope="function") # Recreate client for each test function
async def test_client():
    """Creates an httpx AsyncClient for making requests to the app."""
    # Use 'async with' for proper client startup/shutdown
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture(autouse=True) # Apply this mock automatically to all tests
def mock_llm():
    """Mocks the generate_commit_message_from_diff function."""
    # Patch the function *where it's imported and used* in main.py
    # Use AsyncMock because the original function is async
    with patch("app.main.generate_commit_message_from_diff", new_callable=AsyncMock) as mock_func:
        yield mock_func # The test function will receive this mock object if needed


# --- Test Cases ---

@pytest.mark.asyncio
async def test_read_root(test_client: AsyncClient):
    """Tests the health check endpoint."""
    response = await test_client.get("/")
    assert response.status_code == 200
    # Check response body, accounting for model name from env var
    expected_data = {"status": "ok", "ollama_model": TEST_MODEL_NAME}
    assert response.json() == expected_data

# -- Authentication Tests --

@pytest.mark.asyncio
async def test_generate_commit_no_auth(test_client: AsyncClient):
    """Tests the commit endpoint without any authentication."""
    response = await test_client.post("/generate_commit_message", json={"diff_text": "some diff"})
    # Expect 403 Forbidden when HTTPBearer dependency fails without header
    assert response.status_code == 403
    assert "Not authenticated" in response.json()["detail"] # Or check specific detail message

@pytest.mark.asyncio
async def test_generate_commit_wrong_scheme(test_client: AsyncClient):
    """Tests the commit endpoint with incorrect auth scheme."""
    response = await test_client.post(
        "/generate_commit_message",
        json={"diff_text": "some diff"},
        headers={"Authorization": f"Basic {TEST_API_SECRET_KEY}"} # Wrong scheme
    )
    assert response.status_code == 401 # Changed based on code logic
    assert "Invalid authentication scheme" in response.json()["detail"]

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

# -- Commit Generation Logic Tests --

@pytest.mark.asyncio
async def test_generate_commit_success(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests successful commit message generation."""
    mock_diff = "diff --git a/file.txt b/file.txt\n--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-hello\n+world"
    expected_message = "feat: update file.txt"

    # Configure the mock to return a specific value when called
    mock_llm.return_value = expected_message

    response = await test_client.post(
        "/generate_commit_message",
        json={"diff_text": mock_diff},
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"} # Correct token
    )

    assert response.status_code == 200
    # Validate response structure using the Pydantic model if desired
    response_data = CommitMessageOutput(**response.json())
    assert response_data.commit_message == expected_message

    # Assert that the mocked LLM function was called correctly
    mock_llm.assert_awaited_once_with(mock_diff)

@pytest.mark.asyncio
async def test_generate_commit_empty_diff(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests sending an empty diff string."""
    response = await test_client.post(
        "/generate_commit_message",
        json={"diff_text": "  "}, # Empty or whitespace only
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )
    assert response.status_code == 400 # Bad Request
    assert "diff_text cannot be empty" in response.json()["detail"]
    mock_llm.assert_not_awaited() # Ensure LLM func wasn't called

@pytest.mark.asyncio
async def test_generate_commit_missing_diff(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests sending invalid JSON (missing 'diff_text')."""
    response = await test_client.post(
        "/generate_commit_message",
        json={"other_field": "value"}, # Missing 'diff_text'
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )
    # FastAPI handles Pydantic validation errors with 422
    assert response.status_code == 422
    # Check for detail about missing field in the response body if needed
    # assert "diff_text" in response.text
    # assert "field required" in response.text
    mock_llm.assert_not_awaited() # Ensure LLM func wasn't called


@pytest.mark.asyncio
async def test_generate_commit_llm_error(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests the case where the LLM client raises an exception."""
    mock_diff = "valid diff"
    error_message = "Ollama connection failed"

    # Configure the mock to raise an exception when called
    mock_llm.side_effect = ConnectionError(error_message)

    response = await test_client.post(
        "/generate_commit_message",
        json={"diff_text": mock_diff},
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )

    assert response.status_code == 503 # Service Unavailable
    assert f"Failed to generate commit message due to an internal error: {error_message}" in response.json()["detail"]

    # Assert that the mocked LLM function was called
    mock_llm.assert_awaited_once_with(mock_diff)

# --- Rate Limiting (Basic Check) ---
# Fully testing rate limiting state across requests is complex in unit tests.
# These tests primarily ensure that requests *pass* when the middleware is active
# and authentication is correct. We rely on the success tests above for this.
# We can also check if the middleware is registered, though less common.

def test_rate_limit_middleware_registered():
    """Checks if the SlowAPIMiddleware is present in the app's middleware stack."""
    middleware_classes = [m.cls for m in app.middleware]
    assert SlowAPIMiddleware in middleware_classes

def test_rate_limit_exception_handler_registered():
    """Checks if the RateLimitExceeded handler is registered."""
    assert RateLimitExceeded in app.exception_handlers