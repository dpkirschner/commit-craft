#!/bin/sh
# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
MODEL_TO_PULL=${OLLAMA_PULL_MODEL:-llama3} # Default or from environment
HEALTHCHECK_URL="http://localhost:11434" # Server runs on localhost inside the container
MAX_WAIT_SECONDS=60 # Max time to wait for server startup
WAIT_INTERVAL=2     # Time between health checks

echo "Ollama entrypoint script starting..."

# --- Start Ollama Server in Background ---
echo "Starting Ollama server in background..."
/bin/ollama serve &
# Capture the Process ID (PID) of the background server
SERVER_PID=$!
echo "Ollama server started in background with PID $SERVER_PID"

# --- Wait for Server Readiness ---
echo "Waiting for Ollama server at $HEALTHCHECK_URL to become ready..."
SECONDS_WAITED=0
while true; do
    # Use curl to check the health endpoint (root / usually returns 200 OK when ready)
    # -s: silent mode
    # -o /dev/null: discard response body
    # -w '%{http_code}': output only the HTTP status code
    # --fail: return non-zero exit code on server errors (4xx, 5xx)
    # --connect-timeout: max time to connect
    # --max-time: max total time for operation
    # `|| true` prevents the script from exiting if curl fails before server is up
    response_code=$(curl --silent --output /dev/null --write-out "%{http_code}" --fail --connect-timeout 1 --max-time 2 "$HEALTHCHECK_URL" || true)

    if [ "$response_code" = "200" ]; then
        echo "Ollama server is ready (HTTP $response_code)."
        break
    else
        echo "Server not ready yet (HTTP code: '$response_code')... waiting $WAIT_INTERVAL seconds."
        sleep $WAIT_INTERVAL
        SECONDS_WAITED=$((SECONDS_WAITED + WAIT_INTERVAL))

        if [ $SECONDS_WAITED -ge $MAX_WAIT_SECONDS ]; then
            echo "Error: Ollama server did not become ready within $MAX_WAIT_SECONDS seconds."
            # Kill the background server process before exiting
            echo "Killing server process $SERVER_PID..."
            kill $SERVER_PID
            exit 1 # Exit with error
        fi

        # Also check if the background process died unexpectedly
        if ! kill -0 $SERVER_PID > /dev/null 2>&1; then
             echo "Error: Ollama server process $SERVER_PID died unexpectedly during startup wait."
             exit 1 # Exit with error
        fi
    fi
done

# --- Check and Pull Model (Server is now ready) ---
echo "Attempting to pull model '$MODEL_TO_PULL' (will skip if already present)..."
ollama pull "$MODEL_TO_PULL"
echo "Model pull command finished for '$MODEL_TO_PULL'."

# --- Keep Container Running ---
echo "Ollama setup complete. Tailing server process (PID $SERVER_PID) to keep container alive."
# Use 'wait' to keep the script running as long as the background server process lives.
# When the server process exits (e.g., docker stop), 'wait' will finish, and the script will exit.
wait $SERVER_PID

# Check the exit code of the server process (optional)
SERVER_EXIT_CODE=$?
echo "Ollama server process (PID $SERVER_PID) exited with code $SERVER_EXIT_CODE."
exit $SERVER_EXIT_CODE # Exit the container with the same code as the server