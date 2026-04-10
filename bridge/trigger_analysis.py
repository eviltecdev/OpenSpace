#!/usr/bin/env python3
"""
OpenSpace Background Analysis Trigger
======================================
Runs OpenSpace's ExecutionAnalyzer on a completed Claude Code recording.
Launched as a detached background process by claude_recorder.py after Stop.

Usage:
  python3 trigger_analysis.py <task_id> <recording_dir>
"""

import asyncio
import sys
import os
import json
import datetime
from pathlib import Path

OPENSPACE_DIR = Path("/home/claude/OpenSpace")
LOG_FILE = OPENSPACE_DIR / "logs" / "openspace-dashboard" / "cc_analysis.log"


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"{ts} {msg}\n")


async def run_analysis(task_id: str, recording_dir: str) -> None:
    try:
        # Ensure OpenSpace is importable
        sys.path.insert(0, str(OPENSPACE_DIR))

        from openspace.host_detection import load_runtime_env, build_llm_kwargs
        load_runtime_env()

        from openspace.llm.client import LLMClient
        from openspace.skill_engine.store import SkillStore
        from openspace.skill_engine.analyzer import ExecutionAnalyzer
        from openspace.utils.logging import Logger

        Logger.set_level("ERROR")  # Silent in background

        # Use the cheapest/fastest model for analysis
        model_str = os.environ.get("OPENSPACE_ANALYSIS_MODEL", "")
        if not model_str:
            # Auto-detect from available API keys
            if os.environ.get("ANTHROPIC_API_KEY"):
                model_str = "anthropic/claude-haiku-4-5-20251001"
            else:
                model_str, _ = build_llm_kwargs("")

        llm_client = LLMClient(model=model_str, timeout=60.0, max_retries=2)

        db_path = OPENSPACE_DIR / ".openspace" / "openspace.db"
        store = SkillStore(str(db_path))

        analyzer = ExecutionAnalyzer(
            store=store,
            llm_client=llm_client,
            enabled=True,
        )

        # Build a minimal execution_result dict from metadata
        meta_file = Path(recording_dir) / "metadata.json"
        exec_result: dict = {"status": "success", "response": "", "task_id": task_id}
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
            outcome = meta.get("execution_outcome") or {}
            exec_result = {
                "status": outcome.get("status", "success"),
                "response": meta.get("task_name", ""),
                "task_id": task_id,
                "execution_time": outcome.get("execution_time", 0),
                "iterations": outcome.get("iterations", 0),
                "tool_executions": [],
                "active_skills": [],
                "evolved_skills": [],
            }

        analysis = await analyzer.analyze_execution(
            task_id=task_id,
            recording_dir=recording_dir,
            execution_result=exec_result,
        )

        if analysis:
            suggestions = len(analysis.evolution_suggestions)
            _log(f"[OK] {task_id}: completed={analysis.task_completed}, "
                 f"suggestions={suggestions}, "
                 f"note={analysis.execution_note[:80]!r}")
        else:
            _log(f"[SKIP] {task_id}: analyzer returned None (insufficient data)")

    except Exception as e:
        _log(f"[ERR] {task_id}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)

    task_id = sys.argv[1]
    recording_dir = sys.argv[2]

    asyncio.run(run_analysis(task_id, recording_dir))
