

import asyncio
from collections.abc import Awaitable
import inspect
from typing import Callable, Type, TypeVar
from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)

def tool(schema: type[T]):
    """Decorator that generates the registered function for a tool."""
    def decorator(func: Callable[[T], str]):
        func.registered = lambda: Tool(schema, func)  # type: ignore
        return func
    return decorator

def pydantic_tool(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": model.__name__,
            "description": model.__doc__ or "",
            "parameters": schema,
        },
    }

class Tool[T: BaseModel]:
    def __init__(
        self,
        schema: Type[T],
        function: Callable[[T], Awaitable[str]],
    ):
        self.schema = schema
        self.function = function
        self.openai_tool = pydantic_tool(schema)
        self.name = schema.__name__
    
    async def execute(self, input: T) -> str:
        fn = self.function

        if inspect.iscoroutinefunction(fn):
            return await fn(input)
        result = fn(input)
        if inspect.isawaitable(result):
            return await result

        return result