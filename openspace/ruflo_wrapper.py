"""Ruflo CLI Wrapper — Thin orchestration layer over OpenSpace HTTP API.

This module provides a CLI interface for Ruflo to interact with OpenSpace.
It handles command routing, output formatting, and error handling.

Ruflo (via this wrapper) does NOT own:
- Task execution (OpenSpace owns via execute_task endpoint)
- Skill management (OpenSpace owns via skills endpoints)
- State management (OpenSpace owns)
- Readiness/health (OpenSpace owns)

Ruflo ONLY owns:
- Workflow orchestration and command routing
- User-facing CLI interface
- Workflow definition execution

All execution happens through OpenSpace HTTP API.
"""

from __future__ import annotations

import argparse
import json
import sys
import logging
from typing import Any, Dict, Optional

from openspace.http_client import create_client
from openspace.utils.logging import Logger

logger = Logger.get_logger(__name__)


class RufloWrapper:
    """Thin CLI wrapper for Ruflo that delegates to OpenSpace HTTP API.

    Uses unified OpenSpaceClient with .runtime() and .control() accessors.
    """

    def __init__(
        self,
        runtime_url: Optional[str] = None,
        control_url: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        """Initialize Ruflo wrapper.

        Args:
            runtime_url: Runtime server URL (execute, health, status)
            control_url: Control server URL (skills, workflows, routing)
            api_token: Bearer token for control_server
        """
        self.client = create_client(
            runtime_url=runtime_url,
            control_url=control_url,
            api_token=api_token,
        )

    def ready(self) -> int:
        """Check if OpenSpace is ready (200 if ready, 503 if not)."""
        try:
            result = self.client.runtime().ready()
            ready = result.get("ready", False)
            reason = result.get("reason")

            if ready:
                print("✓ OpenSpace is READY")
                return 0
            else:
                print(f"✗ OpenSpace is NOT READY: {reason}")
                return 1
        except Exception as e:
            logger.error(f"Readiness check failed: {e}")
            print(f"Error: {e}", file=sys.stderr)
            return 1

    def status(self) -> int:
        """Display detailed system status (runtime + control)."""
        try:
            # Runtime server status (execution, readiness)
            runtime_status = self.client.runtime().status()

            # Control server overview (skills, workflows)
            control_overview = self.client.control().overview()

            print("\n" + "=" * 70)
            print("  OPENSPACE STATUS")
            print("=" * 70)

            # Runtime status
            print(f"\nUptime: {runtime_status.get('uptime_seconds', 0)}s")
            print(f"Initialized: {runtime_status.get('initialized', False)}")

            # Control overview
            skills = control_overview.get("skills", {})
            print(f"\nSkills: {skills.get('summary', {}).get('total', 0)}")
            print(f"Average Score: {skills.get('average_score', 0)}")

            workflows = control_overview.get("workflows", {})
            print(f"\nWorkflows: {workflows.get('total', 0)}")
            print(f"Avg Success Rate: {workflows.get('average_success_rate', 0)}%")

            print("\n" + "=" * 70 + "\n")

            return 0
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            print(f"Error: {e}", file=sys.stderr)
            return 1

    def skills(self, limit: int = 10, sort: str = "score", query: Optional[str] = None) -> int:
        """List skills."""
        try:
            result = self.client.control().list_skills(limit=limit, sort=sort, query=query)
            items = result.get("items", [])

            print("\n" + "=" * 70)
            print(f"  SKILLS ({result.get('count', 0)} total)")
            print("=" * 70 + "\n")

            for skill in items:
                print(f"ID: {skill.get('skill_id')}")
                print(f"Name: {skill.get('name')}")
                print(f"Score: {skill.get('score')}")
                print(f"Status: {skill.get('status')}")
                print()

            return 0
        except Exception as e:
            logger.error(f"Failed to list skills: {e}")
            print(f"Error: {e}", file=sys.stderr)
            return 1

    def workflows(self) -> int:
        """List workflows."""
        try:
            result = self.client.control().list_workflows()
            items = result.get("items", [])

            print("\n" + "=" * 70)
            print(f"  WORKFLOWS ({result.get('count', 0)} total)")
            print("=" * 70 + "\n")

            for workflow in items:
                print(f"ID: {workflow.get('workflow_id')}")
                print(f"Name: {workflow.get('name')}")
                print(f"Created: {workflow.get('created_at')}")
                print(f"Success Rate: {workflow.get('success_rate')}%")
                print()

            return 0
        except Exception as e:
            logger.error(f"Failed to list workflows: {e}")
            print(f"Error: {e}", file=sys.stderr)
            return 1

    def route_task(self, task: str) -> int:
        """Route a task for execution.

        Note: This does NOT execute the task. It routes it for execution
        at the OpenSpace level.
        """
        try:
            result = self.client.control().route_task(task)
            print("\n" + "=" * 70)
            print("  ROUTE RESULT")
            print("=" * 70)
            print(json.dumps(result, indent=2))
            print("\n" + "=" * 70 + "\n")

            return 0
        except Exception as e:
            logger.error(f"Failed to route task: {e}")
            print(f"Error: {e}", file=sys.stderr)
            return 1

    def health(self) -> int:
        """Check OpenSpace health."""
        try:
            result = self.client.runtime().health()
            print(json.dumps(result, indent=2))
            return 0
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            print(f"Error: {e}", file=sys.stderr)
            return 1

    def execute(self, command: str, timeout: int = 120) -> int:
        """Execute a shell command.

        Args:
            command: Command string or list to execute
            timeout: Timeout in seconds (default: 120)

        Returns:
            Exit code (0 if successful, 1 if error)
        """
        try:
            result = self.client.runtime().execute(command=command, timeout=timeout)

            if result.get("status") == "success":
                if result.get("output"):
                    print(result["output"], end="")
                if result.get("error"):
                    print(result["error"], end="", file=sys.stderr)
                return result.get("returncode", 0)
            else:
                print(f"Error: {result.get('message')}", file=sys.stderr)
                return 1

        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            print(f"Error: {e}", file=sys.stderr)
            return 1

    def task(self, task: str, task_args: Optional[Dict[str, str]] = None, timeout: int = 120) -> int:
        """Execute a structured task.

        Args:
            task: Task name (e.g., "list_directory", "read_file")
            task_args: Task input parameters as dict (e.g., {"path": "/tmp"})
            timeout: Timeout in seconds (default: 120)

        Returns:
            Exit code (0 if successful, 1 if error)
        """
        try:
            input_dict = task_args or {}

            result = self.client.runtime().task(
                task=task,
                input=input_dict,
                timeout=timeout,
            )

            print("\n" + "=" * 70)
            print(f"  TASK RESULT: {task}")
            print("=" * 70)
            print(json.dumps(result, indent=2))
            print("\n" + "=" * 70 + "\n")

            return 0

        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            print(f"Error: {e}", file=sys.stderr)
            return 1


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for Ruflo CLI."""
    parser = argparse.ArgumentParser(
        description="Ruflo — Workflow Orchestration Layer for OpenSpace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Runtime operations
  ruflo health                                  Check OpenSpace health
  ruflo ready                                   Check readiness
  ruflo status                                  Show system status
  ruflo execute "ls -la /tmp"                   Execute shell command
  ruflo task list_directory --input '{"path": "/tmp"}'  Execute structured task

  # Control operations
  ruflo skills --limit 20                       List top 20 skills
  ruflo workflows                               List workflows
  ruflo route-task "do something"               Route task for execution

Note: Ruflo is a thin orchestration layer over OpenSpace.
All execution happens at the OpenSpace level.
        """,
    )

    parser.add_argument(
        "--runtime-url",
        default=None,
        help="Runtime server URL (env: OPENSPACE_RUNTIME_URL or OPENSPACE_LOCAL_URL)",
    )
    parser.add_argument(
        "--control-url",
        default=None,
        help="Control server URL (env: OPENSPACE_CONTROL_URL or OPENSPACE_DASHBOARD_URL)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Bearer token for control server (env: OPENSPACE_API_TOKEN)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # status command
    subparsers.add_parser("status", help="Show system status")

    # ready command
    subparsers.add_parser("ready", help="Check if OpenSpace is ready")

    # health command
    subparsers.add_parser("health", help="Check OpenSpace health")

    # execute command
    exec_parser = subparsers.add_parser("execute", help="Execute a command on local server")
    exec_parser.add_argument("exec_command", metavar="COMMAND", help="Command to execute")
    exec_parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds")

    # task command
    task_parser = subparsers.add_parser(
        "task",
        help="Execute a structured task",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ruflo task list_directory --path /tmp
  ruflo task read_file --path /home/user/file.txt
  ruflo task write_file --path /tmp/test.txt --content "hello"

Task arguments are passed as --key value pairs and become input dict.
        """,
    )
    task_parser.add_argument("task_name", metavar="TASK", help="Task name")
    task_parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds")
    # Capture remaining arguments as task input
    task_parser.add_argument("task_kwargs", nargs="*", help="Task arguments as --key value pairs")

    # skills command
    skills_parser = subparsers.add_parser("skills", help="List skills")
    skills_parser.add_argument("--limit", type=int, default=10, help="Max skills to show")
    skills_parser.add_argument("--sort", default="score", help="Sort field (score, updated)")
    skills_parser.add_argument("--query", help="Search query")

    # workflows command
    subparsers.add_parser("workflows", help="List workflows")

    # route-task command
    route_parser = subparsers.add_parser("route-task", help="Route task for execution")
    route_parser.add_argument("task", help="Task description")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    wrapper = RufloWrapper(
        runtime_url=args.runtime_url,
        control_url=args.control_url,
        api_token=args.token,
    )

    if args.command == "status":
        return wrapper.status()
    elif args.command == "ready":
        return wrapper.ready()
    elif args.command == "health":
        return wrapper.health()
    elif args.command == "skills":
        return wrapper.skills(
            limit=args.limit,
            sort=args.sort,
            query=args.query,
        )
    elif args.command == "workflows":
        return wrapper.workflows()
    elif args.command == "route-task":
        return wrapper.route_task(args.task)
    elif args.command == "execute":
        return wrapper.execute(command=args.exec_command, timeout=args.timeout)
    elif args.command == "task":
        # Parse task arguments from --key value pairs
        task_args = {}
        i = 0
        while i < len(args.task_kwargs):
            arg = args.task_kwargs[i]
            if arg.startswith("--"):
                key = arg[2:]  # Remove -- prefix
                if i + 1 < len(args.task_kwargs) and not args.task_kwargs[i + 1].startswith("--"):
                    value = args.task_kwargs[i + 1]
                    task_args[key] = value
                    i += 2
                else:
                    print(f"Error: --{key} requires a value", file=sys.stderr)
                    return 1
            else:
                print(f"Error: Unknown argument format: {arg}", file=sys.stderr)
                return 1

        return wrapper.task(
            task=args.task_name,
            task_args=task_args,
            timeout=args.timeout,
        )
    else:
        parser.print_error(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
