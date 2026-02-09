## To run
`python computer\cli.py` (`--discord`, `--notasks`)

# Computer

Agent system that integrates with your Linux machine, providing assistance through primarily a Discord interface. The agent can execute system commands, search the web, manage emails, and perform scheduled tasks while maintaining conversational context.

## Overview

System works with any OpenAI compatible API. Requires a model with tool calling capabilities.

## Features

### Discord Interface

The main interface for the agent is a Discord bot with a private server.

- Multi-message handling.
- Reaction-based approval system for sensitive operations (send emails, sudo, etc.)
- Channels with persistent conversation history
- Auto create forums for new tasks
- Streaming response updates
- Fork history through threads

### Tool System

The agent has access to various tools that extend its capabilities:

- **System Commands**: Execute shell commands with configurable timeouts
- **Sudo Operations**: Execute privileged commands with explicit user approval
- **Admin Tooling**: Specialized admin interface for VPN management and other administrative tasks
- **Web Search**: Integration with Tavily API for real-time web search capabilities
- **Email Management**: Search, send, and delete emails via SMTP/IMAP
  - Search by sender, subject, body, date range, and read status
  - HTML email support
  - User approval required for sending emails

### Task Scheduling

Automated periodic tasks using cron-style scheduling:

- **Email Monitoring**: Check for unread emails twice daily (5 AM and 5 PM)
- **System Health Checks**: Run system diagnostics twice daily (7 AM and 7 PM)
- Extensible task framework for custom automation

### Skills System

Reusable scripts with structured documentation:

- Skills are stored as directories with SKILL.md files
- Metadata-driven descriptions and usage instructions
- Built-in health check skill for baseline system diagnostics

## Approval Flow

For operations requiring approval (sudo commands, email sending):

1. Agent calls tool
2. Discord sends message to user
3. User reacts with thumbs up or down
4. Tool executes only upon approval
