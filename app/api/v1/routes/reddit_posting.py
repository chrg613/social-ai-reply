"""Reddit OAuth, posting, and published post endpoints."""
import logging
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_active_project,
    get_current_user,
    get_current_workspace,
)
from app.core.config import get_settings
from app.db.supabase_client import get_supabase
from app.db.tables.campaigns import (
    create_published_post,
    get_published_post_by_id,
    list_published_posts_for_project,
    update_published_post,
)
from app.db.tables.projects import get_project_by_id
from app.schemas.v1.reddit import (
    PublishedPostItem,
    PublishedPostListResponse,
    PublishedPostStatusResponse,
    RedditAccountListResponse,
    RedditAccountResponse,
    RedditCallbackRequest,
    RedditConnectRequest,
    RedditConnectResponse,
    RedditPostRequest,
    RedditPostResponse,
)
from app.services.product.account_safety import (
    assess_account_safety,
    check_shadowban,
    compute_posting_budget,
    get_account_activity,
    parse_timestamp,
)
from app.services.product.reddit import RedditClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["reddit-posting"])

# In-memory store for pending OAuth state tokens: state → (workspace_id, expires_at_unix).
# Reddit OAuth is short-lived (few minutes) so in-memory is acceptable in single-worker
# deployments. Multi-worker deployments should front this with Redis; the helpers below
# are isolated so that migration is a drop-in change.
_STATE_TTL_SECONDS = 10 * 60
_state_lock = threading.Lock()
_pending_oauth_states: dict[str, tuple[int, float]] = {}


def _reap_expired_states() -> None:
    now = time.time()
    expired = [s for s, (_, exp) in _pending_oauth_states.items() if exp < now]
    for s in expired:
        _pending_oauth_states.pop(s, None)


def _remember_state(state: str, workspace_id: int) -> None:
    with _state_lock:
        _reap_expired_states()
        _pending_oauth_states[state] = (workspace_id, time.time() + _STATE_TTL_SECONDS)


def _consume_state(state: str) -> int | None:
    with _state_lock:
        _reap_expired_states()
        entry = _pending_oauth_states.pop(state, None)
    if entry is None:
        return None
    workspace_id, _expires_at = entry
    return workspace_id


REDDIT_SCOPES = "identity,submit,edit,read,history"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_IDENTITY_URL = "https://oauth.reddit.com/api/v1/me"


def _exchange_authorization_code(code: str) -> dict:
    """Exchange an OAuth authorization code for Reddit access/refresh tokens.

    Raises HTTPException on configuration or exchange failure. Returns the
    parsed Reddit token response on success, which contains ``access_token``,
    ``token_type``, ``expires_in``, ``scope``, and ``refresh_token`` (when
    ``duration=permanent`` was requested during authorization).
    """
    settings = get_settings()
    if not settings.reddit_client_id or not settings.reddit_client_secret or not settings.reddit_redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reddit OAuth is not fully configured (client id / secret / redirect URI missing).",
        )
    user_agent = getattr(settings, "reddit_user_agent", None) or "SignalFlow/1.0"
    try:
        resp = httpx.post(
            REDDIT_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.reddit_redirect_uri,
            },
            auth=(settings.reddit_client_id, settings.reddit_client_secret),
            headers={"User-Agent": user_agent},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        logger.warning("Reddit token exchange transport failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Reddit to exchange the authorization code.",
        ) from exc
    if resp.status_code >= 400:
        logger.warning("Reddit token exchange returned %s: %s", resp.status_code, resp.text[:300])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reddit rejected the authorization code. Please reconnect your account.",
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Reddit returned an unparseable token response.",
        ) from exc
    if data.get("error") or not data.get("access_token"):
        logger.warning("Reddit token exchange returned error payload: %s", data)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reddit did not return an access token. Please reconnect.",
        )
    return data


