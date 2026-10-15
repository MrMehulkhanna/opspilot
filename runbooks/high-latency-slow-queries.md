---
title: High latency from slow database queries
service: search
---
Symptoms: "slow query", "statement timeout", "query canceled", p95 latency rising, CPU high on the
database.

1. List the slowest queries (pg_stat_statements) and compare with the previous day.
2. Run EXPLAIN on the top query and look for sequential scans on large tables.
3. Check for a missing index after a recent migration and for table bloat.
4. Add a covering index or roll back the change that introduced the query.
