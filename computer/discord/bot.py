import asyncio
import datetime
import os
import time
import random
import yaml
import logging
import discord
from discord import app_commands

from pydantic import BaseModel

from computer.config import Config
from computer.conversation import Conversation, ConversationStorage
from computer.model import Computer
from computer.tasks.task import Task, TaskParams
from computer.utils import discover_tasks, discover_tools, parse_tool_call, CommandHelpers, clean_discord_message
from asyncio.queues import Queue
# from multiprocessing import Process
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)
DISCORD_MSG_LIMIT = 1900  # keep margin for formatting
# im not AI, I just need these for legit reasons 👍😊
THUMBS_UP = "👍"
THUMBS_DOWN = "👎"
# APPROVAL_REQUESTS = "ExecuteSudoCommand"

class MessageUpdater:
    """Abstraction for updating Discord messages, automatically splitting when content is too long."""
    
    def __init__(self, channel, initial_message: discord.Message | None = None):
        self.channel = channel
        self.messages: list[discord.Message] = [initial_message] if initial_message else []
        self.current_index = 0
        self._finalized = False
    
    async def _ensure_message_at_index(self, index: int) -> discord.Message:
        """Ensure a message exists at the given index, creating if necessary."""
        while len(self.messages) <= index:
            # Need to create a new message
            new_msg = await self.channel.send("...")
            self.messages.append(new_msg)
        return self.messages[index]
    
    def _split_content(self, content: str) -> list[str]:
        """Split content into chunks that fit within Discord's message limit."""
        if len(content) <= DISCORD_MSG_LIMIT:
            return [content]
        
        chunks = []
        remaining = content
        
        while remaining:
            if len(remaining) <= DISCORD_MSG_LIMIT:
                chunks.append(remaining)
                break
            
            # Find the best split point
            split_pos = remaining.rfind('\n\n', 0, DISCORD_MSG_LIMIT)
            if split_pos == -1:
                # Try single newline
                split_pos = remaining.rfind('\n', 0, DISCORD_MSG_LIMIT)
            if split_pos == -1:
                # Try space
                split_pos = remaining.rfind(' ', 0, DISCORD_MSG_LIMIT)
            if split_pos == -1:
                # No good split point, hard cut
                split_pos = DISCORD_MSG_LIMIT
            
            chunk = remaining[:split_pos]
            chunks.append(chunk)
            remaining = remaining[split_pos:].lstrip('\n ')
        
        return chunks
        
    async def update(self, content: str) -> bool:
        """Update with new content, splitting into multiple messages if needed.
        
        Returns:
            True if update succeeded, False otherwise
        """
        if self._finalized:
            logger.warning("Attempted to update a finalized MessageUpdater")
            return False
        
        if not content:
            content = "..."
        
        chunks = self._split_content(content)
        
        try:
            for i, chunk in enumerate(chunks):
                msg = await self._ensure_message_at_index(i)
                await msg.edit(content=chunk)
            
            self.current_index = len(chunks) - 1
            return True
        except discord.NotFound:
            logger.error("Message not found during update")
            return False
        except discord.HTTPException as e:
            logger.error(f"Discord HTTP error during update: {e}")
            return False
    
    async def finalize(self, content: str) -> None:
        """Final update with complete content, handling splits and cleanup."""
        if self._finalized:
            logger.warning("MessageUpdater already finalized, skipping")
            return
        
        await self.update(content)
        
        # Delete any extra messages beyond what we used
        while len(self.messages) > self.current_index + 1:
            extra_msg = self.messages.pop()
            try:
                await extra_msg.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException as e:
                logger.error(f"Error deleting extra message: {e}")
        
        self._finalized = True
    
    async def send_new(self, content: str) -> discord.Message:
        """Send a new standalone message (for errors, etc)."""
        if not content:
            content = "..."
        
        chunks = self._split_content(content)
        last_msg = None
        
        for chunk in chunks:
            last_msg = await self.channel.send(chunk)
        
        assert last_msg is not None
        return last_msg


