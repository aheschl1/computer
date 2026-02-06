import asyncio
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
from computer.utils import parse_tool_call, CommandHelpers, clean_discord_message
from asyncio.queues import Queue


logger = logging.getLogger(__name__)
DISCORD_MSG_LIMIT = 1900  # keep margin for formatting


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
        await log_channel.send(
            f"**Tool Call**\n"
            f"Source: {source_message.author.mention}\n"
            f"Channel: {source_message.channel.mention}\n" # type: ignore
            f"Message: {jump_url}\n\n"
            f"**Tool Details**\n{tools_desc}"
        )
    # else:
    #     timeout = None
    # else:
    #     # dm the user the log if no log channel found
    #     try:
    #         await source_message.author.send(
    #             f"**Tool Call Logged**\n"
    #             f"Source: {source_message.author.mention}\n"
    #             f"Channel: {source_message.channel.name}\n"
    #             f"Message: {jump_url}\n\n"
    #             f"**Tool Details**\n{tools_desc}"
    #         )
    
    # # temporary notification in main channel
    # await source_message.channel.send(
    #     ephemeral_message,
    #     delete_after=timeout
    # ) # type: ignore

class ConversationContext:
    def __init__(self, computer: Computer):
        self.computer = computer
        self.user_discord_id = int(os.environ["USER_DISCORD_ID"])
        # holds messages, and index in Conversation when they were added
        self.message_queue: Queue[discord.Message] = Queue()
        # self.stop = LockedInt(0)
        self.su_context = True
        self.protected_mode = True
        self.stop = False
        asyncio.create_task(self.consume())

    async def consume(self):
        """Consume the next message from the queue, blocking if necessary."""
        while True:
            if self.stop:
                # drain on freeze
                while not self.message_queue.empty():
                    await self.message_queue.get()
                self.stop = False
                
            message = await self.message_queue.get()
            if self.stop:
                self.stop = False
                # in this case, the system was waiting for a message
                # there was none
                # then /stop was issued
                # then a message got sent
                # the stop was irrelevant at this point
            
            content = message.content.strip()
            is_superuser = message.author.id == self.user_discord_id or not self.protected_mode            
            
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
                            
                    await self.computer.cycle(content, hook=hook, tools_enabled=is_superuser)
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
        
    async def message(self, message: discord.Message) -> None:
        content = message.content.strip()
        if not content:
            return
        is_superuser = message.author.id == self.user_discord_id
        if not is_superuser and message.channel.type == discord.ChannelType.private:
            updater = MessageUpdater(message.channel)
            await updater.send_new("Access denied.")
            return
        await self.message_queue.put(message)
        
    @staticmethod
    async def recover_context_for_channel(
        channel, 
        computer: Computer,
    ) -> "ConversationContext":
        channel_id = channel.id
        conversation: Conversation | None = ConversationStorage.load(str(channel_id))
        if conversation is None and hasattr(channel, "parent") and channel.parent is not None:
            parent_channel = channel.parent
            parent_id = parent_channel.id
            conversation = ConversationStorage.load(parent_id)
        computer.set_conversation(conversation or Conversation())
        return ConversationContext(computer)
            
class DiscordBot:
    def __init__(self, computer: Computer):
        logger.info("Initializing Discord bot")
        self.computer = computer

        intents = discord.Intents.default()
        intents.message_content = True 

        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)
        self.contexts = {} # channel ID to ConversationContext

        self._register_events()
        self._register_commands()

        # attach setup hook
        self.client.setup_hook = self.setup_hook

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

    async def route(self, channel) -> ConversationContext:
        """Route to the appropriate ConversationContext based on channel ID."""
        if channel.id not in self.contexts:
            context = None
            if channel.type in [
                discord.ChannelType.public_thread, 
                discord.ChannelType.private_thread,
                discord.ChannelType.private,
            ]:
                # persistent context type
                context = await ConversationContext.recover_context_for_channel(channel, self.computer.replicate())
            else:
                # ephemeral context type
                context = ConversationContext(self.computer.replicate())
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
            history_text = CommandHelpers.get_history_text(self.computer.conversation, max_length=1900)
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
            output = f"**System Prompt**\n```\n{system_prompt}\n```"
            cleaned_output = clean_discord_message(output)
            await interaction.response.send_message(cleaned_output, ephemeral=True)

        @self.tree.command(name="tools", description="List available tools")
        async def tools(interaction: discord.Interaction):
            tools_text = CommandHelpers.get_tools_list(self.computer.tool_schemas)
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

    def run(self) -> None:
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            logger.error("DISCORD_TOKEN not set in environment")
            raise RuntimeError("DISCORD_TOKEN not set")

        logger.info("Starting Discord bot client")
        self.client.run(token)

def run(computer: Computer) -> None:
    logger.info("Initializing Discord bot with Computer instance")
    bot = DiscordBot(computer)
    bot.run()
