import json
from pydantic import BaseModel, Field
from typing import TYPE_CHECKING, Optional

from computer.google.contacts import create_people_contact, fuzzy_search_contacts, get_people_service, authenticate_people_api
from computer.tools.tool import tool

if TYPE_CHECKING:
    from computer.model import ApprovalHook

SERVICE = get_people_service(authenticate_people_api())

class SearchContacts(BaseModel):
    """
    Fuzzy search for contacts, using names, phone numbers, or email addresses.
    """
    query: str = Field(..., description="The search query for contacts.")    

class CreateContact(BaseModel):
    """
    Create a new contact with the provided details.
    """
    name: str = Field(..., description="The full name of the contact.")
    email: Optional[str] = Field(default=None, description="The email address of the contact.")
    phone: Optional[str] = Field(default=None, description="The phone number of the contact.")

@tool(CreateContact)
async def create_contact(command: CreateContact) -> str:
    result = await create_people_contact(
        SERVICE,
        name=command.name,
        email=command.email,
        phone=command.phone
    )
    if result:
        return f"Contact '{command.name}' created successfully"
    else:
        return f"Failed to create contact '{command.name}'" 

@tool(SearchContacts)
async def search_contacts(command: SearchContacts) -> str:
    if command.query.strip() == "":
        return "Please provide a non-empty query to search for contacts."
    contacts = await fuzzy_search_contacts(SERVICE, command.query)
    results = {
        "count": len(contacts),
        "contacts": [contact.serialize() for contact in contacts]
    }
    return json.dumps(results)
    