---
title: DNS resolution errors
service:
---
Symptoms: "name or service not known", "could not resolve host", "NXDOMAIN", "temporary failure in
name resolution", errors calling internal services by hostname.

1. Resolve the failing hostname from an affected host and from a healthy one.
2. Check recent DNS record or service discovery changes.
3. Check resolver health and whether the resolver is rate limiting.
4. Restart the local DNS cache on affected hosts if only some hosts fail.