def feedback_message() -> str:
    return random.choice([
        "Computer is pondering...",
        "Computer is considering...",
        "Computer is computing...",
        "Computer is contemplating...",
        "Computer is doing computer stuff...",
        "Computer says 'hmmmm...'",
    ])
    
def non_su_message() -> str:
    return random.choice([
        "Imposter... (tools disabled)",
        "Non-superuser... (tools disabled)"
    ])

def pydantic_pretty_print(obj: BaseModel) -> str:
    return yaml.dump(
        obj.model_dump(),
        sort_keys=False,
        indent=2,
    )


# return a desc, and list of names of tools called, for logging purposes
def tool_description(tools: dict[int, dict], computer: Computer) -> tuple[str, set[str]]:
    descriptions: list[str] = []

    for _, tool in tools.items():
        tool, tool_args, error = parse_tool_call(
            tool,
            computer.tools_by_name
        )

        if error is None:
            assert tool and tool_args
            descriptions.append(
                f"**{tool.name}**\n"
                f"```yaml\n{pydantic_pretty_print(tool_args)}```"
            )

    names = {tool["name"] for tool in tools.values() if "name" in tool}
    
    return "\n".join(descriptions), names

def get_log_channel(guild: discord.Guild | None) -> discord.TextChannel | None:
    if guild is None:
        return None
    
    return discord.utils.get(
        guild.text_channels,
        name="logs"
    )

async def log_tool_call(source_message: discord.Message, ephemeral_message: str, tools_desc: str, timeout: float = 5.0):
    log_channel = get_log_channel(source_message.guild)

    # jump link to original message
    jump_url = source_message.jump_url

    # send log entry
    if log_channel:
        log_message = (
            f"**Tool Call**\n"
            f"Source: {source_message.author.mention}\n"
            f"Channel: {source_message.channel.mention}\n" # type: ignore
            f"Message: {jump_url}\n\n"
            f"**Tool Details**\n{tools_desc}"
        )
        # Use MessageUpdater to handle splitting into multiple messages if needed
        updater = MessageUpdater(log_channel)
        await updater.send_new(log_message)


def is_mention_only_channel(channel: discord.abc.GuildChannel | discord.Thread | discord.DMChannel) -> bool:
    if isinstance(channel, discord.Thread):
        if any(tag.name.lower() == "mention-only" for tag in channel.applied_tags):
            return True

    # threads inherit parent topic if needed
    topic = getattr(channel, "topic", None)

    if topic and "mention-only" in topic.lower():
        return True

    # if thread, optionally check parent
    parent = getattr(channel, "parent", None)
    parent_topic = getattr(parent, "topic", None)
    if parent_topic and "mention-only" in parent_topic.lower():
        return True

    return False

def bot_is_mentioned(client: discord.Client, message: discord.Message) -> bool:
    return client.user is not None and client.user.mentioned_in(message)

