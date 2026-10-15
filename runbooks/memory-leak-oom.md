---
title: Out of memory and suspected memory leak
service:
---
Symptoms: "OutOfMemoryError", "killed process", "OOMKilled", containers restarting in a loop,
latency rising steadily before a crash.

1. Confirm OOM kills in container events or the kernel log.
2. Compare memory usage over the last few deploys to find when growth started.
3. Restart affected instances to restore service, then capture a heap profile from one.
4. Roll back the release that introduced the growth if one is identified.
