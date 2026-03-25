# Daemon Process

The summon-claude daemon is a long-running background process that owns the Slack connection and all Claude sessions. It starts automatically on the first `summon start` and stays alive until all sessions end or it is shut down explicitly.

## Daemonization

`start_daemon()` forks a child process and calls `os.setsid()` to detach from the parent's terminal session, then uses `python-daemon.DaemonContext` to close inherited file descriptors. The parent polls for the Unix socket file (up to 10 seconds) and returns once the daemon is ready.

```
summon start
    │
    ├─ fork()
    │      │
    │      └─ child: os.setsid()
    │                DaemonContext (close fds)
    │                run_daemon()
    │                    │
    │                    └─ asyncio.run(daemon_main())
    │
    └─ parent: poll daemon.sock → return when socket appears
```

`DaemonContext(detach_process=False)` is used because the `fork()` + `setsid()` have already handled detachment. `DaemonContext` in this mode only closes inherited file descriptors.

## PID File and Lock

`run_daemon()` acquires a file lock on `daemon.lock` using `fcntl.flock(LOCK_EX | LOCK_NB)` before writing `daemon.pid`. If the lock is already held, `DaemonAlreadyRunningError` is raised immediately without forking. The lock is held by the kernel for the lifetime of the file descriptor — it is released automatically when the daemon exits, eliminating stale-lock races.

File locations (XDG-aware data directory):

```
$XDG_DATA_HOME/summon/
  daemon.pid      # PID of the running daemon
  daemon.lock     # fcntl advisory lock
  daemon.sock     # Unix socket (mode 600)
  registry.db     # SQLite session registry
  logs/
    daemon.log    # Rotating file log (5 MB × 2 backups)
```

The socket is restricted to mode `0600` (owner-only) so other users on the same machine cannot connect.

## IPC Protocol

The CLI communicates with the daemon through a Unix domain socket using a simple length-prefix framing protocol:

```
┌──────────────┬──────────────────────────────────────┐
│  4 bytes     │  N bytes                             │
│  (big-endian │  JSON payload                        │
│   uint32)    │                                      │
└──────────────┴──────────────────────────────────────┘
```

Maximum message size is 64 KiB (`MAX_MESSAGE_SIZE = 65_536`). Each message has a 30-second receive timeout. `send_msg()` and `recv_msg()` in `daemon.py` implement this framing.

### Control Commands

`SessionManager.handle_client()` reads commands from each connected CLI process. The `_dispatch_control()` method handles:

| Command | Description |
|---------|-------------|
| `create_session` | Start a new session with the given options |
| `create_session_with_spawn_token` | Pre-authenticated session creation (spawn flow) |
| `stop_session` | Stop a specific session by ID |
| `stop_all_sessions` | Stop all running sessions |
| `authenticate_session` | Complete auth after `/summon` verification |
| `status` | Return daemon status (uptime, session count) |
| `list_sessions` | Return all active session records |
| `project_up` | Start all suspended sessions for a project |
| `project_down` | Stop all sessions for a project |
| `resume_channel` | Resume a session in an existing channel |

## Health Monitoring: Three Layers

The daemon uses three independent watchdog layers, each handling increasingly severe failure scenarios.

### Layer 1: Socket Health Monitor (BoltRouter)

`_HealthMonitor` polls the Slack Socket Mode client every 10 seconds by calling `client.is_connected()`. If the socket is unhealthy:

- Calls `BoltRouter.reconnect()`: closes the old socket, creates a fresh `AsyncApp` + handler, re-registers all Bolt handlers, and reconnects.
- Up to 10 reconnection attempts (`_MAX_RECONNECT_ATTEMPTS`). The failure counter resets after each successful reconnect.
- On exhaustion: posts a disconnect notice to all active session channels, then calls `shutdown_callback` to signal the daemon event to shut down.

Reconnection is stateless — existing sessions continue running uninterrupted. Only the Slack WebSocket layer is replaced.

### Layer 2: Event Loop Watchdog (asyncio)

`_watchdog_loop()` runs as an asyncio task, waking every 15 seconds (`_WATCHDOG_CHECK_INTERVAL_S`). It measures how much wall time elapsed since its last wake. If the event loop was blocked, the sleep returns late and `elapsed > _WATCHDOG_THRESHOLD_S` (90 seconds). On threshold breach, it logs a critical message and sets the shutdown event.

This guards against blocking calls (a buggy SDK operation that never returns) that would freeze all concurrent sessions.

### Layer 3: SIGALRM OS Watchdog (last resort)

`_start_sigalrm_watchdog()` sets a 120-second SIGALRM (`_SIGALRM_TIMEOUT_S`). The Layer 2 watchdog rearms it on every successful check, so as long as the event loop is alive the alarm never fires. If both Layer 2 and the event loop are completely frozen, SIGALRM fires and the handler calls `os._exit(2)` — guaranteed termination even if Python's signal handling is broken.

No-op on Windows (SIGALRM unavailable).

```
Layer 3: SIGALRM (120s) ──────────────────────────────→ os._exit(2)
                  │ rearmed every 15s by Layer 2
Layer 2: asyncio watchdog (90s stall threshold) ──────→ shutdown_event.set()
                  │ reconnects on socket drop
Layer 1: socket health check (10s interval, 10 attempts) → reconnect() or shutdown
```

## Graceful Shutdown

Shutdown is triggered by `SIGTERM`, `SIGINT`, or any watchdog layer setting `session_manager.shutdown_event`. The three-phase shutdown sequence:

1. **Stop accepting**: Close the Unix socket control server (5-second timeout).
2. **Drain sessions**: `session_manager.shutdown()` signals all sessions to stop and waits up to 30 seconds (`_SHUTDOWN_WAIT_TIMEOUT`). Sessions that do not exit within this window are cancelled.
3. **Stop Bolt**: `bolt_router.stop()` closes the Slack Socket Mode connection.

After shutdown completes, the daemon removes `daemon.pid` and `daemon.sock`.

Sending a second `SIGTERM` or `SIGINT` during shutdown forces immediate exit (the signal handler calls `shutdown_event.set()` again, which is a no-op since it is already set — but the asyncio runtime responds to repeated signals by raising `KeyboardInterrupt` which exits the loop).

## Logging

The daemon configures non-blocking file logging using `QueueHandler` + `QueueListener`:

- **QueueHandler** is attached to the root logger. Log records are enqueued instantly (no file I/O on the event loop).
- **QueueListener** writes to a `RotatingFileHandler` in a background thread (5 MB file, 2 backups).
- `SessionIdFilter` is attached to the `QueueHandler` (not the file handler) so it runs in the asyncio task context where the `session_id` contextvar is available.

Log location: `<data-dir>/logs/daemon.log`

Use `summon session logs` to view logs from the CLI.
