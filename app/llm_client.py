import os
import logging
import re
from typing import List
from openai import AsyncOpenAI

# --- Setup Logging ---
logger = logging.getLogger(__name__)

# --- Configuration ---
llm_host = os.getenv("LLM_BASE_URL", "http://localhost")
llm_port = os.getenv("LLM_BASE_PORT", "11434")
llm_api_base_url = f"{llm_host.rstrip('/')}:{llm_port}/v1"
MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3")

SYSTEM_PROMPT = """
You are an expert programmer tasked with writing a git commit message.
Analyze the provided context and git diff to generate ONLY the commit message subject line.
Follow the Conventional Commits specification (e.g., 'feat: ...', 'fix: ...', 'chore: ...', 'docs: ...').
The subject line should be concise, imperative (e.g., 'Add feature', not 'Added feature'), and ideally under 72 characters.
Do not include backticks, markdown formatting, or the phrase 'commit message:' in your output. Just provide the raw subject line.
Focus on *what* the change achieves and *why*.
"""

logger.info(f"Configuring LLM client:")
logger.info(f"  API Base URL: {llm_api_base_url}")
logger.info(f"  Model: {MODEL_NAME}")

# --- Initialize Async OpenAI Client ---
try:
    client = AsyncOpenAI(
        base_url=llm_api_base_url,
        api_key="ollama", # required by library, not checked by Ollama
        timeout=45.0,
    )
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}", exc_info=True)
    client = None

async def generate_commit_message_with_context(
    diff_text: str,
    branch_name: str,
    changed_files: List[str],
    author_name: str,
    existing_message: str
) -> str:
    """
    Calls the Ollama API to generate a commit message using the diff and context.
    """
    if not client:
        logger.error("LLM client is not initialized. Cannot generate commit message.")
        raise ConnectionError("LLM client failed to initialize.")

    prompt_lines = [
        "Generate a Conventional Commit message subject line based on the following context and git diff."
    ]

    # Context Section
    prompt_lines.append("\n# Context:")
    prompt_lines.append(f"- Branch: {branch_name}")

    # Attempt to extract a ticket ID (e.g., JIRA-123, TKT-456)
    # This pattern looks for 1 or more uppercase letters, a hyphen, and 1 or more digits.
    match = re.search(r'([A-Z]+-\d+)', branch_name, re.IGNORECASE)
    if match:
        ticket_id = match.group(1).upper()
        prompt_lines.append(f"- Potential Ticket ID from branch: {ticket_id} (If relevant, the commit body should reference this, e.g., 'Refs {ticket_id}', but DO NOT include it in the subject line itself unless essential).")

    prompt_lines.append(f"- Author: {author_name}")

    if changed_files:
        prompt_lines.append("- Changed Files:")
        limit = 10
        for f in changed_files[:limit]:
            prompt_lines.append(f"  - {f}")
        if len(changed_files) > limit:
            prompt_lines.append(f"  - ... ({len(changed_files) - limit} more)")

    if existing_message and not existing_message.isspace():
        if "Merge pull request #" in existing_message or "Merge branch " in existing_message:
             prompt_lines.append(f"- Note: The existing message ('{existing_message.splitlines()[0]}...') seems like a default merge message. Generate a new message based *only* on the diff and other context.")
        else:
            prompt_lines.append(f"- Existing Message Draft: '{existing_message.splitlines()[0]}' (Analyze the diff and context. Either refine this draft or generate a completely new subject line if this draft is inadequate or inaccurate.)")

    prompt_lines.append("\n# Git Diff:")
    prompt_lines.append("```diff")
    max_diff_len = 15000
    truncated_diff = (diff_text[:max_diff_len] + '\n... [TRUNCATED]') if len(diff_text) > max_diff_len else diff_text
    prompt_lines.append(truncated_diff)
    prompt_lines.append("```")
    prompt_lines.append("\nGenerate the single-line commit message subject NOW:")

    user_prompt = "\n".join(prompt_lines)

    try:
        logger.debug(f"Sending request to Ollama model '{MODEL_NAME}'. User prompt length: {len(user_prompt)}")

        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=100,
            stream=False,
            # stop=["\n"] # Optional: Force stop after the first line if model tends to be verbose
        )
        message = response.choices[0].message.content.strip()
        logger.debug(f"Raw response from Ollama: '{message}'")

        # --- Post-processing ---
        # Remove potential quotation marks or markdown code blocks
        message = re.sub(r'^["\']', '', message)
        message = re.sub(r'["\']$', '', message)
        message = message.strip('` \n')
        # Take only the first line if the model generated more
        message = message.splitlines()[0] if message else ""


        if not message:
            logger.warning("Model '{MODEL_NAME}' returned an empty message.")
            return "chore: Automatic generation failed"

        logger.info(f"Generated commit message: '{message}'")
        return message

    except Exception as e:
        logger.error(
            f"Error calling LLM (model: {MODEL_NAME}, URL: {llm_api_base_url}): {e}",
            exc_info=True
        )
        raise ConnectionError(f"Failed to communicate with LLM service at {llm_api_base_url}") from e