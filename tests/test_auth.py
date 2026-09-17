"""Tests for shani-gui auth manager.

Note: keyring storage is not yet implemented (TODO in auth.py).
Tests verify in-memory behavior. Keyring integration tests will be
added once roadmap item for keyring storage lands.
"""

import json
import time

import httpx
import pytest

from shani_gui.auth import AuthManager


class MockTransport(httpx.BaseTransport):
    """Mock transport for HTTP tests."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        url = str(request.url)
        if url in self.responses:
            status_code, data = self.responses[url]
            return httpx.Response(
                status_code=status_code, json=data, request=request
            )
        return httpx.Response(
            status_code=404, json={"error": "not found"}, request=request
        )

    def close(self):
        pass


class TestAuthManagerConstruction:
    """Test AuthManager initialization."""

    def test_auth_manager_instantiation(self):
        """AuthManager can be constructed."""
        am = AuthManager()
        assert am is not None
        assert am._access_token is None
        assert am._refresh_token is None
        assert am._token_expiry == 0
        assert am._org_id is None
        assert am._username is None
        assert am._is_authenticated is False

    def test_auth_manager_custom_base_url(self):
        """AuthManager accepts custom base_url."""
        am = AuthManager(base_url="http://localhost:8080")
        assert am._base_url == "http://localhost:8080"

    def test_auth_manager_clears_credentials_on_init(self):
        """AuthManager starts with no credentials."""
        am = AuthManager()
        assert am._access_token is None
        assert not am._is_authenticated


class TestAuthManagerLogin:
    """Test AuthManager login/logout flow."""

    def test_login_success(self):
        """Login with valid credentials sets tokens."""
        transport = MockTransport({
            "http://localhost:9999/auth/login": (200, {
                "access_token": "tok-abc",
                "refresh_token": "tok-refresh",
                "expires_in": 3600,
                "org_id": "org-1",
            }),
        })
        am = AuthManager(base_url="http://localhost:9999")
        am._http_client = httpx.Client(transport=transport)

        result = am.login("user", "pass")
        assert result is True
        assert am._access_token == "tok-abc"
        assert am._refresh_token == "tok-refresh"
        assert am._is_authenticated is True
        assert am._org_id == "org-1"
        assert am._username == "user"

    def test_login_failure(self):
        """Login with invalid credentials returns False."""
        transport = MockTransport({
            "http://localhost:9999/auth/login": (401, {"error": "invalid"}),
        })
        am = AuthManager(base_url="http://localhost:9999")
        am._http_client = httpx.Client(transport=transport)

        result = am.login("bad", "creds")
        assert result is False
        assert am._is_authenticated is False
        assert am._access_token is None

    def test_login_clears_credentials_on_failure(self):
        """Failed login clears credentials."""
        transport = MockTransport({
            "http://localhost:9999/auth/login": (401, {"error": "invalid"}),
        })
        am = AuthManager(base_url="http://localhost:9999")
        am._http_client = httpx.Client(transport=transport)
        am._access_token = "old-token"
        am._is_authenticated = True

        am.login("bad", "creds")
        assert am._access_token is None
        assert not am._is_authenticated

    def test_login_sends_correct_payload(self):
        """Login sends username and password in JSON body."""
        transport = MockTransport({
            "http://localhost:9999/auth/login": (200, {"access_token": "tok"}),
        })
        am = AuthManager(base_url="http://localhost:9999")
        am._http_client = httpx.Client(transport=transport)

        am.login("testuser", "testpass")
        assert len(transport.requests) == 1
        req = transport.requests[0]
        body = json.loads(req.content)
        assert body["username"] == "testuser"
        assert body["password"] == "testpass"

    def test_login_saves_credentials(self):
        """Login calls _save_credentials."""
        transport = MockTransport({
            "http://localhost:9999/auth/login": (200, {"access_token": "tok"}),
        })
        am = AuthManager(base_url="http://localhost:9999")
        am._http_client = httpx.Client(transport=transport)
        am._save_credentials = pytest.MagicMock()

        am.login("user", "pass")
        am._save_credentials.assert_called_once()


class TestAuthManagerLogout:
    """Test AuthManager logout."""

    def test_logout_clears_credentials(self):
        """Logout clears all credentials."""
        am = AuthManager(base_url="http://localhost:9999")
        am._access_token = "tok-abc"
        am._refresh_token = "tok-refresh"
        am._is_authenticated = True
        am._username = "user"
        am._org_id = "org-1"

        am.logout()
        assert am._access_token is None
        assert am._refresh_token is None
        assert am._is_authenticated is False
        assert am._username is None
        assert am._org_id is None

    def test_logout_without_token(self):
        """Logout works when no token is set."""
        am = AuthManager(base_url="http://localhost:9999")
        am.logout()


class TestAuthManagerIsAuthenticated:
    """Test AuthManager authentication state."""

    def test_not_authenticated_by_default(self):
        """New AuthManager is not authenticated."""
        am = AuthManager()
        assert not am.is_authenticated()

    def test_authenticated_after_login(self):
        """is_authenticated returns True after login."""
        am = AuthManager()
        am._is_authenticated = True
        assert am.is_authenticated()

    def test_expired_token(self):
        """is_authenticated returns False for expired token."""
        am = AuthManager()
        am._is_authenticated = True
        am._token_expiry = 0
        assert not am.is_authenticated()

    def test_future_token(self):
        """is_authenticated returns True for future token."""
        am = AuthManager()
        am._is_authenticated = True
        am._token_expiry = time.time() + 3600
        assert am.is_authenticated()


class TestAuthManagerGetters:
    """Test AuthManager getter methods."""

    def test_get_access_token_authenticated(self):
        """get_access_token returns token when authenticated."""
        am = AuthManager()
        am._access_token = "my-token"
        am._is_authenticated = True
        assert am.get_access_token() == "my-token"

    def test_get_access_token_not_authenticated(self):
        """get_access_token returns None when not authenticated."""
        am = AuthManager()
        am._access_token = "my-token"
        am._is_authenticated = False
        assert am.get_access_token() is None

    def test_get_access_token_expired(self):
        """get_access_token returns None when token expired."""
        am = AuthManager()
        am._access_token = "my-token"
        am._is_authenticated = True
        am._token_expiry = 0
        assert am.get_access_token() is None

    def test_get_org_id(self):
        """get_org_id returns org_id when authenticated."""
        am = AuthManager()
        am._org_id = "org-1"
        am._is_authenticated = True
        assert am.get_org_id() == "org-1"

    def test_get_org_id_not_authenticated(self):
        """get_org_id returns None when not authenticated."""
        am = AuthManager()
        am._org_id = "org-1"
        assert am.get_org_id() is None

    def test_get_username(self):
        """get_username returns username when authenticated."""
        am = AuthManager()
        am._username = "testuser"
        am._is_authenticated = True
        assert am.get_username() == "testuser"

    def test_get_username_not_authenticated(self):
        """get_username returns None when not authenticated."""
        am = AuthManager()
        am._username = "testuser"
        assert am.get_username() is None


class TestAuthManagerRefreshToken:
    """Test AuthManager token refresh."""

    def test_refresh_no_refresh_token(self):
        """Refresh returns False when no refresh token."""
        am = AuthManager()
        assert am.refresh_token() is False

    def test_refresh_success(self):
        """Refresh updates tokens on success."""
        transport = MockTransport({
            "http://localhost:9999/auth/refresh": (200, {
                "access_token": "new-tok",
                "expires_in": 7200,
            }),
        })
        am = AuthManager(base_url="http://localhost:9999")
        am._refresh_token = "old-refresh"
        am._http_client = httpx.Client(transport=transport)

        result = am.refresh_token()
        assert result is True
        assert am._access_token == "new-tok"

    def test_refresh_failure(self):
        """Refresh returns False on failure."""
        transport = MockTransport({
            "http://localhost:9999/auth/refresh": (401, {"error": "invalid"}),
        })
        am = AuthManager(base_url="http://localhost:9999")
        am._refresh_token = "old-refresh"
        am._http_client = httpx.Client(transport=transport)

        result = am.refresh_token()
        assert result is False


class TestAuthManagerClose:
    """Test AuthManager close method."""

    def test_close(self):
        """close() does not raise."""
        am = AuthManager()
        am.close()
