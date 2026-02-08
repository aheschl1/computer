import os
from typing import Callable
from imapclient import IMAPClient
import email
from email.message import EmailMessage
from email.header import decode_header
from email.utils import parsedate_to_datetime
import smtplib
import asyncio
import dotenv
import logging
from datetime import datetime

dotenv.load_dotenv("secret.env")

logger = logging.getLogger(__name__)

# Configuration
IMAP_HOST = 'imap.gmail.com'
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587
USERNAME = os.getenv("GMAIL_USERNAME")
PASSWORD = os.getenv("GMAIL_PASSWORD")
TRASH_FOLDER = '[Gmail]/Trash'  # Gmail's trash folder name

class Email:
    def __init__(
        self, 
        uid, 
        sender, 
        subject,
        body,
        date=None,
        to=None,
        cc=None
    ):
        self.uid = uid
        self.sender = sender
        self.subject = subject
        self.body = body
        self.date = date
        self.to = to
        self.cc = cc
    
    def __repr__(self):
        return f"Email(uid={self.uid}, sender='{self.sender}', subject='{self.subject}', date='{self.date}')"

    
    def serialize(self):
        """Convert Email object to a dictionary for easier serialization"""
        return {
            "uid": self.uid,
            "sender": self.sender,
            "subject": self.subject,
            "body": self.body,
            "date": self.date,
            "to": self.to,
            "cc": self.cc
        }
    
    @staticmethod
    def decode_header_value(header_value):
        """Decode email header that might be encoded"""
        if header_value is None:
            return ""
        
        decoded_parts = decode_header(header_value)
        decoded_string = ""
        
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_string += part.decode(encoding or 'utf-8', errors='ignore')
            else:
                decoded_string += part
        
        return decoded_string

    @staticmethod
    def get_body(msg):
        """Extract email body from multipart or plain message"""
        body = ""
        
        if msg.is_multipart():
            # Iterate through email parts
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                
                # Get text/plain parts
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
                    except:
                        pass
                # If no text/plain, try text/html
                elif content_type == "text/html" and not body and "attachment" not in content_disposition:
                    try:
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    except:
                        pass
        else:
            # Not multipart - get payload directly
            try:
                body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            except:
                body = str(msg.get_payload())
        
        return body

    @staticmethod
    def get(client: IMAPClient, uid=None) -> "Email | None":
        """Fetch the latest email or a specific email by UID"""
        if uid is None:
            # Get the most recent email
            messages = client.search('ALL')  # type: ignore
            if not messages:
                return None
            uid = messages[-1]
        
        # Fetch the email data without marking as read using BODY.PEEK
        raw_message = client.fetch([uid], ['BODY.PEEK[]'])
        
        if uid not in raw_message:
            return None
        
        # Parse the email (BODY.PEEK[] returns the same data as RFC822 but doesn't set \Seen flag)
        email_body = raw_message[uid][b'BODY[]']
        msg = email.message_from_bytes(email_body)  # type: ignore
        
        # Extract email details
        sender = Email.decode_header_value(msg.get('From', ''))
        subject = Email.decode_header_value(msg.get('Subject', ''))
        date = msg.get('Date', '')
        to = Email.decode_header_value(msg.get('To', ''))
        cc = Email.decode_header_value(msg.get('Cc', ''))
        
        # Extract body
        body = Email.get_body(msg)
        
        return Email(
            uid=uid,
            sender=sender,
            subject=subject,
            body=body,
            date=date,
            to=to,
            cc=cc
        )
        
type Hook = Callable[[Email], None]
type AsyncHook = Callable[[Email], asyncio.Future]

async def delete_email_imap(uid: int) -> bool:
    """
    Move an email to the trash bin by UID.
    
    Args:
        uid: The UID of the email to delete
        
    Returns:
        True if email was successfully moved to trash, False otherwise
    """
    def _delete():
        try:
            with IMAPClient(IMAP_HOST) as client:
                client.login(USERNAME, PASSWORD)  # type: ignore
                client.select_folder('INBOX')
                
                # Copy the email to trash
                client.copy([uid], TRASH_FOLDER)
                client.delete_messages([uid])
                client.expunge()
                
                logger.info(f"Email UID {uid} moved to trash")
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete email UID {uid}: {e}")
            return False
    
    return await asyncio.to_thread(_delete)

