import pytest
import pytest_asyncio # Required for async fixtures
from unittest.mock import AsyncMock, patch, MagicMock # AsyncMock for async methods

# Assuming your llm_client.py file is in the app directory
# This import should now work correctly when running pytest from the root
from app.llm_client import generate_commit_message_with_context, client as llm_client_instance

# --- Test Data ---
SAMPLE_DIFF = """
diff --git a/README.md b/README.md
index e69de29..7f5a3d5 100644
--- a/README.md
+++ b/README.md
@@ -0,0 +1,3 @@
+# Project Title
+
+A brief description.
"""
SAMPLE_BRANCH = "feature/JIRA-123-add-readme"
SAMPLE_FILES = ["README.md"]
SAMPLE_AUTHOR = "Test User"
SAMPLE_EXISTING_MSG = "Initial commit"
EXPECTED_LLM_RESPONSE = "feat: Add initial README file"
FALLBACK_MESSAGE = "chore: Automatic generation failed"

# --- Fixtures ---

@pytest_asyncio.fixture(autouse=True)
def mock_openai_client(monkeypatch):
    """
    Automatically mocks the client.chat.completions.create method for all tests.
    Uses monkeypatch to replace the method within the llm_client module.
    """
    # Create an AsyncMock instance to simulate the async 'create' method
    mock_create = AsyncMock()

    # Use monkeypatch to replace the 'create' method on the actual client instance
    # This assumes 'client' is the initialized AsyncOpenAI instance in llm_client.py
    if llm_client_instance: # Only patch if client was initialized successfully
         # We need to patch the 'create' method specifically
         # Path is 'package_name.module_name.client_instance_name.attribute.attribute.method_name'
         # *** THIS IS THE CORRECTED PATH ***
         monkeypatch.setattr("app.llm_client.client.chat.completions.create", mock_create)
    else:
        # If client initialization failed in llm_client.py, we might skip tests
        # or mock the entire client differently depending on desired behavior.
        print("Warning: llm_client.client instance not found or not initialized.")


    # Return the mock object so tests can configure its return value/side effect
    yield mock_create


# --- Test Functions ---

@pytest.mark.asyncio
async def test_generate_commit_message_success(mock_openai_client):
    """
    Tests successful commit message generation.
    """
    # Configure the mock response
    mock_response = MagicMock()
    # Simulate the nested structure: response.choices[0].message.content
    mock_message = MagicMock()
    mock_message.content = EXPECTED_LLM_RESPONSE
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    mock_openai_client.return_value = mock_response

    # Call the function under test
    result = await generate_commit_message_with_context(
        diff_text=SAMPLE_DIFF,
        branch_name=SAMPLE_BRANCH,
        changed_files=SAMPLE_FILES,
        author_name=SAMPLE_AUTHOR,
        existing_message=SAMPLE_EXISTING_MSG
    )

    # Assertions
    assert result == EXPECTED_LLM_RESPONSE
    mock_openai_client.assert_awaited_once() # Check if the mocked method was called

    # Optional: Inspect the call arguments to check prompt construction
    call_args, call_kwargs = mock_openai_client.call_args
    assert "model" in call_kwargs
    assert "messages" in call_kwargs
    messages = call_kwargs["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "# Context:" in messages[1]["content"]
    assert f"- Branch: {SAMPLE_BRANCH}" in messages[1]["content"]
    assert "- Potential Ticket ID from branch: JIRA-123" in messages[1]["content"]
    assert "- Changed Files:" in messages[1]["content"]
    assert f"  - {SAMPLE_FILES[0]}" in messages[1]["content"]
    assert f"- Existing Message Draft: '{SAMPLE_EXISTING_MSG}'" in messages[1]["content"]
    assert "# Git Diff:" in messages[1]["content"]
    assert f"```diff\n{SAMPLE_DIFF}\n```" in messages[1]["content"]


@pytest.mark.asyncio
async def test_generate_commit_message_api_error(mock_openai_client):
    """
    Tests handling of API errors during the call.
    """
    # Configure the mock to raise an exception
    mock_openai_client.side_effect = Exception("Simulated API error")

    # Assert that the expected exception is raised
    with pytest.raises(ConnectionError, match="Failed to communicate with LLM service"):
        await generate_commit_message_with_context(
            diff_text=SAMPLE_DIFF,
            branch_name=SAMPLE_BRANCH,
            changed_files=SAMPLE_FILES,
            author_name=SAMPLE_AUTHOR,
            existing_message=SAMPLE_EXISTING_MSG
        )

    mock_openai_client.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_commit_message_empty_response(mock_openai_client):
    """
    Tests handling of an empty message returned by the LLM.
    """
    # Configure the mock response with empty content
    mock_response = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "  " # Empty or whitespace content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    mock_openai_client.return_value = mock_response

    # Call the function
    result = await generate_commit_message_with_context(
        diff_text=SAMPLE_DIFF,
        branch_name=SAMPLE_BRANCH,
        changed_files=SAMPLE_FILES,
        author_name=SAMPLE_AUTHOR,
        existing_message=SAMPLE_EXISTING_MSG
    )

    # Assert that the fallback message is returned
    assert result == FALLBACK_MESSAGE
    mock_openai_client.assert_awaited_once()

@pytest.mark.asyncio
async def test_generate_commit_message_no_ticket_in_branch(mock_openai_client):
    """
    Tests prompt construction when the branch name doesn't contain a ticket ID.
    """
    # Configure mock response (content doesn't matter for this specific check)
    mock_response = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "fix: Update documentation"
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    mock_openai_client.return_value = mock_response

    branch_no_ticket = "feature/update-docs"

    # Call the function
    await generate_commit_message_with_context(
        diff_text=SAMPLE_DIFF,
        branch_name=branch_no_ticket, # Branch without ticket pattern
        changed_files=SAMPLE_FILES,
        author_name=SAMPLE_AUTHOR,
        existing_message=SAMPLE_EXISTING_MSG
    )

    # Assert call arguments
    mock_openai_client.assert_awaited_once()
    call_args, call_kwargs = mock_openai_client.call_args
    user_prompt = call_kwargs["messages"][1]["content"]
    assert f"- Branch: {branch_no_ticket}" in user_prompt
    # Crucially, assert that the "Potential Ticket ID" line is NOT present
    assert "- Potential Ticket ID from branch:" not in user_prompt


@pytest.mark.asyncio
async def test_generate_commit_message_default_merge_message(mock_openai_client):
    """
    Tests prompt construction when the existing message is a default merge message.
    """
    # Configure mock response
    mock_response = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "refactor: Clean up merged code"
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    mock_openai_client.return_value = mock_response

    default_merge_msg = "Merge pull request #42 from some/branch"

    # Call the function
    await generate_commit_message_with_context(
        diff_text=SAMPLE_DIFF,
        branch_name=SAMPLE_BRANCH,
        changed_files=SAMPLE_FILES,
        author_name=SAMPLE_AUTHOR,
        existing_message=default_merge_msg # Default merge message
    )

    # Assert call arguments
    mock_openai_client.assert_awaited_once()
    call_args, call_kwargs = mock_openai_client.call_args
    user_prompt = call_kwargs["messages"][1]["content"]
    # Assert that the specific note about default merge messages is present
    assert "- Note: The existing message ('Merge pull request #42 from some/branch...') seems like a default merge message." in user_prompt
    # Assert that the "Existing Message Draft" line is NOT present
    assert "- Existing Message Draft:" not in user_prompt

