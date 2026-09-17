"""Tests for shani-gui API client with mocked HTTP responses."""

import json
import pytest
import httpx
from unittest.mock import MagicMock, call

from shani_gui.auth import AuthManager
from shani_gui.api_client import APIClient


class MockTransport(httpx.BaseTransport):
    """Mock transport that returns canned responses for HTTP tests."""

    def __init__(self, responses=None):
        """Initialize with a dict of URL -> response data.

        Args:
            responses: Dict mapping URLs to (status_code, json_data) tuples
        """
        super().__init__()
        self.responses = responses or {}
        self.requests = []

    def handle_request(self, request):
        """Return a mocked response."""
        self.requests.append(request)
        url = str(request.url)

        if url in self.responses:
            status_code, data = self.responses[url]
            return httpx.Response(
                status_code=status_code,
                json=data,
                request=request,
            )

        return httpx.Response(
            status_code=404,
            json={"error": "not found"},
            request=request,
        )

    def close(self):
        pass


class TestAPIClientConstruction:
    """Test APIClient initialization."""

    def test_api_client_instantiation(self, auth_manager):
        """APIClient can be constructed with auth_manager."""
        client = APIClient(auth_manager)
        assert client is not None
        assert client._base_url == "https://platform.shani.dev"

    def test_api_client_custom_base_url(self, auth_manager):
        """APIClient accepts custom base_url."""
        client = APIClient(auth_manager, base_url="http://localhost:8080")
        assert client._base_url == "http://localhost:8080"

    def test_api_client_strips_trailing_slash(self, auth_manager):
        """APIClient strips trailing slash from base_url."""
        client = APIClient(auth_manager, base_url="https://platform.shani.dev/")
        assert client._base_url == "https://platform.shani.dev"


class TestAPIClientAuthHeaders:
    """Test APIClient header construction."""

    def test_headers_without_token(self, auth_manager):
        """Headers include Content-Type and Accept when no token."""
        client = APIClient(auth_manager)
        headers = client._get_headers()
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        assert "Authorization" not in headers

    def test_headers_with_token(self, auth_manager):
        """Headers include Authorization when authenticated."""
        auth_manager._access_token = "test-token-123"
        auth_manager._is_authenticated = True
        client = APIClient(auth_manager)
        headers = client._get_headers()
        assert headers["Authorization"] == "Bearer test-token-123"


