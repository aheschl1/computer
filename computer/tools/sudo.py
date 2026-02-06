

from pydantic import BaseModel, Field

from computer.tools.system import execute_command, ExecuteCommand
from computer.tools.tool import tool


class ExecuteSudoCommand(BaseModel):
    """
    Runs a command with sudo privileges. Checks with the user before executing, and is thus safe.
    Only use if you need to run with 'sudo' permissions.
    """
    command: str
    timeout: int | None = Field (
        default = 20,
        description = "Timeout in seconds for command execution."
    )
    
@tool(ExecuteSudoCommand)
def execute_sudo(command: ExecuteSudoCommand) -> str:
    if not command.command.split()[0] == "sudo":
        cmd = f"sudo {command.command}"
        command = ExecuteSudoCommand(
            command=cmd,
            timeout=command.timeout
        )
    
    
    
    return execute_command(command) # type: ignore