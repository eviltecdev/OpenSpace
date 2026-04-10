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

        # Defensive: check if instance exists and has is_initialized method
        openspace_ready = False
        if _openspace_instance is not None:
            try:
                if hasattr(_openspace_instance, 'is_initialized') and callable(_openspace_instance.is_initialized):
                    openspace_ready = _openspace_instance.is_initialized()
            except Exception:
                pass

        # Defensive: safely read shutdown flag
        try:
            not_shutting_down = not _shutdown_requested
        except Exception:
            not_shutting_down = False

        return openspace_ready and not_shutting_down
    except Exception:
        # Any error reading state → not ready
        return False


def get_openspace_initialized() -> bool:
    """Check if OpenSpace engine is initialized.

    Returns True only if OpenSpace instance exists and is initialized.
    Returns False otherwise or on any error.
    """
    try:
        from openspace.mcp_server import _openspace_instance

        # Defensive: check instance and method existence
        if _openspace_instance is None:
            return False
        if not hasattr(_openspace_instance, 'is_initialized'):
            return False
        if not callable(_openspace_instance.is_initialized):
            return False
        try:
            return _openspace_instance.is_initialized()
        except Exception:
            return False
    except Exception:
        return False


def get_execute_task_active() -> int:
    """Get count of active execute_task limiter slots.

    Returns 0 if limiter not available or on any error.
    """
    try:
        from openspace.mcp_server_limiter import execute_task_limiter

        # Defensive: check attribute exists and is an int
        if execute_task_limiter is None:
            return 0
        if not hasattr(execute_task_limiter, 'active_tasks'):
            return 0
        try:
            value = execute_task_limiter.active_tasks
            return int(value) if isinstance(value, (int, float)) else 0
        except (TypeError, ValueError):
            return 0
    except Exception:
        return 0


def get_search_skills_active() -> int:
    """Get count of active search_skills limiter slots.

    Returns 0 if limiter not available or on any error.
    """
    try:
        from openspace.mcp_server_limiter import search_skills_limiter

        # Defensive: check attribute exists and is an int
        if search_skills_limiter is None:
            return 0
        if not hasattr(search_skills_limiter, 'active_tasks'):
            return 0
        try:
            value = search_skills_limiter.active_tasks
            return int(value) if isinstance(value, (int, float)) else 0
        except (TypeError, ValueError):
            return 0
    except Exception:
        return 0


def get_cloud_status() -> str:
    """Get last known cloud API status.

    Returns one of: 'available', 'degraded', 'unavailable', 'unknown'
    Returns 'unknown' on any error.
    """
    try:
        from openspace.mcp_server import _last_cloud_status

        # Defensive: ensure it's a valid string
        status = str(_last_cloud_status) if _last_cloud_status is not None else 'unknown'
        # Validate it's one of the expected values
        valid_statuses = {'available', 'degraded', 'unavailable', 'unknown'}
        return status if status in valid_statuses else 'unknown'
    except Exception:
        return "unknown"


def get_shutdown_requested() -> bool:
    """Check if graceful shutdown has been requested.

    Returns True if shutdown in progress, False otherwise.
    Returns False on any error.
    """
    try:
        from openspace.mcp_server import _shutdown_requested

        # Defensive: ensure it's a bool
        try:
            return bool(_shutdown_requested)
        except Exception:
            return False
    except Exception:
        return False
