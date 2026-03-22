# Database

summon-claude uses a single SQLite database (`registry.db`) as the session registry. It is visible to both the daemon process and the CLI, providing cross-process session state without a separate database server.

## SQLite Configuration

The registry opens with these pragmas on every connection (`_connect()` in `sessions/registry.py`):

```sql
PRAGMA journal_mode=WAL;          -- WAL for concurrent daemon + CLI access
PRAGMA busy_timeout=5000;         -- wait up to 5s on locks before failing
PRAGMA synchronous=NORMAL;        -- durable but faster than FULL
PRAGMA journal_size_limit=67108864; -- cap WAL file at 64 MB
PRAGMA foreign_keys=ON;           -- enforce FK constraints (required for CASCADE)
```

WAL (Write-Ahead Logging) mode allows concurrent readers even while a write transaction is in progress. The daemon and CLI can both read session state without blocking each other.

!!! warning "PRAGMA foreign_keys and transactions"
    `PRAGMA foreign_keys` cannot be changed inside an open transaction — SQLite silently ignores it. This pragma is set before any `BEGIN` in `_connect()`. Migrations that need to temporarily violate FK constraints must run before this pragma or use a separate connection.

## Database File Location

```
$XDG_DATA_HOME/summon/registry.db   # if XDG_DATA_HOME is set
~/.local/share/summon/registry.db   # default on most systems
~/.summon/registry.db               # fallback / legacy location
```

Use `summon config path` or `summon db status` to see the active path. The database file is restricted to mode `0600` (owner-only) on creation.

## Schema

Current schema version: **12** (`CURRENT_SCHEMA_VERSION` in `sessions/migrations.py`)

### sessions

