from pydantic import BaseModel, Field
from typing import List

class DiffInput(BaseModel):
    """Model representing the input data for commit message generation."""
    diff_text: str = Field(..., description="The raw git diff output.")
    branch_name: str = Field(..., description="The name of the branch the commit is on.")
    changed_files: List[str] = Field(..., description="A list of filenames changed in the diff.")
    author_name: str = Field(..., description="The name of the commit author.")
    # The existing message from the commit that triggered the workflow
    existing_message: str = Field(..., description="The existing commit message from the HEAD commit.")

class CommitMessageOutput(BaseModel):
    """Model representing the output containing the generated commit message."""
    commit_message: str