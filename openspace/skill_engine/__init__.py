"""OpenSpace skill engine — DEPRECATED, use ruflo.skill_engine instead."""
# Lazy imports to avoid circular deps
def __getattr__(name):
    if name == "SkillStore":
        from ruflo.skill_engine.store import SkillStore
        return SkillStore
    elif name == "SkillRegistry":
        from ruflo.skill_engine.registry import SkillRegistry
        return SkillRegistry
    elif name == "ExecutionAnalyzer":
        from ruflo.skill_engine.analyzer import ExecutionAnalyzer
        return ExecutionAnalyzer
    elif name == "SkillEvolver":
        from ruflo.skill_engine.evolver import SkillEvolver
        return SkillEvolver
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["SkillStore", "SkillRegistry", "ExecutionAnalyzer", "SkillEvolver"]
