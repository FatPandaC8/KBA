import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from server.app.application.ports import (
    UserRepositoryPort,
    SessionRepositoryPort,
    EmailTokenRepositoryPort,
    ConsentRepositoryPort,
    EmailPort,
    GoogleTokenVerifierPort,
)
from server.app.domain.entities import UserEntity, ConsentEntity
from server.app.domain.errors import AuthError, ValidationError
from server.app.security import (
    generate_token,
    hash_password,
    hash_token,
    is_valid_email,
    normalize_email,
    validate_password,
    verify_password,
)

PURPOSE_VERIFY = "verify_email"
PURPOSE_RESET = "reset_password"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    def __init__(
        self,
        user_repo: UserRepositoryPort,
        session_repo: SessionRepositoryPort,
        email_token_repo: EmailTokenRepositoryPort,
        email_port: EmailPort,
        google_verifier: GoogleTokenVerifierPort,
        settings: Any,
    ):
        self.user_repo = user_repo
        self.session_repo = session_repo
        self.email_token_repo = email_token_repo
        self.email_port = email_port
        self.google_verifier = google_verifier
        self.settings = settings

    # ------------------------------------------------------------------ tokens
    def _issue_session(self, user: UserEntity) -> str:
        raw = generate_token()
        expires = (_now() + timedelta(hours=self.settings.session_ttl_hours)).isoformat()
        self.session_repo.create(user.id, hash_token(raw), expires)
        return raw

    def _issue_email_token(self, user: UserEntity, purpose: str, ttl_minutes: int) -> str:
        raw = generate_token(24)
        expires = (_now() + timedelta(minutes=ttl_minutes)).isoformat()
        self.email_token_repo.create(user.id, purpose, hash_token(raw), expires)
        return raw

    def send_verification(self, user: UserEntity) -> str:
        raw = self._issue_email_token(user, PURPOSE_VERIFY, self.settings.verify_token_ttl_minutes)
        self.email_port.send(
            user.email,
            "Verify your Echo email",
            f"Open the Echo app and enter this verification token: {raw}",
        )
        return raw

    # ------------------------------------------------------------------- auth
    def signup(self, email: str, password: str) -> Tuple[Optional[UserEntity], Optional[str], bool]:
        """Create an account.

        Returns ``(user, verification_token, created)``. A duplicate email
        returns the same generic shape without creating a second account so
        the endpoint cannot be used to enumerate registered emails.
        """
        normalized = normalize_email(email)
        if not is_valid_email(normalized):
            raise ValidationError("Enter a valid email address.")
        password_error = validate_password(password, self.settings.password_min_length)
        if password_error:
            raise ValidationError(password_error)

        existing = self.user_repo.get_by_email(normalized)
        if existing:
            return None, None, False

        user = UserEntity.create(normalized, hash_password(password))
        self.user_repo.save(user)
        token = self.send_verification(user)
        return user, token, True

    def login(self, email: str, password: str) -> Tuple[UserEntity, str]:
        normalized = normalize_email(email)
        user = self.user_repo.get_by_email(normalized)
        # Always run a hash comparison to keep timing roughly uniform.
        password_ok = verify_password(password, user.password_hash if user else None)
        if not user or not password_ok:
            raise AuthError("Email or password is incorrect.")
        if user.is_locked:
            raise AuthError("This account is locked.")
        return user, self._issue_session(user)

    def authenticate(self, token: str) -> UserEntity:
        if not token:
            raise AuthError("Authentication required.")
        user = self.session_repo.get_user_by_token_hash(hash_token(token))
        if not user:
            raise AuthError("Session is invalid or expired.")
        self.session_repo.touch(hash_token(token))
        return user

    def logout(self, token: str) -> None:
        if token:
            self.session_repo.revoke(hash_token(token))

    def verify_email(self, token: str) -> UserEntity:
        user_id = self.email_token_repo.consume(hash_token(token), PURPOSE_VERIFY)
        if not user_id:
            raise AuthError("This verification link is invalid or has expired.")
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise AuthError("This verification link is invalid or has expired.")
        user.email_verified_at = _now().isoformat()
        self.user_repo.update(user)
        return user

    def request_password_reset(self, email: str) -> Optional[str]:
        """Always returns success to the caller; returns a token only in dev."""
        user = self.user_repo.get_by_email(normalize_email(email))
        if not user:
            return None
        raw = self._issue_email_token(user, PURPOSE_RESET, self.settings.reset_token_ttl_minutes)
        self.email_port.send(
            user.email,
            "Reset your Echo password",
            f"Enter this reset token in the Echo app: {raw}",
        )
        return raw

    def reset_password(self, token: str, new_password: str) -> UserEntity:
        password_error = validate_password(new_password, self.settings.password_min_length)
        if password_error:
            raise ValidationError(password_error)
        user_id = self.email_token_repo.consume(hash_token(token), PURPOSE_RESET)
        if not user_id:
            raise AuthError("This reset token is invalid or has expired.")
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise AuthError("This reset token is invalid or has expired.")
        user.password_hash = hash_password(new_password)
        user.updated_at = _now().isoformat()
        self.user_repo.update(user)
        # A password reset revokes every existing session.
        self.session_repo.revoke_all_for_user(user.id)
        return user

    def google_sign_in(self, id_token: str) -> Tuple[UserEntity, str]:
        identity = self.google_verifier.verify(id_token)
        sub = str(identity.get("sub") or "")
        email = normalize_email(str(identity.get("email") or ""))
        if not sub or not email:
            raise AuthError("Google sign-in failed.")

        user = self.user_repo.get_by_google_sub(sub)
        if user is None:
            existing = self.user_repo.get_by_email(email)
            if existing:
                # AUTH-07: only link after ownership is verified. Google has
                # verified the address, but an unverified password account is
                # not proof of ownership, so refuse the automatic takeover.
                if not existing.email_verified:
                    raise AuthError(
                        "An unverified account already uses this email. "
                        "Verify it before linking Google."
                    )
                existing.google_sub = sub
                existing.updated_at = _now().isoformat()
                self.user_repo.update(existing)
                user = existing
            else:
                user = UserEntity.create(email)
                user.google_sub = sub
                user.email_verified_at = _now().isoformat()
                self.user_repo.save(user)

        if user.is_locked:
            raise AuthError("This account is locked.")
        return user, self._issue_session(user)