def _fetch_reddit_identity(access_token: str) -> dict:
    """Fetch the Reddit identity for the freshly-issued access token.

    Best-effort: if identity lookup fails we return an empty dict and the
    caller falls back to whatever the client advertised as the username.
    """
    settings = get_settings()
    user_agent = getattr(settings, "reddit_user_agent", None) or "SignalFlow/1.0"
    try:
        resp = httpx.get(
            REDDIT_IDENTITY_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": user_agent,
            },
            timeout=10.0,
        )
        if resp.status_code >= 400:
            logger.info("Reddit identity lookup returned %s", resp.status_code)
            return {}
        return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    except httpx.HTTPError as exc:
        logger.info("Reddit identity lookup failed: %s", exc)
        return {}


def _truncate_text(raw: str | None, max_len: int = 100) -> str:
    text = raw or ""
    return text if len(text) <= max_len else text[:max_len] + "..."


@router.post("/reddit/connect", response_model=RedditConnectResponse)
def initiate_reddit_oauth(
    payload: RedditConnectRequest | None = None,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> RedditConnectResponse:
    """Initiate Reddit OAuth connection."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    settings = get_settings()
    if not settings.reddit_client_id or not settings.reddit_redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Reddit OAuth is not configured for this deployment. Set REDDIT_CLIENT_ID, "
                "REDDIT_CLIENT_SECRET, and REDDIT_REDIRECT_URI environment variables on the backend."
            ),
        )

    state = secrets.token_urlsafe(32)
    _remember_state(state, workspace["id"])

    params = {
        "client_id": settings.reddit_client_id,
        "response_type": "code",
        "state": state,
        "redirect_uri": settings.reddit_redirect_uri,
        "duration": "permanent",
        "scope": REDDIT_SCOPES,
    }
    reddit_auth_url = f"https://www.reddit.com/api/v1/authorize?{urlencode(params)}"
    return RedditConnectResponse(auth_url=reddit_auth_url, state=state)


@router.post("/reddit/callback", response_model=RedditAccountResponse)
def handle_reddit_callback(
    payload: RedditCallbackRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> RedditAccountResponse:
    """Handle Reddit OAuth callback."""
    from app.db.tables.integrations import create_reddit_account
    from app.utils.encryption import encrypt_text

    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    expected_wid = _consume_state(payload.state)
    if expected_wid is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter.")
    if expected_wid != workspace["id"]:
        raise HTTPException(status_code=403, detail="State mismatch for this workspace.")

    # Exchange the one-shot authorization code for an access/refresh token
    # pair. This MUST happen before persisting anything to the database —
    # Reddit's authorization codes are single-use and short-lived, so storing
    # the raw code instead of the exchanged token would make posting
    # impossible.
    token_payload = _exchange_authorization_code(payload.code)
    access_token: str = token_payload["access_token"]
    refresh_token: str | None = token_payload.get("refresh_token")
    expires_in = int(token_payload.get("expires_in") or 3600)
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    granted_scope = token_payload.get("scope") or REDDIT_SCOPES

    # Pull the canonical username from Reddit so we don't trust the
    # client-supplied value. Fall back if the identity call fails.
    identity = _fetch_reddit_identity(access_token)
    username = (identity.get("name") or payload.username or "connected_account")[:255]
    karma = int(identity.get("total_karma") or 0) if identity else 0

    account_data: dict = {
        "workspace_id": workspace["id"],
        "username": username,
        "access_token": encrypt_text(access_token),
        "is_active": True,
        "karma": karma,
    }
    # Only populate refresh_token/expires_at when the columns exist. If the
    # DB schema is older, fall back to the minimal payload so the connect
    # still succeeds; callers will re-auth on expiry.
    if refresh_token:
        account_data["refresh_token"] = encrypt_text(refresh_token)
    account_data["token_expires_at"] = expires_at.isoformat()
    account_data["scope"] = granted_scope

    try:
        reddit = create_reddit_account(supabase, account_data)
    except Exception as exc:
        logger.exception("Failed to persist Reddit account")
        raise HTTPException(
            status_code=500,
            detail="Failed to connect Reddit account. Please try again.",
        ) from exc

    return RedditAccountResponse(
        id=reddit["id"],
        username=reddit["username"],
        karma=reddit.get("karma", 0),
        is_active=reddit.get("is_active", True),
        connected_at=reddit.get("created_at"),
        message="Reddit account connected successfully.",
    )


@router.get("/reddit/accounts", response_model=RedditAccountListResponse)
def list_reddit_accounts(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> RedditAccountListResponse:
    """List connected Reddit accounts."""
    from app.db.tables.integrations import list_reddit_accounts_for_workspace

    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    accounts = list_reddit_accounts_for_workspace(supabase, workspace["id"])
    return RedditAccountListResponse(
        items=[
            RedditAccountResponse(
                id=acc["id"],
                username=acc["username"],
                karma=acc.get("karma", 0),
                is_active=acc.get("is_active", True),
                connected_at=acc.get("created_at"),
            )
            for acc in accounts
        ]
    )


@router.delete("/reddit/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reddit_account(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """Delete a connected Reddit account."""
    from app.db.tables.integrations import delete_reddit_account as _delete
    from app.db.tables.integrations import get_reddit_account_by_id

    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    account = get_reddit_account_by_id(supabase, account_id)
    if not account or account["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Reddit account not found.")
    _delete(supabase, account_id)


@router.get("/reddit/accounts/{account_id}/safety")
def get_account_safety(
    account_id: str,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """Assess posting safety for a connected Reddit account.

    Returns the warm-up budget, recent activity counts, a 0-100 safety score,
    and warnings. The shadowban probe runs at most once per hour per account
    (tracked via ``last_safety_check_at``).
    """
    from app.core.constants.limits import SAFETY_SHADOWBAN_CHECK_INTERVAL_SECONDS
    from app.db.tables.integrations import get_reddit_account_by_id, update_reddit_account

    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    account = get_reddit_account_by_id(supabase, account_id)
    if not account or account["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Reddit account not found.")

    now = datetime.now(UTC)
    last_check = parse_timestamp(account.get("last_safety_check_at"))
    if last_check is None or (now - last_check).total_seconds() >= SAFETY_SHADOWBAN_CHECK_INTERVAL_SECONDS:
        suspected = check_shadowban(account)
        update_payload: dict = {"last_safety_check_at": now.isoformat()}
        if suspected is not None:
            account["shadowban_suspected"] = suspected
            update_payload["shadowban_suspected"] = suspected
        try:
            update_reddit_account(supabase, str(account["id"]), update_payload)
        except Exception:
            # Best-effort persistence: the safety columns may not exist yet if
            # the 20260610_03 migration hasn't been applied. The assessment
            # below still works off the in-memory account dict.
            logger.warning("Could not persist safety-check results for Reddit account %s", account_id, exc_info=True)

    return assess_account_safety(supabase, account, now=now)


@router.post("/reddit/post", response_model=RedditPostResponse)
def post_to_reddit(
    payload: RedditPostRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> RedditPostResponse:
    """Post a comment or thread to Reddit."""
    from app.db.tables.integrations import get_reddit_account_by_id
    from app.db.tables.system import create_notification

    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    if payload.type == "post" and not payload.title:
        raise HTTPException(status_code=400, detail="Title is required when posting a new thread.")
    if payload.type == "comment" and not payload.parent_post_id:
        raise HTTPException(status_code=400, detail="parent_post_id is required when posting a comment.")

    account = get_reddit_account_by_id(supabase, str(payload.reddit_account_id))
    if not account or account["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Reddit account not found.")

    proj = get_project_by_id(supabase, payload.project_id)
    if not proj or proj["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Project not found.")

    # Account-safety guard: enforce the warm-up daily cap unless the caller
    # explicitly overrides it.
    if not payload.override_safety:
        budget = compute_posting_budget(account)
        activity = get_account_activity(supabase, account["id"])
        if activity["posted_today"] >= budget["daily_cap"]:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Account safety: u/{account['username']} has already posted "
                    f"{activity['posted_today']} time(s) today, meeting its daily cap of "
                    f"{budget['daily_cap']} (warm-up tier '{budget['tier']}'). Posting more today risks "
                    'spam filters or a shadowban. Wait until tomorrow, or resend with "override_safety": true '
                    "to post anyway."
                ),
            )

    try:
        reddit = RedditClient()
        if payload.type == "comment":
            reddit_id = reddit.post_comment(payload.subreddit, payload.parent_post_id, payload.content)
            permalink = f"https://reddit.com/r/{payload.subreddit}/comments/{payload.parent_post_id}/"
        else:
            reddit_id = reddit.post_thread(payload.subreddit, payload.title or "", payload.content)
            permalink = f"https://reddit.com/r/{payload.subreddit}/comments/{reddit_id}/"

        published = create_published_post(
            supabase,
            {
                "project_id": proj["id"],
                "campaign_id": payload.campaign_id,
                "reddit_account_id": account["id"],
                "type": payload.type,
                "reddit_id": reddit_id,
                "subreddit": payload.subreddit,
                "title": payload.title,
                "content": payload.content,
                "permalink": permalink,
                "parent_post_id": payload.parent_post_id if payload.type == "comment" else None,
                "status": "published",
            },
        )

        create_notification(
            supabase,
            {
                "workspace_id": workspace["id"],
                "user_id": current_user["id"],
                "title": f"Posted to r/{payload.subreddit}",
                "body": f"Your {payload.type} has been successfully published.",
                "type": "opportunity",
                "action_url": permalink,
            },
        )

        return RedditPostResponse(
            id=published["id"],
            type=published["type"],
            subreddit=published["subreddit"],
            permalink=published["permalink"],
            status=published["status"],
            published_at=published.get("published_at"),
        )
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail=(
                "Automated Reddit posting is not yet available. "
                "Copy the draft and post it manually — we'll enable auto-posting soon."
            ),
        ) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to publish Reddit post")
        raise HTTPException(status_code=500, detail="Failed to post to Reddit. Please try again later.") from None


@router.get("/reddit/published", response_model=PublishedPostListResponse)
def list_published_posts(
    project_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> PublishedPostListResponse:
    """List published posts with status."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    proj = get_active_project(supabase, workspace["id"], project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="No active project found.")

    published_posts = list_published_posts_for_project(supabase, proj["id"])
    published_posts = published_posts[offset : offset + limit]

    return PublishedPostListResponse(
        items=[
            PublishedPostItem(
                id=p["id"],
                type=p["type"],
                subreddit=p["subreddit"],
                title=p.get("title") or "",
                content=_truncate_text(p.get("content")),
                status=p.get("status", "published"),
                upvotes=p.get("upvotes", 0),
                permalink=p["permalink"],
                published_at=p.get("published_at"),
            )
            for p in published_posts
        ]
    )


@router.post("/reddit/published/{post_id}/check", response_model=PublishedPostStatusResponse)
def check_published_status(
    post_id: str,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> PublishedPostStatusResponse:
    """Check current status of a published post."""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    published = get_published_post_by_id(supabase, post_id)
    if not published:
        raise HTTPException(status_code=404, detail="Published post not found.")

    proj = get_project_by_id(supabase, published["project_id"])
    if not proj or proj["workspace_id"] != workspace["id"]:
        raise HTTPException(status_code=404, detail="Published post not found.")

    try:
        reddit = RedditClient()
        post_stats = reddit.get_post_stats(published["reddit_id"])
        if post_stats:
            update_published_post(
                supabase,
                post_id,
                {
                    "upvotes": post_stats.get("upvotes", 0),
                    "last_checked_at": datetime.now(UTC).isoformat(),
                },
            )
            if post_stats.get("removed"):
                update_published_post(
                    supabase,
                    post_id,
                    {
                        "status": "removed",
                        "removal_reason": post_stats.get("removal_reason"),
                    },
                )
            # Re-fetch to return the latest values without an extra round-trip if possible
            published = get_published_post_by_id(supabase, post_id) or published

        return PublishedPostStatusResponse(
            id=published["id"],
            status=published.get("status", "published"),
            upvotes=published.get("upvotes", 0),
            last_checked_at=published.get("last_checked_at"),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to check Reddit post status")
        raise HTTPException(status_code=502, detail="Failed to check post status on Reddit.") from None
