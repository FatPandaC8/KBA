"""Authentication, consent and account routes.

All error messages are deliberately generic where account enumeration or
credential probing would otherwise be possible.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from server.app.adapters.inbound.http.schemas import (
    AccountDeletionResponse,
    AuthSessionResponse,
    ConsentStatusResponse,
    ConsentUpdateRequest,
    GoogleSignInRequest,
    LoginRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
    UserResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from server.app.api.dependencies import (
    Container,
    get_bearer_token,
    get_container,
    get_current_user,
)
from server.app.domain.entities import UserEntity
from server.app.domain.errors import AuthError, ProviderNotConfiguredError, RateLimitedError, ValidationError
from server.app.security import normalize_email, rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])
consent_router = APIRouter(prefix="/api/consent", tags=["consent"])
account_router = APIRouter(prefix="/api/account", tags=["account"])


def _user_response(user: UserEntity) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified,
        created_at=user.created_at,
    )


def _client_ip(request: Request) -> str:
    # The MVP is deployed behind a single reverse proxy at most. Trusting
    # arbitrary X-Forwarded-For values without a configured proxy would let a
    # caller bypass per-IP limits, so only the socket peer is used here.
    return request.client.host if request.client else "unknown"


def _limit(request: Request, scope: str, identity: str, settings, per_minute: Optional[int] = None) -> None:
    limit = per_minute or settings.auth_rate_limit_per_minute
    allowed, retry_after = rate_limiter.check(
        f"{scope}:{_client_ip(request)}:{identity.strip().lower()}",
        limit=limit,
        window_seconds=60,
    )
    if not allowed:
        raise RateLimitedError(retry_after)


def _raise(exc: Exception) -> None:
    if isinstance(exc, RateLimitedError):
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, AuthError):
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if isinstance(exc, ProviderNotConfiguredError):
        raise HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValidationError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.post("/signup", response_model=SignupResponse)
def signup(payload: SignupRequest, request: Request, container: Container = Depends(get_container)):
    normalized = normalize_email(payload.email)
    _limit(request, "signup", normalized, container.settings)
    try:
        user, token, created = container.auth_service.signup(payload.email, payload.password)
    except (ValidationError, RateLimitedError, AuthError, ProviderNotConfiguredError) as exc:
        _raise(exc)
        return  # pragma: no cover - _raise always raises

    # A duplicate address receives the same generic response so this endpoint
    # cannot be used to enumerate registered emails. No second account is made.
    dev_token = token if (created and container.settings.expose_dev_tokens) else None
    return SignupResponse(email=normalized, dev_verification_token=dev_token)


@router.post("/login", response_model=AuthSessionResponse)
def login(payload: LoginRequest, request: Request, container: Container = Depends(get_container)):
    normalized = normalize_email(payload.email)
    _limit(request, "login", normalized, container.settings)
    try:
        user, token = container.auth_service.login(payload.email, payload.password)
    except (ValidationError, RateLimitedError, AuthError, ProviderNotConfiguredError) as exc:
        _raise(exc)
        return  # pragma: no cover
    return AuthSessionResponse(token=token, user=_user_response(user))


@router.get("/me", response_model=UserResponse)
def me(user: UserEntity = Depends(get_current_user)):
    return _user_response(user)


@router.post("/logout")
def logout(
    token: str = Depends(get_bearer_token),
    container: Container = Depends(get_container),
    _user: UserEntity = Depends(get_current_user),
):
    container.auth_service.logout(token)
    return {"logged_out": True}


@router.post("/verify-email", response_model=VerifyEmailResponse)
def verify_email(payload: VerifyEmailRequest, container: Container = Depends(get_container)):
    try:
        container.auth_service.verify_email(payload.token.strip())
    except (ValidationError, AuthError) as exc:
        _raise(exc)
    return VerifyEmailResponse()


@router.post("/request-verification")
def request_verification(
    payload: ResendVerificationRequest,
    request: Request,
    container: Container = Depends(get_container),
):
    normalized = normalize_email(payload.email)
    _limit(request, "request-verification", normalized, container.settings, per_minute=5)
    # Generic response whether or not the address exists. In development the
    # token is returned so the flow can be exercised without a real mailbox.
    user = container.user_repo.get_by_email(normalized)
    dev_token = None
    if user and not user.email_verified:
        dev_token = container.auth_service.send_verification(user)
        if not container.settings.expose_dev_tokens:
            dev_token = None
    return {
        "message": "If that address needs verification, a message has been sent.",
        "dev_verification_token": dev_token,
    }


@router.post("/request-password-reset", response_model=PasswordResetRequestResponse)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    container: Container = Depends(get_container),
):
    normalized = normalize_email(payload.email)
    _limit(request, "request-password-reset", normalized, container.settings, per_minute=5)
    token = container.auth_service.request_password_reset(payload.email)
    return PasswordResetRequestResponse(
        message="If an account exists for that address, a reset message has been sent.",
        dev_reset_token=token if container.settings.expose_dev_tokens else None,
    )


@router.post("/reset-password", response_model=VerifyEmailResponse)
def reset_password(payload: ResetPasswordRequest, container: Container = Depends(get_container)):
    try:
        container.auth_service.reset_password(payload.token.strip(), payload.new_password)
    except (ValidationError, AuthError) as exc:
        _raise(exc)
    return VerifyEmailResponse(verified=True)


@router.post("/google", response_model=AuthSessionResponse)
def google_sign_in(payload: GoogleSignInRequest, container: Container = Depends(get_container)):
    try:
        user, token = container.auth_service.google_sign_in(payload.id_token)
    except (ValidationError, AuthError, ProviderNotConfiguredError) as exc:
        _raise(exc)
        return  # pragma: no cover
    return AuthSessionResponse(token=token, user=_user_response(user))


@consent_router.get("", response_model=ConsentStatusResponse)
def get_consent(
    user: UserEntity = Depends(get_current_user),
    container: Container = Depends(get_container),
):
    return ConsentStatusResponse(**container.consent_service.status(user.id))


@consent_router.post("", response_model=ConsentStatusResponse)
def update_consent(
    payload: ConsentUpdateRequest,
    user: UserEntity = Depends(get_current_user),
    container: Container = Depends(get_container),
):
    try:
        container.consent_service.record(user.id, payload.granted)
    except Exception:
        logger.exception("Could not record consent for user %s", user.id)
        raise HTTPException(status_code=500, detail="Consent could not be recorded.")
    return ConsentStatusResponse(**container.consent_service.status(user.id))


@account_router.delete("", response_model=AccountDeletionResponse)
def delete_account(
    confirm: str = "",
    user: UserEntity = Depends(get_current_user),
    container: Container = Depends(get_container),
):
    if confirm != "DELETE":
        raise HTTPException(
            status_code=400,
            detail='Send confirm=DELETE to permanently delete your account.',
        )
    try:
        result = container.delete_account_uc.execute(user.id)
    except Exception:
        logger.exception("Account deletion failed for user %s", user.id)
        raise HTTPException(
            status_code=500,
            detail="Account deletion failed. No success was reported; retry or contact support.",
        )
    return AccountDeletionResponse(**result)
