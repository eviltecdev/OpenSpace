#!/usr/bin/env python3
"""
Migration script: Recalculate success_rate for all old workflows using proper logic.

Old logic: "ERROR" not in output_string (too strict, many false positives)
New logic: result.success boolean field (already computed at execution time)

This script:
1. Finds all traj.jsonl files in logs/recordings
2. Recalculates statistics using result.success (more reliable)
3. Saves as statistics_v2 in metadata.json
4. Reports migration summary
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = PROJECT_ROOT / "logs" / "recordings"

def recalculate_statistics(traj_file: Path) -> Dict[str, Any]:
    """
    Recalculate statistics from trajectory using result.success field.

    Returns:
        {
            "total_steps": int,
            "success_count": int,
            "success_rate": float (0.0-1.0),
            "backends": {backend: count},
            "tools": {tool: count},
            "migrated_at": ISO timestamp
        }
    """
    if not traj_file.exists():
        return None

    try:
        trajectory = []
        with open(traj_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    step = json.loads(line)
                    trajectory.append(step)
    except Exception as e:
        print(f"  ✗ Failed to load {traj_file}: {e}")
        return None

    if not trajectory:
        return None

    total_steps = len(trajectory)
    success_count = 0
    backends = {}
    tools = {}

    for step in trajectory:
        # Use result.success if available, else try to infer from legacy fields
        result = step.get("result", {})
        is_success = result.get("success", False)

        if is_success:
            success_count += 1

        # Count backends and tools
        backend = step.get("backend", "unknown")
        backends[backend] = backends.get(backend, 0) + 1

        tool = step.get("tool", "unknown")
        tools[tool] = tools.get(tool, 0) + 1

    success_rate = success_count / total_steps if total_steps > 0 else 0.0

    return {
        "total_steps": total_steps,
        "success_count": success_count,
        "success_rate": round(success_rate, 4),
        "backends": backends,
        "tools": tools,
        "migrated_at": datetime.now().isoformat(),
    }


def migrate_workflow(workflow_dir: Path) -> Dict[str, Any]:
    """
    Migrate one workflow directory: recalculate stats and update metadata.

    Returns:
        {
            "path": workflow_dir,
            "success": bool,
            "message": str,
            "old_success_rate": float or None,
            "new_success_rate": float,
        }
    """
    traj_file = workflow_dir / "traj.jsonl"
    metadata_file = workflow_dir / "metadata.json"

    result = {
        "path": str(workflow_dir),
        "success": False,
        "message": "",
        "old_success_rate": None,
        "new_success_rate": None,
    }

    # Load old metadata if exists
    old_stats = None
    if metadata_file.exists():
        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
                old_stats = metadata.get("statistics", {})
                result["old_success_rate"] = old_stats.get("success_rate")
        except Exception as e:
            result["message"] = f"Failed to load metadata: {e}"
            return result

    # Recalculate statistics
    new_stats = recalculate_statistics(traj_file)
    if not new_stats:
        result["message"] = "No trajectory found or failed to parse"
        return result

    result["new_success_rate"] = new_stats["success_rate"]

    # Update metadata with statistics_v2
    if metadata_file.exists():
        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except:
            metadata = {}
    else:
        metadata = {}

    # Store both old (now marked as deprecated) and new
    if "statistics" not in metadata:
        metadata["statistics"] = {}

    # Mark old stats as deprecated
    if old_stats:
        metadata["statistics_v1_deprecated"] = old_stats

    # Write new stats
    metadata["statistics"] = new_stats
    metadata["statistics_v2_migrated"] = True

    try:
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        result["success"] = True
        result["message"] = f"Migrated: {new_stats['total_steps']} steps, {new_stats['success_rate']*100:.1f}% success"
    except Exception as e:
        result["message"] = f"Failed to write metadata: {e}"

    return result


def main():
    if not RECORDINGS_DIR.exists():
        print(f"✗ Recordings directory not found: {RECORDINGS_DIR}")
        sys.exit(1)

    # Discover all workflow directories (those with traj.jsonl)
    workflow_dirs = []
    for traj_file in sorted(RECORDINGS_DIR.rglob("traj.jsonl")):
        workflow_dir = traj_file.parent
        workflow_dirs.append(workflow_dir)

    print(f"Found {len(workflow_dirs)} workflows to migrate")
    print()

    success_count = 0
    failed_count = 0
    total_old_success_rate = 0.0
    total_new_success_rate = 0.0
    old_rate_count = 0

    for idx, workflow_dir in enumerate(workflow_dirs, 1):
        result = migrate_workflow(workflow_dir)

        status = "✓" if result["success"] else "✗"
        print(f"{idx:3d}. {status} {workflow_dir.name}")
        print(f"     {result['message']}")

        if result["old_success_rate"] is not None:
            old_rate = result["old_success_rate"] * 100 if isinstance(result["old_success_rate"], float) else result["old_success_rate"]
            new_rate = result["new_success_rate"] * 100
            print(f"     OLD: {old_rate:.1f}% → NEW: {new_rate:.1f}%")
            total_old_success_rate += old_rate
            total_new_success_rate += new_rate
            old_rate_count += 1
        else:
            new_rate = result["new_success_rate"] * 100 if result["new_success_rate"] else 0
            print(f"     NEW: {new_rate:.1f}% (no old stats)")
            total_new_success_rate += new_rate
            old_rate_count += 1

        if result["success"]:
            success_count += 1
        else:
            failed_count += 1

    print()
    print("=" * 70)
    print(f"Migration Summary")
    print("=" * 70)
    print(f"Total workflows:       {len(workflow_dirs)}")
    print(f"Successfully migrated: {success_count}")
    print(f"Failed:                {failed_count}")
    print()

    if old_rate_count > 0:
        avg_old = total_old_success_rate / old_rate_count
        avg_new = total_new_success_rate / old_rate_count
        print(f"Average success rate (OLD): {avg_old:.2f}%")
        print(f"Average success rate (NEW): {avg_new:.2f}%")
        print(f"Improvement: {avg_new - avg_old:+.2f}%")
    else:
        print(f"Average success rate (NEW): {total_new_success_rate / len(workflow_dirs) if workflow_dirs else 0:.2f}%")

    print()
    print("✓ Migration complete. Old statistics saved as statistics_v1_deprecated.")


if __name__ == "__main__":
    main()
