# OpenSpace Operations Runbook

**Version**: Phase 11 (April 2026)  
**Audience**: DevOps, SREs, platform engineers  
**Expected Runtime**: Minutes for quick troubleshooting; hours for deep investigation

---

## Purpose

This runbook explains how to start, verify, monitor, and safely shut down the OpenSpace MCP server. It assumes you understand Linux, HTTP health checks, and graceful shutdown patterns.

---

## Quickstart

### Start the MCP Server

```bash
# Terminal 1: Start OpenSpace
python3 -m openspace.mcp_server

# Expected output:
# INFO — Server initialized, listening on stdio
# INFO — MCP server ready for requests
```

### Verify Health (in parallel terminal)

```bash
# Terminal 2: Check liveness (should always return 200)
curl -s http://localhost:5000/health | jq .

# Response: {"status": "ok"}
# Status: 200 OK
```

### Check Readiness

```bash
# Check if system is ready to serve requests
curl -s http://localhost:5000/ready | jq .

# If ready:
# {"ready": true, "reason": null}
# Status: 200 OK

# If not ready (e.g., still initializing):
# {"ready": false, "reason": "MCP server not ready or shutting down"}
# Status: 503 Service Unavailable
```

### Get Diagnostics

```bash
# View uptime, limiter state, cloud status
curl -s http://localhost:5000/status | jq .

# Response example:
# {
#   "uptime_seconds": 123.45,
#   "openspace_initialized": true,
#   "limiter": {
#     "execute_task_active": 1,
#     "search_skills_active": 0
#   },
#   "cloud_status": "available"
# }
# Status: 200 OK
```

### Graceful Shutdown

```bash
# Kill with SIGTERM (container orchestration will do this)
kill -TERM $PID

# Server will:
# 1. Log "Graceful shutdown initiated"
# 2. Stop accepting new requests (/ready returns 503)
# 3. Wait up to 30s for active tasks to complete
# 4. Log "All active tasks completed" or timeout warning
# 5. Close SkillStore and cleanup resources
# 6. Exit with code 0

# Verify shutdown:
echo $?  # Should print 0
```

---

## Understanding the Probes

### /health (Liveness Probe)

**Purpose**: Tell orchestrator if process is alive  
**Always returns**: 200 OK  
**What it means**: Process is running (no state checks)

**When to use**: Kubernetes `livenessProbe`

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 5000
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 1
```

### /ready (Readiness Probe)

**Purpose**: Tell orchestrator if it's safe to route traffic  
**Returns 200** if: OpenSpace initialized AND not shutting down  
**Returns 503** if: Initializing, shut-down requested, or internal error

**When to use**: Kubernetes `readinessProbe`

```yaml
readinessProbe:
  httpGet:
    path: /ready
    port: 5000
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 1
  failureThreshold: 2
```

**Typical startup timeline**:
- T+0s: /health returns 200, /ready returns 503 (initializing)
- T+2-5s: /health returns 200, /ready returns 200 (ready)

### /status (Diagnostics)

**Purpose**: Understand what the system is doing right now  
**Always returns**: 200 OK with JSON

**Fields**:
| Field | Type | Meaning |
|-------|------|---------|
| `uptime_seconds` | float | Seconds since Flask app started |
| `openspace_initialized` | bool | Whether skill engine is ready |
| `limiter.execute_task_active` | int | Active `execute_task()` calls (max 3) |
| `limiter.search_skills_active` | int | Active `search_skills()` calls (max 5) |
| `cloud_status` | string | Cloud API state: `unknown`, `available`, or `degraded` |

**How to interpret**:
- `openspace_initialized=true` + `cloud_status=available` → Healthy ✅
- `openspace_initialized=true` + `cloud_status=degraded` → Working offline (expected if network down)
- `openspace_initialized=false` → Still initializing or crashed
- Limiter counts growing → System under load (monitor for saturation)

---

## Graceful Shutdown Behavior

### What Happens When You Send SIGTERM

```
T+0ms:   SIGTERM received
         _shutdown_requested = True
         All new requests get /ready → 503
         
T+0-30s: Wait for active task limiter to drain
         Loops every 500ms checking:
         - execute_task_limiter.active_tasks
         - search_skills_limiter.active_tasks
         
T+30s:   If still active tasks: log warning, continue anyway
         (Shutdown does NOT wait forever)
         
T+30+ms: Cleanup resources:
         - Close SkillStore database connection
         - Close stderr file
         
