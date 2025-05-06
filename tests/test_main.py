import pytest
import os
from unittest.mock import patch, AsyncMock

# Use httpx's AsyncClient AND ASGITransport for testing
from httpx import AsyncClient, ASGITransport

# Import the FastAPI app instance and necessary components
# Adjust 'app.main' if your main FastAPI file/app instance is located elsewhere
from app.main import app, API_SECRET_KEY, MODEL_NAME
# Import the *input* model as well to construct valid test data
from app.models import CommitMessageOutput, DiffInput
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler

# --- Test Configuration ---
TEST_API_SECRET_KEY = "test_secret_key_123"
TEST_MODEL_NAME = "test_model"

# --- Sample Test Data for New Fields ---
SAMPLE_DIFF = "diff --git a/file.txt b/file.txt\n--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-hello\n+world"
SAMPLE_BRANCH = "feature/TEST-1-sample-branch"
SAMPLE_FILES = ["file.txt", "another/file.py"]
SAMPLE_AUTHOR = "Test Author"
SAMPLE_EXISTING_MSG = "Previous commit message"
EXPECTED_GENERATED_MSG = "feat: update file.txt based on context"

# --- Pytest Fixture Setup (using monkeypatch for env vars) ---

@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Sets environment variables for the test session."""
    monkeypatch.setenv("API_SECRET_KEY", TEST_API_SECRET_KEY)
    monkeypatch.setenv("OLLAMA_MODEL", TEST_MODEL_NAME)
    # Ensure these are set correctly within the app module context
    monkeypatch.setattr("app.main.API_SECRET_KEY", TEST_API_SECRET_KEY)
    monkeypatch.setattr("app.main.MODEL_NAME", TEST_MODEL_NAME)


# --- Fixtures ---

@pytest.fixture(scope="function")
async def test_client():
    """Creates an httpx AsyncClient configured for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.fixture(autouse=True)
def mock_llm():
    """
    Mocks the generate_commit_message_with_context function.
    Note the updated path to the function.
    """
    # Update the path to the new function name
    with patch("app.main.generate_commit_message_with_context", new_callable=AsyncMock) as mock_func:
        yield mock_func

# --- Helper Function to Create Valid Payload ---
def create_valid_payload(**overrides):
    """Creates a valid JSON payload for the endpoint."""
    payload = {
        "diff_text": SAMPLE_DIFF,
        "branch_name": SAMPLE_BRANCH,
        "changed_files": SAMPLE_FILES,
        "author_name": SAMPLE_AUTHOR,
        "existing_message": SAMPLE_EXISTING_MSG,
    }
    payload.update(overrides)
    return payload

# --- Test Cases ---

@pytest.mark.asyncio
async def test_read_root(test_client: AsyncClient):
    """Tests the health check endpoint."""
    response = await test_client.get("/")
    assert response.status_code == 200
    expected_data = {"status": "ok", "ollama_model": TEST_MODEL_NAME}
    assert response.json() == expected_data

# -- Authentication Tests --
# Use the helper to create a structurally valid payload, even though content doesn't matter here

@pytest.mark.asyncio
async def test_generate_commit_no_auth(test_client: AsyncClient):
    """Tests the commit endpoint without any authentication header."""
    response = await test_client.post("/generate_commit_message", json=create_valid_payload())
    # FastAPI's default for missing security dependency is 403 if auto_error=True (default)
    assert response.status_code == 403
    assert "Not authenticated" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_commit_wrong_scheme(test_client: AsyncClient):
    """Tests the commit endpoint with incorrect auth scheme."""
    response = await test_client.post(
        "/generate_commit_message",
        json=create_valid_payload(),
        headers={"Authorization": f"Basic {TEST_API_SECRET_KEY}"} # Wrong scheme
    )
    assert response.status_code == 403 # HTTPBearer rejects non-Bearer
    assert "Invalid authentication credentials" in response.json()["detail"] # Default message is exactly 'Invalid authentication credentials'

@pytest.mark.asyncio
async def test_generate_commit_wrong_token(test_client: AsyncClient):
    """Tests the commit endpoint with an incorrect token."""
    response = await test_client.post(
        "/generate_commit_message",
        json=create_valid_payload(),
        headers={"Authorization": "Bearer wrong_token"}
    )
    assert response.status_code == 403
    # Detail message comes from our verify_token function
    assert "Invalid or expired token" in response.json()["detail"]
    assert response.headers.get("www-authenticate") == "Bearer"


