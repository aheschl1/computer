import os
import datetime
from pathlib import Path
import dotenv

dotenv.load_dotenv()
dotenv.load_dotenv("secret.env")

def try_get_file(path: str, default: str) -> str:
    try:
        with open(path, "r") as file:
            return file.read()
    except FileNotFoundError:
        return default

class Config:
    
    DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
    DEFAULT_CORE = "You are a helpful assistant."
    
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
    def core_path() -> str:
        return os.getenv("CORE_FILE", "CORE.txt")
    
    @staticmethod
    def get_core() -> str:
        p = os.getenv("CORE", try_get_file(Config.core_path(), Config.DEFAULT_CORE))
        p = p.replace("{{CORE_PATH}}", Config.core_path())
        p = p.replace("{{USER_NAME}}", os.getenv("USER_NAME", "User"))
        p = p.replace("{{DATE}}", datetime.datetime.now().strftime("%Y-%m-%d"))
        return p

    @staticmethod
    def get_system_prompt() -> str:
        p = os.getenv("SYSTEM_PROMPT", try_get_file(os.getenv("SYSTEM_PROMPT_FILE", "SYSTEM.txt"), Config.DEFAULT_SYSTEM_PROMPT))
        p = p.replace("{{DATE}}", datetime.datetime.now().strftime("%Y-%m-%d"))
        p = p.replace("{{USER_NAME}}", os.getenv("USER_NAME", "User"))
        p = p.replace("{{CORE_PATH}}", Config.core_path())
        return p