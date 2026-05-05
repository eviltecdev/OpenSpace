"""OpenSpace LLM client — DEPRECATED, use ruflo.llm instead."""
# Lazy imports to avoid circular deps
def __getattr__(name):
    if name == "LLMClient":
        from ruflo.llm.client import LLMClient
        return LLMClient
    elif name == "route_task":
        from ruflo.llm.task_router import route_task
        return route_task
    elif name == "CostTracker":
        from ruflo.llm.cost_tracker import CostTracker
        return CostTracker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["LLMClient", "route_task", "CostTracker"]
