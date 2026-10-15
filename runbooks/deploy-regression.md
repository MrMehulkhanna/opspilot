---
title: Errors after a deployment
service:
---
Symptoms: errors begin within minutes of a release, "NullPointerException", "KeyError",
"500 internal server error", new error messages never seen before.

1. Check the deploy log: what changed and when, and whether the error start time matches.
2. Compare error rates between old and new versions if a canary is running.
3. Roll back first, investigate second, when customer impact is high.
4. Add a test that reproduces the failure before re-deploying the fix.
