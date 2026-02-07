

import asyncio
from datetime import datetime, timedelta
import json
import subprocess
import os
from pydantic import BaseModel, Field
from typing import TYPE_CHECKING

from computer.gmail.client import delete_email_imap, search_emails_imap, send_smtp
from computer.tools.tool import tool

if TYPE_CHECKING:
    from computer.model import ApprovalHook


ONE_DAY_AGO = datetime.now() - timedelta(days=1)

class SendEmail(BaseModel):
    """
    Send an email on behalf of the user. This is safe, as the user will need to approve it explicitly.
    """
    body: str = Field(..., description="The body of the email to send.")
    subject: str = Field(..., description="The subject of the email.")
    to: str = Field(..., description="The recipient email address.")
    cc: str | None = Field(None, description="The CC email address.")
    bcc: str | None = Field(None, description="The BCC email address.")
    html: bool = Field(False, description="Send the body as rich HTML content.")

class DeleteEmail(BaseModel):
    """
    Delete an email from the user's inbox.
    """
    uid: str = Field(..., description="The ID of the email to delete.")

class SearchEmails(BaseModel):
    """
    Search for emails in the user's inbox that match a query.
    """
    sender: str | None = Field(None, description="Filter emails by sender email address.")
    subject: str | None = Field(None, description="Filter emails by subject content.")
    body: str | None = Field(None, description="Filter emails by body content.")
    unread_only: bool | None = Field(None, description="Filter for only unread emails.")
    since: str | None = Field(ONE_DAY_AGO.strftime("%Y-%m-%d"), description="Filter for emails received since this date (YYYY-MM-DD).")
    before: str | None = Field(None, description="Filter for emails received before this date (YYYY-MM-DD).")

@tool(SearchEmails)
async def search_emails(command: SearchEmails) -> str:
    datetime_from = None
    datetime_before = None
    if command.since:
        datetime_from = datetime.strptime(command.since, "%Y-%m-%d")
    if command.before:
        datetime_before = datetime.strptime(command.before, "%Y-%m-%d")
        
    emails = await search_emails_imap(
        from_address=command.sender,
        subject=command.subject,
        body=command.body,
        unread_only=command.unread_only or False,
        since=datetime_from,
        before=datetime_before
    )
    
    result = {
        "count": len(emails),
        "emails": [email.serialize() for email in emails]
    }
    return json.dumps(result)

@tool(DeleteEmail)
async def delete_email(command: DeleteEmail) -> str:
    success = await delete_email_imap(int(command.uid))
    if success:
        return "Email deleted successfully."
    else:
        return "Failed to delete email. Please check the UID and try again."
    
    
@tool(SendEmail)
async def send_email(command: SendEmail, approval_hook: "ApprovalHook | None" = None) -> str:
    # Request approval from user
    if approval_hook:
        approval_message = (
            f"**Email Approval Request**\n\n"
            f"Subject: `{command.subject}`\n"
            f"To: {command.to}\n\n"
            f"Body: {command.body}\n\n"
        )
        
        # Use 3 minute timeout (180 seconds) for approval
        approved = await approval_hook(approval_message, 180.0)
        
        if not approved:
            return "User did not approve the email. Work with the user to refine."
    else:
        # Fallback: if no approval hook, deny by default for safety
        return "Approval mechanism not available. Cannot send email without user confirmation."
    
    sent = await send_smtp(
        to=command.to,
        subject=command.subject,
        body=command.body
    )
    
    if sent:
        return "Email sent successfully."
    else:
        return "Failed to send email."