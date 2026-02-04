COMPUTER AGENT - ARCHITECTURE NOTES
===================================

Overview
--------
This is a Python-based AI agent named "Computer" that interfaces with an LLM (via OpenAI-compatible API)
to perform tasks using tools. It supports both CLI and Discord bot interfaces.

Core Components
---------------
1. computer/model.py - Main Computer class that orchestrates cycles with the LLM
   - Manages chat history (system, user, assistant, tool messages)
   - Supports streaming responses with hooks
   - Handles tool calls with automatic re-cycling
   - Configurable max_cycles (default 50) to prevent infinite loops

2. computer/config.py - Configuration management
   - Loads from .env and secret.env files
   - Key settings: MODEL, ENDPOINT, API_KEY, CORE_FILE, USER_NAME
   - Dynamic system prompt/core loading with template substitution

3. computer/cli.py - CLI interface (ChatInterface class)
   - Commands: /help, /exit, /history, /clear, /save, /load, /system, /core, /tools
   - Streaming output with print_hook
   - Discord mode available via --discord flag

4. computer/discord/bot.py - Discord integration
   - DiscordBot class with slash commands
   - Commands: /ping, /history, /clear, /system, /core, /tools
   - Uses feedback messages during processing
   - Handles message streaming and editing

5. computer/tools/ - Tool implementations
   - tool.py - Decorator system (@tool) and Tool class
   - system.py - ExecuteCommand tool (subprocess)
   - admin.py - AdminTooling (sudo-level commands via 'admin' binary)
   - web.py - WebSearch (Tavily)
   - core.py - UpdateCore tool (modifies CORE.txt)

6. computer/gmail/main.py - Email monitoring (IMAP IDLE)

External Dependencies
---------------------
- Python: openai, pydantic, httpx, dotenv, discord.py, tavily
- Rust: administrator binary (sudo-level VPN management)
- System: wireguard (wg), ping

Key Design Patterns
-------------------
- Streaming: Responses streamed incrementally via hooks
- Tool Discovery: Auto-discovers @tool decorated functions in computer.tools
- Tool Call Parsing: Uses pydantic models for validation
- Cycle-based: Each LLM call is a "cycle"; tool calls trigger re-cycles

Current Configuration
---------------------
- Model: Qwen3-Next-80B-A3B-Instruct-UD-Q4_K_XL
- Endpoint: http://10.8.0.15:8080/v1
- Core file: CORE.txt (at project root)
- User: Andrew (per USER_NAME env var)
- Ana: Noted as important person to Andrew

Tools Available
---------------
1. ExecuteCommand - Run shell commands (timeout configurable)
2. AdminTooling - Run admin commands via 'admin' binary (requires sudo)
3. WebSearch - Search web via Tavily API
4. UpdateCore - Append or diff-update CORE.txt

VPN Management (via admin binary)
---------------------------------
- admin vpn health - Check VPN server and peer status
- admin vpn add <name> <address> - Create new WireGuard client
- admin vpn remove <name> - Remove client
- admin vpn show <name> - Show client config

Notes
-----
- The agent uses OpenAI-compatible API (not necessarily OpenAI)
- History can be saved/loaded as JSON with timestamps
- System prompts and core are loaded from files with template substitution
- Logging is configured at INFO level
