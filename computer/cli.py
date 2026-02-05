import asyncio
import logging
from computer.config import Config
from computer.model import Computer
from computer.utils import discover_tools, CommandHelpers
import dotenv

dotenv.load_dotenv("secret.env")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ChatInterface:
    def __init__(self, computer: Computer):
        self.computer = computer
        
    async def print_hook(
        self, 
        new_content: str, 
        _full_content: str, 
        full_tool_calls: dict[int, dict], 
        done: bool,
        _: bool
    ) -> bool:
        print(new_content, end="", flush=True)
        if done:
            print()
            # Display tools that were called
            if full_tool_calls:
                tool_names = [call["name"] for call in full_tool_calls.values()]
                print(f"  [Tools called: {', '.join(tool_names)}]")
                logger.info(f"Tools called: {', '.join(tool_names)}")
        return True
    
    def show_help(self):
        logger.debug("Displaying help menu")
        print("\n=== Available Commands ===")
        print("/help      - Show this help message")
        print("/exit      - Exit the chat")
        print("/history   - Show conversation history")
        print("/clear     - Clear conversation history (keeps system prompts)")
        print("/save      - Save conversation history to file")
        print("/load      - Load conversation history from file")
        print("/system    - Show current system prompt")
        print("/core      - Show current core")
        print("/tools     - List available tools")
        print("========================\n")
    
    def show_history(self):
        logger.debug("Displaying conversation history")
        print("\n=== Conversation History ===")
        print(CommandHelpers.get_history_text(self.computer.conversation))
        print("============================\n")
    
    def clear_history(self):
        # Keep only system prompts
        self.computer.conversation.clear_history()
        logger.info("Conversation history cleared (system prompts retained)")
        print("History cleared (system prompts retained).\n")
    
    def save_history(self):
        filename = input("Enter filename to save (default: history.json): ").strip()
        if not filename:
            filename = "history.json"
        success, message = CommandHelpers.save_history(
            self.computer.conversation, 
            self.computer.model, 
            filename
        )
        if success:
            logger.info(f"History saved to {filename}")
        else:
            logger.error(f"Failed to save history: {message}")
        print(f"{message}\n")
    
    def load_history(self):
        filename = input("Enter filename to load (default: history.json): ").strip()
        if not filename:
            filename = "history.json"
        history, timestamp, message = CommandHelpers.load_history(filename)
        if history is not None:
            self.computer.set_conversation(history)
            logger.info(f"History loaded from {filename} (saved at {timestamp})")
        else:
            logger.error(f"Failed to load history: {message}")
        print(f"{message}\n")
    
    def show_system_prompt(self):
        logger.debug("Displaying system prompt")
        print("\n=== System Prompt ===")
        print(CommandHelpers.get_system_prompt())
        print("=====================\n")
    
    def show_core(self):
        logger.debug("Displaying core")
        print("\n=== Core ===")
        print(CommandHelpers.get_core())
        print("============\n")
    
    def show_tools(self):
        logger.debug("Displaying available tools")
        print("\n=== Available Tools ===")
        print(CommandHelpers.get_tools_list(self.computer.tool_schemas))
        print("=======================\n")
    
    async def run(self):
        # Welcome message
        logger.info("Starting Computer Chat Interface")
        print("=" * 60)
        print("COMPUTER CHAT INTERFACE")
        print("=" * 60)
        print("Type /help for available commands, /exit to quit\n")
        
        # Main chat loop
        try:
            while True:
                try:
                    user_input = input("You: ").strip()
                    
                    if not user_input:
                        continue
                    
                    # Handle commands
                    if user_input.lower() in ["/exit", "/quit"]:
                        logger.info("User requested exit")
                        break
                    elif user_input.lower() == "/help":
                        self.show_help()
                        continue
                    elif user_input.lower() == "/history":
                        self.show_history()
                        continue
                    elif user_input.lower() == "/clear":
                        self.clear_history()
                        continue
                    elif user_input.lower() == "/save":
                        self.save_history()
                        continue
                    elif user_input.lower() == "/load":
                        self.load_history()
                        continue
                    elif user_input.lower() == "/system":
                        self.show_system_prompt()
                        continue
                    elif user_input.lower() == "/core":
                        self.show_core()
                        continue
                    elif user_input.lower() == "/tools":
                        self.show_tools()
                        continue
                    
                    # Process regular message
                    logger.debug(f"Processing user message: {user_input[:50]}...")
                    print("Assistant: ", end="", flush=True)
                    await self.computer.cycle(user_input, self.print_hook)
                    print()  # Extra newline for spacing
                    
                except KeyboardInterrupt:
                    logger.debug("KeyboardInterrupt received")
                    print("\n\nUse /exit or /quit to end the conversation.")
                    continue
                except EOFError:
                    logger.info("EOFError received, exiting")
                    print("\nGoodbye!")
                    break
                    
        except Exception as e:
            logger.exception(f"Fatal error in chat interface: {e}")
            print(f"\nFatal error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    import argparse
    import dotenv
    dotenv.load_dotenv()
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Computer Chat Interface")
    parser.add_argument(
        "--discord",
        action="store_true",
        help="Start the Discord bot instead of the CLI interface"
    )
    args = parser.parse_args()
    
    # Initialize computer with tools
    computer = Computer(
        tools=discover_tools()
    )
    
    logger.info(f"Initialized Computer: {computer}")
    print("Initialized Computer:")
    print(computer)
    
    # Start Discord bot or CLI interface
    if args.discord:
        from computer.discord.bot import run as run_discord
        logger.info("Starting Discord bot...")
        print("Starting Discord bot...")
        run_discord(computer)
    else:
        logger.info("Starting CLI interface")
        interface = ChatInterface(computer)
        asyncio.run(interface.run())