"""Dependency injection helpers for authenticated routes.

This module provides dependencies for getting the current user, workspace,
project, and other shared resources. All database operations use the Supabase client.
"""

import hashlib
import logging
from datetime import UTC, datetime

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client

from app.db.supabase_client import get_supabase
from app.db.tables.projects import (
    create_brand_profile,
    create_project,
    create_prompt_template,
    get_project_by_id,
    list_prompt_templates_for_project,
)
from app.db.tables.users import get_user_by_supabase_id
from app.db.tables.workspaces import (
    get_membership,
    get_subscription_by_workspace,
    get_workspace_by_id,
    list_memberships_for_user,
)
from app.schemas.v1.auth import WorkspaceSummary
from app.schemas.v1.billing import SubscriptionResponse
from app.services.product.entitlements import PLAN_CATALOG, feature_set
from app.services.product.supabase_auth import JWKSUnavailableError, verify_supabase_jwt
from app.utils.slug import unique_slug as _unique_slug

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


def _issued_at_utc(payload: dict) -> datetime | None:
    """Extract issued-at timestamp from JWT payload."""
    raw_value = payload.get("iat")
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value.astimezone(UTC) if raw_value.tzinfo else raw_value.replace(tzinfo=UTC)
    try:
        return datetime.fromtimestamp(float(raw_value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _coerce_utc(value: datetime) -> datetime:
    """Coerce datetime to UTC."""
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _token_hash(token: str) -> str:
    """Generate SHA256 hash of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_token_revoked(user: dict, payload: dict, token: str) -> bool:
    """Check if a token has been revoked."""
    if user.get("revoked_access_token_hash") and _token_hash(token) == user["revoked_access_token_hash"]:
        return True
    if not user.get("tokens_invalid_before"):
        return False
    issued_at = _issued_at_utc(payload)
    if issued_at is None:
        return True
    tokens_invalid_before = user["tokens_invalid_before"]
    # Handle both datetime objects and ISO strings
    if isinstance(tokens_invalid_before, str):
        try:
            tokens_invalid_before = datetime.fromisoformat(tokens_invalid_before.replace("Z", "+00:00"))
        except ValueError:
            return True
    return issued_at < _coerce_utc(tokens_invalid_before)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """Validate the Supabase JWT and return the local user record.

    The token's `sub` claim contains the Supabase user UUID which maps
    to our local account_users table.

    Returns:
        User record dict with keys: id, supabase_user_id, email, full_name, is_active, etc.
    """
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    try:
        payload = verify_supabase_jwt(credentials.credentials)
        supabase_uid = payload["sub"]
    except JWKSUnavailableError as exc:
        logger.error("JWKS unavailable while verifying JWT: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from exc
    except (jwt.InvalidTokenError, jwt.DecodeError, jwt.ExpiredSignatureError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from exc
    except Exception as exc:
        logger.error("Unexpected error verifying JWT: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from exc

    user = get_user_by_supabase_id(supabase, supabase_uid)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account is deactivated.")
    if _is_token_revoked(user, payload, credentials.credentials):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please sign in again.")
    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    supabase: Client = Depends(get_supabase),
) -> dict | None:
    """Like get_current_user but returns None instead of raising when unauthenticated."""
    if not credentials:
        return None
    try:
        payload = verify_supabase_jwt(credentials.credentials)
        supabase_uid = payload["sub"]
    except (jwt.InvalidTokenError, jwt.DecodeError, jwt.ExpiredSignatureError, ValueError):
        return None
    except Exception:
        logger.error("Unexpected error verifying JWT in optional auth")
        return None

    user = get_user_by_supabase_id(supabase, supabase_uid)
    if not user or not user.get("is_active", True):
        return None
    if _is_token_revoked(user, payload, credentials.credentials):
        return None
    return user


def get_current_workspace(
    current_user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """Get the current user's primary workspace.

    Returns the first workspace the user belongs to (by membership ID order).
    This maintains backward compatibility with the existing UX.

    Returns:
        Workspace record dict with keys: id, name, slug, owner_user_id, etc.
    """
    memberships = list_memberships_for_user(supabase, current_user["id"])
    if not memberships:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No workspace membership found.")

    # Get the first workspace (by membership order)
    workspace = get_workspace_by_id(supabase, memberships[0]["workspace_id"])
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return workspace


# ── Shared query helpers ──────────────────────────────────────────


def ensure_workspace_membership(
    supabase: Client,
    workspace_id: int,
    user_id: int,
) -> dict:
    """Ensure a user has membership in a workspace."""
    membership = get_membership(supabase, workspace_id, user_id)
    if not membership:
        raise HTTPException(status_code=403, detail="You do not have access to this workspace.")
    return membership


def get_project(
    supabase: Client,
    workspace_id: int,
    project_id: int,
) -> dict:
    """Get a project by ID, ensuring it belongs to the workspace."""
    project = get_project_by_id(supabase, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    if project["workspace_id"] != workspace_id:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def get_active_project(
    supabase: Client,
    workspace_id: int,
    project_id: int | None = None,
) -> dict | None:
    """Get the active project, either by ID or the most recent one."""
    from app.db.tables.projects import list_projects_for_workspace

    if project_id is not None:
        project = get_project_by_id(supabase, project_id)
        if project and project["workspace_id"] == workspace_id and project.get("status") == "active":
            return project

    # Get most recent active project
    projects = list_projects_for_workspace(supabase, workspace_id)
    for project in projects:
        if project.get("status") == "active":
            return project
    return None


def ensure_default_project(supabase: Client, workspace: dict) -> dict:
    """Ensure a default project exists for the workspace."""
    project = get_active_project(supabase, workspace["id"])
    if project:
        return project

    base_name = (workspace.get("name") or "").strip() or "Default"
    if not base_name.lower().endswith("project"):
        base_name = f"{base_name} Project"

    # Generate unique slug
    slug = _unique_slug(supabase, "projects", base_name, "workspace_id", workspace["id"])

    project_data = {
        "workspace_id": workspace["id"],
        "name": base_name,
        "slug": slug,
        "status": "active",
        "description": None,
    }
    project = create_project(supabase, project_data)

    # Create brand profile
    brand_profile_data = {
        "project_id": project["id"],
        "brand_name": project["name"],
        "summary": None,
        "voice_notes": None,
        "product_summary": None,
        "target_audience": None,
        "call_to_action": None,
        "business_domain": None,
        "linkedin_url": None,
    }
    create_brand_profile(supabase, brand_profile_data)

    # Ensure default prompts
    ensure_default_prompts(supabase, project["id"])

    return get_project_by_id(supabase, project["id"]) or project


def ensure_default_prompts(supabase: Client, project_id: int) -> None:
    """Ensure default prompt templates exist for a project."""
    defaults = [
        {
            "prompt_type": "reply",
            "name": "Helpful Reply",
            "system_prompt": "You write grounded Reddit replies that help first and pitch never.",
            "instructions": "Start with empathy, answer the actual question, avoid hard CTAs, and only mention the product when invited.",
        },
        {
            "prompt_type": "post",
            "name": "Educational Post",
            "system_prompt": "You write Reddit posts that teach from direct experience.",
            "instructions": "Use first-hand lessons, concrete examples, and end with an invitation for discussion rather than a promo CTA.",
        },
        {
            "prompt_type": "analysis",
            "name": "Signal Review",
            "system_prompt": "You summarize opportunities with clarity and no fluff.",
            "instructions": "Highlight why the thread matters, what the risk is, and how the brand can contribute credibly.",
        },
    ]

    existing = list_prompt_templates_for_project(supabase, project_id)
    existing_types = {p.get("prompt_type") or p.get("type") for p in existing}

    for prompt in defaults:
        if prompt["prompt_type"] not in existing_types:
            prompt_data = {
                **prompt,
                "project_id": project_id,
            }
            create_prompt_template(supabase, prompt_data)


def workspace_summary(supabase: Client, workspace: dict, user_id: int) -> WorkspaceSummary:
    """Build workspace summary response."""
    membership = ensure_workspace_membership(supabase, workspace["id"], user_id)
    return WorkspaceSummary(
        id=workspace["id"],
        name=workspace["name"],
        slug=workspace["slug"],
        role=membership.get("role", "member"),
    )


def subscription_response(supabase: Client, workspace: dict) -> SubscriptionResponse:
    """Build subscription response."""
    subscription = get_subscription_by_workspace(supabase, workspace["id"])
    if not subscription:
        # Create default subscription
        from app.db.tables.workspaces import create_subscription

        subscription = create_subscription(
            supabase,
            {
                "workspace_id": workspace["id"],
                "plan_code": "free",
                "status": "active",
            },
        )

    plan = next((plan for plan in PLAN_CATALOG if plan["code"] == subscription["plan_code"]), PLAN_CATALOG[0])
    return SubscriptionResponse(
        plan_code=subscription["plan_code"],
        status=subscription["status"],
        current_period_end=subscription.get("current_period_end"),
        features=list(feature_set(subscription["plan_code"])),
        limits=dict(plan["limits"]),
    )


def build_subreddit_analysis(
    name: str,
    description: str,
    rules: list[str],
) -> tuple[list[str], list[str], list[str], str]:
    """Build subreddit analysis from name, description, and rules."""
    text = f"{name} {description}".lower()
    top_post_types = []
    if "help" in text or "question" in text:
        top_post_types.append("questions")
    if "case study" in text or "showcase" in text:
        top_post_types.append("case studies")
    if not top_post_types:
        top_post_types = ["discussion", "advice"]

    audience_signals = []
    if "startup" in text or "founder" in text:
        audience_signals.append("founders")
    if "marketing" in text or "growth" in text:
        audience_signals.append("marketers")
    if "saas" in text or "software" in text:
        audience_signals.append("software buyers")
    if not audience_signals:
        audience_signals = ["broad interest audience"]

    recommendation = "Engage with helpful, specific replies and avoid promotional language."
    posting_risk = [rule for rule in rules[:5]]
    return top_post_types, audience_signals, posting_risk, recommendation
