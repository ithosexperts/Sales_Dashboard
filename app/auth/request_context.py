"""
ContextVar storage for request identity & target database resolution.
"""
from __future__ import annotations

import contextvars
from typing import Optional

_bearer_token: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("bearer_token", default=None)
_database_target: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("database_target", default=None)


def get_current_bearer_token() -> Optional[str]:
    return _bearer_token.get()


def set_current_bearer_token(token: Optional[str]) -> contextvars.Token:
    return _bearer_token.set(token)


def get_current_database_target() -> Optional[str]:
    return _database_target.get()


def set_current_database_target(db: Optional[str]) -> contextvars.Token:
    return _database_target.set(db)
