"""Shared test fixtures and configuration.

In test mode, we mock Supabase by:
1. Overriding verify_supabase_jwt to accept test tokens
2. Using a mock Supabase client with in-memory storage
3. Creating test data directly via table helper functions
"""

import uuid
from datetime import UTC
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from app.db.tables.users import create_user
from app.db.tables.workspaces import (
    create_membership,
    create_subscription,
    create_workspace,
)
from app.main import app
from app.middleware import reset_rate_limit_store

# ── Test token helpers ───────────────────────────────────────────

def _make_test_token(supabase_user_id: str) -> str:
    """Create a simple test token that encodes the Supabase user ID."""
    return f"test-token-{supabase_user_id}"


def _mock_verify_supabase_jwt(token: str) -> dict:
    """Mock JWT verifier for tests.

    Accepts tokens in the format 'test-token-<supabase_user_id>' and
    returns a payload matching what Supabase would return.
    """
    if not token.startswith("test-token-"):
        raise jwt.InvalidTokenError("Invalid test token")
    supabase_uid = token.removeprefix("test-token-")
    return {
        "sub": supabase_uid,
        "aud": "authenticated",
        "exp": 9999999999,
        "iat": 1000000000,
        "email": f"{supabase_uid}@test.local",
        "role": "authenticated",
    }


def _make_mock_supabase_signup():
    """Create a test-local Supabase signup mock with stable IDs per email."""
    email_to_uid: dict[str, str] = {}

    def _mock_supabase_signup(email: str, password: str, full_name: str) -> dict:
        del password
        uid = email_to_uid.setdefault(email, str(uuid.uuid4()))
        return {
            "access_token": _make_test_token(uid),
            "refresh_token": f"refresh-{uid}",
            "user": {
                "id": uid,
                "email": email,
                "email_confirmed_at": "2025-01-01T00:00:00Z",
                "user_metadata": {"full_name": full_name},
            },
        }

    return _mock_supabase_signup


# ── Mock Supabase Client ────────────────────────────────────────────


class MockSupabaseClient:
    """In-memory mock Supabase client for tests.

    Provides a table() method that returns a mock query builder.
    All data is stored in memory and reset between tests.
    """

    def __init__(self):
        self._tables: dict[str, list[dict]] = {}
        self._reset()

    def _reset(self):
        """Clear all tables."""
        self._tables = {
            "account_users": [],
            "workspaces": [],
            "memberships": [],
            "subscriptions": [],
            "projects": [],
            "brand_profiles": [],
            "prompt_templates": [],
            "personas_v1": [],
            "discovery_keywords": [],
            "monitored_subreddits": [],
            "opportunities": [],
            "reply_drafts": [],
            "post_drafts": [],
            "prompt_sets": [],
            "prompt_runs": [],
            "ai_responses": [],
            "brand_mentions": [],
            "citations": [],
            "source_domains": [],
            "source_gaps": [],
            "campaigns": [],
            "published_posts": [],
            "webhook_endpoints": [],
            "integration_secrets": [],
            "reddit_accounts": [],
            "notifications": [],
            "activity_logs": [],
            "usage_metrics": [],
            "analytics_snapshots": [],
            "visibility_snapshots": [],
            "audit_events": [],
            "auto_pipelines": [],
            "invitations": [],
            "scan_runs": [],
        }

    def table(self, name: str):
        """Return a mock query builder for the table."""
        return MockTableQuery(self._tables.get(name, []), self._tables, name)

    def reset(self):
        """Reset all data."""
        self._reset()


class MockTableQuery:
    """Mock query builder for Supabase table operations."""

    def __init__(self, data: list[dict], all_tables: dict[str, list[dict]], table_name: str):
        self._data = data
        self._all_tables = all_tables
        self._table_name = table_name
        self._filters: list[tuple] = []
        self._order_by: str | None = None
        self._order_desc: bool = False
        self._limit: int | None = None
        self._offset: int | None = None
        self._count: bool = False

    def select(self, columns: str = "*", count: str | None = None):
        """Select columns."""
        self._count = count == "exact"
        return self

    def eq(self, field: str, value):
        """Add equality filter."""
        self._filters.append(("eq", field, value))
        return self

    def neq(self, field: str, value):
        """Add not-equal filter."""
        self._filters.append(("neq", field, value))
        return self

    def in_(self, field: str, values: list):
        """Add IN filter."""
        self._filters.append(("in", field, values))
        return self

    def order(self, field: str, desc: bool = False):
        """Add ordering."""
        self._order_by = field
        self._order_desc = desc
        return self

    def limit(self, n: int):
        """Add limit."""
        self._limit = n
        return self

    def range(self, start: int, end: int):
        """Add range (pagination)."""
        self._offset = start
        self._limit = end - start + 1
        return self

    def insert(self, data):
        """Insert data."""
        from datetime import datetime

        if isinstance(data, dict):
            data = [data]
        self._insert_data = []
        for item in data:
            if "id" not in item:
                item["id"] = len(self._data) + 1
            # Special handling for scan_runs - id should be string
            if self._table_name == "scan_runs":
                item["id"] = str(item["id"]) if not isinstance(item["id"], str) else item["id"]
                if "search_window_hours" not in item:
                    item["search_window_hours"] = 24
                if "error_message" not in item:
                    item["error_message"] = None
                if "started_at" not in item:
                    item["started_at"] = datetime.now(UTC).isoformat()
                if "finished_at" not in item:
                    item["finished_at"] = datetime.now(UTC).isoformat()
            # Add timestamps if not present
            if "created_at" not in item:
                item["created_at"] = datetime.now(UTC).isoformat()
            if "updated_at" not in item:
                item["updated_at"] = datetime.now(UTC).isoformat()
            # Add table-specific defaults
            if self._table_name == "account_users" and "is_active" not in item:
                item["is_active"] = True
            if self._table_name == "brand_profiles" and "last_analyzed_at" not in item:
                item["last_analyzed_at"] = None
            if self._table_name == "opportunities" and "posted_at" not in item:
                item["posted_at"] = None
            self._data.append(item)
            self._insert_data.append(item)
        return self

    def update(self, data):
        """Store update data to be applied on execute()."""
        self._update_data = data
        return self

    def delete(self):
        """Delete matching records."""
        for item in self._apply_filters():
            self._data.remove(item)
        return self

    def execute(self):
        """Execute the query and return results."""
        # For insert operations, return only the inserted data
        if hasattr(self, "_insert_data") and self._insert_data:
            response = MagicMock()
            response.data = self._insert_data
            response.count = len(self._insert_data) if self._count else None
            return response

        result = self._apply_filters()

        # Apply ordering
        if self._order_by:
            result = sorted(
                result,
                key=lambda x: x.get(self._order_by, ""),
                reverse=self._order_desc
            )

        # Apply pagination
        if self._offset:
            result = result[self._offset:]
        if self._limit:
            result = result[:self._limit]

        # Apply update if update_data was set
        if hasattr(self, "_update_data"):
            for item in result:
                item.update(self._update_data)

        response = MagicMock()
        response.data = result
        response.count = len(result) if self._count else None
        return response

    def _apply_filters(self):
        """Apply all filters to data."""
        result = list(self._data)

        for op, field, value in self._filters:
            if op == "eq":
                result = [r for r in result if r.get(field) == value]
            elif op == "neq":
                result = [r for r in result if r.get(field) != value]
            elif op == "in":
                result = [r for r in result if r.get(field) in value]

        return result