T+30+ms: Exit with code 0
```

### Why This Matters

1. **Load balancers**: Remove instance from pool immediately when /ready returns 503
2. **In-flight requests**: Have up to 30s to complete gracefully
3. **Long-running tasks**: Will be interrupted after 30s (not forever)
4. **Data consistency**: SkillStore closed cleanly (no partial writes)

### Testing Graceful Shutdown

```bash
# Terminal 1: Start server
python3 -m openspace.mcp_server &
PID=$!

# Terminal 2: Verify ready
curl -s http://localhost:5000/ready | jq '.ready'  # Should be true

# Terminal 3: Send SIGTERM and monitor
kill -TERM $PID

# Watch logs for:
# - "Graceful shutdown initiated"
# - "All active tasks completed" OR "timeout reached"
# - No errors about unclosed resources

# Check exit code (should be 0)
wait $PID
echo "Exit code: $?"
```

---

## Monitoring & Alerts

### Critical Alerts (Act Immediately)

| Condition | Action |
|-----------|--------|
| `/health` returns non-200 or timeout | Process crashed; restart container |
| `/ready` returns 503 for >2 min after startup | Initialization hanging; check logs for errors |
| `limiter.execute_task_active ≥ 3` for >5 min | Queue saturation; either reduce load or scale horizontally |
| `cloud_status = "degraded"` persistent | Cloud API failure; check network or API status |

### Warning Alerts (Investigate)

| Condition | Meaning |
|-----------|---------|
| `/status` uptime very high (>7 days) without restart | No updates applied; schedule maintenance window |
| Limiter counts fluctuating but not exceeding capacity | Normal load variation; no action needed |
| `cloud_status` oscillating between `available`/`degraded` | Flaky network or API; consider circuit breaker |

### Info Metrics (Track)

- Uptime between restarts
- Average limiter usage (for capacity planning)
- Cloud status changes (frequency and duration)
- Request ID patterns (for tracing failures)

---

## Troubleshooting

### System Won't Start

**Symptom**: No output or crashes immediately

**Check**:
```bash
# 1. Python version
python3 --version  # Must be 3.10+

# 2. Dependencies
python3 -m pip list | grep -E "litellm|flask|openspace"

# 3. LLM API keys
echo $OPENAI_API_KEY  # Set? If not:
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

# 4. Logs
python3 -m openspace.mcp_server 2>&1 | head -100
```

### /ready Stuck on 503

**Symptom**: After 2+ minutes, /ready still returns 503

**Check**:
```bash
# 1. Is OpenSpace actually initializing?
curl -s http://localhost:5000/status | jq '.openspace_initialized'
# If false: Check logs for init errors

# 2. Is there a blocked network call?
strace -p $PID -e trace=network 2>&1 | head -20
# Look for hanging connect() calls

# 3. Restart manually
kill -9 $PID
sleep 2
python3 -m openspace.mcp_server  # Start fresh
```

### Limiter Saturation

**Symptom**: `execute_task_active` or `search_skills_active` stuck at max

**Check**:
```bash
# 1. How many active tasks?
curl -s http://localhost:5000/status | jq '.limiter'

# 2. What's blocking?
# If execute_task_active = 3:
#   - Check if long-running skills (>30s timeout)
#   - May need to increase timeout or split task
# If search_skills_active = 5:
#   - Cloud search stalled
#   - Check cloud_status in /status

# 3. Force restart if hung
kill -TERM $PID
# Wait 30s for graceful shutdown
sleep 35
# Restart
python3 -m openspace.mcp_server
```

### Cloud Status Degraded

**Symptom**: `/status` shows `cloud_status: "degraded"`

**Meaning**: Cloud API call failed (timeout, network error, etc.)

**Action**:
```bash
# 1. Check network
ping api.openai.com  # Or your cloud provider

# 2. Check API key
echo $OPENAI_API_KEY | wc -c  # Should be ~50+ characters

# 3. Check logs for specific error
# Look for lines like:
# "Cloud search failed: TimeoutError"
# "Cloud search failed: AuthenticationError"

# 4. System is still operational offline
# It will fall back to local skill search
# No action required unless cloud needs to be available
```

### Resource Leak / Memory Growth

**Symptom**: Memory usage growing steadily over hours

**Check**:
```bash
# 1. Monitor memory (in separate terminal)
watch -n 1 'ps aux | grep openspace | grep -v grep | awk "{print \$6}"'
# Should stabilize, not continuously grow

