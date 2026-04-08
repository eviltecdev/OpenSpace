"""Automatic model router for OpenSpace.

Classifies tasks by keyword patterns and routes them to the most
suitable LLM — Claude Sonnet for complex reasoning/code, GPT-4o-mini
for creative/general tasks, Claude Haiku for simple/quick requests.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional

from openspace.config.constants import MODEL_CLAUDE, MODEL_HAIKU, MODEL_GPT

logger = logging.getLogger("openspace.llm.task_router")

# ---------------------------------------------------------------------------
# Model identifiers (re-exported from constants for backwards compatibility)
# ---------------------------------------------------------------------------
MODEL_GPT_MINI = MODEL_GPT


@dataclass
class RouteDecision:
    model: str
    reason: str


# ---------------------------------------------------------------------------
# Keyword pattern sets
# ---------------------------------------------------------------------------

_CLAUDE_PATTERNS = re.compile(
    r"\b("
    r"debug|debugg|fehler|bug|error|traceback|exception|crash|fix|reparier"
    r"|refactor|refaktor|architektur|architecture|design pattern"
    r"|code review|pull request|merge|git"
    r"|analyse|analyze|analys|untersuche|untersuchen|prüf"
    r"|screenshot|bild|image|vision|gui|klick|button|fenster|window|screen"
    r"|sicherheit|security|vulnerability|injection|exploit"
    r"|datenbank|database|sql|query|schema|migration"
    r"|performance|optimier|optimiz|speicher|memory|cpu|latenz"
    r"|typescript|python|rust|golang|java|c\+\+|bash|shell script"
    r"|unittest|test|pytest|coverage|ci/cd|pipeline"
    r"|docker|kubernetes|k8s|deployment|infrastruktur"
    r")\b",
    re.IGNORECASE,
)

_GPT_PATTERNS = re.compile(
    r"\b("
    r"schreib|write|erstell.*text|erstell.*bericht|erstell.*zusammenfassung"
    r"|blog|artikel|article|email|e-mail|brief|nachricht|message"
    r"|kreativ|creative|story|geschichte|gedicht|poem"
    r"|erkläre|explain|was ist|what is|wie funktioniert|how does"
    r"|recherchier|research|suche.*nach|search for|find information"
    r"|übersetze|translate|übersetzung|translation"
    r"|zusammenfasse|summarize|zusammenfassung|summary"
    r"|ideen|ideas|brainstorm|vorschläge|suggestions"
    r"|marketing|seo|content|social media"
    r")\b",
    re.IGNORECASE,
)

_GPT_MINI_PATTERNS = re.compile(
    r"\b("
    r"sag mir|tell me|was ist die|what is the|wie viel|how much|wie many"
    r"|kurz|quick|schnell|fast|einfach|simple|kurze antwort|short answer"
    r"|ja oder nein|yes or no|stimmt das|is that correct|check ob|check if"
    r"|datum|date|uhrzeit|time|wetter|weather|preis|price"
    r")\b",
    re.IGNORECASE,
)

# Long tasks (> N chars) should use Claude for better context handling
_LONG_TASK_THRESHOLD = 500


def route_task(
    task: str,
    default_model: Optional[str] = None,
) -> RouteDecision:
    """Classify a task and return the best model to use.

    Priority: explicit length check → Claude keywords → GPT-mini keywords
              → GPT keywords → default / Claude fallback.
    """
    if not task or not task.strip():
        model = default_model or MODEL_CLAUDE
        return RouteDecision(model=model, reason="empty task → default")

    # Very long tasks → Claude handles large context better
    if len(task) > _LONG_TASK_THRESHOLD:
        return RouteDecision(
            model=MODEL_CLAUDE,
            reason=f"long task ({len(task)} chars) → Claude",
        )

    if _CLAUDE_PATTERNS.search(task):
        return RouteDecision(model=MODEL_CLAUDE, reason="code/debug/analysis → Claude")

    if _GPT_MINI_PATTERNS.search(task):
        return RouteDecision(model=MODEL_GPT_MINI, reason="simple/quick → GPT-mini")

    if _GPT_PATTERNS.search(task):
        return RouteDecision(model=MODEL_GPT, reason="creative/research → GPT-mini")

    # Fallback: Haiku is fast and cheap enough for unmatched tasks
    model = default_model or MODEL_HAIKU
    return RouteDecision(model=model, reason="no pattern matched → Haiku")


def log_route(task: str, decision: RouteDecision) -> None:
    logger.info(
        "[ModelRouter] '%s...' → %s (%s)",
        task[:60].replace("\n", " "),
        decision.model,
        decision.reason,
    )