class ConsentService:
    def __init__(self, consent_repo: ConsentRepositoryPort, settings: Any):
        self.consent_repo = consent_repo
        self.settings = settings

    def providers(self) -> List[Dict[str, object]]:
        return self.settings.ai_providers

    def providers_hash(self) -> str:
        canonical = json.dumps(
            sorted(self.providers(), key=lambda p: str(p.get("id"))),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def status(self, user_id: str) -> Dict[str, object]:
        latest = self.consent_repo.get_latest(user_id)
        current_hash = self.providers_hash()
        current = bool(
            latest
            and latest.granted
            and latest.version == self.settings.consent_version
            and latest.providers_hash == current_hash
        )
        return {
            "required": True,
            "version": self.settings.consent_version,
            "providers": self.providers(),
            "granted": current,
            "granted_at": latest.created_at if latest else None,
            "recorded_version": latest.version if latest else None,
        }

    def record(self, user_id: str, granted: bool) -> ConsentEntity:
        consent = ConsentEntity(
            id=uuid.uuid4().hex,
            user_id=user_id,
            version=self.settings.consent_version,
            providers_hash=self.providers_hash(),
            providers=self.providers(),
            granted=granted,
        )
        self.consent_repo.save(consent)
        return consent

    def has_current_consent(self, user_id: str) -> bool:
        return bool(self.status(user_id)["granted"])
