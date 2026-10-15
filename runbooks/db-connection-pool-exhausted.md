---
title: Database connection pool exhausted
service: orders-db
---
Symptoms: "connection pool exhausted", "too many connections", "timeout acquiring connection",
requests hang then fail with 503.

1. Check active connections on the database (pg_stat_activity) grouped by application and state.
2. Look for long-running or idle-in-transaction sessions; terminate obvious leaks.
3. Compare current traffic to normal; a traffic surge needs more replicas, not a bigger pool.
4. If a recent deploy changed query patterns, roll it back.
5. Only raise the pool size if the database has headroom (max_connections, CPU).
Escalate to the DBA on-call if the database itself is saturated.
