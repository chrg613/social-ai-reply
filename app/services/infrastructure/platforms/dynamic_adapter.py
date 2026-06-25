import json
import logging
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.services.infrastructure.platforms.models import UnifiedComment, UnifiedPost
from app.services.infrastructure.llm.agents import _build_model
from app.services.infrastructure.platforms.base import PlatformAdapter
from app.services.infrastructure.platforms.rapidapi_client import RapidAPIClient, RapidAPIError

logger = logging.getLogger(__name__)


class ParsedPost(BaseModel):
    """LLM-parsed standard representation of a social media post/profile."""
    external_id: str = Field(description="Unique ID for the post or user in the source platform")
    author_username: str = Field(default="unknown", description="Username of the author or profile")
    author_id: str = Field(default="", description="Internal ID of the author/user")
    title: str = Field(default="", description="Title of the post, or Full Name of the profile")
    body: str = Field(default="", description="Text content of the post, or bio of the profile")
    profile_url: str = Field(default="", description="URL to the post or profile")
    upvotes: int = Field(default=0, description="Number of likes/upvotes/followers")
    comments_count: int = Field(default=0, description="Number of comments")
    hashtags: list[str] = Field(default_factory=list, description="Extracted hashtags")


class ParsedPostList(BaseModel):
    """Wrapper to parse an array of posts at once."""
    posts: list[ParsedPost]


# Define the dynamic parsing agent
dynamic_parser_agent = Agent(
    model=_build_model(),
    output_type=ParsedPostList,
    retries=2,
    model_settings={"max_tokens": 4000},
    system_prompt=(
        "You are an API parsing assistant. You will be provided with a raw JSON array of items "
        "extracted from a social media scraper (e.g. Instagram, Reddit, Twitter).\n\n"
        "Your job is to extract the relevant data from each item and map it into the requested "
        "ParsedPost schema. If the JSON items are 'posts', extract the post data. If they are 'users' "
        "or profiles, extract the user data.\n\n"
        "For Reddit, map 'id' or 'name' to external_id, 'author' to author_username, 'title' to title, "
        "'selftext' to body, and 'ups' or 'score' to upvotes.\n\n"
        "Do not invent information. Ensure `external_id` is unique per item.\n"
        "CRITICAL: Extract EVERY item you are given. Do not skip items! Map whatever data you can find. "
        "If an item is missing fields, leave them blank or use a default, but you MUST return a ParsedPost for each item in the input array."
    ),
)


