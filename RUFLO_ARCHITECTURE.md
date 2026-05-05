# Ruflo Architecture Cut — Phase 2 Complete

## Decision Summary

**Architecture Decision (Phase 14.5):**
- OpenSpace = core runtime (execution, state, health, readiness)
- Ruflo = thin orchestration layer (CLI, workflow coordination)
- **Boundary**: Ruflo calls OpenSpace via HTTP only. No direct MCP or internal state access.

---

## What Changed

### BEFORE (Overlapping)
```
Ruflo (MCP server)
├─ Direct MCP access
├─ Task execution / state management
├─ HTTP API surface (port conflict risk)
└─ Skill execution

OpenSpace (HTTP server)
├─ Task execution
├─ State management
├─ HTTP API
└─ MCP integration
```

**Problem:** Two systems own execution and state. Debugging confusion. Limiter bypass risk.

---

### AFTER (Clean Boundary — Unified OpenSpaceClient)

```
User / CLI
    ↓
Ruflo (openspace.ruflo_wrapper)
  - Thin CLI orchestration layer
  - NO direct execution logic
  - NO state management
  - NO MCP access
    ↓
OpenSpaceClient (unified facade)
  ├─ client.runtime() → RuntimeClient
  │   ├─ .health()                 → GET /health (liveness)
  │   ├─ .ready()                  → GET /ready (readiness)
  │   ├─ .status()                 → GET /status (diagnostics)
  │   ├─ .execute(cmd)             → POST /execute {type: shell} → stdout
  │   └─ .task(task, input)        → POST /execute {type: task} → JSON
  │   ↓
  │   LocalServer (localhost:5000)
  │
  └─ client.control() → ControlClient
      ├─ .list_skills()            → GET /api/v1/skills
      ├─ .list_workflows()         → GET /api/v1/workflows
      ├─ .route_task(task)         → POST /api/v1/route-task
      ├─ .overview()               → GET /api/v1/overview
      └─ .costs()                  → GET /api/v1/costs
      ↓
      DashboardServer (localhost:5000 or :8000)
    ↓
MCP / LLM / Python Execution / Storage
```

**Result:** Single execution source. Clear responsibility. No overlap.

---

## Ruflo: What It NOW Does

### Python Module: `openspace.ruflo_wrapper`

**Location:** `/home/claude/OpenSpace/openspace/ruflo_wrapper.py`

Uses unified `OpenSpaceClient` with `.runtime()` and `.control()` accessors.

**Commands:**

```bash
# Runtime operations (via client.runtime())
python3 -m openspace.ruflo_wrapper health                                    # Check health
python3 -m openspace.ruflo_wrapper ready                                     # Check readiness
python3 -m openspace.ruflo_wrapper status                                    # Show system status
python3 -m openspace.ruflo_wrapper execute "ls -la /tmp"                     # Execute shell command
python3 -m openspace.ruflo_wrapper task list_directory --input '{"path": "/tmp"}'  # Execute structured task

# Control operations (via client.control())
python3 -m openspace.ruflo_wrapper skills --limit 20                         # List skills
python3 -m openspace.ruflo_wrapper workflows                                 # List workflows
python3 -m openspace.ruflo_wrapper route-task "task description"             # Route task

# Custom server URLs
python3 -m openspace.ruflo_wrapper \
  --runtime-url http://localhost:5000 \
  --control-url http://localhost:8000 \
  --token YOUR_API_TOKEN \
  status
```

**Internal Architecture:**

```python
class RufloWrapper:
    def __init__(self, runtime_url=None, control_url=None, api_token=None):
        self.client = create_client(
            runtime_url=runtime_url,
            control_url=control_url,
            api_token=api_token
        )
    
    def execute(self, command: str, timeout: int = 120) -> int:
        result = self.client.runtime().execute(command=command, timeout=timeout)
        # Handle result...
    
    def skills(self, limit: int = 10) -> int:
        result = self.client.control().list_skills(limit=limit)
        # Handle result...
```

**What It Does:**
- CLI parsing and display formatting
- Delegates to `client.runtime()` for: health, ready, status, execute, task
- Delegates to `client.control()` for: skills, workflows, route-task, costs
- User-facing interface
- Command routing to OpenSpace (via HTTP)

**Runtime Operations:**
- `execute()` — Shell command execution → POST /execute {type: shell} → stdout/stderr
- `task()` — Structured task execution → POST /execute {type: task} → JSON result
- `health()` / `ready()` / `status()` — Health probes

**What It Does NOT Do:**
- ❌ Direct task execution (delegated to client.runtime().task())
- ❌ Direct shell execution (delegated to client.runtime().execute())
- ❌ Direct skill management (delegated to client.control().list_skills())
- ❌ Direct MCP invocation
- ❌ State mutations
- ❌ Limiter enforcement (OpenSpace owns this)

