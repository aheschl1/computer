import abc
import asyncio
import datetime
import inspect
from typing import Callable, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from computer.model import ApprovalHook

class TaskParams(abc.ABC):
    
    def __init__(
        self,
        time: datetime.datetime,
    ):
        self.time = time
    
    @staticmethod
    def periodicity() -> str:
        """Determines how often the task should run. Returns a cron string."""
        ...

def task[T: TaskParams](schema: type[T]):
    """Decorator that generates the registered function for a tool."""
    def decorator(func: Callable):
        func.registered = lambda: Task(schema, func)  # type: ignore
        return func
    return decorator

class Task[T: TaskParams]:
    def __init__(
        self,
        schema: Type[T],
        function: Callable,
    ):
        self.schema: Type[T] = schema
        self.function = function
        self.name = schema.__name__
    
    def description(self) -> str:
        """Returns the description of the task, which is the docstring of the function."""
        return self.function.__doc__ or "No description provided."
    
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