async def search_emails_imap(
    from_address: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    unread_only: bool = False,
    folder: str = 'INBOX',
    max_return: int = 10
) -> list[Email]:
    """
    Search for emails based on various criteria.
    
    Args:
        from_address: Filter by sender email address (partial match)
        subject: Filter by subject line (partial match)
        body: Filter by body text (partial match)
        since: Only include emails received at or after this datetime
        before: Only include emails received before this datetime
        unread_only: If True, only return unread emails
        folder: Which folder to search in (default: 'INBOX')
        
    Returns:
        List of Email objects matching the search criteria
    """
    def _search():
        emails = []
        
        try:
            with IMAPClient(IMAP_HOST) as client:
                client.login(USERNAME, PASSWORD)  # type: ignore
                client.select_folder(folder)
                
                # Build search criteria
                criteria = []
                
                if unread_only:
                    criteria.append('UNSEEN')
                
                if from_address:
                    criteria.extend(['FROM', from_address])
                
                if subject:
                    criteria.extend(['SUBJECT', subject])
                
                if body:
                    criteria.extend(['BODY', body])
                
                if since:
                    criteria.extend(['SINCE', since.date()])
                
                if before:
                    criteria.extend(['BEFORE', before.date()])
                
                # If no criteria specified, search for all
                if not criteria:
                    criteria = ['ALL']
                
                logger.info(f"Searching with criteria: {criteria}")
                
                # Perform search
                message_uids = client.search(criteria)  # type: ignore
                
                if not message_uids:
                    logger.info("No emails found matching search criteria")
                    return emails[:max_return]
                
                logger.info(f"Found {len(message_uids)} email(s) matching criteria")
                
                # Fetch each matching email
                for uid in message_uids:
                    email_obj = Email.get(client, uid)
                    
                    if email_obj:
                        # Apply time-based filtering if needed (SINCE/BEFORE only use date precision)
                        if email_obj.date:
                            try:
                                email_date = parsedate_to_datetime(email_obj.date)
                                
                                # Check time-based filters with precision
                                if since and email_date < since:
                                    continue
                                if before and email_date >= before:
                                    continue
                                    
                            except Exception as e:
                                logger.warning(f"Could not parse date for email UID {uid}: {e}")
                        
                        emails.append(email_obj)
                        if len(emails) == max_return:
                            logger.info(f"Reached max return limit of {max_return} emails")
                            break
                        logger.debug(f"Added email UID {uid} from {email_obj.sender}")
                
                logger.info(f"Returning {len(emails)} email(s) after filtering")
                return emails[:max_return]
                
        except Exception as e:
            logger.error(f"Error searching emails: {e}")
            return []
    
    return await asyncio.to_thread(_search)

