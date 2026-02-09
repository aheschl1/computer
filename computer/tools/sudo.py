

import asyncio
import subprocess
import os
from pydantic import BaseModel, Field
from typing import TYPE_CHECKING, Optional

from computer.tools.tool import tool

if TYPE_CHECKING:
    from computer.model import ApprovalHook


class ExecuteSudoCommand(BaseModel):
    """
    Runs a command with elevated privileges (sudo on Linux, administrator on Windows).
    Checks with the user before executing, and is thus safe.
    Only use if you need to run with elevated permissions.
    """
    command: str
    timeout: Optional[int] = Field(
        default=120,
        description="Timeout in seconds for command execution."
    )

@tool(ExecuteSudoCommand, platform="linux")
async def execute_sudo(command: ExecuteSudoCommand, approval_hook: "ApprovalHook | None" = None) -> str:
    """Execute command with elevated privileges on Linux."""
    # Request approval from user
    if approval_hook:
        approval_message = (
            f"**Sudo Command Approval Request (Linux)**\n\n"
            f"Command: `{command.command}`\n"
            f"Timeout: {command.timeout}s\n\n"
            f"This command requires sudo privileges."
        )
        
        approved = await approval_hook(approval_message, 180.0)
        
        if not approved:
            return "Permission denied: User did not approve sudo command execution."
    else:
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


@tool(ExecuteSudoCommand, platform="windows")
async def execute_sudo(command: ExecuteSudoCommand, approval_hook: "ApprovalHook | None" = None) -> str:
    """Execute command with elevated privileges on Windows."""
    # Request approval from user
    if approval_hook:
        approval_message = (
            f"**Elevated Command Approval Request (Windows)**\n\n"
            f"Command: `{command.command}`\n"
            f"Timeout: {command.timeout}s\n\n"
            f"This command requires administrator privileges."
        )
        
        approved = await approval_hook(approval_message, 180.0)
        
        if not approved:
            return "Permission denied: User did not approve elevated command execution."
    else:
        return "Permission denied: Approval mechanism not available. Cannot execute elevated commands without user confirmation."
    
    # Remove any 'sudo' prefix if present
    cmd = command.command
    if cmd.lower().startswith("sudo "):
        cmd = cmd[5:].strip()
    
    # Escape quotes for PowerShell
    cmd_escaped = cmd.replace('"', '`"').replace("'", "''")
    
    # Use PowerShell to run as administrator
    ps_script = f'Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command \\"{cmd_escaped}; Write-Host \'\'; Write-Host \'Press any key to close...\' -NoNewline; $null = $Host.UI.RawUI.ReadKey(\'NoEcho,IncludeKeyDown\')\\"" -Wait'
    
    process = subprocess.Popen(
        ['powershell', '-NoProfile', '-Command', ps_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    try:
        stdout, stderr = await asyncio.to_thread(process.communicate, timeout=command.timeout)
        
        if process.returncode != 0:
            return f"Error: Command failed with return code {process.returncode}\n{stderr.strip()}"
        
        return stdout.strip()
    except subprocess.TimeoutExpired:
        process.kill()
        return f"Error: Command timed out after {command.timeout} seconds"
