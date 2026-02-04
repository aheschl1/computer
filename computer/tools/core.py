from typing_extensions import Literal
from pydantic import BaseModel, Field

from computer.config import Config
from computer.tools.tool import tool

import subprocess
import tempfile
import os


class UpdateCore(BaseModel):
    """
    Update your core with memories, new traits, or statements you should recall.
    """
    update: str = Field(
        description="The modification to your core."
    )
    update_type: Literal['append', 'diff'] = Field(
        description="The type of update being provided: 'append' to add new content, 'diff' to apply a unified diff.",
        default='append'
    )


def apply_patch(file_path: str, patch_text: str):
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as tf:
        tf.write(patch_text)
        patch_path = tf.name

    try:
        dry_run = subprocess.run(
            ["patch", "--dry-run", file_path, patch_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if dry_run.returncode != 0:
            return f"Error in patch dry run: {dry_run.stderr}"
        
        subprocess.run(
            ["patch", file_path, patch_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    finally:
        os.remove(patch_path)


@tool(UpdateCore)
def update_core(tool_input: UpdateCore) -> str:
    """Update the core with new content."""
    core_document = Config.core_path()

    if tool_input.update_type == 'append':
        with open(core_document, 'a') as f:
            f.write("\n" + tool_input.update + "\n")
        return "Core updated successfully with appended content."

    elif tool_input.update_type == 'diff':
        apply_patch(core_document, tool_input.update)
        return "Core updated successfully with diff applied."

    else:
        return "Error: Unknown update type."
