"""Separate credentials for HTTP execution and human-operated approval endpoints."""

import os
from hmac import compare_digest

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


_bearer = HTTPBearer(auto_error=False)


def _require_token(role: str, credentials: HTTPAuthorizationCredentials | None) -> None:
    execution = os.getenv("PERMITMCP_EXECUTION_TOKEN", "")
    approval = os.getenv("PERMITMCP_APPROVAL_TOKEN", "")
    configured = bool(execution and approval) and not compare_digest(execution, approval)
    expected = execution if role == "execution" else approval
    if not configured or credentials is None or not compare_digest(credentials.scheme.lower(), "bearer") or not compare_digest(credentials.credentials, expected):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_execution(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    _require_token("execution", credentials)


def require_approval(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    _require_token("approval", credentials)
