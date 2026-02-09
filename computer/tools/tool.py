

import asyncio
from collections.abc import Awaitable
import inspect
from typing import Callable, Literal, Optional, Type, TypeVar, TYPE_CHECKING, Union
import openai
from pydantic import BaseModel

if TYPE_CHECKING:
    from computer.model import ApprovalHook

T = TypeVar('T', bound=BaseModel)

def tool(schema: type[T], platform: Optional[Literal["linux", "windows"]] = None):
    """Decorator that generates the registered function for a tool."""
    def decorator(func: Callable):
        func.registered = lambda: Tool(schema, func, platform)  # type: ignore
        return func
    return decorator

class Tool[T: BaseModel]:
    def __init__(
        self,
        schema: Type[T],
        function: Callable,
        platform: Optional[Literal["linux", "windows"]] = None,
    ):
        self.schema = schema
        self.function = function
        self.platform = platform
        self.openai_tool = openai.pydantic_function_tool(schema) 
        self.name = schema.__name__
    
    async def execute(self, input: T, approval_hook: "ApprovalHook | None" = None) -> str:
        fn = self.function
        
        # Check if function accepts approval_hook parameter
        sig = inspect.signature(fn)
        accepts_approval_hook = 'approval_hook' in sig.parameters

        # Build kwargs based on function signature
        kwargs = {}
        if accepts_approval_hook:
            kwargs['approval_hook'] = approval_hook

        # Call the function with appropriate parameters
        if inspect.iscoroutinefunction(fn):
            # Async function - await directly
            return await fn(input, **kwargs)
        else:
            # Sync function - run in thread
            result = await asyncio.to_thread(fn, input, **kwargs)
            
            # Check if result is awaitable (shouldn't be, but handle just in case)
            if inspect.isawaitable(result):
                return await result
            
            return result