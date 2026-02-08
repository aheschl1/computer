import asyncio
import copy
from json import loads
import logging
from openai import OpenAI, APIError, APIConnectionError, APITimeoutError
from pydantic import BaseModel
from computer.config import Config
from typing import Any, Awaitable, Callable, Dict, Tuple
from computer.conversation import Conversation
from computer.tools.tool import Tool
from computer.utils import parse_tool_call
import httpx

logger = logging.getLogger(__name__)

type CycleHook = Callable[[
    str,                    # delta
    str,                    # content up to now  
    dict[int, dict],        # full tool calls so far
    bool,                   # completed current stream
    bool,                   # completed full cycle (may have multiple streams)
    bool                    # error occurred (if true, content may be error message)
], Awaitable[bool]]         # returns False to stop

type ApprovalHook = Callable[[
    str,                    # message to display
    float                   # timeout in seconds
], Awaitable[bool]]         # returns True if approved, False if denied

class Computer:
    def __init__(
        self, 
        tools: list[Tool] = [],
        max_cycles: int = 50,
        timeout: float = 120.0,
        conversation: Conversation | None = None,
        temperature: float = 1.0,
        approval_hook: ApprovalHook | None = None,
    ):
        logger.info(f"Initializing Computer with {len(tools)} tools, max_cycles={max_cycles}, timeout={timeout}s")
        self.client = OpenAI(
            base_url=Config.get_endpoint(),
            api_key=Config.get_api_key(),
            timeout=timeout,
        )
        self.model = Config.get_model()
        logger.info(f"Using model: {self.model} at endpoint: {Config.get_endpoint()}")
        
        self.root_conversation = copy.deepcopy(conversation) if conversation else Conversation()
        self.conversation = conversation or Conversation()
        self.timeout = timeout
        self.tools = tools
        self.tool_schemas = [tool.openai_tool for tool in tools]
        self.tools_by_name = {tool.name: tool for tool in tools}
        self.temperature = temperature
        self.approval_hook = approval_hook
        
        self.max_cycles = max_cycles
        self.abort_signal = False
    
    def replicate(self) -> "Computer":
        logger.info("Replicating Computer instance")
        return Computer(
            tools=self.tools,
            max_cycles=self.max_cycles,
            timeout=self.timeout,
            conversation=copy.deepcopy(self.root_conversation),
            approval_hook=self.approval_hook,
        )
    
    def set_conversation(self, conversation: Conversation):
        logger.info("Setting new conversation")
        self.conversation = conversation
    
    async def handle_tools(self, tool_calls: dict[int, dict]) -> dict[int, dict]:
        logger.info(f"Handling {len(tool_calls)} tool call(s)")
        results = {}
        for index, call in tool_calls.items():
            tool_name = call.get("name", "unknown")
            logger.debug(f"Executing tool: {tool_name}")
            result = await execute_tool_call(call, self.tools_by_name, self.approval_hook)
            results[index] = {"result": result}
            logger.debug(f"Tool {tool_name} completed with result length: {len(str(result))}")
        return results

    @property
    def history(self) -> list[dict]:
        return self.conversation.history
    
    def stop_cycling(self) -> None:
        logger.info("Abort signal set for current cycle")
        self.abort_signal = True
    
    async def cycle(
        self, 
        prompt: str | None, 
        hook: CycleHook, 
        depth: int = 0, 
        tools_enabled: bool = True,
        # # these args are for eliminating a chunk of context. imagine message a comes. it starts being handled. message b comes nefore the response.
        # # message bs response should not include message a's response as context.
        # conversation_branch: int = -1, # we can work with only up to ith message in conversation. non inclusive index
        # conversation_merge: int = -1,  # the context merges back at this message index. inclusive index
    ) -> None:
            
        if depth >= self.max_cycles:
            logger.warning(f"Maximum recursion depth ({self.max_cycles}) reached at depth {depth}")
            error_msg = f"Maximum recursion depth ({self.max_cycles}) reached. Stopping to prevent infinite loop."
            await hook("", error_msg, {}, True, True, True)
            return
        
        if self.abort_signal:
            self.abort_signal = False
            if depth > 0: # if the abortion is true but level is 0, then the abortion came when there was no cycle running
                logger.info("Cycle aborted by abort signal")
                error_msg = "Agent loop aborted by user."
                self.conversation.add_message("system", "Your work was paused by the user. Continue if the user wants.")
                await hook("", error_msg, {}, True, True, True)
                return
        # if conversation_branch >= 0 and conversation_merge >= 0:
        #     if conversation_branch >= conversation_merge:
        #         logger.error("Invalid conversation branch/merge indices")
        #         error_msg = "Invalid conversation branch/merge indices. Stopping cycle."
        #         await hook("", error_msg, {}, True, True, True)
        #         return
        
        if prompt:
            logger.debug(f"Starting cycle at depth {depth} with prompt: {prompt[:100]}...")
            self.conversation.add_message("user", prompt)
            # if conversation_branch >= 0:
            #     # because we add the new message, we are responsible for including it
            #     conversation_branch += 1
        else:
            logger.debug(f"Continuing cycle at depth {depth} (tool response processing)")
        
        try:
            logger.debug(f"Creating chat completion stream for model {self.model}")
            history = self.history
            # print(history)
            # if conversation_branch >= 0:
            #     history = history[:conversation_branch]
            # if conversation_merge >= 0:
            #     history += self.conversation.history[conversation_merge:]
            stream = await self.call_model(
                model=self.model,
                messages=history, # type: ignore
                stream=True,
                tools=self.tool_schemas, # type: ignore
                temperature=self.temperature,
            ) # type: ignore
            
            # Process the incoming stream and collect the final assistant text and any tool calls
            logger.debug("Processing response stream")
            response_content, full_tool_calls = await process_stream(stream, hook)
            logger.debug(f"Stream processed: content_length={len(response_content)}, tool_calls={len(full_tool_calls)}")
        except (APIConnectionError, APITimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout) as e:
            logger.error(f"Network error during API call: {str(e)}")
            error_msg = f"Network error: {str(e)}\nStopping cycle."
            await hook("", error_msg, {}, True, True, True)
            return
        except APIError as e:
            logger.error(f"API error during call: {str(e)}")
            error_msg = f"API error: {str(e)}\nStopping cycle."
            await hook("", error_msg, {}, True, True, True)
            return
        except Exception as e:
            logger.exception(f"Unexpected error during cycle: {str(e)}")
            error_msg = f"Unexpected error: {str(e)}\nStopping cycle."
            await hook("", error_msg, {}, True, True, True)
            return
        
        self.handle_assistant_msg(response_content, full_tool_calls)
        
        if full_tool_calls:
            print(full_tool_calls)
            if not tools_enabled:
                logger.warning("Tool calls received but tools are disabled. Skipping execution.")
                self.conversation.add_message(
                    "system",
                    "Tool execution is currently disabled."
                )
            else:
                tool_results: dict[int, dict] = await self.handle_tools(full_tool_calls)
                for idx, tool_result in tool_results.items():
                    self.conversation.add_message(
                        "tool",
                        str(tool_result["result"]),
                        tool_call_id=full_tool_calls[idx]["id"],
                    )
        
        cycle_again = full_tool_calls != {}
        await hook(
            "", 
            response_content, 
            full_tool_calls, 
            True,
            not cycle_again,
            False
        )
        if cycle_again:
            # if conversation_branch >= 0:
            #     # we need to set a merge if it does not exist
            #     if conversation_merge < 0:
            #         conversation_merge = len(self.conversation.history) - 1
                
            await self.cycle(None, hook, depth + 1, tools_enabled)
    
    
    def handle_assistant_msg(self, response_content: str, full_tool_calls: Dict[int, dict]):
        """Construct the assistant message dict including tool_calls when present.
        """
        tool_calls = None
        if full_tool_calls:
            tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in full_tool_calls.values()
            ]
        self.conversation.add_message(
            "assistant", 
            response_content,
            tool_calls=tool_calls
        )
    
    async def call_model(self, *args, **kwargs):
        return await asyncio.to_thread(
            self.client.chat.completions.create,
            *args,
            **kwargs,
        )
    
    def __repr__(self) -> str:
        return f"<Computer model={self.model} tools={len(self.tools)} history_msgs={len(self.conversation)}>"
            

