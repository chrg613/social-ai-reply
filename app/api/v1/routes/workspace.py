"""Workspace and user profile management endpoints."""
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from postgrest.exceptions import APIError
from supabase import Client

from app.api.v1.deps import (
    ensure_workspace_membership,
    get_active_project,
    get_current_user,
    get_current_workspace,
)
from app.db.supabase_client import get_supabase
from app.db.tables import (
    delete_workspace as delete_workspace_db,
)
from app.db.tables.projects import list_projects_for_workspace
from app.db.tables.system import list_activity_logs_for_workspace
from app.db.tables.users import update_user
from app.db.tables.workspaces import update_workspace
from app.schemas.v1.workspace import (
    NotificationPreferences,
    UserProfileResponse,
    UserProfileUpdateRequest,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["workspace"])

_ALLOWED_NOTIF_KEYS = {"email_notifications", "digest_email", "slack_notifications"}


def _is_missing_column_error(exc: APIError, column: str) -> bool:
    code = (exc.code or "").upper()
    if code == "PGRST204":
        return True
    context = " ".join(part for part in [exc.message, exc.details, exc.hint] if part).lower()
    return "does not exist" in context and column.lower() in context


def _build_notification_prefs(raw: dict | None) -> NotificationPreferences:
    raw = raw or {}
    return NotificationPreferences(
        email_notifications=bool(raw.get("email_notifications", True)),
        digest_email=bool(raw.get("digest_email", False)),
        slack_notifications=bool(raw.get("slack_notifications", False)),
    )