class ConversationContext:
    def __init__(self, computer: Computer, client: discord.Client):
        self.computer = computer
        self.user_discord_id = int(os.environ["USER_DISCORD_ID"])
        # holds messages, and index in Conversation when they were added
        self.message_queue: Queue[tuple[discord.Message, bool]] = Queue()
        # self.stop = LockedInt(0)
        self.su_context = True
        self.protected_mode = True
        self.stop = False
        self.client = client
        asyncio.create_task(self.consume())

    async def consume(self):
        """Consume the next message from the queue, blocking if necessary."""
        while True:
            if self.stop:
                # drain on freeze
                while not self.message_queue.empty():
                    await self.message_queue.get()
                self.stop = False
                
            (message, include_content) = await self.message_queue.get()
            # if self.stop:
            # in this case, the system was waiting for a message
            # there was none
            # then /stop was issued
            # then a message got sent
            # the stop was irrelevant at this point
            self.stop = False
            
            content = message.content.strip()
            is_superuser = (message.author.id == self.user_discord_id or message.author.id == self.client.user.id) or not self.protected_mode            
            
            if is_mention_only_channel(message.channel) and include_content: # type: ignore
                if not bot_is_mentioned(self.client, message):
                    logger.debug(f"Message in mention-only channel {message.channel} ignored because bot was not mentioned")
                    # in this case, throw on the conversation still
                    self.computer.conversation.add_message("user", clean_discord_message(content, user=self.client.user))
                    await ConversationStorage.save(
                        self.computer.conversation,
                        str(message.channel.id)
                    )
                    continue
            
            if is_superuser:
                seed = f"*{feedback_message()}*"
            else:
                seed = f"*{non_su_message()}*"
            
            response_msg = await message.reply(seed)

            updater = MessageUpdater(message.channel, response_msg)
            last_update_time = 0.0

            async def stream_complete(
                full_content: str,
                tool_calls: dict[int, dict],
            ) -> None:
                nonlocal updater

                # Build final content
                final_content = full_content or ""
                
                if tool_calls:
                    logger.debug(f"Stream complete with {len(tool_calls)} tool calls")
                    tools_desc, names = tool_description(tool_calls, self.computer)
                    
                    # Prepend tool descriptions to content
                    final_content = f"*[{len(tool_calls)} Tools Called ({', '.join(names)})]*\n\n{final_content}"
                    # asyncio.create_task(message.channel.send(f"**Tool Details**\n{tools_desc}", delete_after=5))
                    await log_tool_call(
                        source_message=message,
                        ephemeral_message=f"**Tool Call**\n{tools_desc}",
                        tools_desc=tools_desc,
                        timeout=3
                    )
                # Finalize with the combined content (or "*Done*" if empty)
                await updater.finalize(final_content or "*Done*")

            # note: each cycle gets one message
            
            async def hook(
                _: str,
                full_content: str,
                tool_calls: dict[int, dict],
                done_stream: bool,
                done_cycle: bool,
                error: bool
            ) -> bool:
                """Hook to handle streaming updates from the computer."""
                nonlocal last_update_time, updater

                if done_stream:
                    await stream_complete(full_content, tool_calls)
                    if not done_cycle:
                        # Create new updater for next cycle
                        new_msg = await updater.send_new(f"*{feedback_message()}*")
                        updater = MessageUpdater(message.channel, new_msg)
                
                now = time.time()
                if now - last_update_time > 1.5 and full_content.strip():
                    success = await updater.update(full_content)
                    if not success:
                        return False
                    last_update_time = now

                return not self.stop # allow hook to signal abortion

            try:
                # type
                async with message.channel.typing():
                    logger.info(f"Processing message from {message.author}: {content[:100]}...")
                    if not is_superuser:
                        logger.warning(f"Message from non-superuser {message.author}")
                    
                    switched_su_mode = self.su_context != is_superuser
                    self.su_context = is_superuser
                    if not is_superuser and switched_su_mode:
                        name = message.author.name
                        self.computer.conversation.add_message(
                            "system",
                            f"Now speaking to {name}. Not the user. Protect the {Config.user()}. Be careful. Tools are disabled until {Config.user()} returns.",
                        )
                    if is_superuser and switched_su_mode:
                        name = message.author.name
                        self.computer.conversation.add_message(
                            "system",
                            f"Now speaking to {Config.user()}. Full tool access restored. Return to normal operation.",
                        )
                            
                    await self.computer.cycle(content if include_content else None, hook=hook, tools_enabled=is_superuser)
                await ConversationStorage.save(
                    self.computer.conversation,
                    str(message.channel.id)
                )
                logger.info(f"Message processing completed for user {message.author}")
            except Exception as exc:
                logger.exception(f"Error processing message from {message.author}: {exc}")
                error_msg = f"Nooooo: (Server Error) {exc}"
                cleaned_error = clean_discord_message(error_msg)
                error_updater = MessageUpdater(message.channel)
                await error_updater.send_new(cleaned_error)
    
    async def abort(self) -> None:
        """Abort the current operation."""
        # if not self.message_queue.empty():
        self.stop = True
        self.computer.stop_cycling() # stops cycling
        
    async def message(self, message: discord.Message, exclude: bool = False) -> None:
        content = message.content.strip()
        if not content:
            return
        is_superuser = (message.author.id == self.user_discord_id) or (message.author.id == self.client.user.id)
        if not is_superuser and message.channel.type == discord.ChannelType.private:
            updater = MessageUpdater(message.channel)
            await updater.send_new("Access denied.")
            return
        await self.message_queue.put((message, not exclude))
        
    @staticmethod
    async def recover_context_for_channel(
        channel, 
        computer: Computer,
        client: discord.Client,
        conversation: Conversation | None = None
    ) -> "ConversationContext":
        channel_id = channel.id
        final_conversation: Conversation | None = conversation or ConversationStorage.load(str(channel_id))
        if final_conversation is None and hasattr(channel, "parent") and channel.parent is not None:
            parent_channel = channel.parent
            parent_id = parent_channel.id
            final_conversation = ConversationStorage.load(parent_id)
        computer.set_conversation(final_conversation or Conversation())
        return ConversationContext(computer, client)
            
