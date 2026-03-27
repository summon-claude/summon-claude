# Concepts

Understand how summon-claude works — from high-level architecture to the threading model that organizes Slack conversations.

<div class="grid cards" markdown>

-   :material-sitemap: **[Overview](overview.md)**

    High-level architecture and component diagram.

-   :material-message-text: **[Threading & Streaming](threading.md)**

    How Slack conversations are organized into turns and threads.

-   :material-server: **[Daemon](daemon.md)**

    The background process that manages sessions.

-   :material-slack: **[Slack Integration](slack-integration.md)**

    How events flow between Slack and Claude.

-   :material-database: **[Database](database.md)**

    Session registry and schema migrations.

-   :material-lock: **[Security](security.md)**

    Authentication, authorization, and secret handling.

-   :material-chart-donut: **[Context Management](context.md)**

    Compaction, overflow recovery, and context tracking.

</div>

!!! tip "Suggested reading order"
    Start with the **[Overview](overview.md)** for the big picture, then explore topics that interest you. **[Threading & Streaming](threading.md)** is especially useful for understanding how Slack conversations are organized.
