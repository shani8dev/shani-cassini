"""Authentication manager for the Shanios GUI."""

import logging
import json
import time
from typing import Optional
import httpx  # type: ignore

try:
    import keyring
except ImportError:  # pragma: no cover - keyring is a declared dependency
    keyring = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class AuthManager:
    """Manages authentication with the Shanios platform."""

    _KEYRING_SERVICE = "shani-gui"
    _KEYRING_ACCOUNT = "credentials"

    def __init__(self, base_url: str = "https://platform.shani.dev") -> None:
        """Initialize the authentication manager.

        Args:
            base_url: Base URL for the Shanios platform API
        """
        self._base_url = base_url.rstrip("/")
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expiry: float = 0
        self._org_id: Optional[str] = None
        self._username: Optional[str] = None
        self._is_authenticated: bool = False
        self._http_client = httpx.Client(timeout=30.0)
        self._keyring_available = self._keyring_ready()

        # Try to load existing tokens from keyring
        self._load_credentials()
        logger.info("AuthManager initialized")

    def _keyring_ready(self) -> bool:
        """Probe whether the system keyring is accessible.

        Returns False on any failure so the app falls back to
        in-memory storage transparently.
        """
        if keyring is None:
            return False
        try:
            keyring.get_password(self._KEYRING_SERVICE, "__keyring_probe__")
            return True
        except Exception:
            return False

    def _load_credentials(self) -> None:
        """Load credentials from the system keyring with graceful fallback."""
        if not self._keyring_available:
            logger.info("keyring not available; using memory-only storage")
            return
        try:
            cred = keyring.get_credential(
                self._KEYRING_SERVICE, self._KEYRING_ACCOUNT
            )
            if cred is not None and cred.password:
                data = json.loads(cred.password)
                self._access_token = data.get("access_token")
                self._refresh_token = data.get("refresh_token")
                self._token_expiry = data.get("token_expiry", 0)
                self._org_id = data.get("org_id")
                self._username = data.get("username")
                self._is_authenticated = True
                logger.info(
                    f"Loaded credentials from keyring for user: {self._username}"
                )
            else:
                logger.info("No credentials found in keyring")
        except Exception as e:
            logger.warning(f"Failed to load credentials from keyring: {e}")

    def _save_credentials(self) -> None:
        """Save credentials to the system keyring."""
        if not self._keyring_available:
            return
        try:
            blob = json.dumps(
                {
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "token_expiry": self._token_expiry,
                    "org_id": self._org_id,
                    "username": self._username,
                }
            )
            keyring.set_password(
                self._KEYRING_SERVICE, self._KEYRING_ACCOUNT, blob
            )
            logger.info(
                f"Saved credentials to keyring for user: {self._username}"
            )
        except Exception as e:
            logger.warning(f"Failed to save credentials to keyring: {e}")

    def _clear_credentials(self) -> None:
        """Clear stored credentials from memory and keyring."""
        self._access_token = None
        self._refresh_token = None
        self._token_expiry = 0
        self._org_id = None
        self._username = None
        self._is_authenticated = False

        if self._keyring_available:
            try:
                keyring.delete_password(
                    self._KEYRING_SERVICE, self._KEYRING_ACCOUNT
                )
            except Exception:
                pass

        logger.info("Cleared credentials")

    def login(self, username: str, password: str) -> bool:
        """Log in to the Shanios platform.
        
        Args:
            username: Username or email
            password: Password
            
        Returns:
            True if login successful, False otherwise
        """
        logger.info(f"Attempting login for user: {username}")
        try:
            response = self._http_client.post(
                f"{self._base_url}/auth/login",
                json={"username": username, "password": password}
            )
            response.raise_for_status()
            data = response.json()
            
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._token_expiry = time.time() + data.get("expires_in", 3600)  # default 1 hour
            self._org_id = data.get("org_id")
            self._username = username
            self._is_authenticated = True
            
            self._save_credentials()
            logger.info(f"Login successful for user: {username}")
            return True
        except Exception as e:
            logger.error(f"Login failed: {e}")
            self._clear_credentials()
            return False

    def logout(self) -> None:
        """Log out from the Shanios platform."""
        logger.info(f"Logging out user: {self._username}")
        try:
            # Call actual logout API to invalidate tokens server-side
            if self._access_token:
                self._http_client.post(
                    f"{self._base_url}/auth/logout",
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )
        except Exception as e:
            logger.error(f"Error during logout: {e}")
        finally:
            self._clear_credentials()
            logger.info("Logout successful")

    def is_authenticated(self) -> bool:
        """Check if the user is currently authenticated.
        
        Returns:
            True if authenticated, False otherwise
        """
        # Check if token is still valid
        if self._is_authenticated and time.time() >= self._token_expiry:
            logger.info("Access token expired")
            self._is_authenticated = False
            self._clear_credentials()
        
        return self._is_authenticated

    def get_access_token(self) -> Optional[str]:
        """Get the current access token.
        
        Returns:
            Access token string or None if not authenticated
        """
        if self.is_authenticated():
            return self._access_token
        return None

    def get_org_id(self) -> Optional[str]:
        """Get the current organization ID.
        
        Returns:
            Organization ID string or None if not authenticated
        """
        return self._org_id if self.is_authenticated() else None

    def get_username(self) -> Optional[str]:
        """Get the current username.
        
        Returns:
            Username string or None if not authenticated
        """
        return self._username if self.is_authenticated() else None

    def refresh_token(self) -> bool:
        """Refresh the access token using the refresh token.
        
        Returns:
            True if refresh successful, False otherwise
        """
        if not self._refresh_token:
            logger.warning("No refresh token available")
            return False
        
        logger.info("Refreshing access token")
        try:
            response = self._http_client.post(
                f"{self._base_url}/auth/refresh",
                json={"refresh_token": self._refresh_token}
            )
            response.raise_for_status()
            data = response.json()
            
            self._access_token = data.get("access_token")
            # The refresh token might be rotated
            if "refresh_token" in data:
                self._refresh_token = data.get("refresh_token")
            self._token_expiry = time.time() + data.get("expires_in", 3600)  # default 1 hour
            self._save_credentials()
            logger.info("Access token refreshed successfully")
            return True
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            self._clear_credentials()
            return False

    def close(self) -> None:
        """Close the HTTP client."""
        self._http_client.close()
        logger.info("AuthManager closed")