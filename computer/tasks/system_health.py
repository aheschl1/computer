import asyncio
import subprocess
from anyio import Path
from computer.model import Computer
from computer.skills import load_skill_by_name
from computer.tasks.task import TaskParams, task
from computer.tools.system import ExecuteCommand

class SystemHealthParams(TaskParams):
    """
    Parameters for the SystemHealthTask. This task runs a system health check and reports the results.
    """
    @staticmethod
    def periodicity() -> str:
        return "* * * * *"  # Every minute

@task(SystemHealthParams)
async def run_health_check(_input: SystemHealthParams):
    health_skill = load_skill_by_name("health-check")
    if not health_skill:
        return "Health check skill not found."
    script_path = health_skill.path / "health_check.sh"
    cmd = ExecuteCommand(
        command=f"bash {script_path}",
        timeout=120
    )
    
    try:
        process = await asyncio.create_subprocess_shell(
            cmd.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=cmd.timeout
        )
        
        if process.returncode != 0:
            return f"Error: {stderr.decode().strip()}"
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        return f"Error: Command timed out after {cmd.timeout} seconds"
    except Exception as e:
        return f"Error: {str(e)}"
    return subprocess_result.stdout.strip()