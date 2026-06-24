"""Workspace, membership, invitation, and subscription table operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from postgrest.exceptions import APIError

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

WORKSPACES_TABLE = "workspaces"
MEMBERSHIPS_TABLE = "memberships"
INVITATIONS_TABLE = "invitations"
SUBSCRIPTIONS_TABLE = "subscriptions"
PLAN_ENTITLEMENTS_TABLE = "plan_entitlements"
REDEMPTIONS_TABLE = "redemptions"


# Workspace operations
def get_workspace_by_id(db: Client, workspace_id: int) -> dict[str, Any] | None:
    """Get a workspace by ID."""
    result = db.table(WORKSPACES_TABLE).select("*").eq("id", workspace_id).execute()
    return result.data[0] if result.data else None


def get_workspace_by_slug(db: Client, slug: str) -> dict[str, Any] | None:
    """Get a workspace by slug."""
    result = db.table(WORKSPACES_TABLE).select("*").eq("slug", slug).execute()
    return result.data[0] if result.data else None


def create_workspace(db: Client, workspace_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new workspace."""
    result = db.table(WORKSPACES_TABLE).insert(workspace_data).execute()
    return result.data[0]


def update_workspace(db: Client, workspace_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a workspace."""
    result = db.table(WORKSPACES_TABLE).update(update_data).eq("id", workspace_id).execute()
    return result.data[0] if result.data else None


def delete_workspace(db: Client, workspace_id: int) -> None:
    """Delete a workspace."""
    db.table(WORKSPACES_TABLE).delete().eq("id", workspace_id).execute()


def list_workspaces_for_user(db: Client, user_id: int) -> list[dict[str, Any]]:
    """List all workspaces a user belongs to."""
    # Get memberships first
    memberships_result = db.table(MEMBERSHIPS_TABLE).select("workspace_id").eq("user_id", user_id).execute()
    workspace_ids = [m["workspace_id"] for m in memberships_result.data]

    if not workspace_ids:
        return []

    result = db.table(WORKSPACES_TABLE).select("*").in_("id", workspace_ids).execute()
    return list(result.data)


# Membership operations
def get_membership(db: Client, workspace_id: int, user_id: int) -> dict[str, Any] | None:
    """Get a membership by workspace and user ID."""
    result = (
        db.table(MEMBERSHIPS_TABLE).select("*").eq("workspace_id", workspace_id).eq("user_id", user_id).execute()
    )
    return result.data[0] if result.data else None


def get_membership_by_id(db: Client, membership_id: int) -> dict[str, Any] | None:
    """Get a membership by ID."""
    result = db.table(MEMBERSHIPS_TABLE).select("*").eq("id", membership_id).execute()
    return result.data[0] if result.data else None


def create_membership(db: Client, membership_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new membership."""
    result = db.table(MEMBERSHIPS_TABLE).insert(membership_data).execute()
    return result.data[0]


def update_membership(db: Client, membership_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a membership."""
    result = db.table(MEMBERSHIPS_TABLE).update(update_data).eq("id", membership_id).execute()
    return result.data[0] if result.data else None


def delete_membership(db: Client, membership_id: int) -> None:
    """Delete a membership."""
    db.table(MEMBERSHIPS_TABLE).delete().eq("id", membership_id).execute()


def list_memberships_for_workspace(db: Client, workspace_id: int) -> list[dict[str, Any]]:
    """List all memberships in a workspace."""
    result = db.table(MEMBERSHIPS_TABLE).select("*").eq("workspace_id", workspace_id).execute()
    return list(result.data)


def list_memberships_for_user(db: Client, user_id: int) -> list[dict[str, Any]]:
    """List all memberships for a user."""
    result = db.table(MEMBERSHIPS_TABLE).select("*").eq("user_id", user_id).execute()
    return list(result.data)


# Invitation operations
def get_invitation_by_token(db: Client, token: str) -> dict[str, Any] | None:
    """Get an invitation by token."""
    result = db.table(INVITATIONS_TABLE).select("*").eq("token", token).execute()
    return result.data[0] if result.data else None


def get_invitation_by_id(db: Client, invitation_id: str) -> dict[str, Any] | None:
    """Get an invitation by ID."""
    result = db.table(INVITATIONS_TABLE).select("*").eq("id", invitation_id).execute()
    return result.data[0] if result.data else None


def create_invitation(db: Client, invitation_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new invitation."""
    result = db.table(INVITATIONS_TABLE).insert(invitation_data).execute()
    return result.data[0]


def update_invitation(db: Client, invitation_id: str, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update an invitation."""
    result = db.table(INVITATIONS_TABLE).update(update_data).eq("id", invitation_id).execute()
    return result.data[0] if result.data else None


def delete_invitation(db: Client, invitation_id: str) -> None:
    """Delete an invitation."""
    db.table(INVITATIONS_TABLE).delete().eq("id", invitation_id).execute()


def list_invitations_for_workspace(db: Client, workspace_id: int) -> list[dict[str, Any]]:
    """List all invitations for a workspace."""
    result = db.table(INVITATIONS_TABLE).select("*").eq("workspace_id", workspace_id).execute()
    return list(result.data)


def get_invitation_by_workspace_and_email(
    db: Client,
    workspace_id: int,
    email: str,
) -> dict[str, Any] | None:
    """Get an invitation by workspace ID and email."""
    result = (
        db.table(INVITATIONS_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("email", email)
        .execute()
    )
    return result.data[0] if result.data else None


def get_membership_by_user_and_workspace(
    db: Client,
    user_id: int,
    workspace_id: int,
) -> dict[str, Any] | None:
    """Get a membership by user ID and workspace ID."""
    result = (
        db.table(MEMBERSHIPS_TABLE)
        .select("*")
        .eq("user_id", user_id)
        .eq("workspace_id", workspace_id)
        .execute()
    )
    return result.data[0] if result.data else None


# Subscription operations
def get_subscription_by_workspace(db: Client, workspace_id: int) -> dict[str, Any] | None:
    """Get a subscription by workspace ID."""
    try:
        result = db.table(SUBSCRIPTIONS_TABLE).select("*").eq("workspace_id", workspace_id).execute()
        return result.data[0] if result.data else None
    except APIError:
        logger.warning("subscriptions table not found — returning None")
        return None


def get_subscription_by_id(db: Client, subscription_id: int) -> dict[str, Any] | None:
    """Get a subscription by ID."""
    try:
        result = db.table(SUBSCRIPTIONS_TABLE).select("*").eq("id", subscription_id).execute()
        return result.data[0] if result.data else None
    except APIError:
        logger.warning("subscriptions table not found — returning None")
        return None


def create_subscription(db: Client, subscription_data: dict[str, Any]) -> dict[str, Any] | None:
    """Create a new subscription."""
    try:
        result = db.table(SUBSCRIPTIONS_TABLE).insert(subscription_data).execute()
        return result.data[0]
    except APIError:
        logger.warning("subscriptions table not found — skipping insert")
        return None


def update_subscription(db: Client, subscription_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a subscription."""
    try:
        result = db.table(SUBSCRIPTIONS_TABLE).update(update_data).eq("id", subscription_id).execute()
        return result.data[0] if result.data else None
    except APIError:
        logger.warning("subscriptions table not found — skipping update")
        return None


def delete_subscription(db: Client, subscription_id: int) -> None:
    """Delete a subscription."""
    try:
        db.table(SUBSCRIPTIONS_TABLE).delete().eq("id", subscription_id).execute()
    except APIError:
        logger.warning("subscriptions table not found — skipping delete")


# Plan entitlements operations
def get_plan_entitlements(db: Client, plan_code: str) -> list[dict[str, Any]]:
    """Get all entitlements for a plan."""
    try:
        result = db.table(PLAN_ENTITLEMENTS_TABLE).select("*").eq("plan_code", plan_code).execute()
        return list(result.data)
    except APIError:
        logger.warning("plan_entitlements table not found — returning empty list")
        return []


def get_entitlement(db: Client, plan_code: str, feature_key: str) -> dict[str, Any] | None:
    """Get a specific entitlement for a plan and feature."""
    try:
        result = (
            db.table(PLAN_ENTITLEMENTS_TABLE)
            .select("*")
            .eq("plan_code", plan_code)
            .eq("feature_key", feature_key)
            .execute()
        )
        return result.data[0] if result.data else None
    except APIError:
        logger.warning("plan_entitlements table not found — returning None")
        return None


# Redemption operations
def get_redemption_by_code(db: Client, code: str) -> dict[str, Any] | None:
    """Get a redemption by code."""
    try:
        result = db.table(REDEMPTIONS_TABLE).select("*").eq("code", code).execute()
        return result.data[0] if result.data else None
    except APIError:
        logger.warning("redemptions table not found — returning None")
        return None


def create_redemption(db: Client, redemption_data: dict[str, Any]) -> dict[str, Any] | None:
    """Create a new redemption."""
    try:
        result = db.table(REDEMPTIONS_TABLE).insert(redemption_data).execute()
        return result.data[0]
    except APIError:
        logger.warning("redemptions table not found — skipping insert")
        return None


def update_redemption(db: Client, redemption_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a redemption."""
    try:
        result = db.table(REDEMPTIONS_TABLE).update(update_data).eq("id", redemption_id).execute()
        return result.data[0] if result.data else None
    except APIError:
        logger.warning("redemptions table not found — skipping update")
        return None
