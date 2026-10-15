---
title: Message queue backlog growing
service: notifications
---
Symptoms: "queue depth", "consumer lag", "message processing timeout", delayed notifications.

1. Check consumer count and whether consumers are crashing or stuck on a poison message.
2. Move poison messages to the dead-letter queue after capturing one for debugging.
3. Scale consumers horizontally if processing is healthy but slow.
4. Confirm downstream dependencies used by consumers are healthy.
