"""OpenSpace config — DEPRECATED, use ruflo.config instead."""
# Lazy imports to avoid circular deps
def __getattr__(name):
    if name == "get_config":
        from ruflo.config.loader import get_config
        return get_config
    elif name == "load_config":
        from ruflo.config.loader import load_config
        return load_config
    elif name == "OpenSpaceConfig":
        from ruflo.config.types import OpenSpaceConfig
        return OpenSpaceConfig
    elif name == "GroundingConfig":
        from ruflo.config.types import GroundingConfig
        return GroundingConfig
    elif name == "constants":
        from ruflo.config import constants
        return constants
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["get_config", "load_config", "OpenSpaceConfig", "GroundingConfig"]
