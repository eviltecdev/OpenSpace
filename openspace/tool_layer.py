"""OpenSpace tool layer — DEPRECATED, use ruflo.core instead."""
# Lazy imports to avoid circular deps
def __getattr__(name):
    if name == "OpenSpace":
        from ruflo.core.engine import OpenSpace
        return OpenSpace
    elif name == "OpenSpaceConfig":
        from ruflo.core.engine import OpenSpaceConfig
        return OpenSpaceConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["OpenSpace", "OpenSpaceConfig"]
