from typing import Callable
from pydantic import BaseModel, Field
import subprocess

from computer.tools.tool import Tool, tool

class ExecuteCommand(BaseModel):
    """
    Execute a command in the (non-root) linux terminal environment.
    """
    command: str = Field (
        description = "Command to execute."
    )
    
    timeout: int | None = Field (
        default = 20,
        description = "Timeout in seconds for command execution."
    )

@tool(ExecuteCommand)
def execute_command(tool_input: ExecuteCommand) -> str:
    """
    Execute the ExecuteCommand tool with the given input.

    Args:
        tool_input (ExecuteCommand): The input parameters for the ExecuteCommand tool.

    Returns:
        str: The result of the ExecuteCommand tool execution.
    """
    if "sudo" in tool_input.command:
        return "Error: 'sudo' commands are not allowed. Please use the ExecuteSudoCommand tool for commands requiring elevated privileges."
    subprocess_result = subprocess.run(
        tool_input.command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=tool_input.timeout
    )
    if subprocess_result.returncode != 0:
        return f"Error: {subprocess_result.stderr.strip()}"
    return subprocess_result.stdout.strip()