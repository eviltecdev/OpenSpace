"""OpenSpace recording — DEPRECATED, use ruflo.recording instead."""
# Lazy imports to avoid circular deps
def __getattr__(name):
    if name == "RecordingManager":
        from ruflo.recording.manager import RecordingManager
        return RecordingManager
    elif name == "TrajectoryRecorder":
        from ruflo.recording.trajectory_recorder import TrajectoryRecorder
        return TrajectoryRecorder
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["RecordingManager", "TrajectoryRecorder"]