---

## HTTP Client: `openspace.http_client`

**Location:** `/home/claude/OpenSpace/openspace/http_client.py`

**Unified Client Pattern with Facade:**

```python
from openspace.http_client import create_client

# Single unified client
client = create_client(
    runtime_url="http://localhost:5000",
    control_url="http://localhost:8000",
    api_token="your-token"
)

# Access runtime operations
client.runtime().health()                                    # GET /health
client.runtime().ready()                                     # GET /ready
client.runtime().status()                                    # GET /status
client.runtime().execute("ls -la /tmp")                      # POST /execute (type: shell)
client.runtime().task("list_directory", {"path": "/tmp"})    # POST /execute (type: task)

# Access control operations
client.control().list_skills()                               # GET /api/v1/skills
client.control().list_workflows()                            # GET /api/v1/workflows
client.control().route_task("task description")             # POST /api/v1/route-task
client.control().costs()                                     # GET /api/v1/costs
```

### RuntimeClient (via client.runtime())

**Communicates with:** local_server (no authentication)

**Methods:**

| Method | Endpoint | Type | Purpose |
|--------|----------|------|---------|
| `health()` | GET /health | - | Liveness check (always 200) |
| `ready()` | GET /ready | - | Readiness probe (200 or 503) |
| `status()` | GET /status | - | Diagnostics & uptime |
| `execute(cmd, timeout)` | POST /execute | `shell` | Shell command execution (stdout/stderr) |
| `task(task, input, timeout)` | POST /execute | `task` | Structured task execution (JSON result) |

### ControlClient (via client.control())

**Communicates with:** dashboard_server (with authentication)

**Methods:**

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `list_skills(...)` | GET /api/v1/skills | List skills |
| `get_skill(id)` | GET /api/v1/skills/{id} | Skill details |
| `skill_stats()` | GET /api/v1/skills/stats | Aggregate stats |
| `skill_lineage(id)` | GET /api/v1/skills/{id}/lineage | Lineage graph |
| `skill_source(id)` | GET /api/v1/skills/{id}/source | Source code |
| `list_workflows()` | GET /api/v1/workflows | List workflows |
| `get_workflow(id)` | GET /api/v1/workflows/{id} | Workflow details |
| `route_task(task)` | POST /api/v1/route-task | Route for execution |
| `overview()` | GET /api/v1/overview | System overview |
| `costs()` | GET /api/v1/costs | Cost tracking |

### OpenSpaceClient (Unified Facade)

```python
class OpenSpaceClient:
    def runtime(self) -> RuntimeClient
    def control(self) -> ControlClient
```

**Configuration:**
- Runtime URL env: `OPENSPACE_RUNTIME_URL` or `OPENSPACE_LOCAL_URL` (default: `http://localhost:5000`)
- Control URL env: `OPENSPACE_CONTROL_URL` or `OPENSPACE_DASHBOARD_URL` (default: `http://localhost:5000`)
- Token env: `OPENSPACE_API_TOKEN`

---

## What Was Removed

### Removed from Ruflo

**Old npm package:** `ruflo` (CLI tool)
- ❌ Standalone MCP server (`ruflo mcp start`)
- ❌ Direct MCP tool access
- ❌ Task execution logic
- ❌ Internal HTTP API

**Why:** It duplicated OpenSpace responsibilities and created the overlap.

### NOT Removed

✅ Ruflo's workflow orchestration logic (now in Python)
✅ Ruflo's command parsing (now in Python CLI wrapper)
✅ Ruflo's scheduling/workflow features (still available via HTTP calls)

---

## Testing the Boundary

### 1. Verify HTTP Client Works

```bash
cd /home/claude/OpenSpace
python3 -c "
from openspace.http_client import create_client
client = create_client()
health = client.health()
print(f'OpenSpace is alive: {health.get(\"status\") == \"ok\"}')"
```

**Expected:** ✓ If OpenSpace server is running

### 2. Verify Ruflo CLI Works

```bash
python3 -m openspace.ruflo_wrapper status
```

**Expected:** System status displayed

### 3. Verify No Direct MCP Access

```bash
# Should fail: no mcp__ruflo__* tools in Claude Code
# Should succeed: only mcp__openspace__* tools available
```

---

## Deployment: Single vs. Dual Server

### Option A: Single Server (Both on same process/port)

```bash
# Start a single OpenSpace server that handles both local and dashboard endpoints
# (this would require merging local_server and dashboard_server into one Flask app)

# Terminal 1: OpenSpace (both servers)
cd /home/claude/OpenSpace
python3 -m openspace --mode combined

# Terminal 2: Use Ruflo (auto-detects single server)
export OPENSPACE_LOCAL_URL=http://localhost:5000
export OPENSPACE_DASHBOARD_URL=http://localhost:5000  # Same server
export OPENSPACE_API_TOKEN=your-token-here
python3 -m openspace.ruflo_wrapper status
```

