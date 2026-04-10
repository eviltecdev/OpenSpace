# LLMClient Auto Model Selection

## Overview

`LLMClient` now supports **automatic model selection** to intelligently choose between Haiku and Sonnet based on task complexity.

## How It Works

When `auto_select_model=True` is passed to `complete()`, the LLMClient will:

1. Analyze the task description
2. Evaluate complexity using heuristics
3. Select the most appropriate model:
   - **Haiku** (fast, cheap) for simple tasks
   - **Sonnet** (powerful, more expensive) for complex tasks
4. Log the selection decision
5. Execute with the chosen model

## Usage

### Basic Example

```python
from openspace.llm.client import LLMClient

client = LLMClient()

# Auto-select model based on task complexity
result = await client.complete(
    messages="Design a scalable microservices architecture",
    auto_select_model=True,
)

# The client will automatically select Sonnet (detected "design" + "architecture")
```

### What Triggers Sonnet

Sonnet is automatically selected if ANY of these apply:

| Condition | Example |
|-----------|---------|
| Task > 2000 characters | Very detailed requirements |
| Explicit `[SONNET]` flag | `"Fix this bug [SONNET]"` |
| Architecture keywords | "design", "architect", "pattern" |
| Security keywords | "security", "vulnerability", "exploit", "auth", "token" |
| Debug/diagnosis keywords | "debug", "root cause", "troubleshoot" |
| Refactoring keywords | "refactor", "restructure", "overhaul" |
| Comparison keywords | "compare", "alternative", "tradeoff" |
| Performance keywords | "optimize", "performance", "bottleneck" |
| Multi-file tasks | Multiple file paths mentioned (>3) |

### What Stays with Haiku

Haiku is selected for:

- Simple queries ("What is 2+2?")
- Basic code tasks ("Write a factorial function")
- Creative/general tasks ("Tell me a joke")
- Short focused requests

## Model Selection Logic (Implementation)

The `model_auto_select(task: str) -> tuple[str, str]` method implements:

1. **Explicit flags** — fastest path, highest priority
2. **Task length** — >2000 chars → Sonnet
3. **Keyword patterns** — regex matching for complex reasoning
4. **Security indicators** — auth, token, credential, key → Sonnet
5. **File references** — >3 file paths → Sonnet
6. **Default** — Haiku for everything else

## Logging

Auto-selection decisions are logged with prefix `[AutoSelect]`:

```
[AutoSelect] long task (2500 chars) → Sonnet
[AutoSelect] complex keyword matched → Sonnet
[AutoSelect] simple task, no complex patterns → Haiku
```

Check logs to verify the model selection is working as expected.

## Testing

Unit tests in `tests/test_llm_model_selection.py` verify:
- Empty task handling
- Threshold detection
- Keyword matching
- Default fallback behavior

Run tests:
```bash
pytest tests/test_llm_model_selection.py -v
```

## Backward Compatibility

- `auto_select_model` parameter is **optional** (defaults to `False`)
- Existing code without this parameter continues to work unchanged
- Model set at `LLMClient.__init__()` is used when `auto_select_model=False`

## Deactivating Auto-Selection

If you want to always use a specific model, set it at initialization:

```python
# Always use Haiku
client = LLMClient(model="anthropic/claude-haiku-4-5-20251001")

# Now auto_select_model=True will be ignored if you also pass model= kwarg
result = await client.complete(messages="...", auto_select_model=True)
```

Or disable auto-selection:

```python
# Default: use whatever model was set at init
result = await client.complete(messages="...", auto_select_model=False)
```