@pytest.fixture
def mock_supabase():
    """Provide a mock Supabase client for tests."""
    client = MockSupabaseClient()
    yield client
    client.reset()


# ── Test fixtures ────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Keep the in-memory rate limiter isolated across tests."""
    reset_rate_limit_store()
    yield
    reset_rate_limit_store()


@pytest.fixture(autouse=True)
def stub_llm_stage_refinement():
    """Keep scans offline: never call a real LLM for buying-stage refinement."""
    with patch("app.services.product.scanner.refine_stages_with_llm", return_value={}):
        yield


@pytest.fixture(autouse=True)
def mock_supabase_auth():
    """Keep the test suite offline by mocking auth verification + signup."""
    with (
        patch("app.api.v1.deps.verify_supabase_jwt", side_effect=_mock_verify_supabase_jwt),
        patch("app.api.v1.routes.auth.verify_supabase_jwt", side_effect=_mock_verify_supabase_jwt),
        patch("app.api.v1.routes.auth.sign_up", side_effect=_make_mock_supabase_signup()),
    ):
        yield


# nplusone: detect N+1 query patterns in tests
nplusone = None
try:
    import nplusone.ext.pytest  # noqa: F401
    nplusone = True
except ImportError:
    pass


def _create_test_user(mock_supabase, email: str, full_name: str, workspace_name: str) -> dict:
    """Create a user + workspace + membership directly in the DB."""
    supabase_uid = str(uuid.uuid4())

    # Create user
    user_data = {
        "supabase_uid": supabase_uid,
        "email": email,
        "full_name": full_name,
    }
    user = create_user(mock_supabase, user_data)

    # Create workspace
    workspace_data = {
        "name": workspace_name,
        "slug": f"{workspace_name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
    }
    workspace = create_workspace(mock_supabase, workspace_data)

    # Create membership
    create_membership(
        mock_supabase,
        {
            "workspace_id": workspace["id"],
            "user_id": user["id"],
            "role": "owner",
        }
    )

    # Create subscription
    create_subscription(
        mock_supabase,
        {
            "workspace_id": workspace["id"],
            "plan_code": "free",
            "status": "active",
        }
    )

    token = _make_test_token(supabase_uid)

    return {
        "access_token": token,
        "refresh_token": None,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "supabase_user_id": supabase_uid,
            "email": email,
            "full_name": full_name,
            "is_active": True,
        },
        "workspace": {
            "id": workspace["id"],
            "name": workspace["name"],
            "slug": workspace["slug"],
            "role": "owner",
        },
    }


@pytest.fixture
def client(mock_supabase):
    """Provide a FastAPI TestClient with Supabase dependency overridden.

    Use authed_client for tests that need authentication.
    """
    from app.api.v1.deps import get_supabase as deps_get_supabase

    def override_get_supabase():
        try:
            yield mock_supabase
        finally:
            pass

    app.dependency_overrides.clear()
    app.dependency_overrides[deps_get_supabase] = override_get_supabase

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def authed_client(mock_supabase):
    """Client with a registered user and valid auth headers.

    This fixture overrides all dependencies including get_current_user
    and get_current_workspace to work with the mock Supabase client.
    """
    from app.api.v1.deps import get_current_user, get_current_workspace
    from app.api.v1.deps import get_supabase as deps_get_supabase

    # Create test user data
    user_data_dict = _create_test_user(mock_supabase, "test@example.com", "Test User", "Test Workspace")
    token = user_data_dict["access_token"]

    # Set up dependency overrides
    def override_get_supabase():
        try:
            yield mock_supabase
        finally:
            pass

    def override_get_current_user():
        return user_data_dict["user"]

    def override_get_current_workspace():
        return user_data_dict["workspace"]

    app.dependency_overrides.clear()
    app.dependency_overrides[deps_get_supabase] = override_get_supabase
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_current_workspace] = override_get_current_workspace

    test_client = TestClient(app)
    test_client.headers.update({"Authorization": f"Bearer {token}"})

    yield test_client, user_data_dict

    app.dependency_overrides.clear()
