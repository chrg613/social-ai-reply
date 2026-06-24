"""Competitor Intelligence — detect competitor mentions + sentiment."""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

    from app.services.infrastructure.llm.service import LLMService

from app.db.tables.competitors import create_competitor_mention

logger = logging.getLogger(__name__)


def _jsonb_to_list(val: Any) -> list[str]:
    """Convert a JSONB column value (list or comma-separated string) to a Python list."""
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        return [x.strip() for x in val.split(",") if x.strip()]
    return []


def get_project_competitors(db: Client, project_id: int) -> list[str]:
    """Get competitor names from the company profile.

    The ``company_profiles`` table is keyed by ``workspace_id`` (not
    ``project_id``), so we first resolve the workspace from the project.
    """
    # Resolve workspace_id from the project
    proj = db.table("projects").select("workspace_id").eq("id", project_id).execute()
    if not proj.data:
        return []
    workspace_id = proj.data[0]["workspace_id"]

    result = (
        db.table("company_profiles")
        .select("competitors, extracted_competitors")
        .eq("workspace_id", workspace_id)
        .execute()
    )
    if not result.data:
        return []
    profile = result.data[0]
    competitors = _jsonb_to_list(profile.get("competitors"))
    if not competitors:
        competitors = _jsonb_to_list(profile.get("extracted_competitors"))
    return competitors


def detect_competitor_mentions(
    posts: list[dict[str, Any]],
    competitors: list[str],
) -> list[dict[str, Any]]:
    """Fast keyword pass: find posts mentioning any competitor.

    Returns list of dicts: {post: ..., competitor: ..., match_context: ...}
    """
    if not competitors:
        return []

    # Build regex patterns for each competitor
    patterns: dict[str, re.Pattern[str]] = {}
    for comp in competitors:
        comp_clean = comp.strip()
        if len(comp_clean) >= 2:
            patterns[comp_clean] = re.compile(
                r"\b" + re.escape(comp_clean) + r"\b",
                re.IGNORECASE,
            )

    matches: list[dict[str, Any]] = []
    for post in posts:
        text = f"{post.get('title', '')} {post.get('body', '')} {post.get('selftext', '')}".lower()
        for comp_name, pattern in patterns.items():
            match = pattern.search(text)
            if match:
                # Extract context around the match (50 chars before/after)
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end]
                matches.append({
                    "post": post,
                    "competitor": comp_name,
                    "match_context": context,
                })
                break  # One match per post is enough

    logger.info("[competitor_intel] Detected %d competitor mentions in %d posts", len(matches), len(posts))
    return matches


def _keyword_sentiment(post_text: str) -> dict[str, Any]:
    """Simple keyword-based sentiment fallback."""
    text_lower = post_text.lower()
    neg_words = {
        "terrible", "awful", "worst", "horrible", "scam", "fraud", "hate",
        "bad", "poor", "slow", "broken", "useless", "waste", "disappointed",
        "frustrating", "annoying",
    }
    pos_words = {
        "great", "excellent", "love", "amazing", "best", "awesome",
        "fantastic", "perfect", "good", "wonderful",
    }
    neg_count = sum(1 for w in neg_words if w in text_lower)
    pos_count = sum(1 for w in pos_words if w in text_lower)
    if neg_count > pos_count:
        return {"sentiment": "negative", "sentiment_score": -0.5, "complaint_category": None, "complaint_detail": None}
    if pos_count > neg_count:
        return {"sentiment": "positive", "sentiment_score": 0.5, "complaint_category": None, "complaint_detail": None}
    return {"sentiment": "neutral", "sentiment_score": 0.0, "complaint_category": None, "complaint_detail": None}


