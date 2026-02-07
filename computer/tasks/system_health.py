import asyncio
import subprocess
from anyio import Path
from computer.model import Computer
from computer.skills import load_skill_by_name
from computer.tasks.task import TaskParams, task
from computer.tools.system import ExecuteCommand

class SystemHealthTask(TaskParams):
    """
    Periodic check of system health. If any issues are detected, report. Otherwise, report that the system is healthy. 
    """
    @staticmethod
    def periodicity() -> str:
        # every day at 7 am, and at 7 pm
        return "0 7,19 * * *"

@task(SystemHealthTask)
async def run_health_check(_input: SystemHealthTask):
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