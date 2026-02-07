import json
from datetime import datetime, timezone
from computer.gmail.client import get_unread_emails
from computer.tasks.task import TaskParams, task

ORIGIN_TIME = datetime(2026, 2, 5, 19, 13, 0, tzinfo=timezone.utc)  # February 6, 2026, 7:13 PM UTC 

class EmailTask(TaskParams):
    """
    Periodic check of unread emails. Extract important information and summarize and to the user what unread emails they have.
    """
    @staticmethod
    def periodicity() -> str:
        # every day at 5 AM, and at 5 PM
        return "0 5,17 * * *"

@task(EmailTask)
async def run_email_check(_input: EmailTask) -> str:
    unread_emails = await get_unread_emails(ORIGIN_TIME)
    message = {
        "count": len(unread_emails),
        "emails": [x.serialize() for x in unread_emails]
    }
    return json.dumps(message)