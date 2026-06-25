from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.api.v1.deps import get_current_user, get_current_workspace, ensure_workspace_membership
from app.db.supabase_client import get_supabase
from app.db.tables.custom_scrapers import (
    list_custom_scrapers_for_workspace,
    upsert_custom_scraper,
    delete_custom_scraper,
)
from pydantic import BaseModel
from app.schemas.v1.scrapers import CustomScraperResponse, CustomScraperCreateRequest
from app.services.infrastructure.llm.service import LLMService

router = APIRouter(prefix="/v1/scrapers", tags=["scrapers"])

class ChatMessagePayload(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessagePayload]

class ChatResponse(BaseModel):
    reply: str


@router.get("", response_model=list[CustomScraperResponse])
def list_scrapers_endpoint(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> list[CustomScraperResponse]:
    """List all custom scrapers for the current workspace."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    scrapers = list_custom_scrapers_for_workspace(supabase, workspace["id"])
    return [CustomScraperResponse.model_validate(s) for s in scrapers]


@router.post("", response_model=CustomScraperResponse, status_code=status.HTTP_201_CREATED)
def create_scraper_endpoint(
    payload: CustomScraperCreateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> CustomScraperResponse:
    """Create or update a custom scraper configuration for a specific platform."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    
    data = payload.model_dump()
    data["workspace_id"] = workspace["id"]
    
    scraper = upsert_custom_scraper(supabase, data)
    return CustomScraperResponse.model_validate(scraper)


@router.delete("/{scraper_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scraper_endpoint(
    scraper_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> None:
    """Delete a custom scraper configuration."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    
    # Optional: verify the scraper belongs to the workspace before deleting
    # RLS handles this mostly, but good practice.
    
    delete_custom_scraper(supabase, scraper_id)


@router.post("/chat", response_model=ChatResponse)
def scrapers_chat_endpoint(
    payload: ChatRequest,
    current_user: dict = Depends(get_current_user),
) -> ChatResponse:
    """Setup Assistant chat endpoint to help map API responses to JSON paths."""
    system_prompt = (
        "You are an API integration expert assisting a user in setting up a custom social media scraper. "
        "The user will paste raw JSON from an API endpoint (like Instagram/Twitter/LinkedIn). "
        "Your job is to identify the 'dot notation' paths to the required fields: "
        "`items_json_path` (array of posts/users), and for each item, how to map `external_id`, `author_username`, "
        "`title`, `body`, `profile_url`, `upvotes`, and `comments_count`. "
        "Be concise and output the recommended mapping configuration."
    )
    
    # Format messages into a single prompt string since LLMService.call_text expects a string
    prompt_lines = []
    for msg in payload.history:
        role_label = "Assistant" if msg.role == "assistant" else "User"
        prompt_lines.append(f"{role_label}: {msg.content}")
    
    prompt_lines.append(f"User: {payload.message}")
    prompt_lines.append("Assistant:")
    
    final_prompt = "\n\n".join(prompt_lines)
    
    llm = LLMService()
    reply = llm.call_text(
        prompt=final_prompt,
        system_message=system_prompt,
        temperature=0.3
    )
    if not reply:
        reply = "Sorry, I couldn't process that right now."
        
    return ChatResponse(reply=reply)
