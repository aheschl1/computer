

import asyncio
import subprocess
import os
from pydantic import BaseModel, Field
from typing import TYPE_CHECKING

from computer.tools.tool import tool

if TYPE_CHECKING:
    from computer.model import ApprovalHook


class ExecuteSudoCommand(BaseModel):
    """
    Runs a command with sudo privileges. Checks with the user before executing, and is thus safe.
    Only use if you need to run with 'sudo' permissions.
    """
    command: str
    timeout: int | None = Field (
        default = 120,
        description = "Timeout in seconds for command execution."
    )
    
@tool(ExecuteSudoCommand)
async def execute_sudo(command: ExecuteSudoCommand, approval_hook: "ApprovalHook | None" = None) -> str:
    # Request approval from user
    if approval_hook:
        approval_message = (
            f"**Sudo Command Approval Request**\n\n"
            f"Command: `{command.command}`\n"
            f"Timeout: {command.timeout}s\n\n"
            f"This command requires elevated privileges."
        )
        
        # Use 3 minute timeout (180 seconds) for approval
        approved = await approval_hook(approval_message, 180.0)
        
        if not approved:
            return "Permission denied: User did not approve sudo command execution. Consider finding an alternative approach that doesn't require sudo privileges."
    else:
        # Fallback: if no approval hook, deny by default for safety
        return "Permission denied: Approval mechanism not available. Cannot execute sudo commands without user confirmation."
    
    # Get sudo password from environment
    sudo_password = os.getenv("SUDO_PASSWORD")
    if not sudo_password:
        return "Error: SUDO_PASSWORD environment variable not set. Cannot execute sudo commands."
    
    # Remove 'sudo' prefix if present since we'll add it back with -S
    cmd = command.command
    if cmd.startswith("sudo "):
        cmd = cmd[5:].strip()  # Remove "sudo " prefix
    
    # This avoids shell injection and keeps password out of shell history
    process = subprocess.Popen(
        ['sudo', '-S'] + cmd.split(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    try:
        stdout, stderr = await asyncio.to_thread(process.communicate, input=f"{sudo_password}\n", timeout=command.timeout)
        
        if process.returncode != 0:
            # Clean up sudo password prompt from stderr if present
            stderr_clean = stderr.replace("[sudo] password for ", "").strip()
            return f"Error: {stderr_clean}"
        
        return stdout.strip()
    except subprocess.TimeoutExpired:
        process.kill()
        return f"Error: Command timed out after {command.timeout} seconds"