# Agent Platform - Temporal Worker Production Deployment Guide

This guide details the production deployment, operations, and scaling architecture for Temporal Workers executing LangGraph workflows in the Agent Platform.

---

## 1. Architecture Overview

* **Decoupled Execution:** Temporal Workers run as dedicated long-running systemd processes independent of FastAPI.
* **Process-Level Concurrency:** Multiple Worker instances on a server independently poll the same Temporal task queue (`agent-platform-queue`).
* **Graceful Lifecycle Management:** On `SIGTERM`, workers invoke `worker.shutdown()`, ceasing task polling and permitting in-flight activities up to 30 seconds to conclude before process exit.
* **Storage Isolation:** Workers and FastAPI share a validated local SQLite database path (`AGENT_PLATFORM_DB_PATH`) protected by WAL mode and bounded exponential backoff retries on transient file locks.

---

## 2. Server Installation & Setup (Linux)

### Step 1: Create Dedicated System User
```bash
sudo useradd --system --shell /usr/sbin/nologin --comment "Agent Platform Service User" agentplatform
```

### Step 2: Prepare Application & Storage Directories
```bash
# Application code and virtual environment directory
sudo mkdir -p /opt/agent_platform
sudo chown -R agentplatform:agentplatform /opt/agent_platform

# Secure configuration directory
sudo mkdir -p /etc/agent-platform
sudo chown -R root:agentplatform /etc/agent-platform
sudo chmod 750 /etc/agent-platform

# State and SQLite database directory
sudo mkdir -p /var/lib/agent-platform
sudo chown -R agentplatform:agentplatform /var/lib/agent-platform
sudo chmod 770 /var/lib/agent-platform
```

### Step 3: Configure Environment File
Copy the example environment configuration into `/etc/agent-platform/worker.env`:
```bash
sudo cp deployment/systemd/worker.env.example /etc/agent-platform/worker.env
sudo chown root:agentplatform /etc/agent-platform/worker.env
sudo chmod 640 /etc/agent-platform/worker.env
```

Ensure `AGENT_PLATFORM_DB_PATH` is set to `/var/lib/agent-platform/agent_platform.db` and your `TEMPORAL_TARGET_HOST` points to your Temporal cluster.

### Step 4: Install Systemd Service Files
```bash
sudo cp deployment/systemd/agent-platform-worker@.service /etc/systemd/system/
sudo cp deployment/systemd/agent-platform-workers.target /etc/systemd/system/
sudo systemctl daemon-reload
```

---

## 3. Operations Runbook

### A. Start Two Workers
Enable and start the workers target (which manages instances 1 and 2 by default):
```bash
sudo systemctl enable --now agent-platform-workers.target
```
Alternatively, enable and start individual instances explicitly:
```bash
sudo systemctl enable --now agent-platform-worker@1
sudo systemctl enable --now agent-platform-worker@2
```

### B. Stop Workers Gracefully
Stopping via systemd sends `SIGTERM`, giving workers up to 30 seconds to drain running activities before exit:
```bash
# Stop all running workers
sudo systemctl stop agent-platform-workers.target

# Stop a single worker instance
sudo systemctl stop agent-platform-worker@1
```

### C. Restart Workers
```bash
# Restart all workers gracefully (drains in-flight tasks then restarts)
sudo systemctl restart agent-platform-workers.target

# Restart only instance 2
sudo systemctl restart agent-platform-worker@2
```

### D. View Individual Worker Logs
```bash
sudo journalctl -u agent-platform-worker@1 -f
```

### E. View Logs Across All Worker Instances
```bash
sudo journalctl -u 'agent-platform-worker@*' -f
```
Log output includes structured identity metadata identifying the exact instance, host, and PID:
```text
2026-10-31 10:15:00 [INFO] [worker-1@worker-host-01:4120] app.temporal.worker: Starting Temporal Worker on queue 'agent-platform-queue'...
2026-10-31 10:15:00 [INFO] [worker-2@worker-host-01:4121] app.temporal.worker: Starting Temporal Worker on queue 'agent-platform-queue'...
```

### F. Scale From Two to Four Instances
To increase throughput without any code or service file modifications:
```bash
sudo systemctl enable --now agent-platform-worker@3
sudo systemctl enable --now agent-platform-worker@4
```
To scale back down:
```bash
sudo systemctl stop agent-platform-worker@4
sudo systemctl disable agent-platform-worker@4
```

### G. Check Worker Health
```bash
# Check systemd service status
systemctl status agent-platform-workers.target
systemctl status 'agent-platform-worker@*'

# Check if workers are actively polling Temporal Server
temporal task-queue describe --task-queue agent-platform-queue --task-queue-type workflow
```

---

## 4. Local Development (Windows / macOS / Linux)

For local development, continue using direct command-line execution:
```powershell
# Windows PowerShell
$env:TEMPORAL_TARGET_HOST = "localhost:7233"
$env:AGENT_PLATFORM_DB_PATH = "agent_platform.db"
.\.venv\Scripts\python.exe -m app.temporal.worker
```
The worker automatically identifies the operating system and runs cross-platform graceful handlers (e.g., `KeyboardInterrupt` / `SIGINT`).

---

## 5. Production Limitations & Architectural Constraints

1. **Process-Level vs. Host-Level Resilience:**
   * Running multiple worker processes on a single server provides **process-level resilience** (if one process crashes or encounters an OOM error, others continue polling and systemd automatically restarts the failed process).
   * It does **not** provide **host-level high availability**. A physical host failure, network partition, or OS freeze takes down all workers on that host.
2. **Multi-Host High Availability Requires Client-Server Database:**
   * True host-level high availability requires deploying workers across multiple independent physical hosts or cloud VMs.
   * **SQLite cannot be shared across multiple hosts.** Attempting to share SQLite files over network filesystems (NFS, SMB, EFS) results in lock manager deadlocks and permanent database corruption under WAL mode.
   * Before deploying workers to multiple separate servers, migrate `ExecutionRepository` from SQLite to a shared client-server database such as **PostgreSQL**.
3. **Activity Idempotency and Side Effect Retries:**
   * Temporal automatically retries activities upon transient failures.
   * Tool and agent executions with external side effects (e.g., sending emails, database mutations) must be idempotent or accept at-least-once execution semantics.
4. **Workflow Definition Versioning:**
   * In-flight Temporal workflows replay historical events using the registered workflow definition version.
   * When deploying new agent workflow topologies, preserve existing version definitions (`v1.0.0`, `v1.0.1`) so in-flight executions can complete without non-deterministic replay mismatches.

