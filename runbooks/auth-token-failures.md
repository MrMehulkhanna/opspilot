---
title: Authentication and token validation failures
service: auth
---
Symptoms: "invalid token", "signature verification failed", "jwt expired", spikes of 401 responses.

1. Check whether signing keys were rotated recently and every service has the new public key.
2. Verify system clocks are in sync (NTP); skew makes valid tokens look expired.
3. Check the identity provider status and the token endpoint latency.
4. If a key rotation caused it, re-publish the previous key alongside the new one.
