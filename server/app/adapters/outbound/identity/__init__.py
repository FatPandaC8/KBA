import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict

import urllib.error
import urllib.parse
import urllib.request

from server.app.application.ports import EmailPort, GoogleTokenVerifierPort
from server.app.domain.errors import AuthError, ProviderNotConfiguredError

logger = logging.getLogger(__name__)


class LogEmailAdapter(EmailPort):
    """Development email adapter.

    Writes each message to a local JSONL outbox and the application log. The
    MVP does not ship a paid transactional email provider; production must
    plug a real free-tier sender into this port. No email is sent by this
    adapter, and that is stated in the operator documentation.
    """

    def __init__(self, outbox_dir: str):
        self.outbox_dir = outbox_dir

    def send(self, to_email: str, subject: str, body: str) -> None:
        record = {
            "to": to_email,
            "subject": subject,
            "body": body,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            os.makedirs(self.outbox_dir, exist_ok=True)
            with open(os.path.join(self.outbox_dir, "outbox.jsonl"), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except OSError:
            # Never fail sign-up because the local outbox is unwritable; the
            # message is still logged for an operator to retrieve.
            logger.exception("Could not write email outbox entry for %s", to_email)
        logger.info("Email queued for %s: %s", to_email, subject)


class GoogleTokenInfoVerifier(GoogleTokenVerifierPort):
    """Server-side Google ID token validation.

    Uses Google's tokeninfo endpoint so no extra crypto dependency is needed.
    The audience is checked against the configured client id and expiry is
    re-checked locally. Disabled unless ``ECHO_GOOGLE_CLIENT_ID`` is set.
    """

    def __init__(self, client_id: str, timeout_seconds: int = 10):
        self.client_id = client_id.strip()
        self.timeout_seconds = timeout_seconds

    def verify(self, id_token: str) -> Dict[str, object]:
        if not self.client_id:
            raise ProviderNotConfiguredError("Google Sign-In is not configured on this server.")
        if not id_token or len(id_token) > 4096:
            raise AuthError("Google sign-in failed.")

        url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": id_token})
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise AuthError("Google sign-in failed.")

        if payload.get("aud") != self.client_id:
            raise AuthError("Google sign-in failed.")
        try:
            expires = int(payload.get("exp", "0"))
        except (TypeError, ValueError):
            raise AuthError("Google sign-in failed.")
        if expires <= int(datetime.now(timezone.utc).timestamp()):
            raise AuthError("Google sign-in failed.")

        email = (payload.get("email") or "").strip()
        verified = payload.get("email_verified")
        if not email or str(verified).lower() not in ("true", "1"):
            raise AuthError("Google sign-in failed.")
        return {
            "sub": payload.get("sub"),
            "email": email,
            "email_verified": True,
        }
