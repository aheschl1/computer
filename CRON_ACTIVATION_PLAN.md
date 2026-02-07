# Cron-Triggered Agent Activation Plan

## Overview
The system uses a cron-triggered script that runs every 10 minutes. Each task within the script independently decides if it's valid for the current time/context. The script activates the agent only when needed.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          CRON (every 10 min)                    │
│  */10 * * * * /home/andrew/Documents/agent/cron_runner.sh       │
└─────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    cron_runner.sh                               │
│  - Check time/day for each task                                 │
│  - For each task, check if activation is needed                 │
│  - Collect tasks that want to run                               │
│  - If any tasks active → invoke agent with task list            │
└─────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    agent_runner.py                              │
│  - Load conversation history (if any)                           │
│  - Modify system prompt to include active tasks                 │
│  - Pass tasks as context to agent                               │
│  - Agent decides what to do based on tasks                      │
│  - Save conversation if needed                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Cron Tasks

### Task Types

1. **Email Check** - Check Gmail inbox for new messages
2. **System Health** - Monitor CPU, memory, disk usage
3. **Log Rotation** - Clean up old logs/cache files
4. **Backup Check** - Verify backups are running
5. **Scheduled Messages** - Send messages at specific times

### Task Activation Logic

Each task has:
- `should_run()` - Returns `True` if the task should execute now
- `get_activation_message()` - Returns the message to send to agent

**Example: Email Check Task**
```python
def should_run():
    # Only check during work hours, every 10 minutes
    now = datetime.now()
    return 9 <= now.hour <= 17 and now.minute % 10 == 0

def get_activation_message():
    emails = check_new_emails()
    if emails:
        return f"New emails received: {emails}"
    return None  # No activation needed
```

## Agent Activation Flow

### When Cron Triggers

1. **cron_runner.sh** collects all task messages where `should_run() == True`
2. If no tasks active → exit without agent invocation
3. If tasks active → invoke agent with:
   - System prompt modified to include active tasks
   - User message listing active tasks
   - Conversation history (if any)

### Agent System Prompt Enhancement

When tasks are active, the system prompt includes:

```
## Active Tasks
- email_check: Check for new emails and notify user
- system_health: Monitor system health metrics
- [other active tasks...]

## Task Execution Guidelines
1. Review the active tasks
2. Execute appropriate actions for each task
3. Report results clearly to the user
4. If a task requires user input, ask for it
```

## Implementation Details

### 1. cron_runner.sh

```bash
#!/bin/bash
cd /home/andrew/Documents/agent

# Collect active task messages
TASK_MESSAGES=""

# Check email task
python3 -c "
import sys
sys.path.insert(0, '.')
from tasks.email_check import should_run, get_activation_message
if should_run():
    msg = get_activation_message()
    if msg:
        print(msg)
"

# Check system health task
# (similar pattern)

# If any tasks active, invoke agent
if [ -n "$TASK_MESSAGES" ]; then
    python3 -c "
import asyncio
from computer.cli import ChatInterface
from computer.model import Computer
from computer.utils import discover_tools
    
async def run_with_tasks():
    computer = Computer(tools=discover_tools())
    interface = ChatInterface(computer)
    # Pre-populate conversation with task context
    computer.conversation.add_message('system', f'Active tasks: $TASK_MESSAGES')
    await computer.cycle('$TASK_MESSAGES', interface.print_hook)
    
asyncio.run(run_with_tasks())
" >> /var/log/agent_cron.log 2>&1
fi
```

### 2. Task Module Structure

```
tasks/
├── __init__.py
├── email_check.py
├── system_health.py
├── scheduled_messages.py
└── backup_check.py
```

### 3. Task Interface (Python)

Each task module exports:
- `should_run() -> bool` - Returns True if task should activate agent
- `get_activation_message() -> str | None` - Returns task message or None
- `execute() -> str | None` - Optional: execute task directly if agent doesn't handle it

**Example: tasks/email_check.py**

