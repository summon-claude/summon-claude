# Database

summon-claude uses a single SQLite database (`registry.db`) as the session registry. It is visible to both the daemon process and the CLI, providing cross-process session state without a separate database server.

## SQLite Configuration

The registry opens with these pragmas on every connection (`_connect()` in `sessions/registry.py`):

```
PRAGMA journal_mode=WAL;          -- WAL for concurrent daemon + CLI access
PRAGMA busy_timeout=5000;         -- wait up to 5s on locks before failing
PRAGMA synchronous=NORMAL;        -- durable but faster than FULL
PRAGMA journal_size_limit=67108864; -- cap WAL file at 64 MB
PRAGMA foreign_keys=ON;           -- enforce FK constraints (required for CASCADE)
```

WAL (Write-Ahead Logging) mode allows concurrent readers even while a write transaction is in progress. The daemon and CLI can both read session state without blocking each other.

PRAGMA foreign_keys and transactions

`PRAGMA foreign_keys` cannot be changed inside an open transaction — SQLite silently ignores it. This pragma is set before any `BEGIN` in `_connect()`. Migrations that need to temporarily violate FK constraints must run before this pragma or use a separate connection.

## Database File Location

```
$XDG_DATA_HOME/summon/registry.db   # if XDG_DATA_HOME is set
~/.local/share/summon/registry.db   # default on most systems
~/.summon/registry.db               # fallback / legacy location
```

Use `summon config path` or `summon db status` to see the active path. The database file is restricted to mode `0600` (owner-only) on creation.

## Schema

```
14
```

(`CURRENT_SCHEMA_VERSION` in `sessions/migrations.py`)

### sessions

The primary session tracking table.

```
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    status TEXT NOT NULL,
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
    error_message TEXT
, parent_session_id TEXT, authenticated_user_id TEXT, context_pct REAL, project_id TEXT, effort TEXT)
```

### channels

Normalized channel data (one row per Slack channel, independent of session lifecycle).

```
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

```
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

```
CREATE TABLE spawn_tokens (
    token TEXT PRIMARY KEY,
    parent_session_id TEXT,
    parent_channel_id TEXT,
    target_user_id TEXT NOT NULL,
    cwd TEXT NOT NULL,
    spawn_source TEXT NOT NULL DEFAULT 'session',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0
)
```

### projects

Project configuration (PM agent multi-session groups).

```
CREATE TABLE "projects" (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            directory TEXT NOT NULL,
            channel_prefix TEXT NOT NULL,
            pm_channel_id TEXT,
            workflow_instructions TEXT DEFAULT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            hooks TEXT DEFAULT NULL
        )
```

### workflow_defaults

Global workflow defaults applied when no project-level override exists.

```
CREATE TABLE workflow_defaults (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            instructions TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        , hooks TEXT DEFAULT NULL)
```

### session_tasks

Structured task tracking for sessions (used by `TaskCreate`/`TaskUpdate` tools).

```
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

```
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

```
CREATE TABLE schema_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
)
```

## Migration System

`sessions/migrations.py` is the single source of truth for all schema changes. No DDL is duplicated — post-v1 schema changes exist only as migration functions.

**How migrations run:**

1. `_connect()` creates the v1 baseline tables and stamps `schema_version` as v1.
1. `run_migrations()` is called at the end of every `_connect()`.
1. If `current_version < CURRENT_SCHEMA_VERSION`, each pending migration runs in sequence inside a `BEGIN IMMEDIATE` transaction.
1. The version row is updated atomically with the migration.

`BEGIN IMMEDIATE` prevents concurrent migration races when both the daemon and CLI connect simultaneously.

**Migration history:**

| From → To | Change |
| --------- | ------ |
|           |        |

```
| 0 → 1 | Baseline (no-op) |
| 1 → 2 | Add parent_session_id and authenticated_user_id to sessions table. |
| 2 → 3 | Create workflow_defaults table. |
| 3 → 4 | Add partial unique index on active session names. |
| 4 → 5 | Add canvas_id and canvas_markdown to sessions table. |
| 5 → 6 | Add index on parent_session_id for list_children queries. |
| 6 → 7 | Add context_pct column for tracking context window usage. |
| 7 → 8 | Create projects table and add project_id column to sessions table. |
| 8 → 9 | Add unique index on channel_prefix in projects table. |
| 9 → 10 | Create channels table, add effort column, migrate canvas data, drop redundant columns. |
| 10 → 11 | Create session_tasks table for structured task tracking. |
| 11 → 12 | Add hooks column to workflow_defaults and projects tables. |
| 12 → 13 | Add index on authenticated_user_id + status for channel scoping queries. |
| 13 → 14 | Make projects.workflow_instructions nullable (NULL = use global, '' = explicit clear). |

Current schema version: **14**
```

See [Contributing — Database Migrations](https://summon-claude.github.io/summon-claude/development/contributing/#database-migrations) for instructions on writing new migrations.

## Database Commands

| Command                                | Description                                                                                                       |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `summon db status`                     | Show schema version, integrity check result, and row counts per table. Migrations apply automatically on connect. |
| `summon reset data`                    | Delete and recreate the registry database. All session history is lost.                                           |
| `summon db vacuum`                     | Run `VACUUM` to compact the database and recheck integrity.                                                       |
| `summon db purge --older-than N --yes` | Delete completed/errored sessions, audit logs, and expired tokens older than N days (default: 30).                |
