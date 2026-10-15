---
title: Disk full on application hosts
service:
---
Symptoms: "no space left on device", "disk full", write failures, log shipping stops.

1. Find the full mount with df -h and the largest directories with du.
2. Rotate or compress application logs; check that logrotate is running.
3. Clear old build artifacts and temp files; never delete database data files.
4. Expand the volume if usage grows steadily, and add a disk usage alert at 80 percent.
