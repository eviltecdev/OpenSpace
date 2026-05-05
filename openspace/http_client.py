"""OpenSpace HTTP Clients — Runtime and Control plane separation.

Architecture:
- RuntimeClient: Execute commands, check health/readiness/status (local_server)
- ControlClient: Manage skills, workflows, routes, costs (dashboard_server)
- Both use HTTP only (no direct MCP or internal state access)
"""

from __future__ import annotations

import os
import json
import logging
from typing import Any, Dict, Optional
from urllib.parse import urljoin

try:
    import requests
    import requests.adapters
except ImportError:
    requests = None  # type: ignore

logger = logging.getLogger(__name__)


class BaseHTTPClient:
    """Base HTTP client for OpenSpace.

    Handles common HTTP operations and session management.
    """

    def __init__(self, base_url: str, api_token: Optional[str] = None, timeout: int = 30):
        """Initialize HTTP client.

        Args:
            base_url: Server URL (default: http://localhost:5000)
            api_token: Bearer token for authentication (if needed)
            timeout: Request timeout in seconds (default: 30)
        """
        if not requests:
            raise ImportError(
                "requests library required. Install with: pip install requests"
            )

        self.base_url = base_url.rstrip("/")
        self.api_token = api_token or os.environ.get("OPENSPACE_API_TOKEN", "").strip()
        self.timeout = timeout
        self.session = requests.Session()

        # Add retry logic
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
            )
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _get_headers(self, needs_auth: bool = False) -> Dict[str, str]:
        """Get HTTP headers.

        Args:
            needs_auth: Whether this endpoint requires authentication

        Returns:
            HTTP headers dict
        """
        headers = {"Content-Type": "application/json"}
        if needs_auth and self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        needs_auth: bool = False,
    ) -> Dict[str, Any]:
        """Execute HTTP request.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: JSON request body (for POST/PUT)
            params: Query parameters
            needs_auth: Whether endpoint requires authentication

        Returns:
            Parsed JSON response

        Raises:
            requests.RequestException: On network/HTTP errors
        """
        url = urljoin(self.base_url, endpoint)
        headers = self._get_headers(needs_auth=needs_auth)

        try:
            if method.upper() == "GET":
                response = self.session.get(
                    url, headers=headers, params=params, timeout=self.timeout
                )
            elif method.upper() == "POST":
                response = self.session.post(
                    url,
                    headers=headers,
                    json=data,
                    params=params,
                    timeout=self.timeout,
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP request failed: {method} {url}: {e}")
            raise


class RuntimeClient(BaseHTTPClient):
    """OpenSpace Runtime Client — Execute commands, check health/readiness/status.

    Communicates with local_server (no authentication required).
    Endpoints:
    - GET /health — Liveness probe (always 200 if process alive)
    - GET /ready — Readiness probe (200 if ready, 503 if not)
    - GET /status — Diagnostics & uptime (always 200)
    - POST /execute — Execute system commands
    """

    def health(self) -> Dict[str, Any]:
        """Get liveness status (always 200 if process alive).

        Returns:
            Dict with 'status': 'ok'
        """
        return self._request("GET", "/health", needs_auth=False)

    def ready(self) -> Dict[str, Any]:
        """Check readiness (200 if ready, 503 if not).

        Returns:
            Dict with 'ready': bool and 'reason': str|None
        """
        return self._request("GET", "/ready", needs_auth=False)

    def status(self) -> Dict[str, Any]:
        """Get diagnostics and status (always 200).

        Returns:
            Dict with uptime, init state, limiter counts, cloud status
        """
        return self._request("GET", "/status", needs_auth=False)

    def execute(
        self,
        command: str | list[str],
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """Execute a shell command on the system.

        Args:
            command: Command as string or list of arguments
            timeout: Timeout in seconds (default: 120)

        Returns:
            Dict with 'status', 'output', 'error', 'returncode'
        """
        data = {
            "type": "shell",
            "command": command,
            "timeout": timeout,
        }
        return self._request("POST", "/execute", data=data, needs_auth=False)

    def task(
        self,
        task: str,
        input: Optional[Dict[str, Any]] = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """Execute a structured task.

        Args:
            task: Task name (e.g., "list_directory", "read_file", etc.)
            input: Task input parameters as dict (e.g., {"path": "/tmp"})
            timeout: Timeout in seconds (default: 120)

        Returns:
            Dict with task result data
        """
        data = {
            "type": "task",
            "task": task,
            "input": input or {},
            "timeout": timeout,
        }
        return self._request("POST", "/execute", data=data, needs_auth=False)


class ControlClient(BaseHTTPClient):
    """OpenSpace Control Client — Manage skills, workflows, routes, costs.

    Communicates with dashboard_server (authentication required).
    Endpoints:
    - GET /api/v1/skills — List available skills
    - GET /api/v1/workflows — List available workflows
    - POST /api/v1/route-task — Route task for execution
    - GET /api/v1/costs — Get cost tracking data
    - GET /api/v1/overview — System overview
    """

    def list_skills(
        self,
        active_only: bool = True,
        limit: int = 100,
        sort: str = "score",
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List available skills.

        Args:
            active_only: Only list active skills (default: True)
            limit: Max skills to return (default: 100)
            sort: Sort field (score, updated, etc.) (default: "score")
            query: Search query (skill name, id, or description)

        Returns:
            Dict with 'items' (list of skills) and 'count'
        """
        params = {
            "active_only": str(active_only).lower(),
            "limit": limit,
            "sort": sort,
        }
        if query:
            params["query"] = query

        return self._request("GET", "/api/v1/skills", params=params, needs_auth=True)

    def get_skill(self, skill_id: str) -> Dict[str, Any]:
        """Get detailed skill information.

        Args:
            skill_id: Skill identifier

        Returns:
            Skill detail dict with metadata, source, lineage, analyses
        """
        return self._request("GET", f"/api/v1/skills/{skill_id}", needs_auth=True)

    def skill_stats(self) -> Dict[str, Any]:
        """Get aggregate skill statistics.

        Returns:
            Stats dict with counts, averages, etc.
        """
        return self._request("GET", "/api/v1/skills/stats", needs_auth=True)

    def skill_lineage(self, skill_id: str) -> Dict[str, Any]:
        """Get skill evolution lineage (parents, children).

        Args:
            skill_id: Skill identifier

        Returns:
            Lineage graph dict
        """
        return self._request(
            "GET", f"/api/v1/skills/{skill_id}/lineage", needs_auth=True
        )

    def skill_source(self, skill_id: str) -> Dict[str, Any]:
        """Get skill source code.

        Args:
            skill_id: Skill identifier

        Returns:
            Source code and metadata
        """
        return self._request(
            "GET", f"/api/v1/skills/{skill_id}/source", needs_auth=True
        )

    def list_workflows(self) -> Dict[str, Any]:
        """List available workflows.

        Returns:
            Dict with 'items' (list of workflows) and 'count'
        """
        return self._request("GET", "/api/v1/workflows", needs_auth=True)

    def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Get detailed workflow information.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Workflow detail dict with trajectory, artifacts, stats
        """
        return self._request(
            "GET", f"/api/v1/workflows/{workflow_id}", needs_auth=True
        )

    def route_task(self, task: str, **kwargs) -> Dict[str, Any]:
        """Route a task for execution (model selection, skill matching, etc.).

        Args:
            task: Task description/instruction
            **kwargs: Additional routing options (context, preferences, etc.)

        Returns:
            Routing result dict with selected model, skills, metadata
        """
        data = {"task": task, **kwargs}
        return self._request("POST", "/api/v1/route-task", data=data, needs_auth=True)

    def overview(self) -> Dict[str, Any]:
        """Get system overview (skills, workflows, health, pipeline).

        Returns:
            Overview dict with aggregated system status
        """
        return self._request("GET", "/api/v1/overview", needs_auth=True)

    def costs(self) -> Dict[str, Any]:
        """Get LLM cost tracking data.

        Returns:
            Costs dict with daily totals, breakdowns, etc.
        """
        return self._request("GET", "/api/v1/costs", needs_auth=True)


def create_runtime_client(
    base_url: Optional[str] = None,
    timeout: int = 30,
) -> RuntimeClient:
    """Create a RuntimeClient for local_server operations.

    Args:
        base_url: Runtime server URL (env: OPENSPACE_RUNTIME_URL or OPENSPACE_LOCAL_URL,
                  default: http://localhost:5000)
        timeout: Request timeout in seconds

    Returns:
        Initialized RuntimeClient
    """
    base_url = (
        base_url
        or os.environ.get("OPENSPACE_RUNTIME_URL")
        or os.environ.get("OPENSPACE_LOCAL_URL", "http://localhost:5000")
    )
    return RuntimeClient(base_url=base_url, timeout=timeout)


def create_control_client(
    base_url: Optional[str] = None,
    api_token: Optional[str] = None,
    timeout: int = 30,
) -> ControlClient:
    """Create a ControlClient for dashboard_server operations.

    Args:
        base_url: Control server URL (env: OPENSPACE_CONTROL_URL or OPENSPACE_DASHBOARD_URL,
                  default: http://localhost:5000)
        api_token: Bearer token for authentication (env: OPENSPACE_API_TOKEN)
        timeout: Request timeout in seconds

    Returns:
        Initialized ControlClient
    """
    base_url = (
        base_url
        or os.environ.get("OPENSPACE_CONTROL_URL")
        or os.environ.get("OPENSPACE_DASHBOARD_URL", "http://localhost:5000")
    )
    api_token = api_token or os.environ.get("OPENSPACE_API_TOKEN")
    return ControlClient(base_url=base_url, api_token=api_token, timeout=timeout)


class OpenSpaceClient:
    """Unified OpenSpace client facade.

    Provides access to both RuntimeClient and ControlClient through a single interface.

    Usage:
        client = OpenSpaceClient()
        client.runtime().execute(...)
        client.control().skills(...)
    """

    def __init__(
        self,
        runtime_url: Optional[str] = None,
        control_url: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        """Initialize OpenSpace client.

        Args:
            runtime_url: Runtime server URL (env: OPENSPACE_RUNTIME_URL or OPENSPACE_LOCAL_URL)
            control_url: Control server URL (env: OPENSPACE_CONTROL_URL or OPENSPACE_DASHBOARD_URL)
            api_token: Bearer token for ControlClient (env: OPENSPACE_API_TOKEN)
        """
        self._runtime = create_runtime_client(base_url=runtime_url)
        self._control = create_control_client(base_url=control_url, api_token=api_token)

    def runtime(self) -> RuntimeClient:
        """Get RuntimeClient (execution, health, readiness, status).

        Returns:
            RuntimeClient instance
        """
        return self._runtime

    def control(self) -> ControlClient:
        """Get ControlClient (skills, workflows, routing, costs).

        Returns:
            ControlClient instance
        """
        return self._control


def create_client(
    runtime_url: Optional[str] = None,
    control_url: Optional[str] = None,
    api_token: Optional[str] = None,
) -> OpenSpaceClient:
    """Create a unified OpenSpace client.

    Args:
        runtime_url: Runtime server URL (env: OPENSPACE_RUNTIME_URL or OPENSPACE_LOCAL_URL,
                     default: http://localhost:5000)
        control_url: Control server URL (env: OPENSPACE_CONTROL_URL or OPENSPACE_DASHBOARD_URL,
                     default: http://localhost:5000)
        api_token: Bearer token for ControlClient (env: OPENSPACE_API_TOKEN)

    Returns:
        Initialized OpenSpaceClient (provides .runtime() and .control() methods)

    Example:
        client = create_client()
        await client.runtime().health()
        await client.control().list_skills()
    """
    return OpenSpaceClient(
        runtime_url=runtime_url,
        control_url=control_url,
        api_token=api_token,
    )
