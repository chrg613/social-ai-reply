"""API tests for auth endpoints with Supabase integration.

In test mode, we mock Supabase auth by:
1. Overriding verify_supabase_jwt to accept test tokens
2. Creating test data directly via table helper functions
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import get_supabase
from app.db.tables.users import get_user_by_email
from app.main import app
from app.services.product.supabase_auth import SupabaseAuthError
from tests.conftest import _create_test_user, _make_test_token


@pytest.fixture
def client(mock_supabase):
    """Provide a FastAPI TestClient with Supabase dependency overridden.

    Supabase JWT mocking is handled by the autouse ``mock_supabase_auth``
    fixture in conftest.py — no need to duplicate the patch here.
    """
    def override_get_supabase():
        try:
            yield mock_supabase
        finally:
            pass

    app.dependency_overrides.clear()
    app.dependency_overrides[get_supabase] = override_get_supabase

    yield TestClient(app)

    app.dependency_overrides.clear()


def _mock_supabase_signup(email, password, full_name):
    """Mock for supabase_auth.sign_up that returns a fake Supabase response."""
    uid = str(uuid.uuid4())
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


class TestRegister:
    @patch("app.api.v1.routes.auth.sign_up", side_effect=_mock_supabase_signup)
    def test_register_success(self, mock_signup, client, mock_supabase):
        resp = client.post("/v1/auth/register", json={
            "email": "new@example.com",
            "password": "strongpass123",
            "full_name": "New User",
            "workspace_name": "New WS",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["email"] == "new@example.com"
        assert "supabase_uid" in data["user"]
        user = get_user_by_email(mock_supabase, "new@example.com")
        assert user is not None
        assert user["supabase_uid"] is not None

    @patch("app.api.v1.routes.auth.sign_up", side_effect=_mock_supabase_signup)
    def test_register_duplicate_email(self, mock_signup, client, mock_supabase):
        payload = {
            "email": "dup@example.com",
            "password": "strongpass123",
            "full_name": "Dup User",
            "workspace_name": "Dup WS",
        }
        client.post("/v1/auth/register", json=payload)
        resp = client.post("/v1/auth/register", json=payload)
        assert resp.status_code == 409

    def test_register_missing_fields(self, client):
        resp = client.post("/v1/auth/register", json={"email": "a@b.com"})
        assert resp.status_code == 422

    def test_register_rejects_existing_email(self, client, mock_supabase):
        """Registration must reject emails that already exist locally."""
        _create_test_user(mock_supabase, "existing@example.com", "Existing User", "Existing WS")

        resp = client.post("/v1/auth/register", json={
            "email": "existing@example.com",
            "password": "strongpass123",
            "full_name": "Existing User",
            "workspace_name": "New Workspace",
        })

        assert resp.status_code == 409

    @patch(
        "app.api.v1.routes.auth.sign_up",
        side_effect=SupabaseAuthError(
            503,
            "SUPABASE_SECRET_KEY is not configured. Email/password registration requires the service role key.",
        ),
    )
    def test_register_preserves_service_unavailable_errors(self, _mock_signup, client):
        resp = client.post("/v1/auth/register", json={
            "email": "new@example.com",
            "password": "strongpass123",
            "full_name": "New User",
            "workspace_name": "New WS",
        })

        assert resp.status_code == 503
        assert "SUPABASE_SECRET_KEY is not configured" in resp.json()["detail"]


class TestMe:
    def test_me_with_valid_token(self, client, mock_supabase):
        data = _create_test_user(mock_supabase, "me@example.com", "Me User", "Me WS")
        token = data["access_token"]
        resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == "me@example.com"

    def test_me_without_token(self, client):
        resp = client.get("/v1/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token(self, client):
        resp = client.get("/v1/auth/me", headers={"Authorization": "Bearer invalid-token-here"})
        assert resp.status_code == 401

    def test_me_returns_404_for_unknown_user(self, client, mock_supabase):
        """When a JWT is valid but no local user exists, /auth/me should return
        404 with 'no_local_account' to signal the OAuth setup flow."""
        supabase_uid = str(uuid.uuid4())

        with patch(
            "app.api.v1.routes.auth.verify_supabase_jwt",
            return_value={
                "sub": supabase_uid,
                "aud": "authenticated",
                "exp": 9999999999,
                "iat": 1000000000,
                "email": "unknown@example.com",
                "role": "authenticated",
            },
        ):
            resp = client.get("/v1/auth/me", headers={"Authorization": "Bearer test-token"})

        assert resp.status_code == 404
        assert resp.json()["detail"] == "no_local_account"


class TestOAuthComplete:
    def test_oauth_complete_creates_user_and_workspace(self, client, mock_supabase):
        supabase_uid = str(uuid.uuid4())

        with patch(
            "app.api.v1.routes.auth.verify_supabase_jwt",
            return_value={
                "sub": supabase_uid,
                "aud": "authenticated",
                "exp": 9999999999,
                "iat": 1000000000,
                "email": "oauth@example.com",
                "role": "authenticated",
                "user_metadata": {"full_name": "OAuth User"},
            },
        ):
            resp = client.post(
                "/v1/auth/oauth-complete",
                json={"workspace_name": "OAuth Workspace"},
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["user"]["email"] == "oauth@example.com"
        assert data["user"]["supabase_uid"] == supabase_uid
        assert data["workspace"]["name"] == "OAuth Workspace"

        user = get_user_by_email(mock_supabase, "oauth@example.com")
        assert user is not None
        assert user["supabase_uid"] == supabase_uid
        assert user["full_name"] == "OAuth User"

    def test_oauth_complete_rejects_duplicate_email(self, client, mock_supabase):
        """OAuth complete should reject if email is already taken by another account."""
        _create_test_user(mock_supabase, "taken@example.com", "Taken User", "Taken WS")
        supabase_uid = str(uuid.uuid4())

        with patch(
            "app.api.v1.routes.auth.verify_supabase_jwt",
            return_value={
                "sub": supabase_uid,
                "aud": "authenticated",
                "exp": 9999999999,
                "iat": 1000000000,
                "email": "taken@example.com",
                "role": "authenticated",
                "user_metadata": {"full_name": "Another User"},
            },
        ):
            resp = client.post(
                "/v1/auth/oauth-complete",
                json={"workspace_name": "New WS"},
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 409

    def test_oauth_complete_requires_auth(self, client):
        resp = client.post("/v1/auth/oauth-complete", json={"workspace_name": "Test WS"})
        assert resp.status_code == 401

    def test_oauth_complete_requires_workspace_name(self, client, mock_supabase):
        supabase_uid = str(uuid.uuid4())

        with patch(
            "app.api.v1.routes.auth.verify_supabase_jwt",
            return_value={
                "sub": supabase_uid,
                "aud": "authenticated",
                "exp": 9999999999,
                "iat": 1000000000,
                "email": "test@example.com",
                "role": "authenticated",
            },
        ):
            resp = client.post(
                "/v1/auth/oauth-complete",
                json={},
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 422

    def test_oauth_complete_rejects_empty_email(self, client, mock_supabase):
        """OAuth provider that returns an empty email must be rejected with
        422 — we cannot persist a user row whose email would violate
        UserResponse.email: EmailStr or the AccountUser.email UNIQUE
        constraint."""
        supabase_uid = str(uuid.uuid4())

        with patch(
            "app.api.v1.routes.auth.verify_supabase_jwt",
            return_value={
                "sub": supabase_uid,
                "aud": "authenticated",
                "exp": 9999999999,
                "iat": 1000000000,
                "email": "",  # provider returned empty email
                "role": "authenticated",
                "user_metadata": {"full_name": "No Email User"},
            },
        ):
            resp = client.post(
                "/v1/auth/oauth-complete",
                json={"workspace_name": "No Email WS"},
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 422
        assert "email" in resp.json()["detail"].lower()
        # Ensure no orphaned row was written.
        user = get_user_by_email(mock_supabase, "no-email@example.com")
        assert user is None

    def test_oauth_complete_rejects_missing_email_key(self, client, mock_supabase):
        """Same guard when the email key is absent from the JWT claims
        (exercises the jwt_payload.get('email', '') default path)."""
        supabase_uid = str(uuid.uuid4())

        with patch(
            "app.api.v1.routes.auth.verify_supabase_jwt",
            return_value={
                "sub": supabase_uid,
                "aud": "authenticated",
                "exp": 9999999999,
                "iat": 1000000000,
                # no "email" key at all
                "role": "authenticated",
                "user_metadata": {"full_name": "No Email User"},
            },
        ):
            resp = client.post(
                "/v1/auth/oauth-complete",
                json={"workspace_name": "No Email WS"},
                headers={"Authorization": "Bearer test-token"},
            )

        assert resp.status_code == 422
        user = get_user_by_email(mock_supabase, "no-email@example.com")
        assert user is None

    def test_oauth_complete_idempotent_repeat_returns_200(self, client, mock_supabase):
        """Calling oauth-complete twice with the same supabase_uid should
        return 201 on the first call and 200 on the second (no new row, no
        duplicate workspace)."""
        supabase_uid = str(uuid.uuid4())
        claims = {
            "sub": supabase_uid,
            "aud": "authenticated",
            "exp": 9999999999,
            "iat": 1000000000,
            "email": "idem@example.com",
            "role": "authenticated",
            "user_metadata": {"full_name": "Idem User"},
        }

        with patch("app.api.v1.routes.auth.verify_supabase_jwt", return_value=claims):
            first = client.post(
                "/v1/auth/oauth-complete",
                json={"workspace_name": "Idem WS"},
                headers={"Authorization": "Bearer test-token"},
            )
            second = client.post(
                "/v1/auth/oauth-complete",
                json={"workspace_name": "Idem WS Two"},  # deliberately different
                headers={"Authorization": "Bearer test-token"},
            )

        assert first.status_code == 201
        assert second.status_code == 200
        # Same user id on both responses.
        assert first.json()["user"]["id"] == second.json()["user"]["id"]
        # Workspace is the one from the first call — second call must NOT
        # provision a second workspace with the new name.
        assert second.json()["workspace"]["name"] == "Idem WS"


class TestLogout:
    @patch("app.api.v1.routes.auth.sign_out")
    def test_logout_revokes_current_token(self, mock_sign_out, client, mock_supabase):
        data = _create_test_user(mock_supabase, "logout@example.com", "Logout User", "Logout WS")
        token = data["access_token"]

        resp = client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        mock_sign_out.assert_called_once_with(token)

        follow_up = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert follow_up.status_code == 401
        assert follow_up.json()["detail"] == "Session expired. Please sign in again."

    def test_logout_requires_auth(self, client):
        resp = client.post("/v1/auth/logout")
        assert resp.status_code == 401


class TestDeactivatedUser:
    def test_me_rejects_deactivated_user(self, client, mock_supabase):
        """Deactivated users must not be able to access /auth/me."""
        data = _create_test_user(mock_supabase, "deactivated@example.com", "Deactivated", "Deactivated WS")
        user = get_user_by_email(mock_supabase, "deactivated@example.com")
        # Update user to inactive
        mock_supabase.table("account_users").update({"is_active": False}).eq("id", user["id"]).execute()

        resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "account_deactivated"