async def send_smtp(
    to: str | list[str],
    subject: str,
    body: str,
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    html: bool = False
) -> bool:
    """
    Send an email via SMTP using the modern EmailMessage API.
    
    Args:
        to: Email address(es) of recipient(s). Can be a single string or list of strings.
        subject: Email subject line
        body: Email body content
        cc: Optional CC recipient(s). Can be a single string or list of strings.
        bcc: Optional BCC recipient(s). Can be a single string or list of strings.
        html: If True, send body as HTML. If False, send as plain text.
        
    Returns:
        True if email was sent successfully, False otherwise
    """
    def _send():
        try:
            # Create message using modern EmailMessage
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = USERNAME
            
            # Handle single or multiple recipients
            if isinstance(to, list):
                msg["To"] = ", ".join(to)
            else:
                msg["To"] = to
            
            # Handle CC if provided
            if cc:
                if isinstance(cc, list):
                    msg["Cc"] = ", ".join(cc)
                else:
                    msg["Cc"] = cc
            
            # Handle BCC if provided
            if bcc:
                if isinstance(bcc, list):
                    msg["Bcc"] = ", ".join(bcc)
                else:
                    msg["Bcc"] = bcc
            
            # Set content (EmailMessage handles HTML vs plain text automatically)
            if html:
                msg.set_content(body, subtype='html')
            else:
                msg.set_content(body)
            
            # Connect to SMTP server and send
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(USERNAME, PASSWORD)  # type: ignore
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {msg['To']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
    
    return await asyncio.to_thread(_send)

async def get_unread_emails(since: datetime) -> list[Email]:
    """
    Get all unread emails that are not older than the specified datetime.
    
    Args:
        since: datetime object - only return emails received at or after this time
        
    Returns:
        List of Email objects that are unread and within the time window
    """
    def _get_unread():
        emails = []
        
        with IMAPClient(IMAP_HOST) as client:
            client.login(USERNAME, PASSWORD) # type: ignore
            client.select_folder('INBOX')
            
            # Use server-side search with date filter
            # IMAP SINCE uses date only (not time), so we use the date of 'since'
            search_date = since.date()
            
            # Search for unread messages since the specified date
            # The server will filter before returning UIDs - much more efficient
            unread_uids = client.search(['UNSEEN', 'SINCE', search_date])  # type: ignore
            
            if not unread_uids:
                logger.info("No unread emails found")
                return emails
            
            logger.info(f"Found {len(unread_uids)} unread email(s) since {search_date}")
            
            for uid in unread_uids:
                # Fetch the email
                email_obj = Email.get(client, uid)
                
                if email_obj and email_obj.date:
                    try:
                        # Parse the email date
                        email_date = parsedate_to_datetime(email_obj.date)
                        
                        # Double-check with time precision (SINCE only checks date)
                        if email_date >= since:
                            emails.append(email_obj)
                            logger.debug(f"Added email UID {uid} from {email_obj.sender}")
                        else:
                            logger.debug(f"Skipped email UID {uid} - too old ({email_date})")
                    except Exception as e:
                        logger.warning(f"Could not parse date for email UID {uid}: {e}")
                        # Include emails with unparseable dates to be safe
                        emails.append(email_obj)
                elif email_obj:
                    # Include emails without dates to be safe
                    logger.warning(f"Email UID {uid} has no date, including anyway")
                    emails.append(email_obj)
            
            logger.info(f"Returning {len(emails)} unread email(s) since {since}")
            return emails
    
    return await asyncio.to_thread(_get_unread)

async def monitor_mailbox(hook: Hook | AsyncHook | None = None):
    """Monitor mailbox for new emails and trigger hook when received"""
    def _monitor_sync():
        with IMAPClient(IMAP_HOST) as client:
            client.login(USERNAME, PASSWORD) # type: ignore
            client.select_folder('INBOX')
            
            # Get initial message count to track new emails
            initial_messages = client.search('ALL')  # type: ignore
            seen_uids = set(initial_messages) if initial_messages else set()
            
            logger.info(f"Listening for new emails... (Current inbox count: {len(seen_uids)})")
            
            while True:
                try:
                    # Start IDLE mode
                    client.idle()
                    # Wait up to 5 minutes for a change
                    responses = client.idle_check(timeout=300)
                    client.idle_done()
                    
                    if responses:
                        # Filter for "EXISTS" responses (new mail)
                        if any(resp[1] == b'EXISTS' for resp in responses):
                            # Fetch all current messages
                            current_messages = client.search('ALL')  # type: ignore
                            
                            # Find new UIDs
                            new_uids = set(current_messages) - seen_uids
                            
                            if new_uids:
                                for uid in sorted(new_uids):
                                    logger.info(f"New email received (UID: {uid})")
                                    
                                    # Fetch the email details
                                    email_obj = Email.get(client, uid)
                                    
                                    if email_obj:
                                        logger.info(f"  From: {email_obj.sender}")
                                        logger.info(f"  Subject: {email_obj.subject}")
                                        logger.info(f"  Date: {email_obj.date}")
                                        logger.info(f"  Body preview: {email_obj.body[:100]}...")
                                        
                                        # Call the hook if provided
                                        # Note: Hook is called from thread, so async hooks need special handling
                                        if hook:
                                            if asyncio.iscoroutinefunction(hook):
                                                # Schedule coroutine in main event loop
                                                asyncio.run_coroutine_threadsafe(hook(email_obj), asyncio.get_event_loop())
                                            else:
                                                hook(email_obj)
                                    
                                    # Mark as seen
                                    seen_uids.add(uid)
                except Exception as e:
                    logger.error(f"Error monitoring mailbox: {e}")
                    import time
                    time.sleep(5)  # Wait before retrying
    
    # Run the blocking monitor in a separate thread
    await asyncio.to_thread(_monitor_sync)

if __name__ == "__main__":
    asyncio.run(monitor_mailbox())