def extract_json_path(data: Any, path: str) -> Any:
    """Extract a value from a nested dict/list using a dot-notation path (e.g., 'data.items')."""
    if not path or path == ".":
        return data

    keys = path.split(".")
    current = data
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k)
        elif isinstance(current, list):
            try:
                current = current[int(k)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


class DynamicAdapter(PlatformAdapter):
    """Adapter that reads its configuration from the database and uses an LLM to parse responses."""

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.config = config
        self.platform = config["platform"]
        self.api_host = config["api_host"]
        self.api_key = config.get("api_key")
        self._available = True # Always available, will fallback to global RAPIDAPI_KEY if needed
        self.client = RapidAPIClient(self.api_host, api_key=self.api_key)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self._available or not self.client:
            return None
        return await self.client.get(path, params=params)

    async def search_posts(
        self,
        keywords: list[str],
        *,
        limit: int = 50,
        sort: str = "relevance",
        time_filter: str = "week",
    ) -> list[UnifiedPost]:
        """Search using the custom scraper configuration and LLM parsing."""
        if not self._available:
            logger.warning("Dynamic scraper for %s not available (no API key)", self.platform)
            return []

        all_posts: list[UnifiedPost] = []
        seen_ids: set[str] = set()
        endpoint = self.config["search_endpoint"]
        param_name = self.config["search_param_name"]
        json_path = self.config["items_json_path"]

        for keyword in keywords:
            query = keyword.strip()
            if not query:
                continue

            try:
                data = await self._get(endpoint, params={param_name: query})
            except RapidAPIError as e:
                logger.error("Dynamic scraper (%s) failed for '%s': %s", self.platform, query, e)
                continue

            if not isinstance(data, (dict, list)):
                continue

            # Extract the items array
            items = extract_json_path(data, json_path)
            if not isinstance(items, list):
                # If extraction failed, maybe the root is the array
                if isinstance(data, list):
                    items = data
                else:
                    items = [items] if items else []

            # Truncate to save LLM tokens (max 10 items per keyword)
            items = items[:10]
            if not items:
                continue

            # Strip huge nested fields and truncate strings to avoid LLM context errors
            def _truncate_strings(obj: Any) -> Any:
                if isinstance(obj, str):
                    return obj[:1000] + "..." if len(obj) > 1000 else obj
                if isinstance(obj, list):
                    return [_truncate_strings(x) for x in obj]
                if isinstance(obj, dict):
                    # Skip extremely noisy fields common in social APIs
                    return {k: _truncate_strings(v) for k, v in obj.items() if str(k).lower() not in ("media", "media_metadata", "preview", "images", "video_versions", "candidates")}
                return obj
            
            items = _truncate_strings(items)

            # Use LLM to parse the messy JSON array
            try:
                raw_json = json.dumps(items)
                # If the JSON is too massive, this might exceed context, but typical 10 items is ~5-10k tokens
                result = await dynamic_parser_agent.run(raw_json)
                parsed_list: ParsedPostList = result.data

                for parsed in parsed_list.posts:
                    if parsed.external_id not in seen_ids:
                        seen_ids.add(parsed.external_id)
                        
                        post = UnifiedPost(
                            platform=self.platform,
                            external_id=parsed.external_id,
                            author=parsed.author_username,
                            author_id=parsed.author_id,
                            title=parsed.title,
                            body=parsed.body,
                            url=parsed.profile_url,
                            hashtags=parsed.hashtags,
                            upvotes=parsed.upvotes,
                            comments_count=parsed.comments_count,
                            shares=0,
                            views=0,
                            created_at=None,
                            media_urls=[],
                            raw_data={}, # Keep minimal
                        )
                        post.compute_engagement_score()
                        all_posts.append(post)

            except Exception as e:
                logger.warning("Pydantic AI dynamic parsing failed for %s, falling back to legacy: %s", self.platform, e)
                parsed_list = ParsedPostList(posts=[])
                
            # If Pydantic AI failed, try the legacy fallback via LLMService call_json
            if not parsed_list.posts:
                try:
                    from app.services.infrastructure.llm.service import LLMService
                    llm = LLMService()
                    fallback_prompt = (
                        "You are an API parsing assistant. You will be provided with a raw JSON array of items "
                        "extracted from a social media scraper.\n\n"
                        "Extract the relevant data and return a JSON object with a single key 'posts', which is an "
                        "array of objects matching this schema:\n"
                        "- external_id: string (unique ID)\n"
                        "- author_username: string\n"
                        "- author_id: string\n"
                        "- title: string\n"
                        "- body: string\n"
                        "- profile_url: string\n"
                        "- hashtags: array of strings\n"
                        "- upvotes: integer\n"
                        "- comments_count: integer\n\n"
                        "Return only the raw JSON."
                    )
                    payload = llm.call_json(fallback_prompt, json.dumps(items), temperature=0.2)
                    logger.warning("Fallback payload: %s", payload)
                    if payload and isinstance(payload, dict) and "posts" in payload:
                        for p in payload["posts"]:
                            if not isinstance(p, dict):
                                continue
                            if p.get("external_id") not in seen_ids:
                                seen_ids.add(str(p.get("external_id")))
                                post = UnifiedPost(
                                    platform=self.platform,
                                    external_id=str(p.get("external_id", "")),
                                    author=str(p.get("author_username", "")),
                                    author_id=str(p.get("author_id", "")),
                                    title=str(p.get("title", "")),
                                    body=str(p.get("body", "")),
                                    url=str(p.get("profile_url", p.get("url", ""))),
                                    hashtags=p.get("hashtags", []),
                                    upvotes=int(p.get("upvotes") or 0),
                                    comments_count=int(p.get("comments_count") or 0),
                                    shares=0,
                                    views=0,
                                    created_at=None,
                                    media_urls=[],
                                    raw_data={},
                                )
                                post.compute_engagement_score()
                                all_posts.append(post)
                except Exception as fallback_e:
                    logger.error("Legacy dynamic parsing fallback failed: %s", fallback_e)

            # Fallback naive extraction if LLM fails or returns empty list
            if not parsed_list.posts:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    ext_id = str(item.get("id", item.get("name", item.get("pk", ""))))
                    if ext_id and ext_id not in seen_ids:
                        seen_ids.add(ext_id)
                        title = str(item.get("title", item.get("name", "")))
                        body = str(item.get("selftext", item.get("body", item.get("text", ""))))
                        author = str(item.get("author", item.get("username", item.get("author_fullname", "unknown"))))
                        upvotes = int(item.get("ups", item.get("score", item.get("like_count", 0))) or 0)
                        comments = int(item.get("num_comments", item.get("comment_count", 0)) or 0)
                        url = str(item.get("url", item.get("permalink", "")))
                        
                        post = UnifiedPost(
                            platform=self.platform,
                            external_id=ext_id,
                            author=author,
                            author_id=author,
                            title=title,
                            body=body,
                            url=url,
                            hashtags=[],
                            upvotes=upvotes,
                            comments_count=comments,
                            shares=0,
                            views=0,
                            created_at=None,
                            media_urls=[],
                            raw_data={}
                        )
                        post.compute_engagement_score()
                        all_posts.append(post)

            if len(all_posts) >= limit:
                break

        return all_posts[:limit]

    async def get_post_comments(
        self,
        post_id: str,
        *,
        limit: int = 20,
    ) -> list[UnifiedComment]:
        """Fetch comments dynamically if configured."""
        if not self._available or not self.config.get("comments_endpoint"):
            return []

        endpoint = self.config["comments_endpoint"]
        param_name = self.config.get("comments_param_name", "id")
        json_path = self.config["items_json_path"]

        try:
            data = await self._get(endpoint, params={param_name: post_id})
        except RapidAPIError as e:
            logger.error("Failed to fetch comments dynamically for %s: %s", post_id, e)
            return []

        # For comments, we can either use the LLM again or just a naive fallback.
        # To avoid massive token costs for comments, let's just do a naive extraction
        # since comments are standard enough (text, author, likes).
        items = extract_json_path(data, json_path)
        if not isinstance(items, list):
            if isinstance(data, list):
                items = data
            else:
                items = []

        comments = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            
            # Very naive heuristic
            text = item.get("text", item.get("body", item.get("comment", "")))
            if not text:
                continue
                
            c = UnifiedComment(
                platform=self.platform,
                external_id=str(item.get("id", item.get("pk", ""))),
                post_id=post_id,
                author=str(item.get("username", item.get("author", "unknown"))),
                author_id=str(item.get("user_id", "")),
                body=str(text),
                upvotes=int(item.get("like_count", item.get("ups", 0))),
                created_at=None,
                raw_data=item,
            )
            comments.append(c)

        return comments

    async def get_trending(
        self,
        *,
        topic: str | None = None,
        limit: int = 25,
    ) -> list[UnifiedPost]:
        if not self._available:
            return []
        query = topic or "trending"
        return await self.search_posts([query], limit=limit)

    async def health_check(self) -> bool:
        if not self._available:
            return False
        # Do a minimal test call on search
        endpoint = self.config["search_endpoint"]
        param_name = self.config["search_param_name"]
        try:
            await self._get(endpoint, params={param_name: "test"})
            return True
        except Exception:
            return False