class TestAPIClientLogin:
    """Test APIClient login endpoint."""

    def test_login_success(self, auth_manager):
        """Login sends correct request and returns data."""
        transport = MockTransport({
            "http://localhost:9999/auth/login": (200, {
                "access_token": "abc123",
                "refresh_token": "refresh456",
                "expires_in": 3600,
                "org_id": "org-1",
            }),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.login("user", "pass")
        assert result["access_token"] == "abc123"
        assert result["refresh_token"] == "refresh456"

    def test_login_sends_correct_payload(self, auth_manager):
        """Login sends correct JSON payload."""
        transport = MockTransport({
            "http://localhost:9999/auth/login": (200, {"access_token": "abc"}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        client.login("testuser", "testpass")
        assert len(transport.requests) == 1
        req = transport.requests[0]
        assert req.method == "POST"
        assert req.url == "http://localhost:9999/auth/login"
        body = json.loads(req.content)
        assert body["username"] == "testuser"
        assert body["password"] == "testpass"

    def test_login_failure(self, auth_manager):
        """Login raises on server error."""
        transport = MockTransport({
            "http://localhost:9999/auth/login": (401, {"error": "invalid"}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        with pytest.raises(httpx.HTTPStatusError):
            client.login("bad", "creds")


class TestAPIClientAuthEndpoints:
    """Test APIClient authentication endpoints."""

    def test_get_me(self, auth_manager):
        """get_me fetches user info with auth header."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/auth/me": (200, {"username": "testuser"}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.get_me()
        assert result["username"] == "testuser"
        assert transport.requests[0].headers["Authorization"] == "Bearer token-123"

    def test_refresh_token(self, auth_manager):
        """refresh_token sends refresh token."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/auth/refresh": (200, {
                "access_token": "new-token",
                "expires_in": 3600,
            }),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.refresh_token()
        assert result["access_token"] == "new-token"


class TestAPIClientFleetEndpoints:
    """Test APIClient fleet endpoints."""

    def test_get_fleet_status(self, auth_manager):
        """get_fleet_status fetches fleet status."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/fleet/status": (200, {"enrolled": True}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.get_fleet_status()
        assert result["enrolled"] is True

    def test_enroll_fleet(self, auth_manager):
        """enroll_fleet sends enrollment data."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/fleet/enroll": (200, {"success": True}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.enroll_fleet({"token": "abc"})
        assert result["success"] is True
        body = json.loads(transport.requests[0].content)
        assert body["token"] == "abc"

    def test_get_fleet_machines(self, auth_manager):
        """get_fleet_machines fetches machine list."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/fleet/machines": (200, {"machines": []}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.get_fleet_machines()
        assert "machines" in result

    def test_send_fleet_command(self, auth_manager):
        """send_fleet_command sends command to machine."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/fleet/machines/m1/command": (200, {"ok": True}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.send_fleet_command("m1", {"cmd": "reboot"})
        assert result["ok"] is True

    def test_get_fleet_tasks(self, auth_manager):
        """get_fleet_tasks fetches task history."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/fleet/tasks": (200, {"tasks": []}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.get_fleet_tasks()
        assert "tasks" in result


class TestAPIClientLicenseEndpoints:
    """Test APIClient licensing endpoints."""

    def test_get_license_status(self, auth_manager):
        """get_license_status fetches license info."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/fleet/licenses/status": (200, {"valid": True}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.get_license_status()
        assert result["valid"] is True

    def test_issue_license(self, auth_manager):
        """issue_license sends license data."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/fleet/licenses/issue": (200, {"id": "lic-1"}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.issue_license({"plan": "pro"})
        assert result["id"] == "lic-1"

    def test_auto_sync_license(self, auth_manager):
        """auto_sync_license triggers sync."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/fleet/licenses/auto-sync": (200, {"synced": True}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.auto_sync_license()
        assert result["synced"] is True


class TestAPIClientUpdateEndpoints:
    """Test APIClient update/channel endpoints."""

    def test_get_update_channel(self, auth_manager):
        """get_update_channel fetches channel."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/updates/channel": (200, {"channel": "stable"}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.get_update_channel()
        assert result["channel"] == "stable"

    def test_set_update_channel(self, auth_manager):
        """set_update_channel sends channel name."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/updates/channel": (200, {"channel": "testing"}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.set_update_channel("testing")
        assert result["channel"] == "testing"

    def test_check_for_updates(self, auth_manager):
        """check_for_updates checks for updates."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/updates/check": (200, {"available": False}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.check_for_updates()
        assert result["available"] is False

    def test_get_update_history(self, auth_manager):
        """get_update_history fetches history."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/updates/history": (200, {"updates": []}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.get_update_history()
        assert "updates" in result


class TestAPIClientHealthEndpoint:
    """Test APIClient health endpoint."""

    def test_get_health_status(self, auth_manager):
        """get_health_status returns default on failure."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/health/status": (404, {"error": "not found"}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.get_health_status()
        assert result["status"] == "unknown"


class TestAPIClientPluginEndpoints:
    """Test APIClient plugin/gateway endpoints."""

    def test_register_plugin(self, auth_manager):
        """register_plugin sends plugin data."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/plugins": (200, {"id": "plug-1"}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.register_plugin({"name": "test"})
        assert result["id"] == "plug-1"

    def test_get_security_scan_status(self, auth_manager):
        """get_security_scan_status fetches scan status."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/security/scan/scan-1": (200, {"status": "done"}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.get_security_scan_status("scan-1")
        assert result["status"] == "done"

    def test_send_gateway_command(self, auth_manager):
        """send_gateway_command sends gateway data."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/gateway/command": (200, {"sent": True}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.send_gateway_command({"target": "telegram"})
        assert result["sent"] is True

    def test_get_gateway_status(self, auth_manager):
        """get_gateway_status fetches gateway status."""
        auth_manager._access_token = "token-123"
        auth_manager._is_authenticated = True
        transport = MockTransport({
            "http://localhost:9999/gateway/status": (200, {"connected": False}),
        })
        client = APIClient(auth_manager, base_url="http://localhost:9999")
        client._client = httpx.Client(transport=transport)

        result = client.get_gateway_status()
        assert result["connected"] is False


class TestAPIClientClose:
    """Test APIClient close method."""

    def test_close(self, auth_manager):
        """close() does not raise."""
        client = APIClient(auth_manager)
        client.close()  # Should not raise
