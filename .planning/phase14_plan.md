# Phase 14: Stability & Load Testing — Implementation Plan

**Scope**: Realistic, controlled load testing (5-20 parallel requests, short soak)  
**Duration**: ~2-3 hours implementation  
**Goal**: Verify limiter correctness, graceful degradation, state consistency under load

---

## 1. Load Harness Design

### Simple Async Load Generator
- **No external tools** (no locust, k6, etc.)
- **Pure pytest + asyncio**
- **Three load profiles**:
  1. **Baseline** (5 parallel): Baseline metrics
  2. **Medium** (10 parallel): Limiter pressure
  3. **Peak** (20 parallel): Edge of capacity

### Execution Pattern
```
For each profile:
  Create N concurrent tasks
  Wait for all to complete (with timeout)
  Record results
  Measure elapsed time
  Check final state consistency
```

### Duration
- **Not a 72-hour soak** — too impractical
- **10-20 second bursts** per scenario
- **Repeat 3-5 times** (detect state leaks across runs)

---

## 2. Metrics & State Observation

### Collected Metrics (Minimal)
| Metric | How | Why |
|--------|-----|-----|
| **Limiter state** | Read from mcp_server directly | Verify acquire/release symmetry |
| **Success/fail rates** | Count returned results | Track error patterns |
| **Response times** | Record per-request duration | Detect timeouts, slowness |
| **Memory baseline** | `psutil.Process().memory_info()` | Rough leak detection |
| **Final state** | Check limiter counts post-test | Verify no hanging tokens |

### No Heavy Instrumentation
- No Prometheus scraping
- No continuous profiling
- Just simple counters and timing

---

## 3. Failure Scenarios

### Scenario 1: Cloud API Timeout During Search (Expected: Graceful Degradation)
- Mock `search_skills()` to raise `TimeoutError`
- Expect: Requests continue, cloud_status = "degraded"
- Verify: Limiter still works, no token leak

### Scenario 2: Subprocess Failure in Local Server (Expected: Isolation)
- Mock platform adapter to fail on subprocess call
- Expect: Error logged, request fails, limiter released
- Verify: Other requests unaffected, no cascade failure

### Scenario 3: Rate Limit Hits (Expected: Rejection)
- Submit >3 execute_task requests concurrently
- Expect: 3 succeed, remainder get "rate_limited" error
- Verify: Limiter correctly enforces limit

### Scenario 4: Mixed Success/Failure (Expected: State Consistency)
- Mix working and failing tasks in single batch
- Expect: Some pass, some fail, limiter balances
- Verify: Active task counts correct, no double-release

### Scenario 5: Rapid Restart Cycle (Expected: Clean Recovery)
- Start load → stop mid-load → restart → verify state
- Expect: Second run starts with clean limiter state
- Verify: No lingering tokens, no crashes

---

## 4. Test Implementation Structure

### File: `test_phase14_stability_load.py`

**Test Classes**:
1. `TestBaselineLoad` (5 parallel)
   - Normal execution path
   - Baseline metrics for comparison
   - Verify no obvious leaks

2. `TestMediumLoad` (10 parallel)
   - Limiter under pressure
   - Mixed success/failure
   - Response time degradation acceptable?

3. `TestPeakLoad` (20 parallel)
   - Edge capacity (3 execute_task → queue forms)
   - Verify rate limit enforcement
   - No cascade failures

4. `TestFailureScenarios`
   - Cloud timeout isolation
   - Subprocess failure handling
   - Rate limit boundary conditions

5. `TestStateConsistency`
   - Limiter acquire/release balance
   - Memory baseline (no huge leaks)
   - Post-load state clean

### Test Helpers
```python
async def load_execute_task(count: int, duration_sec: int, failure_rate: float):
    """Generate `count` concurrent execute_task calls.
    
    Returns: List of (success, duration_ms, error_msg)
    """

async def load_search_skills(count: int, duration_sec: int):
    """Generate `count` concurrent search_skills calls."""

def assert_limiter_balanced(initial_state, final_state):
    """Verify no token leaks: initial.active_tasks == final.active_tasks == 0"""

def assert_memory_reasonable(before_mb, after_mb):
    """Verify no huge memory jumps (allow ±10MB for Python overhead)"""
```

---

## 5. Success Criteria

✅ **Baseline Load** (5 parallel)
- All requests succeed
- Response times < 500ms
- Limiter state consistent before/after
- Memory delta < 5MB

✅ **Medium Load** (10 parallel)
- >80% success rate
- Limiter saturates search_skills (5 active)
- No cascade failures (one failure doesn't break others)
- State consistent after completion

✅ **Peak Load** (20 parallel)
- execute_task rate limited (3 active, rest queued)
- Proper error messages for rejected requests
- No deadlocks or hangs (all complete within 30s)
- Limiter tokens released correctly

✅ **Failure Scenarios**
- Cloud timeout: Other requests continue
- Subprocess fail: Error isolated, limiter releases
- Rate limit: Correct rejection count
- Mixed success/fail: Limiter balanced

✅ **Rapid Restart**
- Second run starts with clean state
- No hanging tokens from first run

---

## 6. NOT in Scope

❌ Chaos engineering (no random failures injected systematically)  
❌ 1000+ req/min (unrealistic; 5-20 is controlled)  
❌ Kubernetes integration testing  
❌ Detailed memory profiling (just baseline checks)  
❌ Distributed tracing during load  
❌ Custom metrics collection framework  

---

## 7. Expected Output

After implementation:
1. `test_phase14_stability_load.py` — ~500 lines, 15-20 test cases
2. Test metrics in pytest output (pass/fail counts, timing)
3. Short summary in test docstrings (what each test validates)
4. No new dependencies beyond pytest/asyncio (already have)

---

## 8. Timeline

- **Write load harness**: 30 min
- **Implement baseline load tests**: 30 min
- **Implement failure scenarios**: 45 min
- **Debug & verify**: 30 min
- **Total**: ~2.5 hours

---

**Ready to implement?** [Y/n]
