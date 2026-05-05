"""OpenSpace grounding — DEPRECATED, use ruflo.grounding instead."""
# Lazy imports to avoid circular deps
def __getattr__(name):
    if name == "GroundingClient":
        from ruflo.grounding.core.grounding_client import GroundingClient
        return GroundingClient
    elif name == "BaseTool":
        from ruflo.grounding.core.tool import BaseTool
        return BaseTool
    elif name == "ToolResult":
        from ruflo.grounding.core.types import ToolResult
        return ToolResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["GroundingClient", "BaseTool", "ToolResult"]
