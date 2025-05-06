import os
import logging
from openai import AsyncOpenAI # Use AsyncOpenAI for FastAPI

# --- Setup Logging ---
# It's good practice to use logging instead of print in libraries/modules
logger = logging.getLogger(__name__)

# --- Configuration ---
# Get base URL and port from environment variables
# Default to localhost:11434, common for host network or non-Docker setups.
# For Docker Desktop (Mac/Win), you might need 'http://host.docker.internal' as LLM_BASE_URL
# or run the FastAPI container with --network="host".
llm_host = os.getenv("LLM_BASE_URL", "http://localhost")
llm_port = os.getenv("LLM_BASE_PORT", "11434")

# Construct the full base URL for the OpenAI-compatible endpoint
# Ensure no trailing slash in llm_host before adding port and path
ollama_api_base_url = f"{llm_host.rstrip('/')}:{llm_port}/v1"

MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3") # Default model

SYSTEM_PROMPT = """
You are an expert programmer reviewing code changes.
Analyze the following git diff and generate a concise, informative, and semantic commit message.
Follow the Conventional Commits specification (e.g., 'feat: add user login', 'fix: resolve calculation error', 'chore: update dependencies', 'docs: explain API endpoint').
The message should be a single line, ideally under 72 characters. Do not include backticks or the word 'commit message' in the output.
Focus on *what* the change achieves and *why*, not just *how*.
"""

logger.info(f"Configuring Ollama client:")
logger.info(f"  API Base URL: {ollama_api_base_url}")
logger.info(f"  Model: {MODEL_NAME}")

# --- Initialize Async OpenAI Client ---
# Configure the client to connect to the constructed Ollama endpoint
try:
    client = AsyncOpenAI(
        base_url=ollama_api_base_url,
        api_key="ollama", # required by the library, but Ollama server doesn't check it
        timeout=30.0,     # Set a reasonable timeout (adjust as needed)
    )
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}", exc_info=True)
    # Depending on requirements, you might want to raise a critical error here
    # or handle it gracefully in the calling code (main.py)
    client = None # Ensure client is None if initialization fails

# --- Core Function ---
async def generate_commit_message_from_diff(diff_text: str) -> str:
    """
    Calls the Ollama API to generate a commit message based on the provided diff.
    """
    if not client:
        logger.error("LLM client is not initialized. Cannot generate commit message.")
        raise ConnectionError("LLM client failed to initialize.") # Or return an error message

    user_prompt = f"Generate a commit message for the following diff:\n```diff\n{diff_text}\n```"

    try:
        logger.debug(f"Sending request to Ollama model '{MODEL_NAME}' at {ollama_api_base_url}")
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5, # Adjust for creativity vs predictability
            max_tokens=75,   # Increased slightly for potentially longer conventional commit types like feat(...)
            stream=False,
        )
        message = response.choices[0].message.content.strip()
        logger.debug(f"Received response from Ollama: '{message}'")

        # Basic post-processing
        if message.startswith('"') and message.endswith('"'):
            message = message[1:-1]
        if message.startswith("'") and message.endswith("'"):
            message = message[1:-1]
        if message.startswith("```") and message.endswith("```"):
            message = message.strip("`\n ")

        return message

    except Exception as e:
        logger.error(
            f"Error calling Ollama (model: {MODEL_NAME}, URL: {ollama_api_base_url}): {e}",
            exc_info=True
        )
        raise ConnectionError(f"Failed to communicate with Ollama service at {ollama_api_base_url}") from e