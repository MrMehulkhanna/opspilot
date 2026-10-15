---
title: Payment gateway timeouts
service: payments-api
---
Symptoms: "gateway timeout", "upstream timed out", "read timeout" from the payment provider,
checkout failures, rising retry counts.

1. Check the provider's public status page and the provider latency dashboard.
2. Confirm the timeout is upstream: our own CPU, memory and thread pools should look normal.
3. Make sure retries use backoff and the retry budget is not amplifying load.
4. If the provider is degraded, enable the fallback provider through the feature flag.
5. Post an update in the incident channel every 30 minutes while customers are affected.