async def process_stream(stream: Any, hook: CycleHook) -> Tuple[str, Dict[int, dict]]:
    """Consume a streaming chat response and collect full assistant text and tool calls.

    Args:
        stream: An iterable/iterator of streaming chunks from the client.
        hook: A callback hook called with (new_content, full_content, done).

    Returns:
        A tuple (response_content, full_tool_calls) where response_content is the
        accumulated assistant text and full_tool_calls is a dict mapping tool-call
        indices to reconstructed call info (id, name, arguments).
    """
    response_content = ""
    full_tool_calls: Dict[int, dict] = {}

    for chunk in stream:
        # preserve original structure: chunks have choices[0].delta
        delta = chunk.choices[0].delta

        content = getattr(delta, "content", None)
        if content:
            # accumulate text and report incremental content to the hook
            response_content += content
            if await hook(content, response_content, full_tool_calls, False, False, False) is False:
                break

        tool_calls = getattr(delta, "tool_calls", None)
        if tool_calls:
            for tc_delta in tool_calls:
                index = tc_delta.index
                if index not in full_tool_calls:
                    full_tool_calls[index] = {
                        "id": tc_delta.id,
                        "name": tc_delta.function.name,
                        "arguments": "",
                    }

                args = getattr(tc_delta.function, "arguments", None)
                if args:
                    full_tool_calls[index]["arguments"] += args
    return response_content, full_tool_calls

async def execute_tool_call(
    tool_call: dict,
    tools_by_name: Dict[str, Tool],
    approval_hook: ApprovalHook | None
) -> str:
    """Parse and execute a tool call, returning the result or error message.
    
    Args:
        tool_call: Dict containing 'name' and 'arguments' (JSON string)
        tools_by_name: Mapping of tool names to Tool instances
        approval_hook: Approval hook for user confirmation
        
    Returns:
        The tool execution result as a string, or an error message.
    """
    tool_name = tool_call.get("name", "unknown")
    logger.info(f"Executing tool call: {tool_name}")
    
    tool, tool_input, error = parse_tool_call(tool_call, tools_by_name)
    
    if error:
        logger.error(f"Tool call parse error for {tool_name}: {error}")
        return error
    
    try:
        assert tool is not None and tool_input is not None
        logger.debug(f"Tool {tool_name} input: {tool_input}")
        result = await tool.execute(tool_input, approval_hook)
        logger.info(f"Tool {tool_name} executed successfully, result length: {len(str(result))}")
        return result
    except Exception as e:
        logger.exception(f"Error executing tool {tool_name}: {str(e)}")
        return f"Error executing tool: {str(e)}"
