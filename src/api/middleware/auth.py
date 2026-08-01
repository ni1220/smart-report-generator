"""
Cognito JWT authentication middleware.

Validates Bearer tokens from Amazon Cognito User Pool.
"""

import logging
from typing import Any

import boto3
import httpx
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode

from src.shared.config import get_settings

logger = logging.getLogger(__name__)

security = HTTPBearer()

# Cache for JWKS keys
_jwks_cache: dict[str, Any] | None = None


def _get_jwks() -> dict[str, Any]:
    """Fetch and cache JWKS from Cognito."""
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache

    settings = get_settings()
    if not settings.cognito_user_pool_id:
        logger.warning("Cognito not configured, auth disabled")
        return {}

    region = settings.aws_region
    pool_id = settings.cognito_user_pool_id
    jwks_url = (
        f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json"
    )

    try:
        response = httpx.get(jwks_url, timeout=10)
        response.raise_for_status()
        _jwks_cache = response.json()
        return _jwks_cache
    except Exception as e:
        logger.error(f"Failed to fetch JWKS: {e}")
        raise HTTPException(status_code=500, detail="Authentication service unavailable")


def _verify_token(token: str) -> dict[str, Any]:
    """
    Verify a Cognito JWT token.

    Args:
        token: Raw JWT token string

    Returns:
        Decoded token claims

    Raises:
        HTTPException: If token is invalid
    """
    settings = get_settings()

    # Skip auth if Cognito not configured (development mode)
    if not settings.cognito_user_pool_id:
        return {"sub": "dev-user", "email": "dev@localhost"}

    try:
        # Decode header to get key ID
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid")

        if not kid:
            raise HTTPException(status_code=401, detail="Invalid token header")

        # Find matching key
        jwks = _get_jwks()
        key = None
        for k in jwks.get("keys", []):
            if k["kid"] == kid:
                key = k
                break

        if not key:
            raise HTTPException(status_code=401, detail="Token signing key not found")

        # Verify token
        region = settings.aws_region
        pool_id = settings.cognito_user_pool_id
        issuer = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"

        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.cognito_client_id,
            issuer=issuer,
        )

        return claims

    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict[str, Any]:
    """
    FastAPI dependency for authenticating requests.

    Usage:
        @router.get("/protected")
        async def endpoint(user: dict = Depends(get_current_user)):
            ...
    """
    token = credentials.credentials
    return _verify_token(token)
