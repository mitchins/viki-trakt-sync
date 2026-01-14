"""Token expiry notification system using Pushover."""

import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class TokenStatusTracker:
    """Track token status and notification history to prevent duplicate notifications."""

    def __init__(self, status_file: Optional[Path] = None):
        """Initialize tracker.

        Args:
            status_file: Path to token_status.json (default: ~/.config/viki-trakt-sync/token_status.json)
        """
        if status_file is None:
            status_file = Path.home() / ".config" / "viki-trakt-sync" / "token_status.json"

        self.status_file = Path(status_file)
        self.status_file.parent.mkdir(parents=True, exist_ok=True)

        self._load_status()

    def _load_status(self) -> None:
        """Load status from file or create new."""
        if self.status_file.exists():
            try:
                with open(self.status_file) as f:
                    self.status = json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning(f"Could not load {self.status_file}, starting fresh")
                self.status = self._default_status()
        else:
            self.status = self._default_status()

    def _default_status(self) -> dict:
        """Return default status structure."""
        return {
            "current_token": None,
            "token_status": "unknown",  # unknown|active|expired
            "first_failure_at": None,
            "last_notification_sent_at": None,
            "notification_count": 0,
        }

    def _save_status(self) -> None:
        """Persist status to file."""
        try:
            with open(self.status_file, "w") as f:
                json.dump(self.status, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save token status: {e}")

    def mark_token_active(self, token: str) -> None:
        """Mark token as active after successful use.

        Args:
            token: The API token being used
        """
        if token != self.status.get("current_token"):
            logger.info(f"Token changed, resetting failure tracking")
            self.status["current_token"] = token
            self.status["token_status"] = "active"
            self.status["first_failure_at"] = None
            self.status["last_notification_sent_at"] = None
            self.status["notification_count"] = 0
            self._save_status()

    def should_notify_about_expiry(self, token: str) -> bool:
        """Check if we should send a token expiry notification.

        Returns True only if:
        1. This is a NEW token (different from before), OR
        2. 24+ hours since last notification

        Args:
            token: The API token that failed

        Returns:
            True if notification should be sent, False otherwise
        """
        # New token failure → notify
        if token != self.status.get("current_token"):
            logger.info("New token failure detected, should notify")
            return True

        # Same token, check if enough time passed
        last_notif = self.status.get("last_notification_sent_at")
        if last_notif:
            last_notif_time = datetime.fromisoformat(last_notif)
            time_since = datetime.now(timezone.utc) - last_notif_time
            if time_since < timedelta(hours=24):
                logger.debug(f"Already notified {time_since.total_seconds() / 3600:.1f}h ago, skipping")
                return False

        logger.info("24h+ since last notification, should notify again")
        return True

    def mark_notification_sent(self, token: str) -> None:
        """Record that we sent a notification for this token.

        Args:
            token: The token that was notified about
        """
        self.status["current_token"] = token
        self.status["token_status"] = "expired"
        self.status["first_failure_at"] = (
            self.status.get("first_failure_at") or datetime.now(timezone.utc).isoformat()
        )
        self.status["last_notification_sent_at"] = datetime.now(timezone.utc).isoformat()
        self.status["notification_count"] = self.status.get("notification_count", 0) + 1
        self._save_status()

        logger.info(
            f"Recorded notification sent (count: {self.status['notification_count']})"
        )

    def mark_token_refreshed(self, new_token: str) -> None:
        """Mark that token has been refreshed after expiry.

        Args:
            new_token: The new token being used
        """
        logger.info("Token refreshed, resetting failure tracking")
        self.status = self._default_status()
        self.status["current_token"] = new_token
        self.status["token_status"] = "active"
        self._save_status()


class TokenExpiryNotifier:
    """Send Pushover notifications when token expires."""

    PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(self, user_key: Optional[str], app_token: Optional[str]):
        """Initialize notifier.

        Args:
            user_key: Pushover user key (None to disable)
            app_token: Pushover app token (None to disable)
        """
        self.user_key = user_key
        self.app_token = app_token
        self.enabled = bool(user_key and app_token)

        if not self.enabled:
            logger.info("Pushover notifications disabled (credentials not configured)")

    def notify_token_expired(self, token: str, error: str = "") -> bool:
        """Send Pushover notification about expired token.

        Args:
            token: The expired token (to include in message)
            error: Error message from API (optional)

        Returns:
            True if notification sent successfully, False otherwise
        """
        if not self.enabled:
            logger.debug("Pushover disabled, skipping notification")
            return False

        message = (
            "Your Viki API token has expired and sync cannot continue.\n\n"
            "Action required:\n"
            "1. Login to Viki in your browser (https://www.viki.com)\n"
            "2. Open DevTools (F12) → Network tab\n"
            "3. Visit your Continue Watching page\n"
            "4. Find any api.viki.io request\n"
            "5. Copy 'token' parameter from URL (starts with 'ex1')\n"
            "6. Update VIKI_TOKEN in .env file\n"
            "7. Restart the sync\n\n"
            f"Token prefix: {token[:20]}..."
        )

        title = "🔴 Viki Token Expired"

        payload = {
            "token": self.app_token,
            "user": self.user_key,
            "title": title,
            "message": message,
            "priority": 0,  # Normal priority
            "topic": "viki-sync-token-expiry",  # Pushover can deduplicate by topic
        }

        try:
            response = requests.post(self.PUSHOVER_API_URL, data=payload, timeout=5)
            response.raise_for_status()

            logger.info("Pushover notification sent successfully")
            return True

        except requests.RequestException as e:
            logger.error(f"Failed to send Pushover notification: {e}")
            sys.stderr.write(f"⚠️  Could not send Pushover notification: {e}\n")
            # Continue anyway - notification failure shouldn't break sync
            return False


class TokenExpiryHandler:
    """Handle token expiry with notifications and state tracking."""

    def __init__(
        self,
        pushover_user_key: Optional[str] = None,
        pushover_app_token: Optional[str] = None,
        status_file: Optional[Path] = None,
    ):
        """Initialize handler.

        Args:
            pushover_user_key: Pushover user key
            pushover_app_token: Pushover app token
            status_file: Path to token_status.json
        """
        self.tracker = TokenStatusTracker(status_file)
        self.notifier = TokenExpiryNotifier(pushover_user_key, pushover_app_token)

    def mark_token_working(self, token: str) -> None:
        """Mark that token is working (call after successful API call).

        Args:
            token: The token that worked
        """
        self.tracker.mark_token_active(token)

    def handle_token_expired(self, token: str, error: str = "") -> None:
        """Handle token expiry with notification if needed.

        Args:
            token: The expired token
            error: Error message from API
        """
        if self.tracker.should_notify_about_expiry(token):
            # Send notification
            self.notifier.notify_token_expired(token, error)
            # Record that we notified
            self.tracker.mark_notification_sent(token)
        else:
            logger.debug("Skipping notification (already notified recently)")

    def on_token_refreshed(self, new_token: str) -> None:
        """Call when token has been manually refreshed.

        Args:
            new_token: The new token to track
        """
        self.tracker.mark_token_refreshed(new_token)
