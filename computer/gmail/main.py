import os
from imapclient import IMAPClient
import time
import dotenv

dotenv.load_dotenv("secret.env")

# Configuration
HOST = 'imap.gmail.com'
USERNAME = os.getenv("GMAIL_USERNAME")
PASSWORD = os.getenv("GMAIL_PASSWORD")

def monitor_mailbox():
    with IMAPClient(HOST) as client:
        client.login(USERNAME, PASSWORD) # type: ignore
        client.select_folder('INBOX')
        
        print("Listening for new emails...")
        
        while True:
            # Start IDLE mode
            client.idle()
            # Wait up to 5 minutes for a change
            responses = client.idle_check(timeout=300)
            client.idle_done()
            
            if responses:
                # Filter for "EXISTS" responses (new mail)
                if any(resp[1] == b'EXISTS' for resp in responses):
                    print(f"[{time.strftime('%H:%M:%S')}] New email received!")
                    # You can add logic here to fetch the sender/subject


monitor_mailbox()