import os
import datetime
from pathlib import Path
import platform
import subprocess
import multiprocessing
import dotenv

from computer.tasks.task import Task

dotenv.load_dotenv()
dotenv.load_dotenv("secret.env")

# Import after dotenv loads to ensure SKILLS_PATH is available
from computer.skills import load_skills


def try_get_file(path: str, default: str) -> str:
    try:
        with open(path, "r") as file:
            return file.read()
    except FileNotFoundError:
        return default

def get_machine_stats() -> str:
    """Gather information about the machine."""
    stats = []
    
    # Operating System and Kernel
    try:
        stats.append(f"OS: {platform.system()} {platform.release()}")
        stats.append(f"Distribution: {platform.platform()}")
    except:
        pass
    
    # CPU Information
    try:
        cpu_count = multiprocessing.cpu_count()
        stats.append(f"CPU Cores: {cpu_count}")
    except:
        pass
    
    # Check for GPU (NVIDIA)
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], 
                              capture_output=True, text=True, timeout=2)
        if result.returncode == 0 and result.stdout.strip():
            gpu_names = result.stdout.strip().split('\n')
            stats.append(f"GPU: {', '.join(gpu_names)}")
        else:
            stats.append("GPU: None detected (NVIDIA)")
    except:
        stats.append("GPU: None detected")
    
    # Memory information
    try:
        with open('/proc/meminfo', 'r') as f:
            meminfo = f.read()
            for line in meminfo.split('\n'):
                if line.startswith('MemTotal'):
                    mem_kb = int(line.split()[1])
                    mem_gb = round(mem_kb / (1024 ** 2), 1)
                    stats.append(f"RAM: {mem_gb} GB")
                    break
    except:
        pass
    
    return " | ".join(stats) if stats else "Unable to gather machine stats"

class Config:
    
    DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
    
    @staticmethod
    def cache_path() -> Path:
        path = os.getenv("CACHE_PATH", "./cache")
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        return p
    
    @staticmethod
    def user() -> str:
        return os.getenv("USER_NAME", "User")
    
    @staticmethod
    def get_model() -> str:
        return os.getenv("MODEL", "Qwen3-Next-80B-A3B-Instruct-UD-Q4_K_XL")
    
    @staticmethod
    def get_endpoint() -> str:
        return os.getenv("ENDPOINT", "http://10.8.0.15:8080/v1")
    
    @staticmethod
    def get_api_key() -> str:
        return os.getenv("API_KEY", "none")
    
    @staticmethod
    def get_system_prompt() -> str:
        p = os.getenv("SYSTEM_PROMPT", try_get_file(os.getenv("SYSTEM_PROMPT_FILE", "SYSTEM.txt"), Config.DEFAULT_SYSTEM_PROMPT))
        p = p.replace("{{DATE}}", datetime.datetime.now().strftime("%Y-%m-%d"))
        p = p.replace("{{USER_NAME}}", os.getenv("USER_NAME", "User"))
        p = p.replace("{{MACHINE_STATS}}", get_machine_stats())
        p = p.replace("{{SKILLS}}", Config.get_skills_info())
        p = p.replace("{{SKILLS_PATH}}", os.getenv("SKILLS_PATH", "skills"))
        return p
    
    @staticmethod
    def get_task_system_prompt(task: Task, results: str) -> str:
        prompt = Config.get_system_prompt()
        prompt += f"\n\n You also are used for executing scheduled tasks. That is how this conversation was started.\
        The task that is being executed: \
        Name: {task.name} \
        Description: {task.description()} \
        Frequency of task: {task.schema.periodicity()} \
        The task output the following results: {results} \
        Speak directly to the user about the results."
        return prompt
    
    @staticmethod
    def get_skills_info() -> str:
        """Format skills information for the system prompt."""
        skills = load_skills()
        if not skills:
            return "No skills available."
        
        skills_info = []
        for skill in skills:
            skill_md_path = skill.path / "SKILL.md"
            skills_info.append(f"- {skill.name}: {skill.description} (Load: {skill_md_path})")
        
        return "\n".join(skills_info)
    
    @staticmethod
    def get_task_forum_id() -> int:
        return int(os.getenv("TASK_FORUM_ID", "0"))
    
    @staticmethod
    def get_google_credentials_path() -> str:
        return os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")