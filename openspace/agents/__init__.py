"""OpenSpace agents — DEPRECATED, use ruflo.agents instead."""
# Lazy imports to avoid circular deps
def __getattr__(name):
    if name == "GroundingAgent":
        from ruflo.agents.grounding_agent import GroundingAgent
        return GroundingAgent
    elif name == "BaseAgent":
        from ruflo.agents.base import BaseAgent
        return BaseAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["GroundingAgent", "BaseAgent"]
