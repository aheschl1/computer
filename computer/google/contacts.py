from computer.config import Config
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import asyncio
from functools import partial

logger = logging.getLogger(__name__)

# read and write access to contacts
SCOPES = [
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/contacts",
]

async def run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(func, *args, **kwargs)
    )

class Contact:
    def __init__(
        self, 
        name: str,
        uid: int,
        email: str | None = None, 
        phone: str | None = None
    ):
        self.name = name
        self.email = email
        self.phone = phone
        self.uid = uid
    
    
    def serialize(self) -> dict:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "uid": self.uid
        }
    
    def __repr__(self):
        return f"Contact(name={self.name}, email={self.email}, phone={self.phone}, uid={self.uid})"
    
    @staticmethod
    def from_google_person(person: dict) -> "Contact":
        name = None
        email = None
        phone = None
        if "names" in person:
            name = person["names"][0].get("displayName")
        if "emailAddresses" in person:
            email = person["emailAddresses"][0].get("value")
        if "phoneNumbers" in person:
            phone = person["phoneNumbers"][0].get("value")
        uid = person.get("resourceName", "").split("/")[-1]
        return Contact(name=name or "Not Available", email=email, phone=phone, uid=uid)
    
async def fuzzy_search_contacts(service, query: str, page_size: int = 10) -> list[Contact]:
    def _search():
        results = service.people().searchContacts(
            query=query,
            readMask="names,emailAddresses,phoneNumbers"
        ).execute()

        contacts = []
        for person in results.get("results", []):
            contacts.append(Contact.from_google_person(person["person"]))
        return contacts

    return await run_blocking(_search)

async def create_people_contact(
    service,
    name: str,
    email: str | None = None,
    phone: str | None = None
) -> Contact:

    def _create():
        body = {"names": [{"givenName": name}]}

        if email:
            body["emailAddresses"] = [{"value": email}]
        if phone:
            body["phoneNumbers"] = [{"value": phone}]

        person = service.people().createContact(body=body).execute()
        return Contact.from_google_person(person)

    return await run_blocking(_create)


def get_people_service(creds: Credentials):
    return build("people", "v1", credentials=creds, cache_discovery=False)


def authenticate_people_api() -> Credentials:
    cache_path = Config.cache_path() / "people_api"
    creds = None
    if (cache_path / "token.json").exists():
        logger.info("Found existing People API token, using it.")
        creds = Credentials.from_authorized_user_file(cache_path / "token.json", SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired:
            logger.info("People API token expired, refreshing...")
            creds.refresh(Request())
        else:
            logger.info("No valid People API token found, initiating authentication flow...")
            flow = InstalledAppFlow.from_client_secrets_file(
                Config.get_google_credentials_path(),
                SCOPES,
            )
            print("Please complete the authentication flow at 10.8.0.1:8099 in your browser.")
            creds = flow.run_local_server(host="127.0.0.1", port=8099, open_browser=True)
        cache_path.mkdir(parents=True, exist_ok=True)
        with open(cache_path / "token.json", "w+") as token_file:
            token_file.write(creds.to_json())
            logger.info("Saved new People API token to cache.")
    return creds

async def main():
    ...

if __name__ == "__main__":
    creds = authenticate_people_api()
    service = get_people_service(creds)
    query = input("Enter a name or email to search for contacts: ")
    contacts = fuzzy_search_contacts(service, query)
    print(contacts)