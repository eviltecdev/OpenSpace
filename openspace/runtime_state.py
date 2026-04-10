"""Lightweight operational state bridge for HTTP health checks.

This module provides non-blocking getters for system state without importing
the heavy mcp_server or its dependencies. Used by local_server health checks.

Design: Routes call get_*() functions which handle import errors gracefully,
never raising exceptions. Defaults are safe (not_ready, unknown status, zero counts).
"""

from typing import Optional


def get_is_ready() -> bool:
    """Check if system is ready to serve requests.

    Returns True only if:
    1. OpenSpace engine is initialized
    2. Shutdown has NOT been requested

    Returns False if either condition fails or if state cannot be read.
    NEVER raises exceptions.
    """
    try:
        from openspace.mcp_server import _openspace_instance, _shutdown_requested

        openspace_ready = (
            _openspace_instance is not None
            and _openspace_instance.is_initialized()
        )
        not_shutting_down = not _shutdown_requested
        return openspace_ready and not_shutting_down
    except (ImportError, AttributeError, Exception):
        # Any error reading state → not ready
        return False


def get_openspace_initialized() -> bool:
    """Check if OpenSpace engine is initialized.

    Returns True only if OpenSpace instance exists and is initialized.
    Returns False otherwise or on any error.
    """
    try:
        from openspace.mcp_server import _openspace_instance

        return (
            _openspace_instance is not None
            and _openspace_instance.is_initialized()
        )
    except (ImportError, AttributeError, Exception):
        return False


def get_execute_task_active() -> int:
    """Get count of active execute_task limiter slots.

    Returns 0 if limiter not available or on any error.
    """
    try:
        from openspace.mcp_server_limiter import execute_task_limiter

        return execute_task_limiter.active_tasks
    except (ImportError, AttributeError, Exception):
        return 0


def get_search_skills_active() -> int:
    """Get count of active search_skills limiter slots.

    Returns 0 if limiter not available or on any error.
    """
    try:
        from openspace.mcp_server_limiter import search_skills_limiter

        return search_skills_limiter.active_tasks
    except (ImportError, AttributeError, Exception):
        return 0


def get_cloud_status() -> str:
    """Get last known cloud API status.

    Returns one of: 'available', 'degraded', 'unavailable', 'unknown'
    Returns 'unknown' on any error.
    """
    try:
        from openspace.mcp_server import _last_cloud_status

        return _last_cloud_status
    except (ImportError, AttributeError, Exception):
        return "unknown"


def get_shutdown_requested() -> bool:
    """Check if graceful shutdown has been requested.

    Returns True if shutdown in progress, False otherwise.
    Returns False on any error.
    """
    try:
        from openspace.mcp_server import _shutdown_requested

        return _shutdown_requested
    except (ImportError, AttributeError, Exception):
        return False
