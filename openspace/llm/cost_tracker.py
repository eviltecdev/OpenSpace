"""OpenAI API cost tracker — schreibt Tageskosten in eine Cache-Datei.

Wird vom LLMClient nach jedem API-Call aufgerufen.
Die Statusleiste liest daraus.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("openspace.llm.cost_tracker")

_CACHE_DIR = Path("/tmp")

_OPENAI_PREFIXES = ("openai", "gpt", "o1", "o3")
_ANTHROPIC_PREFIXES = ("anthropic", "claude")


def _cache_file(provider: str = "openai") -> Path:
    return _CACHE_DIR / f"{provider}-daily-costs-{date.today()}.json"


def _load_cache(provider: str = "openai") -> dict:
    f = _cache_file(provider)
    if not f.exists():
        return {"total": 0.0, "calls": 0, "models": {}}
    try:
        return json.loads(f.read_text())
    except Exception:
        return {"total": 0.0, "calls": 0, "models": {}}


def _save_cache(data: dict, provider: str = "openai") -> None:
    try:
        _cache_file(provider).write_text(json.dumps(data))
    except Exception as e:
        logger.debug("Cost tracker: could not write cache: %s", e)


def _detect_provider(model: str) -> Optional[str]:
    """Returns 'openai', 'anthropic', or None for unknown providers."""
    model_lower = (model or "").lower()
    if any(p in model_lower for p in _OPENAI_PREFIXES):
        return "openai"
    if any(p in model_lower for p in _ANTHROPIC_PREFIXES):
        return "anthropic"
    return None


def record_cost(response: Any, model: str) -> Optional[float]:
    """Extrahiert Kosten aus einer LiteLLM-Response und speichert sie.

    Gibt den berechneten Cost-Wert zurück (oder None wenn nicht verfügbar).
    """
    if response is None:
        return None

    cost = None

    # LiteLLM setzt _response_cost oder _hidden_params
    try:
        cost = getattr(response, "_response_cost", None)
    except Exception:
        pass

    if cost is None:
        try:
            hidden = getattr(response, "_hidden_params", {}) or {}
            cost = hidden.get("response_cost") or hidden.get("_response_cost")
        except Exception:
            pass

    # Manuell berechnen via liteLLM wenn Usage vorhanden
    if cost is None:
        try:
            import litellm
            usage = getattr(response, "usage", None)
            if usage:
                cost = litellm.completion_cost(completion_response=response)
        except Exception as e:
            logger.debug("litellm.completion_cost failed for model=%s: %s", model, e)

    # Fallback: manuell über cost_per_token berechnen
    if cost is None or cost <= 0:
        try:
            import litellm
            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                if prompt_tokens > 0 or completion_tokens > 0:
                    prompt_cost, completion_cost = litellm.cost_per_token(
                        model=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                    cost = prompt_cost + completion_cost
                    logger.debug(
                        "Cost via cost_per_token: model=%s prompt=%d compl=%d cost=%.6f",
                        model, prompt_tokens, completion_tokens, cost,
                    )
        except Exception as e:
            logger.debug("cost_per_token fallback failed for model=%s: %s", model, e)

    if cost is None or cost <= 0:
        logger.debug("No cost recorded for model=%s (cost=%s)", model, cost)
        return None

    provider = _detect_provider(model)
    if provider is None:
        logger.debug("Unknown provider for model=%s — cost not tracked", model)
        return cost

    data = _load_cache(provider)
    data["total"] = round(data.get("total", 0.0) + cost, 6)
    data["calls"] = data.get("calls", 0) + 1

    models = data.get("models", {})
    short_model = model.split("/")[-1] if "/" in model else model
    models[short_model] = round(models.get(short_model, 0.0) + cost, 6)
    data["models"] = models

    _save_cache(data, provider)
    logger.debug("%s cost recorded: $%.6f (model=%s, total=$%.4f)", provider, cost, model, data["total"])
    return cost


def get_daily_total() -> Optional[dict]:
    """Gibt heutigen Kosten-Summary zurück (alle Provider kombiniert)."""
    openai_data = _load_cache("openai")
    claude_data = _load_cache("anthropic")

    combined_total = round(openai_data["total"] + claude_data["total"], 6)
    if combined_total == 0.0 and openai_data["calls"] == 0 and claude_data["calls"] == 0:
        return None

    return {
        "total": combined_total,
        "calls": openai_data["calls"] + claude_data["calls"],
        "models": {**openai_data["models"], **claude_data["models"]},
        "by_provider": {
            "openai": openai_data,
            "anthropic": claude_data,
        },
    }


def get_daily_total_by_provider(provider: str) -> Optional[dict]:
    """Gibt heutigen Kosten-Summary für einen spezifischen Provider zurück."""
    data = _load_cache(provider)
    if data["total"] == 0.0 and data["calls"] == 0:
        return None
    return data