# -- Commit Generation Logic Tests --

@pytest.mark.asyncio
async def test_generate_commit_success(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests successful commit message generation."""
    # Use the helper to create the payload
    test_payload = create_valid_payload()
    # Set the expected return value from the mocked LLM function
    mock_llm.return_value = EXPECTED_GENERATED_MSG

    response = await test_client.post(
        "/generate_commit_message",
        json=test_payload,
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )

    assert response.status_code == 200
    response_data = CommitMessageOutput(**response.json())
    assert response_data.commit_message == EXPECTED_GENERATED_MSG

    # Assert the mocked function was called with the correct keyword arguments
    mock_llm.assert_awaited_once_with(
        diff_text=test_payload["diff_text"],
        branch_name=test_payload["branch_name"],
        changed_files=test_payload["changed_files"],
        author_name=test_payload["author_name"],
        existing_message=test_payload["existing_message"]
    )

@pytest.mark.asyncio
async def test_generate_commit_empty_diff_text(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests sending an empty diff_text string (handled by endpoint logic)."""
    # Create payload with empty diff_text
    invalid_payload = create_valid_payload(diff_text="   ") # Use whitespace string

    response = await test_client.post(
        "/generate_commit_message",
        json=invalid_payload,
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )
    # Expect 400 Bad Request because the endpoint logic catches empty/whitespace diff_text
    assert response.status_code == 400
    # Check for the specific detail message from the endpoint's HTTPException
    assert "diff_text cannot be empty" in response.json()["detail"]
    mock_llm.assert_not_awaited()

@pytest.mark.asyncio
async def test_generate_commit_missing_required_field(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests sending invalid JSON (missing a required field like 'branch_name')."""
    invalid_payload = create_valid_payload()
    del invalid_payload["branch_name"] # Remove a required field

    response = await test_client.post(
        "/generate_commit_message",
        json=invalid_payload,
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )
    assert response.status_code == 422 # Pydantic validation error
    # Check for validation error related to the missing field
    assert any("branch_name" in error["loc"] and "Field required" in error["msg"] for error in response.json()["detail"])
    mock_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_commit_llm_error(test_client: AsyncClient, mock_llm: AsyncMock):
    """Tests the case where the LLM client function raises an exception."""
    test_payload = create_valid_payload()
    error_instance = ConnectionError("Ollama connection failed")
    # error_message = str(error_instance) # Endpoint now returns generic message

    mock_llm.side_effect = error_instance

    response = await test_client.post(
        "/generate_commit_message",
        json=test_payload,
        headers={"Authorization": f"Bearer {TEST_API_SECRET_KEY}"}
    )

    assert response.status_code == 503 # Service Unavailable
    # Check for the generic error message defined in the endpoint's exception handler
    assert "Failed to generate commit message due to an internal server error" in response.json()["detail"]
    # assert error_message not in response.json()["detail"] # Verify specific error isn't leaked

    # Assert the mocked function was still called with the correct arguments before it raised the error
    mock_llm.assert_awaited_once_with(
        diff_text=test_payload["diff_text"],
        branch_name=test_payload["branch_name"],
        changed_files=test_payload["changed_files"],
        author_name=test_payload["author_name"],
        existing_message=test_payload["existing_message"]
    )

# --- Rate Limiting (Basic Check - No changes needed here) ---

def test_rate_limit_middleware_registered():
    """Checks if the SlowAPIMiddleware is present in the app's user-added middleware stack."""
    found = False
    if hasattr(app, 'user_middleware'):
        found = any(hasattr(m, 'cls') and m.cls == SlowAPIMiddleware for m in app.user_middleware)
    assert found, "SlowAPIMiddleware not found in app.user_middleware stack."


def test_rate_limit_exception_handler_registered():
    """Checks if the RateLimitExceeded handler is registered."""
    assert RateLimitExceeded in app.exception_handlers
    assert app.exception_handlers[RateLimitExceeded] == _rate_limit_exceeded_handler