# 2. Check for long-lived connections
netstat -an | grep ESTABLISHED | wc -l

# 3. If leaking:
# a. Check if /status limiter counts are growing
# b. Check logs for connection errors
# c. Likely cause: SkillStore not closing properly
# d. Restart: kill -TERM $PID && sleep 35 && restart
```

---

## Log Interpretation

### Expected Log Lines (Success)

```
INFO — Server initialized, listening on stdio
INFO — OpenSpace initialized successfully
INFO — MCP server ready for requests
INFO — execute_task acquired limiter token
INFO — Cloud search available, found 5 skills
INFO — execute_task released limiter token
```

### Warning/Error Lines (Investigate)

| Line | Meaning | Action |
|------|---------|--------|
| `WARNING — Graceful shutdown timeout reached with X active tasks` | Took >30s to shutdown | Normal if many tasks were active; check if acceptable |
| `ERROR — Cloud search failed` | Cloud API call failed | Check network; system continues with local skills |
| `WARNING — Limiter acquire timeout` | Could not acquire token after waiting | System under heavy load; requests are being rejected |

### Request ID Tracing

Each request has a unique `request_id` (UUID) in logs:

```
INFO request_id=a1b2c3d4 — execute_task: starting
INFO request_id=a1b2c3d4 — Cloud search: available
INFO request_id=a1b2c3d4 — execute_task: completed
```

**To find all logs for one request**:
```bash
grep "a1b2c3d4" openspace.log
```

---

## Known Limitations

### What Is NOT Supported

| Feature | Status |
|---------|--------|
| **Cluster-wide rate limiting** | Per-process only (no sharing between instances) |
| **Automatic cloud API retry** | Passive tracking only; no built-in retry logic |
| **GUI recording on headless** | Requires X11 display; fails gracefully on headless CI |
| **Custom health checks** | No pluggable health check hooks |
| **Metrics export** | No Prometheus `/metrics` endpoint (use /status for now) |

### GUI/Headless Notes

- **Recording functionality** requires X11 display (Linux desktop)
- **18 GUI automation tests** are skipped on headless CI (expected)
- **HTTP probes work fine** on headless (no GUI needed)
- **MCP server itself** is headless-compatible (pure async)

---

## Scaling & Capacity

### Rate Limits (Per Instance)

| Resource | Limit | Action if Exceeded |
|----------|-------|-------------------|
| `execute_task` concurrent | 3 | New requests rejected with rate limit error |
| `search_skills` concurrent | 5 | New requests rejected with rate limit error |
| `execute_task` per minute | 10 | Oldest request dropped from tracking (per-minute sliding window) |

### Scaling Horizontally

1. **Start new instance** with same LLM API key
2. **Load balancer** distributes requests across instances
3. **Each instance** is independent (rate limits are per-process)
4. **No session affinity** required (stateless design)

**Example**: To handle 10 concurrent execute_task calls, deploy 4 instances (3 + 1 spare).

---

## Safe Usage Notes

### DO

✅ Use SIGTERM for shutdown (orchestrator will do this)  
✅ Monitor /status endpoint regularly  
✅ Use request IDs for debugging failures  
✅ Scale horizontally for higher throughput  
✅ Expect cloud failures and plan accordingly  

### DO NOT

❌ Use SIGKILL (force kill) unless SIGTERM hangs >60s  
❌ Assume cloud API is always available  
❌ Rely on logs if not aggregated (local-only logs are lost on restart)  
❌ Make direct SkillStore database edits (close app first)  
❌ Run without monitoring /ready probe actively  

---

## Appendix: Docker Deployment Example

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . .

RUN pip install -e .

# Health checks (Docker built-in)
HEALTHCHECK --interval=10s --timeout=1s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

CMD ["python3", "-m", "openspace.mcp_server"]
```

```bash
# Run with health checks
docker run \
  -e OPENAI_API_KEY=sk-... \
  -p 5000:5000 \
  openspace:v0.2.0
```

---

## Support & Escalation

| Issue | First Response | If Still Failing |
|-------|---|---|
| Startup failure | Check logs, verify API keys | Restart container |
| Hung readiness | Check limiter state, force graceful shutdown | Contact platform team |
| Memory leak | Monitor /status, restart daily | File incident ticket |
| Persistent cloud failure | Check network, DNS resolution | Check cloud provider status page |

---

**Last Updated**: 2026-04-10  
**Maintained by**: OpenSpace Platform Team
