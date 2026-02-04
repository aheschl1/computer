import subprocess
from typing import Any
from pydantic import BaseModel, Field

from computer.config import Config
from computer.tools.tool import Tool, tool


class AdminTooling(BaseModel):
    """
    Tool implmented to provide access to tasks normally requiring sudo.
    Hints:
    - help : List available admin commands.
    - vpn help: List available VPN commands.
    - vpn <command> help: Get help for a specific vpn command.
    - Source code at ~/Documents/administrator/src/main.rs can be catted for more details.
    """
    command: str = Field(..., description="The admin command to execute.")

@tool(AdminTooling)
def execute_command(tool_input: AdminTooling) -> str:
    """
    Execute the ExecuteCommand tool with the given input.

    Args:
        tool_input (ExecuteCommand): The input parameters for the ExecuteCommand tool.

    Returns:
        str: The result of the ExecuteCommand tool execution.
    """
    subprocess_result = subprocess.run(
        f"admin {tool_input.command}",
        shell=True,
        capture_output=True,
        text=True
    )
    if subprocess_result.returncode != 0:
        return f"Error: {subprocess_result.stderr.strip()}"
    return subprocess_result.stdout.strip()