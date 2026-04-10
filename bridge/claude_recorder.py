#!/usr/bin/env python3
"""
OpenSpace Bridge – Claude Code Session Recorder
================================================
Captures every Claude Code session as an OpenSpace recording so the dashboard
shows real activity and the skill-learning pipeline can learn from it.

Called via Claude Code hooks (settings.json):
  UserPromptSubmit  →  claude_recorder.py start
  PostToolUse       →  claude_recorder.py record-tool
  Stop              →  claude_recorder.py stop
"""

import sys
import json
import os
import datetime
import hashlib
import subprocess
from pathlib import Path

OPENSPACE_DIR = Path("/home/claude/OpenSpace")
RECORDINGS_DIR = OPENSPACE_DIR / "logs" / "recordings"
STATE_DIR = Path("/tmp/openspace_cc_sessions")
BRIDGE_DIR = Path(__file__).parent


def _now() -> str:
    return datetime.datetime.now().isoformat()


def _state_file(session_id: str) -> Path:
    STATE_DIR.mkdir(exist_ok=True)
    safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64]
    return STATE_DIR / f"{safe_id}.json"


def _load_state(session_id: str) -> dict | None:
    f = _state_file(session_id)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            return None
    return None


def _save_state(session_id: str, state: dict) -> None:
    _state_file(session_id).write_text(json.dumps(state, indent=2))


def _clear_state(session_id: str) -> None:
    f = _state_file(session_id)
    if f.exists():
        f.unlink()


def _read_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _backend_for_tool(tool_name: str) -> str:
    shell_tools = {"Bash", "bash", "Read", "Write", "Edit", "Glob", "Grep",
                   "MultiEdit", "NotebookEdit"}
    web_tools = {"WebFetch", "WebSearch"}
    if tool_name in shell_tools:
        return "shell"
    if tool_name in web_tools:
        return "web"
    return "mcp"


def _command_summary(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash" and "command" in tool_input:
        return tool_input["command"][:300]
    if "file_path" in tool_input:
        return f"{tool_name}({tool_input['file_path']})"
    if "pattern" in tool_input:
        return f"{tool_name}(pattern={tool_input['pattern'][:100]})"
    parts = [f"{k}={repr(v)[:60]}" for k, v in list(tool_input.items())[:3]]
    return f"{tool_name}({', '.join(parts)})"


# ---------------------------------------------------------------------------
# COMMAND: start
# ---------------------------------------------------------------------------

def start():
    """Create a new recording for the current user turn."""
    data = _read_stdin()
    session_id = data.get("session_id", "unknown")
    prompt = data.get("prompt", "")

    now = datetime.datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")
    uid = hashlib.md5(f"{session_id}{ts}{prompt}".encode()).hexdigest()[:12]
    task_id = f"cc_{uid}_{ts}"

    task_dir = RECORDINGS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "task_id": task_id,
        "task_name": (prompt[:80] + "…") if len(prompt) > 80 else prompt,
        "start_time": now.isoformat(),
        "end_time": None,
        "instruction": prompt,
        "backends": ["shell", "mcp", "web"],
        "enable_screenshot": False,
        "enable_video": False,
        "enable_conversation_log": True,
        "total_steps": 0,
        "backend_counts": {},
        "execution_outcome": None,
        "source": "claude_code",
        "session_id": session_id,
    }
    (task_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (task_dir / "traj.jsonl").write_text("")
    (task_dir / "agent_actions.jsonl").write_text("")

    # conversations.jsonl – seed with the user prompt
    conv_setup = {
        "type": "setup",
        "agent_name": "ClaudeCode",
        "timestamp": now.isoformat(),
        "messages": [{"role": "user", "content": prompt}],
        "tools": [],
        "extra": {"source": "claude_code", "session_id": session_id},
    }
    (task_dir / "conversations.jsonl").write_text(json.dumps(conv_setup) + "\n")

    _save_state(session_id, {
        "session_id": session_id,
        "task_id": task_id,
        "task_dir": str(task_dir),
        "step": 0,
        "start_time": now.isoformat(),
        "prompt": prompt,
    })


# ---------------------------------------------------------------------------
# COMMAND: record-tool
# ---------------------------------------------------------------------------

def record_tool():
    """Append one tool-execution step to traj.jsonl."""
    data = _read_stdin()
    session_id = data.get("session_id", "unknown")

    state = _load_state(session_id)
    if not state:
        return

    tool_name = data.get("tool_name", "unknown")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", "")

    step = state["step"] + 1
    state["step"] = step
    _save_state(session_id, state)

    task_dir = Path(state["task_dir"])

    # Determine success
    is_success = True
    if isinstance(tool_response, dict):
        is_success = not tool_response.get("is_error", False)

    # Truncate result
    if isinstance(tool_response, str):
        result_str = tool_response[:3000]
    else:
        try:
            result_str = json.dumps(tool_response)[:3000]
        except Exception:
            result_str = str(tool_response)[:3000]

    # Sanitize tool_input (remove non-serialisable values)
    safe_input = {}
    for k, v in tool_input.items():
        if not isinstance(v, (bytes, bytearray)):
            try:
                json.dumps(v)
                safe_input[k] = v
            except Exception:
                safe_input[k] = str(v)[:200]

    step_entry = {
        "step": step,
        "timestamp": _now(),
        "backend": _backend_for_tool(tool_name),
        "tool": tool_name,
        "command": _command_summary(tool_name, tool_input),
        "parameters": safe_input,
        "result": {"output": result_str, "success": is_success},
        "screenshot": None,
    }

    with open(task_dir / "traj.jsonl", "a") as f:
        f.write(json.dumps(step_entry) + "\n")


# ---------------------------------------------------------------------------
# COMMAND: stop
# ---------------------------------------------------------------------------

def stop():
    """Finalise the recording and trigger background analysis."""
    data = _read_stdin()
    session_id = data.get("session_id", "unknown")

    state = _load_state(session_id)
    if not state:
        return

    task_dir = Path(state["task_dir"])
    meta_file = task_dir / "metadata.json"

    if meta_file.exists():
        metadata = json.loads(meta_file.read_text())
        now = datetime.datetime.now()
        start_dt = datetime.datetime.fromisoformat(state["start_time"])
        duration = (now - start_dt).total_seconds()

        metadata["end_time"] = now.isoformat()
        metadata["total_steps"] = state["step"]

        # Count by backend
        counts: dict = {}
        traj_file = task_dir / "traj.jsonl"
        if traj_file.exists():
            for line in traj_file.read_text().splitlines():
                try:
                    entry = json.loads(line)
                    b = entry.get("backend", "mcp")
                    counts[b] = counts.get(b, 0) + 1
                except Exception:
                    pass

        metadata["backend_counts"] = counts
        metadata["execution_outcome"] = {
            "status": "success",
            "iterations": state["step"],
            "execution_time": round(duration, 2),
        }
        meta_file.write_text(json.dumps(metadata, indent=2))

    task_id = state["task_id"]
    _clear_state(session_id)

    # Skip analysis for short sessions – not worth LLM cost
    if state["step"] < 15:
        return

    analysis_script = BRIDGE_DIR / "trigger_analysis.py"
    if analysis_script.exists():
        subprocess.Popen(
            [sys.executable, str(analysis_script), task_id, str(task_dir)],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "start":
            start()
        elif cmd == "record-tool":
            record_tool()
        elif cmd == "stop":
            stop()
    except Exception:
        # Never crash or disrupt the Claude Code session
        pass