class DiscordBot:
    def __init__(self, computer: Computer):
        logger.info("Initializing Discord bot")
        self.computer = computer
        self.user_discord_id = int(os.environ["USER_DISCORD_ID"])

        intents = discord.Intents.default()
        intents.message_content = True 
        intents.reactions = True  # Enable reaction events

        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)
        self.contexts = {} # channel ID to ConversationContext

        self._register_events()
        self._register_commands()

        # attach setup hook
        self.client.setup_hook = self.setup_hook
        
        # Register approval hook with the computer
        self.computer.approval_hook = self.create_approval_hook()
    
    def create_approval_hook(self):
        """Create an approval hook that sends DMs and waits for reactions."""
        async def approval_hook(message: str, timeout: float) -> bool:
            """Send approval request to user via DM and wait for reaction.
            
            Args:
                message: The message to display to the user
                timeout: Timeout in seconds (max 3 minutes)
                
            Returns:
                True if approved (thumbs up reaction), False otherwise
            """
            try:
                # Get the user
                user = await self.client.fetch_user(self.user_discord_id)
                if not user:
                    logger.error("Could not fetch user for approval request")
                    return False
                
                # Send DM
                approval_message = (
                    f"**Approval Required**\n\n{message}\n\n"
                    f"React with thumbs up to approve or anything else to deny.\n"
                    f"Timeout: {int(timeout)} seconds"
                )
                # Ensure message doesn't exceed Discord limit
                cleaned_approval = clean_discord_message(approval_message)
                approval_msg = await user.send(cleaned_approval)
                
                # Add reaction options
                await approval_msg.add_reaction(THUMBS_UP)
                await approval_msg.add_reaction(THUMBS_DOWN)
                
                # Wait for reaction
                def check(payload: discord.RawReactionActionEvent):
                    return (
                        payload.user_id == self.user_discord_id and
                        payload.message_id == approval_msg.id and
                        str(payload.emoji) in [THUMBS_UP, THUMBS_DOWN]
                    )
                    
                try:
                    payload = await self.client.wait_for(
                        "raw_reaction_add",
                        timeout=timeout,
                        check=check
                    )
                    approved = str(payload.emoji) == THUMBS_UP
                    result_msg = "Approved" if approved else "Denied"
                    await approval_msg.edit(content=f"{approval_msg.content}\n\n{result_msg}")
                    
                    logger.info(f"Approval request {'approved' if approved else 'denied'} by user")
                    return approved
                    
                except asyncio.TimeoutError:
                    await approval_msg.edit(content=f"{approval_msg.content}\n\n**Timeout - Request Denied**")
                    logger.warning("Approval request timed out")
                    return False
                    
            except discord.Forbidden:
                logger.error("Cannot send DM to user (privacy settings or bot blocked)")
                return False
            except Exception as e:
                logger.exception(f"Error in approval hook: {e}")
                return False
        
        return approval_hook

    async def setup_hook(self) -> None:
        """Register slash commands."""
        logger.info("Setting up Discord bot slash commands")
        dev_guild = os.getenv("DEV_GUILD_ID")

        if dev_guild:
            logger.info(f"Syncing commands to dev guild: {dev_guild}")
            guild = discord.Object(id=int(dev_guild))
            
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            logger.info("Syncing commands globally")
            await self.tree.sync()
        logger.info("Slash commands synced successfully")
        print("Slash commands synced.")

    def _register_events(self) -> None:
        @self.client.event
        async def on_ready():
            logger.info(f"Discord bot logged in as {self.client.user}")
            print(f"Logged in as {self.client.user}")

        @self.client.event
        async def on_message(message: discord.Message):
            await self.handle_message(message)

    async def route(self, channel, conversation: Conversation | None = None) -> ConversationContext:
        """Route to the appropriate ConversationContext based on channel ID."""
        if channel.id not in self.contexts:
            context = None
            if channel.type in [
                discord.ChannelType.public_thread,
                discord.ChannelType.private_thread,
                discord.ChannelType.private,
            ]:
                # persistent context type
                context = await ConversationContext.recover_context_for_channel(channel, self.computer.replicate(), self.client, conversation)
            else:
                # ephemeral context type
                computer = self.computer.replicate()
                if conversation:
                    computer.set_conversation(conversation)
                context = ConversationContext(computer, self.client)
            self.contexts[channel.id] = context
        return self.contexts[channel.id]
    
    async def handle_message(self, message: discord.Message) -> None:
        if message.author == self.client.user:
            return
        if message.type == discord.MessageType.thread_created:
            return
        
        context = await self.route(message.channel)
        await context.message(message)

    def _register_commands(self) -> None:
        @self.tree.command(name="ping",description="Make sure it's up",)
        async def ping(interaction: discord.Interaction):
            await interaction.response.send_message("Pong")

        @self.tree.command(name="history", description="Show conversation history")
        async def history(interaction: discord.Interaction):
            logger.info(f"History command invoked by {interaction.user}")
            # Account for wrapper text: "**Conversation History**\n```\n" (30) + "\n```" (4) = ~34 chars
            history_text = CommandHelpers.get_history_text(self.computer.conversation, max_length=1960)
            output = f"**Conversation History**\n```\n{history_text}\n```"
            cleaned_output = clean_discord_message(output)
            await interaction.response.send_message(cleaned_output, ephemeral=True)

        @self.tree.command(name="clear", description="Clear conversation history (keeps system prompts)")
        async def clear(interaction: discord.Interaction):
            logger.info(f"Clear command invoked by {interaction.user}")
            context = await self.route(interaction.channel)
            context.computer.conversation.clear_history()
            await interaction.response.send_message("History cleared (system prompts retained).", ephemeral=False)

        @self.tree.command(name="system", description="Show current system prompt")
        async def system(interaction: discord.Interaction):
            system_prompt = CommandHelpers.get_system_prompt()
            # Account for wrapper text: "**System Prompt**\n```\n" (25) + "\n```" (4) = ~29 chars
            max_prompt_length = 1970
            if len(system_prompt) > max_prompt_length:
                system_prompt = system_prompt[:max_prompt_length] + "..."
            output = f"**System Prompt**\n```\n{system_prompt}\n```"
            cleaned_output = clean_discord_message(output)
            await interaction.response.send_message(cleaned_output, ephemeral=True)

        @self.tree.command(name="tools", description="List available tools")
        async def tools(interaction: discord.Interaction):
            tools_text = CommandHelpers.get_tools_list(self.computer.tool_schemas)
            # Account for wrapper text: "**Available Tools**\n" (~20 chars)
            max_tools_length = 1980
            if len(tools_text) > max_tools_length:
                tools_text = tools_text[:max_tools_length] + "..."
            output = f"**Available Tools**\n{tools_text}"
            cleaned_output = clean_discord_message(output)
            await interaction.response.send_message(cleaned_output, ephemeral=True)

        @self.tree.command(name="abort", description="Stop the current operation")
        async def abort(interaction: discord.Interaction):
            # route to the active channel, trigger an abort
            context = await self.route(interaction.channel)
            await context.abort()
            await interaction.response.send_message(
                "Stop signal sent to model. Context will be maintained.", 
                ephemeral=False
            )
        
        @self.tree.command(name="toggle_protected", description="Toggle protected mode (for testing, use with caution)")
        async def toggle_protected(interaction: discord.Interaction):
            if interaction.user.id != int(os.environ["USER_DISCORD_ID"]):
                await interaction.response.send_message(
                    "You do not have permission to use this command.",
                    ephemeral=True
                )
                return
            # toggle su_context for this channel
            context = await self.route(interaction.channel)
            context.computer.conversation.clear_history()
            
            context.protected_mode = not context.protected_mode
            context.su_context = True
            
            mode = "Protected" if context.protected_mode else "Not protected"
            await interaction.response.send_message(
                f"Context mode toggled. Current mode: {mode}",
                ephemeral=False
            )
            await interaction.channel.send("History cleared (system prompts retained).") # type: ignore
        
        @self.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            error_msg = clean_discord_message(str(error))
            await interaction.response.send_message(
                error_msg,
                ephemeral=True,
            )

    async def run(self) -> None:
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            logger.error("DISCORD_TOKEN not set in environment")
            raise RuntimeError("DISCORD_TOKEN not set")

        logger.info("Starting Discord bot client")
        await self.client.start(token)