@router.get("/workspace", response_model=WorkspaceResponse)
def get_workspace(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> WorkspaceResponse:
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    return WorkspaceResponse.model_validate(workspace)


@router.patch("/workspace", response_model=WorkspaceResponse)
def update_workspace_endpoint(
    payload: WorkspaceUpdateRequest,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> WorkspaceResponse:
    """Update workspace settings. Only owners can change workspace name."""
    membership = ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    if payload.name is not None and membership.get("role") not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only workspace owners or admins can rename this workspace.")

    updates: dict = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if not updates:
        return WorkspaceResponse.model_validate(workspace)

    updated = update_workspace(supabase, workspace["id"], updates)
    return WorkspaceResponse.model_validate(updated or workspace)


@router.delete("/workspace")
def delete_workspace(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> dict[str, bool]:
    membership = ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    if membership.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only the workspace owner can delete this workspace.")

    delete_workspace_db(supabase, workspace["id"])
    return {"ok": True}


@router.get("/users/me", response_model=UserProfileResponse)
def get_profile(
    current_user: dict = Depends(get_current_user),
) -> UserProfileResponse:
    return UserProfileResponse(
        id=current_user["id"],
        email=current_user["email"],
        full_name=current_user.get("full_name") or "",
        is_active=current_user.get("is_active", True),
        notification_preferences=_build_notification_prefs(current_user.get("notification_preferences")),
        created_at=current_user.get("created_at"),
    )


@router.patch("/users/me", response_model=UserProfileResponse)
def update_profile(
    payload: UserProfileUpdateRequest,
    current_user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> UserProfileResponse:
    """Update the current user's name and notification preferences.

    Email changes are delegated to Supabase Auth and are not handled here.
    """
    updates: dict = {}
    if payload.full_name is not None:
        updates["full_name"] = payload.full_name
    prefs_update = None
    if payload.notification_preferences is not None:
        # Only keep known keys to avoid persisting arbitrary data.
        prefs_update = {k: bool(v) for k, v in payload.notification_preferences.items() if k in _ALLOWED_NOTIF_KEYS}
        updates["notification_preferences"] = prefs_update

    updated = current_user
    if updates:
        try:
            updated = update_user(supabase, current_user["id"], updates) or current_user
        except APIError as exc:
            # If the notification_preferences column doesn't exist yet (old DB
            # schema), fall back to updating just the name so the user's
            # primary change still persists. PostgREST signals an unknown
            # column with error code PGRST204 / "column ... does not exist".
            is_missing_column = prefs_update is not None and _is_missing_column_error(exc, "notification_preferences")
            if is_missing_column:
                logger.warning("notification_preferences column missing; storing name only")
                fallback = {k: v for k, v in updates.items() if k != "notification_preferences"}
                updated = update_user(supabase, current_user["id"], fallback) if fallback else current_user
            else:
                raise
    target = updated or current_user
    return UserProfileResponse(
        id=target["id"],
        email=target["email"],
        full_name=target.get("full_name") or "",
        is_active=target.get("is_active", True),
        notification_preferences=_build_notification_prefs(target.get("notification_preferences")),
        created_at=target.get("created_at"),
    )


@router.get("/activity")
def list_activity(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    items = list_activity_logs_for_workspace(supabase, workspace["id"], limit=limit, offset=offset)
    return {
        "items": [
            {
                "id": a["id"],
                "action": a["action"],
                "entity_type": a.get("entity_type"),
                "entity_id": a.get("entity_id"),
                "metadata": a.get("metadata_json", {}),
                "created_at": a["created_at"] if a.get("created_at") else None,
            }
            for a in items
        ]
    }


@router.get("/usage")
def get_usage(
    project_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])
    selected_project = get_active_project(supabase, workspace["id"], project_id)
    active_project_id = selected_project["id"] if selected_project else None

    from app.services.product.entitlements import count_active_keywords, count_active_subreddits, count_projects

    return {
        "plan": "unlocked",
        "metrics": {
            "projects": {"used": count_projects(supabase, workspace["id"]), "limit": 999999},
            "keywords": {"used": count_active_keywords(supabase, active_project_id) if active_project_id else 0, "limit": 999999},
            "subreddits": {"used": count_active_subreddits(supabase, active_project_id) if active_project_id else 0, "limit": 999999},
        },
    }


@router.get("/workspace/export")
def export_workspace_data(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
) -> Response:
    """Export a JSON bundle of all workspace data the user owns.

    Returns a downloadable JSON file containing workspace, projects, personas,
    keywords, subreddits, opportunities, drafts, and activity. Sensitive data
    like encrypted secrets and integration tokens are deliberately excluded.
    """
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    # Import lazily to avoid circular imports and to keep cold-start cheap.
    from app.db.tables.content import list_post_drafts_for_project, list_reply_drafts_for_project
    from app.db.tables.discovery import (
        list_discovery_keywords_for_project,
        list_monitored_subreddits_for_project,
        list_opportunities_for_project,
        list_personas_for_project,
    )
    from app.db.tables.projects import get_brand_profile_by_project

    projects = list_projects_for_workspace(supabase, workspace["id"])
    activity = list_activity_logs_for_workspace(supabase, workspace["id"], limit=500, offset=0)

    project_exports = []
    for project in projects:
        pid = project["id"]
        brand = get_brand_profile_by_project(supabase, pid)
        project_exports.append(
            {
                "project": project,
                "brand_profile": brand,
                "personas": list_personas_for_project(supabase, pid),
                "keywords": list_discovery_keywords_for_project(supabase, pid),
                "subreddits": list_monitored_subreddits_for_project(supabase, pid),
                "opportunities": list_opportunities_for_project(supabase, pid, limit=500),
                "reply_drafts": list_reply_drafts_for_project(supabase, pid),
                "post_drafts": list_post_drafts_for_project(supabase, pid),
            }
        )

    bundle = {
        "generated_at": _iso_now(),
        "workspace": {
            "id": workspace["id"],
            "name": workspace.get("name"),
            "slug": workspace.get("slug"),
        },
        "exported_by": {"id": current_user["id"], "email": current_user.get("email")},
        "projects": project_exports,
        "activity": activity,
    }

    body = json.dumps(bundle, default=str, indent=2)
    raw_identifier = str(workspace.get("slug") or workspace["id"])
    # Restrict to a safe filename-token alphabet to avoid header / path
    # injection via a malicious workspace slug. Anything outside
    # [a-zA-Z0-9._-] is collapsed to a hyphen; strip leading/trailing
    # dots to block "..".
    sanitized_identifier = re.sub(r"[^A-Za-z0-9._-]", "-", raw_identifier).strip("-.") or "workspace"
    filename = f"signalflow-export-{sanitized_identifier}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _iso_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
