import json
import os
from typing import Literal
from pydantic import BaseModel, Field
from tavily import TavilyClient

from computer.tools.tool import Tool, tool

tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

class WebSearch(BaseModel):
    """
    Search the web for results on a query.
    """
    query: str = Field(description = "Clear concise web query")
    search_depth: Literal['basic', 'advanced', 'fast', 'ultra-fast'] | None = Field(
        description="Detail requirements for the search. Can be left default.",
        default=None
    )

@tool(WebSearch)
def search_tavily(input: WebSearch):
    response = tavily_client.search(
        input.query, 
        search_depth=input.search_depth,  # type: ignore
        max_results=1, 
        include_answer='advanced'
    )
    return json.dumps({"answer": response["answer"], "top_page": response["results"][0]})