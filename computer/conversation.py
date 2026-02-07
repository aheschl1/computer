import json
from discord import datetime
from typing_extensions import Literal

from computer.config import Config
import hashlib
import aiofiles


class Conversation:
    def __init__(self, system_messages: list[str] | None = None):
        self._history: list[dict[str, str]] = []
        self.system_messages = system_messages or [Config.get_system_prompt()]
        self._mask: int | None = None
        for msg in self.system_messages:
            self.add_message("system", msg)
    
    def add_message(
        self, 
        role: Literal["system", "user", "assistant", "tool"], 
        content: str,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
    ):
        m = {"role": role, "content": content}
        if tool_calls is not None:
            m["tool_calls"] = tool_calls # type: ignore
        if tool_call_id is not None:
            m["tool_call_id"] = tool_call_id
        self._history.append(m)
        # if mask exists, we want to shift it to account for the new message. this will NEVER be excluded
        # so, we increment the mask by 1 to account for the new message, which will be included in the history.
        if self._mask is not None:
            self._mask += 1

    @property
    def history(self) -> list[dict[str, str]]:
        if self._mask is not None:
            return self._history[:len(self.system_messages) + self._mask]
        return self._history
    
    def clear_history(self):
        self._history = [msg for msg in self._history if msg["role"] == "system"]

    def mask(self, n: int):
        """
        masking makes it such that we only expose n messages, other than the system prompt, to the model. 
        does not eliminate from serialization.
        """
        self._mask = n
        
    def serialize(self) -> dict:
        return {
            "time": datetime.now().isoformat(),
            "history": self._history,
        }
    
    @staticmethod
    def deserialize(data: dict):
        conv = Conversation(system_messages=[])
        conv._history = data.get("history", [])
        return conv
    
    def __len__(self) -> int:
        return len(self.history)
    
    def __iter__(self):
        return iter(self.history)
    

def hash(tag: str) -> str:
    return hashlib.sha256(tag.encode()).hexdigest()

class ConversationStorage:
    @staticmethod
    def serialize(conversation: Conversation) -> dict:
        return conversation.serialize()
    
    @staticmethod
    def deserialize(data: dict) -> Conversation:
        return Conversation.deserialize(data)
    
    @staticmethod
    async def save(conversation: Conversation, tag: str) -> None:
        if not isinstance(tag, str):
            tag = str(tag)
        filename = hash(tag) + ".json"
        file = Config.cache_path() / filename
        async with aiofiles.open(file, "w") as f:
            await f.write(json.dumps(conversation.serialize()))
            
    @staticmethod
    def load(tag: str) -> Conversation | None:
        if not isinstance(tag, str):
            tag = str(tag)
        filename = hash(tag) + ".json"
        try:
            file = Config.cache_path() / filename
            with open(file, "r") as f:
                data = json.load(f)
                return Conversation.deserialize(data)
        except FileNotFoundError:
            return None