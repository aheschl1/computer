from typing import Awaitable, Callable, Dict, Tuple, Any, List, Optional
from json import loads
from pydantic import BaseModel
import importlib
import pkgutil
import json
import logging
from datetime import datetime

from computer.tools.tool import Tool

logger = logging.getLogger(__name__)


def discover_tools() -> List[Tool]:
    """Discover all functions decorated with @tool in computer.tools submodules.
    
    Returns:
        A list of Tool instances from all decorated functions found in the package.
    """
    logger.info("Starting tool discovery")
    import computer.tools as tools_package
    import inspect
    
    registered_tools = []
    
    # Iterate through all submodules in computer.tools
    for _, modname, _ in pkgutil.iter_modules(tools_package.__path__):
        # Skip __pycache__ and other non-module entries
        if modname.startswith('_'):
            continue
            
        try:
            # Import the submodule
            full_module_name = f'computer.tools.{modname}'
            logger.debug(f"Scanning module: {full_module_name}")
            module = importlib.import_module(full_module_name)
            
            # Iterate through all members of the module
            for name, obj in inspect.getmembers(module):
                # Check if it's a function decorated with @tool (has registered attribute)
                if callable(obj) and hasattr(obj, 'registered'):
                    try:
                        tool_instance = obj.registered()  # type: ignore
                        registered_tools.append(tool_instance)
                        logger.info(f"Registered tool: {tool_instance.name} from {modname}")
                    except Exception as e:
                        logger.warning(f"Could not register tool {name} from {modname}: {e}")
                
        except Exception as e:
            # Skip modules that fail to import
            logger.warning(f"Could not load tool module {modname}: {e}")
            continue
    
    logger.info(f"Discovered {len(registered_tools)} tools: {[tool.name for tool in registered_tools]}")
    return registered_tools


def parse_tool_call[T: BaseModel](
    tool_call: dict,
    tools_by_name: Dict[str, Tool]
) -> Tuple[Tool[T] | None, T | None, Optional[str]]:
    """Parse a tool call and return the validated Pydantic object and function.
    
    Args:
        tool_call: Dict containing 'name' and 'arguments' (JSON string)
        tool_models: Mapping of tool names to Pydantic model classes
        tool_commands: Mapping of tool names to callable functions
        
    Returns:
        A tuple of (pydantic_object, function, error_message).
        If successful, returns (object, function, None).
        If failed, returns (None, None, error_message).
    """
    tool_name = tool_call.get("name")
    tool_args_str = tool_call.get("arguments", "{}")
    
    if not tool_name:
        logger.error("Tool call missing name")
        return None, None, "Error: Tool name not provided"
    
    if tool_name not in tools_by_name:
        logger.error(f"Tool '{tool_name}' not found in available tools")
        return None, None, f"Error: Tool '{tool_name}' not found"
    
    try:
        tool = tools_by_name[tool_name]
        tool_model = tool.schema
        tool_args_json = loads(tool_args_str)
        tool_input = tool_model(**tool_args_json)
        
        logger.debug(f"Successfully parsed tool call for '{tool_name}'")
        return tool, tool_input, None
        
    except Exception as e:
        logger.error(f"Error parsing tool call for '{tool_name}': {str(e)}")
        return None, None, f"Error parsing tool call: {str(e)}"


def clean_discord_message(content: str, max_length: int = 2000) -> str:
    """Clean and truncate a message to fit Discord's character limit.
    
    Args:
        content: The message content to clean
        max_length: Maximum allowed length (default 2000 for Discord)
        
    Returns:
        Cleaned message that fits within the limit
    """
    if not content:
        return content
        
    # If content is within limit, return as-is
    if len(content) <= max_length:
        return content
    
    # Check if content is wrapped in code blocks
    if content.startswith("```") and content.endswith("```"):
        # Try to preserve code block formatting
        # Find the language identifier if present
        first_newline = content.find("\n")
        if first_newline > 3:
            header = content[3:first_newline]  # e.g., "yaml", "python", etc.
            footer = "```"
            available = max_length - len(header) - 7  # 3 for opening ```, 1 for \n, 3 for closing ```
            if available > 20:  # Only worth it if we have reasonable space
                truncated = content[first_newline + 1:-3][:available - 3] + "..."
                return f"```{header}\n{truncated}\n```"
        
        # Fallback: simple truncation with code block
        available = max_length - 9  # 6 for ``` at start and end, 3 for ...
        if available > 20:
            truncated = content[3:-3][:available]
            return f"```{truncated}...```"
    
    # Check if content has bold markers at start
    if content.startswith("**") and "\n" in content:
        first_newline = content.find("\n")
        header = content[:first_newline + 1]
        if len(header) < 100:  # Reasonable header length
            available = max_length - len(header) - 3
            if available > 20:
                truncated = content[first_newline + 1:first_newline + 1 + available]
                return f"{header}{truncated}..."
    
    # Simple truncation
    return content[:max_length - 3] + "..."


