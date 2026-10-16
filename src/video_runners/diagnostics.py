"""Credential-free lifecycle events shared across runtime boundaries."""

from contextvars import ContextVar
import json
import logging

operation_id = ContextVar("lifecycle_operation_id", default=None)
FIELDS = {
    "operation_id",
    "model",
    "phase",
    "state",
    "container_id",
    "namespace",
    "action",
    "reason",
}


def event(logger: logging.Logger, name: str, **fields) -> None:
    if set(fields) - FIELDS:
        raise ValueError("unsupported lifecycle diagnostic fields")
    if operation_id.get() is not None:
        fields.setdefault("operation_id", operation_id.get())
    logger.info(json.dumps({"event": name, **fields}, sort_keys=True))
