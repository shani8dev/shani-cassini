"""API client for communicating with the Shanios platform."""

import logging
import json
from typing import Optional, Dict, Any, List
import httpx  # type: ignore

from shani_gui.auth import AuthManager


logger = logging.getLogger(__name__)


class APIClient:
    """Client for communicating with the Shanios platform REST API."""
    
    def __init__(self, auth_manager: AuthManager, base_url: str = "https://platform.shani.dev"):
        """Initialize the API client.
        
        Args:
            auth_manager: Authentication manager for token handling
            base_url: Base URL for the Shanios platform API
        """
        self._auth_manager = auth_manager
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=30.0)
        logger.info("APIClient initialized")

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers for API requests.
        
        Returns:
            Dictionary of headers including Authorization if authenticated
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        access_token = self._auth_manager.get_access_token()
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
            
        return headers

    def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        """Handle API response and return parsed JSON.
        
        Args:
            response: HTTP response object
            
        Returns:
            Parsed JSON response
            
        Raises:
            httpx.HTTPStatusError: For HTTP error responses
            ValueError: For invalid JSON responses
        """
        try:
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON response: {e}")
            raise ValueError("Invalid JSON response from server")

    # Authentication endpoints
    def login(self, username: str, password: str) -> Dict[str, Any]:
        """Log in to the Shanios platform.
        
        Args:
            username: Username or email
            password: Password
            
        Returns:
            Login response containing tokens and user info
        """
        logger.info(f"Attempting login for user: {username}")
        try:
            response = self._client.post(
                f"{self._base_url}/auth/login",
                json={"username": username, "password": password}
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Login failed: {e}")
            raise

    def refresh_token(self) -> Dict[str, Any]:
        """Refresh the access token.
        
        Returns:
            Token refresh response
        """
        logger.info("Refreshing access token")
        try:
            response = self._client.post(
                f"{self._base_url}/auth/refresh",
                json={"refresh_token": self._auth_manager.get_access_token()}  # This would be the actual refresh token
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            raise

    def get_me(self) -> Dict[str, Any]:
        """Get current user information.
        
        Returns:
            User information response
        """
        logger.info("Fetching current user information")
        try:
            response = self._client.get(
                f"{self._base_url}/auth/me",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to fetch user info: {e}")
            raise

    # Licensing endpoints
    def get_license_status(self) -> Dict[str, Any]:
        """Get current license status.
        
        Returns:
            License status response
        """
        logger.info("Fetching license status")
        try:
            response = self._client.get(
                f"{self._base_url}/fleet/licenses/status",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to fetch license status: {e}")
            raise

    def issue_license(self, license_data: Dict[str, Any]) -> Dict[str, Any]:
        """Issue a new license.
        
        Args:
            license_data: License information to issue
            
        Returns:
            License issuance response
        """
        logger.info("Issuing new license")
        try:
            response = self._client.post(
                f"{self._base_url}/fleet/licenses/issue",
                json=license_data,
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to issue license: {e}")
            raise

    def auto_sync_license(self) -> Dict[str, Any]:
        """Trigger automatic license synchronization.
        
        Returns:
            License sync response
        """
        logger.info("Triggering license auto-sync")
        try:
            response = self._client.post(
                f"{self._base_url}/fleet/licenses/auto-sync",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to auto-sync license: {e}")
            raise

    # Fleet endpoints
    def get_fleet_status(self) -> Dict[str, Any]:
        """Get fleet enrollment and status information.
        
        Returns:
            Fleet status response
        """
        logger.info("Fetching fleet status")
        try:
            response = self._client.get(
                f"{self._base_url}/fleet/status",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to fetch fleet status: {e}")
            raise

    def enroll_fleet(self, enrollment_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enroll the machine in the Shanios fleet.
        
        Args:
            enrollment_data: Fleet enrollment information
            
        Returns:
            Fleet enrollment response
        """
        logger.info("Enrolling in fleet")
        try:
            response = self._client.post(
                f"{self._base_url}/fleet/enroll",
                json=enrollment_data,
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to enroll in fleet: {e}")
            raise

    def get_fleet_machines(self) -> Dict[str, Any]:
        """Get list of machines in the fleet.
        
        Returns:
            Fleet machines response
        """
        logger.info("Fetching fleet machines")
        try:
            response = self._client.get(
                f"{self._base_url}/fleet/machines",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to fetch fleet machines: {e}")
            raise

    def send_fleet_command(self, machine_id: str, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send a command to a fleet machine.
        
        Args:
            machine_id: ID of the target machine
            command_data: Command to send
            
        Returns:
            Command response
        """
        logger.info(f"Sending command to machine: {machine_id}")
        try:
            response = self._client.post(
                f"{self._base_url}/fleet/machines/{machine_id}/command",
                json=command_data,
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to send fleet command: {e}")
            raise

    def get_fleet_tasks(self) -> Dict[str, Any]:
        """Get fleet task history.
        
        Returns:
            Fleet tasks response
        """
        logger.info("Fetching fleet tasks")
        try:
            response = self._client.get(
                f"{self._base_url}/fleet/tasks",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to fetch fleet tasks: {e}")
            raise

    # Update/Channel endpoints
    def get_update_channel(self) -> Dict[str, Any]:
        """Get current update channel.
        
        Returns:
            Update channel response
        """
        logger.info("Fetching update channel")
        try:
            response = self._client.get(
                f"{self._base_url}/updates/channel",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to fetch update channel: {e}")
            raise

    def set_update_channel(self, channel: str) -> Dict[str, Any]:
        """Set the update channel.
        
        Args:
            channel: Channel name to set (stable, testing, unstable)
            
        Returns:
            Update channel response
        """
        logger.info(f"Setting update channel to: {channel}")
        try:
            response = self._client.post(
                f"{self._base_url}/updates/channel",
                json={"channel": channel},
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to set update channel: {e}")
            raise

    def check_for_updates(self) -> Dict[str, Any]:
        """Check for available updates.
        
        Returns:
            Update check response
        """
        logger.info("Checking for updates")
        try:
            response = self._client.get(
                f"{self._base_url}/updates/check",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to check for updates: {e}")
            raise

    def get_update_history(self) -> Dict[str, Any]:
        """Get update history.
        
        Returns:
            Update history response
        """
        logger.info("Fetching update history")
        try:
            response = self._client.get(
                f"{self._base_url}/updates/history",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to fetch update history: {e}")
            raise

    # Health endpoints (if available via API)
    def get_health_status(self) -> Dict[str, Any]:
        """Get system health status via API (if available).
        
        Returns:
            Health status response
        """
        logger.info("Fetching health status")
        try:
            response = self._client.get(
                f"{self._base_url}/health/status",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to fetch health status: {e}")
            # This endpoint might not exist, so we'll return a default response
            return {"status": "unknown", "message": "Health status not available via API"}

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
        logger.info("APIClient closed")

    # Pulsar OS Sayri integration endpoints
    
    def register_plugin(self, plugin_data: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new skill/plugin.
        
        Args:
            plugin_data: Plugin information to register
            
        Returns:
            Plugin registration response
        """
        logger.info("Registering new plugin")
        try:
            response = self._client.post(
                f"{self._base_url}/plugins",
                json=plugin_data,
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to register plugin: {e}")
            raise

    def get_security_scan_status(self, scan_id: str) -> Dict[str, Any]:
        """Get VirusTotal security scan status.
        
        Args:
            scan_id: Unique identifier for the security scan
            
        Returns:
            Scan status response
        """
        logger.info(f"Getting security scan status for: {scan_id}")
        try:
            response = self._client.get(
                f"{self._base_url}/security/scan/{scan_id}",
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to get security scan status: {e}")
            raise

    def send_gateway_command(self, gateway_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send command to Telegram/Discord channel gateway.
        
        Args:
            gateway_data: Gateway command data including target, message, etc.
            
        Returns:
            Command execution response
        """
        logger.info(f"Sending gateway command to: {gateway_data.get('gateway', 'unknown')}")
        try:
            response = self._client.post(
                f"{self._base_url}/gateway/command",
                json=gateway_data,
                headers=self._get_headers()
            )
            return self._handle_response(response)
        except Exception as e:
            logger.error(f"Failed to send gateway command: {e}")
            raise