"""Notification management endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.api.v1.deps import ensure_workspace_membership, get_current_user, get_current_workspace
from app.db.supabase_client import get_supabase
from app.db.tables.system import (
    delete_notification as delete_notification_table,
)
from app.db.tables.system import (
    get_notification_by_id,
    list_notifications_for_workspace,
    update_notification,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["notifications"])


@router.get("/notifications")
def list_notifications(
    limit: int = 20,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """List notifications for current user"""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    # Get all notifications for workspace, then filter for user-specific or global
    # Fetch extra to ensure we have enough after filtering by user
    all_notifications = list_notifications_for_workspace(supabase, workspace["id"], limit=(limit + offset) * 3)
    # Filter for user-specific or global (user_id is None) notifications
    notifications = [
        n for n in all_notifications
        if n.get("user_id") == current_user["id"] or n.get("user_id") is None
    ]
    # Apply pagination
    notifications = notifications[offset:offset + limit]

    # Count unread
    all_for_user = [
        n for n in all_notifications
        if (n.get("user_id") == current_user["id"] or n.get("user_id") is None) and not n.get("is_read", True)
    ]
    unread_count = len(all_for_user)

    return {
        "items": [
            {
                "id": n.get("id"),
                "title": n.get("title", ""),
                "body": n.get("body", ""),
                "message": n.get("body", ""),
                "type": n.get("type", "info"),
                "link": n.get("action_url"),
                "action_url": n.get("action_url"),
                "is_read": n.get("is_read", False),
                "created_at": n.get("created_at"),
            }
            for n in notifications
        ],
        "unread_count": unread_count,
    }


@router.put("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """Mark a notification as read"""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    notification = get_notification_by_id(supabase, notification_id)
    if not notification:
        raise HTTPException(404, "Notification not found.")

    # Verify notification belongs to workspace and user.
    # Workspace-wide notifications (user_id is None) can be modified by any
    # workspace member (Issue #25).
    if notification["workspace_id"] != workspace["id"]:
        raise HTTPException(404, "Notification not found.")
    if notification.get("user_id") is not None and notification["user_id"] != current_user["id"]:
        raise HTTPException(404, "Notification not found.")

    updated = update_notification(supabase, notification_id, {"is_read": True})

    return {"id": updated["id"], "is_read": updated["is_read"]}


@router.put("/notifications/read-all")
def mark_all_read(
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """Mark all notifications as read"""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    # Get all notifications for workspace
    all_notifications = list_notifications_for_workspace(supabase, workspace["id"], limit=1000)
    # Mark all unread notifications visible to this user as read.
    # This includes user-specific and workspace-wide (user_id=None) notifications.
    to_update = [
        n for n in all_notifications
        if (n.get("user_id") == current_user["id"] or n.get("user_id") is None)
        and not n.get("is_read", True)
    ]

    # Update each notification
    for n in to_update:
        update_notification(supabase, n["id"], {"is_read": True})

    return {"success": True, "message": "All notifications marked as read."}


@router.delete("/notifications/{notification_id}")
def delete_notification_endpoint(
    notification_id: int,
    current_user: dict = Depends(get_current_user),
    workspace: dict = Depends(get_current_workspace),
    supabase: Client = Depends(get_supabase),
):
    """Delete a notification"""
    ensure_workspace_membership(supabase, workspace["id"], current_user["id"])

    notification = get_notification_by_id(supabase, notification_id)
    if not notification:
        raise HTTPException(404, "Notification not found.")

    # Verify notification belongs to workspace and user.
    # Workspace-wide notifications (user_id is None) can be deleted by any
    # workspace member (Issue #25).
    if notification["workspace_id"] != workspace["id"]:
        raise HTTPException(404, "Notification not found.")
    if notification.get("user_id") is not None and notification["user_id"] != current_user["id"]:
        raise HTTPException(404, "Notification not found.")

    delete_notification_table(supabase, notification_id)

    return {"success": True, "message": "Notification deleted."}
