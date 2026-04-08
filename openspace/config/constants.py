from pathlib import Path

# ---------------------------------------------------------------------------
# LLM Model identifiers (single source of truth)
# ---------------------------------------------------------------------------
MODEL_CLAUDE = "anthropic/claude-sonnet-4-6"       # Code / Debug / Architecture
MODEL_HAIKU = "anthropic/claude-haiku-4-5-20251001"  # Fallback / Simple / Fast
MODEL_GPT = "openai/gpt-4o-mini"                   # Creative / Research / General

CONFIG_GROUNDING = "config_grounding.json"
CONFIG_SECURITY = "config_security.json"
CONFIG_MCP = "config_mcp.json"
CONFIG_DEV = "config_dev.json"
CONFIG_AGENTS = "config_agents.json"

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Project root directory (OpenSpace/)
PROJECT_ROOT = Path(__file__).parent.parent.parent


__all__ = [
    "MODEL_CLAUDE",
    "MODEL_HAIKU",
    "MODEL_GPT",
    "CONFIG_GROUNDING",
    "CONFIG_SECURITY",
    "CONFIG_MCP",
    "CONFIG_DEV",
    "CONFIG_AGENTS",
    "LOG_LEVELS",
    "PROJECT_ROOT",
]