```python
import os
from imapclient import IMAPClient
from datetime import datetime
import json

HOST = 'imap.gmail.com'
USERNAME = os.getenv("GMAIL_USERNAME")
PASSWORD = os.getenv("GMAIL_PASSWORD")

def should_run() -> bool:
    """Check if we should run email check now."""
    now = datetime.now()
    # Only check during work hours, every 10 minutes
    return 9 <= now.hour <= 17 and now.minute % 10 == 0

def get_new_emails() -> list:
    """Fetch unread emails."""
    emails = []
    try:
        with IMAPClient(HOST) as client:
            client.login(USERNAME, PASSWORD)
            client.select_folder('INBOX')
            messages = client.search(['UNSEEN'])
            for msg_id in messages:
                response = client.fetch(msg_id, ['RFC822'])
                emails.append({
                    'id': msg_id,
                    'subject': str(response[msg_id][b'RFC822'])
                })
    except Exception as e:
        # Log error but don't fail
        with open('/var/log/agent_email.log', 'a') as f:
            f.write(f"[{datetime.now()}] Email check error: {e}\n")
    return emails

def get_activation_message() -> str | None:
    """Get message to send to agent if new emails exist."""
    emails = get_new_emails()
    if emails:
        return f"New emails detected ({len(emails)}). Check inbox."
    return None

def execute() -> str:
    """Execute email check directly (fallback if agent not invoked)."""
    emails = get_new_emails()
    if emails:
        return f"Found {len(emails)} new emails."
    return "No new emails."
```

### 4. Agent Tool for Email

Add to `computer/tools/email_check.py`:

```python
from typing import Callable
from pydantic import BaseModel, Field
import os
from imapclient import IMAPClient

from computer.tools.tool import Tool, tool

class EmailCheck(BaseModel):
    """Check for new emails in Gmail inbox."""
    max_results: int = Field(
        default=10,
        description="Maximum number of emails to return"
    )

@tool(EmailCheck)
async def check_emails(tool_input: EmailCheck) -> str:
    """Check Gmail for new (unread) emails."""
    try:
        with IMAPClient(HOST) as client:
            client.login(USERNAME, PASSWORD)
            client.select_folder('INBOX')
            messages = client.search(['UNSEEN'])
            
            result = []
            for msg_id in messages[:tool_input.max_results]:
                response = client.fetch(msg_id, ['RFC822'])
                result.append(f"Email {msg_id}: {str(response[msg_id][b'RFC822'])}")
            
            if result:
                return f"New emails:\n" + "\n".join(result)
            return "No new emails."
    except Exception as e:
        return f"Error checking emails: {str(e)}"
```

## Tool Access Based on Active Tasks

When cron activates the agent, only tools relevant to active tasks are passed:

```python
# In cron_runner.sh
ACTIVE_TASKS="email_check system_health"

# Map tasks to tools
TOOL_MAP={
    "email_check": "computer.tools.email_check",
    "system_health": "computer.tools.system_health",
}

# Only import and pass relevant tools
for task in ACTIVE_TASKS; do
    if [ -n "${TOOL_MAP[$task]}" ]; then
        # Import that module's tools
    fi
done
```

## Conversation Persistence

Each cron job run can optionally save/load conversation state:

```python
# Use ConversationStorage for persistence
from computer.conversation import ConversationStorage

# Load previous state if exists
conversation = ConversationStorage.load("cron_email_check")

# Use it when creating Computer
computer = Computer(
    tools=tools,
    conversation=conversation
)

# Save after execution
ConversationStorage.save(computer.conversation, "cron_email_check")
```

## Error Handling

1. **Task execution errors** - Log to separate log files
2. **Agent invocation errors** - Retry up to 3 times with exponential backoff
3. **Gmail API errors** - Continue to next task, log error

## Testing

```bash
# Test task activation
python3 tasks/email_check.py

# Test agent activation
python3 cron_runner.sh

# Monitor logs
tail -f /var/log/agent_cron.log
```

## Deployment

1. Add to user crontab:
```bash
*/10 * * * * /home/andrew/Documents/agent/cron_runner.sh >> /var/log/agent_cron.log 2>&1
```

2. Verify crontab is running:
```bash
crontab -l
```

3. Test with:
```bash
python3 cron_runner.sh
```
