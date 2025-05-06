# Commit Message Suggester Workflow

This repository contains a GitHub Actions workflow designed to automatically generate a suggested commit message based on the changes introduced in the latest commit of a push.

## Overview

When code is pushed to any branch *except* `main` or `master`, this workflow triggers. It analyzes the difference (`git diff`) between the most recent commit and its parent commit. This diff is then sent to a configurable external API endpoint, which processes the changes and returns a suggested commit message. The suggested message is then printed to the workflow logs for the developer to review.

This helps in:
*   Maintaining consistent commit message formats.
*   Providing developers with a starting point for writing informative commit messages.
*   Saving time by automating the initial draft of a commit message based on code changes.

## How it Works

The workflow (`.github/workflows/generate_commit_message.yml`) performs the following steps:

1.  **Trigger:** Activates on `push` events to any branch *except* `main` or `master`.
2.  **Permissions:** Sets `contents: read` permission for security.
3.  **Job Condition:** Runs only if there is a `head_commit` in the event payload (standard for push events).
4.  **Harden Runner:** Uses `step-security/harden-runner` to enhance the security of the GitHub Actions runner environment. Egress policy is initially set to `audit` and should be reviewed.
5.  **Checkout Code:** Checks out the repository code using `actions/checkout`. It fetches the last 2 commits (`fetch-depth: 2`) to allow diffing `HEAD` against `HEAD~1`.
6.  **Get Git Diff:**
    *   Checks if the parent commit (`HEAD~1`) exists (to avoid errors on the very first commit).
    *   Runs `git diff HEAD~1 HEAD` to capture the changes introduced by the latest commit.
    *   Handles potential errors during the diff operation.
    *   Skips the process if no diff is found (e.g., empty commit, merge commit without changes).
    *   Stores the diff content in an environment variable (`GIT_DIFF_CONTENT`) if successful.
7.  **Prepare JSON Payload:**
    *   Uses `jq` to create a JSON object containing the captured diff, ensuring proper escaping. The payload format is `{"diff_text": "<git diff output>"}`.
    *   Stores the JSON payload in an environment variable (`JSON_PAYLOAD_CONTENT`).
8.  **Call Commit Message API:**
    *   Sends a POST request to the API endpoint specified in the `COMMIT_API_URL` secret.
    *   Includes the JSON payload in the request body.
    *   Authenticates using a Bearer token provided by the `COMMIT_API_TOKEN` secret.
    *   Handles potential API call errors (using `curl --fail`).
    *   Stores the API response in an environment variable (`API_RESPONSE_CONTENT`).
9.  **Extract and Display Commit Message:**
    *   Parses the JSON response from the API using `jq`.
    *   Extracts the value associated with the `commit_message` key.
    *   Prints the extracted commit message suggestion to the workflow logs.
    *   Includes error handling in case the message cannot be extracted.

## Setup and Configuration

1.  **Workflow File:** Place the `generate_commit_message.yml` file in the `.github/workflows/` directory of your repository.
2.  **API Endpoint:** You need an external API service that:
    *   Accepts POST requests at a specific URL.
    *   Expects a JSON payload like: `{"diff_text": "..."}`.
    *   Requires authentication via an `Authorization: Bearer <token>` header.
    *   Returns a JSON response like: `{"commit_message": "Suggested commit message here"}`.
3.  **GitHub Secrets:** Configure the following secrets in your repository settings (`Settings` > `Secrets and variables` > `Actions`):
    *   `COMMIT_API_URL`: The full URL of your commit message generation API endpoint (e.g., `https://api.example.com/generate`).
    *   `COMMIT_API_TOKEN`: The bearer token required to authenticate with your API.

## Usage

1.  Ensure the workflow file and secrets are correctly configured as described above.
2.  Create a new branch (e.g., `feature/my-new-feature`).
3.  Make code changes and commit them.
4.  Push the branch to GitHub: `git push origin feature/my-new-feature`.
5.  Navigate to the "Actions" tab in your GitHub repository.
6.  Find the workflow run triggered by your push.
7.  Open the `suggest_commit_message` job logs.
8.  Look for the "Extract and Display Commit Message" step to find the suggested commit message printed between the `---` separators.

```log
------------------------------------
Suggested Commit Message:
------------------------------------
feat: Add new login component

Implement the basic structure and styling for the user login form.
------------------------------------
```

## Security

*   **Permissions:** The workflow uses minimal `contents: read` permissions.
*   **Secrets:** Sensitive information like the API URL and token are stored securely as GitHub Actions secrets.
*   **Runner Hardening:** `step-security/harden-runner` is used to mitigate potential risks within the runner environment. It's recommended to review the `egress-policy` and change it from `audit` to `block` once you confirm the necessary outbound connections.
*   **External API:** Ensure the external API endpoint used is secure and trusted.

## Contributing

Feel free to suggest improvements or report issues by opening an issue or pull request in the repository where this workflow resides.