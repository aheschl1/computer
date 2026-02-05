import io
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

logger = logging.getLogger(__name__)
DISCORD_MSG_LIMIT = 1900  # keep margin for formatting


class MessageUpdater:
    """Abstraction for updating Discord messages, automatically splitting when content is too long."""
    
    def __init__(self, channel, initial_message: discord.Message):
        self.channel = channel
        self.messages: list[discord.Message] = [initial_message]
        self.current_index = 0
        
    async def update(self, content: str) -> bool:
        """Update with new content, splitting into multiple messages if needed.
        
        Returns:
            True if update succeeded, False otherwise
        """
        if len(content) <= DISCORD_MSG_LIMIT:
            # Simple case: content fits in one message
            try:
                await self.messages[self.current_index].edit(content=content)
                return True
            except discord.NotFound:
                return False
        
        # Content is too long - need to split
        # Find the most recent newline that keeps us under the limit
        split_pos = content.rfind('\n\n', 0, DISCORD_MSG_LIMIT)
        if split_pos == -1:
            # No newline found, split at limit
            split_pos = DISCORD_MSG_LIMIT
        
        first_part = content[:split_pos]
        remaining_part = content[split_pos:].lstrip('\n\n')  # Remove leading newlines from second part
        
        try:
            # Update current message with first part
            await self.messages[self.current_index].edit(content=first_part)
            
            # Check if we need a new message or can update existing one
            if self.current_index + 1 < len(self.messages):
                # We have a next message already, update it
                self.current_index += 1
                await self.messages[self.current_index].edit(content=remaining_part)
            else:
                # Need to create a new message
                new_msg = await self.channel.send(remaining_part)
                self.messages.append(new_msg)
                self.current_index += 1
                
            return True
        except discord.NotFound:
            return False
    
    async def finalize(self, content: str) -> None:
        """Final update with complete content, handling splits as needed."""
        await self.update(content)
        
        # Delete any extra messages beyond what we used
        while len(self.messages) > self.current_index + 1:
            extra_msg = self.messages.pop()
            try:
                await extra_msg.delete()
            except discord.NotFound:
                pass


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


def tool_description(tools: dict[int, dict], computer: Computer) -> str:
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

    return "\n".join(descriptions)

async def send_large_content(channel, content: str, filename: str = "output.txt"):
    if len(content) <= DISCORD_MSG_LIMIT:
        return await channel.send(content)

    buffer = io.BytesIO(content.encode("utf-8"))
    file = discord.File(buffer, filename=filename)
    return await channel.send(file=file)

class ConversationContext:
    def __init__(self, computer: Computer):
        self.computer = computer
        self.user_discord_id = int(os.environ["USER_DISCORD_ID"])
        self.su_context = True

    async def message(self, message: discord.Message) -> None:
        content = message.content.strip()
        if not content:
            return

        response_msg = await message.channel.send(f"*{feedback_message()}*")
        updater = MessageUpdater(message.channel, response_msg)
        last_update_time = 0.0

        async def stream_complete(
            full_content: str,
            tool_calls: dict[int, dict],
        ) -> None:
            nonlocal updater

            if tool_calls:
                logger.debug(f"Stream complete with {len(tool_calls)} tool calls")
                tools_desc = tool_description(tool_calls, self.computer)
                await updater.finalize(tools_desc)
                if full_content.strip():
                    await message.channel.send(full_content)
            else:
                logger.debug("Stream complete with no tool calls")
                await updater.finalize(full_content or "*Done*")

        # note: each cycle gets one message
        
        async def hook(
            _: str,
            full_content: str,
            tool_calls: dict[int, dict],
            done_stream: bool,
            done_cycle: bool,
        ) -> bool:
            """Hook to handle streaming updates from the computer."""
            nonlocal last_update_time, updater

            if done_stream:
                await stream_complete(full_content, tool_calls)
                if not done_cycle:
                    # we consumed the message for this cycle, so send a new one for the next cycle
                    response_msg = await message.channel.send(f"*{feedback_message()}*")
                    updater = MessageUpdater(message.channel, response_msg)
            
            now = time.time()
            if now - last_update_time > 1.5 and full_content.strip():
                success = await updater.update(full_content)
                if not success:
                    return False
                last_update_time = now

            return True

        try:
            # is_superuser = message.author.id == self.user_discord_id
            is_superuser = True
            logger.info(f"Processing message from {message.author}: {content[:100]}...")
            if not is_superuser:
                logger.warning(f"Message from non-superuser {message.author}")
            
            if not is_superuser and message.channel.type == discord.ChannelType.private:
                await message.channel.send("Access denied.")
                return
            
            switched_su_mode = self.su_context != is_superuser
            self.su_context = is_superuser
            if not is_superuser and switched_su_mode:
                name = message.author.name
                await message.channel.send(f"*{non_su_message()}*")
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
            ConversationStorage.save(
                self.computer.conversation,
                str(message.channel.id)
            )
            logger.info(f"Message processing completed for user {message.author}")
        except Exception as exc:
            logger.exception(f"Error processing message from {message.author}: {exc}")
            error_msg = f"Nooooo: (Server Error) {exc}"
            cleaned_error = clean_discord_message(error_msg)
            await message.channel.send(cleaned_error)
        
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
            # await self.tree.sync(guild=guild)
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
            self.computer.conversation.clear_history()
            await interaction.response.send_message("History cleared (system prompts retained).", ephemeral=True)

        @self.tree.command(name="system", description="Show current system prompt")
        async def system(interaction: discord.Interaction):
            system_prompt = CommandHelpers.get_system_prompt()
            output = f"**System Prompt**\n```\n{system_prompt}\n```"
            cleaned_output = clean_discord_message(output)
            await interaction.response.send_message(cleaned_output, ephemeral=True)

        @self.tree.command(name="core", description="Show current core")
        async def core(interaction: discord.Interaction):
            core_content = CommandHelpers.get_core()
            output = f"**Core**\n```\n{core_content}\n```"
            cleaned_output = clean_discord_message(output)
            await interaction.response.send_message(cleaned_output, ephemeral=True)

        @self.tree.command(name="tools", description="List available tools")
        async def tools(interaction: discord.Interaction):
            tools_text = CommandHelpers.get_tools_list(self.computer.tool_schemas)
            output = f"**Available Tools**\n{tools_text}"
            cleaned_output = clean_discord_message(output)
            await interaction.response.send_message(cleaned_output, ephemeral=True)

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
