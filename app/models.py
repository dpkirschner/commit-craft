from pydantic import BaseModel

class DiffInput(BaseModel):
    diff_text: str
    # Optional: add context like repo name, branch?
    # context: dict | None = None

class CommitMessageOutput(BaseModel):
    commit_message: str

    