The primary session tracking table.

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    status TEXT NOT NULL,           -- pending_auth, active, completed, errored, suspended
    session_name TEXT,
    cwd TEXT NOT NULL,
    slack_channel_id TEXT,
    slack_channel_name TEXT,
    model TEXT,
    claude_session_id TEXT,
    started_at TEXT NOT NULL,
    authenticated_at TEXT,
    ended_at TEXT,
    last_activity_at TEXT,
    total_cost_usd REAL DEFAULT 0.0,
    total_turns INTEGER DEFAULT 0,
    error_message TEXT,
    parent_session_id TEXT,         -- set for child sessions (spawn flow)
    authenticated_user_id TEXT,     -- Slack user ID that authenticated
    effort TEXT,                    -- effort level (low, medium, high, max)
    project_id TEXT,                -- FK to projects
    context_pct REAL                -- last-known context window usage
)
```

Partial unique index prevents name collisions among active sessions:
```sql
CREATE UNIQUE INDEX idx_active_session_name
ON sessions (session_name)
WHERE session_name IS NOT NULL AND status IN ('pending_auth', 'active')
```

### channels

Normalized channel data (one row per Slack channel, independent of session lifecycle).

```sql
CREATE TABLE channels (
    channel_id TEXT PRIMARY KEY,
    channel_name TEXT NOT NULL,
    claude_session_id TEXT,
    canvas_id TEXT,
    canvas_markdown TEXT,
    cwd TEXT NOT NULL,
    authenticated_user_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

### pending_auth_tokens

Short-code tokens for the `/summon <code>` authentication flow.

```sql
CREATE TABLE pending_auth_tokens (
    short_code TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0
)
```

### spawn_tokens

Capability tokens for pre-authenticated programmatic session creation.

```sql
CREATE TABLE spawn_tokens (
    token TEXT PRIMARY KEY,
    parent_session_id TEXT,
    parent_channel_id TEXT,
    target_user_id TEXT NOT NULL,
    cwd TEXT NOT NULL,
    spawn_source TEXT NOT NULL DEFAULT 'session',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
)
```

### projects

Project configuration (PM agent multi-session groups).

```sql
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    directory TEXT NOT NULL,
    channel_prefix TEXT NOT NULL,   -- unique index
    pm_channel_id TEXT,
    workflow_instructions TEXT NOT NULL DEFAULT '',
    hooks TEXT DEFAULT NULL,        -- JSON lifecycle hooks, NULL = use global
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
```

### workflow_defaults

Global workflow defaults applied when no project-level override exists.

```sql
CREATE TABLE workflow_defaults (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- enforces single row
    instructions TEXT NOT NULL DEFAULT '',
    hooks TEXT DEFAULT NULL,                -- JSON lifecycle hooks
    updated_at TEXT NOT NULL
)
```

### session_tasks

Structured task tracking for sessions (used by `TaskCreate`/`TaskUpdate` tools).

```sql
CREATE TABLE session_tasks (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'medium',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
)
```

`ON DELETE CASCADE` removes tasks automatically when the parent session is deleted.

### audit_log

Event log for security and debugging.

```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    session_id TEXT,
    user_id TEXT,
    details TEXT
)
```

Recorded event types: `session_created`, `auth_attempted`, `auth_succeeded`, `auth_failed`, `session_active`, `session_ended`, `session_errored`, `session_stopped`, `spawn_token_consumed`, `spawn_token_rejected`.

### schema_version

```sql
CREATE TABLE schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- single row
    version INTEGER NOT NULL
)
```

## Migration System

`sessions/migrations.py` is the single source of truth for all schema changes. No DDL is duplicated — post-v1 schema changes exist only as migration functions.

**How migrations run:**

1. `_connect()` creates the v1 baseline tables and stamps `schema_version` as v1.
2. `run_migrations()` is called at the end of every `_connect()`.
3. If `current_version < CURRENT_SCHEMA_VERSION`, each pending migration runs in sequence inside a `BEGIN IMMEDIATE` transaction.
4. The version row is updated atomically with the migration.

`BEGIN IMMEDIATE` prevents concurrent migration races when both the daemon and CLI connect simultaneously.

**Migration history:**

| From → To | Change |
|-----------|--------|
| 1 → 2 | Added `parent_session_id`, `authenticated_user_id` to sessions |
| 2 → 3 | Created `workflow_defaults` table |
| 3 → 4 | Added partial unique index on active session names |
| 4 → 5 | Added `canvas_id`, `canvas_markdown` to sessions |
| 5 → 6 | Added index on `parent_session_id` |
| 6 → 7 | Added `context_pct` to sessions |
| 7 → 8 | Created `projects` table, added `project_id` to sessions |
| 8 → 9 | Added unique index on `channel_prefix` in projects |
| 9 → 10 | Created `channels` table, added `effort` to sessions, migrated canvas data |
| 10 → 11 | Created `session_tasks` table |
| 11 → 12 | Added `hooks` column to `workflow_defaults` and `projects` |

## Adding a Migration

1. Write a new `_migrate_N_to_N+1(db)` async function in `sessions/migrations.py`.
2. Add it to `_MIGRATIONS[N]`.
3. Increment `CURRENT_SCHEMA_VERSION` to `N+1`.
4. Use `contextlib.suppress(sqlite3.OperationalError)` or try/except for `ALTER TABLE ADD COLUMN` (SQLite lacks `IF NOT EXISTS` for column additions).
5. Wrap destructive operations (DROP, data migrations) in a check for existing data first.
6. Do **not** modify any existing migration function — migrations are run exactly once per database.

Example:

```python
async def _migrate_12_to_13(db: aiosqlite.Connection) -> None:
    """Add my_new_column to sessions table."""
    with contextlib.suppress(sqlite3.OperationalError):
        await db.execute("ALTER TABLE sessions ADD COLUMN my_new_column TEXT")

_MIGRATIONS: dict[int, Any] = {
    # ... existing entries ...
    12: _migrate_12_to_13,
}

CURRENT_SCHEMA_VERSION = 13
```

## Database Commands

| Command | Description |
|---------|-------------|
| `summon db status` | Show schema version, integrity check result, and row counts per table. Migrations apply automatically on connect. |
| `summon db reset --yes` | Delete and recreate the registry database. All session history is lost. |
| `summon db vacuum` | Run `VACUUM` to compact the database and recheck integrity. |
| `summon db purge --older-than N --yes` | Delete completed/errored sessions, audit logs, and expired tokens older than N days (default: 30). |
