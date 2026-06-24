"""Authentication routes — all identity operations delegate to Supabase Auth.

FastAPI handles business logic (workspace creation, profile records, entitlements)
while Supabase handles credentials, sessions, password resets, and email verification.
"""

import hashlib
import logging

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from supabase import Client

from app.api.v1.deps import (
    _is_token_revoked,
    bearer_scheme,
    ensure_default_project,
    get_current_user,
    workspace_summary,
)
from app.db.supabase_client import get_supabase
from app.db.tables import (
    create_membership,
    create_user,
    create_workspace,
    get_user_by_email,
    get_user_by_supabase_id,
    list_memberships_for_user,
    update_user,
)
from app.db.tables.workspaces import get_workspace_by_id
from app.schemas.v1.auth import (
    AuthRegisterRequest,
    AuthResponse,
    OAuthCompleteRequest,
    UserResponse,
)
from app.services.product.supabase_auth import (
    SupabaseAuthError,
    admin_delete_user,
    extract_user_from_response,
    sign_out,
    sign_up,
    verify_supabase_jwt,
)
from app.utils.datetime import utc_now
from app.utils.slug import unique_slug

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["auth"])


def _workspace_for_user(supabase: Client, user_id: int) -> dict | None:
    """Return the user's canonical (first-joined) workspace.

    Ordering by Membership.id matches deps.get_current_workspace so
    that /auth/me, /auth/oauth-complete and every subsequent
    authenticated request agree on which workspace is the default tenant for
    a multi-workspace user.
    """
    memberships = list_memberships_for_user(supabase, user_id)
    if not memberships:
        return None
    # Get the first workspace by membership order
    return get_workspace_by_id(supabase, memberships[0]["workspace_id"])


def _provision_workspace(supabase: Client, user: dict, workspace_name: str) -> dict:
    """Create workspace, membership, subscription, and default project for a user."""
    # Create workspace
    workspace = create_workspace(
        supabase,
        {
            "name": workspace_name.strip(),
            "slug": unique_slug(supabase, "workspaces", workspace_name),
        },
    )

    # Create membership
    create_membership(
        supabase,
        {
            "workspace_id": workspace["id"],
            "user_id": user["id"],
            "role": "owner",
        },
    )

    # Create default project
    ensure_default_project(supabase, workspace)

    return workspace



@router.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: AuthRegisterRequest, supabase: Client = Depends(get_supabase)) -> AuthResponse:
    """Register a new user with email and password.

    1. Create the identity in Supabase Auth.
    2. Create a local AccountUser record linked by supabase_user_id.
    3. Create workspace, membership, subscription, and default project.
    4. Return Supabase session tokens + local user/workspace info.
    """
    email = payload.email.lower()

    # Check if email already exists
    existing = get_user_by_email(supabase, email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered.")

    try:
        supabase_data = sign_up(email, payload.password, payload.full_name.strip())
    except SupabaseAuthError as exc:
        if exc.status_code == 422 or "already registered" in exc.message.lower():
            raise HTTPException(status_code=409, detail="Email already registered.") from exc
        logger.error("Supabase sign_up failed: %s", exc)
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        raise HTTPException(status_code=502, detail="Authentication service error.") from exc

    sb_user = extract_user_from_response(supabase_data)
    access_token = supabase_data.get("access_token", "")
    refresh_token = supabase_data.get("refresh_token")

    try:
        # Create local user record
        user = {
            "supabase_uid": sb_user.id,
            "email": email,
            "full_name": payload.full_name.strip(),
            "is_active": True,
        }
        from app.db.tables.users import create_user

        user = create_user(supabase, user)

        # Provision workspace
        workspace = _provision_workspace(supabase, user, payload.workspace_name)

    except Exception:
        # Clean up Supabase auth user on failure
        try:
            admin_delete_user(sb_user.id)
        except Exception:
            logger.error("Failed to clean up Supabase user %s after local provisioning failure", sb_user.id)
        raise

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
        workspace=workspace_summary(supabase, workspace, user["id"]),
    )


@router.get("/auth/me", response_model=AuthResponse)
def me(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    supabase: Client = Depends(get_supabase),
) -> AuthResponse:
    """Return the current user's profile and workspace.

    Returns 404 if the user has no local account (e.g. first-time OAuth user
    needing workspace setup).
    """
    raw_token, payload = _verify_bearer(credentials)
    supabase_uid = payload["sub"]

    user = get_user_by_supabase_id(supabase, supabase_uid)

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no_local_account")

    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_deactivated")

    if _is_token_revoked(user, payload, raw_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
        )

    workspace = _workspace_for_user(supabase, user["id"])
    if not workspace:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no workspace.")

    return AuthResponse(
        access_token="",
        user=UserResponse.model_validate(user),
        workspace=workspace_summary(supabase, workspace, user["id"]),
    )


