"""OIDC identity verification and PUBBA role permission definitions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient


ROLES = ("viewer", "operator", "approver", "admin")
ROLE_PERMISSIONS = {
    "viewer": frozenset({"recommendations:read"}),
    "operator": frozenset({"recommendations:read", "recommendations:capture", "recommendations:acknowledge", "recommendations:link_simulation"}),
    "approver": frozenset({"recommendations:read", "recommendations:capture", "recommendations:acknowledge", "recommendations:link_simulation", "recommendations:approve", "recommendations:link_dispatch"}),
    "admin": frozenset({"recommendations:read", "recommendations:capture", "recommendations:acknowledge", "recommendations:link_simulation", "recommendations:approve", "recommendations:link_dispatch", "operators:manage"}),
}


class OperatorAuthError(RuntimeError):
    """Authentication configuration or token verification failure."""


@dataclass(frozen=True)
class VerifiedIdentity:
    subject: str
    email: str | None
    claims: dict[str, Any]


@dataclass(frozen=True)
class OperatorPrincipal:
    operator_id: str
    auth_subject: str
    email: str
    display_name: str
    role: str
    status: str

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, frozenset())

    def public_dict(self) -> dict[str, str]:
        return {"email": self.email, "display_name": self.display_name, "role": self.role, "status": self.status}


def operator_auth_required() -> bool:
    return os.getenv("OPERATOR_AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=8)
def _jwks_client(issuer: str) -> PyJWKClient:
    return PyJWKClient(
        f"{issuer}/.well-known/jwks.json", cache_jwk_set=True, lifespan=600
    )


def verify_oidc_token(token: str) -> VerifiedIdentity:
    issuer = os.getenv("OPERATOR_OIDC_ISSUER", "").strip().rstrip("/")
    audience = os.getenv("OPERATOR_OIDC_AUDIENCE", "").strip()
    if not issuer or not audience:
        raise OperatorAuthError("Operator identity verification is not configured")
    try:
        signing_key = _jwks_client(issuer).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, signing_key.key, algorithms=["RS256", "ES256"],
            audience=audience, issuer=issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OperatorAuthError("Invalid or expired operator credential") from exc
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise OperatorAuthError("Operator credential is missing a stable subject")
    email = str(claims.get("email") or "").strip().lower() or None
    return VerifiedIdentity(subject=subject, email=email, claims=dict(claims))


def principal_from_record(record: dict[str, Any]) -> OperatorPrincipal:
    role = str(record.get("role") or "")
    if role not in ROLES:
        raise OperatorAuthError("Operator profile has an invalid role")
    return OperatorPrincipal(
        operator_id=str(record["id"]), auth_subject=str(record["auth_subject"]),
        email=str(record["email"]), display_name=str(record["display_name"]),
        role=role, status=str(record.get("status") or "inactive"),
    )
