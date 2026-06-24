"""Integration secrets and Reddit account table operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

INTEGRATION_SECRETS_TABLE = "integration_secrets"
REDDIT_ACCOUNTS_TABLE = "reddit_accounts"


# Integration secret operations
def get_integration_secret_by_id(db: Client, secret_id: int) -> dict[str, Any] | None:
    """Get an integration secret by ID."""
    result = db.table(INTEGRATION_SECRETS_TABLE).select("*").eq("id", secret_id).execute()
    return result.data[0] if result.data else None


def list_integration_secrets_for_workspace(db: Client, workspace_id: int) -> list[dict[str, Any]]:
    """List integration secrets for a workspace."""
    result = (
        db.table(INTEGRATION_SECRETS_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .order("created_at", desc=True)
        .execute()
    )
    return list(result.data)


def get_integration_secret_by_provider_and_label(
    db: Client,
    workspace_id: int,
    provider: str,
    label: str,
) -> dict[str, Any] | None:
    """Get an integration secret by workspace, provider, and label."""
    result = (
        db.table(INTEGRATION_SECRETS_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("provider", provider)
        .eq("label", label)
        .execute()
    )
    return result.data[0] if result.data else None


def create_integration_secret(db: Client, secret_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new integration secret."""
    result = db.table(INTEGRATION_SECRETS_TABLE).insert(secret_data).execute()
    return result.data[0]


def update_integration_secret(
    db: Client,
    secret_id: int,
    update_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Update an integration secret."""
    result = db.table(INTEGRATION_SECRETS_TABLE).update(update_data).eq("id", secret_id).execute()
    return result.data[0] if result.data else None


def delete_integration_secret(db: Client, secret_id: int) -> None:
    """Delete an integration secret."""
    db.table(INTEGRATION_SECRETS_TABLE).delete().eq("id", secret_id).execute()


# Reddit account operations
def get_reddit_account_by_id(db: Client, account_id: str) -> dict[str, Any] | None:
    """Get a Reddit account by ID."""
    result = db.table(REDDIT_ACCOUNTS_TABLE).select("*").eq("id", account_id).execute()
    return result.data[0] if result.data else None


def list_reddit_accounts_for_workspace(db: Client, workspace_id: int) -> list[dict[str, Any]]:
    """List Reddit accounts for a workspace."""
    result = (
        db.table(REDDIT_ACCOUNTS_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .order("created_at", desc=True)
        .execute()
    )
    return list(result.data)


def get_reddit_account_by_workspace_and_username(
    db: Client,
    workspace_id: int,
    username: str,
) -> dict[str, Any] | None:
    """Get a Reddit account by workspace ID and username."""
    result = (
        db.table(REDDIT_ACCOUNTS_TABLE)
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("username", username)
        .execute()
    )
    return result.data[0] if result.data else None


def create_reddit_account(db: Client, account_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new Reddit account."""
    result = db.table(REDDIT_ACCOUNTS_TABLE).insert(account_data).execute()
    return result.data[0]


def update_reddit_account(db: Client, account_id: str, update_data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a Reddit account."""
    result = db.table(REDDIT_ACCOUNTS_TABLE).update(update_data).eq("id", account_id).execute()
    return result.data[0] if result.data else None


def delete_reddit_account(db: Client, account_id: str) -> None:
    """Delete a Reddit account."""
    db.table(REDDIT_ACCOUNTS_TABLE).delete().eq("id", account_id).execute()
