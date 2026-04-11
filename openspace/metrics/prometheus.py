"""Prometheus metrics instrumentation for OpenSpace.

Provides metrics for:
- HTTP request count, latency, and exceptions
- Readiness state
- Active task count
- Rate limiter rejections
"""

import re
from typing import Optional
from prometheus_client import Counter, Histogram, Gauge

# HTTP request metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['endpoint', 'method', 'status']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['endpoint', 'method'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0)
)

http_exceptions_total = Counter(
    'http_exceptions_total',
    'Total HTTP exceptions',
    ['endpoint', 'exception_type']
)

# Operational metrics
openspace_readiness = Gauge(
    'openspace_readiness',
    'OpenSpace readiness state (1=ready, 0=not ready)'
)

openspace_active_tasks = Gauge(
    'openspace_active_tasks',
    'Active task count'
)

openspace_limiter_rejections_total = Counter(
    'openspace_limiter_rejections_total',
    'Total rate limiter rejections',
    ['limiter_type']
)


_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}\b"
)
_INT_RE = re.compile(r"(?<=/)\d+(?=/|$)")
_HEX_RE = re.compile(r"(?<=/)[0-9a-fA-F]{16,}(?=/|$)")


def normalize_endpoint(path: str, url_rule: Optional[str] = None) -> str:
    """Normalize request paths for Prometheus labels.

    Priority:
    1. Use Flask's route template (`request.url_rule.rule`) when available.
       Example: /api/v1/skills/<int:skill_id> -> /api/v1/skills/{skill_id}
    2. Fall back to regex normalization on the raw path.

    This avoids Prometheus cardinality explosions from IDs, UUIDs, hashes, etc.

    Args:
        path: Request path (e.g., /api/v1/skills/123)
        url_rule: Flask URL rule template (e.g., /api/v1/skills/<int:skill_id>)

    Returns:
        Normalized path safe for metric labels
    """
    if url_rule:
        normalized = url_rule
        # Flask converters: <int:id>, <string:name>, <path:file_path>, <id>
        normalized = re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", normalized)
        return normalized

    normalized = path
    normalized = _UUID_RE.sub("{uuid}", normalized)
    normalized = _INT_RE.sub("{id}", normalized)
    normalized = _HEX_RE.sub("{hex}", normalized)
    return normalized


def record_request(
    endpoint: str,
    method: str,
    status: int,
    duration: float,
) -> None:
    """Record HTTP request metrics.

    Args:
        endpoint: Normalized endpoint label (already processed by normalize_endpoint)
        method: HTTP method (GET, POST, etc.)
        status: HTTP status code
        duration: Request duration in seconds
    """
    http_requests_total.labels(endpoint=endpoint, method=method, status=status).inc()
    http_request_duration_seconds.labels(endpoint=endpoint, method=method).observe(duration)


def record_exception(
    endpoint: str,
    exc_type: str,
) -> None:
    """Record HTTP exception.

    Args:
        endpoint: Normalized endpoint label (already processed by normalize_endpoint)
        exc_type: Exception class name
    """
    http_exceptions_total.labels(endpoint=endpoint, exception_type=exc_type).inc()