async def analyze_sentiment(
    post_text: str,
    competitor_name: str,
    llm: LLMService,
) -> dict[str, Any]:
    """Use LLM to classify sentiment and extract complaint details."""
    prompt = f"""Analyze this social media post about the company "{competitor_name}".

Post text:
\"\"\"
{post_text[:1500]}
\"\"\"

Respond with ONLY a JSON object (no markdown, no explanation):
{{
  "sentiment": "negative" or "neutral" or "positive",
  "sentiment_score": float from -1.0 (very negative) to 1.0 (very positive),
  "complaint_category": one of ["support", "pricing", "quality", "reliability", "features", "ux", "delivery", "trust", "none"] or null,
  "complaint_detail": string describing the specific complaint in one sentence, or null
}}"""

    try:
        response = await llm.generate(prompt, max_tokens=200, temperature=0.1)
        # Parse JSON from response
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        result = json.loads(text)
        return {
            "sentiment": result.get("sentiment", "neutral"),
            "sentiment_score": float(result.get("sentiment_score", 0.0)),
            "complaint_category": result.get("complaint_category"),
            "complaint_detail": result.get("complaint_detail"),
        }
    except Exception:
        logger.warning("[competitor_intel] Sentiment analysis failed, using keyword fallback", exc_info=True)
        return _keyword_sentiment(post_text)


async def process_competitor_opportunities(
    db: Client,
    project_id: int,
    posts: list[dict[str, Any]],
    competitors: list[str],
    llm: LLMService | None = None,
) -> list[dict[str, Any]]:
    """Full pipeline: detect → analyze → store competitor mentions.

    Returns the list of created competitor_mention records.
    """
    if not competitors:
        logger.info("[competitor_intel] No competitors configured — skipping")
        return []

    # Step 1: Fast keyword detection
    matches = detect_competitor_mentions(posts, competitors)
    if not matches:
        logger.info("[competitor_intel] No competitor mentions found")
        return []

    logger.info("[competitor_intel] Processing %d competitor mentions", len(matches))

    created: list[dict[str, Any]] = []
    for match in matches:
        post = match["post"]
        competitor = match["competitor"]
        post_text = f"{post.get('title', '')}\n{post.get('body', '')}{post.get('selftext', '')}"

        # Step 2: Sentiment analysis (LLM if available, else keyword fallback)
        if llm:
            analysis = await analyze_sentiment(post_text, competitor, llm)
        else:
            text_lower = post_text.lower()
            neg_words = {
                "terrible", "awful", "worst", "horrible", "scam", "hate",
                "bad", "poor", "slow", "broken", "useless", "disappointed", "frustrating",
            }
            neg_count = sum(1 for w in neg_words if w in text_lower)
            analysis = {
                "sentiment": "negative" if neg_count > 0 else "neutral",
                "sentiment_score": max(-1.0, -0.3 * neg_count) if neg_count else 0.0,
                "complaint_category": None,
                "complaint_detail": None,
            }

        # Step 3: Store the mention
        mention_data: dict[str, Any] = {
            "project_id": project_id,
            "opportunity_id": post.get("opportunity_id"),
            "competitor_name": competitor,
            "sentiment": analysis["sentiment"],
            "sentiment_score": max(-1.0, min(1.0, analysis["sentiment_score"])),
            "complaint_category": analysis.get("complaint_category"),
            "complaint_detail": analysis.get("complaint_detail"),
            "source_platform": post.get("platform", "reddit"),
            "source_url": post.get("url") or post.get("permalink", ""),
            "post_title": (post.get("title") or "")[:500],
            "post_body": (post.get("body") or post.get("selftext") or "")[:2000],
        }

        try:
            mention = create_competitor_mention(db, mention_data)
            created.append(mention)
        except Exception:
            logger.warning("[competitor_intel] Failed to store mention", exc_info=True)

    logger.info(
        "[competitor_intel] Created %d competitor mentions (neg=%d, neutral=%d, pos=%d)",
        len(created),
        sum(1 for m in created if m.get("sentiment") == "negative"),
        sum(1 for m in created if m.get("sentiment") == "neutral"),
        sum(1 for m in created if m.get("sentiment") == "positive"),
    )
    return created