def _verify_bearer(credentials: HTTPAuthorizationCredentials | None) -> tuple[str, dict]:
    """Verify the bearer token and return (raw_token, jwt_payload)."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    try:
        payload = verify_supabase_jwt(credentials.credentials)
    except (jwt.InvalidTokenError, jwt.DecodeError, jwt.ExpiredSignatureError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from exc
    except ValueError as exc:
        logger.error("JWT verification is misconfigured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error verifying JWT: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from exc
    return credentials.credentials, payload


@router.post("/auth/oauth-complete", response_model=AuthResponse)
def oauth_complete(
    payload: OAuthCompleteRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    supabase: Client = Depends(get_supabase),
) -> AuthResponse:
    """Complete OAuth registration by creating a local account and workspace.

    Called after a first-time OAuth user (e.g. Google sign-in) authenticates
    with Supabase but has no local AccountUser record yet.

    Idempotent: if called twice concurrently for the same Supabase user, the
    losing request catches the race condition, re-queries by supabase_user_id,
    and returns the winning row with 200.
    """
    raw_token, jwt_payload = _verify_bearer(credentials)
    supabase_uid = jwt_payload["sub"]
    email = jwt_payload.get("email", "")
    metadata = jwt_payload.get("user_metadata") or {}
    full_name = (
        metadata.get("full_name")
        or metadata.get("name")
        or (email.split("@")[0] if email else "")
    )
    if not full_name.strip():
        full_name = email.split("@")[0] or "User"

    def _respond_existing(existing_user: dict) -> JSONResponse:
        """Return the 200 response for a user that already has a local row."""
        if not existing_user.get("is_active", True):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_deactivated")
        if _is_token_revoked(existing_user, jwt_payload, raw_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired. Please sign in again.",
            )
        # Sync email if changed in Supabase
        if email and email != existing_user["email"]:
            conflict = get_user_by_email(supabase, email)
            if conflict and conflict["id"] != existing_user["id"]:
                raise HTTPException(status_code=409, detail="Email already registered.")
            update_user(supabase, existing_user["id"], {"email": email})

        workspace = _workspace_for_user(supabase, existing_user["id"])
        if not workspace:
            workspace = _provision_workspace(supabase, existing_user, payload.workspace_name)

        return JSONResponse(
            content=AuthResponse(
                access_token="",
                user=UserResponse.model_validate(existing_user),
                workspace=workspace_summary(supabase, workspace, existing_user["id"]),
            ).model_dump(),
            status_code=status.HTTP_200_OK,
        )

    # Return existing account if already provisioned
    existing = get_user_by_supabase_id(supabase, supabase_uid)
    if existing:
        return _respond_existing(existing)

    # Require email from OAuth provider
    if not email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="OAuth provider did not return an email address.",
        )

    # Check if email is already taken
    email_taken = get_user_by_email(supabase, email)
    if email_taken:
        raise HTTPException(status_code=409, detail="Email already registered.")

    # Create new user
    user = create_user(
        supabase,
        {
            "supabase_uid": supabase_uid,
            "email": email,
            "full_name": full_name,
            "is_active": True,
        },
    )

    # Provision workspace
    workspace = _provision_workspace(supabase, user, payload.workspace_name)

    return JSONResponse(
        content=AuthResponse(
            access_token="",
            user=UserResponse.model_validate(user),
            workspace=workspace_summary(supabase, workspace, user["id"]),
        ).model_dump(),
        status_code=status.HTTP_201_CREATED,
    )


@router.post("/auth/logout")
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    current_user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """Sign out — invalidate the session on Supabase side."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")

    raw_token = credentials.credentials
    # Revoke tokens locally
    update_data = {
        "tokens_invalid_before": utc_now().replace(microsecond=0).isoformat(),
        "revoked_access_token_hash": hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
    }
    update_user(supabase, current_user["id"], update_data)

    try:
        sign_out(raw_token)
    except SupabaseAuthError:
        logger.warning("Supabase sign_out failed for user %s", current_user["id"], exc_info=True)
        return {"ok": True, "warning": "Local session revoked but remote sign-out failed."}
    except Exception as exc:
        logger.error("Unexpected error during sign_out for user %s", current_user["id"], exc_info=True)
        raise HTTPException(status_code=502, detail="Remote sign-out failed.") from exc

    return {"ok": True}
