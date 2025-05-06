import os
import logging
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .models import DiffInput, CommitMessageOutput
from .llm_client import generate_commit_message_with_context, MODEL_NAME

API_SECRET_KEY = os.getenv("API_SECRET_KEY")
DEFAULT_RATE_LIMIT = os.getenv("RATE_LIMIT", "10/minute")

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Basic Security Check ---
if not API_SECRET_KEY:
    logger.error("FATAL: API_SECRET_KEY environment variable not set.")
    raise EnvironmentError("API_SECRET_KEY must be set")

# --- Authentication Dependency ---
bearer_scheme = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """Dependency to verify the provided bearer token."""
    if not API_SECRET_KEY:
         raise HTTPException(
             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
             detail="Server configuration error: API token not set.",
         )

    if not credentials or credentials.scheme != "Bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme. Use Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != API_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True

# Limiter based on the client's remote IP address
limiter = Limiter(key_func=get_remote_address, default_limits=[DEFAULT_RATE_LIMIT])

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Git Commit Message Generator API",
    description=f"Generates commit messages from git commit context using Ollama ({MODEL_NAME}).",
    version="0.2.0", # Incremented version
)

# --- Apply Middleware & Exception Handlers ---
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# --- API Endpoints ---
@app.get("/", tags=["Health Check"])
async def read_root():
    """Simple health check endpoint."""
    return {"status": "ok", "ollama_model": MODEL_NAME}

@app.post(
    "/generate_commit_message",
    response_model=CommitMessageOutput,
    dependencies=[Depends(verify_token)],
    tags=["Commit Generation"]
)

async def generate_commit_message_endpoint(commit_data: DiffInput):
    """
    Receives git diff text and related context (branch, files, author, existing message)
    and returns a generated commit message suggestion.

    Requires Bearer token authentication.
    Rate limited per client IP address.
    """
    # Log received data (be mindful of logging sensitive diff content if necessary)
    logger.info(f"Received request for commit message generation. Branch: '{commit_data.branch_name}', Author: '{commit_data.author_name}', Files changed: {len(commit_data.changed_files)}, Diff length: {len(commit_data.diff_text)}")
    logger.debug(f"Changed Files: {commit_data.changed_files}")
    logger.debug(f"Existing Message: {commit_data.existing_message}")

    if not commit_data.diff_text or commit_data.diff_text.isspace():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="diff_text cannot be empty."
        )

    try:
        # Pass all the received data to the updated core logic function
        commit_message = await generate_commit_message_with_context(
            diff_text=commit_data.diff_text,
            branch_name=commit_data.branch_name,
            changed_files=commit_data.changed_files,
            author_name=commit_data.author_name,
            existing_message=commit_data.existing_message
        )
        logger.info(f"Generated commit message snippet: {commit_message[:100]}...") # Log snippet
        return CommitMessageOutput(commit_message=commit_message)

    except Exception as e:
        logger.error(f"Error during commit message generation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to generate commit message due to an internal server error."
        )