# Command helper functions that can be reused by CLI and Discord bot
class CommandHelpers:
    """Helper methods for common commands that can be shared across interfaces."""
    
    @staticmethod
    def get_history_text(history: List[dict], max_length: Optional[int] = None) -> str:
        """Format conversation history as text.
        
        Args:
            history: List of message dictionaries
            max_length: Optional maximum length to truncate to
            
        Returns:
            Formatted history string
        """
        if not history:
            return "No conversation history yet."
        
        lines = []
        for i, msg in enumerate(history):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if role == "system":
                preview = content[:100] + "..." if len(content) > 100 else content
                lines.append(f"[{i}] SYSTEM: {preview}")
            elif role == "user":
                preview = content[:100] + "..." if len(content) > 100 else content
                lines.append(f"[{i}] USER: {preview}")
            elif role == "assistant":
                preview = content[:100] + "..." if len(content) > 100 else content
                lines.append(f"[{i}] ASSISTANT: {preview}")
            elif role == "tool":
                tool_id = msg.get("tool_call_id", "")
                preview = content[:80] + "..." if len(content) > 80 else content
                lines.append(f"[{i}] TOOL ({tool_id}): {preview}")
        
        result = "\n".join(lines)
        
        if max_length and len(result) > max_length:
            result = result[:max_length - 3] + "..."
        
        return result
    
    @staticmethod
    def clear_history(history: List[dict]) -> List[dict]:
        """Clear history but keep system prompts.
        
        Args:
            history: Current history list
            
        Returns:
            New history list with only system prompts
        """
        return [msg for msg in history if msg.get("role") == "system"]
    
    @staticmethod
    def save_history(history: List[dict], model: str, filename: str) -> Tuple[bool, str]:
        """Save conversation history to a JSON file.
        
        Args:
            history: History to save
            model: Model name being used
            filename: File path to save to
            
        Returns:
            Tuple of (success, message)
        """
        try:
            with open(filename, "w") as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "model": model,
                    "history": history
                }, f, indent=2)
            return True, f"History saved to {filename}"
        except Exception as e:
            return False, f"Error saving history: {e}"
    
    @staticmethod
    def load_history(filename: str) -> Tuple[Optional[List[dict]], str, str]:
        """Load conversation history from a JSON file.
        
        Args:
            filename: File path to load from
            
        Returns:
            Tuple of (history or None, timestamp, message)
        """
        try:
            with open(filename, "r") as f:
                data = json.load(f)
                history = data.get("history", [])
                timestamp = data.get("timestamp", "unknown")
                return history, timestamp, f"History loaded from {filename} (saved at {timestamp})"
        except FileNotFoundError:
            return None, "", f"File {filename} not found."
        except Exception as e:
            return None, "", f"Error loading history: {e}"
    
    @staticmethod
    def get_system_prompt() -> str:
        """Get the current system prompt.
        
        Returns:
            System prompt text
        """
        from computer.config import Config
        return Config.get_system_prompt()
    
    @staticmethod
    def get_core() -> str:
        """Get the current core content.
        
        Returns:
            Core content text
        """
        from computer.config import Config
        return Config.get_core()
    
    @staticmethod
    def get_tools_list(tool_schemas: List[dict]) -> str:
        """Format available tools as text.
        
        Args:
            tool_schemas: List of tool schema dictionaries
            
        Returns:
            Formatted tools list string
        """
        if not tool_schemas:
            return "No tools registered."
        
        lines = []
        for tool in tool_schemas:
            func = tool.get("function", {})
            name = func.get("name", "unknown")
            desc = func.get("description", "No description")
            lines.append(f"- {name}: {desc}")
        
        return "\n".join(lines)
