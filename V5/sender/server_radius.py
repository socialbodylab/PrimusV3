"""Compatibility shim — unified HTTP server lives in server.py."""

from server import Handler, _sync_job, _sync_lock, create_server  # noqa: F401