### Option B: Dual Server (Separate processes)

```bash
# Terminal 1: Local server (execution, health, status, files)
cd /home/claude/OpenSpace
python3 -m openspace.local_server.main --port 5000

# Terminal 2: Dashboard server (skills, workflows, routes, costs)
cd /home/claude/OpenSpace
python3 -m openspace.dashboard_server --port 8000

# Terminal 3: Use Ruflo (explicit routing)
export OPENSPACE_LOCAL_URL=http://localhost:5000
export OPENSPACE_DASHBOARD_URL=http://localhost:8000
export OPENSPACE_API_TOKEN=your-token-here
python3 -m openspace.ruflo_wrapper status
```

### Current State

Both local_server/main.py and dashboard_server.py create separate Flask apps.
They can be:
1. **Same process** — merged into one Flask app
2. **Different ports** — separate Flask apps on different ports
3. **Separate processes** — different Python processes

Ruflo's HTTP client supports all three via the dual-URL configuration.

### Port Assignment (Default)

- Local Server: `5000` (execution, health, status)
- Dashboard Server: `5000` (same, or separate port like `8000`)
- Ruflo: No port (CLI only)

### Authentication Flow

```
User CLI
  ↓
Ruflo CLI
  (reads env: OPENSPACE_API_TOKEN)
  ↓ Splits into two request flows:
  ├─ Local Server Request (no auth header)
  │   GET /health
  │   → 200 always (liveness)
  │
  └─ Dashboard Server Request (with auth)
      GET /api/v1/skills
      (Header: Authorization: Bearer $TOKEN)
      → 200 if token valid, 401 if not
  ↓
OpenSpace (validates token for /api/v1/* only)
  ↓
Response (local or dashboard data)
```

---

## Next Steps (Phase 15+)

1. **Add /ready and /status endpoints** to OpenSpace (if not present)
   - Follows Kubernetes conventions
   - Enables orchestration health checks

2. **Prometheus metrics** on OpenSpace
   - Instrument /health, /ready, /status
   - Track request latency, skill usage, costs

3. **Workflow scheduling** in Ruflo CLI
   - Cron-style task submission via OpenSpace
   - No internal scheduler (OpenSpace owns scheduling)

---

## Architecture Validation Checklist

- ✅ Ruflo has NO direct MCP access
- ✅ Ruflo has NO task execution logic
- ✅ Ruflo has NO state mutations
- ✅ Ruflo calls OpenSpace via HTTP only
- ✅ OpenSpace is single execution source
- ✅ OpenSpace owns limiter, health, state
- ✅ Zero overlap between systems
- ✅ Clear debugging boundary (HTTP logging)

---

## Files Changed (Phase 2)

**New Files:**
- `openspace/http_client.py` — RuntimeClient + ControlClient (~340 lines)
  - `BaseHTTPClient` — Common HTTP functionality
  - `RuntimeClient` — Execute, health, ready, status (local_server)
  - `ControlClient` — Skills, workflows, routing, costs (dashboard_server)
  - Factory functions: `create_runtime_client()`, `create_control_client()`, `create_runtime_and_control()`

- `openspace/ruflo_wrapper.py` — CLI wrapper with client delegation (~340 lines)
  - Uses `RuntimeClient` for execution/health operations
  - Uses `ControlClient` for skills/workflows operations
  - Single `RufloWrapper` class unifies the interface

- `RUFLO_ARCHITECTURE.md` — This document

**Modified:**
- None (no changes to existing OpenSpace code)

**Removed:**
- npm package `ruflo` (external MCP server, deactivated)

**Unchanged:**
- `openspace/dashboard_server.py` (API endpoints intact)
- `openspace/local_server/main.py` (server intact)
- All other OpenSpace modules

---

## Deployment Readiness Checklist

- ✓ Ruflo has NO direct MCP access
- ✓ Ruflo has NO execution logic (delegates to RuntimeClient)
- ✓ Ruflo has NO state mutations
- ✓ Ruflo calls OpenSpace via HTTP only
- ✓ RuntimeClient handles: /health, /ready, /status, /execute
- ✓ ControlClient handles: /api/v1/skills, /api/v1/workflows, /api/v1/route-task, /api/v1/costs
- ✓ Auth handled correctly (RuntimeClient: none, ControlClient: Bearer token)
- ✓ Zero overlap between clients
- ✓ Clear client separation (execution vs. control plane)

---

**Boundary:** CLEAN. Ruflo is a thin CLI layer using:
- **RuntimeClient**: Command execution & health probes
- **ControlClient**: Skill & workflow management