async def prepare_tasks(bot: DiscordBot):
        
    def build_trigger[T: TaskParams](task: Task[T]):
        # Create thread in forum channel
        async def trigger():
            task_forum_id = Config.get_task_forum_id()
            if task_forum_id == 0:
                logger.warning(f"TASK_FORUM_ID not configured, skipping task: {task.schema.__name__}")
                return
            
            try:
                forum_channel = bot.client.get_channel(task_forum_id)
                if forum_channel is None:
                    forum_channel = await bot.client.fetch_channel(task_forum_id)
                
                if not isinstance(forum_channel, discord.ForumChannel):
                    logger.error(f"Channel {task_forum_id} is not a forum channel")
                    return
                
                now = datetime.datetime.now()
                thread_name = f"{task.schema.__name__} - {now.strftime('%Y-%m-%d %H:%M')}"
                
                logger.info(f"Triggering scheduled task: {task.schema.__name__} in thread {thread_name}")
                
                task_params = task.schema(now)
                
                # Create a new thread in the forum
                initial_message = f"Scheduled task triggered: {task.schema.__name__}"
                thread = await forum_channel.create_thread(
                    name=thread_name,
                    content=initial_message
                )
                
                # Get the message that was created with the thread
                message = thread.message
                
                response = await task.execute(task_params)
                conversation = Conversation(
                    system_messages=[Config.get_task_system_prompt(task, response)],
                )
                context = await bot.route(thread.thread, conversation)
                await context.message(message, exclude=True)
                
            except Exception as e:
                logger.exception(f"Error triggering task {task.schema.__name__}: {e}")
            
        return trigger
    
    tasks = discover_tasks()
    
    scheduler = AsyncIOScheduler()
    for task in tasks:
        # Parse the cron string (format: minute hour day month day_of_week)
        cron_parts = task.schema.periodicity().split()
        if len(cron_parts) == 5:
            minute, hour, day, month, day_of_week = cron_parts
            scheduler.add_job(
                build_trigger(task), 
                trigger="cron",
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week
            )
        else:
            logger.warning(f"Invalid cron format for task {task.name}: {task.schema.periodicity()}")
    scheduler.start()
    logger.info(f"Scheduler started with {len(tasks)} tasks")
    
async def run(computer: Computer, enable_tasks: bool = True) -> None:
    logger.info("Initializing Discord bot with Computer instance")
    bot = DiscordBot(computer)
    if enable_tasks:
        await prepare_tasks(bot)
    else:
        logger.info("Task scheduling disabled (--notasks flag)")
    await bot.run()
