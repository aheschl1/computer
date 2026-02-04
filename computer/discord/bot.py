import os
import time
import random
import yaml
import logging
import discord
from discord import app_commands
import dotenv

from pydantic import BaseModel

from computer.model import Computer
from computer.utils import parse_tool_call, CommandHelpers, clean_discord_message

logger = logging.getLogger(__name__)

def feedback_message() -> str:
    return random.choice([
        "Computer is pondering...",
        "Computer is considering...",
        "Computer is computing...",
        "Computer is contemplating...",
        "Computer is doing computer stuff...",
        "Computer says 'hmmmm...'",
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

class DiscordBot:
    def __init__(self, computer: Computer):
        logger.info("Initializing Discord bot")
        self.computer = computer

        intents = discord.Intents.default()
        intents.message_content = True 

        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)

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

    async def handle_message(self, message: discord.Message) -> None:
        if message.author == self.client.user:
            return

        content = message.content.strip()
        if not content:
            return

        logger.info(f"Processing message from {message.author}: {content[:100]}...")
        response_msg = await message.channel.send(f"*{feedback_message()}*")
        last_update_time = 0.0

        async def stream_complete(
            full_content: str,
            tool_calls: dict[int, dict],
        ) -> None:
            nonlocal response_msg

            if tool_calls:
                logger.debug(f"Stream complete with {len(tool_calls)} tool calls")
                tools_desc = tool_description(tool_calls, self.computer)
                cleaned_tools = clean_discord_message(tools_desc)
                await response_msg.edit(content=cleaned_tools)
                if full_content.strip():
                    cleaned_content = clean_discord_message(full_content)
                    await message.channel.send(cleaned_content)
            else:
                logger.debug("Stream complete with no tool calls")
                cleaned_content = clean_discord_message(full_content or "*Done*")
                await response_msg.edit(content=cleaned_content)

        # note: each cycle gets one message
        
        async def hook(
            _: str,
            full_content: str,
            tool_calls: dict[int, dict],
            done_stream: bool,
            done_cycle: bool,
        ) -> bool:
            """Hook to handle streaming updates from the computer."""
            nonlocal last_update_time, response_msg

            if done_stream:
                await stream_complete(full_content, tool_calls)
                if not done_cycle:
                    # we consumed the message for this cycle, so send a new one for the next cycle
                    response_msg = await message.channel.send(f"*{feedback_message()}*")
            
            now = time.time()
            if now - last_update_time > 1.5 and full_content.strip():
                try:
                    cleaned_content = clean_discord_message(full_content)
                    await response_msg.edit(content=cleaned_content)
                except discord.NotFound:
                    return False
                finally:
                    last_update_time = now

            return True

        try:
            await self.computer.cycle(content, hook=hook)
            logger.info(f"Message processing completed for user {message.author}")
        except Exception as exc:
            logger.exception(f"Error processing message from {message.author}: {exc}")
            error_msg = f"Nooooo: (Server Error) {exc}"
            cleaned_error = clean_discord_message(error_msg)
            await message.channel.send(cleaned_error)

    def _register_commands(self) -> None:
        @self.tree.command(name="ping",description="Make sure it's up",)
        async def ping(interaction: discord.Interaction):
            await interaction.response.send_message("Pong")

        @self.tree.command(name="history", description="Show conversation history")
        async def history(interaction: discord.Interaction):
            logger.info(f"History command invoked by {interaction.user}")
            history_text = CommandHelpers.get_history_text(self.computer.history, max_length=1900)
            output = f"**Conversation History**\n```\n{history_text}\n```"
            cleaned_output = clean_discord_message(output)
            await interaction.response.send_message(cleaned_output, ephemeral=True)

        @self.tree.command(name="clear", description="Clear conversation history (keeps system prompts)")
        async def clear(interaction: discord.Interaction):
            logger.info(f"Clear command invoked by {interaction.user}")
            self.computer.history = CommandHelpers.clear_history(self.computer.history)
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
